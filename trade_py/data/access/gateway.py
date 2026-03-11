from __future__ import annotations

import json
import logging
import sqlite3
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from trade_py.data.access.policy import BackfillReport, ReadPolicy
from trade_py.data.market.kline.akshare import KlineFetcher
from trade_py.data.market.kline.providers import ensure_symbol
from trade_py.data.market.fund_flow.tushare import FundFlowFetcher
from trade_py.data.market.cross_asset import fetch_btc, fetch_fx_cnh, fetch_gold

logger = logging.getLogger(__name__)

_CST = timezone(timedelta(hours=8))


class DataGateway:
    """Unified read-through data access layer.

    Behavior contract:
    - Try local data first.
    - If gaps are found, attempt refill at least once.
    - Only degrade to defaults when refill attempt fails.
    - Keep failed gaps open, so next call retries again.
    """

    def __init__(self, data_root: str | Path = "data", policy: ReadPolicy | None = None) -> None:
        self._root = Path(data_root)
        self._policy = policy or ReadPolicy()
        from trade_py.db.trade_db import _find_db_path; self._meta_db = _find_db_path(self._root)
        self._meta_db.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_meta_tables()

    # ------------------------------------------------------------------
    # Public readers
    # ------------------------------------------------------------------

    def get_kline(
        self,
        symbol: str,
        lookback_bars: int = 260,
        end_date: date | None = None,
    ) -> tuple[pd.DataFrame, BackfillReport]:
        symbol = ensure_symbol(symbol)
        start_ts = time.perf_counter()
        report = BackfillReport(dataset="kline", key=symbol)

        target_end = end_date or self._effective_market_end()
        local_df = self._load_kline_local(symbol)
        report.local_range = self._df_date_range(local_df)

        local_ok = (not local_df.empty and pd.to_datetime(local_df["date"]).max().date() >= target_end)
        if not local_ok:
            report.action = "gap_fill"
            report.missing_range = self._missing_tail_range(local_df, target_end)
            report.api_endpoint = "kline_provider_chain"
            report.api_calls_est = 1
            ok, err = self._attempt_kline_fill(symbol)
            report.api_calls_actual = 1
            if not ok:
                report.degraded = True
                report.reason_code = err
                report.error = err
                report.action = "degraded"
                self._upsert_gap("kline", symbol, report.missing_range, err)
            else:
                self._resolve_gap("kline", symbol)

            local_df = self._load_kline_local(symbol)
            report.local_range = self._df_date_range(local_df)

        if local_df.empty:
            # Hard fallback: empty frame is still explicit degraded output.
            report.degraded = True
            if not report.reason_code:
                report.reason_code = "no_local_data"
            report.action = "degraded"
            self._record_report(report, start_ts)
            return pd.DataFrame(), report

        local_df = local_df.sort_values("date").reset_index(drop=True)
        local_df = local_df[pd.to_datetime(local_df["date"]).dt.date <= target_end]
        out = local_df.tail(lookback_bars).reset_index(drop=True)
        self._record_report(report, start_ts)
        return out, report

    def get_fund_flow(self, symbol: str, as_of: date | None = None) -> tuple[pd.DataFrame, BackfillReport]:
        symbol = ensure_symbol(symbol)
        start_ts = time.perf_counter()
        report = BackfillReport(dataset="fund_flow", key=symbol)

        target_end = as_of or self._effective_market_end()
        fetcher = FundFlowFetcher(str(self._root))
        df = fetcher.load(symbol)
        report.local_range = self._df_date_range(df)

        latest = self._latest_date(df, "date")
        if latest is None or latest < target_end:
            report.action = "gap_fill"
            report.missing_range = f"{(latest + timedelta(days=1)).isoformat() if latest else 'N/A'}..{target_end.isoformat()}"
            report.api_endpoint = "tushare.moneyflow"
            report.api_calls_est = 1
            try:
                start_date = (latest + timedelta(days=1)).isoformat() if latest else None
                df = fetcher.fetch_and_save(symbol, start_date=start_date, end_date=target_end.isoformat())
                report.api_calls_actual = 1
                self._resolve_gap("fund_flow", symbol)
            except Exception as exc:
                report.api_calls_actual = 1
                report.degraded = True
                report.reason_code = "api_error"
                report.error = repr(exc)
                report.action = "degraded"
                self._upsert_gap("fund_flow", symbol, report.missing_range, report.error)
                df = fetcher.load(symbol)

        self._record_report(report, start_ts)
        return df, report

    def get_cross_asset(self, name: str) -> tuple[pd.DataFrame, BackfillReport]:
        start_ts = time.perf_counter()
        report = BackfillReport(dataset="cross_asset", key=name)
        p = self._root / "cross_asset" / f"{name}.parquet"
        if p.exists():
            try:
                df = pd.read_parquet(p)
                report.local_range = self._df_date_range(df)
                self._record_report(report, start_ts)
                return df, report
            except Exception as exc:
                report.degraded = True
                report.reason_code = "read_error"
                report.error = repr(exc)

        report.action = "gap_fill"
        report.api_calls_est = 1
        try:
            if name == "gold":
                fetch_gold(str(self._root))
                report.api_endpoint = "akshare.spot_hist_sge"
            elif name == "btc":
                fetch_btc(str(self._root))
                report.api_endpoint = "coingecko.ohlc"
            elif name in {"fx", "fx_cnh"}:
                fetch_fx_cnh(str(self._root))
                report.api_endpoint = "akshare.fx_usdcnh"
            else:
                raise ValueError(f"unknown cross-asset dataset: {name}")
            report.api_calls_actual = 1
            df = pd.read_parquet(self._root / "cross_asset" / f"{('fx_cnh' if name == 'fx' else name)}.parquet")
            report.local_range = self._df_date_range(df)
            self._resolve_gap("cross_asset", name)
            self._record_report(report, start_ts)
            return df, report
        except Exception as exc:
            report.api_calls_actual = 1
            report.degraded = True
            report.reason_code = "api_error"
            report.error = repr(exc)
            report.action = "degraded"
            self._upsert_gap("cross_asset", name, "unknown", report.error)
            self._record_report(report, start_ts)
            return pd.DataFrame(), report

    def ensure_sentiment_gold_date(self, target_date: date) -> BackfillReport:
        """Ensure sentiment gold parquet for a date exists.

        API fetch is still controlled by sentiment pipeline. This method forces one
        pipeline attempt and records degradation on failure.
        """
        start_ts = time.perf_counter()
        key = target_date.isoformat()
        report = BackfillReport(dataset="sentiment_gold", key=key)
        gold_path = self._root / "sentiment" / "gold" / f"{target_date.year:04d}" / f"{target_date.month:02d}" / f"{key}.parquet"
        if gold_path.exists():
            report.local_range = key
            self._record_report(report, start_ts)
            return report

        report.action = "gap_fill"
        report.api_endpoint = "sentiment_pipeline"
        report.api_calls_est = 1
        try:
            from trade_py.cli._sentiment import main as sentiment_main
            rc = sentiment_main(["--date", key, "--data-root", str(self._root), "--fetch-mode", "incremental"])
            report.api_calls_actual = 1
            if rc != 0:
                raise RuntimeError(f"sentiment_main exited with {rc}")
            if not gold_path.exists():
                raise RuntimeError("gold not generated after sentiment run")
            report.local_range = key
            self._resolve_gap("sentiment_gold", key)
        except Exception as exc:
            report.degraded = True
            report.reason_code = "pipeline_error"
            report.error = repr(exc)
            report.action = "degraded"
            self._upsert_gap("sentiment_gold", key, key, report.error)

        self._record_report(report, start_ts)
        return report

    # ------------------------------------------------------------------
    # Reporting helpers
    # ------------------------------------------------------------------

    @staticmethod
    def format_report(report: BackfillReport) -> str:
        d = report.to_dict()
        return json.dumps(d, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _attempt_kline_fill(self, symbol: str) -> tuple[bool, str]:
        fetcher = KlineFetcher(self._root)
        try:
            fetcher.update(symbol)
            return True, ""
        except Exception as exc:
            text = str(exc).lower()
            if "429" in text or "rate" in text:
                return False, "rate_limit"
            if "timeout" in text:
                return False, "timeout"
            return False, f"api_error:{type(exc).__name__}"

    def _load_kline_local(self, symbol: str) -> pd.DataFrame:
        symbol_file = symbol.replace(".", "_") + ".parquet"
        base = self._root / "kline"
        if not base.exists():
            return pd.DataFrame()
        frames: list[pd.DataFrame] = []
        for month_dir in sorted(base.iterdir()):
            p = month_dir / symbol_file
            if p.exists():
                try:
                    frames.append(pd.read_parquet(p))
                except Exception as exc:
                    logger.warning("kline read failed: %s (%s)", p, exc)
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)

    @staticmethod
    def _latest_date(df: pd.DataFrame, col: str) -> date | None:
        if df is None or df.empty or col not in df.columns:
            return None
        ts = pd.to_datetime(df[col], errors="coerce").dropna()
        if ts.empty:
            return None
        return ts.max().date()

    @staticmethod
    def _df_date_range(df: pd.DataFrame) -> str:
        if df is None or df.empty or "date" not in df.columns:
            return ""
        ts = pd.to_datetime(df["date"], errors="coerce").dropna()
        if ts.empty:
            return ""
        return f"{ts.min().date().isoformat()}..{ts.max().date().isoformat()}"

    @staticmethod
    def _missing_tail_range(df: pd.DataFrame, target_end: date) -> str:
        if df is None or df.empty or "date" not in df.columns:
            return f"N/A..{target_end.isoformat()}"
        ts = pd.to_datetime(df["date"], errors="coerce").dropna()
        if ts.empty:
            return f"N/A..{target_end.isoformat()}"
        latest = ts.max().date()
        return f"{(latest + timedelta(days=1)).isoformat()}..{target_end.isoformat()}"

    def _effective_market_end(self) -> date:
        now = datetime.now(_CST)
        target = now.date() if now.time() >= datetime.strptime("16:00", "%H:%M").time() else (now.date() - timedelta(days=1))
        while target.weekday() >= 5:
            target -= timedelta(days=1)
        return target

    def _ensure_meta_tables(self) -> None:
        con = sqlite3.connect(str(self._meta_db))
        try:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS data_gaps (
                    dataset      TEXT NOT NULL,
                    item_key     TEXT NOT NULL,
                    missing_range TEXT,
                    status       TEXT NOT NULL DEFAULT 'open',
                    last_error   TEXT,
                    updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (dataset, item_key)
                );

                CREATE TABLE IF NOT EXISTS data_repair_runs (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts            TEXT NOT NULL,
                    dataset       TEXT NOT NULL,
                    item_key      TEXT NOT NULL,
                    action        TEXT NOT NULL,
                    degraded      INTEGER NOT NULL,
                    reason_code   TEXT,
                    local_range   TEXT,
                    missing_range TEXT,
                    api_endpoint  TEXT,
                    api_calls_est INTEGER,
                    api_calls_actual INTEGER,
                    llm_provider  TEXT,
                    token_est     INTEGER,
                    token_actual  INTEGER,
                    cost_est_usd  REAL,
                    duration_ms   INTEGER,
                    error         TEXT,
                    meta_json     TEXT
                );
                """
            )
            con.commit()
        finally:
            con.close()

    def _upsert_gap(self, dataset: str, key: str, missing_range: str, error: str) -> None:
        con = sqlite3.connect(str(self._meta_db))
        try:
            con.execute(
                """
                INSERT INTO data_gaps (dataset, item_key, missing_range, status, last_error, updated_at)
                VALUES (?, ?, ?, 'open', ?, CURRENT_TIMESTAMP)
                ON CONFLICT(dataset, item_key) DO UPDATE SET
                    missing_range = excluded.missing_range,
                    status = 'open',
                    last_error = excluded.last_error,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (dataset, key, missing_range, error),
            )
            con.commit()
        finally:
            con.close()

    def _resolve_gap(self, dataset: str, key: str) -> None:
        con = sqlite3.connect(str(self._meta_db))
        try:
            con.execute(
                """
                INSERT INTO data_gaps (dataset, item_key, status, updated_at)
                VALUES (?, ?, 'resolved', CURRENT_TIMESTAMP)
                ON CONFLICT(dataset, item_key) DO UPDATE SET
                    status = 'resolved',
                    updated_at = CURRENT_TIMESTAMP
                """,
                (dataset, key),
            )
            con.commit()
        finally:
            con.close()

    def _record_report(self, report: BackfillReport, start_ts: float) -> None:
        report.duration_ms = int((time.perf_counter() - start_ts) * 1000)
        con = sqlite3.connect(str(self._meta_db))
        try:
            con.execute(
                """
                INSERT INTO data_repair_runs (
                    ts, dataset, item_key, action, degraded, reason_code, local_range, missing_range,
                    api_endpoint, api_calls_est, api_calls_actual, llm_provider, token_est, token_actual,
                    cost_est_usd, duration_ms, error, meta_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report.ts,
                    report.dataset,
                    report.key,
                    report.action,
                    1 if report.degraded else 0,
                    report.reason_code,
                    report.local_range,
                    report.missing_range,
                    report.api_endpoint,
                    report.api_calls_est,
                    report.api_calls_actual,
                    report.llm_provider,
                    report.token_est,
                    report.token_actual,
                    report.cost_est_usd,
                    report.duration_ms,
                    report.error,
                    json.dumps(report.meta, ensure_ascii=False),
                ),
            )
            con.commit()
        finally:
            con.close()

        if report.action != "hit_local" or report.degraded:
            logger.warning("data autofill report: %s", self.format_report(report))
        else:
            logger.debug("data autofill report: %s", self.format_report(report))
