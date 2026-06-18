"""Simple thread-safe TTL cache for slow-changing external lookups.

Provider schemas and Terraform Registry metadata change rarely, so caching them
avoids re-fetching on every pipeline run. This is an in-process cache; for a
multi-replica deployment, back it with Redis or a CloudSQL table using the same
interface (get/set with TTL).
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable

from .config import get_config
from .logging_setup import get_logger

logger = get_logger(__name__)


class TTLCache:
    """Minimal thread-safe time-to-live cache."""

    def __init__(self, ttl_seconds: int | None = None) -> None:
        self._ttl = ttl_seconds if ttl_seconds is not None else get_config().pipeline.cache_ttl_seconds
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if time.time() >= expires_at:
                self._store.pop(key, None)
                return None
            return value

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._store[key] = (time.time() + self._ttl, value)

    def get_or_compute(self, key: str, compute: Callable[[], Any]) -> Any:
        """Return cached value or compute, store, and return it."""
        cached = self.get(key)
        if cached is not None:
            logger.debug("cache hit: %s", key)
            return cached
        value = compute()
        self.set(key, value)
        logger.debug("cache miss -> stored: %s", key)
        return value

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


# Module-level shared caches.
schema_cache = TTLCache()
registry_cache = TTLCache()
