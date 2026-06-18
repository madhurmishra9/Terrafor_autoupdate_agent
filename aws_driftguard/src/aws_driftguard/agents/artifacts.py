"""Filesystem-backed artifact store shared by Terraform and PR agents.

DecisionMaker saves fetched module files; Terraform loads them, generates
patches, and saves the patched content; PRAgent loads the patched content to
push to GitHub. Artifacts live under a per-run directory.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ..common.config import get_config
from ..common.logging_setup import get_logger

logger = get_logger(__name__)


def _root() -> Path:
    base = os.getenv("ARTIFACT_DIR", "/tmp/aws-driftguard-artifacts")
    p = Path(base)
    p.mkdir(parents=True, exist_ok=True)
    return p


def save_artifact(name: str, content: str, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """Save an artifact (a terraform file's content) under the run directory."""
    path = _root() / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if meta:
        (path.with_suffix(path.suffix + ".meta.json")).write_text(
            json.dumps(meta, indent=2), encoding="utf-8"
        )
    logger.info("Saved artifact: %s (%d bytes)", name, len(content))
    return {"name": name, "bytes": len(content)}


def load_artifact(name: str) -> dict[str, Any]:
    """Load an artifact's content by name."""
    path = _root() / name
    if not path.exists():
        return {"name": name, "exists": False, "content": ""}
    return {"name": name, "exists": True, "content": path.read_text(encoding="utf-8")}


def list_artifacts() -> dict[str, Any]:
    """List all artifact names under the run directory (excluding meta files)."""
    root = _root()
    names = [
        str(p.relative_to(root))
        for p in root.rglob("*")
        if p.is_file() and not p.name.endswith(".meta.json")
    ]
    return {"artifacts": names, "count": len(names)}
