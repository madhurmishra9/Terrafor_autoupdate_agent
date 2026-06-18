"""Native Azure orchestrator (runnable Azure OpenAI tool-use path).

Runs the 7-stage pipeline sequentially. Each stage is a Azure OpenAI
tool-use loop: the stage's skill is the system prompt, its tools are registered,
and the model drives them until it emits a final JSON answer written to the
shared state under the stage's output_key.

A centralised `pipeline_halted` flag short-circuits downstream stages (the same
stop-guard contract as the GCP edition). Connectivity guards probe Jira / GitHub
before the stages that need them.

This path is runnable with only AWS credentials (no pre-provisioned agents).
The managed Bedrock Agents path (see deploy/bedrock-agents/) uses the same
stages + tool registry via Lambda action groups.
"""
from __future__ import annotations

import json
from typing import Any

from ..common.config import get_config
from ..common.logging_setup import get_logger
from ..common.state import (
    PIPELINE_HALTED, STOP_SENTINEL, clear_pipeline_state, halt_pipeline, is_halted,
)
from ..skills_loader import load_skill
from . import tool_registry
from .stages import STAGES, StageSpec

logger = get_logger(__name__)


def _model_for(spec: StageSpec) -> str:
    cfg = get_config().openai
    return cfg.deployment_fast if spec.model_tier == "fast" else cfg.deployment


def _run_connectivity_guard(spec: StageSpec, state: dict[str, Any]) -> bool:
    """Return True to proceed, False if a guard halted the pipeline."""
    if spec.guard == "stop+github":
        from ..common.github_client import GitHubClient

        if not GitHubClient().probe():
            halt_pipeline(state, "github_unreachable")
            return False
    if spec.guard == "stop+jira":
        from ..common.jira_client import JiraClient

        if JiraClient().probe() is None:
            halt_pipeline(state, "jira_unreachable")
            return False
    return True


def _run_stage(spec: StageSpec, state: dict[str, Any]) -> None:
    # Stop guard: if halted, stamp the output key and skip.
    if is_halted(state):
        state[spec.output_key] = STOP_SENTINEL
        logger.info("stop_guard: skipping %s (pipeline halted)", spec.name)
        return

    if not _run_connectivity_guard(spec, state):
        state[spec.output_key] = STOP_SENTINEL
        return

    from ..common.llm_azure_openai import AzureOpenAIUnavailable, chat_with_tools

    system = load_skill(spec.skill)
    # Provide the upstream state as context so the stage can read prior outputs.
    context = {k: v for k, v in state.items() if k != PIPELINE_HALTED}
    user_message = (
        "Pipeline state so far (JSON):\n"
        f"{json.dumps(context, default=str)[:12000]}\n\n"
        "Perform your stage now. Use your tools. Return ONLY the JSON your "
        "output contract specifies."
    )
    tools = tool_registry.openai_specs_for(spec.tools)

    try:
        final = chat_with_tools(
            deployment=_model_for(spec),
            system=system,
            user_message=user_message,
            tools=tools,
            tool_executor=tool_registry.dispatch,
        )
    except AzureOpenAIUnavailable as exc:
        logger.error("Azure OpenAI unavailable, halting: %s", exc)
        halt_pipeline(state, "azure_openai_unavailable")
        state[spec.output_key] = STOP_SENTINEL
        return

    state[spec.output_key] = _coerce_json(final)
    _apply_post_stage_rules(spec, state)


def _apply_post_stage_rules(spec: StageSpec, state: dict[str, Any]) -> None:
    """Honour [STOP]/[FETCH_ONLY] markers and fetch-only halting."""
    value = state.get(spec.output_key)
    text = value if isinstance(value, str) else json.dumps(value)
    if spec.name == "RequestProcessorAgent":
        if isinstance(text, str) and text.lstrip().startswith("[STOP]"):
            halt_pipeline(state, "request_processor_stop")
        elif isinstance(text, str) and "[FETCH_ONLY]" in text:
            state["pipeline_mode"] = "fetch_only"
    if spec.name == "ClassificationAgent" and state.get("pipeline_mode") == "fetch_only":
        halt_pipeline(state, "fetch_only_notes_saved")


def _coerce_json(text: str) -> Any:
    t = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        return t  # keep raw (e.g. [STOP] / [FETCH_ONLY] markers)


def run_pipeline(prompt: str) -> dict[str, Any]:
    """Execute the full 7-stage pipeline. Returns the final state."""
    state: dict[str, Any] = {}
    clear_pipeline_state(state)
    state["_prompt"] = prompt
    logger.info("Starting Azure DriftGuard pipeline (Azure OpenAI mode)")

    for spec in STAGES:
        logger.info("── stage: %s", spec.name)
        _run_stage(spec, state)

    if get_config().pipeline.capture_enabled:
        _write_eval_artifact(state)

    logger.info("Pipeline complete (halted=%s)", is_halted(state))
    return state


def _write_eval_artifact(state: dict[str, Any]) -> None:
    import os
    import time

    cfg = get_config()
    os.makedirs(cfg.pipeline.capture_dir, exist_ok=True)
    path = os.path.join(cfg.pipeline.capture_dir, f"run-{int(time.time())}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(state, fh, default=str, indent=2)
    logger.info("Wrote eval artifact: %s", path)
