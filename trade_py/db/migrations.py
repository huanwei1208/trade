"""Schema migration runner for trade.db.

Each entry is (version: int, sql: str). The sql is executed via executescript()
only when that version has not yet been applied.

Invariant: versions are applied in ascending order, at most once.
"""
from __future__ import annotations

import logging
import sqlite3

logger = logging.getLogger(__name__)

# ── Migration list ─────────────────────────────────────────────────────────────
# Version 1: bootstrap schema_migrations table (handled separately in run_migrations)
# Version 2: drop dead macro_events table
# Version 3: recreate signal_cache without dead columns (smart_money_signal, large_order_trend)
# Version 4: create bus_events table

MIGRATIONS: list[tuple[int, str]] = [
    (2, "DROP TABLE IF EXISTS macro_events;"),
    # Migration 3 is handled in Python (see run_migrations) because SQLite
    # cannot reference columns that may not exist in older schema versions.
    # Placeholder kept for version tracking.
    # (3, "handled below"),
    (4, """
        CREATE TABLE IF NOT EXISTS bus_events (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            topic        TEXT NOT NULL,
            payload      TEXT,
            status       TEXT DEFAULT 'pending',
            handler      TEXT,
            error        TEXT,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            processed_at TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_bus_topic   ON bus_events(topic);
        CREATE INDEX IF NOT EXISTS idx_bus_status  ON bus_events(status);
        CREATE INDEX IF NOT EXISTS idx_bus_created ON bus_events(created_at);
    """),
]


def _migrate_v3(conn: sqlite3.Connection) -> None:
    """Recreate signal_cache without dead columns (smart_money_signal, large_order_trend).

    Copies only columns that exist in all historical schema versions.
    Computed columns (event_kg_score, model_score, etc.) are left NULL
    and will be repopulated by the next pipeline run.
    """
    # Determine which columns exist in the current signal_cache
    existing = {row[1] for row in conn.execute("PRAGMA table_info(signal_cache)").fetchall()}

    # Build SELECT list: only copy columns that exist AND are in the new schema
    new_cols = [
        "date", "symbol", "window_score", "net_sentiment",
        "event_kg_score", "event_affected", "event_type", "event_typical_days",
        "model_score", "model_risk", "model_updated", "updated_at",
    ]
    select_parts = []
    for col in new_cols:
        if col in existing:
            select_parts.append(col)
        else:
            select_parts.append(f"NULL AS {col}")

    conn.executescript(f"""
        CREATE TABLE IF NOT EXISTS signal_cache_v2 (
            date               TEXT NOT NULL,
            symbol             TEXT NOT NULL,
            window_score       INTEGER,
            net_sentiment      REAL,
            event_kg_score     REAL,
            event_affected     INTEGER,
            event_type         TEXT,
            event_typical_days INTEGER,
            model_score        REAL,
            model_risk         REAL,
            model_updated      TEXT,
            updated_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (date, symbol)
        );
        INSERT OR IGNORE INTO signal_cache_v2
            SELECT {", ".join(select_parts)} FROM signal_cache;
        DROP TABLE signal_cache;
        ALTER TABLE signal_cache_v2 RENAME TO signal_cache;
    """)
    conn.commit()


def run_migrations(conn: sqlite3.Connection) -> None:
    """Apply any pending migrations in ascending version order."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(version INTEGER PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);"
    )
    conn.commit()

    applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations").fetchall()}

    # Migration 3: special-cased in Python due to dynamic column detection
    if 3 not in applied:
        logger.info("Applying DB migration v3 (signal_cache cleanup)")
        try:
            _migrate_v3(conn)
            conn.execute("INSERT INTO schema_migrations(version) VALUES (3)")
            conn.commit()
            logger.info("Migration v3 applied")
        except Exception as exc:
            logger.error("Migration v3 failed: %s", exc)
            raise

    for version, sql in MIGRATIONS:
        if version in applied:
            continue
        logger.info("Applying DB migration v%d", version)
        try:
            conn.executescript(sql)
            conn.execute(
                "INSERT INTO schema_migrations(version) VALUES (?)", (version,)
            )
            conn.commit()
            logger.info("Migration v%d applied", version)
        except Exception as exc:
            logger.error("Migration v%d failed: %s", version, exc)
            raise
