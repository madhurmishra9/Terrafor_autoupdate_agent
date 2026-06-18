"""Tools for ChangeAnalyserAgent and DecisionMakerAgent."""
from __future__ import annotations

from typing import Any

import requests

from ..common.config import get_config
from ..common.github_client import GitHubClient
from ..common.logging_setup import get_logger

logger = get_logger(__name__)

_REGISTRY_BASE = "https://registry.terraform.io/v1"


def search_terraform_support(provider: str = "azurerm", resource: str = "") -> dict[str, Any]:
    """Query the Terraform Registry for provider versions (TTL-cached).

    Shares the registry cache with TerraformAgent so repeated lookups within and
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
    # Allow-list could come from config / policy API. Conservative default.
# Driven by the declarative product registry (skills/products/*.yaml).
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
    resp = requests.get(url, timeout=20, headers={"User-Agent": "azure-driftguard"})
    resp.raise_for_status()
    text = resp.text
    # Trim to a reasonable size for LLM context.
    return {"url": url, "content": text[:20000], "truncated": len(text) > 20000}


def get_module_file(file_path: str, ref: str = "") -> dict[str, Any]:
    """Read a Terraform module file from the GitHub repo (DecisionMaker)."""
    client = GitHubClient()
    return client.get_file(file_path, ref=ref or None)


def list_module_path() -> dict[str, Any]:
    """Return the configured Terraform module root path."""
    return {"module_path": get_config().pipeline.terraform_module_path}
