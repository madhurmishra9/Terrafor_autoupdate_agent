"""Lambda action-group handler for managed Bedrock Agents.

Each Bedrock Agent (one per pipeline stage) declares an action group whose
executor is this Lambda. Bedrock invokes it with the tool name (apiPath /
function) and parameters; the handler dispatches to the shared tool registry and
returns the result in the Bedrock action-group response shape.

Package this with the aws_driftguard source on the Lambda PYTHONPATH.
"""
from __future__ import annotations

import json
from typing import Any

from aws_driftguard.orchestration import tool_registry


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    action_group = event.get("actionGroup", "")
    function = event.get("function", event.get("apiPath", "")).lstrip("/")
    params = {p["name"]: p["value"] for p in event.get("parameters", [])}

    result = tool_registry.dispatch(function, params)

    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": action_group,
            "function": function,
            "functionResponse": {
                "responseBody": {"TEXT": {"body": json.dumps(result, default=str)}}
            },
        },
    }
