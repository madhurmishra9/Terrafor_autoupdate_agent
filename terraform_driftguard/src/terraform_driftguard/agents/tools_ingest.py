"""Tools for IngestAgent and ClassifyAgent."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

import requests

from ..common.cloudsql_store import CloudSqlStore
from ..common.config import get_config
from ..common.logging_setup import get_logger

logger = get_logger(__name__)

_GA_SIGNALS = ("generally available", "is now ga", "graduated to ga", " ga ", "launched")
_NON_GA_SIGNALS = ("preview", "beta", "alpha", "experimental", "pre-ga")


def get_current_timestamp() -> str:
    """Return the current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def list_feeds() -> dict[str, Any]:
    """Return the feeds to fetch this run, and when the run was triggered.

    Tells Ingest WHICH feeds to pull: the shared cloud feed
    (RELEASE_FEED_URL) plus any per-product feed_url declared in
    skills/products/*.yaml. The pipeline run itself is triggered on a schedule
    (k8s CronJob / ECS scheduled task), so "when" is the trigger time returned
    here as triggered_at.
    """
    from ..common.product_registry import registry

    cfg = get_config()
    feeds = registry.feeds(shared_feed_url=cfg.pipeline.release_feed_url)
    return {"feeds": feeds, "count": len(feeds),
            "triggered_at": get_current_timestamp()}


def fetch_gcp_release_notes(max_items: int = 50, feed_url: str = "") -> dict[str, Any]:
    """Fetch a release-notes feed and return raw entries.

    feed_url is optional: when empty the shared RELEASE_FEED_URL is used; pass a
    specific feed (from list_feeds) to fetch a per-product feed instead.
    Returns a dict: {"entries": [{title, summary, updated, link}], "count": N}.
    """
    cfg = get_config()
    url = feed_url or cfg.pipeline.release_feed_url
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entries: list[dict[str, str]] = []
    for entry in root.findall("atom:entry", ns)[:max_items]:
        entries.append({
            "title": (entry.findtext("atom:title", default="", namespaces=ns) or "").strip(),
            "summary": (entry.findtext("atom:summary", default="", namespaces=ns) or "").strip(),
            "updated": (entry.findtext("atom:updated", default="", namespaces=ns) or "").strip(),
            "link": _entry_link(entry, ns),
        })
    return {"entries": entries, "count": len(entries)}


def _entry_link(entry: ET.Element, ns: dict[str, str]) -> str:
    link_el = entry.find("atom:link", ns)
    return link_el.get("href", "") if link_el is not None else ""


def parse_xml_entry(title: str, summary: str, updated: str, link: str) -> dict[str, Any]:
    """Normalise a single feed entry into a structured release note with GA flag."""
    haystack = f"{title} {summary}".lower()
    is_ga = any(sig in haystack for sig in _GA_SIGNALS) and not any(
        sig in haystack for sig in _NON_GA_SIGNALS
    )
    # release_date from updated (YYYY-MM-DD)
    release_date = updated[:10] if updated else datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # Resolve to a canonical managed product when the note matches one; else
    # fall back to the raw title prefix. The registry drives the mapping.
    from ..common.product_registry import registry

    matched = registry.match(f"{title} {summary}")
    product = matched.name if matched else (
        title.split(":")[0].strip() if ":" in title else title.strip()
    )
    return {
        "product": product,
        "version": _extract_version(summary) or "",
        "release_date": release_date,
        "title": title,
        "description": summary,
        "url": link,
        "is_ga": is_ga,
    }


def _extract_version(text: str) -> str | None:
    import re

    m = re.search(r"\bv?(\d+\.\d+(?:\.\d+)?)\b", text)
    return m.group(1) if m else None


def list_gcp_products() -> dict[str, Any]:
    """Return the set of managed products from the declarative product registry.

    Products are onboarded as manifests under skills/products/ — see that
    directory's README. No code change is needed to add a product.
    """
    from ..common.product_registry import registry

    return {"products": registry.names()}


def check_existing_release_note(product: str, version: str, release_date: str) -> dict[str, Any]:
    """Check whether a release note already exists in CloudSQL."""
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
