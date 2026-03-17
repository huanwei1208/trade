"""Schema migration runner for trade.db.

Each entry is (version: int, sql: str). The sql is executed via executescript()
only when that version has not yet been applied.

Invariant: versions are applied in ascending order, at most once.
"""
from __future__ import annotations

import logging
import sqlite3

logger = logging.getLogger(__name__)


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone())


def _col_exists(conn: sqlite3.Connection, table: str, col: str) -> bool:
    if not _table_exists(conn, table):
        return False
    return col in {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


# ── Migration list ─────────────────────────────────────────────────────────────
# Version 1: bootstrap schema_migrations table (handled separately in run_migrations)
# Version 2: drop dead macro_events table
# Version 3: recreate signal_cache without dead columns (smart_money_signal, large_order_trend)
# Version 4: create bus_events table
# Version 5: full schema redesign (handled in Python below)
# Version 6: learned KG review schema enhancements
# Version 7: intraday realtime DAG rows
# Version 8: calendar/planned-event DAG rows
# Version 9: daily evaluation DAG rows
# Version 10: UI snapshot cache + remove legacy brief DAG/settings

MIGRATIONS: list[tuple[int, str]] = [
    (2, "DROP TABLE IF EXISTS macro_events;"),
    # Migration 3 is handled in Python (see run_migrations)
    # Migration 4 is handled in Python (see run_migrations) — now superseded by v5 event_log
    # Migration 5 is handled in Python (see run_migrations)
]


def _migrate_v3(conn: sqlite3.Connection) -> None:
    """Recreate signal_cache without dead columns (smart_money_signal, large_order_trend)."""
    if not _table_exists(conn, "signal_cache"):
        return  # Already on new schema (signal_cache renamed to signals)

    existing = {row[1] for row in conn.execute("PRAGMA table_info(signal_cache)").fetchall()}

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


def _migrate_v4(conn: sqlite3.Connection) -> None:
    """Create bus_events table (legacy; v5 renames it to event_log)."""
    conn.executescript("""
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
    """)
    conn.commit()


def _migrate_v5(conn: sqlite3.Connection) -> None:
    """Full schema redesign:
    - Rename: bus_events→event_log, signal_cache→signals,
              instrument_sector_members→sector_members, events→market_events
    - Redesign: job_runs (new columns), event_propagations (rel_path, validated_at)
    - Create: sync_state (from downloads+watermarks), pipeline_dag, factors,
              model_registry, kg_relations, event_templates
    - Drop: job_schedule, downloads, watermarks
    """
    # 1. Migrate bus_events → event_log
    if _table_exists(conn, "bus_events"):
        conn.execute("""
            INSERT OR IGNORE INTO event_log
                (id, topic, payload, status, handler, error, created_at, processed_at)
                SELECT id, topic, payload, status, handler, error, created_at, processed_at
                FROM bus_events
        """)
        conn.execute("DROP TABLE IF EXISTS bus_events")

    # 2. Migrate signal_cache → signals
    if _table_exists(conn, "signal_cache"):
        conn.execute("""
            INSERT OR IGNORE INTO signals
                (date, symbol, window_score, net_sentiment,
                 event_kg_score, event_affected, event_type, event_typical_days,
                 model_score, model_risk, updated_at)
                SELECT date, symbol, window_score, net_sentiment,
                       event_kg_score, event_affected, event_type, event_typical_days,
                       model_score, model_risk, updated_at
                FROM signal_cache
        """)
        conn.execute("DROP TABLE IF EXISTS signal_cache")

    # 3. Migrate instrument_sector_members → sector_members
    if _table_exists(conn, "instrument_sector_members"):
        conn.execute("""
            INSERT OR IGNORE INTO sector_members
                (symbol, sector_code, sector_name, industry_code, updated_at)
                SELECT symbol, sector_code, sector_name, industry_code, updated_at
                FROM instrument_sector_members
        """)
        conn.execute("DROP TABLE IF EXISTS instrument_sector_members")

    # 4. Migrate events → market_events
    if _table_exists(conn, "events"):
        conn.execute("""
            INSERT OR IGNORE INTO market_events
                (event_id, event_date, event_type, entity_id,
                 magnitude, breadth, sentiment_score, news_volume, summary, created_at)
                SELECT event_id, event_date, event_type, primary_sector,
                       magnitude, breadth, sentiment_score, news_volume, summary, created_at
                FROM events
        """)
        conn.execute("DROP TABLE IF EXISTS events")

    # 5. Add new columns to event_propagations
    for ddl in [
        "ALTER TABLE event_propagations ADD COLUMN rel_path TEXT",
        "ALTER TABLE event_propagations ADD COLUMN validated_at TIMESTAMP",
    ]:
        try:
            conn.execute(ddl)
        except sqlite3.OperationalError:
            pass  # column already exists

    # 6. Add new columns to job_runs (non-destructive — keep legacy columns)
    for ddl in [
        "ALTER TABLE job_runs ADD COLUMN stage TEXT",
        "ALTER TABLE job_runs ADD COLUMN trigger_event_id INTEGER",
        "ALTER TABLE job_runs ADD COLUMN result_summary TEXT",
        "ALTER TABLE job_runs ADD COLUMN symbols_processed INTEGER",
        "ALTER TABLE job_runs ADD COLUMN elapsed_ms INTEGER",
        "ALTER TABLE job_runs ADD COLUMN completed_at TIMESTAMP",
    ]:
        try:
            conn.execute(ddl)
        except sqlite3.OperationalError:
            pass

    # 7. Migrate watermarks → sync_state
    if _table_exists(conn, "watermarks"):
        conn.execute("""
            INSERT OR IGNORE INTO sync_state
                (source, dataset, symbol, last_date, cursor, updated_at)
                SELECT source, dataset, symbol, last_event_date, cursor_payload, updated_at
                FROM watermarks
        """)
        conn.execute("DROP TABLE IF EXISTS watermarks")

    # 8. Migrate downloads → sync_state
    if _table_exists(conn, "downloads"):
        conn.execute("""
            INSERT OR REPLACE INTO sync_state
                (source, dataset, symbol, last_date, row_count, updated_at)
                SELECT 'tushare_kline', 'daily', symbol, end_date, row_count, downloaded_at
                FROM downloads
        """)
        conn.execute("DROP TABLE IF EXISTS downloads")

    # 9. Drop obsolete tables
    conn.execute("DROP TABLE IF EXISTS job_schedule")

    # 10. Add indexes that may be missing
    for idx_ddl in [
        "CREATE INDEX IF NOT EXISTS idx_ep_labeled ON event_propagations(validated_at)",
        "CREATE INDEX IF NOT EXISTS idx_job_stage  ON job_runs(stage)",
        "CREATE INDEX IF NOT EXISTS idx_job_event  ON job_runs(trigger_event_id)",
    ]:
        try:
            conn.execute(idx_ddl)
        except Exception:
            pass

    # 11. Seed event_templates if empty
    count = conn.execute("SELECT COUNT(*) FROM event_templates").fetchone()[0]
    if count == 0:
        conn.executemany(
            "INSERT OR IGNORE INTO event_templates "
            "(event_type, default_magnitude, typical_days, max_hop, decay_factor, description) "
            "VALUES (?,?,?,?,?,?)",
            [
                ("policy_positive",  0.6,  3, 2, 0.6, "政策利好"),
                ("policy_negative", -0.5,  3, 2, 0.6, "政策利空"),
                ("earnings_beat",    0.5,  1, 1, 0.4, "业绩超预期"),
                ("earnings_miss",   -0.6,  1, 1, 0.4, "业绩不及预期"),
                ("macro_positive",   0.3,  5, 3, 0.5, "宏观数据利好"),
                ("macro_negative",  -0.3,  5, 3, 0.5, "宏观数据利空"),
                ("supply_shock",    -0.7,  2, 2, 0.7, "供应链冲击"),
                ("sector_rotation",  0.4,  3, 1, 0.3, "板块轮动信号"),
            ],
        )

    # 12. Seed pipeline_dag if empty
    count = conn.execute("SELECT COUNT(*) FROM pipeline_dag").fetchone()[0]
    if count == 0:
        dag_rows = [
            # STAGE: fetch
            ("fetch", "gate.morning",            "kline_update",       "data.kline.synced",     1, "K线同步"),
            ("fetch", "gate.morning",            "cross_asset_fetch",  None,                    1, "跨资产数据"),
            ("fetch", "gate.pre_market",         "market_index",       "data.index.synced",     1, "指数数据"),
            ("fetch", "gate.signal_am",          "fund_flow_update",   None,                    1, "资金流向（早盘）"),
            ("fetch", "gate.market_close",       "fund_flow_update",   None,                    1, "资金流向（收盘）"),
            ("fetch", "gate.market_close",       "northbound",         None,                    1, "北向资金"),
            ("fetch", "gate.evening",            "sentiment_pipeline", "data.sentiment.synced", 1, "情绪流水线"),
            ("fetch", "gate.sector_weekly",      "sector_refresh",     None,                    1, "板块成员刷新"),
            ("fetch", "gate.fundamental_weekly", "fundamental",        None,                    1, "基本面数据"),
            ("fetch", "gate.macro_weekly",       "macro",              None,                    1, "宏观数据"),
            # STAGE: compute
            ("compute", "data.kline.synced",     "window_score",   "signal.window.updated",  1, "K线完成→全市场评分"),
            ("compute", "gate.signal_am",        "window_score",   "signal.window.updated",  1, "早盘前全市场评分"),
            ("compute", "gate.market_close",     "window_score",   "signal.window.updated",  1, "收盘后全市场评分"),
            ("compute", "data.sentiment.synced", "event_pipeline", None,                     1, "情绪→事件级联"),
            ("compute", "gate.event_extract",    "event_pipeline", None,                     1, "事件提取"),
            ("compute", "gate.report",           "morning_brief",  "report.morning_brief",   1, "晨报生成"),
            ("compute", "gate.model_weekly",     "build_features", "model.features.built",   1, "特征构建"),
            ("compute", "model.features.built",  "build_labels",   "model.labels.built",     1, "标签构建"),
            # STAGE: train
            ("train",   "model.labels.built",    "model_train",    "model.trained",          1, "模型训练"),
        ]
        conn.executemany(
            "INSERT INTO pipeline_dag (stage, source, job_name, emits, enabled, description) "
            "VALUES (?,?,?,?,?,?)",
            dag_rows,
        )

    conn.commit()


def _migrate_v6(conn: sqlite3.Connection) -> None:
    """Extend KG tables for learned/reviewed relations."""
    for ddl in [
        "ALTER TABLE kg_relations ADD COLUMN direction INTEGER NOT NULL DEFAULT 1",
        "ALTER TABLE kg_relations ADD COLUMN typical_days INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE kg_relations ADD COLUMN confidence REAL NOT NULL DEFAULT 0.0",
        "ALTER TABLE kg_relations ADD COLUMN sample_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE kg_relations ADD COLUMN evidence_json TEXT",
        "ALTER TABLE kg_relations ADD COLUMN status TEXT NOT NULL DEFAULT 'active'",
        "ALTER TABLE kg_relations ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
    ]:
        try:
            conn.execute(ddl)
        except sqlite3.OperationalError:
            pass

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS kg_edge_candidates (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            from_entity         TEXT NOT NULL,
            to_entity           TEXT NOT NULL,
            rel_type            TEXT NOT NULL,
            weight              REAL NOT NULL DEFAULT 0.0,
            direction           INTEGER NOT NULL DEFAULT 1,
            lag_days            INTEGER NOT NULL DEFAULT 0,
            confidence          REAL NOT NULL DEFAULT 0.0,
            sample_count        INTEGER NOT NULL DEFAULT 0,
            price_link_score    REAL NOT NULL DEFAULT 0.0,
            stability_score     REAL NOT NULL DEFAULT 0.0,
            event_support_score REAL NOT NULL DEFAULT 0.0,
            raw_score           REAL NOT NULL DEFAULT 0.0,
            source              TEXT,
            evidence_json       TEXT,
            status              TEXT NOT NULL DEFAULT 'pending',
            generated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            reviewed_at         TIMESTAMP,
            reviewer            TEXT,
            review_note         TEXT,
            UNIQUE (from_entity, to_entity, rel_type)
        );
        CREATE INDEX IF NOT EXISTS idx_kg_candidate_status
            ON kg_edge_candidates(status);
        CREATE INDEX IF NOT EXISTS idx_kg_candidate_from
            ON kg_edge_candidates(from_entity);
        CREATE INDEX IF NOT EXISTS idx_kg_candidate_to
            ON kg_edge_candidates(to_entity);
        CREATE INDEX IF NOT EXISTS idx_kg_candidate_type
            ON kg_edge_candidates(rel_type);
    """)

    try:
        conn.execute("""
            UPDATE kg_relations
            SET direction = CASE WHEN weight < 0 THEN -1 ELSE 1 END
            WHERE direction IS NULL OR direction = 0
        """)
    except Exception:
        pass
    try:
        conn.execute("UPDATE kg_relations SET weight = ABS(weight) WHERE weight < 0")
    except Exception:
        pass
    try:
        conn.execute("UPDATE kg_relations SET status = 'active' WHERE status IS NULL OR status = ''")
    except Exception:
        pass
    conn.commit()


def _migrate_v7(conn: sqlite3.Connection) -> None:
    """Seed intraday realtime DAG rows for scheduler-driven minute pipeline."""
    if not _table_exists(conn, "pipeline_dag"):
        return
    rows = [
        ("fetch", "gate.intraday", "realtime_quote_sync", "data.realtime.synced", 1, "盘中分钟行情"),
        ("compute", "data.realtime.synced", "realtime_compute", None, 1, "盘中分钟因子"),
    ]
    for stage, source, job_name, emits, enabled, description in rows:
        exists = conn.execute(
            """
            SELECT 1 FROM pipeline_dag
            WHERE stage=? AND source=? AND job_name=?
            LIMIT 1
            """,
            (stage, source, job_name),
        ).fetchone()
        if exists:
            continue
        conn.execute(
            """
            INSERT INTO pipeline_dag
                (stage, source, job_name, emits, enabled, description)
            VALUES (?,?,?,?,?,?)
            """,
            (stage, source, job_name, emits, enabled, description),
        )
    
    conn.commit()


def _migrate_v8(conn: sqlite3.Connection) -> None:
    """Seed calendar/planned-event DAG rows for scheduler-driven future-event sync."""
    if not _table_exists(conn, "pipeline_dag"):
        return
    rows = [
        ("fetch", "gate.macro_weekly", "calendar_sync", None, 1, "交易日历同步"),
        ("fetch", "gate.evening", "planned_event_sync", None, 1, "未来计划事件同步"),
    ]
    for stage, source, job_name, emits, enabled, description in rows:
        exists = conn.execute(
            """
            SELECT 1 FROM pipeline_dag
            WHERE stage=? AND source=? AND job_name=?
            LIMIT 1
            """,
            (stage, source, job_name),
        ).fetchone()
        if exists:
            continue
        conn.execute(
            """
            INSERT INTO pipeline_dag
                (stage, source, job_name, emits, enabled, description)
            VALUES (?,?,?,?,?,?)
            """,
            (stage, source, job_name, emits, enabled, description),
        )
    conn.commit()


def _migrate_v9(conn: sqlite3.Connection) -> None:
    """Seed daily evaluation DAG rows for scheduler-driven quality gate refresh."""
    if not _table_exists(conn, "pipeline_dag"):
        return
    rows = [
        ("compute", "gate.evaluate_daily", "evaluate_daily", None, 1, "日常全链路评估"),
    ]
    for stage, source, job_name, emits, enabled, description in rows:
        exists = conn.execute(
            """
            SELECT 1 FROM pipeline_dag
            WHERE stage=? AND source=? AND job_name=?
            LIMIT 1
            """,
            (stage, source, job_name),
        ).fetchone()
        if exists:
            continue
        conn.execute(
            """
            INSERT INTO pipeline_dag
                (stage, source, job_name, emits, enabled, description)
            VALUES (?,?,?,?,?,?)
            """,
            (stage, source, job_name, emits, enabled, description),
        )
    conn.commit()


def _migrate_v10(conn: sqlite3.Connection) -> None:
    """Create UI snapshot cache and remove legacy brief/report DAG artifacts."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS ui_snapshots (
            snapshot_key    TEXT NOT NULL,
            scope           TEXT NOT NULL DEFAULT 'default',
            signature       TEXT NOT NULL,
            payload_json    TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'ok',
            built_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at      TIMESTAMP,
            build_ms        INTEGER NOT NULL DEFAULT 0,
            producer        TEXT NOT NULL DEFAULT 'web',
            PRIMARY KEY (snapshot_key, scope)
        );
        CREATE INDEX IF NOT EXISTS idx_ui_snapshots_expiry
            ON ui_snapshots(expires_at);
    """)
    if _table_exists(conn, "pipeline_dag"):
        conn.execute(
            """
            DELETE FROM pipeline_dag
            WHERE job_name='morning_brief'
               OR source='gate.report'
               OR emits='report.morning_brief'
            """
        )
    if _table_exists(conn, "settings"):
        conn.execute("DELETE FROM settings WHERE key='scheduler.brief_time'")
    conn.commit()


def run_migrations(conn: sqlite3.Connection) -> None:
    """Apply any pending migrations in ascending version order."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(version INTEGER PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);"
    )
    conn.commit()

    applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations").fetchall()}

    # ── v2: plain SQL ─────────────────────────────────────────────────────────
    if 2 not in applied:
        logger.info("Applying DB migration v2")
        conn.execute("DROP TABLE IF EXISTS macro_events")
        conn.commit()
        conn.execute("INSERT INTO schema_migrations(version) VALUES (2)")
        conn.commit()

    # ── v3: Python-assisted signal_cache cleanup ───────────────────────────────
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

    # ── v4: bus_events table (legacy) ─────────────────────────────────────────
    if 4 not in applied:
        logger.info("Applying DB migration v4 (bus_events)")
        try:
            _migrate_v4(conn)
            conn.execute("INSERT INTO schema_migrations(version) VALUES (4)")
            conn.commit()
            logger.info("Migration v4 applied")
        except Exception as exc:
            logger.error("Migration v4 failed: %s", exc)
            raise

    # ── v5: full schema redesign ───────────────────────────────────────────────
    if 5 not in applied:
        logger.info("Applying DB migration v5 (schema redesign)")
        try:
            _migrate_v5(conn)
            conn.execute("INSERT INTO schema_migrations(version) VALUES (5)")
            conn.commit()
            logger.info("Migration v5 applied")
        except Exception as exc:
            logger.error("Migration v5 failed: %s", exc)
            raise

    # ── v6: learned KG schema enhancements ────────────────────────────────────
    if 6 not in applied:
        logger.info("Applying DB migration v6 (learned KG)")
        try:
            _migrate_v6(conn)
            conn.execute("INSERT INTO schema_migrations(version) VALUES (6)")
            conn.commit()
            logger.info("Migration v6 applied")
        except Exception as exc:
            logger.error("Migration v6 failed: %s", exc)
            raise

    # ── v7: intraday realtime DAG rows ───────────────────────────────────────
    if 7 not in applied:
        logger.info("Applying DB migration v7 (intraday realtime DAG)")
        try:
            _migrate_v7(conn)
            conn.execute("INSERT INTO schema_migrations(version) VALUES (7)")
            conn.commit()
            logger.info("Migration v7 applied")
        except Exception as exc:
            logger.error("Migration v7 failed: %s", exc)
            raise

    # ── v8: calendar DAG rows ────────────────────────────────────────────────
    if 8 not in applied:
        logger.info("Applying DB migration v8 (calendar DAG)")
        try:
            _migrate_v8(conn)
            conn.execute("INSERT INTO schema_migrations(version) VALUES (8)")
            conn.commit()
            logger.info("Migration v8 applied")
        except Exception as exc:
            logger.error("Migration v8 failed: %s", exc)
            raise

    # ── v9: daily evaluation DAG rows ───────────────────────────────────────
    if 9 not in applied:
        logger.info("Applying DB migration v9 (daily evaluation DAG)")
        try:
            _migrate_v9(conn)
            conn.execute("INSERT INTO schema_migrations(version) VALUES (9)")
            conn.commit()
            logger.info("Migration v9 applied")
        except Exception as exc:
            logger.error("Migration v9 failed: %s", exc)
            raise

    # ── v10: UI snapshots + remove legacy brief DAG/settings ────────────────
    if 10 not in applied:
        logger.info("Applying DB migration v10 (UI snapshots / remove brief DAG)")
        try:
            _migrate_v10(conn)
            conn.execute("INSERT INTO schema_migrations(version) VALUES (10)")
            conn.commit()
            logger.info("Migration v10 applied")
        except Exception as exc:
            logger.error("Migration v10 failed: %s", exc)
            raise
