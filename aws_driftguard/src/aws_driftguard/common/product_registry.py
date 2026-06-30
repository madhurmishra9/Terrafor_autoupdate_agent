"""Declarative product registry.

Products are onboarded as manifest files under ``skills/products/*.yaml`` — no
code changes required. Each manifest describes one cloud product: how to match
release notes to it, which Terraform resources and module paths it owns, whether
org policy auto-allows it, and extra phrases for the relevance filter.

The ingest, analysis, and relevance tools all read from this single registry, so
adding a product file updates every stage consistently.

Manifest schema (all keys optional except ``name``):

    name: Cloud SQL                 # display name
    enabled: true                   # set false to temporarily disable
    aliases:                        # strings that identify this product in a
      - Cloud SQL                   #   release-note title / description
      - CloudSQL
    resources:                      # Terraform provider resources it maps to
      - google_sql_database_instance
    module_paths:                   # module dirs in the Terraform repo
      - modules/cloudsql
    policy_allowed: true            # true => auto-actionable; false => review
    relevance_topics:               # extra phrases for the embedding filter
      - Cloud SQL data cache

The registry is cached and reloaded only on process start (or via reload()).
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import get_config
from .logging_setup import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class Product:
    name: str
    enabled: bool = True
    aliases: tuple[str, ...] = ()
    # Primary Terraform resources for this product.
    resources: tuple[str, ...] = ()
    # Secondary / related resources in the same product family. Features often
    # live here rather than on the primary resource (e.g. an attribute on
    # google_storage_bucket_object, not google_storage_bucket). The deep
    # resolver searches these so the agent patches the right resource.
    related_resources: tuple[str, ...] = ()
    module_paths: tuple[str, ...] = ()
    policy_allowed: bool = False
    relevance_topics: tuple[str, ...] = ()
    # Feeds the product owner wants polled (in addition to the shared cloud
    # feed). Either a single feed_url or a list of feeds.
    feed_url: str = ""
    feed_format: str = "auto"   # "auto" | "atom" | "rss"
    feeds_list: tuple[tuple[str, str], ...] = ()  # ((url, format), ...)
    # Provider these resources belong to (defaults to the cloud's provider) and
    # the version constraint to ground Terraform syntax against.
    provider: str = ""
    provider_version: str = ""

    @property
    def family(self) -> tuple[str, ...]:
        """All resources in this product: primary + related, de-duplicated."""
        seen: dict[str, None] = {}
        for r in (*self.resources, *self.related_resources):
            seen.setdefault(r, None)
        return tuple(seen.keys())

    @property
    def match_terms(self) -> tuple[str, ...]:
        """All strings that should match this product in a release note."""
        return tuple({self.name, *self.aliases})


class ProductRegistry:
    def __init__(self) -> None:
        self._products: list[Product] = []
        self._loaded_at: float = 0.0
        self._lock = threading.Lock()

    def _ttl(self) -> int:
        # Reuse the skills cache TTL so registry refresh matches skill refresh.
        return get_config().pipeline.skills_cache_ttl

    def load(self) -> None:
        with self._lock:
            import time

            fresh = self._loaded_at and (time.time() - self._loaded_at) < self._ttl()
            if self._products and fresh:
                return
            self._products = self._read_all()
            self._loaded_at = time.time()
            logger.info("Loaded %d product manifests from %s",
                        len(self._products), _source_desc())

    def reload(self) -> None:
        with self._lock:
            self._loaded_at = 0.0
        self.load()

    def _read_all(self) -> list[Product]:
        import yaml

        from . import skills_source

        products: list[Product] = []
        try:
            names = skills_source.list_dir("skills/products")
        except Exception as exc:  # GitHub/local unreachable -> fail open (empty)
            logger.error("could not list product manifests (%s): %s",
                         skills_source.describe_source(), exc)
            return products
        for fname in names:
            if not (fname.endswith(".yaml") or fname.endswith(".yml")):
                continue
            try:
                raw = skills_source.read_text(f"skills/products/{fname}")
                data = yaml.safe_load(raw) or {}
            except Exception as exc:
                logger.error("skipping invalid product manifest %s: %s", fname, exc)
                continue
            name = data.get("name")
            if not name:
                logger.warning("product manifest %s missing 'name'; skipped", fname)
                continue
            primary, related = _parse_resources(data.get("resources"),
                                                data.get("related_resources"))
            products.append(Product(
                name=name,
                enabled=bool(data.get("enabled", True)),
                aliases=tuple(data.get("aliases", []) or []),
                resources=primary,
                related_resources=related,
                module_paths=tuple(data.get("module_paths", []) or []),
                policy_allowed=bool(data.get("policy_allowed", False)),
                relevance_topics=tuple(data.get("relevance_topics", []) or []),
                feed_url=str(data.get("feed_url", "") or ""),
                feed_format=str(data.get("feed_format", "auto") or "auto"),
                feeds_list=_parse_feeds(data.get("feeds")),
                provider=str(data.get("provider", "") or ""),
                provider_version=str(data.get("provider_version", "") or ""),
            ))
        return products

    # ── Accessors used by the tools ────────────────────────────────────────
    def all(self) -> list[Product]:
        self.load()
        return [p for p in self._products if p.enabled]

    def names(self) -> list[str]:
        return [p.name for p in self.all()]

    def is_allowed(self, product: str) -> bool:
        return any(p.policy_allowed for p in self.all() if _norm(p.name) == _norm(product))

    def is_known(self, product: str) -> bool:
        return any(_norm(p.name) == _norm(product) for p in self.all())

    def relevance_topics(self) -> list[str]:
        topics: list[str] = []
        for p in self.all():
            topics.extend(p.match_terms)
            topics.extend(p.relevance_topics)
            topics.extend(p.resources)
        # de-dupe, preserve order
        seen: set[str] = set()
        out: list[str] = []
        for t in topics:
            if t and t.lower() not in seen:
                seen.add(t.lower())
                out.append(t)
        return out

    def match(self, text: str) -> Product | None:
        """Resolve a release-note title/description to a known product."""
        low = text.lower()
        best: Product | None = None
        best_len = 0
        for p in self.all():
            for term in p.match_terms:
                if term.lower() in low and len(term) > best_len:
                    best, best_len = p, len(term)
        return best

    def module_paths_for(self, product: str) -> list[str]:
        for p in self.all():
            if _norm(p.name) == _norm(product):
                return list(p.module_paths)
        return []

    def resources_for(self, product: str) -> list[str]:
        for p in self.all():
            if _norm(p.name) == _norm(product):
                return list(p.resources)
        return []

    def family_for(self, product: str) -> list[str]:
        """All resources (primary + related) for a product — the deep-scan set."""
        for p in self.all():
            if _norm(p.name) == _norm(product):
                return list(p.family)
        return []

    def related_resources_for(self, product: str) -> list[str]:
        for p in self.all():
            if _norm(p.name) == _norm(product):
                return list(p.related_resources)
        return []

    def provider_for(self, product: str, default: str = "") -> str:
        for p in self.all():
            if _norm(p.name) == _norm(product):
                return p.provider or default
        return default

    def provider_version_for(self, product: str) -> str:
        for p in self.all():
            if _norm(p.name) == _norm(product):
                return p.provider_version
        return ""

    def get(self, product: str) -> Product | None:
        for p in self.all():
            if _norm(p.name) == _norm(product):
                return p
        return None

    def feeds(self, shared_feed_url: str = "") -> list[dict[str, str]]:
        """Return the feeds Ingest should fetch this run.

        Always includes the shared cloud feed (when provided), plus any feed the
        product owner declared — either a single feed_url or a feeds: list.
        De-duplicated by URL. Each entry is {url, format, product}.
        """
        feeds: list[dict[str, str]] = []
        seen: set[str] = set()
        if shared_feed_url:
            feeds.append({"url": shared_feed_url, "format": "auto", "product": ""})
            seen.add(shared_feed_url)
        for p in self.all():
            product_feeds: list[tuple[str, str]] = []
            if p.feed_url:
                product_feeds.append((p.feed_url, p.feed_format))
            product_feeds.extend(p.feeds_list)
            for url, fmt in product_feeds:
                if url and url not in seen:
                    feeds.append({"url": url, "format": fmt, "product": p.name})
                    seen.add(url)
        return feeds


def _norm(s: str) -> str:
    return s.strip().lower()


def _parse_resources(resources: Any, related: Any) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Normalise the resources field into (primary, related).

    Supports three shapes for backward + forward compatibility:
      resources: [a, b]                          -> primary=[a,b], related=[]
      resources: {primary: [a], related: [b]}    -> primary=[a],   related=[b]
      resources: [a]  + related_resources: [b]   -> primary=[a],   related=[b]
    """
    primary: list[str] = []
    rel: list[str] = []
    if isinstance(resources, dict):
        primary = list(resources.get("primary", []) or [])
        rel = list(resources.get("related", []) or [])
    elif isinstance(resources, list):
        primary = list(resources)
    if related:
        rel.extend(r for r in related if r not in rel)
    return tuple(primary), tuple(rel)


def _parse_feeds(feeds: Any) -> tuple[tuple[str, str], ...]:
    """Normalise the optional feeds: field into ((url, format), ...).

    Supports:
      feeds: [https://...a.xml, https://...b.xml]
      feeds: [{url: https://...a.xml, format: atom}, ...]
    """
    out: list[tuple[str, str]] = []
    if not feeds:
        return ()
    for item in feeds:
        if isinstance(item, dict):
            url = str(item.get("url", "") or "")
            fmt = str(item.get("format", "auto") or "auto")
        else:
            url, fmt = str(item), "auto"
        if url:
            out.append((url, fmt))
    return tuple(out)


def _source_desc() -> str:
    from . import skills_source

    return skills_source.describe_source()


# Process-wide singleton.
registry = ProductRegistry()
