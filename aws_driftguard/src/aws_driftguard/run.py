"""Process entrypoint for AWS DriftGuard (native Bedrock orchestration).

ORCHESTRATION_MODE selects the runtime:
  - "converse" (default): runnable Bedrock Converse tool-use orchestrator.
  - "agents": invoke the provisioned managed Bedrock Agents supervisor.
"""
from __future__ import annotations

import os

from .common.logging_setup import get_logger

logger = get_logger(__name__)


def main() -> None:
    prompt = os.getenv(
        "AWS_DRIFTGUARD_PROMPT",
        "Fetch the latest GA AWS release notes and update affected Terraform modules.",
    )
    mode = os.getenv("ORCHESTRATION_MODE", "converse")

    if mode == "agents":
        from .orchestration.bedrock_agents_runtime import invoke_supervisor

        result = invoke_supervisor(prompt)
        logger.info("Managed Bedrock Agents run complete: %s", result.get("status"))
    else:
        from .orchestration.bedrock_orchestrator import run_pipeline

        state = run_pipeline(prompt)
        logger.info("Converse run complete. PR result: %s", state.get("publish_result"))


if __name__ == "__main__":
    main()
