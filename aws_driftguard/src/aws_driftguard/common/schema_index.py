"""Terraform schema index for a product's resource family.

A product (e.g. "Cloud Storage") is a *family* of resources, not one resource:
google_storage_bucket, google_storage_bucket_object, google_storage_bucket_iam_*,
etc. A release-note feature often lives on a secondary resource — "custom
context" is an attribute of google_storage_bucket_object, NOT the bucket. If the
agent assumes every Storage feature belongs to the bucket, it hallucinates.

This module grounds against the *real* provider schema for the exact provider
version and builds:
  - per-resource attribute/block maps (argument names, nested blocks, types)
  - an INVERTED index: attribute name -> which resource(s) in the family own it

The agent uses the inverted index to resolve "which resource does <attribute>
belong to?" before patching — a deterministic, schema-backed answer instead of a
guess. When the schema cannot be fetched (no terraform binary / provider), the
index reports unavailable and callers flag the change for manual review rather
than guessing.

Results are TTL-cached by (provider, version, family).
"""
from __future__ import annotations

from typing import Any

from .cache import schema_cache
from .logging_setup import get_logger

logger = get_logger(__name__)


def build_family_index(provider: str, family: list[str], version: str = "") -> dict[str, Any]:
    """Build the schema index for a resource family.

    Returns:
      {
        "available": bool,
        "provider": str, "version": str,
        "resources": { resource: {arguments: {...}, blocks: [...]} },
        "attribute_index": { attribute_name: [resource, ...] },
        "block_index": { block_name: [resource, ...] },
      }
    available=False means the schema could not be grounded (caller should flag
    for review rather than guess).
    """
    key = f"family-index:{provider}:{version or 'latest'}:{','.join(sorted(family))}"

    def _compute() -> dict[str, Any]:
        from ..agents import tools_terraform

        resources: dict[str, Any] = {}
        attribute_index: dict[str, list[str]] = {}
        block_index: dict[str, list[str]] = {}
        any_grounded = False

        for resource in family:
            schema = tools_terraform.extract_resource_schema(provider, resource, version)
            if not schema.get("ok"):
                continue
            any_grounded = True
            args = schema.get("arguments", {})
            blocks = schema.get("block_types", [])
            resources[resource] = {"arguments": args, "blocks": blocks}
            for arg in args:
                attribute_index.setdefault(arg, []).append(resource)
            for blk in blocks:
                block_index.setdefault(blk, []).append(resource)

        return {
            "available": any_grounded,
            "provider": provider,
            "version": version or "latest",
            "resources": resources,
            "attribute_index": attribute_index,
            "block_index": block_index,
        }

    return schema_cache.get_or_compute(key, _compute)


def resolve_owner(provider: str, family: list[str], attribute: str,
                  version: str = "") -> dict[str, Any]:
    """Resolve which resource(s) in the family own a given attribute/block.

    This is the second-level lookup that prevents hallucination: given an
    attribute mentioned in a release note (e.g. "custom_context"), it returns
    the resource that actually declares it (e.g. google_storage_bucket_object),
    distinguishing primary vs related ownership.
    """
    index = build_family_index(provider, family, version)
    if not index.get("available"):
        return {
            "resolved": False,
            "reason": "schema_unavailable",
            "attribute": attribute,
            "action": "flag_for_review",
            "note": "Provider schema could not be grounded; do not guess the "
                    "owning resource — flag for manual review.",
        }

    attr = attribute.strip()
    owners = index["attribute_index"].get(attr, [])
    block_owners = index["block_index"].get(attr, [])
    all_owners = list(dict.fromkeys([*owners, *block_owners]))

    if not all_owners:
        return {
            "resolved": False,
            "reason": "attribute_not_found",
            "attribute": attr,
            "searched_resources": family,
            "action": "flag_for_review",
            "note": f"'{attr}' was not found on any resource in the {provider} "
                    "family at this version. It may be new, renamed, or on a "
                    "resource not yet onboarded — flag for manual review.",
        }

    return {
        "resolved": True,
        "attribute": attr,
        "owner_resources": all_owners,
        "is_block": bool(block_owners),
        "kind": "block" if block_owners else "argument",
        "version": index["version"],
    }


def list_family_attributes(provider: str, family: list[str], version: str = "") -> dict[str, Any]:
    """Return the full attribute surface of a family (for the agent to scan)."""
    index = build_family_index(provider, family, version)
    if not index.get("available"):
        return {"available": False, "action": "flag_for_review"}
    surface = {
        res: {"arguments": sorted(meta["arguments"].keys()),
              "blocks": sorted(meta["blocks"])}
        for res, meta in index["resources"].items()
    }
    return {"available": True, "version": index["version"], "by_resource": surface}
