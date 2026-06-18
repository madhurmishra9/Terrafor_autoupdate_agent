"""Azure AI Agent Service runtime (managed orchestration path).

Used when ORCHESTRATION_MODE=connected. Creates one Azure AI agent per pipeline
stage (instruction = the stage's SKILL.md, function tools = the stage's tools),
then drives them sequentially over a shared thread, passing each agent's output
as context to the next. State + stop-guard semantics mirror the runnable path.

Requires an Azure AI project (AZURE_AI_PROJECT_ENDPOINT). The function tools wrap
the same shared tool registry, so behaviour is identical to the SDK chat path.
"""
from __future__ import annotations

import json
from typing import Any

from ..common.config import get_config
from ..common.logging_setup import get_logger
from ..common.state import STOP_SENTINEL, clear_pipeline_state, halt_pipeline, is_halted
from ..skills_loader import load_skill
from . import tool_registry
from .stages import STAGES

logger = get_logger(__name__)


def run_pipeline_via_agent_service(prompt: str) -> dict[str, Any]:
    """Drive the 7 stages using the Azure AI Agent Service SDK."""
    from azure.ai.agents import AgentsClient
    from azure.ai.agents.models import FunctionTool
    from azure.identity import DefaultAzureCredential

    cfg = get_config()
    if not cfg.agents.project_endpoint:
        raise RuntimeError(
            "AZURE_AI_PROJECT_ENDPOINT is not set. Provision an Azure AI project "
            "before using ORCHESTRATION_MODE=connected."
        )

    client = AgentsClient(endpoint=cfg.agents.project_endpoint,
                          credential=DefaultAzureCredential())
    state: dict[str, Any] = {}
    clear_pipeline_state(state)
    state["_prompt"] = prompt

    thread = client.threads.create()

    for spec in STAGES:
        if is_halted(state):
            state[spec.output_key] = STOP_SENTINEL
            continue

        # Wrap the stage's tools as Azure AI function tools.
        functions = {tool_registry._CATALOGUE[t] for t in spec.tools
                     if t in tool_registry._CATALOGUE}
        function_tool = FunctionTool(functions=functions)

        agent = client.create_agent(
            model=_deployment_for(spec),
            name=spec.name,
            instructions=load_skill(spec.skill),
            tools=function_tool.definitions,
        )
        context = {k: v for k, v in state.items() if not k.startswith("_")}
        client.messages.create(
            thread_id=thread.id, role="user",
            content=f"Pipeline state: {json.dumps(context, default=str)[:12000]}\n"
                    "Perform your stage and return ONLY your output-contract JSON.",
        )
        run = client.runs.create_and_process(thread_id=thread.id, agent_id=agent.id)
        if run.status == "failed":
            halt_pipeline(state, f"{spec.name}_run_failed")
            state[spec.output_key] = STOP_SENTINEL
            continue
        state[spec.output_key] = _last_text(client, thread.id)
        client.delete_agent(agent.id)

    return state


def _deployment_for(spec: Any) -> str:
    cfg = get_config().openai
    return cfg.deployment_fast if spec.model_tier == "fast" else cfg.deployment


def _last_text(client: Any, thread_id: str) -> Any:
    msgs = client.messages.list(thread_id=thread_id)
    for m in msgs:
        if m.role == "assistant":
            text = "".join(c.text.value for c in m.content if hasattr(c, "text"))
            try:
                return json.loads(text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip())
            except json.JSONDecodeError:
                return text
    return ""
