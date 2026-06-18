"""Skill source abstraction — local disk or GitHub repo as single source of truth.

When ``SKILLS_SOURCE=local`` (default), skills are read from the local
``SKILLS_ROOT`` (image-baked or mounted). When ``SKILLS_SOURCE=github``, the
GitHub repository is the single source of truth: SKILL.md files and product
manifests are fetched at runtime via the GitHub contents API, with a short TTL
cache. Adding or editing a skill in the repo takes effect on the next run (after
the TTL), with no rebuild or redeploy.

Both modes expose the same two operations:
  - read_text(path): return the text of a skill file (relative to the skills root)
  - list_dir(path):   return the file names under a skills subdirectory

GitHub auth reuses the same PAT / GitHub App credentials as the rest of the
pipeline. If GitHub is unreachable, read/list raise and the caller decides how
to degrade (the loader surfaces a clear error; the registry fails open to empty).
"""
from __future__ import annotations

import base64
import threading
import time
from pathlib import Path
from typing import Any

from .config import get_config
from .logging_setup import get_logger

logger = get_logger(__name__)


class _TTL:
    def __init__(self) -> None:
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str, ttl: int) -> Any | None:
        if ttl <= 0:
            return None
        with self._lock:
            hit = self._store.get(key)
            if not hit:
                return None
            ts, val = hit
            if time.time() - ts >= ttl:
                self._store.pop(key, None)
                return None
            return val

    def set(self, key: str, val: Any) -> None:
        with self._lock:
            self._store[key] = (time.time(), val)


_cache = _TTL()


def _is_github() -> bool:
    return get_config().pipeline.skills_source.strip().lower() == "github"


# ── Public API ─────────────────────────────────────────────────────────────
def read_text(rel_path: str) -> str:
    """Return the text of a skill file given a path relative to the skills root.

    Example rel_path: "skills/terraform/SKILL.md" or "terraform/SKILL.md".
    """
    if _is_github():
        return _github_read(_norm(rel_path))
    return _local_read(rel_path)


def list_dir(rel_dir: str) -> list[str]:
    """Return the file names directly under a skills subdirectory."""
    if _is_github():
        return _github_list(_norm(rel_dir))
    return _local_list(rel_dir)


def describe_source() -> str:
    cfg = get_config().pipeline
    if _is_github():
        owner, name, ref, path = _gh_coords()
        return f"github://{owner}/{name}@{ref or 'default'}/{path}"
    return f"local://{Path(cfg.skills_root).resolve()}"


# ── Local implementation ───────────────────────────────────────────────────
def _local_root() -> Path:
    return Path(get_config().pipeline.skills_root)


def _local_resolve(rel_path: str) -> Path:
    p = Path(rel_path)
    if p.is_absolute():
        return p
    # Accept both "skills/x" and "x" relative to skills_root.
    if rel_path.startswith("skills/"):
        return _local_root().parent / rel_path
    return _local_root() / rel_path


def _local_read(rel_path: str) -> str:
    resolved = _local_resolve(rel_path)
    if not resolved.exists():
        raise FileNotFoundError(f"Skill file not found: {resolved}")
    return resolved.read_text(encoding="utf-8")


def _local_list(rel_dir: str) -> list[str]:
    resolved = _local_resolve(rel_dir)
    if not resolved.exists():
        return []
    return sorted(p.name for p in resolved.iterdir() if p.is_file())


# ── GitHub implementation ──────────────────────────────────────────────────
def _norm(rel_path: str) -> str:
    """Strip a leading 'skills/' so paths are relative to the skills root."""
    return rel_path[len("skills/"):] if rel_path.startswith("skills/") else rel_path


def _gh_coords() -> tuple[str, str, str, str]:
    cfg = get_config()
    owner = cfg.pipeline.skills_repo_owner or cfg.github.repo_owner
    name = cfg.pipeline.skills_repo_name or cfg.github.repo_name
    ref = cfg.pipeline.skills_repo_ref or cfg.github.default_branch
    base = cfg.pipeline.skills_repo_path.strip("/")
    return owner, name, ref, base


def _gh_request(path: str, params: dict[str, str]) -> Any:
    import requests

    from .github_client import GitHubClient

    cfg = get_config()
    client = GitHubClient()
    url = f"{cfg.github.api_base.rstrip('/')}/{path.lstrip('/')}"
    headers = {"Accept": "application/vnd.github+json", **client._auth_header()}
    resp = requests.get(url, headers=headers, params=params,
                        timeout=cfg.github.timeout_seconds)
    resp.raise_for_status()
    return resp.json()


def _github_read(rel_path: str) -> str:
    owner, name, ref, base = _gh_coords()
    full = f"{base}/{rel_path}".strip("/")
    key = f"read:{owner}/{name}@{ref}:{full}"
    ttl = get_config().pipeline.skills_cache_ttl
    cached = _cache.get(key, ttl)
    if cached is not None:
        return cached
    data = _gh_request(f"repos/{owner}/{name}/contents/{full}", {"ref": ref})
    content = base64.b64decode(data["content"]).decode("utf-8") if data.get("content") else ""
    _cache.set(key, content)
    logger.info("Fetched skill from GitHub: %s", full)
    return content


def _github_list(rel_dir: str) -> list[str]:
    owner, name, ref, base = _gh_coords()
    full = f"{base}/{rel_dir}".strip("/")
    key = f"list:{owner}/{name}@{ref}:{full}"
    ttl = get_config().pipeline.skills_cache_ttl
    cached = _cache.get(key, ttl)
    if cached is not None:
        return cached
    data = _gh_request(f"repos/{owner}/{name}/contents/{full}", {"ref": ref})
    names = sorted(item["name"] for item in data if item.get("type") == "file")
    _cache.set(key, names)
    return names
