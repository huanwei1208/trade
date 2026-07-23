"""Crypto market factor group: Fear & Greed Index + cross-asset crypto OHLC features.

These are market-wide crypto factors, applied as cross-sectional context for
both crypto symbols and as macro context for the broader market.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from trade_py.factors.groups._base import FactorGroupResult

logger = logging.getLogger(__name__)

CRYPTO_FEATURE_COLS: list[str] = [
    "crypto_fear_greed_value",
    "crypto_fear_greed_zscore",
    "crypto_fear_greed_delta_1d",
    "crypto_fear_greed_delta_7d",
    "crypto_btc_return_1d",
    "crypto_btc_return_5d",
    "crypto_btc_volatility_5d",
    "crypto_eth_return_1d",
    "crypto_eth_btc_beta",
    "crypto_market_sentiment",
    "crypto_news_volume",
    "crypto_news_urgent_count",
]

_CRYPTO_SYMBOLS = ("btc", "eth", "sol", "bnb", "xrp")


def build_crypto_group(
    data_root: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> FactorGroupResult:
    """Build crypto-asset factors from fear_greed and crypto OHLC data.

    Returns a FactorGroupResult with one row per date (symbol='_CRYPTO_MARKET_'),
    suitable for merging into the broader feature frame as market-wide context.

    Checks canonical market/crypto/ path first, then falls back to legacy
    market/cross_asset/crypto/ and market/cross_asset/ layouts.
    """
    root = Path(data_root)
    canonical_dir = root / "market" / "crypto"
    legacy_crypto_dir = root / "market" / "cross_asset" / "crypto"
    legacy_cross_dir = root / "market" / "cross_asset"
    # Choose the directory that contains fear_greed.parquet; prefer canonical.
    if (canonical_dir / "fear_greed.parquet").exists():
        crypto_dir = canonical_dir
    elif (legacy_crypto_dir / "fear_greed.parquet").exists():
        crypto_dir = legacy_crypto_dir
    else:
        crypto_dir = canonical_dir  # will fail missing-file path below
    news_dir = root / "news" / "silver"

    fng_path = crypto_dir / "fear_greed.parquet"
    if not fng_path.exists():
        logger.debug("crypto_group: fear_greed.parquet not found at %s", fng_path)
        return FactorGroupResult.empty("crypto", CRYPTO_FEATURE_COLS)

    try:
        import duckdb
        con = duckdb.connect()

        fng_df = con.execute(f"""
            SELECT CAST(timestamp AS BIGINT) AS ts, value, classification
            FROM read_parquet('{fng_path}')
            ORDER BY ts
        """).df()
        con.close()
    except Exception as exc:
        logger.debug("crypto_group: fear_greed load failed: %s", exc)
        return FactorGroupResult.empty("crypto", CRYPTO_FEATURE_COLS)

    if fng_df.empty:
        return FactorGroupResult.empty("crypto", CRYPTO_FEATURE_COLS)

    fng_df["date"] = pd.to_datetime(fng_df["ts"], unit="s").dt.date.astype(str)
    fng_df = fng_df.drop_duplicates(subset=["date"], keep="last").sort_values("date")
    fng_df["value"] = pd.to_numeric(fng_df["value"], errors="coerce")
    fng_mean = fng_df["value"].mean()
    fng_std = fng_df["value"].std() or 1.0
    fng_df["fng_zscore"] = (fng_df["value"] - fng_mean) / fng_std
    fng_df["fng_delta_1d"] = fng_df["value"].diff(1)
    fng_df["fng_delta_7d"] = fng_df["value"].diff(7)

    ohlc: dict[str, pd.DataFrame] = {}
    for sym in _CRYPTO_SYMBOLS:
        candidates = [
            crypto_dir / f"{sym}.parquet",
            legacy_cross_dir / f"{sym}.parquet",
            root / "cross_asset" / f"{sym}.parquet",
        ]
        path = next((p for p in candidates if p.exists()), candidates[0])
        if not path.exists():
            continue
        try:
            import duckdb
            con = duckdb.connect()
            df = con.execute(f"""
                SELECT date, close FROM read_parquet('{path}')
                ORDER BY date
            """).df()
            con.close()
            df["date"] = df["date"].astype(str)
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            ohlc[sym] = df
        except Exception as exc:
            logger.debug("crypto_group: %s load failed: %s", sym, exc)

    news_counts: pd.DataFrame | None = None
    if news_dir.exists():
        try:
            import duckdb
            con = duckdb.connect()
            news_glob = str(news_dir / "*.parquet")
            nc = con.execute(f"""
                SELECT date, COUNT(*) AS news_volume,
                       SUM(CASE WHEN is_urgent THEN 1 ELSE 0 END) AS urgent_count,
                       AVG(sentiment_score) AS news_sentiment
                FROM read_parquet('{news_glob}', union_by_name=true)
                GROUP BY date
                ORDER BY date
            """).df()
            con.close()
            if not nc.empty:
                news_counts = nc
        except Exception as exc:
            logger.debug("crypto_group: news load failed: %s", exc)

    result = fng_df[["date", "value", "fng_zscore", "fng_delta_1d", "fng_delta_7d"]].copy()
    result = result.rename(columns={
        "value": "crypto_fear_greed_value",
        "fng_zscore": "crypto_fear_greed_zscore",
        "fng_delta_1d": "crypto_fear_greed_delta_1d",
        "fng_delta_7d": "crypto_fear_greed_delta_7d",
    })

    for sym in _CRYPTO_SYMBOLS:
        if sym not in ohlc:
            continue
        odf = ohlc[sym].copy()
        odf[f"{sym}_ret1d"] = odf["close"].pct_change(1)
        odf[f"{sym}_ret5d"] = odf["close"].pct_change(5)
        odf[f"{sym}_vol5d"] = odf[f"{sym}_ret1d"].rolling(5, min_periods=2).std()
        result = result.merge(
            odf[["date", f"{sym}_ret1d", f"{sym}_ret5d", f"{sym}_vol5d"]],
            on="date", how="left",
        )

    if news_counts is not None:
        result = result.merge(news_counts, on="date", how="left")
        result["crypto_news_volume"] = result.get("news_volume", 0).fillna(0).astype(int)
        result["crypto_news_urgent_count"] = result.get("urgent_count", 0).fillna(0).astype(int)
        result["crypto_market_sentiment"] = result.get("news_sentiment", 0.0).fillna(0.0)
    else:
        result["crypto_news_volume"] = 0
        result["crypto_news_urgent_count"] = 0
        result["crypto_market_sentiment"] = 0.0

    rename_map = {"btc_ret1d": "crypto_btc_return_1d", "btc_ret5d": "crypto_btc_return_5d",
                  "btc_vol5d": "crypto_btc_volatility_5d", "eth_ret1d": "crypto_eth_return_1d"}
    result = result.rename(columns=rename_map)

    if "eth_ret1d" in result.columns and "btc_ret1d" in result.columns:
        eth_ret = result["eth_ret1d"] if "eth_ret1d" in result.columns else None
        btc_ret = result.get("btc_ret1d")
        if eth_ret is not None and btc_ret is not None:
            cov = eth_ret.rolling(20, min_periods=5).cov(btc_ret)
            var = btc_ret.rolling(20, min_periods=5).var()
            result["crypto_eth_btc_beta"] = (cov / var.replace(0, float("nan"))).fillna(1.0)
        else:
            result["crypto_eth_btc_beta"] = 1.0
    else:
        result["crypto_eth_btc_beta"] = 1.0

    for col in CRYPTO_FEATURE_COLS:
        if col not in result.columns:
            result[col] = 0.0 if col != "crypto_fear_greed_zscore" else 0.0

    result["symbol"] = "_CRYPTO_MARKET_"
    result = result[["date", "symbol"] + CRYPTO_FEATURE_COLS].ffill().fillna(0.0)

    if start_date:
        result = result[result["date"] >= start_date]
    if end_date:
        result = result[result["date"] <= end_date]

    return FactorGroupResult(
        group_name="crypto",
        values=result,
        expected_cols=CRYPTO_FEATURE_COLS,
        missing=[],
        used_defaults=[],
        coverage=round(float((result["crypto_fear_greed_value"] > 0).mean()), 4),
        source_date_range=(result["date"].min(), result["date"].max()) if not result.empty else None,
    )
