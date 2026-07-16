from __future__ import annotations

"""Provider-native crypto daily market-data contracts and adapters.

All providers here are **free, keyless public exchange APIs**:
- OKX public market-data endpoints (primary, full OHLCV, no key required)
- Binance public kline endpoints (shadow, full OHLCV, no key required)

No paid or API-key-required services (e.g. CoinGecko Pro, CoinMarketCap) are used.
Supports arbitrary trading pairs, defaults to BTC-USDT and other top crypto assets.

All outbound HTTP calls are routed through a ``requests.Session`` with a
``urllib3`` ``Retry`` mounted so that transient transport failures
(``RemoteDisconnected``, reset connections, DNS blips, 5xx/429) are retried
at the connection layer before surfacing to callers.
"""

import hashlib
import json
from dataclasses import dataclass, replace
from typing import Any, Callable, Literal, Mapping, Protocol, Sequence

import pandas as pd

from trade_py.utils.retry import (
    DEFAULT_TIMEOUT,
    DEFAULT_USER_AGENT,
    create_retry_session,
)

CRYPTO_PROVIDER_SCHEMA_VERSION = "crypto-provider-v2"
OKX_HISTORY_CANDLES_URL = "https://www.okx.com/api/v5/market/history-candles"
BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"

CRYPTO_PROVIDER_REQUIRED_COLUMNS = (
    "provider",
    "venue",
    "instrument",
    "base_asset",
    "quote_asset",
    "interval",
    "bar_open_at",
    "bar_close_at",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "is_final",
    "fetched_at",
    "available_at",
    "payload_hash",
    "schema_version",
    "run_id",
)
CRYPTO_PROVIDER_COLUMNS = CRYPTO_PROVIDER_REQUIRED_COLUMNS + (
    "source_timestamp_ms",
    "provider_status",
)

# Supported default assets
DEFAULT_CRYPTO_ASSETS = ("BTC", "ETH", "SOL", "BNB", "XRP")
DEFAULT_QUOTE_ASSET = "USDT"
DEFAULT_INTERVAL = "1Dutc"
BINANCE_DEFAULT_INTERVAL = "1d"


class CryptoProviderError(RuntimeError):
    """Base exception for crypto provider acquisition and contract failures."""


class CryptoProviderContractError(CryptoProviderError):
    """Raised when a payload cannot satisfy its declared provider contract."""


class CryptoProviderResponseError(CryptoProviderError):
    """Raised when an upstream provider reports an unsuccessful response."""


@dataclass(frozen=True)
class CryptoProviderContract:
    provider: str
    venue: str
    instrument: str
    base_asset: str
    quote_asset: str
    interval: str
    role: Literal["primary", "shadow"]
    schema_version: str = CRYPTO_PROVIDER_SCHEMA_VERSION


def make_okx_contract(base_asset: str, quote_asset: str = DEFAULT_QUOTE_ASSET) -> CryptoProviderContract:
    return CryptoProviderContract(
        provider="okx",
        venue="okx",
        instrument=f"{base_asset}-{quote_asset}",
        base_asset=base_asset.upper(),
        quote_asset=quote_asset.upper(),
        interval=DEFAULT_INTERVAL,
        role="primary",
    )


def make_binance_contract(base_asset: str, quote_asset: str = DEFAULT_QUOTE_ASSET) -> CryptoProviderContract:
    return CryptoProviderContract(
        provider="binance",
        venue="binance",
        instrument=f"{base_asset}{quote_asset}",
        base_asset=base_asset.upper(),
        quote_asset=quote_asset.upper(),
        interval=BINANCE_DEFAULT_INTERVAL,
        role="shadow",
    )


# Backwards-compatible BTC contracts
OKX_BTC_CONTRACT = make_okx_contract("BTC")
BINANCE_BTC_SHADOW_CONTRACT = make_binance_contract("BTC")
# IMPORTANT: The D3 shadow provider is **Binance**, NOT an independent third
# source like CoinGecko. There is NO third independent price source wired in;
# D3 reconciliation is TWO-SOURCE ONLY (OKX primary vs Binance shadow).
# Operators must NOT interpret "shadow agreement" as triangulation — if both
# OKX and Binance print the same wrong bar, D3 will report ANOMALY_NONE even
# though no independent corroboration exists. Adding a real third source
# (e.g. CoinGecko) is future work and is NOT wired up here.
BINANCE_SHADOW_CONTRACT_ALIAS = BINANCE_BTC_SHADOW_CONTRACT
# Deprecated misnomer — kept only for backwards compatibility with callers
# that still import this name. Use BINANCE_BTC_SHADOW_CONTRACT or
# BINANCE_SHADOW_CONTRACT_ALIAS instead.
COINGECKO_BTC_SHADOW_CONTRACT = BINANCE_SHADOW_CONTRACT_ALIAS


@dataclass(frozen=True)
class CryptoProviderCapture:
    """One immutable-in-memory acquisition result and its raw response bytes."""

    contract: CryptoProviderContract
    frame: pd.DataFrame
    raw_payloads: tuple[bytes, ...]
    request_params: tuple[Mapping[str, Any], ...]
    fetched_at: pd.Timestamp
    run_id: str

    @property
    def final_rows(self) -> pd.DataFrame:
        if self.frame.empty:
            return self.frame.copy()
        return self.frame.loc[self.frame["is_final"].eq(True)].reset_index(drop=True)

    @property
    def raw_payload_hashes(self) -> tuple[str, ...]:
        return tuple(hashlib.sha256(payload).hexdigest() for payload in self.raw_payloads)

    def with_run_id(self, run_id: str) -> "CryptoProviderCapture":
        normalized_run_id = _require_run_id(run_id)
        frame = self.frame.copy()
        frame["run_id"] = normalized_run_id
        return replace(self, frame=frame, run_id=normalized_run_id)


# Backwards-compatible alias
BtcProviderCapture = CryptoProviderCapture


class ResponseLike(Protocol):
    content: bytes

    def raise_for_status(self) -> None:
        ...

    def json(self) -> Any:
        ...


HttpGet = Callable[..., ResponseLike]


def _default_http_session():
    """Lazily build a shared ``requests.Session`` with connection-level retries,
    a non-default User-Agent, and sane timeouts. One session is shared across
    provider instances so connection pooling works across calls."""
    # Module-level cache to avoid re-mounting adapters on every provider
    # construction and to benefit from connection pooling.
    global _HTTP_SESSION
    if _HTTP_SESSION is None:
        _HTTP_SESSION = create_retry_session(
            retries=3,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
        )
    return _HTTP_SESSION


_HTTP_SESSION = None


def _default_headers() -> dict[str, str]:
    return {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "application/json",
    }


def _requests_get(*args: Any, **kwargs: Any) -> ResponseLike:
    import requests

    session = _default_http_session()
    # Ensure every call has timeouts and a non-default User-Agent even if the
    # caller forgot to pass them.
    kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
    headers = dict(_default_headers())
    headers.update(kwargs.pop("headers", {}) or {})
    kwargs["headers"] = headers
    return session.get(*args, **kwargs)


def _require_run_id(run_id: str) -> str:
    value = str(run_id).strip()
    if not value:
        raise CryptoProviderContractError("run_id must be non-empty")
    return value


def _as_utc(value: Any | None) -> pd.Timestamp:
    if value is None:
        return pd.Timestamp.now(tz="UTC")
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def _stable_json_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _payload_hash(payload: Any) -> str:
    return hashlib.sha256(_stable_json_bytes(payload)).hexdigest()


def _response_payload(response: ResponseLike) -> tuple[Any, bytes]:
    response.raise_for_status()
    payload = response.json()
    content = getattr(response, "content", b"")
    if not isinstance(content, bytes) or not content:
        content = _stable_json_bytes(payload)
    return payload, content


def _empty_provider_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=CRYPTO_PROVIDER_COLUMNS)


def _ms_to_utc_daily(timestamp_ms: Any, *, provider: str) -> pd.Timestamp:
    try:
        timestamp = pd.to_datetime(int(timestamp_ms), unit="ms", utc=True)
    except (TypeError, ValueError, OverflowError) as exc:
        raise CryptoProviderContractError(
            f"{provider} returned an invalid millisecond timestamp: {timestamp_ms!r}"
        ) from exc
    if timestamp.hour != 0 or timestamp.minute != 0 or timestamp.second != 0:
        raise CryptoProviderContractError(
            f"{provider} returned a non-UTC-daily timestamp: {timestamp} "
            f"(expected 00:00 UTC for daily bars)"
        )
    return timestamp.normalize()


def _number_or_nan(value: Any) -> float:
    return float(pd.to_numeric(value, errors="coerce"))


def normalize_okx_candles(
    payload: Mapping[str, Any] | Sequence[Sequence[Any]],
    *,
    fetched_at: Any,
    run_id: str,
    contract: CryptoProviderContract | None = None,
) -> pd.DataFrame:
    """Normalize OKX ``<base>-<quote>`` ``1Dutc`` rows without dropping partials."""

    normalized_run_id = _require_run_id(run_id)
    fetched_timestamp = _as_utc(fetched_at)
    contract = contract or OKX_BTC_CONTRACT

    if isinstance(payload, Mapping):
        code = str(payload.get("code", ""))
        if code != "0":
            raise CryptoProviderResponseError(
                f"OKX history-candles failed code={code!r} msg={payload.get('msg', '')!r}"
            )
        raw_rows = payload.get("data")
    else:
        raw_rows = payload
    if raw_rows is None:
        raise CryptoProviderContractError("OKX payload is missing data")
    if not isinstance(raw_rows, Sequence) or isinstance(raw_rows, (str, bytes)):
        raise CryptoProviderContractError("OKX data must be a sequence of candle rows")

    records: list[dict[str, Any]] = []
    for raw_row in raw_rows:
        if not isinstance(raw_row, Sequence) or isinstance(raw_row, (str, bytes)):
            raise CryptoProviderContractError("OKX candle row must be a sequence")
        if len(raw_row) < 9:
            raise CryptoProviderContractError(
                f"OKX candle row must contain 9 fields, got {len(raw_row)}"
            )
        row = list(raw_row[:9])
        bar_open_at = _ms_to_utc_daily(row[0], provider="OKX")
        provider_status = str(row[8])
        records.append(
            {
                "provider": contract.provider,
                "venue": contract.venue,
                "instrument": contract.instrument,
                "base_asset": contract.base_asset,
                "quote_asset": contract.quote_asset,
                "interval": contract.interval,
                "bar_open_at": bar_open_at,
                "bar_close_at": bar_open_at + pd.Timedelta(days=1),
                "open": _number_or_nan(row[1]),
                "high": _number_or_nan(row[2]),
                "low": _number_or_nan(row[3]),
                "close": _number_or_nan(row[4]),
                "volume": _number_or_nan(row[5]),
                "is_final": provider_status == "1",
                "fetched_at": fetched_timestamp,
                "available_at": bar_open_at + pd.Timedelta(days=1),
                "payload_hash": _payload_hash(row),
                "schema_version": contract.schema_version,
                "run_id": normalized_run_id,
                "source_timestamp_ms": int(row[0]),
                "provider_status": provider_status,
            }
        )
    if not records:
        return _empty_provider_frame()
    return (
        pd.DataFrame.from_records(records, columns=CRYPTO_PROVIDER_COLUMNS)
        .sort_values("bar_open_at", kind="stable")
        .reset_index(drop=True)
    )


def normalize_binance_klines(
    payload: Sequence[Sequence[Any]],
    *,
    fetched_at: Any,
    run_id: str,
    contract: CryptoProviderContract | None = None,
) -> pd.DataFrame:
    """Normalize Binance public klines (``1d`` interval, full OHLCV, no API key)."""

    normalized_run_id = _require_run_id(run_id)
    fetched_timestamp = _as_utc(fetched_at)
    contract = contract or BINANCE_BTC_SHADOW_CONTRACT

    if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes)):
        raise CryptoProviderContractError("Binance klines response must be a sequence")

    records: list[dict[str, Any]] = []
    for raw_row in payload:
        if not isinstance(raw_row, Sequence) or isinstance(raw_row, (str, bytes)):
            raise CryptoProviderContractError("Binance kline row must be a sequence")
        if len(raw_row) < 11:
            raise CryptoProviderContractError(
                f"Binance kline row must contain 11 fields, got {len(raw_row)}"
            )
        row = list(raw_row[:11])
        # Binance kline open time is milliseconds UTC, aligned to 00:00 for 1d interval
        bar_open_at = _ms_to_utc_daily(row[0], provider="Binance")
        bar_close_at = pd.to_datetime(int(row[6]), unit="ms", utc=True)
        # Binance field 8 is the number of trades, not a close flag. A candle
        # is final only after its declared close timestamp has passed.
        is_final = bool(bar_close_at <= fetched_timestamp)
        records.append(
            {
                "provider": contract.provider,
                "venue": contract.venue,
                "instrument": contract.instrument,
                "base_asset": contract.base_asset,
                "quote_asset": contract.quote_asset,
                "interval": contract.interval,
                "bar_open_at": bar_open_at,
                "bar_close_at": bar_close_at,
                "open": _number_or_nan(row[1]),
                "high": _number_or_nan(row[2]),
                "low": _number_or_nan(row[3]),
                "close": _number_or_nan(row[4]),
                "volume": _number_or_nan(row[5]),
                "is_final": is_final,
                "fetched_at": fetched_timestamp,
                "available_at": bar_close_at,
                "payload_hash": _payload_hash(row),
                "schema_version": contract.schema_version,
                "run_id": normalized_run_id,
                "source_timestamp_ms": int(row[0]),
                "provider_status": "closed" if is_final else "open",
            }
        )
    if not records:
        return _empty_provider_frame()
    return (
        pd.DataFrame.from_records(records, columns=CRYPTO_PROVIDER_COLUMNS)
        .sort_values("bar_open_at", kind="stable")
        .reset_index(drop=True)
    )


# Backwards-compatible alias - shadow provider is Binance (NOT CoinGecko).
# A real independent third source is not yet wired; D3 is two-source only.
normalize_coingecko_market_chart = normalize_binance_klines


def okx_canonical_candidate(
    capture_or_frame: CryptoProviderCapture | pd.DataFrame,
    contract: CryptoProviderContract | None = None,
) -> pd.DataFrame:
    """Return completed primary rows, rejecting shadow/provider mixing."""

    expected_contract = contract or OKX_BTC_CONTRACT

    if isinstance(capture_or_frame, CryptoProviderCapture):
        if capture_or_frame.contract.provider != expected_contract.provider:
            raise CryptoProviderContractError(
                f"Shadow ({capture_or_frame.contract.provider}) rows cannot be used as canonical OHLC fallback"
            )
        frame = capture_or_frame.frame
    else:
        frame = capture_or_frame
    missing = [column for column in CRYPTO_PROVIDER_REQUIRED_COLUMNS if column not in frame]
    if missing:
        raise CryptoProviderContractError(
            f"Crypto provider frame is missing required columns: {', '.join(missing)}"
        )
    if frame.empty:
        return frame.copy()
    expected_identity = {
        "provider": expected_contract.provider,
        "venue": expected_contract.venue,
        "instrument": expected_contract.instrument,
        "base_asset": expected_contract.base_asset,
        "quote_asset": expected_contract.quote_asset,
        "interval": expected_contract.interval,
    }
    for column, expected in expected_identity.items():
        actual = set(frame[column].dropna().astype(str))
        if actual != {expected}:
            raise CryptoProviderContractError(
                f"canonical candidate has invalid {column}: {sorted(actual)!r}"
            )
    return frame.loc[frame["is_final"].eq(True)].reset_index(drop=True)


class OkxDailyProvider:
    """Injectable OKX <base>-<quote> ``1Dutc`` history-candle adapter (free, keyless)."""

    def __init__(
        self,
        base_asset: str = "BTC",
        quote_asset: str = DEFAULT_QUOTE_ASSET,
        http_get: HttpGet | None = None,
        *,
        endpoint: str = OKX_HISTORY_CANDLES_URL,
        timeout_s: float | tuple[float, float] = DEFAULT_TIMEOUT,
        page_limit: int = 100,
    ) -> None:
        if page_limit < 1 or page_limit > 100:
            raise ValueError("OKX history-candle page_limit must be in [1, 100]")
        self.contract = make_okx_contract(base_asset, quote_asset)
        self._http_get = http_get or _requests_get
        self._endpoint = endpoint
        self._timeout_s = timeout_s
        self._page_limit = page_limit

    def capture(
        self,
        *,
        days: int,
        fetched_at: Any | None,
        run_id: str,
    ) -> CryptoProviderCapture:
        if days < 1:
            raise ValueError("days must be positive")
        normalized_run_id = _require_run_id(run_id)
        capture_time = _as_utc(fetched_at)
        earliest_open = capture_time.normalize() - pd.Timedelta(days=days)
        raw_rows: list[Sequence[Any]] = []
        raw_payloads: list[bytes] = []
        requests_made: list[Mapping[str, Any]] = []
        after: int | None = None
        seen_cursors: set[int] = set()

        while True:
            params: dict[str, Any] = {
                "instId": self.contract.instrument,
                "bar": self.contract.interval,
                "limit": self._page_limit,
            }
            if after is not None:
                params["after"] = after
            response = self._http_get(
                self._endpoint,
                params=params,
                headers={"Accept": "application/json"},
                timeout=self._timeout_s,
            )
            payload, raw_payload = _response_payload(response)
            raw_payloads.append(raw_payload)
            requests_made.append(dict(params))
            if not isinstance(payload, Mapping):
                raise CryptoProviderContractError("OKX response must be an object")
            if str(payload.get("code", "")) != "0":
                raise CryptoProviderResponseError(
                    f"OKX history-candles failed code={payload.get('code')!r} "
                    f"msg={payload.get('msg', '')!r}"
                )
            page_rows = payload.get("data")
            if page_rows is None:
                raise CryptoProviderContractError("OKX payload is missing data")
            if not isinstance(page_rows, Sequence) or isinstance(page_rows, (str, bytes)):
                raise CryptoProviderContractError("OKX data must be a sequence")
            if not page_rows:
                break
            raw_rows.extend(page_rows)
            last_row = page_rows[-1]
            if (
                not isinstance(last_row, Sequence)
                or isinstance(last_row, (str, bytes))
                or not last_row
            ):
                raise CryptoProviderContractError("OKX pagination row is malformed")
            try:
                oldest_timestamp = int(last_row[0])
            except (TypeError, ValueError) as exc:
                raise CryptoProviderContractError("OKX pagination timestamp is invalid") from exc
            if (
                pd.to_datetime(oldest_timestamp, unit="ms", utc=True) <= earliest_open
                or len(page_rows) < self._page_limit
            ):
                break
            if oldest_timestamp in seen_cursors:
                raise CryptoProviderContractError("OKX pagination cursor did not advance")
            seen_cursors.add(oldest_timestamp)
            after = oldest_timestamp

        frame = normalize_okx_candles(
            raw_rows,
            fetched_at=capture_time,
            run_id=normalized_run_id,
            contract=self.contract,
        )
        if not frame.empty:
            frame = frame.loc[frame["bar_open_at"] >= earliest_open].reset_index(drop=True)
        return CryptoProviderCapture(
            contract=self.contract,
            frame=frame,
            raw_payloads=tuple(raw_payloads),
            request_params=tuple(requests_made),
            fetched_at=capture_time,
            run_id=normalized_run_id,
        )


# Backwards-compatible alias
OkxBtcDailyProvider = lambda **kwargs: OkxDailyProvider(base_asset="BTC", **{k: v for k, v in kwargs.items() if k != "base_asset"})


class BinanceDailyProvider:
    """Injectable Binance public klines adapter (``1d`` interval, full OHLCV, **FREE, no API key required**)."""

    def __init__(
        self,
        base_asset: str = "BTC",
        quote_asset: str = DEFAULT_QUOTE_ASSET,
        http_get: HttpGet | None = None,
        *,
        endpoint: str = BINANCE_KLINES_URL,
        timeout_s: float | tuple[float, float] = DEFAULT_TIMEOUT,
        page_limit: int = 1000,
    ) -> None:
        if page_limit < 1 or page_limit > 1000:
            raise ValueError("Binance kline page_limit must be in [1, 1000]")
        self.contract = make_binance_contract(base_asset, quote_asset)
        self._http_get = http_get or _requests_get
        self._endpoint = endpoint
        self._timeout_s = timeout_s
        self._page_limit = page_limit

    def capture(
        self,
        *,
        days: int,
        fetched_at: Any | None,
        run_id: str,
    ) -> CryptoProviderCapture:
        if days < 1:
            raise ValueError("days must be positive")
        normalized_run_id = _require_run_id(run_id)
        capture_time = _as_utc(fetched_at)
        earliest_open = capture_time.normalize() - pd.Timedelta(days=days)
        raw_rows: list[Sequence[Any]] = []
        raw_payloads: list[bytes] = []
        requests_made: list[Mapping[str, Any]] = []
        end_time: int | None = None
        seen_cursors: set[int] = set()

        while True:
            params: dict[str, Any] = {
                "symbol": self.contract.instrument,
                "interval": self.contract.interval,
                "limit": self._page_limit,
            }
            if end_time is not None:
                params["endTime"] = end_time
            response = self._http_get(
                self._endpoint,
                params=params,
                headers={"Accept": "application/json"},
                timeout=self._timeout_s,
            )
            payload, raw_payload = _response_payload(response)
            raw_payloads.append(raw_payload)
            requests_made.append(dict(params))
            if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes)):
                raise CryptoProviderContractError("Binance klines response must be a sequence")
            if not payload:
                break
            page_rows = payload
            raw_rows = page_rows + raw_rows  # Binance returns oldest first when paginating backwards
            first_row = page_rows[0]
            if (
                not isinstance(first_row, Sequence)
                or isinstance(first_row, (str, bytes))
                or not first_row
            ):
                raise CryptoProviderContractError("Binance pagination row is malformed")
            try:
                oldest_timestamp = int(first_row[0])
            except (TypeError, ValueError) as exc:
                raise CryptoProviderContractError("Binance pagination timestamp is invalid") from exc
            oldest_open = pd.to_datetime(oldest_timestamp, unit="ms", utc=True)
            if oldest_open <= earliest_open or len(page_rows) < self._page_limit:
                break
            if oldest_timestamp in seen_cursors:
                raise CryptoProviderContractError("Binance pagination cursor did not advance")
            seen_cursors.add(oldest_timestamp)
            end_time = oldest_timestamp - 1  # endTime is inclusive, subtract 1ms

        frame = normalize_binance_klines(
            raw_rows,
            fetched_at=capture_time,
            run_id=normalized_run_id,
            contract=self.contract,
        )
        if not frame.empty:
            frame = frame.loc[frame["bar_open_at"] >= earliest_open].reset_index(drop=True)
        return CryptoProviderCapture(
            contract=self.contract,
            frame=frame,
            raw_payloads=tuple(raw_payloads),
            request_params=tuple(requests_made),
            fetched_at=capture_time,
            run_id=normalized_run_id,
        )


# Backwards-compatible alias.
# NOTE: Despite the historical "CoinGecko" name, this provider is backed by
# Binance. There is NO third independent source in D3; shadow agreement means
# "OKX agrees with Binance", not true triangulation.
CoinGeckoBtcDailyShadowProvider = lambda **kwargs: BinanceDailyProvider(base_asset="BTC", **{k: v for k, v in kwargs.items() if k not in ("api_key", "require_api_key", "api_key_header")})


__all__ = [
    "CRYPTO_PROVIDER_SCHEMA_VERSION",
    "CRYPTO_PROVIDER_REQUIRED_COLUMNS",
    "CRYPTO_PROVIDER_COLUMNS",
    "DEFAULT_CRYPTO_ASSETS",
    "DEFAULT_QUOTE_ASSET",
    "CryptoProviderError",
    "CryptoProviderContractError",
    "CryptoProviderResponseError",
    "CryptoProviderContract",
    "CryptoProviderCapture",
    "make_okx_contract",
    "make_binance_contract",
    "OKX_BTC_CONTRACT",
    "BINANCE_BTC_SHADOW_CONTRACT",
    "BINANCE_SHADOW_CONTRACT_ALIAS",
    "COINGECKO_BTC_SHADOW_CONTRACT",
    "normalize_okx_candles",
    "normalize_binance_klines",
    "normalize_coingecko_market_chart",
    "okx_canonical_candidate",
    "OkxDailyProvider",
    "OkxBtcDailyProvider",
    "BinanceDailyProvider",
    "CoinGeckoBtcDailyShadowProvider",
    # Legacy column name exports
    "BTC_PROVIDER_COLUMNS",
    "BTC_PROVIDER_REQUIRED_COLUMNS",
    "BtcProviderCapture",
    "BtcProviderError",
    "BtcProviderContractError",
    "BtcProviderCredentialError",
    "BtcProviderResponseError",
]

# Legacy BTC column aliases
BTC_PROVIDER_COLUMNS = CRYPTO_PROVIDER_COLUMNS
BTC_PROVIDER_REQUIRED_COLUMNS = CRYPTO_PROVIDER_REQUIRED_COLUMNS
BtcProviderError = CryptoProviderError
BtcProviderContractError = CryptoProviderContractError
BtcProviderCredentialError = CryptoProviderError
BtcProviderResponseError = CryptoProviderResponseError
