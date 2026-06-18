-- Terraform DriftGuard Agent — CloudSQL (Postgres) schema
-- Applied idempotently by cloudsql_store.ensure_schema() on startup, and
-- provided here for manual provisioning / review.

CREATE TABLE IF NOT EXISTS release_notes (
    id             SERIAL PRIMARY KEY,
    product        VARCHAR(255) NOT NULL,
    version        VARCHAR(100),
    release_date   DATE NOT NULL,
    title          TEXT NOT NULL,
    description    TEXT,
    url            TEXT,
    is_ga          BOOLEAN DEFAULT TRUE,
    classification VARCHAR(20),
    fetched_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (product, version, release_date)
);

-- Lookup index for the duplicate / existence checks the pipeline performs.
CREATE INDEX IF NOT EXISTS idx_release_notes_identity
    ON release_notes (product, version, release_date);

-- Filter index for classification reporting.
CREATE INDEX IF NOT EXISTS idx_release_notes_classification
    ON release_notes (classification);
