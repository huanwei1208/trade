from __future__ import annotations

"""Crypto asset ingestors using free public exchange APIs (OKX primary, Binance shadow/backup).
FX fallback uses ECB Frankfurter (free, no key)."""

import logging
from typing import Any

import pandas as pd

from trade_py.data.ingest.base import AssetIngestor
from trade_py.data.market.cross_asset.providers import (
    OkxDailyProvider,
    BinanceDailyProvider,
)

logger = logging.getLogger(__name__)


class OKXCryptoIngestor(AssetIngestor):
    """OKX public market data ingestor (100% free, no API key required)."""

    name = "okx"

    def fetch(
        self,
        asset: dict,
        *,
        days: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        symbol = asset["symbol"]
        quote = asset.get("quote_asset", "USDT")
        fetch_days = days or asset.get("backfill_days", 730)

        if start_date is not None:
            start_ts = pd.Timestamp(start_date, tz="UTC")
            end_ts = pd.Timestamp(end_date or "now", tz="UTC")
            fetch_days = max(1, (end_ts.normalize() - start_ts.normalize()).days + 1)

        provider = OkxDailyProvider(base_asset=symbol, quote_asset=quote)
        capture = provider.capture(
            days=fetch_days,
            fetched_at=pd.Timestamp.now(tz="UTC"),
            run_id=f"ingest-okx-{symbol.lower()}",
        )

        final = capture.final_rows
        if final.empty:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

        out = final.assign(date=final["bar_open_at"].dt.tz_localize(None))
        result = out[["date", "open", "high", "low", "close", "volume"]].reset_index(drop=True)

        if start_date is not None:
            result = result[result["date"] >= pd.Timestamp(start_date)]
        if end_date is not None:
            result = result[result["date"] <= pd.Timestamp(end_date)]

        return result.reset_index(drop=True)


class BinanceCryptoIngestor(AssetIngestor):
    """Binance public klines ingestor (100% free, no API key required). Used as shadow/backup."""

    name = "binance"

    def fetch(
        self,
        asset: dict,
        *,
        days: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        symbol = asset["symbol"]
        quote = asset.get("quote_asset", "USDT")
        fetch_days = days or asset.get("backfill_days", 730)

        if start_date is not None:
            start_ts = pd.Timestamp(start_date, tz="UTC")
            end_ts = pd.Timestamp(end_date or "now", tz="UTC")
            fetch_days = max(1, (end_ts.normalize() - start_ts.normalize()).days + 1)

        provider = BinanceDailyProvider(base_asset=symbol, quote_asset=quote)
        capture = provider.capture(
            days=fetch_days,
            fetched_at=pd.Timestamp.now(tz="UTC"),
            run_id=f"ingest-binance-{symbol.lower()}",
        )

        final = capture.final_rows
        if final.empty:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

        out = final.assign(date=final["bar_open_at"].dt.tz_localize(None))
        result = out[["date", "open", "high", "low", "close", "volume"]].reset_index(drop=True)

        if start_date is not None:
            result = result[result["date"] >= pd.Timestamp(start_date)]
        if end_date is not None:
            result = result[result["date"] <= pd.Timestamp(end_date)]

        return result.reset_index(drop=True)


class AkshareCrossAssetIngestor(AssetIngestor):
    """Akshare-based ingestor for gold, FX, and other cross-asset data."""

    name = "akshare"

    def fetch(
        self,
        asset: dict,
        *,
        days: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        import akshare as ak

        asset_id = asset["asset_id"]
        symbol = asset["symbol"]

        if asset_id == "commodity.gold" or symbol == "Au99.99":
            df_raw = ak.spot_hist_sge(symbol="Au99.99")
            df = df_raw.rename(columns={
                "date": "date", "open": "open", "high": "high", "low": "low", "close": "close",
            })[["date", "open", "high", "low", "close"]]
            df["volume"] = pd.NA
        elif asset_id == "fx.USDCNH" or symbol == "USDCNH":
            df = self._fetch_usdcnh_with_fallback(days=days, start_date=start_date)
        else:
            raise ValueError(f"Unsupported akshare asset: {asset_id}")

        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)

        if start_date is not None:
            df = df[df["date"] >= pd.Timestamp(start_date)]
        if end_date is not None:
            df = df[df["date"] <= pd.Timestamp(end_date)]

        for col in ["open", "high", "low", "close"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        return df.reset_index(drop=True)

    def _fetch_usdcnh_with_fallback(
        self,
        *,
        days: int | None = None,
        start_date: str | None = None,
    ) -> pd.DataFrame:
        """Fetch USD/CNH daily rates. Try EastMoney first; fall back to ECB Frankfurter on failure.

        EastMoney push2his may block datacenter IPs. Frankfurter (ECB reference rates via CNY proxy)
        is authoritative, free, key-less, and provides daily rates back to 1999.
        Only close price is used downstream (5d momentum for risk-on/off), so open=high=low=close.
        """
        try:
            import akshare as ak
            df_raw = ak.forex_hist_em(symbol="USDCNH")
            df = df_raw.rename(columns={
                "日期": "date", "今开": "open", "最高": "high", "最低": "low", "最新价": "close",
            })[["date", "open", "high", "low", "close"]]
            df["volume"] = pd.NA
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)
            for col in ["open", "high", "low", "close"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            if start_date is not None:
                df = df[df["date"] >= pd.Timestamp(start_date)]
            logger.info("USDCNH: EastMoney fetch succeeded, %d rows", len(df))
            return df.reset_index(drop=True)
        except Exception as exc:
            logger.warning("USDCNH: EastMoney fetch failed (%s), falling back to ECB Frankfurter", exc)

        return self._fetch_usdcny_frankfurter(days=days, start_date=start_date)

    @staticmethod
    def _fetch_usdcny_frankfurter(
        *,
        days: int | None = None,
        start_date: str | None = None,
    ) -> pd.DataFrame:
        """Fetch USD/CNY daily reference rates from the ECB Frankfurter API (free, no key).

        https://www.frankfurter.app/docs/  —  ECB reference rates, updated ~16:00 CET daily.
        Returns columns: date, open, high, low, close, volume (OHLC all set to close since ECB
        publishes a single reference rate per day; volume=NA for FX spot).
        Weekend/holiday gaps are forward-filled from the last published rate (standard FX convention).
        """
        import json
        import urllib.request
        import urllib.error

        if start_date is not None:
            start = pd.Timestamp(start_date)
        elif days is not None:
            start = pd.Timestamp.now().normalize() - pd.Timedelta(days=days)
        else:
            start = pd.Timestamp("2010-01-01")

        start_str = start.strftime("%Y-%m-%d")
        url = f"https://api.frankfurter.app/{start_str}..?from=USD&to=CNY"
        req = urllib.request.Request(url, headers={"User-Agent": "trade-data/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))

        rates = payload.get("rates", {})
        if not rates:
            raise RuntimeError(f"Frankfurter returned empty rates for URL: {url}")

        rows = []
        for date_str, rate_map in sorted(rates.items()):
            cny = rate_map.get("CNY")
            if cny is None:
                continue
            ts = pd.Timestamp(date_str)
            rows.append({
                "date": ts,
                "open": cny,
                "high": cny,
                "low": cny,
                "close": cny,
                "volume": pd.NA,
            })

        df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
        if df.empty:
            raise RuntimeError("Frankfurter produced no valid rows")

        all_days = pd.date_range(df["date"].min(), df["date"].max(), freq="D")
        df = df.set_index("date").reindex(all_days).ffill().reset_index().rename(columns={"index": "date"})

        for col in ["open", "high", "low", "close"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        logger.info("USDCNH: Frankfurter (ECB) produced %d rows (%s to %s)",
                    len(df), df["date"].min().date(), df["date"].max().date())
        return df.reset_index(drop=True)


# Ingestor registry by venue name
INGESTOR_REGISTRY: dict[str, AssetIngestor] = {
    "okx": OKXCryptoIngestor(),
    "binance": BinanceCryptoIngestor(),
    "sge": AkshareCrossAssetIngestor(),
    "eastmoney": AkshareCrossAssetIngestor(),
}


def get_ingestor(venue: str) -> AssetIngestor:
    """Get ingestor for a given venue name."""
    if venue not in INGESTOR_REGISTRY:
        raise ValueError(f"No ingestor registered for venue: {venue}. Available: {list(INGESTOR_REGISTRY.keys())}")
    return INGESTOR_REGISTRY[venue]
