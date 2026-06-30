"""GitHub client supporting both PAT and GitHub App authentication.

Works against github.com (https://api.github.com) and GitHub Enterprise Server
(https://<host>/api/v3). Auth mode is selected by GITHUB_AUTH_MODE:

    pat  -> static Personal Access Token in the Authorization header
    app  -> GitHub App: sign a short-lived JWT with the app private key, exchange
            it for an installation access token, refresh on expiry

Used by DecideAgent (read files) and PublishAgent (branch, commit, PR, comment).
"""
from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from typing import Any

import requests

from .config import GitHubConfig, get_config
from .logging_setup import get_logger

logger = get_logger(__name__)


class GitHubAuthError(RuntimeError):
    """Raised when GitHub authentication cannot be established."""


@dataclass
class _InstallationToken:
    token: str
    expires_at: float  # epoch seconds


class GitHubClient:
    def __init__(self, cfg: GitHubConfig | None = None) -> None:
        self.cfg = cfg or get_config().github
        self._inst_token: _InstallationToken | None = None
        self._session = requests.Session()

    # ── Auth ───────────────────────────────────────────────────────────────
    def _auth_header(self) -> dict[str, str]:
        if self.cfg.auth_mode == "pat":
            if not self.cfg.pat:
                raise GitHubAuthError("GITHUB_PAT is not set but auth mode is 'pat'")
            return {"Authorization": f"Bearer {self.cfg.pat}"}
        if self.cfg.auth_mode == "app":
            return {"Authorization": f"Bearer {self._installation_token()}"}
        raise GitHubAuthError(f"Unknown GITHUB_AUTH_MODE: {self.cfg.auth_mode}")

    def _app_jwt(self) -> str:
        """Build a short-lived RS256 JWT signed with the App private key."""
        try:
            import jwt  # PyJWT
        except ImportError as exc:  # pragma: no cover
            raise GitHubAuthError("PyJWT is required for GitHub App auth") from exc

        with open(self.cfg.app_private_key_path, "rb") as fh:
            private_key = fh.read()

        now = int(time.time())
        payload = {
            "iat": now - 60,
            "exp": now + 9 * 60,  # max 10 min; use 9 for clock skew
            "iss": self.cfg.app_id,
        }
        return jwt.encode(payload, private_key, algorithm="RS256")

    def _installation_token(self) -> str:
        now = time.time()
        if self._inst_token and self._inst_token.expires_at - 60 > now:
            return self._inst_token.token

        jwt_token = self._app_jwt()
        url = (
            f"{self.cfg.api_base.rstrip('/')}/app/installations/"
            f"{self.cfg.app_installation_id}/access_tokens"
        )
        resp = self._session.post(
            url,
            headers={
                "Authorization": f"Bearer {jwt_token}",
                "Accept": "application/vnd.github+json",
            },
            timeout=self.cfg.timeout_seconds,
        )
        resp.raise_for_status()
        data = resp.json()
        # token valid 1h; parse expiry, store conservatively
        expires_at = now + 55 * 60
        self._inst_token = _InstallationToken(token=data["token"], expires_at=expires_at)
        logger.info("Obtained GitHub App installation token (mode=app)")
        return self._inst_token.token

    # ── Low-level request ──────────────────────────────────────────────────
    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        url = f"{self.cfg.api_base.rstrip('/')}/{path.lstrip('/')}"
        headers = {"Accept": "application/vnd.github+json", **self._auth_header()}
        headers.update(kwargs.pop("headers", {}))
        resp = self._session.request(
            method, url, headers=headers, timeout=self.cfg.timeout_seconds, **kwargs
        )
        resp.raise_for_status()
        return resp

    @property
    def _repo_path(self) -> str:
        return f"repos/{self.cfg.repo_owner}/{self.cfg.repo_name}"

    # ── Operations ─────────────────────────────────────────────────────────
    def get_file(self, file_path: str, ref: str | None = None) -> dict[str, Any]:
        """Return {path, content, sha} for a file in the repo."""
        params = {"ref": ref} if ref else {}
        resp = self._request("GET", f"{self._repo_path}/contents/{file_path}", params=params)
        data = resp.json()
        content = base64.b64decode(data["content"]).decode("utf-8") if data.get("content") else ""
        return {"path": data["path"], "content": content, "sha": data["sha"]}

    def get_default_branch_sha(self) -> str:
        resp = self._request("GET", f"{self._repo_path}/git/ref/heads/{self.cfg.default_branch}")
        return resp.json()["object"]["sha"]

    def create_branch(self, branch: str, from_sha: str | None = None) -> dict[str, Any]:
        sha = from_sha or self.get_default_branch_sha()
        resp = self._request(
            "POST",
            f"{self._repo_path}/git/refs",
            json={"ref": f"refs/heads/{branch}", "sha": sha},
        )
        return resp.json()

    def create_or_update_file(
        self,
        *,
        file_path: str,
        content: str,
        message: str,
        branch: str,
        sha: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "message": message,
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "branch": branch,
        }
        if sha:
            payload["sha"] = sha
        resp = self._request(
            "PUT", f"{self._repo_path}/contents/{file_path}", json=payload
        )
        return resp.json()

    def list_pull_requests(self, *, head: str | None = None, state: str = "open") -> list[dict[str, Any]]:
        params: dict[str, str] = {"state": state}
        if head:
            params["head"] = f"{self.cfg.repo_owner}:{head}"
        resp = self._request("GET", f"{self._repo_path}/pulls", params=params)
        return resp.json()

    def create_pull_request(
        self, *, title: str, body: str, head: str, base: str | None = None
    ) -> dict[str, Any]:
        resp = self._request(
            "POST",
            f"{self._repo_path}/pulls",
            json={
                "title": title,
                "body": body,
                "head": head,
                "base": base or self.cfg.default_branch,
            },
        )
        return resp.json()

    def comment_on_issue(self, number: int, body: str) -> dict[str, Any]:
        resp = self._request(
            "POST", f"{self._repo_path}/issues/{number}/comments", json={"body": body}
        )
        return resp.json()

    def probe(self) -> bool:
        try:
            self._request("GET", self._repo_path)
            return True
        except Exception as exc:
            logger.error("GitHub probe failed: %s", exc)
            return False
