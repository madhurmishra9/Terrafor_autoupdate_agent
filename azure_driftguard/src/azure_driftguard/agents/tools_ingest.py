"""Tools for RequestProcessorAgent and ClassificationAgent (Azure target cloud).

Source: Azure Updates RSS feed (https://www.microsoft.com/releasecommunications/api/v2/azure/rss).
The pipeline runtime platform stays on GCP (Vertex + CloudSQL); only the cloud
being analysed (Azure) and the Terraform provider (hashicorp/azurerm) differ from
the GCP edition.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

import requests

from ..common.azuresql_store import CloudSqlStore
from ..common.config import get_config
from ..common.logging_setup import get_logger

logger = get_logger(__name__)

# Azure Updates marks lifecycle in the title/category: "General Availability",
# "Public Preview", "Private Preview". GA when it says GA / generally available.
_GA_SIGNALS = ("general availability", "generally available", "now ga", "is ga")
_NON_GA_SIGNALS = ("preview", "private preview", "public preview", "beta")


def get_current_timestamp() -> str:
    """Return the current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def list_feeds() -> dict[str, Any]:
    """Return the feeds to fetch this run, and when the run was triggered.

    Tells RequestProcessor WHICH feeds to pull: the shared cloud feed
    (RELEASE_FEED_URL) plus any per-product feed_url declared in
    skills/products/*.yaml. The pipeline run is triggered on a schedule
    (EventBridge/ECS, EKS/AKS CronJob), so "when" is the trigger time returned
    here as triggered_at.
    """
    from ..common.product_registry import registry

    cfg = get_config()
    feeds = registry.feeds(shared_feed_url=cfg.pipeline.release_feed_url)
    return {"feeds": feeds, "count": len(feeds),
            "triggered_at": get_current_timestamp()}


def fetch_azure_release_notes(max_items: int = 50, feed_url: str = "") -> dict[str, Any]:
    """Fetch the Azure Updates RSS feed and return raw entries.

    Returns {"entries": [{title, summary, updated, link}], "count": N}.
    """
    cfg = get_config()
    url = feed_url or cfg.pipeline.release_feed_url
    resp = requests.get(url, timeout=30,
                        headers={"User-Agent": "azure-driftguard"})
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    entries: list[dict[str, str]] = []
    for item in root.findall(".//item")[:max_items]:
        entries.append({
            "title": (item.findtext("title") or "").strip(),
            "summary": (item.findtext("description") or "").strip(),
            "updated": (item.findtext("pubDate") or "").strip(),
            "link": (item.findtext("link") or "").strip(),
        })
    return {"entries": entries, "count": len(entries)}


def parse_xml_entry(title: str, summary: str, updated: str, link: str) -> dict[str, Any]:
    """Normalise a single feed entry into a structured release note with GA flag."""
    haystack = f"{title} {summary}".lower()
    is_ga = any(sig in haystack for sig in _GA_SIGNALS) and not any(
        sig in haystack for sig in _NON_GA_SIGNALS
    )
    release_date = _parse_rss_date(updated)
    from ..common.product_registry import registry
    matched = registry.match(f"{title} {summary}")
    product = matched.name if matched else _extract_azure_service(title)
    return {
        "product": product,
        "version": _extract_version(summary) or "",
        "release_date": release_date,
        "title": title,
        "description": summary,
        "url": link,
        "is_ga": is_ga,
    }


def _parse_rss_date(value: str) -> str:
    """Parse an RFC-822 RSS pubDate to YYYY-MM-DD; fall back to today."""
    if value:
        for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z"):
            try:
                return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _extract_azure_service(title: str) -> str:
    """Best-effort Azure service name from an Updates title.

    Azure Updates titles often start with the lifecycle tag, e.g.
    'General Availability: Azure SQL Database ...'. Strip the tag, then take the
    leading service words.
    """
    t = title.strip()
    for tag in ("General Availability:", "Public Preview:", "Private Preview:",
                "Generally Available:", "Retirement:"):
        if t.startswith(tag):
            t = t[len(tag):].strip()
            break
    words = t.split()
    return " ".join(words[:3]).strip()[:80] if words else t[:80]


def _extract_version(text: str) -> str | None:
    import re

    m = re.search(r"\bv?(\d+\.\d+(?:\.\d+)?)\b", text)
    return m.group(1) if m else None


def list_azure_products() -> dict[str, Any]:
    """Return managed products from the declarative product registry.

    Products are onboarded as manifests under skills/products/ — see that
    directory's README. No code change is needed to add a product.
    """
    from ..common.product_registry import registry

    return {"products": registry.names()}


def check_existing_release_note(product: str, version: str, release_date: str) -> dict[str, Any]:
    """Check whether a release note already exists in the store."""
    exists = CloudSqlStore().exists(product=product, version=version, release_date=release_date)
    return {"exists": exists}


def save_classification_to_database(
    product: str, version: str, release_date: str, classification: str,
    title: str = "", description: str = "", url: str = "", is_ga: bool = True,
) -> dict[str, Any]:
    """Persist a release note and its classification. Idempotent."""
    store = CloudSqlStore()
    inserted = store.upsert_release({
        "product": product, "version": version, "release_date": release_date,
        "title": title, "description": description, "url": url, "is_ga": is_ga,
    })
    store.set_classification(
        product=product, version=version, release_date=release_date,
        classification=classification,
    )
    return {"inserted": inserted, "classification": classification}
