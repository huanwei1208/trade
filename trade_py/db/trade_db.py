"""TradeDB — single consolidated SQLite wrapper.

Merges SettingsDB and InstrumentsDB into one class that connects to a single
trade.db file and runs schema migrations on construction.

DB location (in priority order):
  1. {data_root}/.db/trade.db      (new path, post-migration)
  2. {data_root}/.metadata/trade.db (legacy path, pre-migration)
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from trade_py.db.migrations import run_migrations
from trade_py.db._utils import _json_loads_safe  # noqa: F401 (re-exported for compat)
from trade_py.db.ebrt_crud import EBRTCRUDMixin
from trade_py.db.signal_crud import SignalCRUDMixin
from trade_py.db.kg_crud import KGCRUDMixin
from trade_py.utils.a_share_symbols import infer_a_share_suffix

logger = logging.getLogger(__name__)
_REPO_ROOT = Path(__file__).resolve().parents[2]

# ── Instruments helpers ────────────────────────────────────────────────────────

_MARKET_SH = 0
_MARKET_SZ = 1
_MARKET_BJ = 2
_BOARD_MAIN = 0
_BOARD_ST = 1
_BOARD_STAR = 2
_BOARD_CHINEXT = 3
_BOARD_BSE = 4
_STATUS_NORMAL = 0
_STATUS_SUSPENDED = 1
_STATUS_ST = 2
_STATUS_STAR_ST = 3
_INDUSTRY_UNKNOWN = 255

_INDUSTRY_NAMES = {
    0: "农林牧渔", 1: "采掘", 2: "基础化工", 3: "钢铁", 4: "有色金属",
    5: "电子", 6: "汽车", 7: "家用电器", 8: "食品饮料", 9: "纺织服装",
    10: "轻工制造", 11: "医药生物", 12: "公用事业", 13: "交通运输", 14: "房地产",
    15: "商业贸易", 16: "社会服务", 17: "银行", 18: "非银金融", 19: "建筑装饰",
    20: "建筑材料", 21: "机械设备", 22: "国防军工", 23: "计算机", 24: "传媒",
    25: "通信", 26: "环保", 27: "电力设备", 28: "美容护理", 29: "煤炭",
    30: "石油石化", _INDUSTRY_UNKNOWN: "未分类",
}


_DEFAULT_SETTINGS: list[tuple[str, str, str, str, str]] = [
    ("risk.target_annual_vol",   "0.11",    "float",  "risk",      "目标年化波动率"),
    ("risk.max_single_weight",   "0.10",    "float",  "risk",      "单股最大仓位"),
    ("risk.max_industry_weight", "0.35",    "float",  "risk",      "行业最大仓位"),
    ("risk.base_cash_pct",       "0.10",    "float",  "risk",      "基础现金比例"),
    ("cost.stamp_tax_rate",      "0.0005",  "float",  "risk",      "印花税率"),
    ("cost.commission_rate",     "0.00025", "float",  "risk",      "佣金率"),
    ("cost.commission_min_yuan", "5.0",     "float",  "risk",      "最低佣金（元）"),
    ("backtest.initial_capital", "1000000", "float",  "backtest",  "初始资金（元）"),
    ("backtest.max_positions",   "25",      "int",    "backtest",  "最大持仓数"),
    ("backtest.min_positions",   "15",      "int",    "backtest",  "最小持仓数"),
    ("signal.window_act_threshold",   "80", "int",    "signal",    "出手窗口质量分 cutoff"),
    ("signal.window_watch_threshold", "60", "int",    "signal",    "观察窗口质量分 cutoff"),
    ("scheduler.scan_interval",  "5",       "int",    "scheduler", "盘中扫描间隔（分钟）"),
    ("kline.start",              "2024-01-01", "string", "market_data", "K线默认起始日期"),
    ("index.start_date",         "2024-01-01", "string", "market_data", "指数/板块默认起始日期"),
    ("tushare.http_url",         "",       "string", "market_data", "Tushare API URL"),
    ("tushare.min_interval_sec", "0.6",    "float",  "market_data", "Tushare最小请求间隔（秒）"),
    ("tushare.minute_budget",    "50",     "int",    "market_data", "Tushare每分钟预算"),
    ("tushare.chunk_days",       "1825",   "int",    "market_data", "Tushare K线单次请求天数跨度"),
    ("tushare.rate_limit_backoff_sec", "5,15,30,45,60", "string", "market_data", "Tushare限流退避序列（秒）"),
    ("tushare.audit_log_enabled","1",      "bool",   "market_data", "Tushare请求审计日志"),
    ("storage.enabled",          "0", "bool", "storage", "启用远端存储/备份"),
    ("storage.backend",          "local", "string", "storage", "存储后端"),
    ("storage.google_drive_key_file", "", "string", "storage", "Google Drive service account key file"),
    ("storage.google_drive_folder_id", "", "string", "storage", "Google Drive root folder id"),
    ("storage.google_drive_timeout_ms", "30000", "int", "storage", "Google Drive timeout"),
    ("storage.google_drive_retry_count", "2", "int", "storage", "Google Drive retry count"),
    ("storage.backup_remote_dir", "trade-backups", "string", "storage", "备份远端目录"),
    ("sentiment.start",          "2024-01-01", "string", "market_data", "情绪数据默认起始日期"),
    ("sentiment.scheduler_semantic_mode", "base", "string", "market_data", "调度情绪流水线语义模式"),
    ("sentiment.settle_window_days", "7", "int", "market_data", "情绪数据稳定窗口（天）"),
    ("event.min_magnitude",      "0.4",   "float",  "market_data", "事件提取最低强度"),
    ("event.sync_window_days",   "7",     "int",    "market_data", "事件补齐窗口（天）"),
    ("eval.min_fund_flow_coverage", "0.85", "float", "evaluation", "资金流覆盖率门槛"),
    ("eval.min_fundamental_coverage", "0.85", "float", "evaluation", "基本面覆盖率门槛"),
    ("eval.min_event_count", "5", "int", "evaluation", "每日最少事件数"),
    ("eval.min_labeled_propagation_ratio", "0.05", "float", "evaluation", "事件标签成熟度门槛"),
    ("eval.min_model_rank_ic_5d", "0.02", "float", "evaluation", "模型 5d RankIC 门槛"),
    ("hooks.notify_url",  "",               "string", "hooks", "推送 Webhook URL"),
    ("hooks.notify_on",   "failure,success", "string", "hooks", "触发推送的事件"),
]

_CONFIG_JSON_SEEDS: list[tuple[str, str, str, str]] = [
    ("config.defaults", "trade_py/infra/config/defaults.json", "config", "历史默认配置"),
    ("catalog.feeds.backfill_priority", "trade_py/infra/config/feeds/backfill_priority.json", "catalog", "回补优先级目录"),
    ("catalog.feeds.china_public", "trade_py/infra/config/feeds/china_public.json", "catalog", "中国公开 feed 目录"),
    ("catalog.feeds.gdelt", "trade_py/infra/config/feeds/gdelt.json", "catalog", "GDELT 频道目录"),
    ("catalog.feeds.global_public", "trade_py/infra/config/feeds/global_public.json", "catalog", "全球公开 feed 目录"),
    ("catalog.feeds.premium", "trade_py/infra/config/feeds/premium.json", "catalog", "付费 feed 目录"),
    ("catalog.feeds.rss", "trade_py/infra/config/feeds/rss.json", "catalog", "RSS feed 目录"),
]

_CONFIG_TEXT_SEEDS: list[tuple[str, str, str, str]] = [
    ("config.module.market_data", "trade_py/infra/config/modules/market_data.yaml", "config", "市场数据模块配置"),
    ("config.module.security", "trade_py/infra/config/modules/security.yaml", "config", "安全模块配置"),
    ("config.module.sentiment", "trade_py/infra/config/modules/sentiment.yaml", "config", "情绪模块配置"),
    ("config.module.storage", "trade_py/infra/config/modules/storage.yaml", "config", "存储模块配置"),
    ("config.resource.sentiment_dict", "trade_py/infra/config/sentiment_dict.txt", "config", "情绪词典"),
]


def _infer_market(code: str) -> int:
    suffix = infer_a_share_suffix(code)
    if suffix == ".BJ":
        return _MARKET_BJ
    if suffix == ".SH":
        return _MARKET_SH
    return _MARKET_SZ


def _market_name(market: int) -> str:
    names = {0: "Shanghai", 1: "Shenzhen", 2: "Beijing", 3: "Hong Kong", 4: "US", 5: "Crypto"}
    return names.get(market, "Unknown")


def _is_st_name(name: str) -> bool:
    upper = name.strip().upper().replace(" ", "")
    return upper.startswith(("*ST", "ST", "S*ST", "SST"))


def _infer_board(symbol: str, name: str) -> int:
    code = symbol.split(".")[0]
    suffix = symbol.split(".")[-1].upper() if "." in symbol else ""
    if _is_st_name(name):
        return _BOARD_ST
    if suffix == "BJ":
        return _BOARD_BSE
    if suffix == "SH" and code.startswith("688"):
        return _BOARD_STAR
    if suffix == "SZ" and code.startswith("30"):
        return _BOARD_CHINEXT
    return _BOARD_MAIN


def _infer_status(name: str) -> int:
    upper = name.strip().upper().replace(" ", "")
    if upper.startswith("*ST"):
        return _STATUS_STAR_ST
    if upper.startswith(("ST", "S*ST", "SST")):
        return _STATUS_ST
    return _STATUS_NORMAL


def _industry_case_expr(column: str) -> str:
    parts = [f"WHEN {code} THEN '{name}'" for code, name in _INDUSTRY_NAMES.items() if code != _INDUSTRY_UNKNOWN]
    return "CASE " + column + " " + " ".join(parts) + f" ELSE '{_INDUSTRY_NAMES[_INDUSTRY_UNKNOWN]}' END"


def _normalize_date_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    if not text or text.lower() in {"none", "null", "nan", "nat"}:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 8:
        digits = digits[:8]
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


# _json_loads_safe is imported from trade_py.db._utils above

def _read_repo_json(rel_path: str) -> Any:
    path = _REPO_ROOT / rel_path
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_repo_text(rel_path: str) -> str | None:
    path = _REPO_ROOT / rel_path
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _find_db_path(data_root: Path) -> Path:
    new_path = data_root / ".db" / "trade.db"
    if new_path.exists():
        return new_path
    legacy = data_root / ".metadata" / "trade.db"
    if legacy.exists():
        return legacy
    return new_path


class TradeDB(EBRTCRUDMixin, SignalCRUDMixin, KGCRUDMixin):
    """Unified SQLite wrapper for all trade metadata.

    Combines SettingsDB (settings, watchlist, signals, events, job tracking)
    and InstrumentsDB (instruments, sync_state, sector members).
    Runs schema migrations on construction.

    Domain-specific CRUD is split into mixins:
        EBRTCRUDMixin  — ArticleEvent/Evidence/BeliefState/Recommendation/QualityReport
        SignalCRUDMixin — signals/factors/model_registry/evaluation tables
        KGCRUDMixin    — kg_nodes/kg_relations/market_events/event_propagations
    """

    def __init__(self, data_root: str | Path = "data") -> None:
        self._data_root = Path(data_root)
        db_file = _find_db_path(self._data_root)
        db_file.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_file), timeout=30, check_same_thread=False)
        self._conn_lock = threading.RLock()
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA busy_timeout=30000")
        self._conn.execute("PRAGMA temp_store=MEMORY")
        self._init_schema()
        run_migrations(self._conn)
        self._ensure_indexes()   # safe after migrations have added new columns
        self._ensure_model_registry_columns()
        self._seed_defaults()

    def close(self) -> None:
        with self._conn_lock:
            self._conn.close()

    def __enter__(self) -> "TradeDB":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    # ── Schema ─────────────────────────────────────────────────────────────────

    def _init_schema(self) -> None:
        """Create all tables in their final form."""
        self._conn.executescript("""
            -- SYS
            CREATE TABLE IF NOT EXISTS settings (
                key         TEXT PRIMARY KEY,
                value       TEXT NOT NULL,
                value_type  TEXT NOT NULL DEFAULT 'string',
                category    TEXT NOT NULL DEFAULT 'general',
                label       TEXT,
                description TEXT,
                updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- USR
            CREATE TABLE IF NOT EXISTS watchlist (
                symbol    TEXT PRIMARY KEY,
                added_at  DATE NOT NULL DEFAULT (date('now')),
                note      TEXT,
                active    INTEGER NOT NULL DEFAULT 1
            );

            -- COMPUTE: signals (was signal_cache)
            CREATE TABLE IF NOT EXISTS signals (
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
                model_version      TEXT,
                updated_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (date, symbol)
            );
            CREATE INDEX IF NOT EXISTS idx_signals_date   ON signals(date);
            CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals(symbol);

            -- OBS: event_log (was bus_events)
            CREATE TABLE IF NOT EXISTS event_log (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                topic           TEXT NOT NULL,
                payload         TEXT,
                parent_event_id INTEGER REFERENCES event_log(id),
                status          TEXT DEFAULT 'pending',
                handler         TEXT,
                error           TEXT,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processed_at    TIMESTAMP,
                elapsed_ms      INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_event_topic   ON event_log(topic);
            CREATE INDEX IF NOT EXISTS idx_event_status  ON event_log(status);
            CREATE INDEX IF NOT EXISTS idx_event_created ON event_log(created_at);
            CREATE INDEX IF NOT EXISTS idx_event_parent  ON event_log(parent_event_id);

            -- OBS: job_runs (redesigned)
            CREATE TABLE IF NOT EXISTS job_runs (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                job_name          TEXT NOT NULL,
                stage             TEXT,
                trigger_event_id  INTEGER,
                status            TEXT NOT NULL DEFAULT 'running',
                result_summary    TEXT,
                symbols_processed INTEGER,
                started_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                completed_at      TIMESTAMP,
                elapsed_ms        INTEGER,
                -- Legacy columns kept for backward compat
                message           TEXT,
                finished_at       TIMESTAMP,
                duration_s        REAL
            );
            CREATE INDEX IF NOT EXISTS idx_job_name   ON job_runs(job_name);
            CREATE INDEX IF NOT EXISTS idx_job_status ON job_runs(status);

            -- REF: instruments
            CREATE TABLE IF NOT EXISTS instruments (
                symbol        TEXT PRIMARY KEY,
                name          TEXT,
                market        INTEGER,
                board         INTEGER,
                industry      INTEGER,
                list_date     TEXT,
                delist_date   TEXT,
                status        INTEGER,
                total_shares  INTEGER DEFAULT 0,
                float_shares  INTEGER DEFAULT 0,
                market_name   TEXT NOT NULL DEFAULT ''
            );

            -- REF: sector_members (was instrument_sector_members)
            CREATE TABLE IF NOT EXISTS sector_members (
                symbol        TEXT PRIMARY KEY,
                sector_code   TEXT NOT NULL,
                sector_name   TEXT NOT NULL,
                industry_code INTEGER NOT NULL,
                updated_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_sector_code     ON sector_members(sector_code);
            CREATE INDEX IF NOT EXISTS idx_sector_industry ON sector_members(industry_code);

            -- SYNC: sync_state (merged from downloads + watermarks)
            CREATE TABLE IF NOT EXISTS sync_state (
                source     TEXT NOT NULL,
                dataset    TEXT NOT NULL,
                symbol     TEXT NOT NULL DEFAULT '',
                last_date  TEXT,
                row_count  INTEGER,
                cursor     TEXT DEFAULT '{}',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (source, dataset, symbol)
            );
            CREATE INDEX IF NOT EXISTS idx_sync_source ON sync_state(source, dataset);
            CREATE INDEX IF NOT EXISTS idx_sync_symbol ON sync_state(symbol);

            -- CAL: trading calendar
            CREATE TABLE IF NOT EXISTS trading_calendar (
                exchange           TEXT NOT NULL,
                trade_date         TEXT NOT NULL,
                is_open            INTEGER NOT NULL DEFAULT 0,
                pretrade_date      TEXT,
                session_am_open    TEXT,
                session_am_close   TEXT,
                session_pm_open    TEXT,
                session_pm_close   TEXT,
                source             TEXT NOT NULL DEFAULT 'tushare',
                updated_at         TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (exchange, trade_date)
            );
            CREATE INDEX IF NOT EXISTS idx_trading_calendar_date
                ON trading_calendar(trade_date);
            CREATE INDEX IF NOT EXISTS idx_trading_calendar_open
                ON trading_calendar(exchange, is_open, trade_date);

            -- CAL: planned/future events
            CREATE TABLE IF NOT EXISTS planned_events (
                planned_event_id   TEXT PRIMARY KEY,
                source             TEXT NOT NULL,
                vendor_event_id    TEXT,
                event_type         TEXT NOT NULL,
                entity_id          TEXT,
                event_date         TEXT NOT NULL,
                event_time         TEXT,
                scheduled_at       TEXT NOT NULL,
                timezone           TEXT NOT NULL DEFAULT 'Asia/Shanghai',
                title              TEXT NOT NULL,
                country            TEXT,
                currency           TEXT,
                importance         TEXT NOT NULL DEFAULT 'medium',
                status             TEXT NOT NULL DEFAULT 'scheduled',
                expected_value     TEXT,
                previous_value     TEXT,
                actual_value       TEXT,
                realized_event_id  TEXT,
                payload_json       TEXT,
                created_at         TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at         TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_planned_events_when
                ON planned_events(status, scheduled_at);
            CREATE INDEX IF NOT EXISTS idx_planned_events_type
                ON planned_events(event_type, event_date);
            CREATE INDEX IF NOT EXISTS idx_planned_events_entity
                ON planned_events(entity_id, event_date);

            -- CAL: agenda queue
            CREATE TABLE IF NOT EXISTS agenda_queue (
                agenda_id          INTEGER PRIMARY KEY AUTOINCREMENT,
                planned_event_id   TEXT NOT NULL REFERENCES planned_events(planned_event_id),
                phase              TEXT NOT NULL,
                run_at             TEXT NOT NULL,
                trigger_topic      TEXT NOT NULL DEFAULT '',
                job_name           TEXT NOT NULL DEFAULT '',
                payload_json       TEXT,
                priority           INTEGER NOT NULL DEFAULT 100,
                status             TEXT NOT NULL DEFAULT 'pending',
                executed_at        TEXT,
                result_summary     TEXT,
                created_at         TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at         TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (planned_event_id, phase, run_at, trigger_topic, job_name)
            );
            CREATE INDEX IF NOT EXISTS idx_agenda_queue_due
                ON agenda_queue(status, run_at, priority);
            CREATE INDEX IF NOT EXISTS idx_agenda_queue_event
                ON agenda_queue(planned_event_id, phase);

            -- OPS: backup snapshots
            CREATE TABLE IF NOT EXISTS backup_snapshots (
                snapshot_id         TEXT PRIMARY KEY,
                label               TEXT,
                driver              TEXT NOT NULL DEFAULT 'local',
                scope               TEXT NOT NULL DEFAULT 'data_root',
                archive_path        TEXT,
                manifest_path       TEXT,
                remote_archive_path TEXT,
                remote_manifest_path TEXT,
                status              TEXT NOT NULL DEFAULT 'created',
                size_bytes          INTEGER NOT NULL DEFAULT 0,
                file_count          INTEGER NOT NULL DEFAULT 0,
                sha256              TEXT,
                created_at          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                restored_at         TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_backup_snapshots_created
                ON backup_snapshots(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_backup_snapshots_status
                ON backup_snapshots(status, created_at DESC);

            -- UI snapshot cache
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

            CREATE TABLE IF NOT EXISTS readiness_recovery_actions (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                dataset             TEXT NOT NULL,
                date_from           TEXT NOT NULL,
                date_to             TEXT NOT NULL,
                action_type         TEXT NOT NULL,
                mode                TEXT NOT NULL,
                status              TEXT NOT NULL DEFAULT 'queued',
                requested_at        TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                job_names_json      TEXT,
                affected_outputs_json TEXT,
                request_json        TEXT,
                result_json         TEXT,
                summary             TEXT,
                error               TEXT,
                fingerprint_before  TEXT,
                fingerprint_after   TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_recovery_actions_dataset
                ON readiness_recovery_actions(dataset, date_from, date_to);
            CREATE INDEX IF NOT EXISTS idx_recovery_actions_status
                ON readiness_recovery_actions(status, requested_at DESC);

            CREATE TABLE IF NOT EXISTS causal_decision_snapshots (
                snapshot_id          TEXT PRIMARY KEY,
                symbol               TEXT NOT NULL,
                as_of_date           TEXT NOT NULL,
                action               TEXT,
                decision_confidence  REAL,
                data_model_trust     REAL,
                inferred_state_json  TEXT NOT NULL,
                chain_json           TEXT NOT NULL,
                created_at           TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at           TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(symbol, as_of_date)
            );
            CREATE INDEX IF NOT EXISTS idx_causal_snapshots_symbol_date
                ON causal_decision_snapshots(symbol, as_of_date DESC);

            CREATE TABLE IF NOT EXISTS causal_validation_outcomes (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_id          TEXT NOT NULL REFERENCES causal_decision_snapshots(snapshot_id),
                symbol               TEXT NOT NULL,
                decision_as_of       TEXT NOT NULL,
                evaluation_date      TEXT,
                horizon              TEXT NOT NULL,
                predicted_direction  TEXT,
                realized_return      REAL,
                realized_volatility  REAL,
                invalidator_hit      INTEGER,
                calibration_error    REAL,
                decision_correctness TEXT,
                notes                TEXT,
                payload_json         TEXT NOT NULL,
                created_at           TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(snapshot_id, horizon)
            );
            CREATE INDEX IF NOT EXISTS idx_causal_validation_snapshot
                ON causal_validation_outcomes(snapshot_id, horizon);

            CREATE TABLE IF NOT EXISTS causal_reward_punishment (
                id                          INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_id                 TEXT NOT NULL REFERENCES causal_decision_snapshots(snapshot_id),
                target_type                 TEXT NOT NULL,
                target_id                   TEXT NOT NULL,
                reward_score                REAL,
                punishment_score            REAL,
                rationale                   TEXT,
                evaluation_horizon          TEXT NOT NULL,
                derived_from_validation_id  TEXT,
                payload_json                TEXT NOT NULL,
                created_at                  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_causal_reward_snapshot
                ON causal_reward_punishment(snapshot_id, evaluation_horizon);

            -- CFG: pipeline_dag
            CREATE TABLE IF NOT EXISTS pipeline_dag (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                stage       TEXT NOT NULL DEFAULT 'fetch',
                source      TEXT NOT NULL,
                job_name    TEXT NOT NULL,
                emits       TEXT,
                enabled     INTEGER DEFAULT 1,
                description TEXT,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_dag_source  ON pipeline_dag(source);
            CREATE INDEX IF NOT EXISTS idx_dag_stage   ON pipeline_dag(stage);
            CREATE INDEX IF NOT EXISTS idx_dag_enabled ON pipeline_dag(enabled);

            -- COMPUTE: factors
            CREATE TABLE IF NOT EXISTS factors (
                date         TEXT NOT NULL,
                symbol       TEXT NOT NULL,
                factor_name  TEXT NOT NULL,
                factor_type  TEXT NOT NULL,
                value        REAL NOT NULL,
                updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (date, symbol, factor_name)
            );
            CREATE INDEX IF NOT EXISTS idx_factors_date   ON factors(date);
            CREATE INDEX IF NOT EXISTS idx_factors_symbol ON factors(symbol);
            CREATE INDEX IF NOT EXISTS idx_factors_type   ON factors(factor_type);

            CREATE TABLE IF NOT EXISTS factor_registry (
                factor_name   TEXT PRIMARY KEY,
                factor_type   TEXT NOT NULL,
                factor_layer  TEXT NOT NULL DEFAULT 'feature_store',
                description   TEXT,
                source        TEXT NOT NULL DEFAULT 'system',
                updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_factor_registry_type ON factor_registry(factor_type);
            CREATE INDEX IF NOT EXISTS idx_factor_registry_layer ON factor_registry(factor_layer);

            -- MODEL: model_registry
            CREATE TABLE IF NOT EXISTS model_registry (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                model_name  TEXT NOT NULL,
                target_name TEXT,
                model_type  TEXT NOT NULL,
                backend     TEXT DEFAULT 'lgbm',
                artifact_format TEXT DEFAULT 'joblib',
                file_path   TEXT NOT NULL,
                feature_set TEXT,
                dataset_snapshot_id INTEGER,
                metrics     TEXT,
                trained_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                is_active   INTEGER DEFAULT 1,
                promotion_state TEXT NOT NULL DEFAULT 'active'
            );
            CREATE INDEX IF NOT EXISTS idx_model_name   ON model_registry(model_name);
            CREATE INDEX IF NOT EXISTS idx_model_active ON model_registry(is_active);

            -- EVAL: source health
            CREATE TABLE IF NOT EXISTS source_health_daily (
                eval_date         TEXT NOT NULL,
                source_name       TEXT NOT NULL,
                source_family     TEXT,
                provider_kind     TEXT,
                bronze_days       INTEGER NOT NULL DEFAULT 0,
                article_rows      INTEGER NOT NULL DEFAULT 0,
                unique_articles   INTEGER NOT NULL DEFAULT 0,
                duplicate_rate    REAL NOT NULL DEFAULT 0.0,
                empty_day_rate    REAL NOT NULL DEFAULT 1.0,
                ingest_runs       INTEGER NOT NULL DEFAULT 0,
                ingest_error_rate REAL NOT NULL DEFAULT 0.0,
                records_fetched   INTEGER NOT NULL DEFAULT 0,
                records_new       INTEGER NOT NULL DEFAULT 0,
                healthy           INTEGER NOT NULL DEFAULT 0,
                details_json      TEXT,
                updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (eval_date, source_name)
            );

            CREATE TABLE IF NOT EXISTS source_eval_daily (
                eval_date           TEXT NOT NULL,
                source_name         TEXT NOT NULL,
                source_family       TEXT,
                provider_kind       TEXT,
                silver_rows         INTEGER NOT NULL DEFAULT 0,
                event_rows          INTEGER NOT NULL DEFAULT 0,
                event_yield_per_100 REAL NOT NULL DEFAULT 0.0,
                labeled_rows        INTEGER NOT NULL DEFAULT 0,
                rank_ic_5d          REAL,
                details_json        TEXT,
                updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (eval_date, source_name)
            );

            CREATE TABLE IF NOT EXISTS event_eval_runs (
                id                       INTEGER PRIMARY KEY AUTOINCREMENT,
                eval_date                TEXT NOT NULL,
                start_date               TEXT NOT NULL,
                end_date                 TEXT NOT NULL,
                status                   TEXT NOT NULL DEFAULT 'ok',
                event_count              INTEGER NOT NULL DEFAULT 0,
                effective_event_rate     REAL NOT NULL DEFAULT 0.0,
                sw_unknown_ratio         REAL NOT NULL DEFAULT 0.0,
                propagations_per_event   REAL NOT NULL DEFAULT 0.0,
                labeled_propagation_ratio REAL NOT NULL DEFAULT 0.0,
                avg_actual_return_5d     REAL,
                avg_actual_return_20d    REAL,
                details_json             TEXT,
                created_at               TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (eval_date, start_date, end_date)
            );

            CREATE TABLE IF NOT EXISTS model_eval_runs (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                eval_date            TEXT NOT NULL,
                model_name           TEXT NOT NULL,
                target_name          TEXT NOT NULL,
                model_version        TEXT,
                status               TEXT NOT NULL DEFAULT 'ok',
                sample_count         INTEGER NOT NULL DEFAULT 0,
                valid_days           INTEGER NOT NULL DEFAULT 0,
                rank_ic              REAL,
                mae                  REAL,
                topk_hit_rate        REAL,
                sector_concentration REAL,
                risk_brier_score     REAL,
                baseline_json        TEXT,
                calibration_json     TEXT,
                details_json         TEXT,
                created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (eval_date, model_name, target_name)
            );

            CREATE TABLE IF NOT EXISTS dataset_snapshots (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_name     TEXT NOT NULL,
                eval_date         TEXT NOT NULL,
                start_date        TEXT,
                end_date          TEXT,
                source_count      INTEGER NOT NULL DEFAULT 0,
                market_event_count INTEGER NOT NULL DEFAULT 0,
                propagation_count INTEGER NOT NULL DEFAULT 0,
                feature_rows      INTEGER NOT NULL DEFAULT 0,
                labeled_rows_5d   INTEGER NOT NULL DEFAULT 0,
                labeled_rows_20d  INTEGER NOT NULL DEFAULT 0,
                signal_dates      INTEGER NOT NULL DEFAULT 0,
                metadata_json     TEXT,
                created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (snapshot_name, eval_date)
            );

            CREATE TABLE IF NOT EXISTS daily_quality_gate (
                eval_date       TEXT PRIMARY KEY,
                status          TEXT NOT NULL DEFAULT 'blocked_by_dependency',
                reason_summary  TEXT,
                reasons_json    TEXT,
                metrics_json    TEXT,
                updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- KG: kg_relations
            CREATE TABLE IF NOT EXISTS kg_nodes (
                entity_id    TEXT PRIMARY KEY,
                entity_type  TEXT NOT NULL,
                display_name TEXT,
                source       TEXT,
                status       TEXT NOT NULL DEFAULT 'active',
                updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_kg_nodes_type ON kg_nodes(entity_type);
            CREATE INDEX IF NOT EXISTS idx_kg_nodes_status ON kg_nodes(status);

            CREATE TABLE IF NOT EXISTS kg_relations (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                from_entity TEXT NOT NULL,
                to_entity   TEXT NOT NULL,
                rel_type    TEXT NOT NULL,
                weight      REAL NOT NULL DEFAULT 1.0,
                direction   INTEGER NOT NULL DEFAULT 1,
                typical_days INTEGER NOT NULL DEFAULT 0,
                confidence  REAL NOT NULL DEFAULT 0.0,
                sample_count INTEGER NOT NULL DEFAULT 0,
                source      TEXT,
                valid_from  DATE,
                valid_to    DATE,
                evidence_json TEXT,
                status      TEXT NOT NULL DEFAULT 'active',
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (from_entity, to_entity, rel_type)
            );
            CREATE INDEX IF NOT EXISTS idx_kg_from ON kg_relations(from_entity);
            CREATE INDEX IF NOT EXISTS idx_kg_to   ON kg_relations(to_entity);
            CREATE INDEX IF NOT EXISTS idx_kg_type ON kg_relations(rel_type);

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
            CREATE INDEX IF NOT EXISTS idx_kg_candidate_status ON kg_edge_candidates(status);
            CREATE INDEX IF NOT EXISTS idx_kg_candidate_from ON kg_edge_candidates(from_entity);
            CREATE INDEX IF NOT EXISTS idx_kg_candidate_to ON kg_edge_candidates(to_entity);
            CREATE INDEX IF NOT EXISTS idx_kg_candidate_type ON kg_edge_candidates(rel_type);

            -- KG: event_templates
            CREATE TABLE IF NOT EXISTS event_templates (
                event_type        TEXT PRIMARY KEY,
                default_magnitude REAL,
                typical_days      INTEGER,
                max_hop           INTEGER DEFAULT 2,
                decay_factor      REAL DEFAULT 0.6,
                description       TEXT
            );

            -- KG: market_events (was events)
            CREATE TABLE IF NOT EXISTS market_events (
                event_id        TEXT PRIMARY KEY,
                event_date      DATE NOT NULL,
                event_type      TEXT NOT NULL,
                entity_id       TEXT,
                magnitude       REAL NOT NULL,
                confidence      REAL DEFAULT 1.0,
                breadth         TEXT,
                sentiment_score REAL,
                news_volume     INTEGER,
                summary         TEXT,
                source_hash     TEXT,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_mevt_date   ON market_events(event_date);
            CREATE INDEX IF NOT EXISTS idx_mevt_entity ON market_events(entity_id);
            CREATE INDEX IF NOT EXISTS idx_mevt_type   ON market_events(event_type);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_mevt_src ON market_events(source_hash)
                WHERE source_hash IS NOT NULL;

            -- KG: event_propagations (redesigned)
            CREATE TABLE IF NOT EXISTS event_propagations (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id          TEXT NOT NULL,
                symbol            TEXT NOT NULL,
                hop               INTEGER NOT NULL DEFAULT 0,
                rel_path          TEXT,
                kg_score          REAL,
                typical_days      INTEGER,
                actual_return_5d  REAL,
                actual_return_20d REAL,
                validated_at      TIMESTAMP,
                created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (event_id, symbol)
            );
            CREATE INDEX IF NOT EXISTS idx_ep_event  ON event_propagations(event_id);
            CREATE INDEX IF NOT EXISTS idx_ep_symbol ON event_propagations(symbol);
        """)
        self._conn.commit()
        self._ensure_instruments_columns()
        self._rebuild_classification_view()

    def _ensure_indexes(self) -> None:
        """Create indexes that depend on columns added by migrations (safe to call after migrations)."""
        for ddl in [
            "CREATE INDEX IF NOT EXISTS idx_ep_labeled ON event_propagations(validated_at)",
            "CREATE INDEX IF NOT EXISTS idx_job_event  ON job_runs(trigger_event_id)",
            "CREATE INDEX IF NOT EXISTS idx_job_stage  ON job_runs(stage)",
            "CREATE INDEX IF NOT EXISTS idx_kg_status ON kg_relations(status)",
            "CREATE INDEX IF NOT EXISTS idx_kg_candidate_status ON kg_edge_candidates(status)",
            "CREATE INDEX IF NOT EXISTS idx_source_health_status ON source_health_daily(eval_date, healthy)",
            "CREATE INDEX IF NOT EXISTS idx_source_eval_date ON source_eval_daily(eval_date)",
            "CREATE INDEX IF NOT EXISTS idx_event_eval_date ON event_eval_runs(eval_date)",
            "CREATE INDEX IF NOT EXISTS idx_model_eval_date ON model_eval_runs(eval_date)",
            "CREATE INDEX IF NOT EXISTS idx_quality_gate_status ON daily_quality_gate(status)",
        ]:
            try:
                self._conn.execute(ddl)
            except Exception:
                pass
        self._conn.commit()

    def _ensure_instruments_columns(self) -> None:
        cur = self._conn.cursor()
        for ddl in [
            "ALTER TABLE instruments ADD COLUMN total_shares INTEGER DEFAULT 0",
            "ALTER TABLE instruments ADD COLUMN float_shares INTEGER DEFAULT 0",
            "ALTER TABLE instruments ADD COLUMN market_name TEXT NOT NULL DEFAULT ''",
        ]:
            try:
                cur.execute(ddl)
            except sqlite3.OperationalError:
                pass
        self._conn.commit()

    def _ensure_model_registry_columns(self) -> None:
        cur = self._conn.cursor()
        for ddl in [
            "ALTER TABLE model_registry ADD COLUMN target_name TEXT",
            "ALTER TABLE model_registry ADD COLUMN backend TEXT DEFAULT 'lgbm'",
            "ALTER TABLE model_registry ADD COLUMN artifact_format TEXT DEFAULT 'joblib'",
            "ALTER TABLE model_registry ADD COLUMN feature_set TEXT",
            "ALTER TABLE model_registry ADD COLUMN dataset_snapshot_id INTEGER",
            "ALTER TABLE model_registry ADD COLUMN promotion_state TEXT NOT NULL DEFAULT 'active'",
        ]:
            try:
                cur.execute(ddl)
            except sqlite3.OperationalError:
                pass

        cur.execute(
            "UPDATE model_registry SET target_name=COALESCE(target_name, model_name) "
            "WHERE target_name IS NULL OR target_name=''"
        )
        cur.execute(
            "UPDATE model_registry SET backend="
            "CASE "
            " WHEN backend IS NOT NULL AND backend != '' THEN backend "
            " WHEN lower(model_type) LIKE '%onnx%' OR lower(file_path) LIKE '%.onnx' THEN 'tabular_nn' "
            " ELSE 'lgbm' END"
        )
        cur.execute(
            "UPDATE model_registry SET artifact_format="
            "CASE "
            " WHEN artifact_format IS NOT NULL AND artifact_format != '' THEN artifact_format "
            " WHEN lower(file_path) LIKE '%.onnx' THEN 'onnx' "
            " ELSE 'joblib' END"
        )
        cur.execute(
            "UPDATE model_registry SET promotion_state="
            "CASE "
            " WHEN promotion_state IS NOT NULL AND promotion_state != '' THEN promotion_state "
            " WHEN COALESCE(is_active, 0) = 1 THEN 'active' "
            " ELSE 'candidate' END"
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_model_target ON model_registry(target_name)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_model_state ON model_registry(promotion_state)")
        self._conn.commit()

    def _rebuild_classification_view(self) -> None:
        cur = self._conn.cursor()
        cur.execute(f"""
            CREATE VIEW IF NOT EXISTS instrument_classification_v AS
            SELECT
                i.symbol, i.name, i.market, i.market_name, i.board,
                CASE i.board
                    WHEN 0 THEN '主板' WHEN 1 THEN 'ST' WHEN 2 THEN '科创板'
                    WHEN 3 THEN '创业板' WHEN 4 THEN '北交所'
                    WHEN 5 THEN '主板新股首日' WHEN 6 THEN '科创创业板新股首日'
                    ELSE '未知'
                END AS board_name,
                i.status,
                CASE i.status
                    WHEN 0 THEN '正常' WHEN 1 THEN '停牌'
                    WHEN 2 THEN 'ST' WHEN 3 THEN '*ST' WHEN 4 THEN '退市整理'
                    ELSE '未知'
                END AS status_name,
                CASE
                    WHEN i.status IN (2, 3) THEN 1
                    WHEN i.board = 1 THEN 1
                    WHEN upper(replace(i.name, ' ', '')) LIKE 'ST%'
                      OR upper(replace(i.name, ' ', '')) LIKE '*ST%'
                      OR upper(replace(i.name, ' ', '')) LIKE 'S*ST%'
                      OR upper(replace(i.name, ' ', '')) LIKE 'SST%'
                    THEN 1
                    ELSE 0
                END AS is_st,
                m.sector_code, m.sector_name,
                COALESCE(m.industry_code, i.industry, {_INDUSTRY_UNKNOWN}) AS industry_code,
                {_industry_case_expr(f"COALESCE(m.industry_code, i.industry, {_INDUSTRY_UNKNOWN})")} AS industry_name,
                i.list_date, i.delist_date
            FROM instruments i
            LEFT JOIN sector_members m ON i.symbol = m.symbol
        """)
        self._conn.commit()

    def _seed_defaults(self) -> None:
        cur = self._conn.cursor()
        cur.execute("DELETE FROM settings WHERE key IN ('scheduler.brief_time')")
        for key, value, vtype, category, label in _DEFAULT_SETTINGS:
            cur.execute(
                "INSERT OR IGNORE INTO settings (key, value, value_type, category, label) "
                "VALUES (?, ?, ?, ?, ?)",
                (key, value, vtype, category, label),
            )
        for key, rel_path, category, label in _CONFIG_JSON_SEEDS:
            payload = _read_repo_json(rel_path)
            if payload is None:
                continue
            cur.execute(
                "INSERT OR IGNORE INTO settings (key, value, value_type, category, label) "
                "VALUES (?, ?, 'json', ?, ?)",
                (key, json.dumps(payload, ensure_ascii=False), category, label),
            )
        for key, rel_path, category, label in _CONFIG_TEXT_SEEDS:
            payload = _read_repo_text(rel_path)
            if payload is None:
                continue
            cur.execute(
                "INSERT OR IGNORE INTO settings (key, value, value_type, category, label) "
                "VALUES (?, ?, 'string', ?, ?)",
                (key, payload, category, label),
            )
        self._conn.commit()

    # ── Settings CRUD ──────────────────────────────────────────────────────────

    def get(self, key: str, default: Any = None) -> Any:
        row = self._conn.execute(
            "SELECT value, value_type FROM settings WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return default
        return self._cast(row["value"], row["value_type"])

    def get_json(self, key: str, default: Any = None) -> Any:
        value = self.get(key, default)
        if isinstance(value, (dict, list)):
            return value
        if isinstance(value, str):
            return _json_loads_safe(value, default)
        return default if value is None else value

    def set(self, key: str, value: Any, *, value_type: str | None = None,
            category: str = "general", label: str | None = None) -> None:
        if value_type is None:
            if isinstance(value, bool):
                value_type = "bool"
            elif isinstance(value, int) and not isinstance(value, bool):
                value_type = "int"
            elif isinstance(value, float):
                value_type = "float"
            elif isinstance(value, (dict, list)):
                value_type = "json"
            else:
                value_type = "string"
        if value_type == "json":
            stored = json.dumps(value, ensure_ascii=False)
        elif value_type == "bool":
            stored = "1" if bool(value) else "0"
        else:
            stored = str(value)
        self._conn.execute(
            "INSERT INTO settings (key, value, value_type, category, label, updated_at) "
            "VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(key) DO UPDATE SET "
            "value = excluded.value, "
            "value_type = excluded.value_type, "
            "category = excluded.category, "
            "label = COALESCE(excluded.label, settings.label), "
            "updated_at = CURRENT_TIMESTAMP",
            (key, stored, value_type, category, label),
        )
        self._conn.commit()

    def get_category(self, category: str) -> dict[str, Any]:
        rows = self._conn.execute(
            "SELECT key, value, value_type, label FROM settings WHERE category = ? ORDER BY key",
            (category,),
        ).fetchall()
        return {
            row["key"]: {
                "value": self._cast(row["value"], row["value_type"]),
                "label": row["label"],
                "value_type": row["value_type"],
            }
            for row in rows
        }

    def all_categories(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT category FROM settings ORDER BY category"
        ).fetchall()
        return [r["category"] for r in rows]

    # ── Instrument lookup ──────────────────────────────────────────────────────

    def instrument_lookup(self, symbol: str) -> dict | None:
        row = self._conn.execute(
            "SELECT name, market_name FROM instruments WHERE symbol = ?", (symbol,)
        ).fetchone()
        if row is None:
            return None
        return {"name": row["name"] or "", "market_name": row["market_name"] or ""}

    # ── Watchlist ──────────────────────────────────────────────────────────────

    def watchlist_add(self, symbol: str, note: str = "") -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO watchlist (symbol, added_at, note, active) "
            "VALUES (?, date('now'), ?, 1)",
            (symbol, note),
        )
        self._conn.commit()

    def watchlist_remove(self, symbol: str) -> None:
        self._conn.execute(
            "UPDATE watchlist SET active = 0 WHERE symbol = ?", (symbol,)
        )
        self._conn.commit()

    def watchlist_get(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT symbol FROM watchlist WHERE active = 1 ORDER BY added_at"
        ).fetchall()
        return [r["symbol"] for r in rows]

    def watchlist_get_with_names(self) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT w.symbol,
                   COALESCE(i.name, '')        AS name,
                   COALESCE(i.market_name, '') AS market_name
            FROM watchlist w
            LEFT JOIN instruments i ON w.symbol = i.symbol
            WHERE w.active = 1
            ORDER BY w.added_at
            """
        ).fetchall()
        return [{"symbol": r["symbol"], "name": r["name"], "market_name": r["market_name"]}
                for r in rows]

    # ── Job run history ────────────────────────────────────────────────────────

    def job_run_start(self, job_name: str, stage: str | None = None,
                      trigger_event_id: int | None = None) -> int:
        with self._conn_lock:
            cur = self._conn.execute(
                "INSERT INTO job_runs (job_name, stage, trigger_event_id, status, started_at) "
                "VALUES (?, ?, ?, 'running', datetime('now', 'localtime'))",
                (job_name, stage, trigger_event_id),
            )
            self._conn.commit()
            return cur.lastrowid  # type: ignore[return-value]

    def job_run_finish(self, run_id: int, status: str,
                       result_summary: str | None = None,
                       symbols_processed: int | None = None,
                       elapsed_ms: int | None = None,
                       # Legacy params
                       message: str | None = None) -> None:
        summary = result_summary or message
        with self._conn_lock:
            self._conn.execute(
                """
                UPDATE job_runs
                SET status = ?, result_summary = ?, message = ?,
                    symbols_processed = ?, elapsed_ms = ?,
                    completed_at = datetime('now', 'localtime'),
                    finished_at = datetime('now', 'localtime'),
                    duration_s = CAST(COALESCE(?, 0) / 1000.0 AS REAL)
                WHERE id = ?
                """,
                (status, summary, summary, symbols_processed, elapsed_ms, elapsed_ms, run_id),
            )
            self._conn.commit()

    def job_runs_mark_stale(self, older_than_hours: float = 2.0, note: str | None = None) -> int:
        summary = note or f"marked stale after {older_than_hours:.1f}h without completion"
        with self._conn_lock:
            cur = self._conn.execute(
                """
                UPDATE job_runs
                SET status = 'error',
                    result_summary = CASE
                        WHEN COALESCE(result_summary, '') = '' THEN ?
                        ELSE result_summary
                    END,
                    message = CASE
                        WHEN COALESCE(message, '') = '' THEN ?
                        ELSE message
                    END,
                    completed_at = datetime('now', 'localtime'),
                    finished_at = datetime('now', 'localtime')
                WHERE status = 'running'
                  AND started_at < datetime('now', 'localtime', ?)
                """,
                (summary, summary, f"-{older_than_hours} hours"),
            )
            self._conn.commit()
            return cur.rowcount

    def job_runs_mark_stale_by_policy(self) -> int:
        policies = [
            ("realtime_quote_sync", 0.25),
            ("realtime_compute", 0.25),
            ("planned_event_sync", 0.5),
            ("planned_event_realize", 0.5),
            ("evaluate_gate", 0.5),
            ("evaluate_source", 2.0),
            ("evaluate_daily", 2.0),
            ("window_score", 1.0),
            ("fund_flow_update", 1.0),
            ("northbound", 1.0),
            ("event_pipeline", 2.0),
            ("sentiment_pipeline", 4.0),
        ]
        total = 0
        with self._conn_lock:
            for job_name, older_than_hours in policies:
                cur = self._conn.execute(
                    """
                    UPDATE job_runs
                    SET status = 'error',
                        result_summary = CASE
                            WHEN COALESCE(result_summary, '') = '' THEN ?
                            ELSE result_summary
                        END,
                        message = CASE
                            WHEN COALESCE(message, '') = '' THEN ?
                            ELSE message
                        END,
                        completed_at = datetime('now', 'localtime'),
                        finished_at = datetime('now', 'localtime')
                    WHERE status = 'running'
                      AND job_name = ?
                      AND started_at < datetime('now', 'localtime', ?)
                    """,
                    (
                        f"marked stale by policy after {older_than_hours:.2f}h",
                        f"marked stale by policy after {older_than_hours:.2f}h",
                        job_name,
                        f"-{older_than_hours} hours",
                    ),
                )
                total += int(cur.rowcount or 0)
            self._conn.commit()
        return total

    def job_runs_recent(self, limit: int = 50, stage: str | None = None) -> list[dict]:
        with self._conn_lock:
            if stage:
                rows = self._conn.execute(
                    """
                    SELECT id, job_name, stage, trigger_event_id, status,
                           result_summary, symbols_processed, started_at,
                           completed_at, elapsed_ms
                    FROM job_runs WHERE stage = ? ORDER BY id DESC LIMIT ?
                    """,
                    (stage, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    """
                    SELECT id, job_name, stage, trigger_event_id, status,
                           result_summary, symbols_processed, started_at,
                           completed_at, elapsed_ms
                    FROM job_runs ORDER BY id DESC LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return [dict(r) for r in rows]

    # Legacy no-op methods (job_schedule removed)
    def job_schedule_upsert(self, *args, **kwargs) -> None:
        pass

    def job_schedule_update_next(self, *args, **kwargs) -> None:
        pass

    def job_schedule_update_last(self, *args, **kwargs) -> None:
        pass

    def job_schedule_all(self) -> list[dict]:
        return []

    # ── Market Events (was events) ─────────────────────────────────────────────

    # ── Instruments ────────────────────────────────────────────────────────────

    def upsert_instrument(self, symbol: str, name: str,
                          market: int | None = None,
                          industry_idx: int = _INDUSTRY_UNKNOWN) -> None:
        code = symbol.split(".")[0]
        if market is None:
            market = _infer_market(code)
        mname = _market_name(market)
        board = _infer_board(symbol, name)
        status = _infer_status(name)
        self._conn.execute(
            """
            INSERT INTO instruments (symbol, name, market, board, industry,
                                     list_date, delist_date, status,
                                     total_shares, float_shares, market_name)
            VALUES (?, ?, ?, ?, ?, NULL, NULL, ?, 0, 0, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                name=excluded.name, market=excluded.market, board=excluded.board,
                industry=excluded.industry, status=excluded.status,
                market_name=excluded.market_name
            """,
            (symbol, name, market, board, industry_idx, status, mname),
        )
        self._conn.commit()

    def replace_sector_members(self, rows: list[tuple[str, str, str, int]]) -> None:
        cur = self._conn.cursor()
        cur.execute("DELETE FROM sector_members")
        cur.executemany(
            """
            INSERT INTO sector_members
                (symbol, sector_code, sector_name, industry_code, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            rows,
        )
        self._conn.commit()

    def get_all_symbols(self) -> list[str]:
        cur = self._conn.execute("SELECT symbol FROM instruments ORDER BY symbol")
        return [row[0] for row in cur.fetchall()]

    def get_active_symbols(self, *, include_suspended: bool = False) -> list[str]:
        statuses = [_STATUS_NORMAL]
        if include_suspended:
            statuses.append(_STATUS_SUSPENDED)
        placeholders = ", ".join(["?"] * len(statuses))
        cur = self._conn.execute(
            f"SELECT symbol FROM instruments WHERE status IN ({placeholders}) ORDER BY symbol",
            statuses,
        )
        return [row[0] for row in cur.fetchall()]

    def get_latest_open_trade_date(self, *, on_or_before: str | None = None) -> str | None:
        boundary = _normalize_date_text(on_or_before) or date.today().isoformat()
        row = self._conn.execute(
            """
            SELECT MAX(trade_date)
            FROM trading_calendar
            WHERE trade_date <= ?
              AND COALESCE(is_open, 1) = 1
            """,
            (boundary,),
        ).fetchone()
        value = row[0] if row else None
        return _normalize_date_text(value)

    def get_latest_market_asof(self, *, on_or_before: str | None = None) -> str | None:
        boundary = _normalize_date_text(on_or_before) or date.today().isoformat()
        candidates = [
            self.get_latest_open_trade_date(on_or_before=boundary),
            _normalize_date_text(
                self._conn.execute(
                    "SELECT MAX(date) FROM signals WHERE date <= ?",
                    (boundary,),
                ).fetchone()[0]
            ),
            _normalize_date_text(
                self._conn.execute(
                    "SELECT MAX(eval_date) FROM daily_quality_gate WHERE eval_date <= ?",
                    (boundary,),
                ).fetchone()[0]
            ),
            _normalize_date_text(
                self._conn.execute(
                    "SELECT MAX(eval_date) FROM QualityReport WHERE eval_date <= ?",
                    (boundary,),
                ).fetchone()[0]
            ),
            _normalize_date_text(
                self._conn.execute(
                    "SELECT MAX(as_of_date) FROM Recommendation WHERE as_of_date <= ?",
                    (boundary,),
                ).fetchone()[0]
            ),
            _normalize_date_text(
                self._conn.execute(
                    "SELECT MAX(as_of_date) FROM BeliefState WHERE as_of_date <= ?",
                    (boundary,),
                ).fetchone()[0]
            ),
        ]
        for value in candidates:
            if value:
                return value
        return boundary

    def get_symbols_by_sector(self, sector: Any) -> list[str]:
        rows = self._conn.execute(
            "SELECT symbol FROM sector_members WHERE industry_code = ?",
            (int(sector),),
        ).fetchall()
        return [r[0] for r in rows]

    # ── Sync State (replaces watermarks + downloads) ───────────────────────────

    def sync_state_get(self, source: str, dataset: str,
                       symbol: str = "") -> Optional[date]:
        """Get last synced date for (source, dataset, symbol)."""
        row = self._conn.execute(
            "SELECT last_date FROM sync_state WHERE source=? AND dataset=? AND symbol=?",
            (source, dataset, symbol),
        ).fetchone()
        if row is None or row[0] is None:
            return None
        try:
            return date.fromisoformat(row[0][:10])
        except (ValueError, TypeError):
            return None

    def sync_state_set(self, source: str, dataset: str, symbol: str = "",
                       last_date: date | str | None = None,
                       row_count: int | None = None,
                       cursor: dict | None = None) -> None:
        """Upsert sync state record."""
        last_date_str = (
            last_date.isoformat() if isinstance(last_date, date)
            else last_date
        )
        cursor_str = json.dumps(cursor) if cursor is not None else "{}"
        self._conn.execute(
            """
            INSERT INTO sync_state (source, dataset, symbol, last_date, row_count, cursor, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(source, dataset, symbol) DO UPDATE SET
                last_date = COALESCE(excluded.last_date, last_date),
                row_count = COALESCE(excluded.row_count, row_count),
                cursor = excluded.cursor,
                updated_at = CURRENT_TIMESTAMP
            """,
            (source, dataset, symbol, last_date_str, row_count, cursor_str),
        )
        self._conn.commit()

    def sync_state_get_cursor(self, source: str, dataset: str,
                              symbol: str = "") -> dict:
        """Get the cursor JSON dict for (source, dataset, symbol). Returns {} if none."""
        row = self._conn.execute(
            "SELECT cursor FROM sync_state WHERE source=? AND dataset=? AND symbol=?",
            (source, dataset, symbol),
        ).fetchone()
        if row is None or not row[0]:
            return {}
        try:
            return json.loads(row[0])
        except (ValueError, TypeError):
            return {}

    # Backward compat: watermark methods
    def get_watermark(self, source: str, dataset: str, symbol: str) -> Optional[date]:
        return self.sync_state_get(source, dataset, symbol)

    def set_watermark(self, source: str, dataset: str, symbol: str,
                      last_date: date) -> None:
        self.sync_state_set(source, dataset, symbol, last_date=last_date)

    # Backward compat: downloads methods
    def record_download(self, symbol: str, start: date, end: date, row_count: int) -> None:
        self.sync_state_set("tushare_kline", "daily", symbol,
                            last_date=end, row_count=row_count)

    def last_download_date(self, symbol: str) -> Optional[date]:
        return self.sync_state_get("tushare_kline", "daily", symbol)

    # ── Trading Calendar / Agenda ────────────────────────────────────────────

    def trading_calendar_upsert_batch(self, rows: list[dict]) -> None:
        if not rows:
            return
        payload: list[dict[str, Any]] = []
        for row in rows:
            trade_date = _normalize_date_text(row.get("trade_date"))
            if not trade_date:
                continue
            payload.append({
                "exchange": str(row.get("exchange") or "SSE").upper(),
                "trade_date": trade_date,
                "is_open": 1 if int(row.get("is_open") or 0) else 0,
                "pretrade_date": _normalize_date_text(row.get("pretrade_date")),
                "session_am_open": row.get("session_am_open") or "09:30:00",
                "session_am_close": row.get("session_am_close") or "11:30:00",
                "session_pm_open": row.get("session_pm_open") or "13:00:00",
                "session_pm_close": row.get("session_pm_close") or "15:00:00",
                "source": str(row.get("source") or "tushare"),
            })
        if not payload:
            return
        with self._conn_lock:
            self._conn.executemany(
                """
                INSERT INTO trading_calendar
                    (exchange, trade_date, is_open, pretrade_date,
                     session_am_open, session_am_close, session_pm_open, session_pm_close,
                     source, updated_at)
                VALUES
                    (:exchange, :trade_date, :is_open, :pretrade_date,
                     :session_am_open, :session_am_close, :session_pm_open, :session_pm_close,
                     :source, CURRENT_TIMESTAMP)
                ON CONFLICT(exchange, trade_date) DO UPDATE SET
                    is_open=excluded.is_open,
                    pretrade_date=excluded.pretrade_date,
                    session_am_open=excluded.session_am_open,
                    session_am_close=excluded.session_am_close,
                    session_pm_open=excluded.session_pm_open,
                    session_pm_close=excluded.session_pm_close,
                    source=excluded.source,
                    updated_at=CURRENT_TIMESTAMP
                """,
                payload,
            )
            self._conn.commit()

    def trading_calendar_get(self, trade_date: str | date | datetime, exchange: str = "SSE") -> dict | None:
        trade_date_str = _normalize_date_text(trade_date)
        if not trade_date_str:
            return None
        with self._conn_lock:
            row = self._conn.execute(
                """
                SELECT exchange, trade_date, is_open, pretrade_date,
                       session_am_open, session_am_close, session_pm_open, session_pm_close,
                       source, updated_at
                FROM trading_calendar
                WHERE exchange=? AND trade_date=?
                """,
                (exchange.upper(), trade_date_str),
            ).fetchone()
        return dict(row) if row is not None else None

    def trading_calendar_is_open(self, trade_date: str | date | datetime, exchange: str = "SSE") -> bool | None:
        row = self.trading_calendar_get(trade_date, exchange=exchange)
        if row is None:
            return None
        return bool(int(row.get("is_open") or 0))

    def trading_calendar_prev_trading_day(
        self,
        trade_date: str | date | datetime,
        exchange: str = "SSE",
    ) -> str | None:
        trade_date_str = _normalize_date_text(trade_date)
        if not trade_date_str:
            return None
        row = self.trading_calendar_get(trade_date_str, exchange=exchange)
        if row and row.get("pretrade_date"):
            return str(row["pretrade_date"])
        with self._conn_lock:
            prev = self._conn.execute(
                """
                SELECT trade_date
                FROM trading_calendar
                WHERE exchange=? AND is_open=1 AND trade_date < ?
                ORDER BY trade_date DESC
                LIMIT 1
                """,
                (exchange.upper(), trade_date_str),
            ).fetchone()
        return str(prev["trade_date"]) if prev is not None else None

    def trading_calendar_next_trading_day(
        self,
        trade_date: str | date | datetime,
        exchange: str = "SSE",
    ) -> str | None:
        trade_date_str = _normalize_date_text(trade_date)
        if not trade_date_str:
            return None
        with self._conn_lock:
            nxt = self._conn.execute(
                """
                SELECT trade_date
                FROM trading_calendar
                WHERE exchange=? AND is_open=1 AND trade_date > ?
                ORDER BY trade_date ASC
                LIMIT 1
                """,
                (exchange.upper(), trade_date_str),
            ).fetchone()
        return str(nxt["trade_date"]) if nxt is not None else None

    def planned_events_upsert_batch(self, rows: list[dict]) -> None:
        if not rows:
            return
        payload: list[dict[str, Any]] = []
        for row in rows:
            planned_event_id = str(row.get("planned_event_id") or "").strip()
            scheduled_at = str(row.get("scheduled_at") or "").strip()
            event_date = _normalize_date_text(row.get("event_date"))
            if not planned_event_id or not scheduled_at or not event_date:
                continue
            payload.append({
                "planned_event_id": planned_event_id,
                "source": str(row.get("source") or "manual"),
                "vendor_event_id": str(row.get("vendor_event_id") or ""),
                "event_type": str(row.get("event_type") or "calendar_event"),
                "entity_id": str(row.get("entity_id") or ""),
                "event_date": event_date,
                "event_time": str(row.get("event_time") or ""),
                "scheduled_at": scheduled_at,
                "timezone": str(row.get("timezone") or "Asia/Shanghai"),
                "title": str(row.get("title") or planned_event_id),
                "country": str(row.get("country") or ""),
                "currency": str(row.get("currency") or ""),
                "importance": str(row.get("importance") or "medium"),
                "status": str(row.get("status") or "scheduled"),
                "expected_value": row.get("expected_value"),
                "previous_value": row.get("previous_value"),
                "actual_value": row.get("actual_value"),
                "realized_event_id": row.get("realized_event_id"),
                "payload_json": row.get("payload_json") or "{}",
            })
        if not payload:
            return
        with self._conn_lock:
            self._conn.executemany(
                """
                INSERT INTO planned_events
                    (planned_event_id, source, vendor_event_id, event_type, entity_id,
                     event_date, event_time, scheduled_at, timezone, title,
                     country, currency, importance, status,
                     expected_value, previous_value, actual_value, realized_event_id,
                     payload_json, created_at, updated_at)
                VALUES
                    (:planned_event_id, :source, :vendor_event_id, :event_type, :entity_id,
                     :event_date, :event_time, :scheduled_at, :timezone, :title,
                     :country, :currency, :importance, :status,
                     :expected_value, :previous_value, :actual_value, :realized_event_id,
                     :payload_json, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT(planned_event_id) DO UPDATE SET
                    source=excluded.source,
                    vendor_event_id=excluded.vendor_event_id,
                    event_type=excluded.event_type,
                    entity_id=excluded.entity_id,
                    event_date=excluded.event_date,
                    event_time=excluded.event_time,
                    scheduled_at=excluded.scheduled_at,
                    timezone=excluded.timezone,
                    title=excluded.title,
                    country=excluded.country,
                    currency=excluded.currency,
                    importance=excluded.importance,
                    status=excluded.status,
                    expected_value=excluded.expected_value,
                    previous_value=excluded.previous_value,
                    actual_value=excluded.actual_value,
                    realized_event_id=excluded.realized_event_id,
                    payload_json=excluded.payload_json,
                    updated_at=CURRENT_TIMESTAMP
                """,
                payload,
            )
            self._conn.commit()

    def planned_events_list(
        self,
        *,
        start_date: str | date | datetime | None = None,
        end_date: str | date | datetime | None = None,
        status: str | None = None,
        event_type: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        clauses: list[str] = []
        params: list[Any] = []
        start_date_str = _normalize_date_text(start_date)
        end_date_str = _normalize_date_text(end_date)
        if start_date_str:
            clauses.append("event_date >= ?")
            params.append(start_date_str)
        if end_date_str:
            clauses.append("event_date <= ?")
            params.append(end_date_str)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if event_type:
            clauses.append("event_type = ?")
            params.append(event_type)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._conn_lock:
            rows = self._conn.execute(
                """
                SELECT *
                FROM planned_events
                """ + where + """
                ORDER BY scheduled_at ASC, planned_event_id ASC
                LIMIT ?
                """,
                [*params, max(1, int(limit))],
            ).fetchall()
        return [dict(r) for r in rows]

    def planned_event_get(self, planned_event_id: str) -> dict | None:
        with self._conn_lock:
            row = self._conn.execute(
                "SELECT * FROM planned_events WHERE planned_event_id=?",
                (planned_event_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def planned_events_due(
        self,
        as_of: str | datetime | None = None,
        *,
        statuses: tuple[str, ...] = ("scheduled", "live"),
        limit: int = 100,
    ) -> list[dict]:
        if as_of is None:
            as_of_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        elif isinstance(as_of, datetime):
            as_of_str = as_of.strftime("%Y-%m-%d %H:%M:%S")
        else:
            as_of_str = str(as_of)
        placeholders = ", ".join(["?"] * len(statuses))
        with self._conn_lock:
            rows = self._conn.execute(
                f"""
                SELECT *
                FROM planned_events
                WHERE status IN ({placeholders}) AND scheduled_at <= ?
                ORDER BY scheduled_at ASC, planned_event_id ASC
                LIMIT ?
                """,
                [*statuses, as_of_str, max(1, int(limit))],
            ).fetchall()
        return [dict(r) for r in rows]

    def planned_event_update(self, planned_event_id: str, **fields: Any) -> None:
        if not fields:
            return
        columns = [k for k in fields.keys() if k in {
            "vendor_event_id", "event_type", "entity_id", "event_date", "event_time",
            "scheduled_at", "timezone", "title", "country", "currency", "importance",
            "status", "expected_value", "previous_value", "actual_value", "realized_event_id",
            "payload_json",
        }]
        if not columns:
            return
        assigns = ", ".join(f"{col}=?" for col in columns)
        values = [fields[col] for col in columns]
        with self._conn_lock:
            self._conn.execute(
                f"""
                UPDATE planned_events
                SET {assigns}, updated_at=CURRENT_TIMESTAMP
                WHERE planned_event_id=?
                """,
                [*values, planned_event_id],
            )
            self._conn.commit()

    def agenda_queue_upsert_batch(self, rows: list[dict]) -> None:
        if not rows:
            return
        payload: list[dict[str, Any]] = []
        for row in rows:
            planned_event_id = str(row.get("planned_event_id") or "").strip()
            run_at = str(row.get("run_at") or "").strip()
            phase = str(row.get("phase") or "").strip()
            if not planned_event_id or not run_at or not phase:
                continue
            payload.append({
                "planned_event_id": planned_event_id,
                "phase": phase,
                "run_at": run_at,
                "trigger_topic": str(row.get("trigger_topic") or ""),
                "job_name": str(row.get("job_name") or ""),
                "payload_json": row.get("payload_json") or "{}",
                "priority": int(row.get("priority") or 100),
                "status": str(row.get("status") or "pending"),
                "result_summary": row.get("result_summary"),
            })
        if not payload:
            return
        with self._conn_lock:
            self._conn.executemany(
                """
                INSERT INTO agenda_queue
                    (planned_event_id, phase, run_at, trigger_topic, job_name,
                     payload_json, priority, status, result_summary, created_at, updated_at)
                VALUES
                    (:planned_event_id, :phase, :run_at, :trigger_topic, :job_name,
                     :payload_json, :priority, :status, :result_summary, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT(planned_event_id, phase, run_at, trigger_topic, job_name) DO UPDATE SET
                    payload_json=excluded.payload_json,
                    priority=excluded.priority,
                    status=CASE
                        WHEN agenda_queue.status IN ('done', 'running', 'queued', 'error', 'skipped') THEN agenda_queue.status
                        ELSE excluded.status
                    END,
                    result_summary=CASE
                        WHEN agenda_queue.status IN ('done', 'running', 'queued', 'error', 'skipped') THEN agenda_queue.result_summary
                        ELSE excluded.result_summary
                    END,
                    updated_at=CURRENT_TIMESTAMP
                """,
                payload,
            )
            self._conn.commit()

    def agenda_queue_due(self, as_of: str | datetime | None = None, limit: int = 100) -> list[dict]:
        if as_of is None:
            as_of_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        elif isinstance(as_of, datetime):
            as_of_str = as_of.strftime("%Y-%m-%d %H:%M:%S")
        else:
            as_of_str = str(as_of)
        with self._conn_lock:
            rows = self._conn.execute(
                """
                SELECT aq.*, pe.title, pe.event_type, pe.scheduled_at
                FROM agenda_queue aq
                LEFT JOIN planned_events pe ON pe.planned_event_id = aq.planned_event_id
                WHERE aq.status='pending' AND aq.run_at <= ?
                ORDER BY aq.priority ASC, aq.run_at ASC, aq.agenda_id ASC
                LIMIT ?
                """,
                (as_of_str, max(1, int(limit))),
            ).fetchall()
        return [dict(r) for r in rows]

    def agenda_queue_claim_due(
        self,
        as_of: str | datetime | None = None,
        limit: int = 20,
        *,
        job_limits: dict[str, int] | None = None,
        oversample_factor: int = 5,
    ) -> list[dict]:
        if as_of is None:
            as_of_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        elif isinstance(as_of, datetime):
            as_of_str = as_of.strftime("%Y-%m-%d %H:%M:%S")
        else:
            as_of_str = str(as_of)
        query_limit = max(1, int(limit)) * max(1, int(oversample_factor))
        with self._conn_lock:
            rows = self._conn.execute(
                """
                SELECT aq.*, pe.title, pe.event_type, pe.scheduled_at, pe.entity_id
                FROM agenda_queue aq
                LEFT JOIN planned_events pe ON pe.planned_event_id = aq.planned_event_id
                WHERE aq.status='pending' AND aq.run_at <= ?
                ORDER BY aq.priority ASC, aq.run_at ASC, aq.agenda_id ASC
                LIMIT ?
                """,
                (as_of_str, query_limit),
            ).fetchall()
            if not rows:
                return []
            selected: list[dict] = []
            counts: dict[str, int] = {}
            normalized_limits = {
                str(name or "").strip(): max(0, int(value))
                for name, value in (job_limits or {}).items()
            }
            for row in rows:
                job_name = str(row["job_name"] or row["trigger_topic"] or "").strip()
                cap = normalized_limits.get(job_name)
                if cap is not None and counts.get(job_name, 0) >= cap:
                    continue
                selected.append(dict(row))
                counts[job_name] = counts.get(job_name, 0) + 1
                if len(selected) >= max(1, int(limit)):
                    break
            if not selected:
                return []
            ids = [int(row["agenda_id"]) for row in selected]
            self._conn.executemany(
                """
                UPDATE agenda_queue
                SET status='queued',
                    updated_at=CURRENT_TIMESTAMP
                WHERE agenda_id=?
                """,
                [(agenda_id,) for agenda_id in ids],
            )
            self._conn.commit()
        return selected

    def agenda_queue_recent(
        self,
        limit: int = 100,
        status: str | None = None,
        event_date: str | date | datetime | None = None,
    ) -> list[dict]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("aq.status = ?")
            params.append(status)
        event_date_str = _normalize_date_text(event_date)
        if event_date_str:
            clauses.append("pe.event_date = ?")
            params.append(event_date_str)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._conn_lock:
            rows = self._conn.execute(
                """
                SELECT aq.*, pe.title, pe.event_type, pe.event_date
                FROM agenda_queue aq
                LEFT JOIN planned_events pe ON pe.planned_event_id = aq.planned_event_id
                """ + where + """
                ORDER BY aq.run_at DESC, aq.agenda_id DESC
                LIMIT ?
                """,
                [*params, max(1, int(limit))],
            ).fetchall()
        return [dict(r) for r in rows]

    def agenda_queue_expire_stale(
        self,
        *,
        as_of: str | datetime | None = None,
        phases: tuple[str, ...] = ("pre", "live"),
        grace_minutes: int = 120,
    ) -> int:
        if as_of is None:
            as_of_dt = datetime.now()
        elif isinstance(as_of, datetime):
            as_of_dt = as_of
        else:
            as_of_dt = datetime.fromisoformat(str(as_of))
        cutoff = (as_of_dt - timedelta(minutes=max(1, int(grace_minutes)))).strftime("%Y-%m-%d %H:%M:%S")
        placeholders = ",".join("?" for _ in phases)
        params: list[Any] = [
            "expired stale agenda",
            cutoff,
            *[str(phase) for phase in phases],
        ]
        with self._conn_lock:
            cur = self._conn.execute(
                f"""
                UPDATE agenda_queue
                SET status='skipped',
                    result_summary=COALESCE(result_summary, ?),
                    updated_at=CURRENT_TIMESTAMP
                WHERE status IN ('pending', 'queued', 'running')
                  AND run_at < ?
                  AND phase IN ({placeholders})
                """,
                params,
            )
            self._conn.commit()
            return int(cur.rowcount or 0)

    def agenda_queue_update_status(
        self,
        agenda_id: int,
        status: str,
        *,
        result_summary: str | None = None,
    ) -> None:
        executed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S") if status in {"done", "skipped", "error", "running"} else None
        with self._conn_lock:
            self._conn.execute(
                """
                UPDATE agenda_queue
                SET status=?,
                    result_summary=COALESCE(?, result_summary),
                    executed_at=COALESCE(?, executed_at),
                    updated_at=CURRENT_TIMESTAMP
                WHERE agenda_id=?
                """,
                (status, result_summary, executed_at, agenda_id),
            )
            self._conn.commit()

    def backup_snapshot_upsert(self, row: dict[str, Any]) -> None:
        payload = {
            "snapshot_id": str(row.get("snapshot_id") or "").strip(),
            "label": row.get("label"),
            "driver": str(row.get("driver") or "local"),
            "scope": str(row.get("scope") or "data_root"),
            "archive_path": row.get("archive_path"),
            "manifest_path": row.get("manifest_path"),
            "remote_archive_path": row.get("remote_archive_path"),
            "remote_manifest_path": row.get("remote_manifest_path"),
            "status": str(row.get("status") or "created"),
            "size_bytes": int(row.get("size_bytes") or 0),
            "file_count": int(row.get("file_count") or 0),
            "sha256": row.get("sha256"),
            "restored_at": row.get("restored_at"),
        }
        if not payload["snapshot_id"]:
            return
        with self._conn_lock:
            self._conn.execute(
                """
                INSERT INTO backup_snapshots
                    (snapshot_id, label, driver, scope, archive_path, manifest_path,
                     remote_archive_path, remote_manifest_path, status,
                     size_bytes, file_count, sha256, restored_at, created_at, updated_at)
                VALUES
                    (:snapshot_id, :label, :driver, :scope, :archive_path, :manifest_path,
                     :remote_archive_path, :remote_manifest_path, :status,
                     :size_bytes, :file_count, :sha256, :restored_at, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT(snapshot_id) DO UPDATE SET
                    label=excluded.label,
                    driver=excluded.driver,
                    scope=excluded.scope,
                    archive_path=excluded.archive_path,
                    manifest_path=excluded.manifest_path,
                    remote_archive_path=excluded.remote_archive_path,
                    remote_manifest_path=excluded.remote_manifest_path,
                    status=excluded.status,
                    size_bytes=excluded.size_bytes,
                    file_count=excluded.file_count,
                    sha256=excluded.sha256,
                    restored_at=excluded.restored_at,
                    updated_at=CURRENT_TIMESTAMP
                """,
                payload,
            )
            self._conn.commit()

    def backup_snapshot_get(self, snapshot_id: str) -> dict | None:
        with self._conn_lock:
            row = self._conn.execute(
                "SELECT * FROM backup_snapshots WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def backup_snapshots_recent(self, limit: int = 20, status: str | None = None) -> list[dict]:
        params: list[Any] = []
        where = ""
        if status:
            where = "WHERE status = ?"
            params.append(status)
        with self._conn_lock:
            rows = self._conn.execute(
                f"""
                SELECT *
                FROM backup_snapshots
                {where}
                ORDER BY created_at DESC, snapshot_id DESC
                LIMIT ?
                """,
                [*params, max(1, int(limit))],
            ).fetchall()
        return [dict(row) for row in rows]

    # ── Event Log (was bus_events) ─────────────────────────────────────────────

    def event_log_insert(self, topic: str, payload_json: str,
                         parent_event_id: int | None = None) -> int:
        with self._conn_lock:
            cur = self._conn.execute(
                "INSERT INTO event_log (topic, payload, parent_event_id, status, created_at) "
                "VALUES (?, ?, ?, 'pending', datetime('now', 'localtime'))",
                (topic, payload_json, parent_event_id),
            )
            self._conn.commit()
            return cur.lastrowid  # type: ignore[return-value]

    def event_log_complete(self, id: int, status: str, handler: str,
                           error: str | None = None,
                           elapsed_ms: int | None = None) -> None:
        with self._conn_lock:
            self._conn.execute(
                """
                UPDATE event_log SET status=?, handler=?, error=?,
                    elapsed_ms=?, processed_at=datetime('now', 'localtime') WHERE id=?
                """,
                (status, handler, error, elapsed_ms, id),
            )
            self._conn.commit()

    def event_log_recent(self, limit: int = 50, topic: str | None = None) -> list[dict]:
        with self._conn_lock:
            if topic:
                rows = self._conn.execute(
                    "SELECT * FROM event_log WHERE topic=? ORDER BY id DESC LIMIT ?",
                    (topic, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM event_log ORDER BY id DESC LIMIT ?", (limit,)
                ).fetchall()
        return [dict(r) for r in rows]

    def event_log_since(self, after_id: int = 0, limit: int = 100, topic: str | None = None) -> list[dict]:
        with self._conn_lock:
            if topic:
                rows = self._conn.execute(
                    """
                    SELECT * FROM event_log
                    WHERE id > ? AND topic = ?
                    ORDER BY id ASC
                    LIMIT ?
                    """,
                    (max(0, int(after_id)), topic, max(1, int(limit))),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    """
                    SELECT * FROM event_log
                    WHERE id > ?
                    ORDER BY id ASC
                    LIMIT ?
                    """,
                    (max(0, int(after_id)), max(1, int(limit))),
                ).fetchall()
        return [dict(r) for r in rows]

    def event_log_mark_stale(self, older_than_hours: float = 1.0, note: str | None = None) -> int:
        summary = note or f"marked stale after {older_than_hours:.1f}h without completion"
        with self._conn_lock:
            cur = self._conn.execute(
                """
                UPDATE event_log
                SET status='error',
                    handler=COALESCE(NULLIF(handler, ''), '<stale_cleanup>'),
                    error=COALESCE(NULLIF(error, ''), ?),
                    processed_at=datetime('now', 'localtime')
                WHERE status='pending'
                  AND created_at < datetime('now', 'localtime', ?)
                """,
                (summary, f"-{older_than_hours} hours"),
            )
            self._conn.commit()
            return int(cur.rowcount or 0)

    def event_log_pending(self, topic: str | None = None, min_id: int | None = None) -> list[dict]:
        with self._conn_lock:
            if topic and min_id is not None:
                rows = self._conn.execute(
                    "SELECT * FROM event_log WHERE status='pending' AND topic=? AND id>=? ORDER BY id",
                    (topic, min_id),
                ).fetchall()
            elif topic:
                rows = self._conn.execute(
                    "SELECT * FROM event_log WHERE status='pending' AND topic=? ORDER BY id",
                    (topic,),
                ).fetchall()
            elif min_id is not None:
                rows = self._conn.execute(
                    "SELECT * FROM event_log WHERE status='pending' AND id>=? ORDER BY id",
                    (min_id,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM event_log WHERE status='pending' ORDER BY id"
                ).fetchall()
        return [dict(r) for r in rows]

    # Backward compat aliases
    def bus_event_insert(self, topic: str, payload_json: str) -> int:
        return self.event_log_insert(topic, payload_json)

    def bus_event_complete(self, id: int, status: str, handler: str,
                           error: str | None = None) -> None:
        self.event_log_complete(id, status, handler, error)

    def bus_events_recent(self, limit: int = 50, topic: str | None = None) -> list[dict]:
        return self.event_log_recent(limit, topic)

    def bus_events_pending(self, topic: str | None = None, min_id: int | None = None) -> list[dict]:
        return self.event_log_pending(topic, min_id=min_id)

    def _event_tree_rows(self, root_event_id: int) -> list[dict]:
        with self._conn_lock:
            rows = self._conn.execute(
                """
                WITH RECURSIVE tree AS (
                    SELECT
                        id, topic, payload, parent_event_id, status, handler, error,
                        created_at, processed_at, elapsed_ms, 0 AS depth
                    FROM event_log
                    WHERE id = ?
                    UNION ALL
                    SELECT
                        e.id, e.topic, e.payload, e.parent_event_id, e.status, e.handler, e.error,
                        e.created_at, e.processed_at, e.elapsed_ms, tree.depth + 1
                    FROM event_log e
                    JOIN tree ON e.parent_event_id = tree.id
                )
                SELECT * FROM tree ORDER BY id
                """,
                (root_event_id,),
            ).fetchall()
        result: list[dict] = []
        for row in rows:
            item = dict(row)
            item["payload_json"] = _json_loads_safe(item.get("payload"), {})
            result.append(item)
        return result

    def _workflow_expected_nodes(self, root_topic: str) -> list[dict]:
        dag_rows = self.pipeline_dag_all(enabled_only=False)
        by_source: dict[str, list[dict]] = {}
        for row in dag_rows:
            by_source.setdefault(str(row.get("source") or ""), []).append(row)
        queue = [str(root_topic or "")]
        seen_topics = set(queue)
        expected: list[dict] = []
        seen_rows: set[int] = set()
        while queue:
            topic = queue.pop(0)
            for row in by_source.get(topic, []):
                row_id = int(row.get("id") or 0)
                if row_id in seen_rows:
                    continue
                seen_rows.add(row_id)
                expected.append(dict(row))
                emits = str(row.get("emits") or "").strip()
                if emits and emits not in seen_topics:
                    seen_topics.add(emits)
                    queue.append(emits)
        return expected

    def event_workflow_detail(self, root_event_id: int) -> dict | None:
        event_rows = self._event_tree_rows(root_event_id)
        if not event_rows:
            return None

        root = event_rows[0]
        event_ids = [int(row["id"]) for row in event_rows]
        placeholders = ", ".join(["?"] * len(event_ids))
        with self._conn_lock:
            job_rows = self._conn.execute(
                f"""
                SELECT id, job_name, stage, trigger_event_id, status,
                       result_summary, symbols_processed, started_at,
                       completed_at, elapsed_ms
                FROM job_runs
                WHERE trigger_event_id IN ({placeholders})
                ORDER BY id
                """,
                event_ids,
            ).fetchall()
        jobs = [dict(row) for row in job_rows]

        event_by_id = {int(row["id"]): row for row in event_rows}
        event_by_topic: dict[str, list[dict]] = {}
        event_by_job: dict[str, list[dict]] = {}
        for row in event_rows:
            event_by_topic.setdefault(str(row.get("topic") or ""), []).append(row)
            payload_json = row.get("payload_json") or {}
            job_name = str(payload_json.get("job_name") or "").strip()
            if job_name:
                event_by_job.setdefault(job_name, []).append(row)
        jobs_by_name: dict[str, list[dict]] = {}
        for row in jobs:
            jobs_by_name.setdefault(str(row.get("job_name") or ""), []).append(row)

        payload = root.get("payload_json") or {}
        expected_nodes = self._workflow_expected_nodes(str(root.get("topic") or ""))
        if not expected_nodes:
            raw_job_plan = payload.get("job_plan")
            synthetic_nodes: list[dict] = []
            if isinstance(raw_job_plan, list):
                for item in raw_job_plan:
                    if not isinstance(item, dict):
                        continue
                    job_name = str(item.get("job_name") or "").strip()
                    if not job_name:
                        continue
                    synthetic_nodes.append({
                        "id": None,
                        "job_name": job_name,
                        "stage": item.get("stage"),
                        "source": root.get("topic"),
                        "emits": None,
                        "description": item.get("description") or payload.get("goal"),
                        "enabled": True,
                    })
            if not synthetic_nodes:
                for job_name in payload.get("job_names") or []:
                    if not str(job_name).strip():
                        continue
                    synthetic_nodes.append({
                        "id": None,
                        "job_name": str(job_name),
                        "stage": None,
                        "source": root.get("topic"),
                        "emits": None,
                        "description": payload.get("goal"),
                        "enabled": True,
                    })
            if not synthetic_nodes and jobs:
                for job in jobs:
                    synthetic_nodes.append({
                        "id": None,
                        "job_name": job.get("job_name"),
                        "stage": job.get("stage"),
                        "source": root.get("topic"),
                        "emits": None,
                        "description": payload.get("goal"),
                        "enabled": True,
                    })
            expected_nodes = synthetic_nodes
        nodes: list[dict] = []
        for row in expected_nodes:
            job_name = str(row.get("job_name") or "")
            source_topic = str(row.get("source") or "")
            emits_topic = str(row.get("emits") or "")
            source_event = (event_by_topic.get(source_topic) or [None])[-1]
            if job_name and event_by_job.get(job_name):
                source_event = (event_by_job.get(job_name) or [None])[-1]
            emitted_event = (event_by_topic.get(emits_topic) or [None])[-1] if emits_topic else None
            job = (jobs_by_name.get(job_name) or [None])[-1]
            status = "pending"
            error = None
            if job:
                status = str(job.get("status") or "pending")
                error = job.get("result_summary") or None
            elif source_event:
                raw_status = str(source_event.get("status") or "pending")
                status = "running" if raw_status in {"pending", "queued"} else raw_status
                error = source_event.get("error") or None
            elif emitted_event:
                status = "ok" if str(emitted_event.get("status") or "") == "ok" else "pending"
            elif str(root.get("status") or "") in {"pending", "running"}:
                status = "queued"
            nodes.append({
                "dag_id": row.get("id"),
                "job_name": job_name,
                "stage": row.get("stage"),
                "source": source_topic,
                "emits": emits_topic,
                "description": row.get("description"),
                "enabled": bool(row.get("enabled")),
                "status": status,
                "error": error,
                "job_run": job,
                "source_event": source_event,
                "emitted_event": emitted_event,
            })

        completed = sum(1 for node in nodes if node["status"] == "ok")
        running = sum(1 for node in nodes if node["status"] in {"running", "queued", "pending"})
        error_count = sum(1 for node in nodes if node["status"] == "error")
        pending = max(0, len(nodes) - completed - running - error_count)

        root_cause = None
        job_errors = [row for row in jobs if str(row.get("status") or "") == "error"]
        if job_errors:
            err = job_errors[0]
            root_cause = {
                "kind": "job",
                "node": err.get("job_name"),
                "message": err.get("result_summary"),
                "trigger_event_id": err.get("trigger_event_id"),
                "run_id": err.get("id"),
            }
        else:
            direct_event_errors = [
                row for row in event_rows
                if str(row.get("status") or "") == "error" and str(row.get("handler") or "") != "<stale_cleanup>"
            ]
            stale_errors = [row for row in event_rows if str(row.get("status") or "") == "error"]
            err = (direct_event_errors or stale_errors or [None])[0]
            if err:
                root_cause = {
                    "kind": "event",
                    "node": err.get("topic"),
                    "message": err.get("error"),
                    "handler": err.get("handler"),
                    "event_id": err.get("id"),
                }

        overall_status = "ok"
        root_status = str(root.get("status") or "")
        if error_count or root_status == "error":
            overall_status = "error"
        elif running or root_status in {"pending", "running"}:
            overall_status = "running"
        elif pending and nodes:
            overall_status = "partial"

        title = (
            payload.get("title")
            or payload.get("name")
            or payload.get("job_name")
            or str(root.get("topic") or "")
        )
        return {
            "root_event_id": int(root.get("id") or 0),
            "topic": root.get("topic"),
            "title": title,
            "status": overall_status,
            "created_at": root.get("created_at"),
            "processed_at": root.get("processed_at"),
            "payload_json": payload,
            "nodes": nodes,
            "events": event_rows,
            "jobs": jobs,
            "progress": {
                "completed": completed,
                "running": running,
                "error": error_count,
                "pending": pending,
                "total": len(nodes),
                "ratio": round((completed / len(nodes)), 4) if nodes else 0.0,
            },
            "root_cause": root_cause,
        }

    def event_workflow_recent(self, limit: int = 20) -> list[dict]:
        with self._conn_lock:
            roots = self._conn.execute(
                """
                SELECT id, topic, payload, parent_event_id, status, handler, error,
                       created_at, processed_at, elapsed_ms
                FROM event_log
                WHERE parent_event_id IS NULL
                   OR topic LIKE 'gate.%'
                   OR topic = 'agenda.due'
                ORDER BY id DESC
                LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()
        result: list[dict] = []
        seen_ids: set[int] = set()
        for row in roots:
            root_id = int(row["id"])
            if root_id in seen_ids:
                continue
            seen_ids.add(root_id)
            detail = self.event_workflow_detail(root_id)
            if not detail:
                continue
            result.append({
                "root_event_id": detail["root_event_id"],
                "topic": detail["topic"],
                "title": detail["title"],
                "status": detail["status"],
                "created_at": detail["created_at"],
                "processed_at": detail["processed_at"],
                "progress": detail["progress"],
                "root_cause": detail["root_cause"],
            })
        return result

    def pipeline_dag_runtime(self, recent_limit: int = 200) -> dict[str, Any]:
        nodes = self.pipeline_dag_all(enabled_only=True)
        with self._conn_lock:
            run_rows = self._conn.execute(
                """
                SELECT id, job_name, stage, trigger_event_id, status,
                       result_summary, started_at, completed_at, elapsed_ms
                FROM job_runs
                ORDER BY id DESC
                LIMIT ?
                """,
                (max(50, int(recent_limit)),),
            ).fetchall()
            event_rows = self._conn.execute(
                """
                SELECT id, topic, status, handler, error, created_at, processed_at, elapsed_ms
                FROM event_log
                ORDER BY id DESC
                LIMIT ?
                """,
                (max(50, int(recent_limit)),),
            ).fetchall()

        runs_by_job: dict[str, list[dict]] = {}
        for row in run_rows:
            runs_by_job.setdefault(str(row["job_name"]), []).append(dict(row))
        events_by_topic: dict[str, list[dict]] = {}
        for row in event_rows:
            events_by_topic.setdefault(str(row["topic"]), []).append(dict(row))

        runtime_nodes: list[dict] = []
        edges: list[dict] = []
        stage_summary: dict[str, dict[str, int]] = {}
        for row in nodes:
            job_name = str(row.get("job_name") or "")
            source_topic = str(row.get("source") or "")
            emits_topic = str(row.get("emits") or "")
            job_runs = runs_by_job.get(job_name, [])
            source_events = events_by_topic.get(source_topic, [])
            latest_run = job_runs[0] if job_runs else None
            latest_source = source_events[0] if source_events else None
            latest_error_run = next((item for item in job_runs if str(item.get("status")) == "error"), None)
            latest_error_event = next((item for item in source_events if str(item.get("status")) == "error"), None)
            running_count = sum(1 for item in job_runs if str(item.get("status")) == "running")
            ok_count = sum(1 for item in job_runs[:10] if str(item.get("status")) == "ok")
            error_count = sum(1 for item in job_runs[:10] if str(item.get("status")) == "error")
            status = "unknown"
            if running_count:
                status = "running"
            elif latest_run:
                status = str(latest_run.get("status") or "unknown")
            elif latest_source:
                status = str(latest_source.get("status") or "unknown")
            error_detail = (
                (latest_error_run or {}).get("result_summary")
                or (latest_error_event or {}).get("error")
            )
            node = {
                **dict(row),
                "status": status,
                "last_run": latest_run,
                "last_source_event": latest_source,
                "running_count": running_count,
                "recent_ok_count": ok_count,
                "recent_error_count": error_count,
                "error_detail": error_detail,
            }
            runtime_nodes.append(node)
            if source_topic:
                edges.append({"from": source_topic, "to": job_name, "kind": "source"})
            if emits_topic:
                edges.append({"from": job_name, "to": emits_topic, "kind": "emit"})
            stage = str(row.get("stage") or "unknown")
            stats = stage_summary.setdefault(stage, {"total": 0, "running": 0, "error": 0, "ok": 0, "disabled": 0})
            stats["total"] += 1
            if not bool(row.get("enabled")):
                stats["disabled"] += 1
            elif status == "running":
                stats["running"] += 1
            elif status == "error":
                stats["error"] += 1
            elif status == "ok":
                stats["ok"] += 1
        return {"nodes": runtime_nodes, "edges": edges, "stage_summary": stage_summary}

    # ── Pipeline DAG ───────────────────────────────────────────────────────────

    def pipeline_dag_all(self, enabled_only: bool = False) -> list[dict]:
        if enabled_only:
            rows = self._conn.execute(
                "SELECT * FROM pipeline_dag WHERE enabled=1 ORDER BY stage, id"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM pipeline_dag ORDER BY stage, id"
            ).fetchall()
        return [dict(r) for r in rows]

    def pipeline_dag_get(self, dag_id: int) -> dict[str, Any] | None:
        with self._conn_lock:
            row = self._conn.execute(
                "SELECT * FROM pipeline_dag WHERE id=? LIMIT 1",
                (int(dag_id),),
            ).fetchone()
        return dict(row) if row else None

    def pipeline_dag_set_enabled(self, dag_id: int, enabled: bool) -> None:
        self._conn.execute(
            "UPDATE pipeline_dag SET enabled=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (1 if enabled else 0, dag_id),
        )
        self._conn.commit()

    def pipeline_dag_set_enabled_by_job(self, job_name: str, enabled: bool) -> int:
        cur = self._conn.execute(
            "UPDATE pipeline_dag SET enabled=?, updated_at=CURRENT_TIMESTAMP WHERE job_name=?",
            (1 if enabled else 0, job_name),
        )
        self._conn.commit()
        return cur.rowcount

    # ── UI snapshot cache ─────────────────────────────────────────────────────

    def ui_snapshot_get(self, snapshot_key: str, scope: str = "default") -> dict[str, Any] | None:
        with self._conn_lock:
            row = self._conn.execute(
                """
                SELECT snapshot_key, scope, signature, payload_json, status,
                       built_at, expires_at, build_ms, producer
                FROM ui_snapshots
                WHERE snapshot_key=? AND scope=?
                LIMIT 1
                """,
                (snapshot_key, scope),
            ).fetchone()
        if not row:
            return None
        data = dict(row)
        payload_json = data.get("payload_json")
        if isinstance(payload_json, str):
            try:
                data["payload_json"] = json.loads(payload_json)
            except Exception:
                data["payload_json"] = {}
        return data

    def ui_snapshot_upsert(
        self,
        snapshot_key: str,
        signature: str,
        payload: dict[str, Any],
        *,
        scope: str = "default",
        ttl_seconds: int | None = None,
        status: str = "ok",
        build_ms: int = 0,
        producer: str = "web",
    ) -> None:
        expires_at = None
        if ttl_seconds and ttl_seconds > 0:
            expires_at = (datetime.now() + timedelta(seconds=int(ttl_seconds))).isoformat(sep=" ", timespec="seconds")
        with self._conn_lock:
            self._conn.execute(
                """
                INSERT INTO ui_snapshots
                    (snapshot_key, scope, signature, payload_json, status,
                     built_at, expires_at, build_ms, producer)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?, ?)
                ON CONFLICT(snapshot_key, scope) DO UPDATE SET
                    signature=excluded.signature,
                    payload_json=excluded.payload_json,
                    status=excluded.status,
                    built_at=CURRENT_TIMESTAMP,
                    expires_at=excluded.expires_at,
                    build_ms=excluded.build_ms,
                    producer=excluded.producer
                """,
                (
                    snapshot_key,
                    scope,
                    signature,
                    json.dumps(payload, ensure_ascii=False),
                    status,
                    expires_at,
                    int(build_ms),
                    producer,
                ),
            )
            self._conn.commit()

    # ── Causal snapshots / validation ───────────────────────────────────────

    def causal_snapshot_upsert(
        self,
        *,
        snapshot_id: str,
        symbol: str,
        as_of_date: str,
        action: str | None,
        decision_confidence: float | None,
        data_model_trust: float | None,
        inferred_state: dict[str, Any],
        chain: dict[str, Any],
    ) -> None:
        with self._conn_lock:
            self._conn.execute(
                """
                INSERT INTO causal_decision_snapshots
                    (snapshot_id, symbol, as_of_date, action, decision_confidence,
                     data_model_trust, inferred_state_json, chain_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT(symbol, as_of_date) DO UPDATE SET
                    snapshot_id=excluded.snapshot_id,
                    action=excluded.action,
                    decision_confidence=excluded.decision_confidence,
                    data_model_trust=excluded.data_model_trust,
                    inferred_state_json=excluded.inferred_state_json,
                    chain_json=excluded.chain_json,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    snapshot_id,
                    symbol,
                    as_of_date,
                    action,
                    decision_confidence,
                    data_model_trust,
                    json.dumps(inferred_state, ensure_ascii=False),
                    json.dumps(chain, ensure_ascii=False),
                ),
            )
            self._conn.commit()

    def causal_snapshot_get(self, snapshot_id: str) -> dict[str, Any] | None:
        with self._conn_lock:
            row = self._conn.execute(
                "SELECT * FROM causal_decision_snapshots WHERE snapshot_id=? LIMIT 1",
                (snapshot_id,),
            ).fetchone()
        if not row:
            return None
        data = dict(row)
        data["inferred_state"] = _json_loads_safe(data.get("inferred_state_json"), {})
        data["chain"] = _json_loads_safe(data.get("chain_json"), {})
        return data

    def causal_snapshot_get_latest(self, symbol: str, *, as_of_date: str | None = None) -> dict[str, Any] | None:
        query = "SELECT * FROM causal_decision_snapshots WHERE symbol=?"
        params: list[Any] = [symbol]
        if as_of_date:
            query += " AND as_of_date<=?"
            params.append(as_of_date)
        query += " ORDER BY as_of_date DESC LIMIT 1"
        with self._conn_lock:
            row = self._conn.execute(query, tuple(params)).fetchone()
        if not row:
            return None
        data = dict(row)
        data["inferred_state"] = _json_loads_safe(data.get("inferred_state_json"), {})
        data["chain"] = _json_loads_safe(data.get("chain_json"), {})
        return data

    def causal_validation_replace(self, snapshot_id: str, outcomes: list[dict[str, Any]]) -> None:
        with self._conn_lock:
            self._conn.execute(
                "DELETE FROM causal_validation_outcomes WHERE snapshot_id=?",
                (snapshot_id,),
            )
            for item in outcomes:
                self._conn.execute(
                    """
                    INSERT INTO causal_validation_outcomes
                        (snapshot_id, symbol, decision_as_of, evaluation_date, horizon,
                         predicted_direction, realized_return, realized_volatility,
                         invalidator_hit, calibration_error, decision_correctness,
                         notes, payload_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (
                        snapshot_id,
                        item.get("symbol"),
                        item.get("decision_as_of"),
                        item.get("evaluation_date"),
                        item.get("horizon"),
                        item.get("predicted_direction"),
                        item.get("realized_return"),
                        item.get("realized_volatility"),
                        None if item.get("invalidator_hit") is None else (1 if item.get("invalidator_hit") else 0),
                        item.get("calibration_error"),
                        item.get("decision_correctness"),
                        item.get("notes"),
                        json.dumps(item, ensure_ascii=False),
                    ),
                )
            self._conn.commit()

    def causal_validation_list(self, snapshot_id: str) -> list[dict[str, Any]]:
        with self._conn_lock:
            rows = self._conn.execute(
                "SELECT * FROM causal_validation_outcomes WHERE snapshot_id=? ORDER BY horizon",
                (snapshot_id,),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            data = dict(row)
            data["payload"] = _json_loads_safe(data.get("payload_json"), {})
            result.append(data)
        return result

    def causal_reward_records_replace(self, snapshot_id: str, records: list[dict[str, Any]]) -> None:
        with self._conn_lock:
            self._conn.execute(
                "DELETE FROM causal_reward_punishment WHERE snapshot_id=?",
                (snapshot_id,),
            )
            for item in records:
                self._conn.execute(
                    """
                    INSERT INTO causal_reward_punishment
                        (snapshot_id, target_type, target_id, reward_score, punishment_score,
                         rationale, evaluation_horizon, derived_from_validation_id,
                         payload_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (
                        snapshot_id,
                        item.get("target_type"),
                        item.get("target_id"),
                        item.get("reward_score"),
                        item.get("punishment_score"),
                        item.get("rationale"),
                        item.get("evaluation_horizon"),
                        item.get("derived_from_validation_id"),
                        json.dumps(item, ensure_ascii=False),
                    ),
                )
            self._conn.commit()

    def causal_reward_records_list(self, snapshot_id: str) -> list[dict[str, Any]]:
        with self._conn_lock:
            rows = self._conn.execute(
                "SELECT * FROM causal_reward_punishment WHERE snapshot_id=? ORDER BY evaluation_horizon, id",
                (snapshot_id,),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            data = dict(row)
            data["payload"] = _json_loads_safe(data.get("payload_json"), {})
            result.append(data)
        return result

    # ── Model Registry ─────────────────────────────────────────────────────────

    # ── Evaluation ─────────────────────────────────────────────────────────────

    # ── KG Relations ───────────────────────────────────────────────────────────

    # ── EBRT: ArticleEvent ─────────────────────────────────────────────────────

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _cast(value: str, vtype: str) -> Any:
        if vtype == "int":
            return int(value)
        if vtype == "float":
            return float(value)
        if vtype == "bool":
            return value.lower() in ("1", "true", "yes")
        if vtype == "json":
            return _json_loads_safe(value, value)
        return value
