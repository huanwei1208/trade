"""Source-only architecture baseline validation.

This module deliberately operates below application startup.  It reads the
versioned baseline plus named repository source files through no-follow
descriptors, and uses the Git index only for the bounded warehouse-producer
inventory.  It must not import inspected application modules or inspect data.
"""

from __future__ import annotations

import ast
import hashlib
import io
import os
import re
import select
import signal
import stat
import subprocess
import threading
import time
import tokenize
from array import array
from collections import deque
from collections.abc import Generator, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from trade_py.devtools.toml_compat import tomllib

BASELINE_FILENAME = "architecture-baseline.toml"

CANONICAL_WAREHOUSE_MODULE = "trade_py.data.warehouse.io"
CANONICAL_WAREHOUSE_PACKAGE = "trade_py.data.warehouse"
CANONICAL_WRITERS = frozenset(
    {
        f"{CANONICAL_WAREHOUSE_MODULE}.write_table",
        f"{CANONICAL_WAREHOUSE_MODULE}.upsert_table",
    }
)
CANONICAL_LAYOUT = f"{CANONICAL_WAREHOUSE_MODULE}.WarehouseLayout"

PRODUCER_UNRESOLVED_IMPORT = "architecture.producer_discovery_unresolved_import"
PRODUCER_UNRESOLVED_LAYOUT = "architecture.producer_discovery_unresolved_layout"
PRODUCER_NONLITERAL_TARGET = "architecture.producer_discovery_nonliteral_target"
PRODUCER_UNDECLARED_WRITER = "architecture.producer_discovery_undeclared_writer"
PRODUCER_PATH_BUDGET = "architecture.producer_discovery_path_budget_exceeded"
PRODUCER_SOURCE_BUDGET = "architecture.producer_discovery_budget_exceeded"
PRODUCER_UNSAFE_SOURCE = "architecture.producer_discovery_unsafe_source"
PRODUCER_RESULT_BUDGET = "architecture.producer_discovery_result_budget_exceeded"
PRODUCER_TIMEOUT = "architecture.producer_discovery_tool_timeout"
PRODUCER_TOOL_FAILURE = "architecture.producer_discovery_tool_failed"

_BASELINE_MALFORMED = "architecture.baseline_malformed"
_BASELINE_DUPLICATE = "architecture.baseline_duplicate_declaration"
_BASELINE_MISSING_SOURCE = "architecture.baseline_missing_source"
_BASELINE_UNSAFE_SOURCE = "architecture.baseline_unsafe_source"
_BASELINE_LITERAL_MISMATCH = "architecture.baseline_literal_mismatch"
_BASELINE_INCOMPLETE_PROVENANCE = "architecture.baseline_incomplete_provenance"
_BASELINE_CLASSIFICATION = "architecture.baseline_invalid_classification"
_BASELINE_NONAUTHORIZING = "architecture.baseline_non_authorizing_binding"
_BASELINE_MISSING_ARTIFACT = "architecture.baseline_missing_producer_artifact"
_BASELINE_INVALID_SOURCE = "architecture.baseline_invalid_source"
_BASELINE_STALE_PRODUCER = "architecture.baseline_stale_producer_declaration"
_BASELINE_EVIDENCE_BUDGET = "architecture.baseline_evidence_budget_exceeded"
_RESULT_TRUNCATED = "architecture.guard_result_truncated"

_PROVENANCE_ROLES = frozenset({"bootstrap", "migration", "alter", "data_transform"})
_CLASSIFICATIONS = frozenset({"candidate", "deferred", "approved_binding"})
_DYNAMIC_SQL_LIMITATION_KINDS = frozenset({"dynamic_ddl"})
_REGULAR_GIT_FILE_MODES = frozenset({"100644", "100755"})
_REQUIRED_DYNAMIC_SQL_LIMITATIONS = {
    (
        "Recommendation",
        "trade_py/db/migrations.py",
        'conn.execute(f"ALTER TABLE Recommendation ADD COLUMN {col_def}")',
    ): (
        "recommendation-dynamic-columns",
        "dynamic_ddl",
        "decision-support-boundary",
        "The f-string column definition is dynamic DDL and is non-authorizing until the "
        "Decision Support migration adds reviewed SQL-normalization or runtime migration "
        "evidence.",
    ),
    (
        "RecommendationTrace",
        "trade_py/db/migrations.py",
        'conn.execute(f"ALTER TABLE RecommendationTrace ADD COLUMN {col_def}")',
    ): (
        "recommendation-trace-dynamic-columns",
        "dynamic_ddl",
        "decision-support-boundary",
        "The f-string column definition is dynamic DDL and is non-authorizing until the "
        "Decision Support migration adds reviewed SQL-normalization or runtime migration "
        "evidence.",
    ),
    (
        "factor_registry",
        "trade_py/db/migrations.py",
        'f"ALTER TABLE factor_registry ADD COLUMN {col} REAL NOT NULL DEFAULT {default}"',
    ): (
        "factor-registry-dynamic-columns",
        "dynamic_ddl",
        "study-boundary",
        "The f-string column and default are dynamic DDL and are non-authorizing until the "
        "Study migration adds reviewed SQL-normalization or runtime migration evidence.",
    ),
}
_APPROVED_BINDING_EVIDENCE_FIELDS = (
    "writer_evidence",
    "reader_evidence",
    "transaction_evidence",
    "compatibility_evidence",
)
_NAMED_ADAPTER_SCOPE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")
_NAMED_CALLABLE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_SQL_IDENTIFIER = r'"(?:[^"]|"")+"|`[^`]+`|\[[^\]]+\]|[A-Za-z_][A-Za-z0-9_]*(?![A-Za-z0-9_$])'
_SQL_INSERT_TABLE = re.compile(
    rf"^\s*INSERT\s+(?:OR\s+(?:ABORT|FAIL|IGNORE|REPLACE|ROLLBACK)\s+)?"
    rf"INTO\s+(?P<table>{_SQL_IDENTIFIER})",
    re.IGNORECASE,
)
_SQL_REPLACE_TABLE = re.compile(
    rf"^\s*REPLACE\s+(?:OR\s+(?:ABORT|FAIL|IGNORE|REPLACE|ROLLBACK)\s+)?"
    rf"INTO\s+(?P<table>{_SQL_IDENTIFIER})",
    re.IGNORECASE,
)
_SQL_UPDATE_TABLE = re.compile(
    rf"^\s*UPDATE\s+(?:OR\s+(?:ABORT|FAIL|IGNORE|REPLACE|ROLLBACK)\s+)?"
    rf"(?P<table>{_SQL_IDENTIFIER})",
    re.IGNORECASE,
)
_SQL_DELETE_TABLE = re.compile(
    rf"^\s*DELETE\s+FROM\s+(?P<table>{_SQL_IDENTIFIER})",
    re.IGNORECASE,
)
_SQL_CREATE_TABLE = re.compile(
    rf"^\s*CREATE\s+(?:TEMP(?:ORARY)?\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    rf"(?P<table>{_SQL_IDENTIFIER})",
    re.IGNORECASE,
)
_SQL_DROP_TABLE = re.compile(
    rf"^\s*DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?P<table>{_SQL_IDENTIFIER})",
    re.IGNORECASE,
)
_SQL_SELECT_TABLE = re.compile(
    rf"\b(?:FROM|JOIN)\s+(?P<table>{_SQL_IDENTIFIER})",
    re.IGNORECASE,
)
_SQL_WRITE_TABLE_PATTERNS = (
    _SQL_INSERT_TABLE,
    _SQL_REPLACE_TABLE,
    _SQL_UPDATE_TABLE,
    _SQL_DELETE_TABLE,
    _SQL_CREATE_TABLE,
)
_SQL_TABLE_OPERATION_PATTERNS = (*_SQL_WRITE_TABLE_PATTERNS, _SQL_DROP_TABLE)
_PERSISTENCE_CALL_NAMES = frozenset(
    {"execute", "executemany", "executescript", "fetch", "fetchall", "fetchone", "query"}
)
_BASELINE_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "target_source_root",
        "target_import_root",
        "legacy_package_roots",
        "target_contexts",
        "source_facts",
        "tables",
        "artifacts",
        "capture_risks",
        "dynamic_sql_limitations",
        "interfaces",
        "native_bindings",
        "warehouse_producers",
    }
)
_UNCLASSIFIABLE_FACT_CATEGORIES = frozenset(
    {
        "source_facts",
        "capture_risks",
        "dynamic_sql_limitations",
        "interfaces",
        "native_bindings",
    }
)
_UNKNOWN_BINDING_ROOT = "\0"
_EXCLUDED_SOURCE_SEGMENTS = frozenset(
    {"vendor", "third_party", "generated", "cache", "__pycache__"}
)
_EVIDENCE_ROOTS = frozenset({"src", "trade_py", "trade_web", "tests", "engine"})
_EVIDENCE_SOURCE_SUFFIXES = frozenset(
    {".py", ".pyi", ".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".cmake", ".txt"}
)
_FORBIDDEN_EVIDENCE_ROOTS = frozenset({"data", "warehouse", "market"})
_FORBIDDEN_EVIDENCE_SUFFIXES = frozenset(
    {".db", ".sqlite", ".duckdb", ".parquet", ".json", ".jsonl", ".avro", ".orc"}
)
_FORBIDDEN_EVIDENCE_SEGMENTS = frozenset(
    {
        "artifact",
        "artifacts",
        "manifest",
        "manifests",
        "pointer",
        "pointers",
        "receipt",
        "receipts",
    }
)
_TARGET_CONTEXTS = frozenset(
    {
        "kernel",
        "capture",
        "datasets",
        "studies",
        "decision_support",
        "processes",
        "platform",
        "interfaces",
        "bootstrap",
    }
)
_REQUIRED_CAPTURE_RISK_IDS = frozenset(
    {
        "raw-record-single-publication-clock",
        "cctv-date-only-publication-time",
        "eastmoney-stock-timezone-overwrite",
        "warehouse-rss-fetched-time-substitution",
        "rss-provider-time-fallback",
        "archive-date-only-publication-time",
        "rss-catalog-environment-override",
        "gdelt-catalog-db-config",
        "gdelt-provider-time-fallback",
        "gdelt-streaming-local-state-and-refetch",
        "ingest-wal-replay",
        "warehouse-semantic-quarantine",
        "influence-signal-runtime-publication-time",
    }
)
_REQUIRED_CAPTURE_RISK_BINDINGS = {
    "raw-record-single-publication-clock": (
        "trade_py/intelligence/raw_record.py",
        "published_at: datetime",
        "trade_py.intelligence",
        "capture-boundary",
        "provider-observed-received-available-revision-clocks-collapsed",
        "RawRecord exposes one published_at field for all temporal semantics.",
        "Independent provider, observed, received, available, revision, and finality clocks.",
    ),
    "cctv-date-only-publication-time": (
        "trade_py/data/news/akshare_news.py",
        "pub = datetime(cur.year, cur.month, cur.day, 12, 0, 0, tzinfo=CST)",
        "trade_py.data.news",
        "capture-boundary",
        "date-only-inferred-precision",
        "A date-only provider value is converted to a synthetic noon timestamp.",
        "Preserve source precision and prohibit unproven point-in-time publication claims.",
    ),
    "eastmoney-stock-timezone-overwrite": (
        "trade_py/data/news/akshare_news.py",
        "pub = pub_raw.to_pydatetime().replace(tzinfo=CST)",
        "trade_py.data.news",
        "capture-boundary",
        "provider-timezone-and-precision-overwrite",
        "Parsed provider timestamps are relabeled CST without preserving source timezone or precision.",
        "Preserve provider timezone and precision, and record observed, received, and available clocks before point-in-time use.",
    ),
    "warehouse-rss-fetched-time-substitution": (
        "trade_py/data/warehouse/fetch.py",
        '"published_at": published_at or fetched_at',
        "trade_py.data.warehouse",
        "capture-boundary",
        "provider-timestamp-absence-substitution",
        "Missing provider publication time falls back to fetch time.",
        "Record provider time and received time separately in CaptureArtifact metadata.",
    ),
    "rss-provider-time-fallback": (
        "trade_py/data/news/rss/base.py",
        "pub_time = datetime.now(timezone.utc)",
        "trade_py.data.news.rss",
        "capture-boundary",
        "provider-timestamp-absence-substitution",
        "RSS entries without a provider timestamp substitute the local collection clock.",
        "Persist provider precision separately from observed and received time, and prohibit synthetic event-time PIT claims.",
    ),
    "archive-date-only-publication-time": (
        "trade_py/data/news/rss/archive.py",
        "return datetime.combine(day, time(12, 0), tzinfo=timezone.utc)",
        "trade_py.data.news.rss",
        "capture-boundary",
        "date-only-inferred-precision",
        "Archive day values become synthetic UTC noon timestamps.",
        "Retain date-only precision and use an explicit availability policy.",
    ),
    "rss-catalog-environment-override": (
        "trade_py/data/news/rss/catalog.py",
        'override = os.environ.get("TRADE_RSS_FEED_INDEX_PATH")',
        "trade_py.data.news.rss",
        "capture-boundary",
        "catalog-environment-override-and-absent-rights-evidence",
        "An environment variable can replace the feed index without an immutable SourceManifest.",
        "Versioned SourceManifest with source rights, credentials, and override audit evidence.",
    ),
    "gdelt-catalog-db-config": (
        "trade_py/data/news/gdelt/source.py",
        'load_catalog_payload("catalog.feeds.gdelt", "config/feeds/gdelt.json")',
        "trade_py.data.news.gdelt",
        "capture-boundary",
        "db-first-provider-channel-config",
        "GDELT channel query, language, enablement, and priority are selected from mutable DB-first catalog settings.",
        "Freeze a SourceManifest channel configuration digest in CaptureRequest and support CaptureArtifactRef-only replay without provider access.",
    ),
    "gdelt-provider-time-fallback": (
        "trade_py/data/news/gdelt/source.py",
        "pub = datetime.now(timezone.utc)",
        "trade_py.data.news.gdelt",
        "capture-boundary",
        "provider-timestamp-absence-substitution",
        "Invalid or absent GDELT seendate is replaced with the local collection clock.",
        "Persist provider precision separately from received time and prohibit synthetic event-time PIT claims.",
    ),
    "gdelt-streaming-local-state-and-refetch": (
        "trade_py/data/news/gdelt/source.py",
        "bronze_offsets = scan_bronze_channel_offsets(data_root)",
        "trade_py.data.news.gdelt",
        "capture-boundary",
        "provider-refetch-versus-local-artifact-replay-versus-stateful-stream-cursor",
        "Streaming scans mutable Bronze Parquet and database cursor state while re-fetching the provider and writing Parquet.",
        "Capture checkpoints and immutable segments must support provider-free replay, revision identity, and bounded retry receipts.",
    ),
    "ingest-wal-replay": (
        "trade_py/data/ingest/batch.py",
        "self._recover_wal()",
        "trade_py.data.ingest",
        "capture-boundary",
        "provider-refetch-versus-local-artifact-replay-versus-wal-recovery",
        "WAL recovery writes legacy parquet before a formal Capture receipt exists.",
        "Provider-free replay from immutable CaptureArtifact references and explicit replay receipts.",
    ),
    "warehouse-semantic-quarantine": (
        "trade_py/data/warehouse/articles.py",
        'quality_status = "quarantined"',
        "trade_py.data.warehouse",
        "dataset-product-boundary",
        "transport-integrity-versus-downstream-semantic-quarantine",
        "Article semantic quality marks rows quarantined in the warehouse transform.",
        "Capture transport failures remain distinct from Datasets semantic quality quarantine.",
    ),
    "influence-signal-runtime-publication-time": (
        "trade_py/intelligence/feed_scorer.py",
        "published_at = datetime.now(timezone.utc).isoformat()",
        "trade_py.intelligence.feed_scorer",
        "study-boundary",
        "runtime-evaluation-time-substituted-for-publication-time",
        "Feed scorer uses the local evaluation clock as InfluenceSignal published_at, which is then used to select the most recent reliability record.",
        "Separate source publication, observed, received, evaluation, available, and revision clocks before a Dataset or Study publishes an InfluenceSignal-derived result.",
    ),
}
_REQUIRED_TABLE_BINDINGS = {
    "event_log": (
        "trade_py/db/trade_db.py",
        "CREATE TABLE IF NOT EXISTS event_log",
        "candidate",
        "platform",
        "process-manager-and-platform-boundary",
    ),
    "pipeline_dag": (
        "trade_py/db/trade_db.py",
        "CREATE TABLE IF NOT EXISTS pipeline_dag",
        "deferred",
        "deferred",
        "process-manager-and-platform-boundary",
    ),
    "asset_registry": (
        "trade_py/db/trade_db.py",
        "CREATE TABLE IF NOT EXISTS asset_registry",
        "candidate",
        "capture",
        "capture-boundary",
    ),
    "source_health_daily": (
        "trade_py/db/trade_db.py",
        "CREATE TABLE IF NOT EXISTS source_health_daily",
        "candidate",
        "datasets",
        "dataset-product-boundary",
    ),
    "source_eval_daily": (
        "trade_py/db/trade_db.py",
        "CREATE TABLE IF NOT EXISTS source_eval_daily",
        "candidate",
        "datasets",
        "dataset-product-boundary",
    ),
    "event_eval_runs": (
        "trade_py/db/trade_db.py",
        "CREATE TABLE IF NOT EXISTS event_eval_runs",
        "candidate",
        "studies",
        "study-boundary",
    ),
    "dataset_snapshots": (
        "trade_py/db/trade_db.py",
        "CREATE TABLE IF NOT EXISTS dataset_snapshots",
        "candidate",
        "datasets",
        "dataset-product-boundary",
    ),
    "daily_quality_gate": (
        "trade_py/db/trade_db.py",
        "CREATE TABLE IF NOT EXISTS daily_quality_gate",
        "candidate",
        "datasets",
        "dataset-product-boundary",
    ),
    "event_templates": (
        "trade_py/db/trade_db.py",
        "CREATE TABLE IF NOT EXISTS event_templates",
        "deferred",
        "deferred",
        "dataset-product-boundary",
    ),
    "market_events": (
        "trade_py/db/trade_db.py",
        "CREATE TABLE IF NOT EXISTS market_events",
        "deferred",
        "deferred",
        "dataset-product-boundary",
    ),
    "event_propagations": (
        "trade_py/db/trade_db.py",
        "CREATE TABLE IF NOT EXISTS event_propagations",
        "deferred",
        "deferred",
        "dataset-product-boundary",
    ),
    "causal_decision_snapshots": (
        "trade_py/db/trade_db.py",
        "CREATE TABLE IF NOT EXISTS causal_decision_snapshots",
        "deferred",
        "deferred",
        "study-boundary",
    ),
    "causal_validation_outcomes": (
        "trade_py/db/trade_db.py",
        "CREATE TABLE IF NOT EXISTS causal_validation_outcomes",
        "deferred",
        "deferred",
        "study-boundary",
    ),
    "causal_reward_punishment": (
        "trade_py/db/trade_db.py",
        "CREATE TABLE IF NOT EXISTS causal_reward_punishment",
        "deferred",
        "deferred",
        "study-boundary",
    ),
    "factors": (
        "trade_py/db/trade_db.py",
        "CREATE TABLE IF NOT EXISTS factors",
        "deferred",
        "deferred",
        "study-boundary",
    ),
    "factor_registry": (
        "trade_py/db/trade_db.py",
        "CREATE TABLE IF NOT EXISTS factor_registry",
        "deferred",
        "deferred",
        "study-boundary",
    ),
    "model_registry": (
        "trade_py/db/trade_db.py",
        "CREATE TABLE IF NOT EXISTS model_registry",
        "deferred",
        "deferred",
        "study-boundary",
    ),
    "model_eval_runs": (
        "trade_py/db/trade_db.py",
        "CREATE TABLE IF NOT EXISTS model_eval_runs",
        "deferred",
        "deferred",
        "study-boundary",
    ),
    "kg_nodes": (
        "trade_py/db/trade_db.py",
        "CREATE TABLE IF NOT EXISTS kg_nodes",
        "deferred",
        "deferred",
        "study-boundary",
    ),
    "kg_relations": (
        "trade_py/db/trade_db.py",
        "CREATE TABLE IF NOT EXISTS kg_relations",
        "deferred",
        "deferred",
        "study-boundary",
    ),
    "kg_edge_candidates": (
        "trade_py/db/trade_db.py",
        "CREATE TABLE IF NOT EXISTS kg_edge_candidates",
        "deferred",
        "deferred",
        "study-boundary",
    ),
    "ArticleEvent": (
        "trade_py/db/migrations.py",
        "CREATE TABLE IF NOT EXISTS ArticleEvent",
        "candidate",
        "datasets",
        "dataset-product-boundary",
    ),
    "InfluenceSignal": (
        "trade_py/db/migrations.py",
        "CREATE TABLE IF NOT EXISTS InfluenceSignal",
        "deferred",
        "deferred",
        "study-boundary",
    ),
    "Evidence": (
        "trade_py/db/migrations.py",
        "CREATE TABLE IF NOT EXISTS Evidence",
        "deferred",
        "deferred",
        "study-boundary",
    ),
    "BeliefState": (
        "trade_py/db/migrations.py",
        "CREATE TABLE IF NOT EXISTS BeliefState",
        "deferred",
        "deferred",
        "decision-support-boundary",
    ),
    "AttentionScore": (
        "trade_py/db/migrations.py",
        "CREATE TABLE IF NOT EXISTS AttentionScore",
        "deferred",
        "deferred",
        "decision-support-boundary",
    ),
    "BeliefTransition": (
        "trade_py/db/migrations.py",
        "CREATE TABLE IF NOT EXISTS BeliefTransition",
        "deferred",
        "deferred",
        "decision-support-boundary",
    ),
    "QualityReport": (
        "trade_py/db/migrations.py",
        "CREATE TABLE IF NOT EXISTS QualityReport",
        "candidate",
        "datasets",
        "dataset-product-boundary",
    ),
    "FreshnessStatus": (
        "trade_py/db/migrations.py",
        "CREATE TABLE IF NOT EXISTS FreshnessStatus",
        "candidate",
        "datasets",
        "dataset-product-boundary",
    ),
    "Recommendation": (
        "trade_py/db/migrations.py",
        "CREATE TABLE IF NOT EXISTS Recommendation",
        "deferred",
        "deferred",
        "decision-support-boundary",
    ),
    "RecommendationTrace": (
        "trade_py/db/migrations.py",
        "CREATE TABLE IF NOT EXISTS RecommendationTrace",
        "deferred",
        "deferred",
        "decision-support-boundary",
    ),
    "settings": (
        "trade_py/db/trade_db.py",
        "CREATE TABLE IF NOT EXISTS settings",
        "candidate",
        "platform",
        "process-manager-and-platform-boundary",
    ),
    "watchlist": (
        "trade_py/db/trade_db.py",
        "CREATE TABLE IF NOT EXISTS watchlist",
        "candidate",
        "decision_support",
        "decision-support-boundary",
    ),
    "signals": (
        "trade_py/db/trade_db.py",
        "CREATE TABLE IF NOT EXISTS signals",
        "candidate",
        "decision_support",
        "decision-support-boundary",
    ),
    "job_runs": (
        "trade_py/db/trade_db.py",
        "CREATE TABLE IF NOT EXISTS job_runs",
        "candidate",
        "platform",
        "process-manager-and-platform-boundary",
    ),
    "instruments": (
        "trade_py/db/trade_db.py",
        "CREATE TABLE IF NOT EXISTS instruments",
        "candidate",
        "datasets",
        "dataset-product-boundary",
    ),
    "sector_members": (
        "trade_py/db/trade_db.py",
        "CREATE TABLE IF NOT EXISTS sector_members",
        "candidate",
        "datasets",
        "dataset-product-boundary",
    ),
    "sync_state": (
        "trade_py/db/trade_db.py",
        "CREATE TABLE IF NOT EXISTS sync_state",
        "candidate",
        "capture",
        "capture-boundary",
    ),
    "trading_calendar": (
        "trade_py/db/trade_db.py",
        "CREATE TABLE IF NOT EXISTS trading_calendar",
        "candidate",
        "datasets",
        "dataset-product-boundary",
    ),
    "planned_events": (
        "trade_py/db/trade_db.py",
        "CREATE TABLE IF NOT EXISTS planned_events",
        "candidate",
        "datasets",
        "dataset-product-boundary",
    ),
    "agenda_queue": (
        "trade_py/db/trade_db.py",
        "CREATE TABLE IF NOT EXISTS agenda_queue",
        "candidate",
        "processes",
        "process-manager-and-platform-boundary",
    ),
    "backup_snapshots": (
        "trade_py/db/trade_db.py",
        "CREATE TABLE IF NOT EXISTS backup_snapshots",
        "candidate",
        "platform",
        "process-manager-and-platform-boundary",
    ),
    "ui_snapshots": (
        "trade_py/db/trade_db.py",
        "CREATE TABLE IF NOT EXISTS ui_snapshots",
        "candidate",
        "interfaces",
        "cli-http-sdk-compatibility",
    ),
    "readiness_recovery_actions": (
        "trade_py/db/trade_db.py",
        "CREATE TABLE IF NOT EXISTS readiness_recovery_actions",
        "candidate",
        "processes",
        "process-manager-and-platform-boundary",
    ),
    "schema_migrations": (
        "trade_py/db/migrations.py",
        "CREATE TABLE IF NOT EXISTS schema_migrations",
        "candidate",
        "platform",
        "process-manager-and-platform-boundary",
    ),
    "signal_cache_v2": (
        "trade_py/db/migrations.py",
        "CREATE TABLE IF NOT EXISTS signal_cache_v2",
        "deferred",
        "deferred",
        "decision-support-boundary",
    ),
    "bus_events": (
        "trade_py/db/migrations.py",
        "CREATE TABLE IF NOT EXISTS bus_events",
        "deferred",
        "deferred",
        "process-manager-and-platform-boundary",
    ),
}
_REQUIRED_MULTI_SOURCE_TABLE_PROVENANCE = {
    "catalog_meta": (
        (
            "trade_py/observatory/catalog/store.py",
            "CREATE TABLE catalog_meta",
            "bootstrap",
        ),
    ),
    "catalog_runs": (
        (
            "trade_py/observatory/catalog/store.py",
            "CREATE TABLE runs",
            "bootstrap",
        ),
    ),
    "catalog_releases": (
        (
            "trade_py/observatory/catalog/store.py",
            "CREATE TABLE releases",
            "bootstrap",
        ),
    ),
    "event_log": (
        (
            "trade_py/db/trade_db.py",
            "CREATE TABLE IF NOT EXISTS event_log",
            "bootstrap",
        ),
        (
            "trade_py/db/migrations.py",
            "INSERT OR IGNORE INTO event_log",
            "data_transform",
        ),
    ),
    "event_handler_runs": (
        (
            "trade_py/db/trade_db.py",
            "CREATE TABLE IF NOT EXISTS event_handler_runs",
            "bootstrap",
        ),
        (
            "trade_py/db/migrations.py",
            "CREATE TABLE IF NOT EXISTS event_handler_runs",
            "migration",
        ),
    ),
    "pipeline_dag": (
        (
            "trade_py/db/trade_db.py",
            "CREATE TABLE IF NOT EXISTS pipeline_dag",
            "bootstrap",
        ),
        (
            "trade_py/db/migrations.py",
            "ALTER TABLE pipeline_dag ADD COLUMN config_json TEXT DEFAULT '{}'",
            "alter",
        ),
        (
            "trade_py/db/migrations.py",
            "ALTER TABLE pipeline_dag ADD COLUMN sync_source TEXT",
            "alter",
        ),
        (
            "trade_py/db/migrations.py",
            "ALTER TABLE pipeline_dag ADD COLUMN sync_dataset TEXT",
            "alter",
        ),
        (
            "trade_py/db/migrations.py",
            "ALTER TABLE pipeline_dag ADD COLUMN mode TEXT DEFAULT 'batch'",
            "alter",
        ),
        (
            "trade_py/db/migrations.py",
            "UPDATE pipeline_dag SET sync_source=?, sync_dataset=?",
            "data_transform",
        ),
        (
            "trade_py/db/migrations.py",
            "UPDATE pipeline_dag SET mode='streaming' WHERE job_name=? AND mode='batch'",
            "data_transform",
        ),
        (
            "trade_py/db/migrations.py",
            "UPDATE pipeline_dag SET mode='both' WHERE job_name=? AND mode='batch'",
            "data_transform",
        ),
        (
            "trade_py/db/migrations.py",
            "DELETE FROM pipeline_dag",
            "data_transform",
        ),
        (
            "trade_py/db/migrations.py",
            "UPDATE pipeline_dag SET enabled=0 WHERE job_name='sentiment_pipeline'",
            "data_transform",
        ),
        (
            "trade_py/db/migrations.py",
            "UPDATE pipeline_dag SET enabled=0 WHERE job_name='event_pipeline'",
            "data_transform",
        ),
        (
            "trade_py/db/migrations.py",
            "UPDATE pipeline_dag SET source=?, emits='', description=?",
            "data_transform",
        ),
        (
            "trade_py/db/migrations.py",
            "UPDATE pipeline_dag SET description='BTC assurance-gated UTC 日线同步' WHERE job_name='crypto_btc_fetch'",
            "data_transform",
        ),
        (
            "trade_py/db/migrations.py",
            "UPDATE pipeline_dag SET enabled=0 WHERE job_name='cross_asset_fetch'",
            "data_transform",
        ),
        (
            "trade_py/db/migrations.py",
            "UPDATE pipeline_dag SET config_json=?, description=? WHERE id=?",
            "data_transform",
        ),
    ),
    "asset_registry": (
        (
            "trade_py/db/trade_db.py",
            "CREATE TABLE IF NOT EXISTS asset_registry",
            "bootstrap",
        ),
        (
            "trade_py/db/migrations.py",
            "CREATE INDEX IF NOT EXISTS idx_asset_class ON asset_registry(asset_class, enabled, priority)",
            "migration",
        ),
        (
            "trade_py/db/migrations.py",
            "INSERT INTO asset_registry",
            "data_transform",
        ),
        (
            "trade_py/db/migrations.py",
            "UPDATE asset_registry SET config_json=?, updated_at=CURRENT_TIMESTAMP WHERE asset_id=?",
            "data_transform",
        ),
    ),
    "event_propagations": (
        (
            "trade_py/db/trade_db.py",
            "CREATE TABLE IF NOT EXISTS event_propagations",
            "bootstrap",
        ),
        (
            "trade_py/db/migrations.py",
            "ALTER TABLE event_propagations ADD COLUMN rel_path TEXT",
            "alter",
        ),
        (
            "trade_py/db/migrations.py",
            "ALTER TABLE event_propagations ADD COLUMN validated_at TIMESTAMP",
            "alter",
        ),
    ),
    "job_runs": (
        (
            "trade_py/db/trade_db.py",
            "CREATE TABLE IF NOT EXISTS job_runs",
            "bootstrap",
        ),
        (
            "trade_py/db/migrations.py",
            "ALTER TABLE job_runs ADD COLUMN stage TEXT",
            "alter",
        ),
        (
            "trade_py/db/migrations.py",
            "ALTER TABLE job_runs ADD COLUMN trigger_event_id INTEGER",
            "alter",
        ),
        (
            "trade_py/db/migrations.py",
            "ALTER TABLE job_runs ADD COLUMN result_summary TEXT",
            "alter",
        ),
        (
            "trade_py/db/migrations.py",
            "ALTER TABLE job_runs ADD COLUMN symbols_processed INTEGER",
            "alter",
        ),
        (
            "trade_py/db/migrations.py",
            "ALTER TABLE job_runs ADD COLUMN elapsed_ms INTEGER",
            "alter",
        ),
        (
            "trade_py/db/migrations.py",
            "ALTER TABLE job_runs ADD COLUMN completed_at TIMESTAMP",
            "alter",
        ),
    ),
    "instruments": (
        (
            "trade_py/db/trade_db.py",
            "CREATE TABLE IF NOT EXISTS instruments",
            "bootstrap",
        ),
        (
            "trade_py/db/trade_db.py",
            "ALTER TABLE instruments ADD COLUMN total_shares INTEGER DEFAULT 0",
            "alter",
        ),
        (
            "trade_py/db/trade_db.py",
            "ALTER TABLE instruments ADD COLUMN float_shares INTEGER DEFAULT 0",
            "alter",
        ),
        (
            "trade_py/db/trade_db.py",
            "ALTER TABLE instruments ADD COLUMN market_name TEXT NOT NULL DEFAULT ''",
            "alter",
        ),
    ),
    "kg_relations": (
        (
            "trade_py/db/trade_db.py",
            "CREATE TABLE IF NOT EXISTS kg_relations",
            "bootstrap",
        ),
        (
            "trade_py/db/migrations.py",
            "ALTER TABLE kg_relations ADD COLUMN direction INTEGER NOT NULL DEFAULT 1",
            "alter",
        ),
        (
            "trade_py/db/migrations.py",
            "ALTER TABLE kg_relations ADD COLUMN typical_days INTEGER NOT NULL DEFAULT 0",
            "alter",
        ),
        (
            "trade_py/db/migrations.py",
            "ALTER TABLE kg_relations ADD COLUMN confidence REAL NOT NULL DEFAULT 0.0",
            "alter",
        ),
        (
            "trade_py/db/migrations.py",
            "ALTER TABLE kg_relations ADD COLUMN sample_count INTEGER NOT NULL DEFAULT 0",
            "alter",
        ),
        (
            "trade_py/db/migrations.py",
            "ALTER TABLE kg_relations ADD COLUMN evidence_json TEXT",
            "alter",
        ),
        (
            "trade_py/db/migrations.py",
            "ALTER TABLE kg_relations ADD COLUMN status TEXT NOT NULL DEFAULT 'active'",
            "alter",
        ),
        (
            "trade_py/db/migrations.py",
            "ALTER TABLE kg_relations ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            "alter",
        ),
        (
            "trade_py/db/migrations.py",
            "UPDATE kg_relations",
            "data_transform",
        ),
        (
            "trade_py/db/migrations.py",
            "UPDATE kg_relations SET weight = ABS(weight) WHERE weight < 0",
            "data_transform",
        ),
        (
            "trade_py/db/migrations.py",
            "UPDATE kg_relations SET status = 'active' WHERE status IS NULL OR status = ''",
            "data_transform",
        ),
    ),
    "kg_edge_candidates": (
        (
            "trade_py/db/trade_db.py",
            "CREATE TABLE IF NOT EXISTS kg_edge_candidates",
            "bootstrap",
        ),
        (
            "trade_py/db/migrations.py",
            "CREATE TABLE IF NOT EXISTS kg_edge_candidates",
            "migration",
        ),
    ),
    "model_registry": (
        (
            "trade_py/db/trade_db.py",
            "CREATE TABLE IF NOT EXISTS model_registry",
            "bootstrap",
        ),
        (
            "trade_py/db/trade_db.py",
            "ALTER TABLE model_registry ADD COLUMN target_name TEXT",
            "alter",
        ),
        (
            "trade_py/db/trade_db.py",
            "ALTER TABLE model_registry ADD COLUMN backend TEXT DEFAULT 'lgbm'",
            "alter",
        ),
        (
            "trade_py/db/trade_db.py",
            "ALTER TABLE model_registry ADD COLUMN artifact_format TEXT DEFAULT 'joblib'",
            "alter",
        ),
        (
            "trade_py/db/trade_db.py",
            "ALTER TABLE model_registry ADD COLUMN feature_set TEXT",
            "alter",
        ),
        (
            "trade_py/db/trade_db.py",
            "ALTER TABLE model_registry ADD COLUMN dataset_snapshot_id INTEGER",
            "alter",
        ),
        (
            "trade_py/db/trade_db.py",
            "ALTER TABLE model_registry ADD COLUMN promotion_state TEXT NOT NULL DEFAULT 'active'",
            "alter",
        ),
        (
            "trade_py/db/trade_db.py",
            "UPDATE model_registry SET target_name=COALESCE(target_name, model_name)",
            "data_transform",
        ),
        (
            "trade_py/db/trade_db.py",
            "UPDATE model_registry SET backend=",
            "data_transform",
        ),
        (
            "trade_py/db/trade_db.py",
            "UPDATE model_registry SET artifact_format=",
            "data_transform",
        ),
        (
            "trade_py/db/trade_db.py",
            "UPDATE model_registry SET promotion_state=",
            "data_transform",
        ),
    ),
    "signals": (
        (
            "trade_py/db/trade_db.py",
            "CREATE TABLE IF NOT EXISTS signals",
            "bootstrap",
        ),
        (
            "trade_py/db/migrations.py",
            "INSERT OR IGNORE INTO signals",
            "data_transform",
        ),
    ),
    "sector_members": (
        (
            "trade_py/db/trade_db.py",
            "CREATE TABLE IF NOT EXISTS sector_members",
            "bootstrap",
        ),
        (
            "trade_py/db/migrations.py",
            "INSERT OR IGNORE INTO sector_members",
            "data_transform",
        ),
    ),
    "market_events": (
        (
            "trade_py/db/trade_db.py",
            "CREATE TABLE IF NOT EXISTS market_events",
            "bootstrap",
        ),
        (
            "trade_py/db/migrations.py",
            "INSERT OR IGNORE INTO market_events",
            "data_transform",
        ),
    ),
    "sync_state": (
        (
            "trade_py/db/trade_db.py",
            "CREATE TABLE IF NOT EXISTS sync_state",
            "bootstrap",
        ),
        (
            "trade_py/db/migrations.py",
            "INSERT OR IGNORE INTO sync_state",
            "data_transform",
        ),
        (
            "trade_py/db/migrations.py",
            "INSERT OR REPLACE INTO sync_state",
            "data_transform",
        ),
    ),
    "ui_snapshots": (
        (
            "trade_py/db/trade_db.py",
            "CREATE TABLE IF NOT EXISTS ui_snapshots",
            "bootstrap",
        ),
        (
            "trade_py/db/migrations.py",
            "CREATE TABLE IF NOT EXISTS ui_snapshots",
            "migration",
        ),
    ),
    "signal_cache_v2": (
        (
            "trade_py/db/migrations.py",
            "CREATE TABLE IF NOT EXISTS signal_cache_v2",
            "migration",
        ),
        (
            "trade_py/db/migrations.py",
            "INSERT OR IGNORE INTO signal_cache_v2",
            "data_transform",
        ),
        (
            "trade_py/db/migrations.py",
            "ALTER TABLE signal_cache_v2 RENAME TO signal_cache",
            "alter",
        ),
    ),
    "bus_events": (
        (
            "trade_py/db/migrations.py",
            "CREATE TABLE IF NOT EXISTS bus_events",
            "migration",
        ),
        (
            "trade_py/db/migrations.py",
            "DROP TABLE IF EXISTS bus_events",
            "alter",
        ),
    ),
}
_REQUIRED_ARTIFACT_BINDINGS = {
    "warehouse-parquet": (
        "trade_py/data/warehouse/io.py",
        'f"{table}.parquet"',
        "legacy-warehouse-artifact-family",
        "candidate",
        "datasets",
        "dataset-product-boundary",
    ),
    "catalog-sqlite-projection": (
        "trade_py/observatory/catalog/store.py",
        'return base / "catalog.sqlite", base / "generation.json"',
        "rebuildable-catalog-projection",
        "candidate",
        "datasets",
        "dataset-product-boundary",
    ),
    "catalog-generation-pointer": (
        "trade_py/observatory/catalog/store.py",
        'return base / "catalog.sqlite", base / "generation.json"',
        "catalog-generation-pointer",
        "candidate",
        "datasets",
        "dataset-product-boundary",
    ),
    "crypto-ads-current-pointer": (
        "trade_py/data/warehouse/crypto_store.py",
        'CRYPTO_VALIDATION_CURRENT = "_crypto_validation_current.json"',
        "legacy-current-pointer",
        "candidate",
        "datasets",
        "dataset-product-boundary",
    ),
    "crypto-ads-validation-receipt": (
        "trade_py/data/warehouse/crypto_store.py",
        'receipt_root = ads_root / "_validation_receipts"',
        "completion-receipt",
        "candidate",
        "datasets",
        "dataset-product-boundary",
    ),
    "btc-compatibility-pointer": (
        "trade_py/data/market/crypto/store.py",
        'self.current_path = self.crypto_root / "btc_current.json"',
        "legacy-current-pointer",
        "candidate",
        "datasets",
        "dataset-product-boundary",
    ),
    "kline-reconciliation-operation-pointer": (
        "trade_py/data/operations/checks.py",
        'path = root / "market" / "kline" / "reconciliation" / "current.json"',
        "data-operation-reconciliation-pointer",
        "deferred",
        "deferred",
        "dataset-product-boundary",
    ),
    "kline-reconciliation-pointer": (
        "trade_py/utils/data_inspector.py",
        'return KLINE_DIR(data_root) / "reconciliation" / "current.json"',
        "legacy-reconciliation-pointer",
        "deferred",
        "deferred",
        "dataset-product-boundary",
    ),
}
_GIT_ENVIRONMENT_OVERRIDES = frozenset(
    {
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_COMMON_DIR",
        "GIT_DIR",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_WORK_TREE",
    }
)


@dataclass(frozen=True)
class DiscoveryLimits:
    """Hard ceilings for the source-only producer discovery pass."""

    max_raw_records: int = 1_024
    max_raw_path_bytes: int = 128 * 1024
    max_included_paths: int = 512
    max_included_path_bytes: int = 64 * 1024
    max_source_bytes: int = 32 * 1024 * 1024
    max_file_bytes: int = 1 * 1024 * 1024
    max_evidence_bytes: int = 1 * 1024 * 1024
    max_evidence_python_tokens: int = 100_000
    max_baseline_entries: int = 512
    max_total_baseline_entries: int = 1_024
    max_evidence_sources: int = 512
    max_aggregate_evidence_bytes: int = 8 * 1024 * 1024
    max_evidence_literals_per_source: int = 256
    max_evidence_literal_bytes_per_source: int = 64 * 1024
    max_callable_proof_operations: int = 256
    max_callable_proof_sql_bytes: int = 64 * 1024
    max_discovered_producers: int = 1_024
    max_producer_literal_bytes: int = 8 * 1024
    max_producer_report_bytes: int = 256 * 1024
    max_ast_nodes_per_file: int = 250_000
    max_ast_depth: int = 512
    max_findings: int = 64
    max_diagnostic_field_bytes: int = 1_024
    max_git_record_bytes: int = 128 * 1024 + 512
    max_git_stderr_bytes: int = 4 * 1024
    git_timeout_seconds: float = 30.0


DEFAULT_LIMITS = DiscoveryLimits()


@dataclass(frozen=True)
class ArchitectureFinding:
    rule_id: str
    path: str
    line: int | None
    message: str
    remediation: str


@dataclass(frozen=True)
class WarehouseProducer:
    source: str
    line: int
    column: int
    writer: str
    layer: str
    table: str
    literal: str
    call_digest: str

    @property
    def artifact_key(self) -> str:
        return f"{self.layer}.{self.table}"

    @property
    def declaration_key(self) -> tuple[str, int, int, str, str, str, str, str]:
        return (
            self.source,
            self.line,
            self.column,
            self.writer,
            self.layer,
            self.table,
            self.literal,
            self.call_digest,
        )


@dataclass(frozen=True)
class ArchitectureReport:
    findings: tuple[ArchitectureFinding, ...]
    producers: tuple[WarehouseProducer, ...]
    omitted_findings_count: int = 0

    @property
    def ok(self) -> bool:
        return not self.findings and self.omitted_findings_count == 0


@dataclass(frozen=True)
class _SourceSignature:
    device: int
    inode: int
    size: int
    mtime_ns: int
    ctime_ns: int


@dataclass(frozen=True)
class _Utf8ColumnMap:
    """Map AST UTF-8 byte columns to decoded source character columns."""

    character_columns: array

    def character_column(self, byte_column: int) -> int:
        if byte_column < 0 or byte_column >= len(self.character_columns):
            return byte_column
        return self.character_columns[byte_column]


class _GuardError(RuntimeError):
    def __init__(
        self,
        rule_id: str,
        path: str,
        message: str,
        remediation: str,
        *,
        line: int | None = None,
    ) -> None:
        super().__init__(message)
        self.finding = ArchitectureFinding(rule_id, path, line, message, remediation)


@dataclass(frozen=True)
class _Baseline:
    target_contexts: frozenset[str]
    source_facts: tuple[Mapping[str, Any], ...]
    tables: tuple[Mapping[str, Any], ...]
    artifacts: tuple[Mapping[str, Any], ...]
    capture_risks: tuple[Mapping[str, Any], ...]
    dynamic_sql_limitations: tuple[Mapping[str, Any], ...]
    interfaces: tuple[Mapping[str, Any], ...]
    native_bindings: tuple[Mapping[str, Any], ...]
    producers: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class _PersistenceOperation:
    sql: str
    line: int
    receiver: tuple[str, ...]
    transaction_receivers: frozenset[tuple[str, ...]]


@dataclass(frozen=True)
class _ExternalBindingDeclaration:
    name: str
    kind: str
    line: int


@dataclass(frozen=True)
class _TransactionProofRejection:
    declaration: _ExternalBindingDeclaration
    target: str
    with_line: int
    candidate_sql: tuple[str, ...]


@dataclass(frozen=True)
class _CallableProofSummary:
    callable_line: int
    operations: tuple[_PersistenceOperation, ...]
    transaction_rejections: tuple[_TransactionProofRejection, ...]


@dataclass
class _EvidenceReader:
    """Memoize descriptor-verified and executable source evidence for one run."""

    root: Path
    limits: DiscoveryLimits
    _payloads: dict[str, bytes]
    _decoded_text: dict[str, str]
    _executable_text: dict[str, str]
    _python_trees: dict[str, ast.Module]
    _callable_proof_summaries: dict[tuple[str, str], _CallableProofSummary]
    _callable_proof_failures: dict[tuple[str, str], ArchitectureFinding]
    _executable_failures: dict[str, ArchitectureFinding]
    _literal_matches: dict[tuple[str, str], bool]
    _aggregate_bytes: int = 0

    def __init__(self, root: Path, limits: DiscoveryLimits) -> None:
        self.root = root
        self.limits = limits
        self._payloads = {}
        self._decoded_text = {}
        self._executable_text = {}
        self._python_trees = {}
        self._callable_proof_summaries = {}
        self._callable_proof_failures = {}
        self._executable_failures = {}
        self._literal_matches = {}

    def read(self, relative: str) -> bytes:
        cached = self._payloads.get(relative)
        if cached is not None:
            return cached
        if len(self._payloads) >= self.limits.max_evidence_sources:
            raise _baseline_evidence_budget_error(
                relative,
                "declared source-evidence file count exceeds the configured aggregate budget",
            )
        remaining_bytes = self.limits.max_aggregate_evidence_bytes - self._aggregate_bytes
        read_limit = min(self.limits.max_evidence_bytes, remaining_bytes)
        try:
            payload = _safe_read_relative(
                self.root,
                relative,
                max_bytes=read_limit,
            )
        except _GuardError as exc:
            if (
                exc.finding.rule_id != PRODUCER_SOURCE_BUDGET
                or read_limit == self.limits.max_evidence_bytes
            ):
                raise
            raise _baseline_evidence_budget_error(
                relative,
                "declared source-evidence bytes exceed the configured aggregate budget",
            ) from exc
        if len(payload) > remaining_bytes:
            raise _baseline_evidence_budget_error(
                relative,
                "declared source-evidence bytes exceed the configured aggregate budget",
            )
        self._payloads[relative] = payload
        self._aggregate_bytes += len(payload)
        return payload

    def executable_text(self, relative: str) -> str:
        cached = self._executable_text.get(relative)
        if cached is not None:
            return cached
        failure = self._executable_failures.get(relative)
        if failure is not None:
            raise _GuardError(
                failure.rule_id,
                failure.path,
                failure.message,
                failure.remediation,
                line=failure.line,
            )
        try:
            decoded = self._decoded_text.get(relative)
            if decoded is None:
                decoded = self.read(relative).decode("utf-8")
                self._decoded_text[relative] = decoded
            if PurePosixPath(relative).suffix in {".py", ".pyi"}:
                executable = _live_python_source_text(
                    decoded,
                    source=relative,
                    max_tokens=self.limits.max_evidence_python_tokens,
                )
            else:
                executable = _live_non_python_source_text(decoded, source=relative)
        except UnicodeDecodeError:
            failure = ArchitectureFinding(
                _BASELINE_UNSAFE_SOURCE,
                relative,
                None,
                "declared evidence source is not valid UTF-8",
                "Keep declared evidence as stable UTF-8 source inside the repository.",
            )
        except (RecursionError, SyntaxError, tokenize.TokenError):
            failure = ArchitectureFinding(
                _BASELINE_INVALID_SOURCE,
                relative,
                None,
                "declared Python evidence source cannot be parsed safely",
                "Repair the source before relying on it as architecture baseline evidence.",
            )
        except _GuardError as exc:
            failure = exc.finding
        else:
            self._executable_text[relative] = executable
            return executable
        self._executable_failures[relative] = failure
        raise _GuardError(
            failure.rule_id,
            failure.path,
            failure.message,
            failure.remediation,
            line=failure.line,
        )

    def literal_is_present(self, relative: str, literal: str) -> bool:
        """Memoize one executable literal lookup per source/literal pair."""

        key = (relative, literal)
        cached = self._literal_matches.get(key)
        if cached is not None:
            return cached
        text = self.executable_text(relative)
        present = _literal_is_present(text, literal)
        self._literal_matches[key] = present
        return present

    def python_tree(self, relative: str) -> ast.Module:
        """Return one parsed Python module after source evidence is admitted."""

        cached = self._python_trees.get(relative)
        if cached is not None:
            return cached
        if PurePosixPath(relative).suffix not in {".py", ".pyi"}:
            raise _GuardError(
                _BASELINE_CLASSIFICATION,
                relative,
                "approved adapter evidence must be Python source",
                "Bind approved persistence proofs to the named target adapter Python module.",
            )
        self.executable_text(relative)
        source = self._decoded_text[relative]
        try:
            tree = ast.parse(source, filename=relative)
        except (RecursionError, SyntaxError) as exc:
            raise _GuardError(
                _BASELINE_INVALID_SOURCE,
                relative,
                "approved adapter evidence source cannot be parsed safely",
                "Repair the target adapter source before using it as approved-binding evidence.",
            ) from exc
        self._python_trees[relative] = tree
        return tree

    def callable_proof_summary(
        self,
        relative: str,
        callable_name: str,
    ) -> _CallableProofSummary | None:
        """Return one direct-scope persistence summary for an adapter callable."""

        key = (relative, callable_name)
        cached = self._callable_proof_summaries.get(key)
        if cached is not None:
            return cached
        failure = self._callable_proof_failures.get(key)
        if failure is not None:
            raise _GuardError(
                failure.rule_id,
                failure.path,
                failure.message,
                failure.remediation,
                line=failure.line,
            )
        callable_node = _adapter_callable(self.python_tree(relative), callable_name)
        if callable_node is None:
            return None
        try:
            summary = _summarize_callable_proof(
                callable_node,
                source=relative,
                limits=self.limits,
            )
        except _GuardError as exc:
            self._callable_proof_failures[key] = exc.finding
            raise
        except RecursionError as exc:
            failure = _baseline_evidence_budget_error(
                relative,
                "approved-binding callable proof exceeds the guarded AST traversal depth",
                remediation=(
                    "Reduce callable nesting or make a reviewed approved-binding "
                    "AST-depth-budget increase."
                ),
            )
            self._callable_proof_failures[key] = failure.finding
            raise failure from exc
        self._callable_proof_summaries[key] = summary
        return summary

    def prime_literal_matches(self, queries: Sequence[tuple[str, str]]) -> None:
        """Evaluate each declared source's pending literals in one source scan."""

        grouped: dict[str, set[str]] = {}
        for source, literal in queries:
            if (
                _is_allowed_evidence_source(source)
                and (source, literal) not in self._literal_matches
            ):
                grouped.setdefault(source, set()).add(literal)
        for source, literals in grouped.items():
            literal_bytes = sum(len(literal.encode("utf-8")) for literal in literals)
            if (
                len(literals) > self.limits.max_evidence_literals_per_source
                or literal_bytes > self.limits.max_evidence_literal_bytes_per_source
            ):
                failure = _baseline_evidence_budget_error(
                    source,
                    "declared source-evidence literals exceed the configured per-source "
                    "literal-count or literal-byte budget",
                    remediation=(
                        "Reduce duplicate source literals, split the governed evidence source, "
                        "or make a reviewed per-source literal-budget increase."
                    ),
                )
                self._executable_failures[source] = failure.finding
                continue
            try:
                text = self.executable_text(source)
            except _GuardError:
                # Individual validation replays the cached failure with fact context.
                continue
            matches = _literal_matches_for_source(text, literals)
            self._literal_matches.update(
                ((source, literal), present) for literal, present in matches.items()
            )


def validate_architecture_baseline(
    repo_root: Path | str,
    *,
    baseline_name: str = BASELINE_FILENAME,
    limits: DiscoveryLimits = DEFAULT_LIMITS,
) -> ArchitectureReport:
    """Validate the architecture baseline without loading application code.

    A source-discovery failure intentionally returns no producers.  Consumers
    therefore cannot mistake a truncated inventory for an empty or complete one.
    """

    root = Path(repo_root)
    from trade_py.devtools.target_architecture_guard import validate_target_architecture

    target_findings = list(validate_target_architecture(root))
    findings: list[ArchitectureFinding] = []
    try:
        baseline = _load_baseline(root, baseline_name, limits)
    except _GuardError as exc:
        return _report((*target_findings, exc.finding), (), limits)

    evidence = _EvidenceReader(root, limits)
    evidence.prime_literal_matches(_baseline_evidence_queries(baseline))
    findings.extend(_validate_baseline_facts(root, baseline, evidence))
    if findings:
        return _report((*target_findings, *findings), (), limits)

    findings.extend(_declared_producer_source_missing(root, baseline, limits))
    if findings:
        return _report((*target_findings, *findings), (), limits)

    try:
        producers = discover_warehouse_producers(root, limits=limits)
    except _GuardError as exc:
        return _report((*target_findings, exc.finding), (), limits)

    findings.extend(_validate_producer_declarations(root, baseline, producers, limits))
    findings = [*target_findings, *findings]
    return _report(findings, producers if not findings else (), limits)


def discover_warehouse_producers(
    repo_root: Path | str,
    *,
    limits: DiscoveryLimits = DEFAULT_LIMITS,
) -> tuple[WarehouseProducer, ...]:
    """Return every bounded, tracked production call to a canonical writer."""

    root = Path(repo_root)
    raw_records = 0
    raw_path_bytes = 0
    included_path_bytes = 0
    included_paths: set[str] = set()
    aggregate_source_bytes = 0
    producers: list[WarehouseProducer] = []
    findings: list[ArchitectureFinding] = []

    for mode, path in _iter_git_index(root, limits=limits):
        raw_records += 1
        raw_path_bytes += len(path.encode("utf-8"))
        if raw_records > limits.max_raw_records or raw_path_bytes > limits.max_raw_path_bytes:
            raise _producer_path_budget_error(
                path,
                "raw Git-index record or raw path-byte budget exceeded before AST parsing",
            )
        if path.startswith("trade_py/") and not _is_safe_relative_path(path):
            raise _unsafe_source_error(path, "Git index path escapes the repository")
        if _is_production_python_candidate_path(path) and mode not in _REGULAR_GIT_FILE_MODES:
            raise _unsafe_source_error(
                path,
                "Git index production Python source is not a regular file",
            )
        if not _is_production_python_path(path, mode):
            continue
        if path in included_paths:
            raise _GuardError(
                _BASELINE_DUPLICATE,
                path,
                "Git index produced a duplicate production source path",
                "Repair the index so each tracked source has one canonical path.",
            )
        included_paths.add(path)
        included_path_bytes += len(path.encode("utf-8"))
        if (
            len(included_paths) > limits.max_included_paths
            or included_path_bytes > limits.max_included_path_bytes
        ):
            raise _producer_path_budget_error(
                path,
                "included producer path-count or path-byte budget exceeded before AST parsing",
            )

        payload = _safe_read_relative(root, path, max_bytes=limits.max_file_bytes)
        aggregate_source_bytes += len(payload)
        if aggregate_source_bytes > limits.max_source_bytes:
            raise _producer_source_budget_error(
                path,
                "aggregate producer source-byte budget exceeded before AST parsing",
            )
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise _GuardError(
                PRODUCER_UNSAFE_SOURCE,
                path,
                "production source is not valid UTF-8",
                "Keep the inspected source as a stable UTF-8 regular file inside the repository.",
            ) from exc
        parsed, source_findings = _discover_in_source(
            path,
            text,
            limits=limits,
            producer_capacity=limits.max_discovered_producers - len(producers),
            finding_capacity=limits.max_findings - len(findings),
            producer_report_capacity=limits.max_producer_report_bytes
            - _producer_report_size(producers),
        )
        producers.extend(parsed)
        findings.extend(source_findings)
        if len(producers) > limits.max_discovered_producers:
            raise _producer_result_budget_error(
                path,
                "canonical writer-call inventory exceeds the configured result budget",
            )
        if len(findings) > limits.max_findings:
            raise _producer_result_budget_error(
                path,
                "producer discovery findings exceed the configured result budget",
            )
    if findings:
        first = _ordered_findings(findings)[0]
        raise _GuardError(
            first.rule_id,
            first.path,
            first.message,
            first.remediation,
            line=first.line,
        )
    return tuple(
        sorted(
            producers,
            key=lambda item: (item.source, item.line, item.column, item.writer),
        )
    )


def _load_baseline(root: Path, baseline_name: str, limits: DiscoveryLimits) -> _Baseline:
    if not _is_safe_relative_path(baseline_name):
        raise _GuardError(
            _BASELINE_MALFORMED,
            baseline_name,
            "baseline name must be a repository-relative file path",
            "Use a regular repository-relative baseline file.",
        )
    try:
        payload = _safe_read_relative(root, baseline_name, max_bytes=limits.max_evidence_bytes)
        parsed = tomllib.loads(payload.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise _GuardError(
            _BASELINE_MALFORMED,
            baseline_name,
            "baseline is not valid UTF-8 TOML",
            "Write the baseline as UTF-8 TOML.",
        ) from exc
    except tomllib.TOMLDecodeError as exc:
        raise _GuardError(
            _BASELINE_MALFORMED,
            baseline_name,
            f"baseline TOML cannot be parsed: {exc}",
            "Repair the baseline TOML syntax and required declarations.",
        ) from exc
    except RecursionError as exc:
        raise _GuardError(
            _BASELINE_MALFORMED,
            baseline_name,
            "baseline TOML exceeds the supported parser recursion depth",
            "Reduce baseline nesting and keep declarations as bounded flat tables.",
        ) from exc
    except _GuardError:
        raise

    if not isinstance(parsed, dict):
        raise _GuardError(
            _BASELINE_MALFORMED,
            baseline_name,
            "baseline TOML root must be a table",
            "Use a TOML table with the required architecture declarations.",
        )
    unexpected_keys = sorted(set(parsed) - _BASELINE_TOP_LEVEL_KEYS)
    if unexpected_keys:
        raise _GuardError(
            _BASELINE_MALFORMED,
            baseline_name,
            "baseline contains unsupported top-level declarations: " + ", ".join(unexpected_keys),
            "Use only the governed baseline schema fields; introduce a new resource "
            "authorization schema through its separately reviewed owning child.",
        )
    schema_version = parsed.get("schema_version")
    if type(schema_version) is not int or schema_version != 1:
        raise _GuardError(
            _BASELINE_MALFORMED,
            baseline_name,
            "baseline schema_version must equal 1",
            "Use the supported architecture baseline schema version.",
        )
    target_source_root = _require_text(parsed, "target_source_root", baseline_name)
    target_import_root = _require_text(parsed, "target_import_root", baseline_name)
    if target_source_root != "src/trade" or target_import_root != "trade":
        raise _GuardError(
            _BASELINE_MALFORMED,
            baseline_name,
            "baseline must freeze target_source_root='src/trade' and target_import_root='trade'",
            "Keep the target filesystem and import roots distinct and explicit.",
        )
    _require_string_list(parsed, "legacy_package_roots", baseline_name)
    target_contexts = _require_string_list(parsed, "target_contexts", baseline_name)
    target_context_set = frozenset(target_contexts)
    if len(target_context_set) != len(target_contexts):
        raise _GuardError(
            _BASELINE_MALFORMED,
            baseline_name,
            "baseline target_contexts must not contain duplicate Context names",
            "List each governed target Context exactly once.",
        )
    if target_context_set != _TARGET_CONTEXTS:
        raise _GuardError(
            _BASELINE_MALFORMED,
            baseline_name,
            "baseline target_contexts must exactly match the approved architecture vocabulary",
            "Update the governed architecture design before changing the target Context vocabulary.",
        )

    collections = {
        "source_facts": _read_table_array(parsed, "source_facts", baseline_name),
        "tables": _read_table_array(parsed, "tables", baseline_name),
        "artifacts": _read_table_array(parsed, "artifacts", baseline_name),
        "capture_risks": _read_table_array(parsed, "capture_risks", baseline_name),
        "dynamic_sql_limitations": _read_table_array(
            parsed,
            "dynamic_sql_limitations",
            baseline_name,
        ),
        "interfaces": _read_table_array(parsed, "interfaces", baseline_name),
        "native_bindings": _read_table_array(parsed, "native_bindings", baseline_name),
        "producers": _read_table_array(parsed, "warehouse_producers", baseline_name),
    }
    for name, items in collections.items():
        if not items or len(items) > limits.max_baseline_entries:
            raise _GuardError(
                _BASELINE_MALFORMED,
                baseline_name,
                f"baseline must declare one through {limits.max_baseline_entries} {name} entries",
                "Record the audited source-only facts within the governed baseline-entry limit.",
            )
    total_entries = sum(len(items) for items in collections.values())
    if total_entries > limits.max_total_baseline_entries:
        raise _GuardError(
            _BASELINE_MALFORMED,
            baseline_name,
            "baseline declarations exceed the configured aggregate entry budget",
            "Reduce duplicate declarations or make a reviewed governed aggregate budget increase.",
        )

    return _Baseline(target_contexts=target_context_set, **collections)


def _validate_baseline_facts(
    root: Path,
    baseline: _Baseline,
    evidence: _EvidenceReader,
) -> list[ArchitectureFinding]:
    findings: list[ArchitectureFinding] = []
    seen_ids: set[str] = set()
    artifact_ids: set[str] = set()

    for category, facts in (
        ("source_facts", baseline.source_facts),
        ("artifacts", baseline.artifacts),
        ("capture_risks", baseline.capture_risks),
        ("dynamic_sql_limitations", baseline.dynamic_sql_limitations),
        ("interfaces", baseline.interfaces),
        ("native_bindings", baseline.native_bindings),
        ("warehouse_producers", baseline.producers),
    ):
        for fact in facts:
            try:
                fact_id = _require_text(fact, "id", category)
                if fact_id in seen_ids:
                    raise _GuardError(
                        _BASELINE_DUPLICATE,
                        BASELINE_FILENAME,
                        f"duplicate baseline declaration id: {fact_id}",
                        "Give each declared source fact one stable, unique id.",
                    )
                seen_ids.add(fact_id)
                if category == "artifacts":
                    artifact_ids.add(fact_id)
                if category not in {"dynamic_sql_limitations", "warehouse_producers"}:
                    _validate_common_fact(root, fact, category, evidence)
                if category in _UNCLASSIFIABLE_FACT_CATEGORIES:
                    _reject_unclassifiable_binding_fields(fact, category)
                if category == "artifacts":
                    _validate_classification(
                        root,
                        fact,
                        category,
                        baseline.target_contexts,
                        evidence,
                    )
                    _require_text(fact, "role", category)
                elif category == "capture_risks":
                    _require_text(fact, "risk_kind", category)
                    _require_text(fact, "current_behavior", category)
                    _require_text(fact, "required_migration_proof", category)
                elif category == "dynamic_sql_limitations":
                    _validate_source_literal(root, fact, evidence)
                    _require_text(fact, "logical_name", category)
                    limitation_kind = _require_text(fact, "limitation_kind", category)
                    if limitation_kind not in _DYNAMIC_SQL_LIMITATION_KINDS:
                        raise _GuardError(
                            _BASELINE_INCOMPLETE_PROVENANCE,
                            BASELINE_FILENAME,
                            f"dynamic SQL limitation has unsupported kind {limitation_kind!r}",
                            "Use dynamic_ddl only for the bounded reviewed nonliteral DDL inventory.",
                        )
                    _require_text(fact, "owning_child", category)
                    _require_text(fact, "limitation", category)
                    if fact.get("non_authorizing") is not True:
                        raise _GuardError(
                            _BASELINE_NONAUTHORIZING,
                            BASELINE_FILENAME,
                            "dynamic SQL limitation must declare non_authorizing = true",
                            "Keep dynamic SQL limitation records explicitly non-authorizing.",
                        )
                elif category == "interfaces":
                    _require_text(fact, "surface_kind", category)
                    _require_text(fact, "current_behavior", category)
                    _require_text(fact, "compatibility_owner", category)
                elif category == "native_bindings":
                    _require_text(fact, "current_binding", category)
                    _require_text(fact, "reserved_binding", category)
                elif category == "warehouse_producers":
                    _validate_classification(
                        root,
                        fact,
                        category,
                        baseline.target_contexts,
                        evidence,
                    )
                    _require_text(fact, "current_owner", category)
                    _require_text(fact, "required_child", category)
                    _require_text(fact, "layer", category)
                    _require_text(fact, "table", category)
                    _require_text(fact, "path_role", category)
                    _require_text(fact, "artifact_id", category)
            except _GuardError as exc:
                findings.append(exc.finding)

    capture_risks_by_id: dict[str, Mapping[str, Any]] = {}
    for fact in baseline.capture_risks:
        risk_id = fact.get("id")
        if isinstance(risk_id, str):
            capture_risks_by_id[risk_id] = fact
    missing_capture_risks = sorted(_REQUIRED_CAPTURE_RISK_IDS - set(capture_risks_by_id))
    unexpected_capture_risks = sorted(set(capture_risks_by_id) - _REQUIRED_CAPTURE_RISK_IDS)
    invalid_capture_risks = [
        risk_id
        for risk_id, (
            source,
            literal,
            current_owner,
            required_child,
            risk_kind,
            current_behavior,
            required_migration_proof,
        ) in _REQUIRED_CAPTURE_RISK_BINDINGS.items()
        if risk_id in capture_risks_by_id
        and (
            capture_risks_by_id[risk_id].get("source") != source
            or capture_risks_by_id[risk_id].get("literal") != literal
            or capture_risks_by_id[risk_id].get("current_owner") != current_owner
            or capture_risks_by_id[risk_id].get("required_child") != required_child
            or capture_risks_by_id[risk_id].get("risk_kind") != risk_kind
            or capture_risks_by_id[risk_id].get("current_behavior") != current_behavior
            or capture_risks_by_id[risk_id].get("required_migration_proof")
            != required_migration_proof
        )
    ]
    if missing_capture_risks or unexpected_capture_risks or invalid_capture_risks:
        risk_details: list[str] = []
        if missing_capture_risks:
            risk_details.append("missing " + ", ".join(missing_capture_risks))
        if unexpected_capture_risks:
            risk_details.append("ungoverned " + ", ".join(unexpected_capture_risks))
        if invalid_capture_risks:
            risk_details.append("misbound " + ", ".join(sorted(invalid_capture_risks)))
        findings.append(
            ArchitectureFinding(
                _BASELINE_MALFORMED,
                BASELINE_FILENAME,
                None,
                "baseline omits or misbinds required Capture-risk declarations: "
                + "; ".join(risk_details),
                "Keep the Task 2.1 Capture-risk inventory exactly governed; add a new "
                "record only through its owning child with separately reviewed source scope "
                "and a refreshed binding.",
            )
        )

    required_interface_kinds = {
        "cli-facade",
        "cli-domain",
        "cli-compatibility",
        "http-app",
        "http-openapi",
        "http-router",
        "sse",
        "http-contract-test",
    }
    interface_kinds = {
        fact.get("surface_kind")
        for fact in baseline.interfaces
        if isinstance(fact.get("surface_kind"), str)
    }
    missing_interface_kinds = sorted(required_interface_kinds - interface_kinds)
    if missing_interface_kinds:
        findings.append(
            ArchitectureFinding(
                _BASELINE_MALFORMED,
                BASELINE_FILENAME,
                None,
                "baseline omits required interface surface kinds: "
                + ", ".join(missing_interface_kinds),
                "Record the audited CLI, HTTP, OpenAPI, SSE, and contract-test source facts.",
            )
        )

    tables_by_name: dict[str, Mapping[str, Any]] = {}
    for table in baseline.tables:
        try:
            name = _require_text(table, "logical_name", "tables")
            if name in tables_by_name:
                raise _GuardError(
                    _BASELINE_DUPLICATE,
                    BASELINE_FILENAME,
                    f"duplicate logical table declaration: {name}",
                    "Declare each logical table exactly once and retain all provenance on it.",
                )
            tables_by_name[name] = table
            _require_text(table, "current_owner", "tables")
            _require_text(table, "semantic_kind", "tables")
            _require_text(table, "reason", "tables")
            _require_text(table, "required_child", "tables")
            _validate_classification(
                root,
                table,
                "tables",
                baseline.target_contexts,
                evidence,
            )
            provenance = table.get("provenance")
            if not isinstance(provenance, list) or not provenance:
                raise _GuardError(
                    _BASELINE_INCOMPLETE_PROVENANCE,
                    BASELINE_FILENAME,
                    f"logical table {name} has no source provenance",
                    "Record each bootstrap, migration, alter, or transform source that defines it.",
                )
            for item in provenance:
                if not isinstance(item, dict):
                    raise _GuardError(
                        _BASELINE_INCOMPLETE_PROVENANCE,
                        BASELINE_FILENAME,
                        f"logical table {name} has malformed provenance",
                        "Use table provenance records with source, literal, and role.",
                    )
                role = _require_text(item, "role", f"tables.{name}.provenance")
                if role not in _PROVENANCE_ROLES:
                    raise _GuardError(
                        _BASELINE_INCOMPLETE_PROVENANCE,
                        BASELINE_FILENAME,
                        f"logical table {name} has unsupported provenance role {role!r}",
                        "Use bootstrap, migration, alter, or data_transform provenance roles.",
                    )
                _validate_source_literal(root, item, evidence)
        except _GuardError as exc:
            findings.append(exc.finding)

    required_table_names = set(_REQUIRED_TABLE_BINDINGS) | set(
        _REQUIRED_MULTI_SOURCE_TABLE_PROVENANCE
    )
    missing_table_names = sorted(required_table_names - set(tables_by_name))
    invalid_table_bindings = [
        name
        for name, (
            source,
            literal,
            classification,
            target_context,
            required_child,
        ) in _REQUIRED_TABLE_BINDINGS.items()
        if name in tables_by_name
        and (
            tables_by_name[name].get("classification") != classification
            or tables_by_name[name].get("target_context") != target_context
            or tables_by_name[name].get("required_child") != required_child
            or not _has_provenance_literal(tables_by_name[name], source, literal)
        )
    ]
    invalid_table_bindings.extend(
        name
        for name, requirements in _REQUIRED_MULTI_SOURCE_TABLE_PROVENANCE.items()
        if name in tables_by_name
        and any(
            not _has_provenance_record(tables_by_name[name], source, literal, role)
            for source, literal, role in requirements
        )
    )
    if missing_table_names or invalid_table_bindings:
        details = []
        if missing_table_names:
            details.append("missing " + ", ".join(missing_table_names))
        if invalid_table_bindings:
            details.append("misbound or misclassified " + ", ".join(sorted(invalid_table_bindings)))
        findings.append(
            ArchitectureFinding(
                _BASELINE_MALFORMED,
                BASELINE_FILENAME,
                None,
                "baseline omits or misclassifies required central-schema declarations: "
                + "; ".join(details),
                "Record each audited legacy table with its reviewed source literal, current "
                "classification, target Context, and responsible child change.",
            )
        )

    _validate_dynamic_sql_limitations(
        baseline.dynamic_sql_limitations,
        tables_by_name,
        findings,
    )

    artifacts_by_id = {
        fact.get("id"): fact for fact in baseline.artifacts if isinstance(fact.get("id"), str)
    }
    missing_artifact_ids = sorted(set(_REQUIRED_ARTIFACT_BINDINGS) - set(artifacts_by_id))
    invalid_artifact_bindings = [
        artifact_id
        for artifact_id, (
            source,
            literal,
            role,
            classification,
            target_context,
            required_child,
        ) in _REQUIRED_ARTIFACT_BINDINGS.items()
        if artifact_id in artifacts_by_id
        and (
            artifacts_by_id[artifact_id].get("source") != source
            or artifacts_by_id[artifact_id].get("literal") != literal
            or artifacts_by_id[artifact_id].get("role") != role
            or artifacts_by_id[artifact_id].get("classification") != classification
            or artifacts_by_id[artifact_id].get("target_context") != target_context
            or artifacts_by_id[artifact_id].get("required_child") != required_child
        )
    ]
    if missing_artifact_ids or invalid_artifact_bindings:
        details: list[str] = []
        if missing_artifact_ids:
            details.append("missing " + ", ".join(missing_artifact_ids))
        if invalid_artifact_bindings:
            details.append("misbound " + ", ".join(sorted(invalid_artifact_bindings)))
        findings.append(
            ArchitectureFinding(
                _BASELINE_MALFORMED,
                BASELINE_FILENAME,
                None,
                "baseline omits or misbinds required artifact, pointer, and receipt facts: "
                + "; ".join(details),
                "Record every audited artifact family, projection, pointer, and receipt with its "
                "reviewed source, literal, role, classification, target Context, and child change.",
            )
        )

    for producer in baseline.producers:
        artifact_id = producer.get("artifact_id")
        if not isinstance(artifact_id, str) or not artifact_id:
            # _validate_baseline_facts already records the malformed declaration.
            # Do not let an unhashable TOML value escape the fail-closed report path.
            continue
        if artifact_id not in artifact_ids:
            findings.append(
                ArchitectureFinding(
                    _BASELINE_MISSING_ARTIFACT,
                    BASELINE_FILENAME,
                    None,
                    f"warehouse producer {producer.get('id', '<unknown>')} references "
                    f"missing artifact declaration {artifact_id!r}",
                    "Add a reviewed source-only artifact declaration for the produced table.",
                )
            )
    return findings


def _has_provenance_literal(table: Mapping[str, Any], source: str, literal: str) -> bool:
    return _has_provenance_record(table, source, literal, role=None)


def _has_provenance_record(
    table: Mapping[str, Any],
    source: str,
    literal: str,
    role: str | None,
) -> bool:
    provenance = table.get("provenance")
    return isinstance(provenance, list) and any(
        isinstance(item, dict)
        and item.get("source") == source
        and item.get("literal") == literal
        and (role is None or item.get("role") == role)
        for item in provenance
    )


def _declared_producer_source_missing(
    root: Path,
    baseline: _Baseline,
    limits: DiscoveryLimits,
) -> list[ArchitectureFinding]:
    """Classify a deleted declaration without charging a second full source read."""

    findings: list[ArchitectureFinding] = []
    for declaration in baseline.producers:
        source = declaration.get("source")
        if not isinstance(source, str) or not _is_safe_relative_path(source):
            continue
        try:
            _safe_verify_relative(root, source, max_bytes=limits.max_file_bytes)
        except _GuardError as exc:
            if isinstance(exc.__cause__, FileNotFoundError):
                findings.append(
                    ArchitectureFinding(
                        _BASELINE_MISSING_SOURCE,
                        source,
                        None,
                        "declared warehouse producer source does not exist",
                        "Update or remove the producer declaration with reviewed inventory evidence.",
                    )
                )
    return findings


def _validate_producer_declarations(
    root: Path,
    baseline: _Baseline,
    producers: Sequence[WarehouseProducer],
    limits: DiscoveryLimits,
) -> list[ArchitectureFinding]:
    findings: list[ArchitectureFinding] = []
    declarations: dict[tuple[str, int, int, str, str, str, str, str], Mapping[str, Any]] = {}
    for declaration in baseline.producers:
        try:
            _validate_producer_declaration(declaration)
        except _GuardError as exc:
            findings.append(exc.finding)
            continue
        key = _producer_declaration_key(declaration)
        if key in declarations:
            findings.append(
                ArchitectureFinding(
                    _BASELINE_DUPLICATE,
                    BASELINE_FILENAME,
                    None,
                    "duplicate warehouse producer declaration for "
                    f"{key[0]}:{key[1]}:{key[2]} {key[3]} {key[4]}.{key[5]}",
                    "Keep one declaration per canonical writer call identity.",
                )
            )
            continue
        declarations[key] = declaration

    for producer in producers:
        key = producer.declaration_key
        if key not in declarations:
            findings.append(
                ArchitectureFinding(
                    PRODUCER_UNDECLARED_WRITER,
                    producer.source,
                    producer.line,
                    f"canonical writer {producer.writer} produces undeclared "
                    f"{producer.artifact_key}",
                    "Add a reviewed baseline declaration for this producer and its artifact.",
                )
            )
    producer_keys = {producer.declaration_key for producer in producers}
    for key in declarations:
        if key not in producer_keys:
            findings.append(
                ArchitectureFinding(
                    _BASELINE_STALE_PRODUCER,
                    key[0],
                    key[1],
                    "declared canonical warehouse writer call is absent or changed: "
                    f"{key[3]} {key[4]}.{key[5]}",
                    "Update the reviewed baseline declaration after reconciling the changed writer call.",
                )
            )
    return findings


def _validate_producer_declaration(declaration: Mapping[str, Any]) -> None:
    source = _require_text(declaration, "source", "warehouse_producers")
    if not _is_production_python_path(source, "100644"):
        raise _GuardError(
            _BASELINE_MALFORMED,
            source,
            "warehouse producer source must be a production Python path beneath trade_py",
            "Declare only a source that belongs to the bounded producer-discovery universe.",
        )
    _require_text(declaration, "id", "warehouse_producers")
    _require_text(declaration, "literal", "warehouse_producers")
    _require_text(declaration, "current_owner", "warehouse_producers")
    _require_text(declaration, "required_child", "warehouse_producers")
    _require_text(declaration, "path_role", "warehouse_producers")
    _require_text(declaration, "artifact_id", "warehouse_producers")
    line = declaration.get("line")
    column = declaration.get("column")
    writer = declaration.get("writer")
    layer = declaration.get("layer")
    table = declaration.get("table")
    call_digest = declaration.get("call_digest")
    if (
        not isinstance(line, int)
        or line < 1
        or not isinstance(column, int)
        or column < 0
        or writer not in CANONICAL_WRITERS
        or not isinstance(layer, str)
        or not layer
        or not isinstance(table, str)
        or not table
        or not isinstance(call_digest, str)
        or len(call_digest) != 64
        or any(character not in "0123456789abcdef" for character in call_digest)
    ):
        raise _GuardError(
            _BASELINE_MALFORMED,
            source,
            "warehouse producer declaration requires positive line, nonnegative column, "
            "canonical writer, and non-empty literal layer/table",
            "Record the exact AST-discovered writer call identity in the baseline.",
        )


def _producer_declaration_key(
    declaration: Mapping[str, Any],
) -> tuple[str, int, int, str, str, str, str, str]:
    return (
        str(declaration["source"]),
        int(declaration["line"]),
        int(declaration["column"]),
        str(declaration["writer"]),
        str(declaration["layer"]),
        str(declaration["table"]),
        str(declaration["literal"]),
        str(declaration["call_digest"]),
    )


def _validate_common_fact(
    root: Path,
    fact: Mapping[str, Any],
    category: str,
    evidence: _EvidenceReader,
) -> None:
    _require_text(fact, "current_owner", category)
    _require_text(fact, "required_child", category)
    _validate_source_literal(root, fact, evidence)


def _baseline_evidence_queries(baseline: _Baseline) -> tuple[tuple[str, str], ...]:
    """Collect source/literal evidence requests without treating producers as evidence."""

    queries: set[tuple[str, str]] = set()
    for facts in (
        baseline.source_facts,
        baseline.tables,
        baseline.artifacts,
        baseline.capture_risks,
        baseline.dynamic_sql_limitations,
        baseline.interfaces,
        baseline.native_bindings,
    ):
        for fact in facts:
            _collect_source_literal_queries(fact, queries)
    return tuple(sorted(queries))


def _collect_source_literal_queries(
    value: object,
    queries: set[tuple[str, str]],
) -> None:
    if isinstance(value, Mapping):
        source = value.get("source")
        literal = value.get("literal")
        if isinstance(source, str) and source and isinstance(literal, str) and literal:
            queries.add((source, literal))
        for child in value.values():
            _collect_source_literal_queries(child, queries)
    elif isinstance(value, list):
        for child in value:
            _collect_source_literal_queries(child, queries)


def _validate_dynamic_sql_limitations(
    limitations: Sequence[Mapping[str, Any]],
    tables_by_name: Mapping[str, Mapping[str, Any]],
    findings: list[ArchitectureFinding],
) -> None:
    """Ensure the closed Task 2.1 dynamic-DDL set stays non-authorizing."""

    seen: set[tuple[str, str, str]] = set()
    declared: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for limitation in limitations:
        try:
            logical_name = _require_text(limitation, "logical_name", "dynamic_sql_limitations")
            source = _require_text(limitation, "source", "dynamic_sql_limitations")
            literal = _require_text(limitation, "literal", "dynamic_sql_limitations")
            key = (logical_name, source, literal)
            if key in seen:
                raise _GuardError(
                    _BASELINE_DUPLICATE,
                    BASELINE_FILENAME,
                    f"duplicate dynamic SQL limitation for {logical_name} at {source}: {literal}",
                    "Record each nonliteral SQL construction site once.",
                )
            seen.add(key)
            declared[key] = limitation
            if logical_name not in tables_by_name:
                raise _GuardError(
                    _BASELINE_INCOMPLETE_PROVENANCE,
                    BASELINE_FILENAME,
                    f"dynamic SQL limitation names undeclared table {logical_name!r}",
                    "Declare the logical table before recording its nonliteral SQL limitation.",
                )
            table = tables_by_name[logical_name]
            if table.get("classification") == "approved_binding":
                raise _GuardError(
                    _BASELINE_NONAUTHORIZING,
                    BASELINE_FILENAME,
                    f"dynamic SQL limitation cannot authorize approved table {logical_name!r}",
                    "Move dynamic SQL behind a separately reviewed static or runtime evidence "
                    "design before authorizing the table.",
                )
            if limitation.get("owning_child") != table.get("required_child"):
                raise _GuardError(
                    _BASELINE_INCOMPLETE_PROVENANCE,
                    BASELINE_FILENAME,
                    f"dynamic SQL limitation for {logical_name} is not owned by its table migration child",
                    "Bind the limitation to the same required child as the audited table.",
                )
        except _GuardError as exc:
            findings.append(exc.finding)
    invalid = [
        logical_name
        for (
            logical_name,
            source,
            literal,
        ), (
            limitation_id,
            limitation_kind,
            owning_child,
            limitation_text,
        ) in _REQUIRED_DYNAMIC_SQL_LIMITATIONS.items()
        if (
            (record := declared.get((logical_name, source, literal))) is None
            or record.get("id") != limitation_id
            or record.get("limitation_kind") != limitation_kind
            or record.get("owning_child") != owning_child
            or record.get("limitation") != limitation_text
            or record.get("non_authorizing") is not True
        )
    ]
    if invalid:
        findings.append(
            ArchitectureFinding(
                _BASELINE_MALFORMED,
                BASELINE_FILENAME,
                None,
                "baseline omits or misbinds required dynamic SQL limitations: "
                + ", ".join(sorted(invalid)),
                "Record each reviewed dynamic SQL construction site with its table, source, "
                "limitation kind, owning child, and non-authorizing limitation rationale.",
            )
        )
    unexpected = sorted(set(declared) - set(_REQUIRED_DYNAMIC_SQL_LIMITATIONS))
    if unexpected:
        findings.append(
            ArchitectureFinding(
                _BASELINE_MALFORMED,
                BASELINE_FILENAME,
                None,
                "baseline contains ungoverned dynamic SQL limitations: "
                + ", ".join(f"{logical_name}@{source}" for logical_name, source, _ in unexpected),
                "Keep Task 2.1 limited to its reviewed dynamic-DDL construction sites; "
                "govern dynamic DML or data transforms in their owning child.",
            )
        )


def _validate_source_literal(
    root: Path,
    fact: Mapping[str, Any],
    evidence: _EvidenceReader,
) -> None:
    source = _require_text(fact, "source", "source fact")
    literal = _require_text(fact, "literal", "source fact")
    if not _is_allowed_evidence_source(source):
        raise _GuardError(
            _BASELINE_UNSAFE_SOURCE,
            source,
            "declared evidence source is outside the source-only admission policy",
            "Declare only approved repository source or build-definition evidence; never data, "
            "artifacts, manifests, pointers, receipts, or database files.",
        )
    try:
        evidence.read(source)
    except _GuardError as exc:
        if exc.__cause__ and isinstance(exc.__cause__, FileNotFoundError):
            raise _GuardError(
                _BASELINE_MISSING_SOURCE,
                source,
                "declared evidence source does not exist",
                "Update or remove the baseline declaration with the corresponding migration evidence.",
            ) from exc
        if exc.finding.rule_id == PRODUCER_UNSAFE_SOURCE:
            raise _GuardError(
                _BASELINE_UNSAFE_SOURCE,
                source,
                exc.finding.message,
                exc.finding.remediation,
            ) from exc
        raise
    try:
        literal_is_present = evidence.literal_is_present(source, literal)
    except UnicodeDecodeError as exc:
        raise _GuardError(
            _BASELINE_UNSAFE_SOURCE,
            source,
            "declared evidence source is not valid UTF-8",
            "Keep declared evidence as stable UTF-8 source inside the repository.",
        ) from exc
    except (RecursionError, SyntaxError, tokenize.TokenError) as exc:
        raise _GuardError(
            _BASELINE_INVALID_SOURCE,
            source,
            "declared Python evidence source cannot be parsed safely",
            "Repair the source before relying on it as architecture baseline evidence.",
        ) from exc
    if not literal_is_present:
        raise _GuardError(
            _BASELINE_LITERAL_MISMATCH,
            source,
            "declared source literal is absent: "
            + _bounded_text(literal, evidence.limits.max_diagnostic_field_bytes),
            "Update the baseline fact and its migration evidence with the changed source literal.",
        )


def _literal_is_present(text: str, literal: str) -> bool:
    """Match a literal against cached executable source evidence."""

    start = text.find(literal)
    requires_boundary = _requires_sql_table_boundary(literal)
    while start != -1:
        end = start + len(literal)
        if (
            not requires_boundary
            or end == len(text)
            or not _is_sql_identifier_continuation(text[end])
        ):
            return True
        start = text.find(literal, end)
    return False


def _literal_matches_for_source(text: str, literals: set[str]) -> Mapping[str, bool]:
    """Match pending literals in one deterministic Aho-Corasick source scan."""

    table_boundary_literals = {
        literal for literal in literals if _requires_sql_table_boundary(literal)
    }
    transitions: list[dict[str, int]] = [{}]
    failures = [0]
    terminals: list[str | None] = [None]
    for literal in sorted(literals):
        node = 0
        for character in literal:
            next_node = transitions[node].get(character)
            if next_node is None:
                next_node = len(transitions)
                transitions[node][character] = next_node
                transitions.append({})
                failures.append(0)
                terminals.append(None)
            node = next_node
        terminals[node] = literal

    pending = deque(transitions[0].values())
    output_links = [-1] * len(transitions)
    while pending:
        node = pending.popleft()
        for character, child in transitions[node].items():
            pending.append(child)
            fallback = failures[node]
            while fallback and character not in transitions[fallback]:
                fallback = failures[fallback]
            failures[child] = transitions[fallback].get(character, 0)
            failure = failures[child]
            output_links[child] = (
                failure if terminals[failure] is not None else output_links[failure]
            )

    retired: set[int] = set()
    next_active = output_links.copy()

    def active_terminal(node: int) -> int:
        if node == -1 or node not in retired:
            return node
        next_active[node] = active_terminal(next_active[node])
        return next_active[node]

    def retire_terminal(node: int) -> None:
        retired.add(node)
        next_active[node] = active_terminal(output_links[node])

    matched: set[str] = set()
    node = 0
    for index, character in enumerate(text):
        while node and character not in transitions[node]:
            node = failures[node]
        node = transitions[node].get(character, 0)

        output = node if terminals[node] is not None else output_links[node]
        while output != -1:
            output = active_terminal(output)
            if output == -1:
                break
            literal = terminals[output]
            assert literal is not None
            if (
                literal in table_boundary_literals
                and index + 1 < len(text)
                and _is_sql_identifier_continuation(text[index + 1])
            ):
                output = output_links[output]
                continue
            matched.add(literal)
            retire_terminal(output)
        if len(matched) == len(literals):
            break

    return {literal: literal in matched for literal in literals}


def _requires_sql_table_boundary(literal: str) -> bool:
    for pattern in (*_SQL_TABLE_OPERATION_PATTERNS, _SQL_SELECT_TABLE):
        match = pattern.search(literal)
        if match is not None and match.end("table") == len(literal):
            return True
    return False


def _is_sql_identifier_continuation(character: str) -> bool:
    return character.isascii() and (character.isalnum() or character in {"_", "$"})


def _live_python_source_text(text: str, *, source: str, max_tokens: int) -> str:
    """Mask comments and bare string expressions without changing code offsets."""

    _validate_python_evidence_token_budget(text, source=source, max_tokens=max_tokens)
    tree = ast.parse(text)
    line_offsets = _source_line_offsets(text)
    utf8_column_maps = _source_utf8_column_maps(text)
    inert_string_spans = _inert_python_string_spans(tree, line_offsets, utf8_column_maps)
    characters = list(text)
    inert_span_index = 0
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        token_start = _source_position_offset(line_offsets, token.start)
        token_end = _source_position_offset(line_offsets, token.end)
        while (
            inert_span_index < len(inert_string_spans)
            and inert_string_spans[inert_span_index][1] <= token_start
        ):
            inert_span_index += 1
        is_inert_string = (
            token.type == tokenize.STRING
            and inert_span_index < len(inert_string_spans)
            and inert_string_spans[inert_span_index][0] < token_end
        )
        if token.type != tokenize.COMMENT and not is_inert_string:
            continue
        _mask_source_span(characters, token_start, token_end)
    return "".join(characters)


def _validate_python_evidence_token_budget(text: str, *, source: str, max_tokens: int) -> None:
    for token_count, _ in enumerate(
        tokenize.generate_tokens(io.StringIO(text).readline),
        start=1,
    ):
        if token_count > max_tokens:
            raise _baseline_evidence_budget_error(
                source,
                f"declared Python evidence exceeds the {max_tokens} token pre-parse budget",
                remediation=(
                    "Reduce or split the declared Python source evidence, or make a reviewed "
                    "governed Python-token-budget increase."
                ),
            )


def _source_line_offsets(text: str) -> tuple[int, ...]:
    offsets = [0]
    for line in text.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    return tuple(offsets)


def _source_utf8_column_maps(text: str) -> Mapping[int, _Utf8ColumnMap]:
    return {
        line_number: _utf8_column_map(line)
        for line_number, line in enumerate(text.splitlines(keepends=True), start=1)
        if not line.isascii()
    }


def _utf8_column_map(line: str) -> _Utf8ColumnMap:
    character_columns = array("I", [0])
    character_column = 0
    for character in line:
        byte_width = _utf8_character_width(character)
        if byte_width > 1:
            character_columns.extend([character_column] * (byte_width - 1))
        character_column += 1
        character_columns.append(character_column)
    return _Utf8ColumnMap(character_columns)


def _utf8_character_width(character: str) -> int:
    codepoint = ord(character)
    if codepoint <= 0x7F:
        return 1
    if codepoint <= 0x7FF:
        return 2
    if codepoint <= 0xFFFF:
        return 3
    return 4


def _source_position_offset(line_offsets: Sequence[int], position: tuple[int, int]) -> int:
    line, column = position
    if line < 1 or line >= len(line_offsets):
        return line_offsets[-1]
    return line_offsets[line - 1] + column


def _inert_python_string_spans(
    tree: ast.AST,
    line_offsets: Sequence[int],
    utf8_column_maps: Mapping[int, _Utf8ColumnMap],
) -> tuple[tuple[int, int], ...]:
    spans: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Expr)
            and _is_inert_literal_expression(node.value)
            and node.end_lineno is not None
            and node.end_col_offset is not None
        ):
            spans.append(
                (
                    _ast_source_position_offset(
                        line_offsets,
                        utf8_column_maps,
                        (node.lineno, node.col_offset),
                    ),
                    _ast_source_position_offset(
                        line_offsets,
                        utf8_column_maps,
                        (node.end_lineno, node.end_col_offset),
                    ),
                )
            )
    return tuple(sorted(spans))


def _is_inert_literal_expression(node: ast.expr) -> bool:
    return (isinstance(node, ast.Constant) and isinstance(node.value, (bytes, str))) or isinstance(
        node, ast.JoinedStr
    )


def _ast_source_position_offset(
    line_offsets: Sequence[int],
    utf8_column_maps: Mapping[int, _Utf8ColumnMap],
    position: tuple[int, int],
) -> int:
    """Convert AST UTF-8 byte columns to offsets in the decoded source text."""

    line, column = position
    if line < 1 or line >= len(line_offsets):
        return line_offsets[-1]
    column_map = utf8_column_maps.get(line)
    character_column = column if column_map is None else column_map.character_column(column)
    return line_offsets[line - 1] + character_column


def _mask_source_span(characters: list[str], start: int, end: int) -> None:
    for index in range(max(0, start), min(len(characters), end)):
        if characters[index] not in "\r\n":
            characters[index] = " "


def _live_non_python_source_text(text: str, *, source: str) -> str:
    """Mask comments in admitted shell, CMake, and C-family evidence files."""

    suffix = PurePosixPath(source).suffix.lower()
    characters = list(text)
    if source == "trade" or suffix in {".cmake", ".txt"}:
        _mask_line_comments(characters, "#")
    elif suffix in {".c", ".cc", ".cpp", ".cxx", ".h", ".hpp"}:
        _mask_c_family_comments(characters)
    return "".join(characters)


def _mask_line_comments(characters: list[str], marker: str) -> None:
    start = 0
    while start < len(characters):
        if characters[start] == marker:
            end = start
            while end < len(characters) and characters[end] not in "\r\n":
                end += 1
            _mask_source_span(characters, start, end)
            start = end
        else:
            start += 1


def _mask_c_family_comments(characters: list[str]) -> None:
    index = 0
    while index + 1 < len(characters):
        pair = "".join(characters[index : index + 2])
        if pair == "//":
            end = index + 2
            while end < len(characters) and characters[end] not in "\r\n":
                end += 1
            _mask_source_span(characters, index, end)
            index = end
        elif pair == "/*":
            end = index + 2
            while end + 1 < len(characters) and "".join(characters[end : end + 2]) != "*/":
                end += 1
            _mask_source_span(characters, index, min(len(characters), end + 2))
            index = end + 2
        else:
            index += 1


def _is_allowed_evidence_source(source: str) -> bool:
    if source == "trade":
        return True
    if not _is_safe_relative_path(source):
        return False
    pure = PurePosixPath(source)
    lowered_parent_parts = tuple(part.lower() for part in pure.parts[:-1])
    if pure.parts[0] in _FORBIDDEN_EVIDENCE_ROOTS:
        return False
    if pure.parts[0] not in _EVIDENCE_ROOTS:
        return False
    suffix = pure.suffix.lower()
    if suffix not in _EVIDENCE_SOURCE_SUFFIXES:
        return False
    if pure.parts[0] in {"trade_py", "trade_web", "tests"} and suffix not in {".py", ".pyi"}:
        return False
    return (
        not any(part in _FORBIDDEN_EVIDENCE_SEGMENTS for part in lowered_parent_parts)
        and pure.suffix.lower() not in _FORBIDDEN_EVIDENCE_SUFFIXES
    )


def _validate_classification(
    root: Path,
    fact: Mapping[str, Any],
    category: str,
    target_contexts: frozenset[str],
    evidence: _EvidenceReader,
) -> None:
    classification = _require_text(fact, "classification", category)
    if classification not in _CLASSIFICATIONS:
        raise _GuardError(
            _BASELINE_CLASSIFICATION,
            BASELINE_FILENAME,
            f"{category} has unsupported classification {classification!r}",
            "Use candidate, deferred, or a separately reviewed approved_binding.",
        )
    target_context = _require_text(fact, "target_context", category)
    if classification == "deferred":
        if target_context != "deferred":
            raise _GuardError(
                _BASELINE_CLASSIFICATION,
                BASELINE_FILENAME,
                f"{category} deferred declaration must target 'deferred'",
                "Keep unproven ownership explicitly deferred until its child proves an owner.",
            )
        _reject_non_authorizing_binding(fact, category)
        _require_text(fact, "reason", category)
        return
    if target_context == "deferred":
        raise _GuardError(
            _BASELINE_CLASSIFICATION,
            BASELINE_FILENAME,
            f"{category} {classification} declaration cannot target 'deferred'",
            "Name the candidate or approved Context explicitly.",
        )
    if target_context not in target_contexts:
        raise _GuardError(
            _BASELINE_CLASSIFICATION,
            BASELINE_FILENAME,
            f"{category} target_context {target_context!r} is not a declared target Context",
            "Use one Context from the baseline target_contexts controlled vocabulary.",
        )
    if classification == "candidate":
        _reject_non_authorizing_binding(fact, category)
        return
    if category != "tables":
        raise _GuardError(
            _BASELINE_NONAUTHORIZING,
            BASELINE_FILENAME,
            f"{category} approved binding is unsupported without a table-specific "
            "authorization contract",
            "Keep artifacts and warehouse producers candidate or deferred until their "
            "owning child introduces a separately reviewed authorization contract.",
        )
    _require_text(fact, "adapter_scope", category)
    adapter_scope = str(fact["adapter_scope"])
    adapter_scope_prefix = f"{target_context}.adapters."
    adapter_scope_suffix = adapter_scope[len(adapter_scope_prefix) :]
    if (
        not adapter_scope.startswith(adapter_scope_prefix)
        or _NAMED_ADAPTER_SCOPE.fullmatch(adapter_scope_suffix) is None
    ):
        raise _GuardError(
            _BASELINE_CLASSIFICATION,
            BASELINE_FILENAME,
            f"{category} approved binding adapter_scope must name a persistence adapter beneath {target_context}.adapters",
            "Use <target_context>.adapters.<identifier>[.<identifier>...].",
        )
    for field in _APPROVED_BINDING_EVIDENCE_FIELDS:
        proof = fact.get(field)
        if not isinstance(proof, Mapping):
            raise _GuardError(
                _BASELINE_MALFORMED,
                BASELINE_FILENAME,
                f"{category} approved binding must declare {field} as a source/literal record",
                "Use a repository source and executable literal for every approved-binding proof.",
            )
    _validate_approved_table_binding(
        fact,
        adapter_scope=adapter_scope,
        evidence=evidence,
    )


def _reject_non_authorizing_binding(fact: Mapping[str, Any], category: str) -> None:
    binding_fields = (
        "approved_binding",
        "adapter_scope",
        *_APPROVED_BINDING_EVIDENCE_FIELDS,
    )
    if any(field in fact for field in binding_fields):
        raise _GuardError(
            _BASELINE_NONAUTHORIZING,
            BASELINE_FILENAME,
            f"{category} audit-only declaration must not contain a persistence binding",
            "Keep candidate and deferred facts audit-only until a separately reviewed approved binding exists.",
        )


def _reject_unclassifiable_binding_fields(fact: Mapping[str, Any], category: str) -> None:
    binding_fields = (
        "classification",
        "target_context",
        "approved_binding",
        "adapter_scope",
        *_APPROVED_BINDING_EVIDENCE_FIELDS,
    )
    if any(field in fact for field in binding_fields):
        raise _GuardError(
            _BASELINE_NONAUTHORIZING,
            BASELINE_FILENAME,
            f"{category} source-only declaration must not contain an authorization binding",
            "Keep this non-table declaration audit-only; add a new reviewed resource "
            "authorization contract before introducing classification or proof fields.",
        )


def _validate_approved_table_binding(
    fact: Mapping[str, Any],
    *,
    adapter_scope: str,
    evidence: _EvidenceReader,
) -> None:
    """Bind prospective table authorization to one target adapter implementation."""

    table_name = _require_text(fact, "logical_name", "tables")
    adapter_source = f"src/trade/{adapter_scope.replace('.', '/')}.py"
    for field in _APPROVED_BINDING_EVIDENCE_FIELDS:
        proof = fact[field]
        assert isinstance(proof, Mapping)
        source = _require_text(proof, "source", f"tables.{table_name}.{field}")
        literal = _require_text(proof, "literal", f"tables.{table_name}.{field}")
        callable_name = _require_text(proof, "callable", f"tables.{table_name}.{field}")
        if source != adapter_source:
            raise _GuardError(
                _BASELINE_CLASSIFICATION,
                BASELINE_FILENAME,
                f"approved table binding for {table_name} has {field} outside "
                f"its adapter scope {adapter_scope}",
                "Bind every approved table proof to the named target adapter module.",
            )
        if not _sql_targets_table(literal, table_name, field):
            raise _GuardError(
                _BASELINE_CLASSIFICATION,
                BASELINE_FILENAME,
                f"approved table binding for {table_name} has {field} without a "
                "table-specific SQL operation",
                "Use a static table-specific SQL proof with an exact SQL table identifier.",
            )
        if _NAMED_CALLABLE.fullmatch(callable_name) is None:
            raise _GuardError(
                _BASELINE_CLASSIFICATION,
                BASELINE_FILENAME,
                f"approved table binding for {table_name} has invalid {field} callable "
                f"{callable_name!r}",
                "Name one function or async function in the target adapter module.",
            )
        summary = evidence.callable_proof_summary(adapter_source, callable_name)
        if summary is None:
            raise _GuardError(
                _BASELINE_CLASSIFICATION,
                BASELINE_FILENAME,
                f"approved table binding for {table_name} has {field} callable "
                f"{callable_name!r} outside its adapter module",
                "Bind each proof to a declared function or async function in the target adapter.",
            )
        operation = _summary_persistence_operation(summary, literal, table_name, field)
        if operation is None:
            rejection = (
                _transaction_proof_rejection(summary, literal, table_name)
                if field == "transaction_evidence"
                else None
            )
            if rejection is not None:
                declaration = rejection.declaration
                raise _GuardError(
                    _BASELINE_CLASSIFICATION,
                    adapter_source,
                    f"approved table binding for {table_name} {field} callable {callable_name} "
                    f"uses external {declaration.kind} transaction alias {rejection.target!r} "
                    f"declared on line {declaration.line}",
                    "Use a callable-local transaction alias or remove the external "
                    f"{declaration.kind} declaration before using transaction evidence.",
                    line=rejection.with_line,
                )
            raise _GuardError(
                _BASELINE_CLASSIFICATION,
                adapter_source,
                f"approved table binding for {table_name} {field} callable {callable_name} "
                "has no exact direct-scope static SQL operation",
                "Make the declared literal exactly match the first static SQL argument in the "
                f"{field} callable {callable_name}; transaction evidence must use its "
                "unmodified transaction receiver or explicit alias.",
                line=summary.callable_line,
            )


def _adapter_callable(tree: ast.Module, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """Return one uniquely bound top-level callable suitable for static proof."""

    candidates = [
        statement
        for statement in tree.body
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)) and statement.name == name
    ]
    if len(candidates) != 1:
        return None
    candidate = candidates[0]
    if _function_has_definition_time_metadata(candidate):
        return None
    if any(
        not _module_statement_is_admitted(statement, name, is_first=index == 0)
        for index, statement in enumerate(tree.body)
    ):
        return None
    return candidate


def _module_statement_is_admitted(
    statement: ast.stmt,
    proof_name: str,
    *,
    is_first: bool,
) -> bool:
    """Admit only inert module declarations beside approved proof callables."""

    if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return not _function_has_definition_time_metadata(statement)
    if isinstance(statement, ast.Assign):
        return all(
            isinstance(target, ast.Name) and target.id != proof_name for target in statement.targets
        ) and _is_inert_module_constant(statement.value)
    return (
        is_first
        and isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Constant)
        and isinstance(statement.value.value, str)
    )


def _is_inert_module_constant(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return all(_is_inert_module_constant(element) for element in node.elts)
    if isinstance(node, ast.Dict):
        return all(
            key is not None and _is_inert_module_constant(key) and _is_inert_module_constant(value)
            for key, value in zip(node.keys, node.values, strict=True)
        )
    return False


def _function_has_definition_time_metadata(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    arguments = node.args
    annotations = (
        *(argument.annotation for argument in (*arguments.posonlyargs, *arguments.args)),
        arguments.vararg.annotation if arguments.vararg is not None else None,
        *(argument.annotation for argument in arguments.kwonlyargs),
        arguments.kwarg.annotation if arguments.kwarg is not None else None,
        node.returns,
    )
    return bool(
        node.decorator_list
        or arguments.defaults
        or any(default is not None for default in arguments.kw_defaults)
        or any(annotation is not None for annotation in annotations)
        or getattr(node, "type_params", ())
    )


def _is_module_namespace(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id
        in {
            "globals",
            "vars",
        }
    )


def _object_namespace_root_name(node: ast.AST) -> str | None:
    if not (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "vars"
        and len(node.args) == 1
        and not node.keywords
    ):
        return None
    identity = _expression_identity(node.args[0])
    return identity[0] if identity is not None else _UNKNOWN_BINDING_ROOT


def _summarize_callable_proof(
    callable_node: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    source: str,
    limits: DiscoveryLimits,
) -> _CallableProofSummary:
    """Collect reachable direct-scope static SQL operations without closures."""

    _validate_callable_proof_shape(callable_node, source=source, limits=limits)
    visitor = _CallableProofVisitor(
        source=source,
        limits=limits,
        external_bindings=_callable_external_bindings(callable_node),
    )
    visitor.visit_statements(callable_node.body)
    return _CallableProofSummary(
        callable_node.lineno,
        tuple(visitor.operations),
        tuple(visitor.transaction_rejections),
    )


def _callable_external_bindings(
    callable_node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> Mapping[str, _ExternalBindingDeclaration]:
    """Return direct-lexical global/nonlocal declarations by bound name."""

    declarations: dict[str, _ExternalBindingDeclaration] = {}
    pending: list[ast.AST] = list(callable_node.body)
    while pending:
        node = pending.pop()
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            kind = "global" if isinstance(node, ast.Global) else "nonlocal"
            declarations.update(
                {name: _ExternalBindingDeclaration(name, kind, node.lineno) for name in node.names}
            )
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        pending.extend(ast.iter_child_nodes(node))
    return declarations


def _validate_callable_proof_shape(
    callable_node: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    source: str,
    limits: DiscoveryLimits,
) -> None:
    node_count, depth = _ast_shape(callable_node)
    if node_count > limits.max_ast_nodes_per_file or depth > limits.max_ast_depth:
        raise _baseline_evidence_budget_error(
            source,
            "approved-binding callable proof exceeds the configured AST node or depth budget",
            remediation=(
                "Reduce callable complexity or make a reviewed approved-binding AST-budget increase."
            ),
        )


class _CallableProofVisitor:
    """Track only straight-line direct-call evidence for approved bindings."""

    def __init__(
        self,
        *,
        source: str,
        limits: DiscoveryLimits,
        external_bindings: Mapping[str, _ExternalBindingDeclaration],
        initial_transaction_receivers: frozenset[tuple[str, ...]] = frozenset(),
        initial_operation_count: int = 0,
        initial_operation_sql_bytes: int = 0,
    ) -> None:
        self._source = source
        self._limits = limits
        self._external_bindings = external_bindings
        self.operations: list[_PersistenceOperation] = []
        self.transaction_rejections: list[_TransactionProofRejection] = []
        self._operation_count = initial_operation_count
        self._operation_sql_bytes = initial_operation_sql_bytes
        self._transaction_receivers: list[frozenset[tuple[str, ...]]] = [
            initial_transaction_receivers
        ]

    def visit_statements(self, statements: Sequence[ast.stmt]) -> bool:
        """Scan a straight-line prefix and stop before ambiguous control flow."""

        for statement in statements:
            if isinstance(statement, (ast.With, ast.AsyncWith)):
                if (
                    self._transaction_receivers[-1]
                    or len(statement.items) != 1
                    or not _transaction_receivers_for_items(
                        statement.items,
                        external_bindings=self._external_bindings,
                    )
                ):
                    self._record_transaction_rejection(statement)
                    return True
                if self._visit_transaction_block(statement.items, statement.body):
                    return True
                continue
            if isinstance(statement, ast.Expr):
                self._visit_direct_expression(statement.value)
                continue
            if isinstance(statement, ast.Assign):
                self._visit_direct_expression(statement.value)
                self._invalidate_transaction_target_mutation(statement.targets)
                self._invalidate_transaction_receivers(
                    _assignment_target_root_names(statement.targets)
                )
            elif isinstance(statement, ast.AnnAssign) and statement.value is not None:
                self._visit_direct_expression(statement.value)
                self._invalidate_transaction_target_mutation((statement.target,))
                self._invalidate_transaction_receivers(
                    _assignment_target_root_names((statement.target,))
                )
            elif isinstance(statement, ast.AugAssign):
                self._visit_direct_expression(statement.value)
                self._invalidate_transaction_target_mutation((statement.target,))
                self._invalidate_transaction_receivers(
                    _assignment_target_root_names((statement.target,))
                )
            elif isinstance(statement, ast.Delete):
                self._invalidate_transaction_target_mutation(statement.targets)
                self._invalidate_transaction_receivers(
                    _assignment_target_root_names(statement.targets)
                )
            elif isinstance(statement, ast.Import):
                self._transaction_receivers[-1] = frozenset()
            elif isinstance(statement, ast.ImportFrom):
                self._transaction_receivers[-1] = frozenset()
            elif isinstance(statement, (ast.Global, ast.Nonlocal)):
                self._invalidate_transaction_receivers(frozenset(statement.names))
            elif isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self._invalidate_transaction_receivers(frozenset((statement.name,)))
                return True
            elif isinstance(statement, ast.Return):
                if statement.value is not None:
                    self._visit_direct_expression(statement.value)
                return True
            elif isinstance(statement, ast.Raise):
                if statement.exc is not None:
                    self._visit_direct_expression(statement.exc)
                if statement.cause is not None:
                    self._visit_direct_expression(statement.cause)
                return True
            elif (
                isinstance(
                    statement,
                    (
                        ast.If,
                        ast.For,
                        ast.AsyncFor,
                        ast.While,
                        ast.Try,
                        ast.Assert,
                        ast.Match,
                    ),
                )
                or type(statement).__name__ == "TryStar"
            ):
                return True
        return False

    def _invalidate_transaction_receivers(self, roots: frozenset[str]) -> None:
        if roots:
            if _UNKNOWN_BINDING_ROOT in roots:
                self._transaction_receivers[-1] = frozenset()
                return
            self._transaction_receivers[-1] = frozenset(
                receiver for receiver in self._transaction_receivers[-1] if receiver[0] not in roots
            )

    def _invalidate_transaction_target_mutation(
        self,
        targets: Sequence[ast.expr | None],
    ) -> None:
        if any(_assignment_target_has_side_effects(target) for target in targets):
            self._transaction_receivers[-1] = frozenset()

    def _visit_direct_expression(self, expression: ast.expr) -> None:
        """Visit immediate call chains without following deferred or conditional AST nodes."""

        self._invalidate_transaction_receivers(_expression_bound_root_names(expression))
        if _expression_has_non_persistence_call(expression):
            self._invalidate_transaction_receivers(frozenset((_UNKNOWN_BINDING_ROOT,)))
        pending: list[ast.expr] = [expression]
        while pending:
            node = pending.pop()
            if isinstance(node, ast.Call):
                self._record_persistence_operation(node)
                pending.append(node.func)
                pending.extend(node.args)
                pending.extend(keyword.value for keyword in node.keywords)
            elif isinstance(node, ast.Attribute):
                pending.append(node.value)
            elif isinstance(node, ast.Await):
                pending.append(node.value)
            elif isinstance(node, ast.Subscript):
                pending.append(node.value)
                if isinstance(node.slice, ast.expr):
                    pending.append(node.slice)

    def _visit_transaction_block(
        self,
        items: list[ast.withitem],
        body: list[ast.stmt],
    ) -> bool:
        transaction_receivers = set(self._transaction_receivers[-1])
        for item in items:
            transaction_receivers = {
                receiver
                for receiver in transaction_receivers
                if receiver[0] not in _assignment_target_root_names((item.optional_vars,))
            }
            transaction_receivers.update(
                _transaction_receivers(
                    item,
                    external_bindings=self._external_bindings,
                )
            )
        self._transaction_receivers.append(frozenset(transaction_receivers))
        try:
            return self.visit_statements(body)
        finally:
            self._transaction_receivers.pop()

    def _record_transaction_rejection(self, statement: ast.With | ast.AsyncWith) -> None:
        """Retain an alias cause only when it blocks otherwise-admissible SQL."""

        if self._transaction_receivers[-1] or len(statement.items) != 1:
            return
        item = statement.items[0]
        rejection = _external_alias_transaction_rejection(item, self._external_bindings)
        if rejection is None:
            return
        expression = item.context_expr
        assert isinstance(expression, ast.Call)
        assert isinstance(expression.func, ast.Attribute)
        receiver = _expression_identity(expression.func.value)
        if receiver is not None and receiver[0] == rejection.target:
            return
        local_bindings = dict(self._external_bindings)
        del local_bindings[rejection.target]
        local_receivers = _transaction_receivers(item, external_bindings=local_bindings)
        if not local_receivers:
            return
        candidate_visitor = _CallableProofVisitor(
            source=self._source,
            limits=self._limits,
            external_bindings=local_bindings,
            initial_transaction_receivers=local_receivers,
            initial_operation_count=self._operation_count,
            initial_operation_sql_bytes=self._operation_sql_bytes,
        )
        candidate_visitor.visit_statements(statement.body)
        candidate_sql = tuple(
            operation.sql
            for operation in candidate_visitor.operations
            if operation.receiver in operation.transaction_receivers
        )
        if candidate_sql:
            self.transaction_rejections.append(
                _TransactionProofRejection(
                    rejection.declaration,
                    rejection.target,
                    rejection.with_line,
                    candidate_sql,
                )
            )

    def _record_persistence_operation(self, node: ast.Call) -> None:
        if _call_attribute_name(node) not in _PERSISTENCE_CALL_NAMES:
            return
        receiver = _persistence_receiver(node)
        if receiver is None or not node.args:
            return
        statement = node.args[0]
        if not isinstance(statement, ast.Constant) or not isinstance(statement.value, str):
            return
        encoded_size = len(statement.value.encode("utf-8"))
        if (
            self._operation_count >= self._limits.max_callable_proof_operations
            or self._operation_sql_bytes + encoded_size > self._limits.max_callable_proof_sql_bytes
        ):
            raise _baseline_evidence_budget_error(
                self._source,
                "approved-binding callable proof exceeds the configured operation "
                "or SQL-byte budget",
                remediation=(
                    "Split the adapter proof or make a reviewed approved-binding "
                    "proof-budget increase."
                ),
            )
        self.operations.append(
            _PersistenceOperation(
                sql=statement.value,
                line=node.lineno,
                receiver=receiver,
                transaction_receivers=self._transaction_receivers[-1],
            )
        )
        self._operation_count += 1
        self._operation_sql_bytes += encoded_size


def _summary_persistence_operation(
    summary: _CallableProofSummary,
    literal: str,
    table_name: str,
    field: str,
) -> _PersistenceOperation | None:
    for operation in summary.operations:
        if literal != operation.sql or not _sql_targets_table(operation.sql, table_name, field):
            continue
        if field != "transaction_evidence" or operation.receiver in operation.transaction_receivers:
            return operation
    return None


def _transaction_proof_rejection(
    summary: _CallableProofSummary,
    literal: str,
    table_name: str,
) -> _TransactionProofRejection | None:
    return next(
        (
            rejection
            for rejection in summary.transaction_rejections
            if any(
                literal == sql and _sql_targets_table(sql, table_name, "transaction_evidence")
                for sql in rejection.candidate_sql
            )
        ),
        None,
    )


def _external_alias_transaction_rejection(
    item: ast.withitem,
    external_bindings: Mapping[str, _ExternalBindingDeclaration],
) -> _TransactionProofRejection | None:
    expression = item.context_expr
    if (
        not isinstance(expression, ast.Call)
        or _call_attribute_name(expression) != "transaction"
        or not isinstance(expression.func, ast.Attribute)
    ):
        return None
    if not isinstance(item.optional_vars, ast.Name):
        return None
    declaration = external_bindings.get(item.optional_vars.id)
    if declaration is None:
        return None
    return _TransactionProofRejection(declaration, item.optional_vars.id, expression.lineno, ())


def _transaction_receivers(
    item: ast.withitem,
    *,
    external_bindings: Mapping[str, _ExternalBindingDeclaration],
) -> frozenset[tuple[str, ...]]:
    expression = item.context_expr
    if (
        not isinstance(expression, ast.Call)
        or _call_attribute_name(expression) != "transaction"
        or not isinstance(expression.func, ast.Attribute)
    ):
        return frozenset()
    receiver = _expression_identity(expression.func.value)
    if receiver is None or receiver[0] in external_bindings:
        return frozenset()
    if item.optional_vars is None:
        return frozenset((receiver,))
    if not isinstance(item.optional_vars, ast.Name):
        return frozenset()
    if item.optional_vars.id in external_bindings:
        return frozenset()
    return frozenset((receiver, (item.optional_vars.id,)))


def _transaction_receivers_for_items(
    items: Sequence[ast.withitem],
    *,
    external_bindings: Mapping[str, _ExternalBindingDeclaration],
) -> frozenset[tuple[str, ...]]:
    receivers: set[tuple[str, ...]] = set()
    for item in items:
        receivers.update(
            _transaction_receivers(
                item,
                external_bindings=external_bindings,
            )
        )
    return frozenset(receivers)


def _assignment_target_root_names(targets: Sequence[ast.expr | None]) -> frozenset[str]:
    roots: set[str] = set()
    pending = [target for target in targets if target is not None]
    while pending:
        target = pending.pop()
        if isinstance(target, ast.Name):
            roots.add(target.id)
        elif isinstance(target, (ast.Attribute, ast.Subscript)):
            if isinstance(target, ast.Subscript):
                namespace_root = _object_namespace_root_name(target.value)
                if namespace_root is not None:
                    roots.add(namespace_root)
                    continue
            if isinstance(target, ast.Subscript) and _is_module_namespace(target.value):
                namespace_key = _static_string_expression(target.slice)
                roots.add(namespace_key or _UNKNOWN_BINDING_ROOT)
                continue
            identity = _expression_identity(target.value)
            if identity is not None:
                roots.add(identity[0])
        elif isinstance(target, ast.Starred):
            pending.append(target.value)
        elif isinstance(target, (ast.Tuple, ast.List)):
            pending.extend(target.elts)
    return frozenset(roots)


def _assignment_target_has_side_effects(target: ast.expr | None) -> bool:
    if target is None or isinstance(target, ast.Name):
        return False
    if isinstance(target, ast.Starred):
        return _assignment_target_has_side_effects(target.value)
    if isinstance(target, (ast.Tuple, ast.List)):
        return any(_assignment_target_has_side_effects(element) for element in target.elts)
    return True


def _static_string_expression(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _expression_bound_root_names(expression: ast.expr) -> frozenset[str]:
    roots: set[str] = set()
    pending: list[ast.AST] = [expression]
    while pending:
        node = pending.pop()
        if isinstance(node, ast.NamedExpr):
            roots.update(_assignment_target_root_names((node.target,)))
        if isinstance(
            node, (ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
        ):
            continue
        pending.extend(ast.iter_child_nodes(node))
    return frozenset(roots)


def _expression_has_non_persistence_call(expression: ast.expr) -> bool:
    pending: list[ast.AST] = [expression]
    while pending:
        node = pending.pop()
        if isinstance(node, ast.Call):
            if _call_attribute_name(node) not in _PERSISTENCE_CALL_NAMES:
                return True
            pending.append(node.func)
            pending.extend(node.args)
            pending.extend(keyword.value for keyword in node.keywords)
        elif isinstance(
            node, (ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
        ):
            continue
        else:
            pending.extend(ast.iter_child_nodes(node))
    return False


def _persistence_receiver(node: ast.Call) -> tuple[str, ...] | None:
    if not isinstance(node.func, ast.Attribute):
        return None
    return _expression_identity(node.func.value)


def _expression_identity(node: ast.AST | None) -> tuple[str, ...] | None:
    if isinstance(node, ast.Name):
        return (node.id,)
    if isinstance(node, ast.Attribute):
        parent = _expression_identity(node.value)
        return (*parent, node.attr) if parent is not None else None
    return None


def _sql_targets_table(sql: str, table_name: str, field: str) -> bool:
    """Require the expected table at a supported SQL statement position."""

    statement = _sql_without_values_and_comments(sql)
    if field in {"reader_evidence", "compatibility_evidence"}:
        return _is_single_read_statement(statement) and any(
            _sql_identifier_matches(identifier, table_name)
            for identifier in _sql_read_table_identifiers(sql)
        )
    if field in {"writer_evidence", "transaction_evidence"}:
        if not _is_single_write_statement(statement):
            return False
        write_match = next(
            (
                match
                for pattern in _SQL_WRITE_TABLE_PATTERNS
                if (match := pattern.search(statement)) is not None
            ),
            None,
        )
        if write_match is not None and _sql_identifier_matches(
            write_match.group("table"),
            table_name,
        ):
            return True
        if field == "writer_evidence":
            return False
    return False


def _is_single_read_statement(statement: str) -> bool:
    stripped = statement.strip()
    if stripped.endswith(";"):
        stripped = stripped[:-1].rstrip()
    return (
        stripped.upper().startswith("SELECT")
        and ";" not in stripped
        and not any(pattern.search(stripped) for pattern in _SQL_TABLE_OPERATION_PATTERNS)
    )


def _is_single_write_statement(statement: str) -> bool:
    stripped = statement.strip()
    if stripped.endswith(";"):
        stripped = stripped[:-1].rstrip()
    return bool(stripped) and ";" not in stripped


def _sql_identifier_matches(identifier: str, table_name: str) -> bool:
    if identifier.startswith('"') and identifier.endswith('"'):
        identifier = identifier[1:-1].replace('""', '"')
    elif identifier.startswith("`") and identifier.endswith("`"):
        identifier = identifier[1:-1]
    elif identifier.startswith("[") and identifier.endswith("]"):
        identifier = identifier[1:-1]
    return identifier.casefold() == table_name.casefold()


def _sql_read_table_identifiers(sql: str) -> Iterator[str]:
    """Yield identifiers following real SQL FROM/JOIN keywords, not quoted text."""

    index = 0
    expects_table = False
    while index < len(sql):
        character = sql[index]
        if character.isspace():
            index += 1
            continue
        if character == "-" and sql[index + 1 : index + 2] == "-":
            newline = sql.find("\n", index + 2)
            index = len(sql) if newline == -1 else newline + 1
            continue
        if character == "/" and sql[index + 1 : index + 2] == "*":
            end = sql.find("*/", index + 2)
            index = len(sql) if end == -1 else end + 2
            continue
        if character == "'":
            index = _sql_quoted_token_end(sql, index, "'", "''")
            expects_table = False
            continue
        if character == '"':
            end = _sql_quoted_token_end(sql, index, '"', '""')
            if expects_table:
                yield sql[index:end]
                expects_table = False
            index = end
            continue
        if character == "`":
            end = _sql_quoted_token_end(sql, index, "`", "``")
            if expects_table:
                yield sql[index:end]
                expects_table = False
            index = end
            continue
        if character == "[":
            end = sql.find("]", index + 1)
            end = len(sql) if end == -1 else end + 1
            if expects_table:
                yield sql[index:end]
                expects_table = False
            index = end
            continue
        if character.isascii() and (character.isalnum() or character in {"_", "$"}):
            end = index + 1
            while (
                end < len(sql)
                and sql[end].isascii()
                and (sql[end].isalnum() or sql[end] in {"_", "$"})
            ):
                end += 1
            token = sql[index:end]
            if expects_table:
                yield token
                expects_table = False
            elif token.upper() in {"FROM", "JOIN"}:
                expects_table = True
            index = end
            continue
        expects_table = False
        index += 1


def _sql_quoted_token_end(sql: str, start: int, delimiter: str, escaped: str) -> int:
    index = start + 1
    while index < len(sql):
        if sql.startswith(escaped, index):
            index += len(escaped)
            continue
        if sql[index] == delimiter:
            return index + 1
        index += 1
    return len(sql)


def _sql_without_values_and_comments(sql: str) -> str:
    """Mask SQL values and comments before locating table identifiers."""

    characters = list(sql)
    index = 0
    while index < len(characters):
        character = characters[index]
        if character == "'":
            end = index + 1
            while end < len(characters):
                if characters[end] == "'":
                    end += 1
                    if end < len(characters) and characters[end] == "'":
                        end += 1
                        continue
                    break
                end += 1
            _mask_source_span(characters, index, end)
            index = end
        elif character == "-" and index + 1 < len(characters) and characters[index + 1] == "-":
            end = index + 2
            while end < len(characters) and characters[end] not in "\r\n":
                end += 1
            _mask_source_span(characters, index, end)
            index = end
        elif character == "/" and index + 1 < len(characters) and characters[index + 1] == "*":
            end = index + 2
            while end + 1 < len(characters) and characters[end : end + 2] != ["*", "/"]:
                end += 1
            _mask_source_span(characters, index, min(len(characters), end + 2))
            index = end + 2
        else:
            index += 1
    return "".join(characters)


def _call_attribute_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    if isinstance(node.func, ast.Name):
        return node.func.id
    return None


def _read_table_array(
    parsed: Mapping[str, Any],
    key: str,
    baseline_name: str,
) -> tuple[Mapping[str, Any], ...]:
    value = parsed.get(key)
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise _GuardError(
            _BASELINE_MALFORMED,
            baseline_name,
            f"{key} must be a TOML array of tables",
            "Declare the required source-only facts as TOML array tables.",
        )
    return tuple(value)


def _require_text(mapping: Mapping[str, Any], key: str, path: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise _GuardError(
            _BASELINE_MALFORMED,
            BASELINE_FILENAME,
            f"{path} must declare non-empty {key}",
            "Fill every required baseline declaration field with an explicit value.",
        )
    return value


def _require_string_list(mapping: Mapping[str, Any], key: str, path: str) -> tuple[str, ...]:
    value = mapping.get(key)
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        raise _GuardError(
            _BASELINE_MALFORMED,
            BASELINE_FILENAME,
            f"{path} must declare a non-empty {key} string list",
            "List the declared architecture roots explicitly.",
        )
    return tuple(value)


def _iter_git_index(
    root: Path, *, limits: DiscoveryLimits = DEFAULT_LIMITS
) -> Generator[tuple[str, str], None, None]:
    environment = os.environ.copy()
    for key in _GIT_ENVIRONMENT_OVERRIDES:
        environment.pop(key, None)
    try:
        process = subprocess.Popen(
            ["git", "-C", str(root), "ls-files", "-z", "--stage", "--", "trade_py"],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            start_new_session=True,
        )
    except OSError as exc:
        raise _GuardError(
            PRODUCER_TOOL_FAILURE,
            "trade_py",
            f"cannot start Git index discovery: {exc}",
            "Install Git and run the check from a repository with a readable Git index.",
        ) from exc
    stdout = process.stdout
    stderr_stream = process.stderr
    assert stdout is not None
    assert stderr_stream is not None
    stderr_chunks: list[bytes] = []
    stderr_size = 0
    stderr_lock = threading.Lock()
    stderr_done = threading.Event()
    stderr_overflow = threading.Event()
    stderr_stop = threading.Event()
    stderr_error: OSError | ValueError | None = None
    poll_interval_seconds = 0.05

    def drain_stderr() -> None:
        nonlocal stderr_error, stderr_size
        diagnostic_limit = max(0, limits.max_git_stderr_bytes)
        try:
            while not stderr_stop.is_set():
                try:
                    ready, _, _ = select.select(
                        [stderr_stream],
                        [],
                        [],
                        poll_interval_seconds,
                    )
                    if not ready or stderr_stop.is_set():
                        continue
                    with stderr_lock:
                        read_size = (
                            1
                            if stderr_size >= diagnostic_limit
                            else min(8_192, diagnostic_limit - stderr_size)
                        )
                    chunk = os.read(stderr_stream.fileno(), read_size)
                except (OSError, ValueError) as exc:
                    if stderr_stop.is_set():
                        return
                    with stderr_lock:
                        stderr_error = exc
                    return
                if not chunk:
                    break
                overflow = False
                with stderr_lock:
                    if stderr_size >= diagnostic_limit:
                        overflow = True
                    else:
                        stderr_chunks.append(chunk)
                        stderr_size += len(chunk)
                if overflow:
                    stderr_overflow.set()
                    _terminate_process_group(process)
                    return
        finally:
            stderr_done.set()

    def stderr_terminal_error() -> _GuardError | None:
        with stderr_lock:
            read_error = stderr_error
        if read_error is not None:
            return _git_stderr_read_error(read_error)
        if stderr_overflow.is_set():
            return _git_stderr_budget_error()
        return None

    stderr_thread = threading.Thread(target=drain_stderr, daemon=True)
    stderr_thread.start()
    deadline = time.monotonic() + limits.git_timeout_seconds
    record_limit = min(
        limits.max_git_record_bytes,
        limits.max_raw_path_bytes + 512,
    )
    buffer = b""
    try:
        while True:
            if terminal_error := stderr_terminal_error():
                raise terminal_error
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _git_timeout_error()
            ready, _, _ = select.select(
                [stdout],
                [],
                [],
                min(remaining, poll_interval_seconds),
            )
            if terminal_error := stderr_terminal_error():
                raise terminal_error
            if not ready:
                continue
            chunk = os.read(stdout.fileno(), 8_192)
            if not chunk:
                break
            while chunk:
                delimiter = chunk.find(b"\0")
                if delimiter < 0:
                    if len(buffer) + len(chunk) > record_limit:
                        raise _producer_path_budget_error(
                            "trade_py",
                            "Git index emitted an unterminated record beyond the configured "
                            "record-byte budget",
                        )
                    buffer += chunk
                    break
                raw = buffer + chunk[:delimiter]
                if len(raw) > record_limit:
                    raise _producer_path_budget_error(
                        "trade_py",
                        "Git index emitted a record beyond the configured record-byte budget",
                    )
                buffer = b""
                chunk = chunk[delimiter + 1 :]
                if not raw:
                    continue
                yield _parse_index_record(raw)
        while True:
            if terminal_error := stderr_terminal_error():
                raise terminal_error
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _git_timeout_error()
            try:
                return_code = process.wait(timeout=min(remaining, poll_interval_seconds))
                break
            except subprocess.TimeoutExpired:
                continue
        while not stderr_done.wait(
            timeout=min(
                max(0.0, deadline - time.monotonic()),
                poll_interval_seconds,
            )
        ):
            if terminal_error := stderr_terminal_error():
                raise terminal_error
            if time.monotonic() >= deadline:
                raise _GuardError(
                    PRODUCER_TOOL_FAILURE,
                    "trade_py",
                    "Git index discovery did not close its stderr stream before the deadline",
                    "Repair the Git environment before running source-only discovery.",
                )
        if terminal_error := stderr_terminal_error():
            raise terminal_error
        with stderr_lock:
            stderr = b"".join(stderr_chunks).decode("utf-8", "replace").strip()
        if buffer or return_code != 0:
            detail = stderr or "incomplete NUL record"
            raise _GuardError(
                PRODUCER_TOOL_FAILURE,
                "trade_py",
                "Git index discovery failed: "
                + _bounded_text(detail, limits.max_diagnostic_field_bytes),
                "Repair Git availability or the repository index before running source-only discovery.",
            )
    finally:
        stderr_stop.set()
        _terminate_process_group(process)
        stdout.close()
        stderr_thread.join()
        stderr_stream.close()


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    """Stop a substituted Git command and any residual process-group children."""

    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        pass

    deadline = time.monotonic() + 1
    while _process_group_exists(process.pid) and time.monotonic() < deadline:
        time.sleep(0.01)
    if not _process_group_exists(process.pid):
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        pass


def _process_group_exists(process_group_id: int) -> bool:
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    return True


def _parse_index_record(raw: bytes) -> tuple[str, str]:
    try:
        metadata, raw_path = raw.split(b"\t", 1)
        mode = metadata.split(b" ", 1)[0].decode("ascii")
        path = raw_path.decode("utf-8")
    except (UnicodeDecodeError, ValueError) as exc:
        raise _GuardError(
            PRODUCER_UNSAFE_SOURCE,
            "trade_py",
            "Git index contains an invalid source record",
            "Use valid UTF-8 repository paths and a regular Git index.",
        ) from exc
    return mode, path


def _is_production_python_path(path: str, mode: str) -> bool:
    if mode not in _REGULAR_GIT_FILE_MODES:
        return False
    return _is_production_python_candidate_path(path)


def _is_production_python_candidate_path(path: str) -> bool:
    if not _is_safe_relative_path(path):
        return False
    pure = PurePosixPath(path)
    parts = pure.parts
    if not parts or parts[0] != "trade_py" or not path.endswith(".py"):
        return False
    if any(part in {"test", "tests"} for part in parts):
        return False
    if any(part in _EXCLUDED_SOURCE_SEGMENTS for part in parts):
        return False
    name = pure.name
    return not name.startswith("test_") and not name.endswith("_test.py")


def _safe_verify_relative(root: Path, relative: str, *, max_bytes: int) -> _SourceSignature:
    """Verify a source descriptor without loading the file's contents."""

    if not _is_safe_relative_path(relative):
        raise _GuardError(
            PRODUCER_UNSAFE_SOURCE,
            relative,
            "source path escapes or is not relative to the repository",
            "Use a stable, repository-confined regular source file.",
        )
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory_flag = getattr(os, "O_DIRECTORY", 0)
    nonblocking_flag = getattr(os, "O_NONBLOCK", 0)
    if not nofollow or not directory_flag or not nonblocking_flag:
        raise _GuardError(
            PRODUCER_UNSAFE_SOURCE,
            relative,
            "the platform does not expose required safe nonblocking descriptor primitives",
            "Run the check on a platform that supports no-follow nonblocking regular-file reads.",
        )
    directory_flags = os.O_RDONLY | os.O_CLOEXEC | directory_flag | nofollow
    file_flags = os.O_RDONLY | os.O_CLOEXEC | nofollow | nonblocking_flag
    try:
        root_fd = os.open(root, directory_flags)
    except OSError as exc:
        raise _GuardError(
            PRODUCER_UNSAFE_SOURCE,
            relative,
            f"cannot open repository root safely: {exc}",
            "Use a readable, non-symlink repository root.",
        ) from exc
    try:
        descriptor = _open_relative_file(root_fd, relative, directory_flags, file_flags)
        try:
            signature = _regular_signature(descriptor, relative)
            if signature.size > max_bytes:
                raise _producer_source_budget_error(
                    relative,
                    f"source file exceeds the {max_bytes} byte read limit",
                )
            return signature
        finally:
            os.close(descriptor)
    except _GuardError:
        raise
    except FileNotFoundError as exc:
        raise _unsafe_source_error(relative, f"source does not exist: {relative}") from exc
    except OSError as exc:
        raise _unsafe_source_error(
            relative, f"cannot read repository source safely: {exc}"
        ) from exc
    finally:
        os.close(root_fd)


def _safe_read_relative(root: Path, relative: str, *, max_bytes: int) -> bytes:
    if not _is_safe_relative_path(relative):
        raise _GuardError(
            PRODUCER_UNSAFE_SOURCE,
            relative,
            "source path escapes or is not relative to the repository",
            "Use a stable, repository-confined regular source file.",
        )
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory_flag = getattr(os, "O_DIRECTORY", 0)
    nonblocking_flag = getattr(os, "O_NONBLOCK", 0)
    if not nofollow or not directory_flag or not nonblocking_flag:
        raise _GuardError(
            PRODUCER_UNSAFE_SOURCE,
            relative,
            "the platform does not expose required safe nonblocking descriptor primitives",
            "Run the check on a platform that supports no-follow nonblocking regular-file reads.",
        )
    directory_flags = os.O_RDONLY | os.O_CLOEXEC | directory_flag | nofollow
    file_flags = os.O_RDONLY | os.O_CLOEXEC | nofollow | nonblocking_flag
    try:
        root_fd = os.open(root, directory_flags)
    except OSError as exc:
        raise _GuardError(
            PRODUCER_UNSAFE_SOURCE,
            relative,
            f"cannot open repository root safely: {exc}",
            "Use a readable, non-symlink repository root.",
        ) from exc
    try:
        descriptor = _open_relative_file(root_fd, relative, directory_flags, file_flags)
        try:
            before = _regular_signature(descriptor, relative)
            if before.size > max_bytes:
                raise _producer_source_budget_error(
                    relative,
                    f"source file exceeds the {max_bytes} byte read limit",
                )
            payload = _read_descriptor(descriptor, before.size, relative)
            after = _regular_signature(descriptor, relative)
            if before != after or len(payload) != before.size:
                raise _unsafe_source_error(relative, "source identity changed while it was read")
        finally:
            os.close(descriptor)
        verify_fd = _open_relative_file(root_fd, relative, directory_flags, file_flags)
        try:
            verified = _regular_signature(verify_fd, relative)
            if verified != before:
                raise _unsafe_source_error(
                    relative, "source identity changed after descriptor read"
                )
            verified_payload = _read_descriptor(verify_fd, verified.size, relative)
            verified_after = _regular_signature(verify_fd, relative)
        finally:
            os.close(verify_fd)
        if (
            verified_after != verified
            or len(verified_payload) != verified.size
            or verified_payload != payload
        ):
            raise _unsafe_source_error(relative, "source content changed after descriptor read")
        return payload
    except _GuardError:
        raise
    except FileNotFoundError as exc:
        raise _unsafe_source_error(relative, f"source does not exist: {relative}") from exc
    except OSError as exc:
        raise _unsafe_source_error(
            relative, f"cannot read repository source safely: {exc}"
        ) from exc
    finally:
        os.close(root_fd)


def _open_relative_file(
    root_fd: int,
    relative: str,
    directory_flags: int,
    file_flags: int,
) -> int:
    descriptor = os.dup(root_fd)
    try:
        parts = PurePosixPath(relative).parts
        for part in parts[:-1]:
            next_descriptor = os.open(part, directory_flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        file_descriptor = os.open(parts[-1], file_flags, dir_fd=descriptor)
        return file_descriptor
    finally:
        os.close(descriptor)


def _regular_signature(descriptor: int, path: str) -> _SourceSignature:
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode):
        raise _unsafe_source_error(path, "source is not a regular file")
    return _SourceSignature(
        device=metadata.st_dev,
        inode=metadata.st_ino,
        size=metadata.st_size,
        mtime_ns=metadata.st_mtime_ns,
        ctime_ns=metadata.st_ctime_ns,
    )


def _read_descriptor(descriptor: int, size: int, path: str) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = os.read(descriptor, min(remaining, 64 * 1024))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    payload = b"".join(chunks)
    if len(payload) != size:
        raise _unsafe_source_error(path, "source could not be read completely from its descriptor")
    return payload


class _ScopedBindings(Mapping[str, str]):
    """Lexical warehouse bindings with local shadowing and O(1) child creation."""

    def __init__(self, parent: _ScopedBindings | None = None) -> None:
        self._parent = parent
        self._aliases: dict[str, str | None] = {}
        self._layouts: dict[str, bool] = {}
        self._rebound_aliases: dict[str, bool] = {}

    def __getitem__(self, name: str) -> str:
        current: _ScopedBindings | None = self
        while current is not None:
            if name in current._aliases:
                value = current._aliases[name]
                if value is not None:
                    return value
                break
            current = current._parent
        raise KeyError(name)

    def __iter__(self) -> Iterator[str]:
        seen: set[str] = set()
        current: _ScopedBindings | None = self
        while current is not None:
            for name, value in current._aliases.items():
                if name not in seen:
                    seen.add(name)
                    if value is not None:
                        yield name
            current = current._parent

    def __len__(self) -> int:
        return sum(1 for _ in self)

    def child(self) -> _ScopedBindings:
        return _ScopedBindings(self)

    def bind_alias(self, name: str, target: str | None) -> None:
        self._aliases[name] = target

    def bind_layout(self, name: str, is_layout: bool) -> None:
        self._layouts[name] = is_layout

    def bind_rebound_alias(self, name: str, is_rebound: bool) -> None:
        self._rebound_aliases[name] = is_rebound

    def is_layout(self, name: str) -> bool:
        current: _ScopedBindings | None = self
        while current is not None:
            if name in current._layouts:
                return current._layouts[name]
            current = current._parent
        return False

    def is_rebound_alias(self, name: str) -> bool:
        current: _ScopedBindings | None = self
        while current is not None:
            if name in current._rebound_aliases:
                return current._rebound_aliases[name]
            current = current._parent
        return False

    def has_tracked_binding(self, name: str) -> bool:
        return self.get(name) is not None or self.is_layout(name) or self.is_rebound_alias(name)

    def tracked_names(self) -> set[str]:
        names: set[str] = set()
        current: _ScopedBindings | None = self
        while current is not None:
            names.update(current._aliases)
            names.update(current._layouts)
            names.update(current._rebound_aliases)
            current = current._parent
        return names


def _discover_in_source(
    path: str,
    text: str,
    *,
    limits: DiscoveryLimits,
    producer_capacity: int,
    finding_capacity: int,
    producer_report_capacity: int,
) -> tuple[list[WarehouseProducer], list[ArchitectureFinding]]:
    try:
        tree = ast.parse(text, filename=path)
    except RecursionError:
        return [], [
            ArchitectureFinding(
                _BASELINE_INVALID_SOURCE,
                path,
                1,
                "production source exceeds the supported parser recursion depth",
                "Reduce source nesting before relying on its architecture inventory.",
            )
        ]
    except SyntaxError as exc:
        return [], [
            ArchitectureFinding(
                _BASELINE_INVALID_SOURCE,
                path,
                exc.lineno,
                f"cannot parse production source for warehouse discovery: {exc.msg}",
                "Repair the source syntax before relying on its architecture inventory.",
            )
        ]
    ast_node_count, ast_depth = _ast_shape(tree)
    if ast_node_count > limits.max_ast_nodes_per_file:
        return [], [
            _producer_finding(
                PRODUCER_RESULT_BUDGET,
                path,
                1,
                "production source AST exceeds the configured node budget",
                "Split the source or make a reviewed governed AST-node budget increase.",
            )
        ]
    if ast_depth > limits.max_ast_depth:
        return [], [
            _producer_finding(
                PRODUCER_RESULT_BUDGET,
                path,
                1,
                "production source AST exceeds the configured nesting-depth budget",
                "Reduce source nesting or make a reviewed governed AST-depth budget increase.",
            )
        ]

    findings: list[ArchitectureFinding] = []
    producers: list[WarehouseProducer] = []
    producer_report_bytes = 0
    finding_budget_exceeded = False

    class _ProducerVisitor(ast.NodeVisitor):
        def __init__(
            self,
            bindings: _ScopedBindings | None = None,
            *,
            lexical_bindings: _ScopedBindings | None = None,
        ) -> None:
            self.bindings = _ScopedBindings() if bindings is None else bindings
            self.lexical_bindings = self.bindings if lexical_bindings is None else lexical_bindings

        def _add_finding(self, finding: ArchitectureFinding) -> bool:
            nonlocal finding_budget_exceeded
            if len(findings) >= finding_capacity:
                finding_budget_exceeded = True
                return False
            findings.append(finding)
            return True

        def _result_budget(self, message: str) -> None:
            nonlocal finding_budget_exceeded
            finding_budget_exceeded = True

        def _invalidate_names(self, names: set[str]) -> None:
            for name in names:
                was_writer = self.bindings.get(name) in CANONICAL_WRITERS
                if was_writer:
                    self.bindings.bind_rebound_alias(name, True)
                if was_writer or self.bindings.has_tracked_binding(name):
                    self.bindings.bind_alias(name, None)
                    self.bindings.bind_layout(name, False)

        def _bind_noncanonical_alias(
            self,
            name: str,
            target: str,
            *,
            track_alias: bool,
        ) -> None:
            was_writer = self.bindings.get(name) in CANONICAL_WRITERS
            if was_writer:
                self.bindings.bind_rebound_alias(name, True)
            if track_alias or was_writer or self.bindings.has_tracked_binding(name):
                self.bindings.bind_alias(name, target if track_alias else None)
                self.bindings.bind_layout(name, False)

        def _bind_names(
            self,
            names: set[str],
            value: ast.AST | None,
            *,
            annotation: ast.AST | None = None,
        ) -> None:
            resolved = _resolve_expression(value, self.bindings)
            if resolved in CANONICAL_WRITERS:
                for name in names:
                    self.bindings.bind_alias(name, resolved)
                    self.bindings.bind_rebound_alias(name, False)
            else:
                self._invalidate_names(names)
            if _annotation_is_layout(annotation, self.bindings) or _is_layout_factory(
                value, self.bindings
            ):
                for name in names:
                    self.bindings.bind_layout(name, True)

        def _function_child(self) -> _ProducerVisitor:
            return _ProducerVisitor(self.lexical_bindings.child())

        def _invalidate_star_import(self) -> None:
            names = {
                name
                for name in self.bindings.tracked_names()
                if (
                    self.bindings.get(name) in CANONICAL_WRITERS
                    or (
                        self.bindings.get(name) is not None
                        and _tracks_warehouse_namespace(self.bindings[name])
                    )
                    or self.bindings.is_layout(name)
                )
            }
            self._invalidate_names(names)

        def _visit_function(
            self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda
        ) -> None:
            child = self._function_child()
            if not isinstance(node, ast.Lambda):
                child._invalidate_names(_function_local_bindings(node))
            arguments = (
                *node.args.posonlyargs,
                *node.args.args,
                *node.args.kwonlyargs,
                *((node.args.vararg,) if node.args.vararg is not None else ()),
                *((node.args.kwarg,) if node.args.kwarg is not None else ()),
            )
            for argument in arguments:
                if _annotation_is_layout(argument.annotation, child.bindings):
                    child.bindings.bind_layout(argument.arg, True)
                else:
                    child._invalidate_names({argument.arg})
            if isinstance(node, ast.Lambda):
                child.visit(node.body)
                return
            for statement in node.body:
                child.visit(statement)

        def _visit_comprehension(
            self,
            generators: list[ast.comprehension],
            expressions: tuple[ast.AST, ...],
        ) -> None:
            if not generators:
                for expression in expressions:
                    self.visit(expression)
                return
            self.visit(generators[0].iter)
            child = self._function_child()
            for index, generator in enumerate(generators):
                if index:
                    child.visit(generator.iter)
                child._invalidate_names(_assignment_names((generator.target,)))
                for condition in generator.ifs:
                    child.visit(condition)
            for expression in expressions:
                child.visit(expression)

        def visit_Import(self, node: ast.Import) -> None:
            for alias in node.names:
                local = alias.asname or alias.name.split(".", 1)[0]
                self._bind_noncanonical_alias(
                    local,
                    alias.name if alias.asname else local,
                    track_alias=_tracks_warehouse_namespace(alias.name),
                )

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            module = _import_from_module(path, node)
            if module is None:
                self._add_finding(
                    _producer_finding(
                        PRODUCER_UNRESOLVED_IMPORT,
                        path,
                        node.lineno,
                        "relative warehouse import escapes the inspected package root",
                        "Use an import that resolves inside the repository package hierarchy.",
                    )
                )
                return
            for alias in node.names:
                if alias.name == "*":
                    self._invalidate_star_import()
                    if module in {CANONICAL_WAREHOUSE_MODULE, CANONICAL_WAREHOUSE_PACKAGE}:
                        self._add_finding(
                            _producer_finding(
                                PRODUCER_UNRESOLVED_IMPORT,
                                path,
                                node.lineno,
                                "star import from the warehouse boundary cannot be resolved",
                                "Import write_table or upsert_table explicitly from the canonical warehouse API.",
                            )
                        )
                    continue
                local = alias.asname or alias.name
                if module in {CANONICAL_WAREHOUSE_MODULE, CANONICAL_WAREHOUSE_PACKAGE}:
                    if alias.name in {"write_table", "upsert_table"}:
                        self.bindings.bind_alias(
                            local, f"{CANONICAL_WAREHOUSE_MODULE}.{alias.name}"
                        )
                        self.bindings.bind_rebound_alias(local, False)
                        self.bindings.bind_layout(local, False)
                    elif alias.name == "WarehouseLayout":
                        self._bind_noncanonical_alias(local, CANONICAL_LAYOUT, track_alias=True)
                    elif alias.name == "io":
                        self._bind_noncanonical_alias(
                            local, CANONICAL_WAREHOUSE_MODULE, track_alias=True
                        )
                    elif _writer_like(alias.name):
                        self._add_finding(
                            _producer_finding(
                                PRODUCER_UNRESOLVED_IMPORT,
                                path,
                                node.lineno,
                                f"warehouse writer-like import {alias.name!r} is not canonical",
                                "Import write_table or upsert_table from trade_py.data.warehouse.io "
                                "or the package re-export.",
                            )
                        )
                    else:
                        self._invalidate_names({local})
                else:
                    target = f"{module}.{alias.name}"
                    self._bind_noncanonical_alias(
                        local,
                        target,
                        track_alias=_tracks_warehouse_namespace(target),
                    )
                    if module.startswith(CANONICAL_WAREHOUSE_PACKAGE) and _writer_like(alias.name):
                        self._add_finding(
                            _producer_finding(
                                PRODUCER_UNRESOLVED_IMPORT,
                                path,
                                node.lineno,
                                f"warehouse writer-like import {module}.{alias.name} is not canonical",
                                "Import a canonical writer from trade_py.data.warehouse.io.",
                            )
                        )

        def visit_Assign(self, node: ast.Assign) -> None:
            self.visit(node.value)
            self._bind_names(_assignment_names(node.targets), node.value)

        def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
            self.visit(node.annotation)
            if node.value is not None:
                self.visit(node.value)
            self._bind_names(
                _assignment_names((node.target,)),
                node.value,
                annotation=node.annotation,
            )

        def visit_AugAssign(self, node: ast.AugAssign) -> None:
            self.visit(node.value)
            self._invalidate_names(_assignment_names((node.target,)))

        def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
            self.visit(node.value)
            self._bind_names(_assignment_names((node.target,)), node.value)

        def visit_Delete(self, node: ast.Delete) -> None:
            self._invalidate_names(_assignment_names(node.targets))

        def visit_For(self, node: ast.For | ast.AsyncFor) -> None:
            self.visit(node.iter)
            self._invalidate_names(_assignment_names((node.target,)))
            for statement in node.body:
                self.visit(statement)
            for statement in node.orelse:
                self.visit(statement)

        visit_AsyncFor = visit_For

        def visit_With(self, node: ast.With | ast.AsyncWith) -> None:
            for item in node.items:
                self.visit(item.context_expr)
                if item.optional_vars is not None:
                    self._invalidate_names(_assignment_names((item.optional_vars,)))
            for statement in node.body:
                self.visit(statement)

        visit_AsyncWith = visit_With

        def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
            if node.type is not None:
                self.visit(node.type)
            if node.name is not None:
                self._invalidate_names({node.name})
            for statement in node.body:
                self.visit(statement)

        def visit_Match(self, node: ast.Match) -> None:
            self.visit(node.subject)
            for case in node.cases:
                self._invalidate_names(_pattern_binding_names(case.pattern))
                if case.guard is not None:
                    self.visit(case.guard)
                for statement in case.body:
                    self.visit(statement)

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            for decorator in node.decorator_list:
                self.visit(decorator)
            for default in (*node.args.defaults, *node.args.kw_defaults):
                if default is not None:
                    self.visit(default)
            self._visit_function_annotations(node)
            self._invalidate_names({node.name})
            self._visit_function(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            for decorator in node.decorator_list:
                self.visit(decorator)
            for default in (*node.args.defaults, *node.args.kw_defaults):
                if default is not None:
                    self.visit(default)
            self._visit_function_annotations(node)
            self._invalidate_names({node.name})
            self._visit_function(node)

        def visit_Lambda(self, node: ast.Lambda) -> None:
            self._visit_function(node)

        def _visit_function_annotations(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
            arguments = (
                *node.args.posonlyargs,
                *node.args.args,
                *node.args.kwonlyargs,
                *((node.args.vararg,) if node.args.vararg is not None else ()),
                *((node.args.kwarg,) if node.args.kwarg is not None else ()),
            )
            for argument in arguments:
                if argument.annotation is not None:
                    self.visit(argument.annotation)
            if node.returns is not None:
                self.visit(node.returns)

        def visit_ListComp(self, node: ast.ListComp) -> None:
            self._visit_comprehension(node.generators, (node.elt,))

        def visit_SetComp(self, node: ast.SetComp) -> None:
            self._visit_comprehension(node.generators, (node.elt,))

        def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
            self._visit_comprehension(node.generators, (node.elt,))

        def visit_DictComp(self, node: ast.DictComp) -> None:
            self._visit_comprehension(node.generators, (node.key, node.value))

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            for decorator in node.decorator_list:
                self.visit(decorator)
            for base in node.bases:
                self.visit(base)
            for keyword in node.keywords:
                self.visit(keyword.value)
            self._invalidate_names({node.name})
            child = _ProducerVisitor(
                self.lexical_bindings.child(),
                lexical_bindings=self.lexical_bindings,
            )
            for statement in node.body:
                child.visit(statement)

        def visit_Call(self, node: ast.Call) -> None:
            nonlocal producer_report_bytes
            writer = _resolve_expression(node.func, self.bindings)
            if writer not in CANONICAL_WRITERS:
                if isinstance(node.func, ast.Name) and self.bindings.is_rebound_alias(node.func.id):
                    self._add_finding(
                        _producer_finding(
                            PRODUCER_UNRESOLVED_IMPORT,
                            path,
                            node.lineno,
                            f"warehouse writer alias {node.func.id!r} was rebound or shadowed "
                            "before this call",
                            "Use a nonconflicting local name or an explicit canonical warehouse import.",
                        )
                    )
                self.generic_visit(node)
                return
            if not node.args or not _is_layout_expression(
                node.args[0], self.bindings, self.bindings
            ):
                self._add_finding(
                    _producer_finding(
                        PRODUCER_UNRESOLVED_LAYOUT,
                        path,
                        node.lineno,
                        f"canonical writer {writer} has no statically known WarehouseLayout first "
                        "argument",
                        "Bind the first argument from WarehouseLayout or WarehouseLayout.from_data_root.",
                    )
                )
                self.generic_visit(node)
                return
            if len(node.args) < 3 or not all(
                isinstance(argument, ast.Constant) and isinstance(argument.value, str)
                for argument in node.args[1:3]
            ):
                self._add_finding(
                    _producer_finding(
                        PRODUCER_NONLITERAL_TARGET,
                        path,
                        node.lineno,
                        f"canonical writer {writer} has a nonliteral layer or table target",
                        "Use literal layer and table strings so the artifact declaration is auditable.",
                    )
                )
                self.generic_visit(node)
                return
            if len(producers) >= producer_capacity:
                self._result_budget(
                    "canonical writer-call inventory exceeds the configured result budget"
                )
                return
            layer = node.args[1]
            table = node.args[2]
            assert isinstance(layer, ast.Constant) and isinstance(layer.value, str)
            assert isinstance(table, ast.Constant) and isinstance(table.value, str)
            literal = ast.unparse(node)
            if len(literal.encode("utf-8")) > limits.max_producer_literal_bytes:
                self._result_budget(
                    "canonical writer-call literal exceeds the configured result budget"
                )
                return
            producer = WarehouseProducer(
                source=path,
                line=node.lineno,
                column=node.col_offset,
                writer=writer,
                layer=layer.value,
                table=table.value,
                literal=literal,
                call_digest=_call_digest(node),
            )
            producer_size = _warehouse_producer_size(producer)
            if producer_report_bytes + producer_size > producer_report_capacity:
                self._result_budget(
                    "canonical writer-call report exceeds the configured result-byte budget"
                )
                return
            producers.append(producer)
            producer_report_bytes += producer_size
            self.generic_visit(node)

    try:
        _ProducerVisitor().visit(tree)
    except RecursionError:
        return [], [
            _producer_finding(
                PRODUCER_RESULT_BUDGET,
                path,
                1,
                "production source exceeds the guarded AST traversal recursion depth",
                "Reduce source nesting or make a reviewed governed AST-depth budget increase.",
            )
        ]
    if finding_budget_exceeded:
        return producers, [
            _producer_finding(
                PRODUCER_RESULT_BUDGET,
                path,
                1,
                "producer discovery findings exceed the configured result budget",
                "Reduce the producer scope or make a reviewed governed result-budget increase.",
            )
        ]
    return producers, findings


def _ast_shape(tree: ast.AST) -> tuple[int, int]:
    """Count AST nodes and maximum depth without recursive traversal."""

    node_count = 0
    maximum_depth = 0
    pending: list[tuple[ast.AST, int]] = [(tree, 1)]
    while pending:
        node, depth = pending.pop()
        node_count += 1
        maximum_depth = max(maximum_depth, depth)
        pending.extend((child, depth + 1) for child in ast.iter_child_nodes(node))
    return node_count, maximum_depth


def _import_from_module(path: str, node: ast.ImportFrom) -> str | None:
    if node.level == 0:
        return node.module or ""
    source_path = PurePosixPath(path)
    package_parts = list(source_path.parts[:-1])
    ascents = node.level - 1
    if ascents > len(package_parts):
        return None
    resolved = package_parts[: len(package_parts) - ascents]
    if node.module:
        resolved.extend(node.module.split("."))
    return ".".join(resolved)


def _tracks_warehouse_namespace(target: str) -> bool:
    return target == CANONICAL_WAREHOUSE_PACKAGE or target.startswith(
        f"{CANONICAL_WAREHOUSE_PACKAGE}."
    )


def _call_digest(node: ast.Call) -> str:
    """Fingerprint the semantic call shape without interpreter-local AST context."""

    normalized = repr(_ast_digest_value(node))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _ast_digest_value(value: Any) -> Any:
    if isinstance(value, ast.AST):
        return (
            type(value).__name__,
            tuple(
                (name, _ast_digest_value(field_value))
                for name, field_value in ast.iter_fields(value)
                if name != "ctx" and _ast_digest_field_is_present(field_value)
            ),
        )
    if isinstance(value, list):
        return tuple(_ast_digest_value(item) for item in value)
    return value


def _ast_digest_field_is_present(value: Any) -> bool:
    """Ignore absent optional fields added by a newer Python AST schema."""

    return value is not None and value != []


def _resolve_expression(node: ast.AST | None, aliases: Mapping[str, str]) -> str | None:
    if isinstance(node, ast.Name):
        return aliases.get(node.id)
    if not isinstance(node, ast.Attribute):
        return None
    base = _resolve_expression(node.value, aliases)
    if base is None and isinstance(node.value, ast.Name):
        base = aliases.get(node.value.id)
    if base is None:
        return None
    resolved = f"{base}.{node.attr}"
    if resolved in {
        f"{CANONICAL_WAREHOUSE_PACKAGE}.write_table",
        f"{CANONICAL_WAREHOUSE_PACKAGE}.upsert_table",
    }:
        return f"{CANONICAL_WAREHOUSE_MODULE}.{node.attr}"
    if resolved == f"{CANONICAL_WAREHOUSE_PACKAGE}.WarehouseLayout":
        return CANONICAL_LAYOUT
    return resolved


def _is_layout_factory(node: ast.AST | None, aliases: Mapping[str, str]) -> bool:
    if not isinstance(node, ast.Call):
        return False
    callee = _resolve_expression(node.func, aliases)
    return callee in {CANONICAL_LAYOUT, f"{CANONICAL_LAYOUT}.from_data_root"}


def _is_layout_expression(
    node: ast.AST,
    aliases: Mapping[str, str],
    bindings: _ScopedBindings,
) -> bool:
    return (
        isinstance(node, ast.Name)
        and bindings.is_layout(node.id)
        or _is_layout_factory(node, aliases)
    )


def _annotation_is_layout(node: ast.AST | None, aliases: Mapping[str, str]) -> bool:
    return _resolve_expression(node, aliases) == CANONICAL_LAYOUT


def _assignment_names(targets: Sequence[ast.AST]) -> set[str]:
    names: set[str] = set()
    for target in targets:
        if isinstance(target, ast.Name):
            names.add(target.id)
        elif isinstance(target, (ast.Tuple, ast.List)):
            names.update(_assignment_names(target.elts))
        elif isinstance(target, ast.Starred):
            names.update(_assignment_names((target.value,)))
    return names


def _pattern_binding_names(pattern: ast.pattern) -> set[str]:
    if isinstance(pattern, ast.MatchAs):
        names = _pattern_binding_names(pattern.pattern) if pattern.pattern is not None else set()
        if pattern.name is not None:
            names.add(pattern.name)
        return names
    if isinstance(pattern, ast.MatchStar):
        return {pattern.name} if pattern.name is not None else set()
    if isinstance(pattern, ast.MatchMapping):
        names = set()
        for nested in pattern.patterns:
            names.update(_pattern_binding_names(nested))
        if pattern.rest is not None:
            names.add(pattern.rest)
        return names
    if isinstance(pattern, ast.MatchClass):
        names = set()
        for nested in (*pattern.patterns, *pattern.kwd_patterns):
            names.update(_pattern_binding_names(nested))
        return names
    if isinstance(pattern, (ast.MatchSequence, ast.MatchOr)):
        names = set()
        for nested in pattern.patterns:
            names.update(_pattern_binding_names(nested))
        return names
    return set()


def _function_local_bindings(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Return lexical locals that shadow imports throughout a function scope."""

    locals_: set[str] = set()
    global_names: set[str] = set()
    nonlocal_names: set[str] = set()

    class _LocalBindingVisitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            locals_.add(node.name)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            locals_.add(node.name)

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            locals_.add(node.name)

        def visit_Lambda(self, node: ast.Lambda) -> None:
            return

        def visit_Assign(self, node: ast.Assign) -> None:
            locals_.update(_assignment_names(node.targets))
            self.visit(node.value)

        def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
            locals_.update(_assignment_names((node.target,)))
            if node.value is not None:
                self.visit(node.value)

        def visit_AugAssign(self, node: ast.AugAssign) -> None:
            locals_.update(_assignment_names((node.target,)))
            self.visit(node.value)

        def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
            locals_.update(_assignment_names((node.target,)))
            self.visit(node.value)

        def visit_Delete(self, node: ast.Delete) -> None:
            locals_.update(_assignment_names(node.targets))

        def visit_For(self, node: ast.For) -> None:
            locals_.update(_assignment_names((node.target,)))
            self.visit(node.iter)
            for statement in (*node.body, *node.orelse):
                self.visit(statement)

        def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
            locals_.update(_assignment_names((node.target,)))
            self.visit(node.iter)
            for statement in (*node.body, *node.orelse):
                self.visit(statement)

        def visit_With(self, node: ast.With) -> None:
            for item in node.items:
                self.visit(item.context_expr)
                if item.optional_vars is not None:
                    locals_.update(_assignment_names((item.optional_vars,)))
            for child in node.body:
                self.visit(child)

        def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
            for item in node.items:
                self.visit(item.context_expr)
                if item.optional_vars is not None:
                    locals_.update(_assignment_names((item.optional_vars,)))
            for child in node.body:
                self.visit(child)

        def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
            if node.name is not None:
                locals_.add(node.name)
            if node.type is not None:
                self.visit(node.type)
            for statement in node.body:
                self.visit(statement)

        def visit_Match(self, node: ast.Match) -> None:
            self.visit(node.subject)
            for case in node.cases:
                locals_.update(_pattern_binding_names(case.pattern))
                if case.guard is not None:
                    self.visit(case.guard)
                for statement in case.body:
                    self.visit(statement)

        def visit_Import(self, node: ast.Import) -> None:
            locals_.update(alias.asname or alias.name.split(".", 1)[0] for alias in node.names)

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            locals_.update(alias.asname or alias.name for alias in node.names if alias.name != "*")

        def visit_Global(self, node: ast.Global) -> None:
            global_names.update(node.names)

        def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
            nonlocal_names.update(node.names)

    visitor = _LocalBindingVisitor()
    for statement in node.body:
        visitor.visit(statement)
    return locals_ - global_names - nonlocal_names


def _writer_like(name: str) -> bool:
    lowered = name.lower()
    return "write" in lowered or "upsert" in lowered or "writer" in lowered


def _producer_finding(
    rule_id: str,
    path: str,
    line: int,
    message: str,
    remediation: str,
) -> ArchitectureFinding:
    return ArchitectureFinding(rule_id, path, line, message, remediation)


def _producer_path_budget_error(path: str, message: str) -> _GuardError:
    return _GuardError(
        PRODUCER_PATH_BUDGET,
        path,
        message,
        "Reduce or split the source scope, or make a reviewed governed budget increase.",
    )


def _producer_source_budget_error(path: str, message: str) -> _GuardError:
    return _GuardError(
        PRODUCER_SOURCE_BUDGET,
        path,
        message,
        "Reduce or split the source scope, or make a reviewed governed budget increase.",
    )


def _producer_result_budget_error(path: str, message: str) -> _GuardError:
    return _GuardError(
        PRODUCER_RESULT_BUDGET,
        path,
        message,
        "Reduce the producer scope or make a reviewed governed result-budget increase.",
    )


def _baseline_evidence_budget_error(
    path: str,
    message: str,
    *,
    remediation: str | None = None,
) -> _GuardError:
    return _GuardError(
        _BASELINE_EVIDENCE_BUDGET,
        path,
        message,
        remediation
        or "Reduce duplicate source evidence or make a reviewed governed evidence-budget increase.",
    )


def _warehouse_producer_size(producer: WarehouseProducer) -> int:
    return (
        sum(
            len(value.encode("utf-8"))
            for value in (
                producer.source,
                producer.writer,
                producer.layer,
                producer.table,
                producer.literal,
                producer.call_digest,
            )
        )
        + 16
    )


def _producer_report_size(producers: Sequence[WarehouseProducer]) -> int:
    return sum(_warehouse_producer_size(producer) for producer in producers)


def _git_timeout_error() -> _GuardError:
    return _GuardError(
        PRODUCER_TIMEOUT,
        "trade_py",
        "Git index discovery exceeded the configured timeout",
        "Repair the Git environment or make a reviewed governed timeout increase.",
    )


def _git_stderr_budget_error() -> _GuardError:
    return _GuardError(
        PRODUCER_TOOL_FAILURE,
        "trade_py",
        "Git index discovery exceeded the configured stderr diagnostic budget",
        "Repair the Git environment or make a reviewed governed stderr budget increase.",
    )


def _git_stderr_read_error(error: OSError | ValueError) -> _GuardError:
    return _GuardError(
        PRODUCER_TOOL_FAILURE,
        "trade_py",
        f"Git index discovery could not read stderr: {error}",
        "Repair the Git environment before running source-only discovery.",
    )


def _unsafe_source_error(path: str, message: str) -> _GuardError:
    return _GuardError(
        PRODUCER_UNSAFE_SOURCE,
        path,
        message,
        "Keep the source regular, repository-confined, and stable for the check.",
    )


def _is_safe_relative_path(path: str) -> bool:
    if not path or "\\" in path:
        return False
    pure = PurePosixPath(path)
    return not pure.is_absolute() and all(part not in {"", ".", ".."} for part in pure.parts)


def _ordered_findings(
    findings: Sequence[ArchitectureFinding],
) -> tuple[ArchitectureFinding, ...]:
    return tuple(
        sorted(
            findings,
            key=lambda item: (
                item.path,
                item.line if item.line is not None else -1,
                item.rule_id,
                item.message,
            ),
        )
    )


def _bounded_text(value: str, max_bytes: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    suffix = "...[truncated]"
    suffix_bytes = suffix.encode("utf-8")
    if max_bytes <= len(suffix_bytes):
        return encoded[:max_bytes].decode("utf-8", "ignore")
    budget = max_bytes - len(suffix_bytes)
    return encoded[:budget].decode("utf-8", "ignore") + suffix


def _bounded_finding(
    finding: ArchitectureFinding,
    limits: DiscoveryLimits,
) -> ArchitectureFinding:
    return ArchitectureFinding(
        rule_id=finding.rule_id,
        path=_bounded_text(finding.path, limits.max_diagnostic_field_bytes),
        line=finding.line,
        message=_bounded_text(finding.message, limits.max_diagnostic_field_bytes),
        remediation=_bounded_text(finding.remediation, limits.max_diagnostic_field_bytes),
    )


def _report(
    findings: Sequence[ArchitectureFinding],
    producers: Sequence[WarehouseProducer],
    limits: DiscoveryLimits,
) -> ArchitectureReport:
    ordered = _ordered_findings(findings)
    if len(ordered) <= limits.max_findings:
        emitted = tuple(_bounded_finding(finding, limits) for finding in ordered)
        omitted_count = 0
    elif limits.max_findings <= 0:
        emitted = ()
        omitted_count = len(ordered)
    else:
        emitted_real_count = limits.max_findings - 1
        omitted_count = len(ordered) - emitted_real_count
        truncation = ArchitectureFinding(
            _RESULT_TRUNCATED,
            BASELINE_FILENAME,
            None,
            f"{omitted_count} additional findings were omitted by the guarded report limit",
            "Address the emitted findings, then rerun the guard to inspect remaining issues.",
        )
        emitted = tuple(
            _bounded_finding(finding, limits) for finding in ordered[:emitted_real_count]
        ) + (_bounded_finding(truncation, limits),)
    return ArchitectureReport(
        findings=emitted,
        producers=tuple(producers),
        omitted_findings_count=omitted_count,
    )


__all__ = [
    "ArchitectureFinding",
    "ArchitectureReport",
    "DEFAULT_LIMITS",
    "DiscoveryLimits",
    "WarehouseProducer",
    "discover_warehouse_producers",
    "validate_architecture_baseline",
]
