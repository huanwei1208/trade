"""Central Tushare Pro API client.

Manages token loading, rate limiting (≥600 ms between calls), and retry.

Usage:
    from trade_py.data.market.tushare_client import get_pro_api
    pro = get_pro_api(data_root="data")
    df = pro.daily(ts_code="000001.SZ", start_date="20250101", end_date="20250301", adj="hfq")

Token is stored via:
    ./trade account setting-set tushare_token YOUR_TOKEN
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pandas as pd

from trade_py.db.settings_db import SettingsDB

logger = logging.getLogger(__name__)

_DEFAULT_MIN_INTERVAL_SEC = 0.6
_DEFAULT_MINUTE_BUDGET = 50
_DEFAULT_RATE_LIMIT_BACKOFF_SEC = (5, 15, 30, 45, 60)
_AUDIT_LOG_NAME = "tushare_requests.jsonl"
_RATE_LIMIT_PATTERNS = (
    "每分钟最多访问该接口",
    "每分钟最多访问",
    "too many requests",
    "rate limit",
)
_TRANSIENT_PATTERNS = (
    "timeout",
    "timed out",
    "timedout",
    "connection aborted",
    "remote end closed connection",
    "temporary failure in name resolution",
    "name or service not known",
    "connection reset",
    "proxy error",
)
_AUTH_PATTERNS = (
    "invalid token",
    "token not found",
    "token失效",
    "token错误",
    "无效的 token",
    "token不对",
    "您的token不对",
)
_PERMISSION_PATTERNS = ("权限", "permission", "积分不足", "无权限")
_INVALID_REQUEST_PATTERNS = ("参数", "parameter", "不存在", "not exist", "unknown api")


class TushareError(RuntimeError):
    """Base class for Tushare API failures."""


class TushareAuthError(TushareError):
    """Authentication or token failure."""


class TusharePermissionError(TushareError):
    """Permission or quota failure."""


class TushareInvalidRequestError(TushareError):
    """Invalid endpoint or bad parameter."""


class TushareTransientError(TushareError):
    """Retryable network-style failure."""


class TushareRateLimitError(TushareError):
    """Provider-side rate limit or quota throttling."""


@dataclass(frozen=True)
class TushareClientConfig:
    token: str
    http_url: str
    min_interval_sec: float
    minute_budget: int
    rate_limit_backoff_sec: tuple[int, ...]
    audit_log_enabled: bool
    data_root: str


class TushareProClient:
    """Thin wrapper around tushare.pro_api with rate limiting and retry."""

    def __init__(self, config: TushareClientConfig) -> None:
        import tushare as ts
        self._config = config
        self._api = ts.pro_api(config.token)
        self._api._DataApi__token = config.token
        if config.http_url:
            self._api._DataApi__http_url = config.http_url
        self._last_call: float = 0.0
        self._call_timestamps: deque[float] = deque()
        self._global_next_allowed_at: float = 0.0
        self._audit_log_path = Path(config.data_root) / ".db" / _AUDIT_LOG_NAME
        self._audit_log_path.parent.mkdir(parents=True, exist_ok=True)

    def _wait(self) -> float:
        now = time.monotonic()
        waits: list[float] = []
        if self._last_call:
            elapsed = now - self._last_call
            if elapsed < self._config.min_interval_sec:
                waits.append(self._config.min_interval_sec - elapsed)
        if now < self._global_next_allowed_at:
            waits.append(self._global_next_allowed_at - now)
        self._prune_call_timestamps(now)
        if self._config.minute_budget > 0 and len(self._call_timestamps) >= self._config.minute_budget:
            waits.append((self._call_timestamps[0] + 60.0) - now)
        wait = max((w for w in waits if w > 0), default=0.0)
        if wait > 0:
            time.sleep(wait)
        return wait

    def _prune_call_timestamps(self, now: float) -> None:
        cutoff = now - 60.0
        while self._call_timestamps and self._call_timestamps[0] <= cutoff:
            self._call_timestamps.popleft()

    def _mark_request_start(self, now: float) -> None:
        self._last_call = now
        self._call_timestamps.append(now)

    def _retry_delay(self, exc: Exception, attempt: int, rate_limit_attempt: int) -> int:
        if _is_rate_limit_error(exc):
            return _rate_limit_delay(rate_limit_attempt, self._config.rate_limit_backoff_sec)
        return 2 ** attempt

    def _audit_log(
        self,
        endpoint: str,
        kwargs: dict[str, Any],
        status: str,
        duration_ms: float,
        wait_ms: float,
        retry_index: int,
        exc: Exception | None = None,
    ) -> None:
        if not self._config.audit_log_enabled:
            return
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "pid": os.getpid(),
            "endpoint": endpoint,
            "params_hash": _params_hash(kwargs),
            "status": status,
            "duration_ms": round(duration_ms, 3),
            "wait_ms": round(wait_ms, 3),
            "retry_index": retry_index,
            "error_type": type(exc).__name__ if exc is not None else "",
            "error_message": str(exc) if exc is not None else "",
            "http_host": _http_host(self._config.http_url or getattr(self._api, "_DataApi__http_url", "")),
        }
        with self._audit_log_path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(payload, ensure_ascii=True) + "\n")

    def call(self, endpoint: str, retries: int = 3, **kwargs: Any) -> pd.DataFrame:
        """Call a Tushare Pro endpoint with rate limiting and exponential back-off."""
        fn = getattr(self._api, endpoint)
        last_exc: Exception | None = None
        attempt = 0
        rate_limit_attempt = 0
        last_max_attempts = retries
        while True:
            wait_sec = self._wait()
            try:
                started_at = time.monotonic()
                self._mark_request_start(started_at)
                result = fn(**kwargs)
                self._audit_log(
                    endpoint=endpoint,
                    kwargs=kwargs,
                    status="success",
                    duration_ms=(time.monotonic() - started_at) * 1000.0,
                    wait_ms=wait_sec * 1000.0,
                    retry_index=attempt + rate_limit_attempt,
                )
                if result is None:
                    return pd.DataFrame()
                return result
            except Exception as exc:
                last_exc = exc
                classification = _classify_exception(exc)
                self._audit_log(
                    endpoint=endpoint,
                    kwargs=kwargs,
                    status=classification,
                    duration_ms=0.0,
                    wait_ms=wait_sec * 1000.0,
                    retry_index=attempt + rate_limit_attempt,
                    exc=exc,
                )
                is_rate_limit = classification == "rate_limit"
                if classification == "auth":
                    raise TushareAuthError(f"tushare endpoint {endpoint!r} failed: {exc}") from exc
                if classification == "permission":
                    raise TusharePermissionError(f"tushare endpoint {endpoint!r} failed: {exc}") from exc
                if classification == "invalid_request":
                    raise TushareInvalidRequestError(f"tushare endpoint {endpoint!r} failed: {exc}") from exc
                if is_rate_limit:
                    rate_limit_attempt += 1
                    if rate_limit_attempt > len(self._config.rate_limit_backoff_sec):
                        break
                    current_attempt = rate_limit_attempt
                    max_attempts = len(self._config.rate_limit_backoff_sec) + 1
                else:
                    attempt += 1
                    if attempt >= retries:
                        break
                    current_attempt = attempt
                    max_attempts = retries
                last_max_attempts = max_attempts
                wait = self._retry_delay(exc, attempt - 1, rate_limit_attempt)
                logger.warning(
                    "tushare call %s attempt %d/%d failed: %s — retrying in %ds",
                    endpoint, current_attempt, max_attempts, exc, wait,
                )
                if is_rate_limit:
                    # Set global guard so _wait() sleeps the backoff on next iteration
                    self._global_next_allowed_at = max(self._global_next_allowed_at, time.monotonic() + wait)
                else:
                    time.sleep(wait)
        if last_exc is not None and _classify_exception(last_exc) == "transient":
            raise TushareTransientError(
                f"tushare endpoint {endpoint!r} failed after {last_max_attempts} attempts"
            ) from last_exc
        raise TushareError(
            f"tushare endpoint {endpoint!r} failed after {last_max_attempts} attempts"
        ) from last_exc


_INSTANCES: dict[tuple[str, str, str], TushareProClient] = {}


def get_pro_api(data_root: str | Path = "data") -> TushareProClient:
    """Return the singleton TushareProClient, initialising it if needed.

    Reads token from SettingsDB (.db/trade.db) at data_root.
    Falls back to TUSHARE_TOKEN environment variable.
    """
    config = _load_client_config(data_root)
    if not config.token:
        raise RuntimeError(
            "Tushare token not found. Run:\n"
            "  ./trade account setting-set tushare_token YOUR_TOKEN"
        )
    key = (config.data_root, config.token, config.http_url)
    client = _INSTANCES.get(key)
    if client is None:
        client = TushareProClient(config)
        _INSTANCES[key] = client
    return client


def _load_client_config(data_root: str | Path) -> TushareClientConfig:
    data_root_str = str(Path(data_root))
    settings = SettingsDB(data_root_str)
    token = str(settings.get("tushare_token", "") or os.environ.get("TUSHARE_TOKEN", "")).strip()
    http_url = str(settings.get("tushare.http_url", "") or "").strip()
    min_interval_sec = _coerce_float(settings.get("tushare.min_interval_sec", _DEFAULT_MIN_INTERVAL_SEC), _DEFAULT_MIN_INTERVAL_SEC)
    minute_budget = _coerce_int(settings.get("tushare.minute_budget", _DEFAULT_MINUTE_BUDGET), _DEFAULT_MINUTE_BUDGET)
    backoff = _coerce_backoff(
        settings.get("tushare.rate_limit_backoff_sec", ",".join(str(v) for v in _DEFAULT_RATE_LIMIT_BACKOFF_SEC)),
        _DEFAULT_RATE_LIMIT_BACKOFF_SEC,
    )
    audit_log_enabled = _coerce_bool(settings.get("tushare.audit_log_enabled", True), True)
    return TushareClientConfig(
        token=token,
        http_url=http_url,
        min_interval_sec=min_interval_sec,
        minute_budget=minute_budget,
        rate_limit_backoff_sec=backoff,
        audit_log_enabled=audit_log_enabled,
        data_root=data_root_str,
    )


def _is_rate_limit_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(pattern.lower() in text for pattern in _RATE_LIMIT_PATTERNS)


def _rate_limit_delay(attempt: int, backoff: tuple[int, ...]) -> int:
    index = min(max(attempt - 1, 0), len(backoff) - 1)
    return backoff[index]


def _classify_exception(exc: Exception) -> str:
    if _is_rate_limit_error(exc):
        return "rate_limit"
    text = str(exc).lower()
    if any(pattern in text for pattern in _AUTH_PATTERNS):
        return "auth"
    if any(pattern in text for pattern in _PERMISSION_PATTERNS):
        return "permission"
    if any(pattern in text for pattern in _INVALID_REQUEST_PATTERNS):
        return "invalid_request"
    if any(pattern in text for pattern in _TRANSIENT_PATTERNS):
        return "transient"
    return "unknown"


def is_tushare_auth_error(exc: Exception) -> bool:
    if isinstance(exc, TushareAuthError):
        return True
    return _classify_exception(exc) == "auth"


def _params_hash(kwargs: dict[str, Any]) -> str:
    payload = json.dumps(kwargs, sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _http_host(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    return parsed.netloc or parsed.path


def _coerce_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


def _coerce_backoff(value: Any, default: tuple[int, ...]) -> tuple[int, ...]:
    if isinstance(value, str):
        parts = [p.strip() for p in value.split(",") if p.strip()]
    elif isinstance(value, (list, tuple)):
        parts = [str(v).strip() for v in value if str(v).strip()]
    else:
        parts = []
    parsed: list[int] = []
    for part in parts:
        try:
            parsed.append(max(1, int(float(part))))
        except ValueError:
            continue
    return tuple(parsed) if parsed else default
