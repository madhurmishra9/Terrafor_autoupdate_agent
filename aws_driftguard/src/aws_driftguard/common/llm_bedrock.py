"""Amazon Bedrock inference client (replaces Vertex/Gemini).

Provides three capabilities used across the pipeline:
  - converse(): a tool-use-capable chat turn via the Bedrock Converse API
  - generate_json(): a single structured-output call (used by the judge)
  - embed(): text embeddings (used by the relevance filter)

All calls degrade gracefully: when boto3 is unavailable (unit tests) the methods
raise BedrockUnavailable, and callers fall back to safe behaviour.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from .config import get_config
from .logging_setup import get_logger

logger = get_logger(__name__)


class BedrockUnavailable(RuntimeError):
    """Raised when the Bedrock runtime client cannot be constructed."""


def _client(service: str = "bedrock-runtime") -> Any:
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover
        raise BedrockUnavailable("boto3 not installed") from exc
    return boto3.client(service, region_name=get_config().bedrock.region)


def generate_json(model: str, system: str, prompt: str, *, temperature: float = 0.0) -> dict[str, Any]:
    """Single Bedrock Converse call expecting a JSON object back."""
    client = _client()
    cfg = get_config()
    resp = client.converse(
        modelId=model,
        system=[{"text": system}],
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": cfg.bedrock.max_tokens, "temperature": temperature},
    )
    text = _extract_text(resp)
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(text)


def converse_with_tools(
    *,
    model: str,
    system: str,
    user_message: str,
    tools: list[dict[str, Any]],
    tool_executor: Callable[[str, dict[str, Any]], dict[str, Any]],
    max_turns: int = 12,
) -> str:
    """Run a Bedrock Converse tool-use loop until the model stops calling tools.

    This is the native-Bedrock runtime path for a single agent stage: the model
    decides which registered tools to call; `tool_executor` runs them; results
    are fed back until the model returns a final text answer.
    """
    client = _client()
    cfg = get_config()
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": [{"text": user_message}]}
    ]
    tool_config = {"tools": tools}

    for _turn in range(max_turns):
        resp = client.converse(
            modelId=model,
            system=[{"text": system}],
            messages=messages,
            toolConfig=tool_config,
            inferenceConfig={"maxTokens": cfg.bedrock.max_tokens, "temperature": 0.0},
        )
        output = resp.get("output", {}).get("message", {})
        messages.append(output)
        stop_reason = resp.get("stopReason")

        if stop_reason == "tool_use":
            tool_results = []
            for block in output.get("content", []):
                if "toolUse" in block:
                    tu = block["toolUse"]
                    result = tool_executor(tu["name"], tu.get("input", {}))
                    tool_results.append({
                        "toolResult": {
                            "toolUseId": tu["toolUseId"],
                            "content": [{"json": result}],
                        }
                    })
            messages.append({"role": "user", "content": tool_results})
            continue

        # Final answer.
        return _extract_text(resp)

    logger.warning("converse loop hit max_turns without final answer")
    return _extract_text_from_messages(messages)


def embed(texts: list[str]) -> list[list[float]] | None:
    """Return embeddings for the given texts, or None if unavailable."""
    try:
        client = _client()
    except BedrockUnavailable:
        return None
    cfg = get_config()
    vectors: list[list[float]] = []
    try:
        for t in texts:
            resp = client.invoke_model(
                modelId=cfg.bedrock.embed_model,
                body=json.dumps({"inputText": t}),
            )
            payload = json.loads(resp["body"].read())
            vectors.append(payload["embedding"])
        return vectors
    except Exception as exc:  # pragma: no cover
        logger.warning("Bedrock embed failed: %s", exc)
        return None


def _extract_text(resp: dict[str, Any]) -> str:
    msg = resp.get("output", {}).get("message", {})
    return "".join(b.get("text", "") for b in msg.get("content", []) if "text" in b)


def _extract_text_from_messages(messages: list[dict[str, Any]]) -> str:
    for m in reversed(messages):
        if m.get("role") == "assistant":
            return "".join(b.get("text", "") for b in m.get("content", []) if "text" in b)
    return ""
