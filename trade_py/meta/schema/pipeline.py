"""DDL for pipeline state tables (PipelineDb)."""

INGEST_RUNS = """
CREATE TABLE IF NOT EXISTS ingest_runs (
    run_id           TEXT PRIMARY KEY,
    source_id        TEXT NOT NULL,
    fetched_at       TIMESTAMPTZ NOT NULL,
    date_range_start DATE,
    date_range_end   DATE,
    records_fetched  INT DEFAULT 0,
    records_new      INT DEFAULT 0,
    status           TEXT NOT NULL,
    error            TEXT DEFAULT ''
)"""

COVERAGE = """
CREATE TABLE IF NOT EXISTS coverage (
    source_id    TEXT NOT NULL,
    data_date    DATE NOT NULL,
    record_count INT DEFAULT 0,
    last_updated TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (source_id, data_date)
)"""

ENRICHMENT_STATUS = """
CREATE TABLE IF NOT EXISTS enrichment_status (
    content_hash TEXT PRIMARY KEY,
    enriched_at  TIMESTAMPTZ NOT NULL,
    model        TEXT DEFAULT '',
    status       TEXT NOT NULL
)"""

ALL = [INGEST_RUNS, COVERAGE, ENRICHMENT_STATUS]
