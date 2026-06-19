"""Tools for RequestProcessorAgent and ClassificationAgent (AWS target cloud).

Source: AWS 'What's New' RSS feed (https://aws.amazon.com/about-aws/whats-new/recent/feed/).
The pipeline runtime platform stays on GCP (Vertex + CloudSQL); only the cloud
being analysed (AWS) and the Terraform provider (hashicorp/aws) differ from the
GCP edition.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

import requests

from ..common.rds_store import CloudSqlStore
from ..common.config import get_config
from ..common.logging_setup import get_logger

logger = get_logger(__name__)

# AWS What's New does not use GA/preview wording the way GCP does. Most posts on
# the feed are GA launches; treat 'preview' as the main non-GA signal.
_NON_GA_SIGNALS = ("preview", "beta", "(preview)", "in preview", "public preview")


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


def fetch_aws_release_notes(max_items: int = 50, feed_url: str = "") -> dict[str, Any]:
    """Fetch the AWS 'What's New' RSS feed and return raw entries.

    Returns {"entries": [{title, summary, updated, link}], "count": N}.
    """
    cfg = get_config()
    url = feed_url or cfg.pipeline.release_feed_url
    resp = requests.get(url, timeout=30,
                        headers={"User-Agent": "aws-driftguard"})
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    # RSS 2.0: channel/item with title, description, pubDate, link
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
    # AWS posts are GA unless explicitly marked preview/beta.
    is_ga = not any(sig in haystack for sig in _NON_GA_SIGNALS)
    release_date = _parse_rss_date(updated)
    # AWS titles look like "Amazon RDS now supports X" — derive the service name.
    from ..common.product_registry import registry
    matched = registry.match(f"{title} {summary}")
    product = matched.name if matched else _extract_aws_service(title)
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


def _extract_aws_service(title: str) -> str:
    """Best-effort AWS service name from a What's New title."""
    t = title.strip()
    for prefix in ("Amazon ", "AWS "):
        if t.startswith(prefix):
            rest = t[len(prefix):]
            # service name is usually the leading 1-3 words before a verb
            words = rest.split()
            return (prefix + " ".join(words[:2])).strip()
    return t.split(" now ")[0].strip()[:80] if " now " in t else t[:80]


def _extract_version(text: str) -> str | None:
    import re

    m = re.search(r"\bv?(\d+\.\d+(?:\.\d+)?)\b", text)
    return m.group(1) if m else None


def list_aws_products() -> dict[str, Any]:
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
