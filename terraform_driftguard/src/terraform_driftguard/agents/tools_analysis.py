"""Tools for AnalyzeAgent and DecideAgent."""
from __future__ import annotations

from typing import Any

import requests

from ..common.config import get_config
from ..common.github_client import GitHubClient
from ..common.logging_setup import get_logger

logger = get_logger(__name__)

_REGISTRY_BASE = "https://registry.terraform.io/v1"


def search_terraform_support(provider: str = "google", resource: str = "") -> dict[str, Any]:
    """Query the Terraform Registry for provider versions (TTL-cached).

    Shares the registry cache with GenerateAgent so repeated lookups within and
    across runs hit the cache instead of re-fetching.
    """
    from ..common.cache import registry_cache

    cache_key = f"registry:{provider}"

    def _compute() -> dict[str, Any]:
        url = f"{_REGISTRY_BASE}/providers/hashicorp/{provider}"
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        return {
            "provider": provider,
            "latest_version": data.get("version"),
            "published_at": data.get("published_at"),
        }

    base = registry_cache.get_or_compute(cache_key, _compute)
    return {**base, "resource_queried": resource}


def check_org_policy_support(product: str, resource: str = "") -> dict[str, Any]:
    """Check whether org policy permits the resource/feature.

    In a real deployment this would call an internal policy service. Here it
    applies a conservative allow-list driven by env config; unknown products
    require manual review (action_required stays true).
    """
    # Driven by the declarative product registry (skills/products/*.yaml).
    # policy_allowed=true => auto-actionable; unknown or false => manual review.
    from ..common.product_registry import registry

    allowed = registry.is_allowed(product)
    known = registry.is_known(product)
    return {
        "product": product,
        "policy_allowed": allowed,
        "requires_review": (not allowed),
        "known_product": known,
    }


def fetch_webpage(url: str) -> dict[str, Any]:
    """Fetch a documentation page's text for analysis (provider docs, etc.)."""
    resp = requests.get(url, timeout=20, headers={"User-Agent": "terraform-driftguard"})
    resp.raise_for_status()
    text = resp.text
    # Trim to a reasonable size for LLM context.
    return {"url": url, "content": text[:20000], "truncated": len(text) > 20000}


def get_module_file(file_path: str, ref: str = "") -> dict[str, Any]:
    """Read a Terraform module file from the GitHub repo (Decide)."""
    client = GitHubClient()
    return client.get_file(file_path, ref=ref or None)


def list_module_path() -> dict[str, Any]:
    """Return the configured Terraform module root path."""
    return {"module_path": get_config().pipeline.terraform_module_path}


# ── Deep / second-level resource resolution (anti-hallucination) ───────────
def list_product_resources(product: str) -> dict[str, Any]:
    """Return the full resource family for a product (primary + related).

    A product is a family of Terraform resources, not one. Analyze uses
    this to know every resource a release note for this product could touch —
    so a feature on a secondary resource (e.g. an object, not the bucket) is not
    missed.
    """
    from ..common.product_registry import registry

    p = registry.get(product)
    if not p:
        return {"product": product, "known": False, "family": []}
    return {
        "product": p.name,
        "known": True,
        "primary": list(p.resources),
        "related": list(p.related_resources),
        "family": list(p.family),
        "provider": p.provider or _default_provider(),
        "provider_version": p.provider_version,
    }


def resolve_attribute_owner(product: str, attribute: str, version: str = "") -> dict[str, Any]:
    """Resolve which resource in a product's family owns an attribute/block.

    THE anti-hallucination tool. Given an attribute mentioned in a release note
    (e.g. "custom_context" for Cloud Storage), it grounds against the real
    provider schema for the whole family and returns the resource that actually
    declares it (e.g. google_storage_bucket_object) — NOT a guess. If it can't
    be confirmed, it returns resolved=false with action=flag_for_review, so the
    agent must not invent an owner.
    """
    from ..common import schema_index
    from ..common.product_registry import registry

    p = registry.get(product)
    if not p:
        return {"resolved": False, "reason": "unknown_product", "product": product,
                "action": "flag_for_review"}
    provider = p.provider or _default_provider()
    ver = version or p.provider_version
    return schema_index.resolve_owner(provider, list(p.family), attribute, ver)


def list_family_schema(product: str, version: str = "") -> dict[str, Any]:
    """Return the grounded attribute/block surface of a product's whole family.

    Lets Analyze scan every resource's real arguments for the pinned
    provider version, rather than relying on the model's memory of the schema.
    """
    from ..common import schema_index
    from ..common.product_registry import registry

    p = registry.get(product)
    if not p:
        return {"available": False, "reason": "unknown_product", "product": product}
    provider = p.provider or _default_provider()
    ver = version or p.provider_version
    return schema_index.list_family_attributes(provider, list(p.family), ver)


def _default_provider() -> str:
    return "google"
