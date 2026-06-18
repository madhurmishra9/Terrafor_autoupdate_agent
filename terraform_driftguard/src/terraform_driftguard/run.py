"""Process entrypoint. Builds the pipeline and runs it via the ADK runner.

This is a thin launcher. In production you may instead expose the pipeline via
`adk web` or a custom FastAPI server; the pipeline object is the same.
"""
from __future__ import annotations

import asyncio
import os

from .common.logging_setup import get_logger
from .pipeline import build_pipeline

logger = get_logger(__name__)


async def _run_once(prompt: str) -> None:
    from google.adk.runners import InMemoryRunner  # type: ignore
    from google.genai import types  # type: ignore

    pipeline = build_pipeline()
    runner = InMemoryRunner(agent=pipeline, app_name="terraform_driftguard")
    session = await runner.session_service.create_session(
        app_name="terraform_driftguard", user_id="system"
    )
    content = types.Content(role="user", parts=[types.Part(text=prompt)])
    async for event in runner.run_async(
        user_id="system", session_id=session.id, new_message=content
    ):
        if event.is_final_response():
            logger.info("Pipeline final response received")


def main() -> None:
    prompt = os.getenv(
        "TERRAFORM_DRIFTGUARD_PROMPT",
        "Fetch the latest GA GCP release notes and evergreen affected Terraform modules.",
    )
    asyncio.run(_run_once(prompt))


if __name__ == "__main__":
    main()
