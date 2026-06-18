"""Embedding-based relevance filter.

Before expensive classification + analysis, score each release note's relevance
to the modules this pipeline manages. Notes below the relevance threshold are
skipped early, cutting token spend on releases that don't touch our modules.

Uses Amazon Bedrock (Titan) text embeddings. When the SDK is unavailable, returns relevant=True
for everything (fail-open) so the pipeline never silently drops releases.
"""
from __future__ import annotations

import math
from typing import Any

from ..common.cache import schema_cache
from ..common.config import get_config
from ..common.logging_setup import get_logger

logger = get_logger(__name__)

# Keywords describing the managed surface. In production, derive these from the
# actual module set (resource types present in the repo).
def _managed_topics() -> list[str]:
    """Managed-product topics from the declarative registry (skills/products/)."""
    from ..common.product_registry import registry

    topics = registry.relevance_topics()
    return topics or ["Terraform provider", "aws_ resource"]

_RELEVANCE_THRESHOLD = 0.55


def _embed(texts: list[str]) -> list[list[float]] | None:
    from ..common.llm_bedrock import embed

    return embed(texts)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _managed_centroid() -> list[float] | None:
    cached = schema_cache.get("relevance:centroid")
    if cached is not None:
        return cached
    embs = _embed(_managed_topics())
    if not embs:
        return None
    dim = len(embs[0])
    centroid = [sum(e[i] for e in embs) / len(embs) for i in range(dim)]
    schema_cache.set("relevance:centroid", centroid)
    return centroid


def score_release_relevance(title: str, description: str = "") -> dict[str, Any]:
    """Score one release note's relevance to managed modules.

    Returns {relevant, score, threshold, method}. Fails open (relevant=True)
    when embeddings are unavailable so no release is silently dropped.
    """
    if not get_config().pipeline.relevance_filter_enabled:
        return {"relevant": True, "score": None, "method": "disabled"}

    centroid = _managed_centroid()
    if centroid is None:
        return {"relevant": True, "score": None, "method": "fail_open"}

    note_emb = _embed([f"{title}. {description}"])
    if not note_emb:
        return {"relevant": True, "score": None, "method": "fail_open"}

    score = _cosine(note_emb[0], centroid)
    relevant = score >= _RELEVANCE_THRESHOLD
    return {"relevant": relevant, "score": round(score, 4),
            "threshold": _RELEVANCE_THRESHOLD, "method": "embedding"}
