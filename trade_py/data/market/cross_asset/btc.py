from __future__ import annotations

"""Provider-native BTC daily market-data contracts and adapters.

OKX is the only primary OHLC provider in the BTC v1 contract. CoinGecko is a
daily-close shadow source used for reconciliation; its rows deliberately keep
``open``, ``high``, and ``low`` empty so they cannot be mistaken for fallback
OHLC bars.
"""

import hashlib
import json
from dataclasses import dataclass, replace
from typing import Any, Callable, Literal, Mapping, Protocol, Sequence

import pandas as pd

BTC_PROVIDER_SCHEMA_VERSION = "btc-provider-v1"
OKX_HISTORY_CANDLES_URL = "https://www.okx.com/api/v5/market/history-candles"
COINGECKO_MARKET_CHART_URL = (
    "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
)

BTC_PROVIDER_REQUIRED_COLUMNS = (
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
BTC_PROVIDER_COLUMNS = BTC_PROVIDER_REQUIRED_COLUMNS + (
    "source_timestamp_ms",
    "provider_status",
)


class BtcProviderError(RuntimeError):
    """Base exception for BTC provider acquisition and contract failures."""


class BtcProviderContractError(BtcProviderError):
    """Raised when a payload cannot satisfy its declared provider contract."""


class BtcProviderCredentialError(BtcProviderError):
    """Raised when a provider configured to require a credential has none."""


class BtcProviderResponseError(BtcProviderError):
    """Raised when an upstream provider reports an unsuccessful response."""


@dataclass(frozen=True)
class BtcProviderContract:
    provider: str
    venue: str
    instrument: str
    base_asset: str
    quote_asset: str
    interval: str
    role: Literal["primary", "shadow"]
    schema_version: str = BTC_PROVIDER_SCHEMA_VERSION


OKX_BTC_CONTRACT = BtcProviderContract(
    provider="okx",
    venue="okx",
    instrument="BTC-USDT",
    base_asset="BTC",
    quote_asset="USDT",
    interval="1Dutc",
    role="primary",
)
COINGECKO_BTC_SHADOW_CONTRACT = BtcProviderContract(
    provider="coingecko",
    venue="coingecko",
    instrument="BTC-USD",
    base_asset="BTC",
    quote_asset="USD",
    interval="daily",
    role="shadow",
)


@dataclass(frozen=True)
class BtcProviderCapture:
    """One immutable-in-memory acquisition result and its raw response bytes."""

    contract: BtcProviderContract
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

    def with_run_id(self, run_id: str) -> "BtcProviderCapture":
        normalized_run_id = _require_run_id(run_id)
        frame = self.frame.copy()
        frame["run_id"] = normalized_run_id
        return replace(self, frame=frame, run_id=normalized_run_id)


class ResponseLike(Protocol):
    content: bytes

    def raise_for_status(self) -> None:
        ...

    def json(self) -> Any:
        ...


HttpGet = Callable[..., ResponseLike]


def _requests_get(*args: Any, **kwargs: Any) -> ResponseLike:
    import requests

    return requests.get(*args, **kwargs)


def _require_run_id(run_id: str) -> str:
    value = str(run_id).strip()
    if not value:
        raise BtcProviderContractError("run_id must be non-empty")
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
    return pd.DataFrame(columns=BTC_PROVIDER_COLUMNS)


def _utc_daily_open(timestamp_ms: Any, *, provider: str) -> pd.Timestamp:
    try:
        timestamp = pd.to_datetime(int(timestamp_ms), unit="ms", utc=True)
    except (TypeError, ValueError, OverflowError) as exc:
        raise BtcProviderContractError(
            f"{provider} returned an invalid millisecond timestamp: {timestamp_ms!r}"
        ) from exc
    if timestamp != timestamp.normalize():
        raise BtcProviderContractError(
            f"{provider} returned a non-UTC-daily timestamp: {timestamp.isoformat()}"
        )
    return timestamp


def _number_or_nan(value: Any) -> float:
    return float(pd.to_numeric(value, errors="coerce"))


def normalize_okx_candles(
    payload: Mapping[str, Any] | Sequence[Sequence[Any]],
    *,
    fetched_at: Any,
    run_id: str,
) -> pd.DataFrame:
    """Normalize OKX ``BTC-USDT`` ``1Dutc`` rows without dropping partials."""

    normalized_run_id = _require_run_id(run_id)
    fetched_timestamp = _as_utc(fetched_at)
    if isinstance(payload, Mapping):
        code = str(payload.get("code", ""))
        if code != "0":
            raise BtcProviderResponseError(
                f"OKX history-candles failed code={code!r} msg={payload.get('msg', '')!r}"
            )
        raw_rows = payload.get("data")
    else:
        raw_rows = payload
    if raw_rows is None:
        raise BtcProviderContractError("OKX payload is missing data")
    if not isinstance(raw_rows, Sequence) or isinstance(raw_rows, (str, bytes)):
        raise BtcProviderContractError("OKX data must be a sequence of candle rows")

    records: list[dict[str, Any]] = []
    for raw_row in raw_rows:
        if not isinstance(raw_row, Sequence) or isinstance(raw_row, (str, bytes)):
            raise BtcProviderContractError("OKX candle row must be a sequence")
        if len(raw_row) < 9:
            raise BtcProviderContractError(
                f"OKX candle row must contain 9 fields, got {len(raw_row)}"
            )
        row = list(raw_row[:9])
        bar_open_at = _utc_daily_open(row[0], provider="OKX")
        provider_status = str(row[8])
        records.append(
            {
                "provider": OKX_BTC_CONTRACT.provider,
                "venue": OKX_BTC_CONTRACT.venue,
                "instrument": OKX_BTC_CONTRACT.instrument,
                "base_asset": OKX_BTC_CONTRACT.base_asset,
                "quote_asset": OKX_BTC_CONTRACT.quote_asset,
                "interval": OKX_BTC_CONTRACT.interval,
                "bar_open_at": bar_open_at,
                "bar_close_at": bar_open_at + pd.Timedelta(days=1),
                "open": _number_or_nan(row[1]),
                "high": _number_or_nan(row[2]),
                "low": _number_or_nan(row[3]),
                "close": _number_or_nan(row[4]),
                "volume": _number_or_nan(row[5]),
                "is_final": provider_status == "1",
                "fetched_at": fetched_timestamp,
                # Provider availability is the completed UTC bar close; local
                # first observation remains separately preserved in fetched_at.
                "available_at": bar_open_at + pd.Timedelta(days=1),
                "payload_hash": _payload_hash(row),
                "schema_version": OKX_BTC_CONTRACT.schema_version,
                "run_id": normalized_run_id,
                "source_timestamp_ms": int(row[0]),
                "provider_status": provider_status,
            }
        )
    if not records:
        return _empty_provider_frame()
    return (
        pd.DataFrame.from_records(records, columns=BTC_PROVIDER_COLUMNS)
        .sort_values("bar_open_at", kind="stable")
        .reset_index(drop=True)
    )


def normalize_coingecko_market_chart(
    payload: Mapping[str, Any],
    *,
    fetched_at: Any,
    run_id: str,
) -> pd.DataFrame:
    """Normalize CoinGecko ``market_chart`` daily prices as close-only rows."""

    normalized_run_id = _require_run_id(run_id)
    fetched_timestamp = _as_utc(fetched_at)
    if not isinstance(payload, Mapping):
        raise BtcProviderContractError(
            "CoinGecko market_chart payload must be an object, not OHLC rows"
        )
    prices = payload.get("prices")
    if prices is None:
        raise BtcProviderContractError("CoinGecko market_chart payload is missing prices")
    if not isinstance(prices, Sequence) or isinstance(prices, (str, bytes)):
        raise BtcProviderContractError("CoinGecko prices must be timestamp/value rows")

    volume_by_timestamp: dict[int, Any] = {}
    total_volumes = payload.get("total_volumes") or []
    if isinstance(total_volumes, Sequence) and not isinstance(total_volumes, (str, bytes)):
        for volume_row in total_volumes:
            if (
                isinstance(volume_row, Sequence)
                and not isinstance(volume_row, (str, bytes))
                and len(volume_row) >= 2
            ):
                try:
                    volume_by_timestamp[int(volume_row[0])] = volume_row[1]
                except (TypeError, ValueError):
                    continue

    records: list[dict[str, Any]] = []
    for raw_price in prices:
        if (
            not isinstance(raw_price, Sequence)
            or isinstance(raw_price, (str, bytes))
            or len(raw_price) < 2
        ):
            raise BtcProviderContractError(
                "CoinGecko price row must contain timestamp and close"
            )
        price_row = list(raw_price[:2])
        source_timestamp_ms = int(price_row[0])
        bar_open_at = _utc_daily_open(source_timestamp_ms, provider="CoinGecko")
        bar_close_at = bar_open_at + pd.Timedelta(days=1)
        is_final = bar_close_at <= fetched_timestamp
        raw_volume = volume_by_timestamp.get(source_timestamp_ms)
        records.append(
            {
                "provider": COINGECKO_BTC_SHADOW_CONTRACT.provider,
                "venue": COINGECKO_BTC_SHADOW_CONTRACT.venue,
                "instrument": COINGECKO_BTC_SHADOW_CONTRACT.instrument,
                "base_asset": COINGECKO_BTC_SHADOW_CONTRACT.base_asset,
                "quote_asset": COINGECKO_BTC_SHADOW_CONTRACT.quote_asset,
                "interval": COINGECKO_BTC_SHADOW_CONTRACT.interval,
                "bar_open_at": bar_open_at,
                "bar_close_at": bar_close_at,
                # Shadow data is close-only by contract. Never synthesize OHLC.
                "open": float("nan"),
                "high": float("nan"),
                "low": float("nan"),
                "close": _number_or_nan(price_row[1]),
                "volume": _number_or_nan(raw_volume),
                "is_final": is_final,
                "fetched_at": fetched_timestamp,
                "available_at": bar_close_at,
                "payload_hash": _payload_hash(
                    {"price": price_row, "total_volume": raw_volume}
                ),
                "schema_version": COINGECKO_BTC_SHADOW_CONTRACT.schema_version,
                "run_id": normalized_run_id,
                "source_timestamp_ms": source_timestamp_ms,
                "provider_status": "complete" if is_final else "partial",
            }
        )
    if not records:
        return _empty_provider_frame()
    return (
        pd.DataFrame.from_records(records, columns=BTC_PROVIDER_COLUMNS)
        .sort_values("bar_open_at", kind="stable")
        .reset_index(drop=True)
    )


def okx_canonical_candidate(
    capture_or_frame: BtcProviderCapture | pd.DataFrame,
) -> pd.DataFrame:
    """Return completed primary rows, rejecting shadow/provider mixing."""

    if isinstance(capture_or_frame, BtcProviderCapture):
        if capture_or_frame.contract != OKX_BTC_CONTRACT:
            raise BtcProviderContractError(
                "CoinGecko shadow rows cannot be used as canonical OHLC fallback"
            )
        frame = capture_or_frame.frame
    else:
        frame = capture_or_frame
    missing = [column for column in BTC_PROVIDER_REQUIRED_COLUMNS if column not in frame]
    if missing:
        raise BtcProviderContractError(
            f"BTC provider frame is missing required columns: {', '.join(missing)}"
        )
    if frame.empty:
        return frame.copy()
    expected_identity = {
        "provider": OKX_BTC_CONTRACT.provider,
        "venue": OKX_BTC_CONTRACT.venue,
        "instrument": OKX_BTC_CONTRACT.instrument,
        "base_asset": OKX_BTC_CONTRACT.base_asset,
        "quote_asset": OKX_BTC_CONTRACT.quote_asset,
        "interval": OKX_BTC_CONTRACT.interval,
    }
    for column, expected in expected_identity.items():
        actual = set(frame[column].dropna().astype(str))
        if actual != {expected}:
            raise BtcProviderContractError(
                f"canonical candidate has invalid {column}: {sorted(actual)!r}"
            )
    return frame.loc[frame["is_final"].eq(True)].reset_index(drop=True)


class OkxBtcDailyProvider:
    """Injectable OKX BTC-USDT ``1Dutc`` history-candle adapter."""

    contract = OKX_BTC_CONTRACT

    def __init__(
        self,
        http_get: HttpGet | None = None,
        *,
        endpoint: str = OKX_HISTORY_CANDLES_URL,
        timeout_s: float = 15.0,
        page_limit: int = 100,
    ) -> None:
        if page_limit < 1 or page_limit > 100:
            raise ValueError("OKX history-candle page_limit must be in [1, 100]")
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
    ) -> BtcProviderCapture:
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
                raise BtcProviderContractError("OKX response must be an object")
            if str(payload.get("code", "")) != "0":
                raise BtcProviderResponseError(
                    f"OKX history-candles failed code={payload.get('code')!r} "
                    f"msg={payload.get('msg', '')!r}"
                )
            page_rows = payload.get("data")
            if page_rows is None:
                raise BtcProviderContractError("OKX payload is missing data")
            if not isinstance(page_rows, Sequence) or isinstance(page_rows, (str, bytes)):
                raise BtcProviderContractError("OKX data must be a sequence")
            if not page_rows:
                break
            raw_rows.extend(page_rows)
            last_row = page_rows[-1]
            if (
                not isinstance(last_row, Sequence)
                or isinstance(last_row, (str, bytes))
                or not last_row
            ):
                raise BtcProviderContractError("OKX pagination row is malformed")
            try:
                oldest_timestamp = int(last_row[0])
            except (TypeError, ValueError) as exc:
                raise BtcProviderContractError("OKX pagination timestamp is invalid") from exc
            if (
                pd.to_datetime(oldest_timestamp, unit="ms", utc=True) <= earliest_open
                or len(page_rows) < self._page_limit
            ):
                break
            if oldest_timestamp in seen_cursors:
                raise BtcProviderContractError("OKX pagination cursor did not advance")
            seen_cursors.add(oldest_timestamp)
            after = oldest_timestamp

        frame = normalize_okx_candles(
            raw_rows,
            fetched_at=capture_time,
            run_id=normalized_run_id,
        )
        if not frame.empty:
            frame = frame.loc[frame["bar_open_at"] >= earliest_open].reset_index(drop=True)
        return BtcProviderCapture(
            contract=self.contract,
            frame=frame,
            raw_payloads=tuple(raw_payloads),
            request_params=tuple(requests_made),
            fetched_at=capture_time,
            run_id=normalized_run_id,
        )


class CoinGeckoBtcDailyShadowProvider:
    """Injectable CoinGecko ``market_chart`` daily-close shadow adapter."""

    contract = COINGECKO_BTC_SHADOW_CONTRACT

    def __init__(
        self,
        http_get: HttpGet | None = None,
        *,
        api_key: str | None = None,
        require_api_key: bool = True,
        endpoint: str = COINGECKO_MARKET_CHART_URL,
        timeout_s: float = 20.0,
        api_key_header: str = "x-cg-demo-api-key",
    ) -> None:
        self._http_get = http_get or _requests_get
        self._api_key = api_key.strip() if api_key else None
        self._require_api_key = require_api_key
        self._endpoint = endpoint
        self._timeout_s = timeout_s
        self._api_key_header = api_key_header

    def capture(
        self,
        *,
        days: int,
        fetched_at: Any | None,
        run_id: str,
    ) -> BtcProviderCapture:
        if days < 1:
            raise ValueError("days must be positive")
        if self._require_api_key and not self._api_key:
            raise BtcProviderCredentialError("CoinGecko API key is required")
        normalized_run_id = _require_run_id(run_id)
        capture_time = _as_utc(fetched_at)
        params: dict[str, Any] = {
            "vs_currency": "usd",
            "days": str(days),
            "interval": "daily",
            "precision": "full",
        }
        headers = {"Accept": "application/json"}
        if self._api_key:
            headers[self._api_key_header] = self._api_key
        response = self._http_get(
            self._endpoint,
            params=params,
            headers=headers,
            timeout=self._timeout_s,
        )
        payload, raw_payload = _response_payload(response)
        if not isinstance(payload, Mapping):
            raise BtcProviderContractError(
                "CoinGecko market_chart response must be an object"
            )
        frame = normalize_coingecko_market_chart(
            payload,
            fetched_at=capture_time,
            run_id=normalized_run_id,
        )
        return BtcProviderCapture(
            contract=self.contract,
            frame=frame,
            raw_payloads=(raw_payload,),
            request_params=(dict(params),),
            fetched_at=capture_time,
            run_id=normalized_run_id,
        )
