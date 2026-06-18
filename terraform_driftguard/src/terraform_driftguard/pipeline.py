"""Assemble the TerraformDriftGuardPipelineAgent SequentialAgent."""
from __future__ import annotations

from typing import Any

from .agents.callbacks import cb_after_pipeline, cb_before_pipeline
from .agents.definitions import build_agents
from .common.logging_setup import get_logger

logger = get_logger(__name__)


def build_pipeline() -> Any:
    """Build and return the root SequentialAgent."""
    from google.adk.agents import SequentialAgent  # type: ignore

    agents = build_agents()
    pipeline = SequentialAgent(
        name="TerraformDriftGuardPipelineAgent",
        sub_agents=agents,
        before_agent_callback=cb_before_pipeline,
        after_agent_callback=cb_after_pipeline,
    )
    logger.info("Built TerraformDriftGuardPipelineAgent with %d sub-agents", len(agents))
    return pipeline


# ADK entrypoint discovery: `root_agent` is conventionally imported by adk run.
def get_root_agent() -> Any:
    return build_pipeline()
