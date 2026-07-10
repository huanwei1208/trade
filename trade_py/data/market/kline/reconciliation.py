from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd

from trade_py.data.market.kline.providers import (
    AkshareKlineProvider,
    BaostockKlineProvider,
    KlineProvider,
    TencentKlineProvider,
    ensure_symbol,
)
from trade_py.data.paths import KLINE_DIR, KLINE_MANIFEST

KLINE_RECONCILIATION_SCHEMA_VERSION = "kline-reconciliation-v1"


@dataclass(frozen=True)
class KlineReconciliationConfig:
    start: str
    end: str
    symbols: tuple[str, ...]
    shadow_provider: str = "akshare"
    adjust: str = "none"
    warn_basis_pct: float = 0.5
    block_basis_pct: float = 2.0
    minimum_checked_rows: int = 1


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_symbol(symbol: str) -> str:
    return ensure_symbol(symbol).replace(".", "_")


def _reconciliation_root(data_root: str | Path) -> Path:
    return KLINE_DIR(data_root) / "reconciliation"


def current_reconciliation_path(data_root: str | Path) -> Path:
    return _reconciliation_root(data_root) / "current.json"


def _provider_by_name(name: str) -> KlineProvider:
    normalized = str(name or "").strip().lower()
    if normalized == "akshare":
        return AkshareKlineProvider()
    if normalized == "tencent":
        return TencentKlineProvider()
    if normalized == "baostock":
        return BaostockKlineProvider()
    raise ValueError(f"unsupported kline shadow provider: {name!r}")


def _read_local_kline(data_root: str | Path, symbol: str, start: str, end: str) -> pd.DataFrame:
    path = KLINE_DIR(data_root) / f"{_safe_symbol(symbol)}.parquet"
    if not path.exists():
        return pd.DataFrame()
    frame = pd.read_parquet(path)
    if frame.empty or "date" not in frame.columns:
        return pd.DataFrame()
    work = frame.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    work = work[(work["date"] >= start) & (work["date"] <= end)].copy()
    return work.sort_values("date").reset_index(drop=True)


def _normalize_shadow(frame: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    if frame is None or frame.empty or "date" not in frame.columns:
        return pd.DataFrame()
    work = frame.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    work = work[(work["date"] >= start) & (work["date"] <= end)].copy()
    return work.sort_values("date").reset_index(drop=True)


def _basis_status(basis_pct: float, warn_basis_pct: float, block_basis_pct: float) -> str:
    magnitude = abs(float(basis_pct))
    if magnitude > block_basis_pct:
        return "block"
    if magnitude > warn_basis_pct:
        return "warn"
    return "pass"


def _compare_symbol(
    *,
    symbol: str,
    canonical: pd.DataFrame,
    shadow: pd.DataFrame,
    config: KlineReconciliationConfig,
) -> pd.DataFrame:
    if canonical.empty or shadow.empty:
        return pd.DataFrame()
    required = {"date", "close"}
    if not required.issubset(canonical.columns) or not required.issubset(shadow.columns):
        return pd.DataFrame()
    left = canonical[["date", "close"]].rename(columns={"close": "canonical_close"})
    right = shadow[["date", "close"]].rename(columns={"close": "shadow_close"})
    merged = left.merge(right, on="date", how="inner")
    if merged.empty:
        return pd.DataFrame()
    merged["symbol"] = symbol
    merged["canonical_close"] = pd.to_numeric(merged["canonical_close"], errors="coerce")
    merged["shadow_close"] = pd.to_numeric(merged["shadow_close"], errors="coerce")
    merged["basis_pct"] = (
        (merged["canonical_close"] - merged["shadow_close"]).abs()
        / merged["shadow_close"].abs().where(merged["shadow_close"].abs() > 0)
        * 100.0
    )
    merged["status"] = merged["basis_pct"].map(
        lambda value: _basis_status(
            float(value) if pd.notna(value) else float("inf"),
            config.warn_basis_pct,
            config.block_basis_pct,
        )
    )
    merged["reason_code"] = merged["status"].map({
        "pass": None,
        "warn": "CLOSE_BASIS_WARN",
        "block": "CLOSE_BASIS_BLOCK",
    })
    return merged[
        ["symbol", "date", "canonical_close", "shadow_close", "basis_pct", "status", "reason_code"]
    ].reset_index(drop=True)


def _manifest_hash(data_root: str | Path) -> str | None:
    path = KLINE_MANIFEST(data_root)
    if not path.exists():
        return None
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _artifact_payload(
    *,
    config: KlineReconciliationConfig,
    reconciliation: pd.DataFrame,
    data_root: str | Path,
    provider_errors: list[dict[str, Any]],
) -> dict[str, Any]:
    checked_rows = int(len(reconciliation))
    block_rows = int((reconciliation["status"] == "block").sum()) if checked_rows else 0
    warn_rows = int((reconciliation["status"] == "warn").sum()) if checked_rows else 0
    max_basis = (
        round(float(reconciliation["basis_pct"].max()), 6)
        if checked_rows and "basis_pct" in reconciliation.columns
        else None
    )
    status = "pass" if checked_rows >= config.minimum_checked_rows and block_rows == 0 else "fail"
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return {
        "schema_version": KLINE_RECONCILIATION_SCHEMA_VERSION,
        "run_id": _sha256_text(
            json.dumps(
                {
                    "symbols": config.symbols,
                    "start": config.start,
                    "end": config.end,
                    "shadow_provider": config.shadow_provider,
                    "observed_at": now,
                },
                sort_keys=True,
            )
        )[:24],
        "status": status,
        "observed_at": now,
        "providers": {
            "primary": "local_parquet",
            "shadow": [config.shadow_provider],
        },
        "primary_source": "local_parquet",
        "shadow_sources": [config.shadow_provider],
        "config": {
            "start": config.start,
            "end": config.end,
            "symbols": list(config.symbols),
            "adjust": config.adjust,
            "warn_basis_pct": config.warn_basis_pct,
            "block_basis_pct": config.block_basis_pct,
            "minimum_checked_rows": config.minimum_checked_rows,
        },
        "kline_manifest_hash": _manifest_hash(data_root),
        "metrics": {
            "checked_rows": checked_rows,
            "symbols_requested": len(config.symbols),
            "symbols_compared": int(reconciliation["symbol"].nunique()) if checked_rows else 0,
            "block_rows": block_rows,
            "warn_rows": warn_rows,
            "max_close_basis_pct": max_basis,
            "provider_errors": len(provider_errors),
        },
        "sample": (
            reconciliation.head(10).assign(
                basis_pct=lambda frame: frame["basis_pct"].round(6)
            ).to_dict(orient="records")
            if checked_rows
            else []
        ),
        "provider_errors": provider_errors[:10],
    }


def write_reconciliation_artifact(data_root: str | Path, payload: dict[str, Any]) -> Path:
    path = current_reconciliation_path(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)
    return path


def reconcile_kline(
    data_root: str | Path,
    *,
    symbols: list[str],
    start: str,
    end: str,
    shadow_provider: str = "akshare",
    adjust: str = "none",
    warn_basis_pct: float = 0.5,
    block_basis_pct: float = 2.0,
    minimum_checked_rows: int = 1,
    provider: KlineProvider | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    normalized_symbols = tuple(sorted({ensure_symbol(symbol) for symbol in symbols if str(symbol).strip()}))
    if not normalized_symbols:
        raise ValueError("at least one symbol is required for kline reconciliation")
    config = KlineReconciliationConfig(
        start=start,
        end=end,
        symbols=normalized_symbols,
        shadow_provider=str(shadow_provider or "").strip().lower(),
        adjust=adjust,
        warn_basis_pct=float(warn_basis_pct),
        block_basis_pct=float(block_basis_pct),
        minimum_checked_rows=int(minimum_checked_rows),
    )
    shadow = provider or _provider_by_name(config.shadow_provider)
    frames: list[pd.DataFrame] = []
    provider_errors: list[dict[str, Any]] = []
    for symbol in normalized_symbols:
        canonical = _read_local_kline(data_root, symbol, config.start, config.end)
        if canonical.empty:
            provider_errors.append({
                "symbol": symbol,
                "provider": "local_parquet",
                "error_kind": "missing_local_data",
                "error_message": "local kline parquet has no rows in requested range",
            })
            continue
        try:
            shadow_frame = _normalize_shadow(
                shadow.fetch(symbol=symbol, start=config.start, end=config.end, adjust=config.adjust),
                config.start,
                config.end,
            )
        except Exception as exc:
            provider_errors.append({
                "symbol": symbol,
                "provider": getattr(shadow, "name", config.shadow_provider),
                "error_kind": type(exc).__name__,
                "error_message": str(exc),
            })
            continue
        compared = _compare_symbol(
            symbol=symbol,
            canonical=canonical,
            shadow=shadow_frame,
            config=config,
        )
        if compared.empty:
            provider_errors.append({
                "symbol": symbol,
                "provider": getattr(shadow, "name", config.shadow_provider),
                "error_kind": "no_aligned_rows",
                "error_message": "no overlapping close rows for requested range",
            })
            continue
        frames.append(compared)

    reconciliation = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
        columns=["symbol", "date", "canonical_close", "shadow_close", "basis_pct", "status", "reason_code"]
    )
    payload = _artifact_payload(
        config=config,
        reconciliation=reconciliation,
        data_root=data_root,
        provider_errors=provider_errors,
    )
    if not dry_run:
        payload["artifact_path"] = str(write_reconciliation_artifact(data_root, payload))
    else:
        payload["artifact_path"] = str(current_reconciliation_path(data_root))
        payload["dry_run"] = True
    return payload
