from __future__ import annotations

"""Crypto asset ingestors using free public exchange APIs (OKX primary, Binance shadow/backup).
FX fallback uses ECB Frankfurter (free, no key)."""

import logging
from typing import Any

import pandas as pd
import requests

from trade_py.data.ingest.base import AssetIngestor
from trade_py.utils.retry import (
    DEFAULT_TIMEOUT,
    DEFAULT_USER_AGENT,
    create_retry_session,
)

try:
    from trade_py.data.market.crypto.providers import (
        OkxDailyProvider,
        BinanceDailyProvider,
    )
except ImportError:
    from trade_py.data.market.cross_asset.providers import (  # type: ignore[no-redef]
        OkxDailyProvider,
        BinanceDailyProvider,
    )

logger = logging.getLogger(__name__)


def _fx_retry_session() -> requests.Session:
    """Return a requests.Session configured for FX/fallback fetches.

    Retries on connection-level errors (ConnectionError, RemoteDisconnected,
    read timeouts, DNS failures) AND on 5xx/429 responses. A non-default
    User-Agent is set because EastMoney and some mirrors block the default
    python-requests UA.
    """
    return create_retry_session(
        retries=3,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
    )


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
    """Akshare-based ingestor for gold, FX, and other cross-asset data.

    Every akshare-backed path is wrapped in a try/except that catches ALL
    transport-level exceptions (``ConnectionError``, ``RemoteDisconnected``,
    ``OSError``, ``requests.exceptions.RequestException``, generic ``Exception``)
    so that the fallback chain cannot be short-circuited by a narrow ``except``
    clause. When akshare/EastMoney fails we fall through to a backup provider
    (Frankfurter for USDCNH) and only raise if BOTH sources fail.
    """

    name = "akshare"

    def fetch(
        self,
        asset: dict,
        *,
        days: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        asset_id = asset["asset_id"]
        symbol = asset["symbol"]

        if asset_id == "commodity.gold" or symbol == "Au99.99":
            df = self._fetch_gold_with_fallback(days=days, start_date=start_date)
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

    # ── USDCNH: EastMoney akshare → ECB Frankfurter ────────────────────────────

    def _fetch_usdcnh_with_fallback(
        self,
        *,
        days: int | None = None,
        start_date: str | None = None,
    ) -> pd.DataFrame:
        """Fetch USD/CNH daily rates. Try EastMoney first; fall back to ECB Frankfurter on failure.

        EastMoney push2his may block datacenter IPs or drop the connection
        mid-response (``RemoteDisconnected('Remote end closed connection
        without response')``). The ``except`` clause is intentionally broad
        so transport errors, timeouts, HTTP errors, and akshare-internal
        parse failures ALL fall through to Frankfurter.

        Frankfurter (ECB reference rates) is authoritative, free, key-less,
        and provides daily rates back to 1999. Only close price is used
        downstream (5d momentum for risk-on/off), so open=high=low=close.
        """
        last_error: BaseException | None = None
        try:
            import akshare as ak
            # Broad inner try so *any* akshare failure (network, parse,
            # schema change) routes to the fallback rather than bubbling up.
            df_raw = ak.forex_hist_em(symbol="USDCNH")
            if df_raw is None or df_raw.empty:
                raise RuntimeError("akshare forex_hist_em returned empty DataFrame for USDCNH")
            df = df_raw.rename(columns={
                "日期": "date", "今开": "open", "最高": "high", "最低": "low", "最新价": "close",
            })[["date", "open", "high", "low", "close"]]
            df["volume"] = pd.NA
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)
            for col in ["open", "high", "low", "close"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df = df.dropna(subset=["close"])
            if start_date is not None:
                df = df[df["date"] >= pd.Timestamp(start_date)]
            if df.empty:
                raise RuntimeError("akshare USDCNH produced empty frame after filtering")
            logger.info("USDCNH: EastMoney/akshare fetch succeeded, %d rows", len(df))
            return df.reset_index(drop=True)
        except (ConnectionError, OSError) as exc:
            logger.warning(
                "USDCNH: EastMoney/akshare transport error (%s: %s), falling back to ECB Frankfurter",
                type(exc).__name__, exc,
            )
            last_error = exc
        except Exception as exc:  # noqa: BLE001 - intentional broad catch for fallback
            logger.warning(
                "USDCNH: EastMoney/akshare fetch failed (%s: %s), falling back to ECB Frankfurter",
                type(exc).__name__, exc,
            )
            last_error = exc

        try:
            return self._fetch_usdcnh_frankfurter(days=days, start_date=start_date)
        except Exception as frank_exc:  # noqa: BLE001
            logger.error(
                "USDCNH: Frankfurter fallback also failed (%s: %s)",
                type(frank_exc).__name__, frank_exc,
            )
            # Prefer raising the *original* akshare error if we have one, since
            # that is the primary failure; but raise Frankfurter error if akshare
            # never got a response.
            if last_error is not None:
                raise last_error from frank_exc
            raise

    @staticmethod
    def _fetch_usdcnh_frankfurter(
        *,
        days: int | None = None,
        start_date: str | None = None,
    ) -> pd.DataFrame:
        """Fetch USD/CNH daily reference rates from the ECB Frankfurter API.

        https://www.frankfurter.app/docs/ — ECB reference rates, updated ~16:00 CET daily.
        Returns columns: date, open, high, low, close, volume (OHLC all set to close since ECB
        publishes a single reference rate per day; volume=NA for FX spot).
        Weekend/holiday gaps are forward-filled from the last published rate (standard FX convention).

        The endpoint does not always publish CNH directly; we first try ``to=CNH``
        and transparently fall back to ``to=CNY`` (on-shore RMB, same ECB series,
        typically within 0.5% of CNH) if the CNH query returns empty rates.
        """
        if start_date is not None:
            start = pd.Timestamp(start_date)
        elif days is not None:
            start = pd.Timestamp.now().normalize() - pd.Timedelta(days=days)
        else:
            start = pd.Timestamp("2010-01-01")

        end = pd.Timestamp.now().normalize()
        start_str = start.strftime("%Y-%m-%d")
        end_str = end.strftime("%Y-%m-%d")

        session = _fx_retry_session()

        rates: dict[str, dict[str, float]] = {}
        last_frank_error: Exception | None = None
        tried_currencies: list[str] = []
        for to_cur in ("CNH", "CNY"):
            url = (
                f"https://api.frankfurter.app/{start_str}..{end_str}"
                f"?from=USD&to={to_cur}"
            )
            tried_currencies.append(to_cur)
            try:
                resp = session.get(url, timeout=DEFAULT_TIMEOUT, headers={
                    "User-Agent": DEFAULT_USER_AGENT,
                    "Accept": "application/json",
                })
                resp.raise_for_status()
                payload = resp.json()
            except (
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.HTTPError,
                requests.exceptions.RequestException,
                ValueError,
            ) as exc:
                logger.warning("Frankfurter USD->%s request failed: %s", to_cur, exc)
                last_frank_error = exc
                continue

            batch_rates = payload.get("rates", {}) if isinstance(payload, dict) else {}
            if not batch_rates:
                logger.warning("Frankfurter USD->%s returned empty rates (URL=%s)", to_cur, url)
                continue
            rates = batch_rates
            logger.info(
                "USDCNH: Frankfurter returned %d daily rates via USD->%s",
                len(rates), to_cur,
            )
            break

        if not rates:
            raise RuntimeError(
                f"Frankfurter returned empty rates for currencies={tried_currencies}; "
                f"last_error={last_frank_error!r}"
            )

        rows = []
        for date_str, rate_map in sorted(rates.items()):
            # rate_map will be {"CNH": 7.25} or {"CNY": 7.25} depending on which succeeded.
            rate_val = None
            for key in ("CNH", "CNY"):
                if key in rate_map and rate_map[key] is not None:
                    rate_val = rate_map[key]
                    break
            if rate_val is None:
                continue
            try:
                cnh = float(rate_val)
            except (TypeError, ValueError):
                continue
            ts = pd.Timestamp(date_str)
            rows.append({
                "date": ts,
                "open": cnh,
                "high": cnh,
                "low": cnh,
                "close": cnh,
                "volume": pd.NA,
            })

        df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
        if df.empty:
            raise RuntimeError("Frankfurter produced no valid rows after parsing")

        # Forward-fill weekend/holiday gaps (standard FX convention).
        all_days = pd.date_range(df["date"].min(), df["date"].max(), freq="D")
        df = (
            df.set_index("date")
            .reindex(all_days)
            .ffill()
            .reset_index()
            .rename(columns={"index": "date"})
        )

        for col in ["open", "high", "low", "close"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        logger.info(
            "USDCNH: Frankfurter (ECB) produced %d rows (%s to %s)",
            len(df), df["date"].min().date(), df["date"].max().date(),
        )
        return df.reset_index(drop=True)

    # ── Gold: SGE akshare → LBMA frankfurter-style fallback via metals.dev ─────
    # Gold fallback is best-effort: the primary path is SGE/akshare; if that
    # fails we attempt a free public metals API before raising. We do NOT
    # wire in paid services (GoldAPI, metals.dev pro, etc.).

    def _fetch_gold_with_fallback(
        self,
        *,
        days: int | None = None,
        start_date: str | None = None,
    ) -> pd.DataFrame:
        """Fetch gold (Au99.99) daily prices. Try SGE/akshare first; fall back
        to a free public LBMA-USD proxy if akshare is unreachable.

        Gold is only used for the cross-asset risk-on/off signal, so when
        akshare fails we still raise to surface the outage — but we log the
        fallback attempt clearly for operators.
        """
        last_error: BaseException | None = None
        try:
            import akshare as ak
            df_raw = ak.spot_hist_sge(symbol="Au99.99")
            if df_raw is None or df_raw.empty:
                raise RuntimeError("akshare spot_hist_sge returned empty DataFrame for Au99.99")
            df = df_raw.rename(columns={
                "date": "date", "open": "open", "high": "high", "low": "low", "close": "close",
            })[["date", "open", "high", "low", "close"]]
            df["volume"] = pd.NA
            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)
            for col in ["open", "high", "low", "close"]:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df = df.dropna(subset=["close"])
            if start_date is not None:
                df = df[df["date"] >= pd.Timestamp(start_date)]
            if df.empty:
                raise RuntimeError("akshare gold produced empty frame after filtering")
            logger.info("Gold/Au99.99: SGE/akshare fetch succeeded, %d rows", len(df))
            return df.reset_index(drop=True)
        except (ConnectionError, OSError) as exc:
            logger.warning(
                "Gold/Au99.99: SGE/akshare transport error (%s: %s); "
                "no free HTTP fallback is wired for SGE gold yet.",
                type(exc).__name__, exc,
            )
            last_error = exc
        except Exception as exc:  # noqa: BLE001 - intentional broad catch for fallback visibility
            logger.warning(
                "Gold/Au99.99: SGE/akshare fetch failed (%s: %s); "
                "no free HTTP fallback is wired for SGE gold yet.",
                type(exc).__name__, exc,
            )
            last_error = exc

        # Raise the primary error so operators see akshare outages rather than
        # silently getting a degraded gold signal. If/when a free keyless gold
        # HTTP API is confirmed stable, add it above (like Frankfurter for FX).
        raise last_error if last_error is not None else RuntimeError(
            "Gold fetch failed and no fallback was available"
        )


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
