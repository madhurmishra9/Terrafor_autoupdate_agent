"""Jira connectivity with a strict 3-tier fallback chain.

Priority order (per the architecture):
    Tier 1  jira Python library   (default, in-process, structured)
    Tier 2  acli (Atlassian CLI)  (subprocess fallback)
    Tier 3  Jira REST API v3      (requests, last resort)

Every public method attempts tier 1, falls back to tier 2 on failure, then
tier 3, and raises JiraUnreachable only if all three fail. The tier that
succeeded is recorded on the result so downstream callers (PRAgent linkback)
reuse the same mechanism.

All rich-text inputs (description, comment body) are ADF documents because the
target is Jira Cloud api/v3.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any

import requests
from requests.auth import HTTPBasicAuth

from .config import JiraConfig, get_config
from .logging_setup import get_logger

logger = get_logger(__name__)


class JiraUnreachable(RuntimeError):
    """Raised when all three Jira connectivity tiers fail."""


@dataclass
class JiraResult:
    ok: bool
    tier: str  # "library" | "acli" | "api"
    data: dict[str, Any]


def _adf_to_text(adf: dict[str, Any]) -> str:
    """Flatten an ADF doc to plain text for tiers that don't accept ADF (acli)."""
    out: list[str] = []

    def walk(node: dict[str, Any]) -> None:
        if node.get("type") == "text":
            out.append(node.get("text", ""))
        for child in node.get("content", []) or []:
            walk(child)
        if node.get("type") in {"paragraph", "heading"}:
            out.append("\n")

    for block in adf.get("content", []) or []:
        walk(block)
    return "".join(out).strip()


class JiraClient:
    """Facade over the 3-tier Jira connectivity chain."""

    def __init__(self, cfg: JiraConfig | None = None) -> None:
        self.cfg = cfg or get_config().jira
        self._lib_client: Any = None
        self._lib_failed = False

    # ── Tier 1: jira python library ────────────────────────────────────────
    def _library(self) -> Any:
        if self._lib_client is not None:
            return self._lib_client
        if self._lib_failed:
            raise RuntimeError("jira library previously failed; skipping")
        try:
            from jira import JIRA  # type: ignore

            self._lib_client = JIRA(
                server=self.cfg.base_url,
                basic_auth=(self.cfg.email, self.cfg.api_token),
                timeout=self.cfg.timeout_seconds,
            )
            return self._lib_client
        except Exception as exc:
            self._lib_failed = True
            logger.warning("Jira tier 1 (library) init failed: %s", exc)
            raise

    # ── Tier 2: acli ───────────────────────────────────────────────────────
    def _acli(self, args: list[str]) -> str:
        binary = shutil.which(self.cfg.acli_path) or self.cfg.acli_path
        cmd = [binary, *args]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=self.cfg.timeout_seconds,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"acli failed (rc={proc.returncode}): {proc.stderr.strip()}")
        return proc.stdout.strip()

    # ── Tier 3: REST API v3 ────────────────────────────────────────────────
    def _api(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.cfg.base_url.rstrip('/')}/rest/api/{self.cfg.api_version}/{path.lstrip('/')}"
        resp = requests.request(
            method,
            url,
            json=payload,
            auth=HTTPBasicAuth(self.cfg.email, self.cfg.api_token),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=self.cfg.timeout_seconds,
        )
        resp.raise_for_status()
        if resp.content:
            return resp.json()
        return {}

    # ── Public operations ──────────────────────────────────────────────────
    def search_issue(self, jql: str) -> JiraResult:
        """Return the first matching issue (or empty) using the highest tier."""
        # Tier 1
        try:
            client = self._library()
            issues = client.search_issues(jql, maxResults=1)
            if issues:
                issue = issues[0]
                return JiraResult(True, "library", {
                    "key": issue.key,
                    "url": f"{self.cfg.base_url.rstrip('/')}/browse/{issue.key}",
                })
            return JiraResult(True, "library", {})
        except Exception as exc:
            logger.info("search tier 1 failed, trying acli: %s", exc)

        # Tier 2
        try:
            out = self._acli(["jira", "search", "--jql", jql, "--limit", "1", "--json"])
            data = json.loads(out) if out else {}
            issues = data.get("issues") or data if isinstance(data, list) else data.get("issues", [])
            if issues:
                key = issues[0].get("key")
                return JiraResult(True, "acli", {
                    "key": key,
                    "url": f"{self.cfg.base_url.rstrip('/')}/browse/{key}",
                })
            return JiraResult(True, "acli", {})
        except Exception as exc:
            logger.info("search tier 2 failed, trying api: %s", exc)

        # Tier 3
        try:
            data = self._api("GET", f"search?jql={requests.utils.quote(jql)}&maxResults=1")
            issues = data.get("issues", [])
            if issues:
                key = issues[0]["key"]
                return JiraResult(True, "api", {
                    "key": key,
                    "url": f"{self.cfg.base_url.rstrip('/')}/browse/{key}",
                })
            return JiraResult(True, "api", {})
        except Exception as exc:
            logger.error("search tier 3 (api) failed: %s", exc)
            raise JiraUnreachable("All Jira tiers failed for search_issue") from exc

    def create_issue(
        self,
        *,
        summary: str,
        description_adf: dict[str, Any],
        issue_type: str,
        labels: list[str] | None = None,
    ) -> JiraResult:
        """Create an issue. description_adf must be a valid ADF document."""
        labels = labels or []
        fields = {
            "project": {"key": self.cfg.project_key},
            "summary": summary,
            "issuetype": {"name": issue_type},
            "description": description_adf,  # ADF for api/v3
            "labels": labels,
        }

        # Tier 1
        try:
            client = self._library()
            issue = client.create_issue(fields=fields)
            return JiraResult(True, "library", {
                "key": issue.key,
                "url": f"{self.cfg.base_url.rstrip('/')}/browse/{issue.key}",
            })
        except Exception as exc:
            logger.info("create tier 1 failed, trying acli: %s", exc)

        # Tier 2 — acli takes plain text; flatten ADF
        try:
            body_text = _adf_to_text(description_adf)
            out = self._acli([
                "jira", "issue", "create",
                "--project", self.cfg.project_key,
                "--type", issue_type,
                "--summary", summary,
                "--description", body_text,
                "--label", ",".join(labels),
                "--json",
            ])
            data = json.loads(out) if out else {}
            key = data.get("key")
            return JiraResult(True, "acli", {
                "key": key,
                "url": f"{self.cfg.base_url.rstrip('/')}/browse/{key}",
            })
        except Exception as exc:
            logger.info("create tier 2 failed, trying api: %s", exc)

        # Tier 3
        try:
            data = self._api("POST", "issue", {"fields": fields})
            key = data["key"]
            return JiraResult(True, "api", {
                "key": key,
                "url": f"{self.cfg.base_url.rstrip('/')}/browse/{key}",
            })
        except Exception as exc:
            logger.error("create tier 3 (api) failed: %s", exc)
            raise JiraUnreachable("All Jira tiers failed for create_issue") from exc

    def add_comment(self, issue_key: str, body_adf: dict[str, Any]) -> JiraResult:
        """Add a comment. body_adf must be a valid ADF document."""
        # Tier 1
        try:
            client = self._library()
            client.add_comment(issue_key, body_adf)
            return JiraResult(True, "library", {"key": issue_key})
        except Exception as exc:
            logger.info("comment tier 1 failed, trying acli: %s", exc)

        # Tier 2
        try:
            body_text = _adf_to_text(body_adf)
            self._acli([
                "jira", "issue", "comment", "add",
                "--issue", issue_key,
                "--body", body_text,
            ])
            return JiraResult(True, "acli", {"key": issue_key})
        except Exception as exc:
            logger.info("comment tier 2 failed, trying api: %s", exc)

        # Tier 3
        try:
            self._api("POST", f"issue/{issue_key}/comment", {"body": body_adf})
            return JiraResult(True, "api", {"key": issue_key})
        except Exception as exc:
            logger.error("comment tier 3 (api) failed: %s", exc)
            raise JiraUnreachable("All Jira tiers failed for add_comment") from exc

    def probe(self) -> str | None:
        """Probe connectivity across all tiers. Return the first working tier."""
        try:
            self._library().myself()
            return "library"
        except Exception:
            pass
        try:
            self._acli(["jira", "me"])
            return "acli"
        except Exception:
            pass
        try:
            self._api("GET", "myself")
            return "api"
        except Exception:
            return None
