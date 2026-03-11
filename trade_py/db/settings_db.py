from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_SETTINGS: list[tuple[str, str, str, str, str]] = [
    # (key, value, value_type, category, label)
    # 风险参数
    ("risk.target_annual_vol",   "0.11",    "float",  "risk",      "目标年化波动率"),
    ("risk.max_single_weight",   "0.10",    "float",  "risk",      "单股最大仓位"),
    ("risk.max_industry_weight", "0.35",    "float",  "risk",      "行业最大仓位"),
    ("risk.base_cash_pct",       "0.10",    "float",  "risk",      "基础现金比例"),
    # 交易成本
    ("cost.stamp_tax_rate",      "0.0005",  "float",  "risk",      "印花税率"),
    ("cost.commission_rate",     "0.00025", "float",  "risk",      "佣金率"),
    ("cost.commission_min_yuan", "5.0",     "float",  "risk",      "最低佣金（元）"),
    # 回测参数
    ("backtest.initial_capital", "1000000", "float",  "backtest",  "初始资金（元）"),
    ("backtest.max_positions",   "25",      "int",    "backtest",  "最大持仓数"),
    ("backtest.min_positions",   "15",      "int",    "backtest",  "最小持仓数"),
    # 信号参数
    ("signal.window_act_threshold",   "80", "int",    "signal",    "出手窗口质量分 cutoff"),
    ("signal.window_watch_threshold", "60", "int",    "signal",    "观察窗口质量分 cutoff"),
    # 调度参数
    ("scheduler.brief_time",     "09:10",   "string", "scheduler", "晨报生成时间"),
    ("scheduler.scan_interval",  "5",       "int",    "scheduler", "盘中扫描间隔（分钟）"),
    # 市场数据参数
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
    # Hook 推送
    ("hooks.notify_url",  "",               "string", "hooks", "推送 Webhook URL（DingTalk/Telegram/飞书/通用）"),
    ("hooks.notify_on",   "failure,success", "string", "hooks", "触发推送的事件（start/success/failure，逗号分隔）"),
]


class SettingsDB:
    """Read/write user settings stored in the shared SQLite metadata database.

    Settings are key-value pairs with a type hint (string | int | float | bool | json).
    All user-tunable parameters (risk limits, backtest params, signal thresholds)
    live here so they can be edited from the Web UI without touching YAML files.
    """

    def __init__(self, data_root: str = "data") -> None:
        db_path = Path(data_root) / ".metadata" / "trade.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
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
                date               DATE NOT NULL,
                symbol             TEXT NOT NULL,
                window_score       INTEGER,
                smart_money_signal INTEGER,
                large_order_trend  TEXT,
                net_sentiment      REAL,
                updated_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (date, symbol)
            );

            CREATE TABLE IF NOT EXISTS macro_events (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                event_date       DATE NOT NULL,
                event_type       TEXT NOT NULL,
                source           TEXT,
                intensity        REAL,
                affected_assets  TEXT,
                notes            TEXT
            );

            CREATE TABLE IF NOT EXISTS job_runs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                job_name    TEXT    NOT NULL,
                status      TEXT    NOT NULL,   -- 'running' | 'success' | 'failure'
                message     TEXT,
                started_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                finished_at TIMESTAMP,
                duration_s  REAL
            );

            CREATE TABLE IF NOT EXISTS job_schedule (
                job_name    TEXT PRIMARY KEY,
                cron_desc   TEXT NOT NULL,   -- 人类可读，如 "每天 07:00"
                next_run    TIMESTAMP,       -- 由守护进程写入，未启动时为 NULL
                last_status TEXT,            -- 上次执行结果 (success/failure/-)
                last_run_at TIMESTAMP,       -- 上次执行时间
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
        """)
        self._conn.commit()
        self._migrate()
        self._seed_defaults()

    def _migrate(self) -> None:
        """Add columns introduced after initial schema creation."""
        cur = self._conn.cursor()
        existing = {
            row[1]
            for row in cur.execute("PRAGMA table_info(signal_cache)").fetchall()
        }
        if "net_sentiment" not in existing:
            cur.execute("ALTER TABLE signal_cache ADD COLUMN net_sentiment REAL")
        for col, typedef in [
            ("event_kg_score",     "REAL"),
            ("event_affected",     "INTEGER"),
            ("event_type",         "TEXT"),
            ("event_typical_days", "INTEGER"),
            ("model_score",        "REAL"),    # LightGBM 预测的 5日超额收益百分位 [0-100]
            ("model_risk",         "REAL"),    # P(loss_5pct_20d) 风险概率 [0-1]
            ("model_updated",      "TEXT"),    # 最近推理日期
        ]:
            if col not in existing:
                cur.execute(f"ALTER TABLE signal_cache ADD COLUMN {col} {typedef}")
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

    # ── Settings CRUD ─────────────────────────────────────────────────────────

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

    # ── Instrument lookup (instruments table lives in the same DB) ────────────

    def instrument_lookup(self, symbol: str) -> dict | None:
        """Return {'name', 'market_name'} for a symbol, or None if not in instruments."""
        row = self._conn.execute(
            "SELECT name, market_name FROM instruments WHERE symbol = ?", (symbol,)
        ).fetchone()
        if row is None:
            return None
        return {"name": row["name"] or "", "market_name": row["market_name"] or ""}

    # ── Watchlist ─────────────────────────────────────────────────────────────

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
        """Return watchlist rows with instrument name joined from instruments table."""
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
        return [
            {"symbol": r["symbol"], "name": r["name"], "market_name": r["market_name"]}
            for r in rows
        ]

    # ── Signal cache ──────────────────────────────────────────────────────────

    def signal_cache_upsert(self, date: str, symbol: str, **fields: Any) -> None:
        cols = ["date", "symbol"] + list(fields.keys())
        placeholders = ", ".join(["?"] * len(cols))
        updates = ", ".join(f"{k} = excluded.{k}" for k in fields)
        values = [date, symbol] + [str(v) for v in fields.values()]
        self._conn.execute(
            f"INSERT INTO signal_cache ({', '.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT(date, symbol) DO UPDATE SET {updates}, "
            f"updated_at = CURRENT_TIMESTAMP",
            values,
        )
        self._conn.commit()

    def signal_cache_get(self, date: str, order_by: str = "auto") -> list[dict]:
        """Return signal cache rows for date.

        order_by: "model_score" | "window_score" | "auto" (model_score if available, else window_score)
        """
        if order_by == "model_score":
            sort_col = "model_score DESC NULLS LAST"
        elif order_by == "window_score":
            sort_col = "window_score DESC NULLS LAST"
        else:
            # auto: prefer model_score, fall back to window_score
            sort_col = "COALESCE(model_score, -1) DESC, COALESCE(window_score, 0) DESC"
        rows = self._conn.execute(
            f"SELECT * FROM signal_cache WHERE date = ? ORDER BY {sort_col}",
            (date,),
        ).fetchall()
        return [dict(r) for r in rows]

    def signal_cache_suggest(
        self,
        limit: int = 20,
        by: str = "model_score",
        sector_limit: int = 3,
    ) -> list[dict]:
        """Return top candidates sorted by score, with per-sector cap.

        Args:
            limit:        Max number of suggestions.
            by:           Sort column: "model_score" | "window_score".
            sector_limit: Max suggestions per SW sector.
        """
        col = by if by in ("model_score", "window_score") else "model_score"

        # Try joining instruments for sector info; fall back to no join if table missing
        # Use latest date per symbol to avoid duplicates
        try:
            rows = self._conn.execute(
                f"""
                WITH latest AS (
                    SELECT symbol, MAX(date) AS max_date
                    FROM signal_cache
                    WHERE {col} IS NOT NULL
                    GROUP BY symbol
                )
                SELECT sc.date, sc.symbol, sc.model_score, sc.model_risk,
                       sc.window_score, sc.net_sentiment,
                       COALESCE(i.industry, 255) AS industry
                FROM signal_cache sc
                JOIN latest ON sc.symbol = latest.symbol AND sc.date = latest.max_date
                LEFT JOIN instruments i ON sc.symbol = i.symbol
                ORDER BY sc.{col} DESC
                LIMIT ?
                """,
                (limit * sector_limit,),
            ).fetchall()
        except Exception:
            rows = self._conn.execute(
                f"""
                WITH latest AS (
                    SELECT symbol, MAX(date) AS max_date
                    FROM signal_cache
                    WHERE {col} IS NOT NULL
                    GROUP BY symbol
                )
                SELECT sc.date, sc.symbol, sc.model_score, sc.model_risk,
                       sc.window_score, sc.net_sentiment,
                       255 AS industry
                FROM signal_cache sc
                JOIN latest ON sc.symbol = latest.symbol AND sc.date = latest.max_date
                ORDER BY sc.{col} DESC
                LIMIT ?
                """,
                (limit * sector_limit,),
            ).fetchall()

        # Apply per-sector cap
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

    # ── Job run history ───────────────────────────────────────────────────────

    def job_run_start(self, job_name: str) -> int:
        """Insert a 'running' row; return the new row id."""
        cur = self._conn.execute(
            "INSERT INTO job_runs (job_name, status, started_at) "
            "VALUES (?, 'running', CURRENT_TIMESTAMP)",
            (job_name,),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def job_run_finish(self, run_id: int, status: str, message: str | None = None) -> None:
        """Update the row with final status, message, and duration."""
        self._conn.execute(
            """
            UPDATE job_runs
            SET status      = ?,
                message     = ?,
                finished_at = CURRENT_TIMESTAMP,
                duration_s  = CAST(
                    (julianday('now') - julianday(started_at)) * 86400 AS REAL
                )
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
                cron_desc  = excluded.cron_desc,
                next_run   = excluded.next_run,
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
            UPDATE job_schedule
            SET last_status = ?, last_run_at = ?, updated_at = CURRENT_TIMESTAMP
            WHERE job_name = ?
            """,
            (status, last_run_at, job_name),
        )
        self._conn.commit()

    def job_schedule_all(self) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT job_name, cron_desc, next_run, last_status, last_run_at
            FROM job_schedule
            ORDER BY next_run NULLS LAST, job_name
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def job_runs_recent(self, limit: int = 50) -> list[dict]:
        """Return the most recent job run rows, newest first."""
        rows = self._conn.execute(
            """
            SELECT id, job_name, status, message, started_at, finished_at,
                   ROUND(duration_s, 1) AS duration_s
            FROM job_runs
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Events ────────────────────────────────────────────────────────────────

    def event_upsert(self, row: dict) -> None:
        """INSERT OR REPLACE into events table."""
        cols = list(row.keys())
        placeholders = ", ".join(["?"] * len(cols))
        self._conn.execute(
            f"INSERT OR REPLACE INTO events ({', '.join(cols)}) VALUES ({placeholders})",
            [row[c] for c in cols],
        )
        self._conn.commit()

    def event_propagation_insert_batch(self, rows: list[dict]) -> None:
        """INSERT OR IGNORE into event_propagations (unique by event_id+symbol)."""
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
        self,
        from_date: str | None = None,
        to_date: str | None = None,
        event_type: str | None = None,
        failed_only: bool = False,
        limit: int = 1000,
    ) -> list[dict]:
        """Return events with optional date/type filtering and propagation count.

        Args:
            from_date:   Inclusive start date (YYYY-MM-DD).
            to_date:     Inclusive end date (YYYY-MM-DD).
            event_type:  Filter by event type string.
            failed_only: If True, return only events with zero propagations.
            limit:       Max rows to return.

        Returns:
            List of dicts with all events columns plus 'affected_stocks' count.
        """
        clauses: list[str] = []
        params: list = []
        if from_date:
            clauses.append("e.event_date >= ?")
            params.append(from_date)
        if to_date:
            clauses.append("e.event_date <= ?")
            params.append(to_date)
        if event_type:
            clauses.append("e.event_type = ?")
            params.append(event_type)
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
            {where}
            GROUP BY e.event_id
            {having}
            ORDER BY e.event_date DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    def events_recent(self, limit: int = 30, symbol: str | None = None,
                      event_type: str | None = None) -> list[dict]:
        """Return recent events. If symbol given, joins event_propagations."""
        if symbol:
            rows = self._conn.execute(
                """
                SELECT e.event_id, e.event_date, e.event_type, e.magnitude,
                       e.primary_sector, e.breadth, e.summary,
                       ep.kg_score, ep.hop, ep.typical_days,
                       ep.actual_return_5d, ep.actual_return_20d
                FROM events e
                JOIN event_propagations ep ON e.event_id = ep.event_id
                WHERE ep.symbol = ?
                  AND (? IS NULL OR e.event_type = ?)
                ORDER BY e.event_date DESC
                LIMIT ?
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
                GROUP BY e.event_id
                ORDER BY e.event_date DESC
                LIMIT ?
                """,
                (event_type, event_type, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def event_propagations_fill_returns(self, event_date: str,
                                        symbol_returns: dict[str, float],
                                        window: int) -> int:
        """UPDATE actual_return_{window}d for rows where it's NULL.

        Returns the number of rows updated.
        """
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

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _cast(value: str, vtype: str) -> Any:
        if vtype == "int":
            return int(value)
        if vtype == "float":
            return float(value)
        if vtype == "bool":
            return value.lower() in ("1", "true", "yes")
        return value
