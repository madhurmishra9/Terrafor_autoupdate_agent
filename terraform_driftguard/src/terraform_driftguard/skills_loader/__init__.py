"""Skill loader for the skills-driven architecture.

Each agent's behavioural instructions live in skills/<name>/SKILL.md. The loader
reads them through the skill *source* abstraction (common/skills_source), which
serves files from local disk (SKILLS_SOURCE=local) or directly from the GitHub
repo at runtime (SKILLS_SOURCE=github) — making the repo the single source of
truth, so a skill change takes effect on the next run without a redeploy.

load_skill(path) reads the file and inlines any `@include: relative/path`
sub-files, enabling a SKILL.md to compose examples and schemas.
"""
from __future__ import annotations

import posixpath

from ..common import skills_source
from ..common.logging_setup import get_logger

logger = get_logger(__name__)


def load_skill(path: str) -> str:
    """Read a SKILL.md (or any skill sub-file) and return its text.

    Works identically for local and GitHub sources. `@include:` directives are
    resolved relative to the skill file's own directory.
    """
    text = skills_source.read_text(path)
    base_dir = posixpath.dirname(path)
    return _expand_includes(text, base_dir)


def _expand_includes(text: str, base_dir: str) -> str:
    out_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("@include:"):
            rel = stripped.split("@include:", 1)[1].strip()
            inc_path = posixpath.normpath(posixpath.join(base_dir, rel))
            try:
                inc_text = skills_source.read_text(inc_path)
                out_lines.append(f"\n<!-- begin include: {rel} -->")
                out_lines.append(inc_text)
                out_lines.append(f"<!-- end include: {rel} -->\n")
            except Exception:
                logger.warning("Skill include not found, skipping: %s", inc_path)
        else:
            out_lines.append(line)
    return "\n".join(out_lines)
