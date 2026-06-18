"""Azure OpenAI inference client (replaces Vertex/Gemini).

Provides the three capabilities used across the pipeline:
  - generate_json(): structured-output call (used by the judge)
  - chat_with_tools(): tool-use loop (used by the SDK orchestrator path)
  - embed(): text embeddings (used by the relevance filter)

Auth uses an API key (from Key Vault in prod) or DefaultAzureCredential token.
Degrades gracefully: when the openai SDK is unavailable, methods raise
AzureOpenAIUnavailable and callers fall back to safe behaviour.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from .config import get_config
from .logging_setup import get_logger

logger = get_logger(__name__)


class AzureOpenAIUnavailable(RuntimeError):
    """Raised when the Azure OpenAI client cannot be constructed."""


def _client() -> Any:
    try:
        from openai import AzureOpenAI
    except ImportError as exc:  # pragma: no cover
        raise AzureOpenAIUnavailable("openai SDK not installed") from exc

    cfg = get_config()
    api_key = cfg.openai.api_key
    if not api_key and cfg.openai.api_key_secret_name and cfg.keyvault.vault_url:
        from .secrets_azure import get_secret

        api_key = get_secret(cfg.keyvault.vault_url, cfg.openai.api_key_secret_name)
    return AzureOpenAI(
        azure_endpoint=cfg.openai.endpoint,
        api_key=api_key,
        api_version=cfg.openai.api_version,
    )


def generate_json(deployment: str, system: str, prompt: str, *, temperature: float = 0.0) -> dict[str, Any]:
    """Single chat completion expecting JSON back (used by the judge)."""
    client = _client()
    resp = client.chat.completions.create(
        model=deployment,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": prompt}],
        temperature=temperature,
        response_format={"type": "json_object"},
        max_tokens=get_config().openai.max_tokens,
    )
    return json.loads(resp.choices[0].message.content or "{}")


def chat_with_tools(
    *,
    deployment: str,
    system: str,
    user_message: str,
    tools: list[dict[str, Any]],
    tool_executor: Callable[[str, dict[str, Any]], dict[str, Any]],
    max_turns: int = 12,
) -> str:
    """Run an Azure OpenAI tool-use loop until the model stops calling tools."""
    client = _client()
    cfg = get_config()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_message},
    ]

    for _turn in range(max_turns):
        resp = client.chat.completions.create(
            model=deployment,
            messages=messages,
            tools=tools,
            temperature=0.0,
            max_tokens=cfg.openai.max_tokens,
        )
        msg = resp.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))

        if not msg.tool_calls:
            return msg.content or ""

        for call in msg.tool_calls:
            args = json.loads(call.function.arguments or "{}")
            result = tool_executor(call.function.name, args)
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": json.dumps(result, default=str),
            })

    logger.warning("chat loop hit max_turns without final answer")
    return ""


def embed(texts: list[str]) -> list[list[float]] | None:
    """Return embeddings for the given texts, or None if unavailable."""
    try:
        client = _client()
    except AzureOpenAIUnavailable:
        return None
    try:
        resp = client.embeddings.create(
            model=get_config().openai.embed_deployment, input=texts
        )
        return [d.embedding for d in resp.data]
    except Exception as exc:  # pragma: no cover
        logger.warning("Azure OpenAI embed failed: %s", exc)
        return None
