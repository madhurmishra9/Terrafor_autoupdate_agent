"""Single source of truth for the classification -> issue type -> PR prefix map.

JiraAgent owns this mapping. PRAgent reads the resolved values from jira_result
and must not re-derive them, preventing title/issue-type drift.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ClassMapping:
    classification: str  # feat | fix | chore
    jira_issue_type: str  # Story | Bug | Task
    pr_prefix: str  # feat: | fix: | chore:


_FEAT = ClassMapping("feat", "Story", "feat:")
_FIX = ClassMapping("fix", "Bug", "fix:")
_CHORE = ClassMapping("chore", "Task", "chore:")

_BY_CLASS = {"feat": _FEAT, "fix": _FIX, "chore": _CHORE}


def resolve(classification: str) -> ClassMapping:
    """Map a raw classification to its Jira/PR mapping. Defaults to chore."""
    return _BY_CLASS.get(classification.strip().lower(), _CHORE)


def classify_change(change_type: str) -> str:
    """Derive feat/fix/chore from a change-analysis change_type string."""
    ct = change_type.strip().lower()
    if ct in {"new_resource", "new_argument", "feature", "new"}:
        return "feat"
    if ct in {"removed_argument", "deprecation", "security", "fix", "breaking"}:
        return "fix"
    return "chore"
