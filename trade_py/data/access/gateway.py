from __future__ import annotations

import json
import hashlib
from io import BytesIO
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
from trade_py.data.paths import KLINE_DIR

logger = logging.getLogger(__name__)

_CST = timezone(timedelta(hours=8))


class DataGateway:
    """Unified data access layer.

    Behavior contract:
    - Kline, fund-flow, and sentiment readers may use explicit repair behavior.
    - Cross-asset reads are local-only and never trigger fetch or persistence.
    - Metadata storage is initialized lazily by readers that record repair work.
    """

    def __init__(self, data_root: str | Path = "data", policy: ReadPolicy | None = None) -> None:
        self._root = Path(data_root)
        self._policy = policy or ReadPolicy()
        from trade_py.db.trade_db import _find_db_path

        self._meta_db = _find_db_path(self._root)
        self._meta_tables_ready = False

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

    # Mapping of legacy get_cross_asset(name) keys to new layout locations.
    # Legacy fallback paths are checked in order if the canonical file is missing.

    def _resolve_cross_asset_path(self, name: str) -> Path:
        """Return the best available parquet path for a legacy cross_asset name.

        Checks the canonical new-layout path first (market/crypto, market/fx,
        market/commodity), then falls back to legacy market/cross_asset/ and
        finally <root>/cross_asset/ for backwards compatibility.
        """
        # Use pure path construction here: this is a read path and must not call
        # directory helpers that create canonical folders on a cache miss.
        name_map: dict[str, tuple] = {
            "btc":    ("crypto",    "btc.parquet",     [
                Path("market") / "cross_asset" / "crypto" / "btc.parquet",
                Path("market") / "cross_asset" / "btc.parquet",
                Path("cross_asset") / "btc.parquet",
            ]),
            "eth":    ("crypto",    "eth.parquet",     [
                Path("market") / "cross_asset" / "crypto" / "eth.parquet",
                Path("market") / "cross_asset" / "eth.parquet",
                Path("cross_asset") / "eth.parquet",
            ]),
            "sol":    ("crypto",    "sol.parquet",     [
                Path("market") / "cross_asset" / "crypto" / "sol.parquet",
                Path("market") / "cross_asset" / "sol.parquet",
                Path("cross_asset") / "sol.parquet",
            ]),
            "bnb":    ("crypto",    "bnb.parquet",     [
                Path("market") / "cross_asset" / "crypto" / "bnb.parquet",
                Path("market") / "cross_asset" / "bnb.parquet",
                Path("cross_asset") / "bnb.parquet",
            ]),
            "xrp":    ("crypto",    "xrp.parquet",     [
                Path("market") / "cross_asset" / "crypto" / "xrp.parquet",
                Path("market") / "cross_asset" / "xrp.parquet",
                Path("cross_asset") / "xrp.parquet",
            ]),
            "fear_greed": ("crypto", "fear_greed.parquet", [
                Path("market") / "cross_asset" / "crypto" / "fear_greed.parquet",
                Path("market") / "cross_asset" / "fear_greed.parquet",
            ]),
            "fx":     ("fx",        "usdcnh.parquet",  [
                Path("market") / "cross_asset" / "fx_cnh.parquet",
                Path("cross_asset") / "fx_cnh.parquet",
                Path("market") / "cross_asset" / "fx_usdcnh.parquet",
            ]),
            "fx_cnh": ("fx",        "usdcnh.parquet",  [
                Path("market") / "cross_asset" / "fx_cnh.parquet",
                Path("cross_asset") / "fx_cnh.parquet",
            ]),
            "gold":   ("commodity", "gold.parquet",    [
                Path("market") / "cross_asset" / "gold.parquet",
                Path("cross_asset") / "gold.parquet",
            ]),
        }
        spec = name_map.get(name)
        if spec is None:
            # Unknown name — fall back to direct market/cross_asset path.
            return self._root / "market" / "cross_asset" / f"{name}.parquet"
        dataset_dir, fname, legacy_rels = spec
        canonical = self._root / "market" / dataset_dir / fname
        if canonical.is_file():
            return canonical
        for rel in legacy_rels:
            p = self._root / rel
            if p.is_file():
                return p
        # Return canonical path even if missing (caller checks is_file).
        return canonical

    def get_cross_asset(self, name: str) -> tuple[pd.DataFrame, BackfillReport]:
        start_ts = time.perf_counter()
        report = BackfillReport(dataset="cross_asset", key=name)
        path = self._resolve_cross_asset_path(name)

        if not path.is_file():
            frame = pd.DataFrame()
            report.action = "degraded"
            report.degraded = True
            report.reason_code = "no_local_data"
            report.error = f"cross-asset file not found for {name!r}: {path}"
        else:
            try:
                if name == "btc":
                    # BTC pointer file (btc_current.json) lives next to btc.parquet
                    # in the crypto directory; fall back to legacy cross_asset/crypto/.
                    pointer_candidates = [
                        path.parent / "btc_current.json",
                        self._root / "market" / "cross_asset" / "btc_current.json",
                        self._root / "market" / "crypto" / "btc_current.json",
                    ]
                    pointer_path = next((p for p in pointer_candidates if p.is_file()), None)
                    if pointer_path is None:
                        raise ValueError("BTC canonical lineage pointer is missing")
                    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
                    expected_hash = str(pointer.get("canonical_sha256") or "")
                    snapshot = path.read_bytes()
                    digest = hashlib.sha256(snapshot).hexdigest()
                    if len(expected_hash) != 64 or digest != expected_hash:
                        raise ValueError("BTC canonical hash does not match current pointer")
                    frame = pd.read_parquet(BytesIO(snapshot))
                else:
                    frame = pd.read_parquet(path)
                report.local_range = self._df_date_range(frame)
            except Exception as exc:
                frame = pd.DataFrame()
                report.action = "degraded"
                report.degraded = True
                report.reason_code = "read_error"
                report.error = repr(exc)

        report.duration_ms = int((time.perf_counter() - start_ts) * 1000)
        if report.degraded:
            logger.warning("cross-asset read report: %s", self.format_report(report))
        else:
            logger.debug("cross-asset read report: %s", self.format_report(report))
        return frame, report

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
        candidates = (KLINE_DIR(self._root), self._root / "kline")

        for base in candidates:
            flat_path = base / symbol_file
            if flat_path.exists():
                try:
                    return pd.read_parquet(flat_path)
                except Exception as exc:
                    logger.warning("kline flat read failed: %s (%s)", flat_path, exc)

        frames: list[pd.DataFrame] = []
        for base in candidates:
            if not base.exists():
                continue
            for month_dir in sorted(base.glob("20??-??")):
                p = month_dir / symbol_file
                if not p.exists():
                    continue
                try:
                    frames.append(pd.read_parquet(p))
                except Exception as exc:
                    logger.warning("kline monthly read failed: %s (%s)", p, exc)
            if frames:
                break
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
        if self._meta_tables_ready:
            return

        self._meta_db.parent.mkdir(parents=True, exist_ok=True)
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
        self._meta_tables_ready = True

    def _upsert_gap(self, dataset: str, key: str, missing_range: str, error: str) -> None:
        self._ensure_meta_tables()
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
        self._ensure_meta_tables()
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
        self._ensure_meta_tables()
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
