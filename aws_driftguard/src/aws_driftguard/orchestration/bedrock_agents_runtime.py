"""Managed Bedrock Agents runtime invoker.

Used when ORCHESTRATION_MODE=agents. Invokes the provisioned supervisor agent
(multi-agent collaboration) which coordinates the 7 collaborator agents. The
collaborators' action groups are backed by the Lambda handler in
deploy/bedrock-agents/lambda_action_group.py, which dispatches to the same
shared tool registry.

Provisioning (CloudFormation in deploy/bedrock-agents/) must run first; this
module only invokes an already-provisioned supervisor.
"""
from __future__ import annotations

import uuid
from typing import Any

from ..common.config import get_config
from ..common.logging_setup import get_logger

logger = get_logger(__name__)


def invoke_supervisor(prompt: str) -> dict[str, Any]:
    """Invoke the provisioned Bedrock supervisor agent with the run prompt."""
    cfg = get_config()
    if not cfg.agents.supervisor_agent_id:
        raise RuntimeError(
            "BEDROCK_SUPERVISOR_AGENT_ID is not set. Provision the agents via "
            "deploy/bedrock-agents/ (CloudFormation) before using mode=agents."
        )
    import boto3

    client = boto3.client("bedrock-agent-runtime", region_name=cfg.bedrock.region)
    session_id = str(uuid.uuid4())
    resp = client.invoke_agent(
        agentId=cfg.agents.supervisor_agent_id,
        agentAliasId=cfg.agents.supervisor_agent_alias_id,
        sessionId=session_id,
        inputText=prompt,
    )
    chunks: list[str] = []
    for event in resp.get("completion", []):
        if "chunk" in event:
            chunks.append(event["chunk"].get("bytes", b"").decode("utf-8", "ignore"))
    return {"status": "completed", "session_id": session_id, "output": "".join(chunks)}
