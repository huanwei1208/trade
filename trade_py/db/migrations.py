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
# Version 12: disable legacy sentiment_pipeline + event_pipeline DAG rows

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


def _migrate_v12(conn: sqlite3.Connection) -> None:
    """Disable legacy sentiment_pipeline and event_pipeline DAG rows.

    The v11 migration added split replacement rows:
      sentiment_fetch → sentiment_silver → sentiment_gold (replacing sentiment_pipeline)
      event_extract → kg_propagate (replacing both event_pipeline rows)
    Keeping the old rows active creates duplicate paths in the DAG view.
    """
    if not _table_exists(conn, "pipeline_dag"):
        return
    # Disable old monolithic sentiment_pipeline that listens on gate.evening
    conn.execute(
        "UPDATE pipeline_dag SET enabled=0 WHERE job_name='sentiment_pipeline'"
    )
    # Disable both old event_pipeline rows (data.sentiment.synced and gate.event_extract)
    conn.execute(
        "UPDATE pipeline_dag SET enabled=0 WHERE job_name='event_pipeline'"
    )
    conn.commit()


def _migrate_v11(conn: sqlite3.Connection) -> None:
    """Extend pipeline_dag with config_json, sync_source, sync_dataset, mode columns."""
    # Add new columns
    for ddl in [
        "ALTER TABLE pipeline_dag ADD COLUMN config_json TEXT DEFAULT '{}'",
        "ALTER TABLE pipeline_dag ADD COLUMN sync_source TEXT",
        "ALTER TABLE pipeline_dag ADD COLUMN sync_dataset TEXT",
        "ALTER TABLE pipeline_dag ADD COLUMN mode TEXT DEFAULT 'batch'",
    ]:
        try:
            conn.execute(ddl)
        except sqlite3.OperationalError:
            pass  # column already exists

    # Populate sync_source/sync_dataset hints for known jobs
    sync_map = {
        "kline_update":     ("tushare_kline", "daily"),
        "fund_flow_update": ("tushare_fundflow", "daily"),
        "sentiment_fetch":  ("sentiment", "bronze"),
        "sentiment_silver": ("sentiment", "silver"),
        "sentiment_gold":   ("sentiment", "gold"),
        "sentiment_pipeline": ("sentiment", "gold"),
        "event_extract":    ("events", "market_events"),
        "event_pipeline":   ("events", "market_events"),
        "fundamental":      ("tushare_fina", "indicator"),
        "macro":            ("tushare_macro", "shibor"),
    }
    for job_name, (src, ds) in sync_map.items():
        try:
            conn.execute(
                "UPDATE pipeline_dag SET sync_source=?, sync_dataset=? "
                "WHERE job_name=? AND (sync_source IS NULL OR sync_source='')",
                (src, ds, job_name),
            )
        except Exception:
            pass

    # Set mode for streaming/both nodes
    streaming_jobs = ["realtime_quote_sync", "realtime_compute"]
    both_jobs = ["sentiment_fetch", "sentiment_silver", "window_score"]
    for job in streaming_jobs:
        try:
            conn.execute(
                "UPDATE pipeline_dag SET mode='streaming' WHERE job_name=? AND mode='batch'",
                (job,),
            )
        except Exception:
            pass
    for job in both_jobs:
        try:
            conn.execute(
                "UPDATE pipeline_dag SET mode='both' WHERE job_name=? AND mode='batch'",
                (job,),
            )
        except Exception:
            pass

    # Add new split job rows for sentiment + event chains (if not already present)
    if not _table_exists(conn, "pipeline_dag"):
        conn.commit()
        return
    new_rows = [
        # Sentiment chain (split from sentiment_pipeline)
        ("fetch", "gate.evening", "sentiment_fetch", "sentiment.fetched", 1, "情绪抓取（增量）"),
        ("fetch", "sentiment.fetched", "sentiment_silver", "sentiment.silver_done", 1, "情绪评分 Silver"),
        ("fetch", "sentiment.silver_done", "sentiment_gold", "sentiment.gold_done", 1, "情绪聚合 Gold"),
        # Event chain (split from event_pipeline)
        ("compute", "sentiment.gold_done", "event_extract", "events.extracted", 1, "事件提取"),
        ("compute", "events.extracted", "kg_propagate", "signals.events_updated", 1, "KG 传导"),
    ]
    for stage, source, job_name, emits, enabled, description in new_rows:
        exists = conn.execute(
            "SELECT 1 FROM pipeline_dag WHERE stage=? AND source=? AND job_name=? LIMIT 1",
            (stage, source, job_name),
        ).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO pipeline_dag (stage, source, job_name, emits, enabled, description) "
                "VALUES (?,?,?,?,?,?)",
                (stage, source, job_name, emits, enabled, description),
            )
    conn.commit()


def _migrate_v13(conn: sqlite3.Connection) -> None:
    """EBRT schema: 10 new tables for Evidence → Belief → Recommendation → Trust."""
    conn.executescript("""
        -- 1. ArticleEvent: Silver 行规范化（content_hash PK）
        CREATE TABLE IF NOT EXISTS ArticleEvent (
            article_id          TEXT PRIMARY KEY,
            published_at        TEXT NOT NULL,
            source_id           TEXT NOT NULL,
            feed_name           TEXT,
            url                 TEXT,
            title               TEXT,
            symbol              TEXT NOT NULL,
            event_type          TEXT,
            event_magnitude     REAL,
            sentiment_score     REAL,
            sentiment_label     TEXT,
            policy_signal       INTEGER,
            entity_density      REAL,
            novelty_score       REAL,
            noise_score         REAL,
            extractor           TEXT NOT NULL,
            extractor_conf      REAL NOT NULL,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_article_event_sym  ON ArticleEvent(symbol, published_at);
        CREATE INDEX IF NOT EXISTS idx_article_event_src  ON ArticleEvent(source_id);

        -- 2. InfluenceSignal: 信源影响力
        CREATE TABLE IF NOT EXISTS InfluenceSignal (
            influence_id        TEXT PRIMARY KEY,
            source_id           TEXT NOT NULL,
            actor_id            TEXT,
            platform            TEXT,
            published_at        TEXT NOT NULL,
            topic_tags          TEXT,
            reach_estimate      REAL,
            reputation_score    REAL,
            manipulation_risk   REAL,
            cross_confirm_1h    REAL,
            cross_confirm_24h   REAL,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_influence_source ON InfluenceSignal(source_id);
        CREATE INDEX IF NOT EXISTS idx_influence_date   ON InfluenceSignal(published_at);

        -- 3. Evidence: 规范化证据单元（symbol/day 粒度）
        CREATE TABLE IF NOT EXISTS Evidence (
            evidence_id         TEXT PRIMARY KEY,
            as_of_date          TEXT NOT NULL,
            symbol              TEXT NOT NULL,
            evidence_type       TEXT NOT NULL,
            payload_ref         TEXT NOT NULL,
            strength            REAL NOT NULL,
            direction           REAL NOT NULL,
            reliability         REAL NOT NULL,
            novelty             REAL NOT NULL,
            noise_penalty       REAL NOT NULL,
            influence_boost     REAL NOT NULL,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(as_of_date, symbol, evidence_type, payload_ref)
        );
        CREATE INDEX IF NOT EXISTS idx_evidence_date   ON Evidence(as_of_date);
        CREATE INDEX IF NOT EXISTS idx_evidence_symbol ON Evidence(symbol, as_of_date);

        -- 4. BeliefState: 每日每 symbol 的信念快照
        CREATE TABLE IF NOT EXISTS BeliefState (
            as_of_date          TEXT NOT NULL,
            symbol              TEXT NOT NULL,
            belief_vec_json     TEXT NOT NULL,
            belief_version      TEXT NOT NULL,
            confidence          REAL NOT NULL,
            uncertainty         REAL NOT NULL,
            updated_at          TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(as_of_date, symbol)
        );
        CREATE INDEX IF NOT EXISTS idx_belief_date   ON BeliefState(as_of_date);
        CREATE INDEX IF NOT EXISTS idx_belief_symbol ON BeliefState(symbol);

        -- 5. AttentionScore: 注意力权重（可解释审计）
        CREATE TABLE IF NOT EXISTS AttentionScore (
            attention_id        TEXT PRIMARY KEY,
            as_of_date          TEXT NOT NULL,
            symbol              TEXT NOT NULL,
            evidence_id         TEXT NOT NULL REFERENCES Evidence(evidence_id),
            logit               REAL NOT NULL,
            weight              REAL NOT NULL,
            factors_json        TEXT NOT NULL,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_attention_date   ON AttentionScore(as_of_date, symbol);
        CREATE INDEX IF NOT EXISTS idx_attention_evid   ON AttentionScore(evidence_id);

        -- 6. BeliefTransition: 残差更新记录
        CREATE TABLE IF NOT EXISTS BeliefTransition (
            transition_id       TEXT PRIMARY KEY,
            symbol              TEXT NOT NULL,
            t_date              TEXT NOT NULL,
            t1_date             TEXT NOT NULL,
            prev_belief_ref     TEXT NOT NULL,
            next_belief_ref     TEXT NOT NULL,
            delta_vec_json      TEXT NOT NULL,
            decay_lambda        REAL NOT NULL,
            gain_eta            REAL NOT NULL,
            conflict_score      REAL NOT NULL,
            attention_set_id    TEXT NOT NULL,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_transition_sym  ON BeliefTransition(symbol, t1_date);
        CREATE INDEX IF NOT EXISTS idx_transition_date ON BeliefTransition(t1_date);

        -- 7. Recommendation: 每日决策输出
        CREATE TABLE IF NOT EXISTS Recommendation (
            rec_id              TEXT PRIMARY KEY,
            as_of_date          TEXT NOT NULL,
            symbol              TEXT NOT NULL,
            action              TEXT NOT NULL,
            conviction          TEXT NOT NULL,
            score               REAL NOT NULL,
            risk                REAL NOT NULL,
            horizon_days        INTEGER NOT NULL,
            reasons_json        TEXT NOT NULL,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(as_of_date, symbol)
        );
        CREATE INDEX IF NOT EXISTS idx_rec_date   ON Recommendation(as_of_date);
        CREATE INDEX IF NOT EXISTS idx_rec_symbol ON Recommendation(symbol);
        CREATE INDEX IF NOT EXISTS idx_rec_score  ON Recommendation(as_of_date, score DESC);

        -- 8. QualityReport: Trust 合同
        CREATE TABLE IF NOT EXISTS QualityReport (
            eval_date           TEXT PRIMARY KEY,
            operational_status  TEXT NOT NULL,
            research_status     TEXT NOT NULL,
            brier_score         REAL,
            calibration_json    TEXT,
            drift_mmd           REAL,
            reasons_json        TEXT NOT NULL,
            metrics_json        TEXT NOT NULL,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP
        );

        -- 9. FreshnessStatus: 每数据集新鲜度
        CREATE TABLE IF NOT EXISTS FreshnessStatus (
            as_of_date          TEXT NOT NULL,
            dataset             TEXT NOT NULL,
            freshness_date      TEXT,
            lag_days            INTEGER,
            coverage_pct        REAL,
            status              TEXT NOT NULL,
            details_json        TEXT,
            updated_at          TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(as_of_date, dataset)
        );
        CREATE INDEX IF NOT EXISTS idx_freshness_date ON FreshnessStatus(as_of_date);

        -- 10. RecommendationTrace: 端到端溯源
        CREATE TABLE IF NOT EXISTS RecommendationTrace (
            trace_id            TEXT PRIMARY KEY,
            as_of_date          TEXT NOT NULL,
            symbol              TEXT NOT NULL,
            rec_id              TEXT NOT NULL REFERENCES Recommendation(rec_id),
            belief_transition_id TEXT,
            top_evidence_json   TEXT NOT NULL,
            model_versions_json TEXT,
            data_fingerprint    TEXT NOT NULL,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_trace_date   ON RecommendationTrace(as_of_date);
        CREATE INDEX IF NOT EXISTS idx_trace_symbol ON RecommendationTrace(symbol);
        CREATE INDEX IF NOT EXISTS idx_trace_rec    ON RecommendationTrace(rec_id);
    """)

    # Seed EBRT DAG rows (belief_update + recommend)
    if _table_exists(conn, "pipeline_dag"):
        new_dag_rows = [
            ("compute", "sentiment.gold_done",   "belief_update", "belief.updated",    1, "信念状态更新"),
            ("compute", "belief.updated",         "recommend",     "recommend.produced", 1, "推荐决策生成"),
        ]
        for stage, source, job_name, emits, enabled, description in new_dag_rows:
            exists = conn.execute(
                "SELECT 1 FROM pipeline_dag WHERE stage=? AND source=? AND job_name=? LIMIT 1",
                (stage, source, job_name),
            ).fetchone()
            if not exists:
                conn.execute(
                    "INSERT INTO pipeline_dag (stage, source, job_name, emits, enabled, description) "
                    "VALUES (?,?,?,?,?,?)",
                    (stage, source, job_name, emits, enabled, description),
                )

    conn.commit()


def _migrate_v14(conn: sqlite3.Connection) -> None:
    """Multi-horizon belief fields + extended Recommendation/Trace columns.

    Strategy:
    - BeliefState.belief_vec_json is extended to carry mu_1d/5d/20d and
      sigma_1d/5d/20d in-JSON; PK (as_of_date, symbol) unchanged.
    - Recommendation gains expected_return_5d, risk_5pct, position_weight,
      horizon_set_json.
    - RecommendationTrace gains trust_json (7-component vector) and
      narrative_text (Chinese explanation paragraph).
    """
    # Recommendation extended columns (safe to ignore if already present)
    for col_def in [
        "expected_return_5d REAL",
        "risk_5pct REAL",
        "position_weight REAL",
        "horizon_set_json TEXT",
    ]:
        col_name = col_def.split()[0]
        existing = [row[1] for row in conn.execute(
            "PRAGMA table_info(Recommendation)"
        ).fetchall()]
        if col_name not in existing:
            conn.execute(f"ALTER TABLE Recommendation ADD COLUMN {col_def}")

    # RecommendationTrace extended columns
    for col_def in [
        "trust_json TEXT",
        "narrative_text TEXT",
    ]:
        col_name = col_def.split()[0]
        existing = [row[1] for row in conn.execute(
            "PRAGMA table_info(RecommendationTrace)"
        ).fetchall()]
        if col_name not in existing:
            conn.execute(f"ALTER TABLE RecommendationTrace ADD COLUMN {col_def}")

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

    # ── v11: pipeline_dag extended columns + split job rows ────────────────
    if 11 not in applied:
        logger.info("Applying DB migration v11 (pipeline_dag extensions)")
        try:
            _migrate_v11(conn)
            conn.execute("INSERT INTO schema_migrations(version) VALUES (11)")
            conn.commit()
            logger.info("Migration v11 applied")
        except Exception as exc:
            logger.error("Migration v11 failed: %s", exc)
            raise

    # ── v12: disable legacy sentiment_pipeline + event_pipeline DAG rows ───
    if 12 not in applied:
        logger.info("Applying DB migration v12 (disable legacy split DAG rows)")
        try:
            _migrate_v12(conn)
            conn.execute("INSERT INTO schema_migrations(version) VALUES (12)")
            conn.commit()
            logger.info("Migration v12 applied")
        except Exception as exc:
            logger.error("Migration v12 failed: %s", exc)
            raise

    # ── v13: EBRT tables (Evidence → Belief → Recommendation → Trust) ───────
    if 13 not in applied:
        logger.info("Applying DB migration v13 (EBRT tables)")
        try:
            _migrate_v13(conn)
            conn.execute("INSERT INTO schema_migrations(version) VALUES (13)")
            conn.commit()
            logger.info("Migration v13 applied")
        except Exception as exc:
            logger.error("Migration v13 failed: %s", exc)
            raise

    # ── v14: multi-horizon belief + extended Recommendation/Trace ────────────
    if 14 not in applied:
        logger.info("Applying DB migration v14 (multi-horizon belief + extended Recommendation/Trace)")
        try:
            _migrate_v14(conn)
            conn.execute("INSERT INTO schema_migrations(version) VALUES (14)")
            conn.commit()
            logger.info("Migration v14 applied")
        except Exception as exc:
            logger.error("Migration v14 failed: %s", exc)
            raise
