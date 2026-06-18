"""Pipeline state contract: canonical session-state keys and stop-guard helpers.

This module is the single source of truth for state key names. Agents must never
hardcode key strings; they import from here. The stop-guard and halt helpers
centralise the pipeline_halted mechanism so a single flag short-circuits every
downstream agent.
"""
from __future__ import annotations

from typing import Any, Callable

from .logging_setup import get_logger

logger = get_logger(__name__)

# ── Canonical session-state keys ───────────────────────────────────────────
RELEASE_NOTES = "release_notes"
CLASSIFICATION_RESULT = "classification_result"
CHANGE_ANALYSER_RESULT = "change_analyser_result"
DECISION_MAKER_RESULT = "decision_maker_result"
TERRAFORM_RESULT = "terraform_result"
JIRA_RESULT = "jira_result"
PR_RESULT = "pr_result"
PIPELINE_MODE = "pipeline_mode"
PIPELINE_HALTED = "pipeline_halted"

ALL_KEYS = [
    RELEASE_NOTES,
    CLASSIFICATION_RESULT,
    CHANGE_ANALYSER_RESULT,
    DECISION_MAKER_RESULT,
    TERRAFORM_RESULT,
    JIRA_RESULT,
    PR_RESULT,
    PIPELINE_MODE,
    PIPELINE_HALTED,
]

# Sentinel written to an agent's output_key when the pipeline is halted.
STOP_SENTINEL = "[STOP]"

# pipeline_mode values
MODE_FULL = "full"
MODE_FETCH_ONLY = "fetch_only"


def halt_pipeline(state: dict[str, Any], reason: str) -> None:
    """Set the centralised halt flag with a reason. Idempotent."""
    if not state.get(PIPELINE_HALTED):
        logger.warning("Pipeline halted: %s", reason)
    state[PIPELINE_HALTED] = {"halted": True, "reason": reason}


def is_halted(state: dict[str, Any]) -> bool:
    flag = state.get(PIPELINE_HALTED)
    return bool(flag and flag.get("halted"))


def clear_pipeline_state(state: dict[str, Any]) -> None:
    """Clear all pipeline keys. Called by cb_before_pipeline."""
    for key in ALL_KEYS:
        state.pop(key, None)
    logger.info("Cleared %d pipeline state keys", len(ALL_KEYS))



