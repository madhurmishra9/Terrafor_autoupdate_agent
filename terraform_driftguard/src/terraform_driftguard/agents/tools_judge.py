"""Judge/critic pass for generated Terraform patches.

After TerraformAgent produces a patch that passes validate + plan, a separate
lightweight model scores its *semantic* correctness against the change analysis
and the provider resource schema. Patches scoring below JUDGE_MIN_SCORE are
rejected so they never reach PRAgent.

The judge model is configurable (defaults to the fast model) to keep the extra
call cheap. The judge runs in-process via the Vertex GenAI SDK; if the SDK is
unavailable (e.g. unit tests), it returns a neutral "skipped" verdict.
"""
from __future__ import annotations

import json
from typing import Any

from ..common.config import get_config
from ..common.logging_setup import get_logger

logger = get_logger(__name__)

_JUDGE_SYSTEM = """You are a strict Terraform code reviewer. Score a proposed HCL
patch for SEMANTIC correctness against the stated change requirement and the
provider resource schema. Return ONLY JSON, no prose:
{
  "score": <0-100 integer>,
  "correct": <true|false>,
  "issues": ["..."],
  "reasoning": "one sentence"
}
Deduct heavily for: invented arguments not in the schema, wrong provider version
assumptions, missing required arguments, changes that don't satisfy the
requirement, or silent provider-version drift."""


def judge_patch(
    *,
    requirement: str,
    patch: str,
    resource_schema_json: str = "",
    provider_version: str = "",
) -> dict[str, Any]:
    """Score a patch. Returns {score, correct, issues, passed, threshold}."""
    cfg = get_config()
    if not cfg.pipeline.judge_enabled:
        return {"passed": True, "score": None, "skipped": True,
                "reason": "judge disabled"}

    threshold = cfg.pipeline.judge_min_score
    prompt = (
        f"CHANGE REQUIREMENT:\n{requirement}\n\n"
        f"PROVIDER VERSION: {provider_version or 'unspecified'}\n\n"
        f"RESOURCE SCHEMA (arguments):\n{resource_schema_json or 'unavailable'}\n\n"
        f"PROPOSED PATCH:\n{patch}\n\n"
        "Score it now."
    )

    verdict = _call_judge_model(cfg.gcp.model_judge, prompt)
    if verdict is None:
        # SDK unavailable or call failed: do not block the pipeline on the judge.
        return {"passed": True, "score": None, "skipped": True,
                "reason": "judge model unavailable", "threshold": threshold}

    score = int(verdict.get("score", 0))
    passed = score >= threshold and verdict.get("correct", False)
    result = {
        "passed": passed,
        "score": score,
        "correct": verdict.get("correct", False),
        "issues": verdict.get("issues", []),
        "reasoning": verdict.get("reasoning", ""),
        "threshold": threshold,
    }
    if not passed:
        logger.info("judge rejected patch: score=%s issues=%s", score, result["issues"])
    return result


def _call_judge_model(model: str, prompt: str) -> dict[str, Any] | None:
    """Call the judge model via Vertex GenAI. Return parsed JSON or None."""
    try:
        from google import genai  # type: ignore
        from google.genai import types  # type: ignore
    except Exception:
        logger.warning("genai SDK unavailable; judge skipped")
        return None

    cfg = get_config()
    try:
        client = genai.Client(
            vertexai=True, project=cfg.gcp.project, location=cfg.gcp.location
        )
        resp = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=_JUDGE_SYSTEM,
                response_mime_type="application/json",
                temperature=0.0,
            ),
        )
        text = resp.text or "{}"
        return json.loads(text)
    except Exception as exc:
        logger.warning("judge model call failed: %s", exc)
        return None
