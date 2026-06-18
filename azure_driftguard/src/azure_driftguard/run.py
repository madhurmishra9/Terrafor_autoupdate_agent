"""Process entrypoint for Azure DriftGuard (native Azure orchestration).

ORCHESTRATION_MODE selects the runtime:
  - "sdk" (default): runnable Azure OpenAI tool-use orchestrator.
  - "connected": managed Azure AI Agent Service (one agent per stage).
"""
from __future__ import annotations

import os

from .common.logging_setup import get_logger

logger = get_logger(__name__)


def main() -> None:
    prompt = os.getenv(
        "AZURE_DRIFTGUARD_PROMPT",
        "Fetch the latest GA Azure release notes and update affected Terraform modules.",
    )
    mode = os.getenv("ORCHESTRATION_MODE", "sdk")

    if mode == "connected":
        from .orchestration.agent_service_runtime import run_pipeline_via_agent_service

        state = run_pipeline_via_agent_service(prompt)
    else:
        from .orchestration.azure_orchestrator import run_pipeline

        state = run_pipeline(prompt)

    logger.info("Run complete. PR result: %s", state.get("pr_result"))


if __name__ == "__main__":
    main()
