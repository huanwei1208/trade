from __future__ import annotations

"""Batch ingest engine with QPS control, watermark tracking, buffered writes, and concurrency isolation."""

import logging
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from trade_py.data.ingest.base import AssetIngestor, IngestResult
from trade_py.data.ingest.crypto import get_ingestor
from trade_py.db.trade_db import TradeDB

logger = logging.getLogger(__name__)


def _atomic_write_parquet(df: pd.DataFrame, path: Path) -> None:
    """Atomically write DataFrame to parquet using temp file + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.parent / f".{path.name}.{uuid.uuid4().hex[:8]}.tmp"
    try:
        df.to_parquet(tmp_path, index=False)
        os.replace(tmp_path, path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise


class TokenBucket:
    """Simple token bucket rate limiter."""

    def __init__(self, rate_per_sec: float, capacity: int | None = None):
        self.rate = rate_per_sec
        self.capacity = capacity or max(1, int(rate_per_sec * 2))
        self._tokens = float(self.capacity)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, tokens: int = 1, timeout: float = 30.0) -> bool:
        """Acquire tokens, blocking if necessary. Returns True if acquired."""
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = now - self._last_refill
                self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
                self._last_refill = now
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return True
            if time.monotonic() > deadline:
                return False
            time.sleep(min(0.05, max(0.001, (tokens - self._tokens) / self.rate)))


@dataclass
class BatchIngestConfig:
    """Configuration for batch ingest engine."""
    max_workers: int = 3  # Dedicated ingest workers, separate from bus workers
    default_interval_ms: int = 300  # Default QPS throttle
    write_buffer_max_rows: int = 10000  # Buffer size before flushing
    write_buffer_timeout_s: float = 5.0  # Max time to hold buffer before flush
    retry_max_attempts: int = 3
    retry_base_delay_s: float = 1.0


class BatchIngestEngine:
    """Batch asset ingest engine with QPS control, watermark tracking, and isolated thread pool."""

    def __init__(
        self,
        data_root: str | Path,
        db: TradeDB | None = None,
        config: BatchIngestConfig | None = None,
    ):
        self.data_root = Path(data_root)
        self._db = db
        self.config = config or BatchIngestConfig()
        self._executor: ThreadPoolExecutor | None = None
        self._write_buffers: dict[str, pd.DataFrame] = {}
        self._buffer_lock = threading.Lock()
        self._rate_limiters: dict[str, TokenBucket] = {}
        self._rate_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._flush_thread: threading.Thread | None = None

    def _get_db(self) -> TradeDB:
        if self._db is None:
            self._db = TradeDB(self.data_root)
        return self._db

    def _get_rate_limiter(self, venue: str, min_interval_ms: int) -> TokenBucket:
        """Get or create per-venue rate limiter."""
        with self._rate_lock:
            if venue not in self._rate_limiters:
                rate_per_sec = 1000.0 / max(min_interval_ms, 100)
                self._rate_limiters[venue] = TokenBucket(rate_per_sec=rate_per_sec)
            return self._rate_limiters[venue]

    def _asset_output_path(self, asset: dict) -> Path:
        """Get parquet output path for an asset."""
        asset_class = asset["asset_class"]
        asset_id = asset["asset_id"]
        if asset_class == "crypto":
            return self.data_root / "market" / "cross_asset" / "crypto" / f"{asset['symbol'].lower()}.parquet"
        elif asset_class == "commodity":
            # Legacy compatibility: commodity.gold -> gold.parquet
            slug = asset_id.split(".", 1)[1] if "." in asset_id else asset["symbol"].lower()
            name_map = {"gold": "gold", "au99.99": "gold"}
            fname = name_map.get(slug.lower(), slug.lower())
            return self.data_root / "market" / "cross_asset" / f"{fname}.parquet"
        elif asset_class == "fx":
            # Legacy compatibility: fx.USDCNH -> fx_cnh.parquet
            slug = asset_id.split(".", 1)[1] if "." in asset_id else asset["symbol"].lower()
            if slug.upper() == "USDCNH":
                return self.data_root / "market" / "cross_asset" / "fx_cnh.parquet"
            return self.data_root / "market" / "cross_asset" / f"fx_{slug.lower()}.parquet"
        else:
            return self.data_root / "market" / asset_class / f"{asset['symbol'].lower()}.parquet"

    def _load_existing(self, path: Path) -> pd.DataFrame | None:
        if path.exists():
            try:
                return pd.read_parquet(path)
            except Exception:
                return None
        return None

    def _watermark_date(self, df: pd.DataFrame | None) -> str | None:
        if df is None or df.empty:
            return None
        return pd.to_datetime(df["date"]).max().strftime("%Y-%m-%d")

    def _buffer_write(self, asset_id: str, df: pd.DataFrame) -> None:
        """Add dataframe to write buffer, flush if buffer is full."""
        with self._buffer_lock:
            if asset_id in self._write_buffers:
                self._write_buffers[asset_id] = pd.concat(
                    [self._write_buffers[asset_id], df], ignore_index=True
                ).drop_duplicates(subset=["date"], keep="last")
            else:
                self._write_buffers[asset_id] = df.copy()
            buf = self._write_buffers[asset_id]
            if len(buf) >= self.config.write_buffer_max_rows:
                self._flush_asset(asset_id)

    def _flush_asset(self, asset_id: str) -> None:
        """Flush buffered data for one asset to disk."""
        with self._buffer_lock:
            if asset_id not in self._write_buffers:
                return
            df = self._write_buffers.pop(asset_id)

        if df.empty:
            return
        # Need to merge with existing on disk
        db = self._get_db()
        asset = db.asset_registry_get(asset_id)
        if not asset:
            return
        path = self._asset_output_path(asset)
        existing = self._load_existing(path)
        if existing is not None:
            df = pd.concat([existing, df], ignore_index=True).drop_duplicates(subset=["date"], keep="last")
        df = df.sort_values("date").reset_index(drop=True)
        _atomic_write_parquet(df, path)

        watermark = self._watermark_date(df)
        db.asset_registry_update_sync_status(
            asset_id=asset_id,
            status="ok",
            watermark_date=watermark,
            rows=len(df),
        )

    def _flush_all(self) -> None:
        """Flush all buffered writes to disk."""
        with self._buffer_lock:
            asset_ids = list(self._write_buffers.keys())
        for asset_id in asset_ids:
            try:
                self._flush_asset(asset_id)
            except Exception as e:
                logger.error("Failed to flush %s: %s", asset_id, e)

    def _ingest_single_asset(
        self,
        asset: dict,
        *,
        full_refresh: bool = False,
    ) -> IngestResult:
        """Ingest a single asset with retries and rate limiting."""
        asset_id = asset["asset_id"]
        venue = asset.get("venue") or "okx"
        min_interval_ms = int(asset.get("min_interval_ms", self.config.default_interval_ms))
        backfill_days = int(asset.get("backfill_days", 730))

        ingestor = get_ingestor(venue)
        limiter = self._get_rate_limiter(venue, min_interval_ms)

        last_error = None
        for attempt in range(1, self.config.retry_max_attempts + 1):
            try:
                limiter.acquire()

                # Determine how many days to fetch
                existing = None
                path = self._asset_output_path(asset)
                if not full_refresh:
                    existing = self._load_existing(path)
                watermark = self._watermark_date(existing)

                if watermark and not full_refresh:
                    start_date = watermark
                    days = (pd.Timestamp.now(tz="UTC").normalize() - pd.Timestamp(watermark, tz="UTC")).days + 2
                else:
                    start_date = None
                    days = backfill_days

                if days <= 0:
                    return IngestResult(
                        asset_id=asset_id,
                        success=True,
                        rows=len(existing) if existing is not None else 0,
                        new_rows=0,
                        watermark_date=watermark,
                    )

                df = ingestor.fetch(asset, days=days, start_date=start_date)
                ingestor.validate_frame(df, asset_id)

                if df.empty:
                    return IngestResult(
                        asset_id=asset_id,
                        success=True,
                        rows=len(existing) if existing is not None else 0,
                        new_rows=0,
                        watermark_date=watermark,
                    )

                new_rows = len(df)
                total_rows = new_rows + (len(existing) if existing is not None else 0)
                new_watermark = self._watermark_date(df)
                if existing is not None:
                    new_watermark = max(str(new_watermark), str(watermark)) if watermark and new_watermark else new_watermark or watermark

                self._buffer_write(asset_id, df)

                return IngestResult(
                    asset_id=asset_id,
                    success=True,
                    rows=total_rows,
                    new_rows=new_rows,
                    watermark_date=str(new_watermark),
                    frame=df,
                )

            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
                logger.warning(
                    "Attempt %d/%d failed for %s: %s",
                    attempt, self.config.retry_max_attempts, asset_id, e,
                )
                if attempt < self.config.retry_max_attempts:
                    delay = self.config.retry_base_delay_s * (2 ** (attempt - 1))
                    time.sleep(delay)

        db = self._get_db()
        db.asset_registry_update_sync_status(
            asset_id=asset_id,
            status="error",
            error=last_error,
        )
        return IngestResult(
            asset_id=asset_id,
            success=False,
            error=last_error,
        )

    def _periodic_flush_loop(self) -> None:
        """Background thread that flushes buffers periodically."""
        while not self._stop_event.is_set():
            time.sleep(self.config.write_buffer_timeout_s)
            try:
                self._flush_all()
            except Exception as e:
                logger.error("Periodic flush failed: %s", e)

    def start(self) -> None:
        """Start the engine (allocate thread pool, start flush thread)."""
        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=self.config.max_workers,
                thread_name_prefix="ingest",
            )
            self._stop_event.clear()
            self._flush_thread = threading.Thread(
                target=self._periodic_flush_loop,
                daemon=True,
                name="ingest-flush",
            )
            self._flush_thread.start()

    def stop(self) -> None:
        """Stop the engine, flush all buffers, shutdown thread pool."""
        self._stop_event.set()
        self._flush_all()
        if self._executor is not None:
            self._executor.shutdown(wait=True)
            self._executor = None

    def _publish_event(self, topic: str, payload: dict[str, Any]) -> None:
        """Publish event to bus if available; silently skip if bus cannot be initialized."""
        try:
            from trade_py.bus import get_bus, Topic
            bus = get_bus(self._get_db())
            bus.publish(topic, payload)
        except Exception:
            pass

    def ingest_batch(
        self,
        assets: list[dict],
        *,
        full_refresh: bool = False,
        progress_cb: Callable[[IngestResult], None] | None = None,
    ) -> list[IngestResult]:
        """Ingest a batch of assets concurrently with QPS control and buffering."""
        if self._executor is None:
            self.start()

        results: list[IngestResult] = []
        futures = {}

        for asset in sorted(assets, key=lambda a: -int(a.get("priority", 5))):
            if not int(asset.get("enabled", 1)):
                continue
            fut = self._executor.submit(self._ingest_single_asset, asset, full_refresh=full_refresh)
            futures[fut] = asset

        for fut in as_completed(futures):
            result = fut.result()
            results.append(result)
            if progress_cb:
                try:
                    progress_cb(result)
                except Exception:
                    pass
            if result.success:
                logger.info(
                    "Ingested %s: %d new rows, watermark=%s",
                    result.asset_id, result.new_rows, result.watermark_date,
                )
                asset = futures[fut]
                self._publish_event("data.asset.ingested", {
                    "asset_id": result.asset_id,
                    "symbol": asset.get("symbol"),
                    "asset_class": asset.get("asset_class"),
                    "new_rows": result.new_rows,
                    "total_rows": result.rows,
                    "watermark_date": result.watermark_date,
                    "venue": asset.get("venue"),
                })
            else:
                logger.error("Failed %s: %s", result.asset_id, result.error)

        # Final flush
        self._flush_all()

        ok_count = sum(1 for r in results if r.success)
        self._publish_event("data.batch.completed", {
            "total": len(results),
            "succeeded": ok_count,
            "failed": len(results) - ok_count,
            "new_rows": sum(r.new_rows for r in results if r.success),
        })

        return results

    def ingest_by_class(
        self,
        asset_class: str | None = None,
        *,
        symbols: list[str] | None = None,
        full_refresh: bool = False,
        progress_cb: Callable[[IngestResult], None] | None = None,
    ) -> list[IngestResult]:
        """Ingest all enabled assets, optionally filtered by class or symbol list."""
        db = self._get_db()
        all_assets = db.asset_registry_list(asset_class=asset_class, enabled_only=True)

        if symbols:
            symbol_set = {s.upper() for s in symbols}
            assets = [a for a in all_assets if a["symbol"].upper() in symbol_set]
        else:
            assets = all_assets

        if not assets:
            logger.warning("No matching assets found for class=%s symbols=%s", asset_class, symbols)
            return []

        logger.info("Starting batch ingest of %d assets", len(assets))
        return self.ingest_batch(assets, full_refresh=full_refresh, progress_cb=progress_cb)


__all__ = ["BatchIngestEngine", "BatchIngestConfig", "IngestResult"]
