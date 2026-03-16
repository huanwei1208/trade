from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from trade_py.data.market.intraday import TushareIntradayFetcher
from trade_py.db.trade_db import TradeDB

INTRADAY_FACTOR_DEFINITIONS = {
    "rt_ret_1m": {"factor_type": "intraday", "description": "Latest 1-minute return."},
    "rt_ret_5m": {"factor_type": "intraday", "description": "Latest 5-minute return."},
    "rt_ret_open": {"factor_type": "intraday", "description": "Return versus today's first intraday open."},
    "rt_vwap_gap": {"factor_type": "intraday", "description": "Price relative to rolling 20-bar VWAP."},
    "rt_range_5m": {"factor_type": "intraday", "description": "5-bar high-low range scaled by price."},
    "rt_volume_ratio_5_20": {"factor_type": "intraday", "description": "5-bar mean volume divided by 20-bar mean volume."},
    "rt_score": {"factor_type": "intraday", "description": "Blended intraday score using price, volume and latest daily context."},
}


def intraday_factor_registry_rows() -> list[dict]:
    rows: list[dict] = []
    for name, spec in INTRADAY_FACTOR_DEFINITIONS.items():
        rows.append(
            {
                "factor_name": name,
                "factor_type": spec["factor_type"],
                "factor_layer": "feature_store",
                "description": spec["description"],
                "source": "intraday_runtime",
            }
        )
    return rows


def _clip(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, float(value)))


def _resolve_symbols(data_root: str | Path, symbols: list[str] | None, limit: int = 50) -> list[str]:
    explicit = [str(s).strip().upper() for s in (symbols or []) if str(s).strip()]
    if explicit:
        return list(dict.fromkeys(explicit))
    db = TradeDB(data_root)
    watchlist = db.watchlist_get()
    if watchlist:
        return watchlist
    latest = db.signal_suggest(limit=limit, by="model_score")
    return [str(row["symbol"]).strip().upper() for row in latest if str(row.get("symbol") or "").strip()]


def _latest_daily_context(db: TradeDB, symbols: list[str]) -> dict[str, dict[str, float]]:
    if not symbols:
        return {}
    placeholders = ",".join(["?"] * len(symbols))
    rows = db._conn.execute(
        f"""
        WITH latest AS (
            SELECT symbol, MAX(date) AS max_date
            FROM signals
            WHERE symbol IN ({placeholders})
            GROUP BY symbol
        )
        SELECT s.symbol, s.model_score, s.window_score, s.event_kg_score
        FROM signals s
        JOIN latest ON s.symbol = latest.symbol AND s.date = latest.max_date
        """,
        symbols,
    ).fetchall()
    result: dict[str, dict[str, float]] = {}
    for row in rows:
        result[str(row["symbol"])] = {
            "model_score": float(row["model_score"] or 0.0),
            "window_score": float(row["window_score"] or 50.0),
            "event_kg_score": float(row["event_kg_score"] or 0.0),
        }
    return result


def _snapshot_path(data_root: str | Path, as_of: datetime, freq: str) -> Path:
    root = Path(data_root) / "market" / "intraday" / "snapshots" / as_of.strftime("%Y-%m-%d")
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{freq.lower()}_{as_of.strftime('%H%M%S')}.parquet"


def compute_intraday_snapshot(
    data_root: str | Path = "data",
    *,
    symbols: list[str] | None = None,
    freq: str = "1MIN",
    lookback_bars: int = 30,
    top: int = 20,
    persist_factors: bool = True,
) -> dict[str, Any]:
    resolved = _resolve_symbols(data_root, symbols)
    fetcher = TushareIntradayFetcher(data_root)
    db = TradeDB(data_root)
    context = _latest_daily_context(db, resolved)
    rows: list[dict[str, Any]] = []
    factor_rows: list[dict[str, Any]] = []
    as_of = datetime.now()

    for symbol in resolved:
        frame = fetcher.load(symbol, freq=freq)
        if frame.empty:
            continue
        frame = frame.sort_values("timestamp").reset_index(drop=True)
        latest_date = str(frame.iloc[-1]["date"])
        day_frame = frame[frame["date"] == latest_date].copy()
        if day_frame.empty:
            continue

        latest = day_frame.iloc[-1]
        recent_5 = day_frame.tail(min(5, len(day_frame)))
        recent_20 = day_frame.tail(min(20, len(day_frame)))
        current_close = float(latest["close"])
        open_price = float(day_frame.iloc[0]["open"])
        prev_close_1 = float(day_frame.iloc[-2]["close"]) if len(day_frame) >= 2 else open_price
        prev_close_5 = float(day_frame.iloc[-6]["close"]) if len(day_frame) >= 6 else open_price
        vol_mean_5 = float(recent_5["volume"].mean()) if not recent_5.empty else 0.0
        vol_mean_20 = float(recent_20["volume"].mean()) if not recent_20.empty else 0.0
        vwap = (
            float((recent_20["close"] * recent_20["volume"]).sum()) / float(recent_20["volume"].sum())
            if float(recent_20["volume"].sum()) > 0
            else current_close
        )
        ret_1m = (current_close / prev_close_1 - 1.0) if prev_close_1 else 0.0
        ret_5m = (current_close / prev_close_5 - 1.0) if prev_close_5 else 0.0
        ret_open = (current_close / open_price - 1.0) if open_price else 0.0
        vwap_gap = (current_close / vwap - 1.0) if vwap else 0.0
        range_5m = ((float(recent_5["high"].max()) - float(recent_5["low"].min())) / current_close) if current_close else 0.0
        volume_ratio = (vol_mean_5 / vol_mean_20) if vol_mean_20 > 0 else 0.0

        daily = context.get(symbol, {})
        window_score = float(daily.get("window_score", 50.0))
        event_kg_score = float(daily.get("event_kg_score", 0.0))
        model_score = float(daily.get("model_score", 0.0))

        rt_score = (
            50.0
            + _clip(ret_5m * 1800.0, -18.0, 18.0)
            + _clip(vwap_gap * 1500.0, -15.0, 15.0)
            + _clip((volume_ratio - 1.0) * 12.0, -10.0, 18.0)
            + _clip((window_score - 50.0) * 0.15, -7.5, 7.5)
            + _clip(event_kg_score * 10.0, -8.0, 8.0)
            + _clip(model_score * 8.0, -8.0, 8.0)
        )

        meta = db.instrument_lookup(symbol) or {"name": "", "market_name": ""}
        rows.append(
            {
                "symbol": symbol,
                "name": meta.get("name", ""),
                "market_name": meta.get("market_name", ""),
                "date": latest_date,
                "timestamp": str(latest["timestamp"]),
                "rt_ret_1m": ret_1m,
                "rt_ret_5m": ret_5m,
                "rt_ret_open": ret_open,
                "rt_vwap_gap": vwap_gap,
                "rt_range_5m": range_5m,
                "rt_volume_ratio_5_20": volume_ratio,
                "window_score": window_score,
                "event_kg_score": event_kg_score,
                "model_score": model_score,
                "rt_score": rt_score,
            }
        )
        if persist_factors:
            for factor_name in INTRADAY_FACTOR_DEFINITIONS:
                factor_rows.append(
                    {
                        "date": latest_date,
                        "symbol": symbol,
                        "factor_name": factor_name,
                        "factor_type": "intraday",
                        "value": float(rows[-1][factor_name]),
                    }
                )

    snapshot = pd.DataFrame(rows)
    if snapshot.empty:
        return {"rows": [], "snapshot_path": None, "symbols": resolved, "as_of": as_of.isoformat()}

    snapshot = snapshot.sort_values("rt_score", ascending=False).reset_index(drop=True)
    path = _snapshot_path(data_root, as_of, freq)
    snapshot.to_parquet(path, index=False)

    if persist_factors and factor_rows:
        db.factor_registry_upsert_batch(intraday_factor_registry_rows())
        db.factor_upsert_batch(factor_rows)

    return {
        "rows": snapshot.head(max(1, int(top))).to_dict(orient="records"),
        "row_count": len(snapshot),
        "snapshot_path": str(path),
        "symbols": resolved,
        "as_of": as_of.isoformat(),
    }
