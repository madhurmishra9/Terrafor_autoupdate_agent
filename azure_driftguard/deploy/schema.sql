-- Azure DriftGuard — Azure SQL Database schema (T-SQL)
-- Applied idempotently by azuresql_store.ensure_schema() on startup.
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
