"""Azure SQL Database access for release-note and classification persistence.

Connects to Azure SQL via pyodbc (ODBC Driver 18). Password resolved from Key
Vault when AZURE_SQL_PASSWORD_SECRET is set. All queries are parameterised
(T-SQL uses ? placeholders). Schema created idempotently on first use.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from .config import AzureSqlConfig, get_config
from .logging_setup import get_logger

logger = get_logger(__name__)

_SCHEMA = """
IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='release_notes' AND xtype='U')
CREATE TABLE release_notes (
    id            INT IDENTITY(1,1) PRIMARY KEY,
    product       NVARCHAR(255) NOT NULL,
    version       NVARCHAR(100),
    release_date  DATE NOT NULL,
    title         NVARCHAR(MAX) NOT NULL,
    description   NVARCHAR(MAX),
    url           NVARCHAR(MAX),
    is_ga         BIT DEFAULT 1,
    classification NVARCHAR(20),
    fetched_at    DATETIME2 DEFAULT SYSUTCDATETIME(),
    CONSTRAINT uq_release UNIQUE (product, version, release_date)
);
"""


class AzureSqlStore:
    def __init__(self, cfg: AzureSqlConfig | None = None) -> None:
        self.cfg = cfg or get_config().sql
        self._vault = get_config().keyvault.vault_url
        self._ensured = False

    @contextmanager
    def _conn(self) -> Iterator[Any]:
        import pyodbc

        conn = pyodbc.connect(self.cfg.connection_string(self._vault), timeout=10)
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
            conn.cursor().execute(_SCHEMA)
        self._ensured = True
        logger.info("release_notes schema ensured (Azure SQL)")

    def upsert_release(self, note: dict[str, Any]) -> bool:
        self.ensure_schema()
        with self._conn() as conn:
            cur = conn.cursor()
            # MERGE for idempotent insert.
            cur.execute(
                """
                MERGE release_notes AS target
                USING (SELECT ? AS product, ? AS version, ? AS release_date) AS src
                ON target.product = src.product AND ISNULL(target.version,'') = ISNULL(src.version,'')
                   AND target.release_date = src.release_date
                WHEN NOT MATCHED THEN
                    INSERT (product, version, release_date, title, description, url, is_ga)
                    VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (note["product"], note.get("version"), note["release_date"],
                 note["product"], note.get("version"), note["release_date"],
                 note["title"], note.get("description"), note.get("url"),
                 1 if note.get("is_ga", True) else 0),
            )
            return cur.rowcount > 0

    def set_classification(self, *, product: str, version: str, release_date: str,
                           classification: str) -> None:
        self.ensure_schema()
        with self._conn() as conn:
            conn.cursor().execute(
                """
                UPDATE release_notes SET classification = ?
                WHERE product = ? AND ISNULL(version,'') = ISNULL(?, '') AND release_date = ?
                """,
                (classification, product, version, release_date),
            )

    def exists(self, *, product: str, version: str, release_date: str) -> bool:
        self.ensure_schema()
        with self._conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT TOP 1 1 FROM release_notes
                WHERE product = ? AND ISNULL(version,'') = ISNULL(?, '') AND release_date = ?
                """,
                (product, version, release_date),
            )
            return cur.fetchone() is not None


# Backwards-compatible alias so tool modules importing CloudSqlStore keep working.
CloudSqlStore = AzureSqlStore
