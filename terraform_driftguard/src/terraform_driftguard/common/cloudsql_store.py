"""CloudSQL (Postgres) access for release-note and classification persistence.

Connects through the Cloud SQL Auth Proxy sidecar at 127.0.0.1:5432. All queries
are parameterised. The schema is created idempotently on first use.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

import psycopg2
import psycopg2.extras

from .config import CloudSqlConfig, get_config
from .logging_setup import get_logger

logger = get_logger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS release_notes (
    id            SERIAL PRIMARY KEY,
    product       VARCHAR(255) NOT NULL,
    version       VARCHAR(100),
    release_date  DATE NOT NULL,
    title         TEXT NOT NULL,
    description   TEXT,
    url           TEXT,
    is_ga         BOOLEAN DEFAULT TRUE,
    classification VARCHAR(20),
    fetched_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (product, version, release_date)
);
"""


class CloudSqlStore:
    def __init__(self, cfg: CloudSqlConfig | None = None) -> None:
        self.cfg = cfg or get_config().cloudsql
        self._ensured = False

    @contextmanager
    def _conn(self) -> Iterator[Any]:
        conn = psycopg2.connect(self.cfg.dsn, connect_timeout=10)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def ensure_schema(self) -> None:
        if self._ensured:
            return
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(_SCHEMA)
        self._ensured = True
        logger.info("release_notes schema ensured")

    def upsert_release(self, note: dict[str, Any]) -> bool:
        """Insert a release note if new. Return True if inserted, False if existed."""
        self.ensure_schema()
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO release_notes
                        (product, version, release_date, title, description, url, is_ga)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (product, version, release_date) DO NOTHING
                    """,
                    (
                        note["product"],
                        note.get("version"),
                        note["release_date"],
                        note["title"],
                        note.get("description"),
                        note.get("url"),
                        note.get("is_ga", True),
                    ),
                )
                return cur.rowcount > 0

    def set_classification(self, *, product: str, version: str, release_date: str, classification: str) -> None:
        self.ensure_schema()
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE release_notes SET classification = %s
                    WHERE product = %s AND version = %s AND release_date = %s
                    """,
                    (classification, product, version, release_date),
                )

    def exists(self, *, product: str, version: str, release_date: str) -> bool:
        self.ensure_schema()
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1 FROM release_notes
                    WHERE product = %s AND version = %s AND release_date = %s
                    LIMIT 1
                    """,
                    (product, version, release_date),
                )
                return cur.fetchone() is not None
