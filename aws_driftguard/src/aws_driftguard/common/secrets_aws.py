"""AWS Secrets Manager access.

Resolves secret values (RDS password, Jira token, GitHub PAT / App key) from
Secrets Manager. Values are cached in-process for the lifetime of the task.
Never logs secret values.
"""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from .logging_setup import get_logger

logger = get_logger(__name__)


@lru_cache(maxsize=64)
def get_secret(secret_id: str, region: str = "") -> str:
    """Return a secret string by id/ARN. Cached per process."""
    import boto3  # imported lazily so unit tests don't require boto3

    kwargs: dict[str, Any] = {}
    if region:
        kwargs["region_name"] = region
    client = boto3.client("secretsmanager", **kwargs)
    resp = client.get_secret_value(SecretId=secret_id)
    logger.info("Resolved secret %s from Secrets Manager", secret_id.split(":")[-1])
    return resp.get("SecretString", "")


def get_secret_json(secret_id: str, region: str = "") -> dict[str, Any]:
    """Return a JSON secret parsed to a dict (e.g. RDS credential bundle)."""
    raw = get_secret(secret_id, region)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"value": raw}
