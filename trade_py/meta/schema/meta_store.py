"""DDL for MetaStore tables (feed scores, source configs)."""

FEED_SCORES = """
CREATE TABLE IF NOT EXISTS feed_scores (
    feed_name          TEXT PRIMARY KEY,
    computed_at        TIMESTAMPTZ NOT NULL,
    coverage_30d       DOUBLE DEFAULT 0.0,
    uniqueness         DOUBLE DEFAULT 0.0,
    signal_density     DOUBLE DEFAULT 0.0,
    reliability        DOUBLE DEFAULT 0.0,
    timeliness_minutes DOUBLE DEFAULT 0.0,
    composite          DOUBLE DEFAULT 0.0,
    notes              TEXT DEFAULT ''
)"""

SOURCE_CONFIGS = """
CREATE TABLE IF NOT EXISTS source_configs (
    source_id  TEXT PRIMARY KEY,
    updated_at TIMESTAMPTZ NOT NULL,
    config_json TEXT NOT NULL
)"""

ALL = [FEED_SCORES, SOURCE_CONFIGS]
