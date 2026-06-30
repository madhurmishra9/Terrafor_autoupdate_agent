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
CLASSIFY_RESULT = "classify_result"
ANALYZE_RESULT = "analyze_result"
DECIDE_RESULT = "decide_result"
GENERATE_RESULT = "generate_result"
TICKET_RESULT = "ticket_result"
PUBLISH_RESULT = "publish_result"
PIPELINE_MODE = "pipeline_mode"
PIPELINE_HALTED = "pipeline_halted"

ALL_KEYS = [
    RELEASE_NOTES,
    CLASSIFY_RESULT,
    ANALYZE_RESULT,
    DECIDE_RESULT,
    GENERATE_RESULT,
    TICKET_RESULT,
    PUBLISH_RESULT,
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


def make_stop_guard(output_key: str) -> Callable[..., Any]:
    """Build a before-agent callback that short-circuits when halted.

    When pipeline_halted is set, the guard stamps the agent's output_key with the
    STOP sentinel and signals ADK to skip the LLM call by returning a non-None
    response content. When not halted, it returns None so the agent runs normally.
    """

    def _guard(callback_context: Any) -> Any | None:
        state = callback_context.state
        if is_halted(state):
            reason = state.get(PIPELINE_HALTED, {}).get("reason", "unknown")
            logger.info(
                "stop_guard: halting before agent (output_key=%s, reason=%s)",
                output_key,
                reason,
            )
            state[output_key] = STOP_SENTINEL
            # Returning Content tells ADK to skip the model call for this agent.
            try:
                from google.genai import types  # type: ignore

                return types.Content(
                    role="model",
                    parts=[types.Part(text=STOP_SENTINEL)],
                )
            except Exception:  # pragma: no cover - ADK/genai not present in unit env
                return STOP_SENTINEL
        return None

    return _guard


def chain_guards(*guards: Callable[..., Any]) -> Callable[..., Any]:
    """Compose multiple before-callbacks. First non-None short-circuits."""

    def _chained(callback_context: Any) -> Any | None:
        for guard in guards:
            result = guard(callback_context)
            if result is not None:
                return result
        return None

    return _chained
