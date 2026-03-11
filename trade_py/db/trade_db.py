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
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

from trade_py.db.migrations import run_migrations

logger = logging.getLogger(__name__)

# ── Instruments helpers (from instruments_db.py) ──────────────────────────────

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
    ("scheduler.brief_time",     "09:10",   "string", "scheduler", "晨报生成时间"),
    ("scheduler.scan_interval",  "5",       "int",    "scheduler", "盘中扫描间隔（分钟）"),
    ("kline.start",              "2020-01-01", "string", "market_data", "K线默认起始日期"),
    ("index.start_date",         "2020-01-01", "string", "market_data", "指数/板块默认起始日期"),
    ("tushare.http_url",         "",       "string", "market_data", "Tushare API URL"),
    ("tushare.min_interval_sec", "0.6",    "float",  "market_data", "Tushare最小请求间隔（秒）"),
    ("tushare.minute_budget",    "50",     "int",    "market_data", "Tushare每分钟预算"),
    ("tushare.chunk_days",       "1825",   "int",    "market_data", "Tushare K线单次请求天数跨度"),
    ("tushare.rate_limit_backoff_sec", "5,15,30,45,60", "string", "market_data", "Tushare限流退避序列（秒）"),
    ("tushare.audit_log_enabled","1",      "bool",   "market_data", "Tushare请求审计日志"),
    ("sentiment.start",          "2026-01-01", "string", "market_data", "情绪数据默认起始日期"),
    ("sentiment.settle_window_days", "7", "int", "market_data", "情绪数据稳定窗口（天）"),
    ("event.min_magnitude",      "0.4",   "float",  "market_data", "事件提取最低强度"),
    ("event.sync_window_days",   "7",     "int",    "market_data", "事件补齐窗口（天）"),
    ("hooks.notify_url",  "",               "string", "hooks", "推送 Webhook URL"),
    ("hooks.notify_on",   "failure,success", "string", "hooks", "触发推送的事件"),
]


def _infer_market(code: str) -> int:
    if code.startswith(("6", "9")):
        return _MARKET_SH
    if code.startswith(("4", "8")):
        return _MARKET_BJ
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


def _find_db_path(data_root: Path) -> Path:
    """Return path to trade.db, preferring new .db/ location over legacy .metadata/."""
    new_path = data_root / ".db" / "trade.db"
    if new_path.exists():
        return new_path
    legacy = data_root / ".metadata" / "trade.db"
    if legacy.exists():
        return legacy
    # Fresh install: use new path
    return new_path


class TradeDB:
    """Unified SQLite wrapper for all trade metadata.

    Combines SettingsDB (settings, watchlist, signal_cache, events, job tracking)
    and InstrumentsDB (instruments, watermarks, downloads, sector members).
    Runs schema migrations on construction.
    """

    def __init__(self, data_root: str | Path = "data") -> None:
        self._data_root = Path(data_root)
        db_file = _find_db_path(self._data_root)
        db_file.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_file), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()
        run_migrations(self._conn)
        self._seed_defaults()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "TradeDB":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    # ── Schema ─────────────────────────────────────────────────────────────────

    def _init_schema(self) -> None:
        """Create all tables in their final form (no dead columns)."""
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS settings (
                key         TEXT PRIMARY KEY,
                value       TEXT NOT NULL,
                value_type  TEXT NOT NULL DEFAULT 'string',
                category    TEXT NOT NULL DEFAULT 'general',
                label       TEXT,
                description TEXT,
                updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS watchlist (
                symbol    TEXT PRIMARY KEY,
                added_at  DATE NOT NULL DEFAULT (date('now')),
                note      TEXT,
                active    INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS signal_cache (
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

            CREATE TABLE IF NOT EXISTS job_runs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                job_name    TEXT    NOT NULL,
                status      TEXT    NOT NULL,
                message     TEXT,
                started_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                finished_at TIMESTAMP,
                duration_s  REAL
            );

            CREATE TABLE IF NOT EXISTS job_schedule (
                job_name    TEXT PRIMARY KEY,
                cron_desc   TEXT NOT NULL,
                next_run    TIMESTAMP,
                last_status TEXT,
                last_run_at TIMESTAMP,
                updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS events (
                event_id        TEXT PRIMARY KEY,
                event_date      DATE NOT NULL,
                event_type      TEXT NOT NULL,
                magnitude       REAL NOT NULL,
                actor_type      TEXT,
                primary_sector  TEXT,
                breadth         TEXT,
                sentiment_score REAL,
                news_volume     INTEGER,
                summary         TEXT,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_events_date ON events(event_date);

            CREATE TABLE IF NOT EXISTS event_propagations (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id          TEXT NOT NULL,
                event_date        DATE NOT NULL,
                symbol            TEXT NOT NULL,
                sector            TEXT,
                kg_score          REAL,
                hop               INTEGER,
                typical_days      INTEGER,
                actual_return_5d  REAL,
                actual_return_20d REAL,
                created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_ep_symbol ON event_propagations(symbol);
            CREATE INDEX IF NOT EXISTS idx_ep_date   ON event_propagations(event_date);

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

            CREATE TABLE IF NOT EXISTS downloads (
                symbol        TEXT,
                start_date    TEXT,
                end_date      TEXT,
                row_count     INTEGER,
                downloaded_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (symbol, end_date)
            );
            CREATE INDEX IF NOT EXISTS idx_downloads_symbol_end ON downloads(symbol, end_date);

            CREATE TABLE IF NOT EXISTS watermarks (
                source          TEXT NOT NULL,
                dataset         TEXT NOT NULL,
                symbol          TEXT NOT NULL,
                last_event_date TEXT NOT NULL,
                cursor_payload  TEXT NOT NULL DEFAULT '{}',
                updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (source, dataset, symbol)
            );
            CREATE INDEX IF NOT EXISTS idx_watermarks_lookup ON watermarks(source, dataset, symbol);

            CREATE TABLE IF NOT EXISTS instrument_sector_members (
                symbol        TEXT PRIMARY KEY,
                sector_code   TEXT NOT NULL,
                sector_name   TEXT NOT NULL,
                industry_code INTEGER NOT NULL,
                updated_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_instrument_sector_members_sector_code
                ON instrument_sector_members(sector_code);
            CREATE INDEX IF NOT EXISTS idx_instrument_sector_members_industry_code
                ON instrument_sector_members(industry_code);
        """)
        self._conn.commit()
        self._ensure_instruments_columns()
        self._rebuild_classification_view()

    def _ensure_instruments_columns(self) -> None:
        """Add columns that may be missing from older instrument tables."""
        cur = self._conn.cursor()
        for ddl in [
            "ALTER TABLE instruments ADD COLUMN total_shares INTEGER DEFAULT 0",
            "ALTER TABLE instruments ADD COLUMN float_shares INTEGER DEFAULT 0",
            "ALTER TABLE instruments ADD COLUMN market_name TEXT NOT NULL DEFAULT ''",
        ]:
            try:
                cur.execute(ddl)
            except sqlite3.OperationalError:
                pass  # column already exists

    def _rebuild_classification_view(self) -> None:
        cur = self._conn.cursor()
        cur.execute("DROP VIEW IF EXISTS instrument_classification_v")
        cur.execute(f"""
            CREATE VIEW instrument_classification_v AS
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
            LEFT JOIN instrument_sector_members m ON i.symbol = m.symbol
        """)
        self._conn.commit()

    def _seed_defaults(self) -> None:
        cur = self._conn.cursor()
        for key, value, vtype, category, label in _DEFAULT_SETTINGS:
            cur.execute(
                "INSERT OR IGNORE INTO settings (key, value, value_type, category, label) "
                "VALUES (?, ?, ?, ?, ?)",
                (key, value, vtype, category, label),
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

    def set(self, key: str, value: Any) -> None:
        self._conn.execute(
            "INSERT INTO settings (key, value, value_type, category, updated_at) "
            "VALUES (?, ?, 'string', 'general', CURRENT_TIMESTAMP) "
            "ON CONFLICT(key) DO UPDATE SET "
            "value = excluded.value, updated_at = CURRENT_TIMESTAMP",
            (key, str(value)),
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

    # ── Signal cache ───────────────────────────────────────────────────────────

    def signal_cache_upsert(self, date: str, symbol: str, **fields: Any) -> None:
        cols = ["date", "symbol"] + list(fields.keys())
        placeholders = ", ".join(["?"] * len(cols))
        updates = ", ".join(f"{k} = excluded.{k}" for k in fields)
        values = [date, symbol] + [str(v) if v is not None else None for v in fields.values()]
        self._conn.execute(
            f"INSERT INTO signal_cache ({', '.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT(date, symbol) DO UPDATE SET {updates}, "
            f"updated_at = CURRENT_TIMESTAMP",
            values,
        )
        self._conn.commit()

    def signal_cache_get(self, date: str, order_by: str = "auto") -> list[dict]:
        if order_by == "model_score":
            sort_col = "model_score DESC NULLS LAST"
        elif order_by == "window_score":
            sort_col = "window_score DESC NULLS LAST"
        else:
            sort_col = "COALESCE(model_score, -1) DESC, COALESCE(window_score, 0) DESC"
        rows = self._conn.execute(
            f"SELECT * FROM signal_cache WHERE date = ? ORDER BY {sort_col}",
            (date,),
        ).fetchall()
        return [dict(r) for r in rows]

    def signal_cache_suggest(
        self, limit: int = 20, by: str = "model_score", sector_limit: int = 3,
    ) -> list[dict]:
        col = by if by in ("model_score", "window_score") else "model_score"
        try:
            rows = self._conn.execute(
                f"""
                WITH latest AS (
                    SELECT symbol, MAX(date) AS max_date
                    FROM signal_cache WHERE {col} IS NOT NULL GROUP BY symbol
                )
                SELECT sc.date, sc.symbol, sc.model_score, sc.model_risk,
                       sc.window_score, sc.net_sentiment,
                       COALESCE(i.industry, 255) AS industry
                FROM signal_cache sc
                JOIN latest ON sc.symbol = latest.symbol AND sc.date = latest.max_date
                LEFT JOIN instruments i ON sc.symbol = i.symbol
                ORDER BY sc.{col} DESC LIMIT ?
                """,
                (limit * sector_limit,),
            ).fetchall()
        except Exception:
            rows = self._conn.execute(
                f"""
                WITH latest AS (
                    SELECT symbol, MAX(date) AS max_date
                    FROM signal_cache WHERE {col} IS NOT NULL GROUP BY symbol
                )
                SELECT sc.date, sc.symbol, sc.model_score, sc.model_risk,
                       sc.window_score, sc.net_sentiment, 255 AS industry
                FROM signal_cache sc
                JOIN latest ON sc.symbol = latest.symbol AND sc.date = latest.max_date
                ORDER BY sc.{col} DESC LIMIT ?
                """,
                (limit * sector_limit,),
            ).fetchall()
        sector_counts: dict[int, int] = {}
        result = []
        for r in rows:
            d = dict(r)
            ind = d.get("industry", 255)
            if sector_counts.get(ind, 0) >= sector_limit:
                continue
            sector_counts[ind] = sector_counts.get(ind, 0) + 1
            result.append(d)
            if len(result) >= limit:
                break
        return result

    # ── Job run history ────────────────────────────────────────────────────────

    def job_run_start(self, job_name: str) -> int:
        cur = self._conn.execute(
            "INSERT INTO job_runs (job_name, status, started_at) "
            "VALUES (?, 'running', CURRENT_TIMESTAMP)",
            (job_name,),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def job_run_finish(self, run_id: int, status: str, message: str | None = None) -> None:
        self._conn.execute(
            """
            UPDATE job_runs
            SET status = ?, message = ?, finished_at = CURRENT_TIMESTAMP,
                duration_s = CAST((julianday('now') - julianday(started_at)) * 86400 AS REAL)
            WHERE id = ?
            """,
            (status, message, run_id),
        )
        self._conn.commit()

    def job_schedule_upsert(self, job_name: str, cron_desc: str, next_run: str | None = None) -> None:
        self._conn.execute(
            """
            INSERT INTO job_schedule (job_name, cron_desc, next_run, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(job_name) DO UPDATE SET
                cron_desc = excluded.cron_desc, next_run = excluded.next_run,
                updated_at = CURRENT_TIMESTAMP
            """,
            (job_name, cron_desc, next_run),
        )
        self._conn.commit()

    def job_schedule_update_next(self, job_name: str, next_run: str) -> None:
        self._conn.execute(
            "UPDATE job_schedule SET next_run = ?, updated_at = CURRENT_TIMESTAMP WHERE job_name = ?",
            (next_run, job_name),
        )
        self._conn.commit()

    def job_schedule_update_last(self, job_name: str, status: str, last_run_at: str) -> None:
        self._conn.execute(
            """
            UPDATE job_schedule SET last_status = ?, last_run_at = ?,
                updated_at = CURRENT_TIMESTAMP WHERE job_name = ?
            """,
            (status, last_run_at, job_name),
        )
        self._conn.commit()

    def job_schedule_all(self) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT job_name, cron_desc, next_run, last_status, last_run_at
            FROM job_schedule ORDER BY next_run NULLS LAST, job_name
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def job_runs_recent(self, limit: int = 50) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT id, job_name, status, message, started_at, finished_at,
                   ROUND(duration_s, 1) AS duration_s
            FROM job_runs ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Events ─────────────────────────────────────────────────────────────────

    def event_upsert(self, row: dict) -> None:
        cols = list(row.keys())
        placeholders = ", ".join(["?"] * len(cols))
        self._conn.execute(
            f"INSERT OR REPLACE INTO events ({', '.join(cols)}) VALUES ({placeholders})",
            [row[c] for c in cols],
        )
        self._conn.commit()

    def event_propagation_insert_batch(self, rows: list[dict]) -> None:
        if not rows:
            return
        cols = list(rows[0].keys())
        placeholders = ", ".join(["?"] * len(cols))
        self._conn.executemany(
            f"INSERT OR IGNORE INTO event_propagations ({', '.join(cols)}) VALUES ({placeholders})",
            [[r[c] for c in cols] for r in rows],
        )
        self._conn.commit()

    def get_events(
        self, from_date: str | None = None, to_date: str | None = None,
        event_type: str | None = None, failed_only: bool = False, limit: int = 1000,
    ) -> list[dict]:
        clauses: list[str] = []
        params: list = []
        if from_date:
            clauses.append("e.event_date >= ?"); params.append(from_date)
        if to_date:
            clauses.append("e.event_date <= ?"); params.append(to_date)
        if event_type:
            clauses.append("e.event_type = ?"); params.append(event_type)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        having = "HAVING COUNT(ep.id) = 0" if failed_only else ""
        params.append(limit)
        rows = self._conn.execute(
            f"""
            SELECT e.event_id, e.event_date, e.event_type, e.magnitude,
                   e.actor_type, e.primary_sector, e.breadth,
                   e.sentiment_score, e.news_volume, e.summary,
                   COUNT(ep.id) AS affected_stocks
            FROM events e
            LEFT JOIN event_propagations ep ON e.event_id = ep.event_id
            {where} GROUP BY e.event_id {having}
            ORDER BY e.event_date DESC LIMIT ?
            """,
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    def events_recent(self, limit: int = 30, symbol: str | None = None,
                      event_type: str | None = None) -> list[dict]:
        if symbol:
            rows = self._conn.execute(
                """
                SELECT e.event_id, e.event_date, e.event_type, e.magnitude,
                       e.primary_sector, e.breadth, e.summary,
                       ep.kg_score, ep.hop, ep.typical_days,
                       ep.actual_return_5d, ep.actual_return_20d
                FROM events e
                JOIN event_propagations ep ON e.event_id = ep.event_id
                WHERE ep.symbol = ? AND (? IS NULL OR e.event_type = ?)
                ORDER BY e.event_date DESC LIMIT ?
                """,
                (symbol, event_type, event_type, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT e.event_id, e.event_date, e.event_type, e.magnitude,
                       e.primary_sector, e.breadth, e.summary,
                       COUNT(ep.id) AS affected_stocks
                FROM events e
                LEFT JOIN event_propagations ep ON e.event_id = ep.event_id
                WHERE (? IS NULL OR e.event_type = ?)
                GROUP BY e.event_id ORDER BY e.event_date DESC LIMIT ?
                """,
                (event_type, event_type, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def event_propagations_fill_returns(self, event_date: str,
                                        symbol_returns: dict[str, float],
                                        window: int) -> int:
        col = f"actual_return_{window}d"
        updated = 0
        for symbol, ret in symbol_returns.items():
            cur = self._conn.execute(
                f"UPDATE event_propagations SET {col} = ? "
                f"WHERE event_date = ? AND symbol = ? AND {col} IS NULL",
                (ret, event_date, symbol),
            )
            updated += cur.rowcount
        self._conn.commit()
        return updated

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
        cur.execute("DELETE FROM instrument_sector_members")
        cur.executemany(
            """
            INSERT INTO instrument_sector_members
                (symbol, sector_code, sector_name, industry_code, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            rows,
        )
        self._conn.commit()

    def get_all_symbols(self) -> list[str]:
        cur = self._conn.execute("SELECT symbol FROM instruments ORDER BY symbol")
        return [row[0] for row in cur.fetchall()]

    def get_symbols_by_sector(self, sector: Any) -> list[str]:
        rows = self._conn.execute(
            "SELECT symbol FROM instrument_sector_members WHERE industry_code = ?",
            (int(sector),),
        ).fetchall()
        return [r[0] for r in rows]

    # ── Watermarks ─────────────────────────────────────────────────────────────

    def get_watermark(self, source: str, dataset: str, symbol: str) -> Optional[date]:
        cur = self._conn.execute(
            "SELECT last_event_date FROM watermarks WHERE source=? AND dataset=? AND symbol=?",
            (source, dataset, symbol),
        )
        row = cur.fetchone()
        if row is None:
            return None
        try:
            return date.fromisoformat(row[0][:10])
        except (ValueError, TypeError):
            return None

    def set_watermark(self, source: str, dataset: str, symbol: str, last_date: date) -> None:
        self._conn.execute(
            """
            INSERT INTO watermarks (source, dataset, symbol, last_event_date, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(source, dataset, symbol) DO UPDATE SET
                last_event_date=excluded.last_event_date, updated_at=CURRENT_TIMESTAMP
            """,
            (source, dataset, symbol, last_date.isoformat()),
        )
        self._conn.commit()

    # ── Downloads ──────────────────────────────────────────────────────────────

    def record_download(self, symbol: str, start: date, end: date, row_count: int) -> None:
        self._conn.execute(
            """
            INSERT INTO downloads (symbol, start_date, end_date, row_count)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(symbol, end_date) DO UPDATE SET
                start_date=excluded.start_date, row_count=excluded.row_count,
                downloaded_at=CURRENT_TIMESTAMP
            """,
            (symbol, start.isoformat(), end.isoformat(), row_count),
        )
        self._conn.commit()

    def last_download_date(self, symbol: str) -> Optional[date]:
        cur = self._conn.execute("SELECT MAX(end_date) FROM downloads WHERE symbol=?", (symbol,))
        row = cur.fetchone()
        if row is None or row[0] is None:
            return None
        try:
            return date.fromisoformat(row[0][:10])
        except (ValueError, TypeError):
            return None

    # ── Bus events ─────────────────────────────────────────────────────────────

    def bus_event_insert(self, topic: str, payload_json: str) -> int:
        """Insert a new bus event (status=pending). Returns the new row id."""
        cur = self._conn.execute(
            "INSERT INTO bus_events (topic, payload, status, created_at) "
            "VALUES (?, ?, 'pending', CURRENT_TIMESTAMP)",
            (topic, payload_json),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def bus_event_complete(self, id: int, status: str, handler: str,
                           error: str | None = None) -> None:
        self._conn.execute(
            """
            UPDATE bus_events SET status=?, handler=?, error=?,
                processed_at=CURRENT_TIMESTAMP WHERE id=?
            """,
            (status, handler, error, id),
        )
        self._conn.commit()

    def bus_events_recent(self, limit: int = 50, topic: str | None = None) -> list[dict]:
        if topic:
            rows = self._conn.execute(
                "SELECT * FROM bus_events WHERE topic=? ORDER BY id DESC LIMIT ?",
                (topic, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM bus_events ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def bus_events_pending(self, topic: str | None = None) -> list[dict]:
        if topic:
            rows = self._conn.execute(
                "SELECT * FROM bus_events WHERE status='pending' AND topic=? ORDER BY id",
                (topic,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM bus_events WHERE status='pending' ORDER BY id"
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _cast(value: str, vtype: str) -> Any:
        if vtype == "int":
            return int(value)
        if vtype == "float":
            return float(value)
        if vtype == "bool":
            return value.lower() in ("1", "true", "yes")
        return value
