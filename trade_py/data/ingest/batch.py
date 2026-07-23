from __future__ import annotations

"""Batch ingest engine with QPS control, watermark tracking, buffered writes, WAL, and concurrency isolation."""

import contextlib
import fcntl
import logging
import os
import shutil
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
from trade_py.data.paths import CRYPTO_DIR, FX_DIR, COMMODITY_DIR
from trade_py.db.trade_db import TradeDB

logger = logging.getLogger(__name__)

# Migration sentinel filename placed in data_root after a successful migration run
# so we don't repeatedly re-scan.
_MIGRATION_SENTINEL = ".cross_asset_migrated"

# Assets with assurance/audit requirements must never be written by the generic
# batch engine. Their dedicated service owns the canonical parquet and pointer.
_SPECIALIZED_ASSET_WRITERS = {"crypto.btc": "btc_assurance"}


class ExistingDataReadError(RuntimeError):
    """Existing canonical data cannot be read safely."""


class WalReadError(RuntimeError):
    """An existing write-ahead log cannot be read safely."""


class UnexpectedEmptyProviderResponse(RuntimeError):
    """A provider returned no rows without evidence that the asset is current."""


# ── Legacy path mappings ──────────────────────────────────────────────────────
# Maps from (asset_class, symbol_lower) -> relative legacy path under market/cross_asset/.
# Used so that _find_existing_path can locate data that was written before the
# per-asset-class directory split.

_LEGACY_CRYPTO_SUBDIR = "crypto"  # cross_asset/crypto/btc.parquet etc.

# FX legacy names: fx.USDCNH -> fx_cnh.parquet (also accepted: usdcnh.parquet in fx dir already)
_FX_LEGACY_FNAME = {
    "usdcnh": "fx_cnh.parquet",
}

# Commodity legacy names: commodity.gold -> gold.parquet (in cross_asset root)
_COMMODITY_LEGACY_FNAME = {
    "gold": "gold.parquet",
    "au99.99": "gold.parquet",
}


def _asset_class_dir(data_root: Path, asset_class: str) -> Path:
    """Return the canonical output directory for an asset class, creating it if needed."""
    if asset_class == "crypto":
        return Path(CRYPTO_DIR(data_root))
    if asset_class == "fx":
        return Path(FX_DIR(data_root))
    if asset_class == "commodity":
        return Path(COMMODITY_DIR(data_root))
    # Fallback for unknown / future classes: data/market/<asset_class>/
    p = data_root / "market" / asset_class
    p.mkdir(parents=True, exist_ok=True)
    return p


def _canonical_output_path(data_root: Path, asset: dict) -> Path:
    """Return the canonical (new-layout) output path for an asset.

    crypto.<SYM>    -> market/crypto/<sym_lower>.parquet
    fx.<SYM>        -> market/fx/<sym_lower>.parquet
    commodity.<SYM> -> market/commodity/<sym_lower>.parquet
    Other classes   -> market/<class>/<sym_lower>.parquet
    """
    asset_class = asset["asset_class"]
    sym = asset["symbol"].lower()
    return _asset_class_dir(data_root, asset_class) / f"{sym}.parquet"


def _legacy_output_path(data_root: Path, asset: dict) -> Path | None:
    """Return the legacy cross_asset path for an asset, or None if no legacy mapping exists.

    This is used only for backwards-compatible reads during the migration window.
    """
    cross_asset = data_root / "market" / "cross_asset"
    asset_class = asset["asset_class"]
    asset_id = asset.get("asset_id", "")
    sym = asset["symbol"].lower()

    if asset_class == "crypto":
        # crypto lived under cross_asset/crypto/<sym>.parquet AND for BTC also cross_asset/btc.parquet
        # We return the subdir path as the primary legacy location.
        return cross_asset / _LEGACY_CRYPTO_SUBDIR / f"{sym}.parquet"

    if asset_class == "fx":
        slug = asset_id.split(".", 1)[1] if "." in asset_id else sym
        legacy_name = _FX_LEGACY_FNAME.get(slug.lower(), f"fx_{slug.lower()}.parquet")
        return cross_asset / legacy_name

    if asset_class == "commodity":
        slug = asset_id.split(".", 1)[1] if "." in asset_id else sym
        legacy_name = _COMMODITY_LEGACY_FNAME.get(slug.lower(), f"{slug.lower()}.parquet")
        return cross_asset / legacy_name

    return None


def _find_existing_path(data_root: Path, asset: dict) -> Path | None:
    """Resolve the path to load existing data from.

    Preference order:
      1. Canonical new-layout path (if file exists).
      2. Legacy cross_asset path (if file exists) - for backwards compat; on next
         write the data will be (re)written to the canonical path and the legacy
         file can be cleaned up manually.
      3. Canonical path (does not exist yet, used for new writes).
    """
    canonical = _canonical_output_path(data_root, asset)
    if canonical.exists():
        return canonical
    legacy = _legacy_output_path(data_root, asset)
    if legacy is not None and legacy.exists():
        logger.info(
            "Asset %s: reading from legacy path %s (will write to %s on next flush)",
            asset.get("asset_id"), legacy, canonical,
        )
        return legacy
    return canonical


def migrate_cross_asset_paths(data_root: str | Path) -> dict[str, int]:
    """One-shot migration from the old market/cross_asset/ layout to the per-class layout.

    Mapping:
      cross_asset/gold.parquet                       -> commodity/gold.parquet
      cross_asset/fx_cnh.parquet                     -> fx/usdcnh.parquet
      cross_asset/crypto/<sym>.parquet (btc,eth,sol) -> crypto/<sym>.parquet
      cross_asset/btc.parquet (assured snapshot)     -> crypto/btc.parquet
      cross_asset/crypto/fear_greed.parquet          -> crypto/fear_greed.parquet

    Skips files whose destination already exists. Returns a dict of counts
    {copied, skipped, missing_src}. Leaves the source cross_asset/ tree intact
    so the migration is non-destructive; operators can delete it after verifying.
    """
    data_root = Path(data_root)
    cross_asset = data_root / "market" / "cross_asset"
    sentinel = data_root / _MIGRATION_SENTINEL

    stats = {"copied": 0, "skipped": 0, "missing_src": 0}

    if sentinel.exists():
        logger.debug("cross_asset migration already completed (sentinel present); skipping")
        return stats

    if not cross_asset.exists():
        # Nothing to migrate; mark done so we don't re-check.
        sentinel.parent.mkdir(parents=True, exist_ok=True)
        sentinel.write_text("no-op: no cross_asset/ directory found\n")
        return stats

    # Ensure target dirs exist
    crypto_dir = Path(CRYPTO_DIR(data_root))
    fx_dir = Path(FX_DIR(data_root))
    commodity_dir = Path(COMMODITY_DIR(data_root))

    def _safe_copy(src: Path, dst: Path) -> str:
        if not src.exists():
            return "missing_src"
        if dst.exists():
            return "skipped"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        logger.info("migrate: %s -> %s", src, dst)
        return "copied"

    # ── commodity ─────────────────────────────────────────────────────────────
    for src_name, dst_name in [("gold.parquet", "gold.parquet")]:
        res = _safe_copy(cross_asset / src_name, commodity_dir / dst_name)
        stats[res] += 1

    # ── fx ────────────────────────────────────────────────────────────────────
    for src_name, dst_name in [("fx_cnh.parquet", "usdcnh.parquet")]:
        res = _safe_copy(cross_asset / src_name, fx_dir / dst_name)
        stats[res] += 1

    # ── crypto (nested subdir) ────────────────────────────────────────────────
    crypto_sub = cross_asset / _LEGACY_CRYPTO_SUBDIR
    if crypto_sub.exists() and crypto_sub.is_dir():
        for src in crypto_sub.glob("*.parquet"):
            res = _safe_copy(src, crypto_dir / src.name)
            stats[res] += 1

    # ── crypto (root-level assured snapshot, e.g. cross_asset/btc.parquet) ────
    # Copy to crypto/<name>.parquet if not already present from the subdir pass.
    for src in cross_asset.glob("*.parquet"):
        # Skip the non-crypto flat files we already handled explicitly.
        if src.name in {"gold.parquet", "fx_cnh.parquet"}:
            continue
        # Heuristic: any other flat parquet in cross_asset/ is treated as a
        # crypto snapshot (e.g. btc.parquet) and copied into crypto/.
        res = _safe_copy(src, crypto_dir / src.name)
        stats[res] += 1

    # Write sentinel so we don't rerun
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.write_text(
        f"cross_asset migration completed. "
        f"copied={stats['copied']} skipped={stats['skipped']} missing_src={stats['missing_src']}\n"
    )
    logger.info(
        "cross_asset migration finished: copied=%d skipped=%d missing_src=%d",
        stats["copied"], stats["skipped"], stats["missing_src"],
    )
    return stats


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
        self.WAL_DIR = self.data_root / ".db" / "wal" / "ingest"
        self._db = db
        self.config = config or BatchIngestConfig()
        self._executor: ThreadPoolExecutor | None = None
        self._write_buffers: dict[str, pd.DataFrame] = {}
        # RLock because _buffer_write may call _flush_asset while holding the lock
        self._buffer_lock = threading.RLock()
        self._rate_limiters: dict[str, TokenBucket] = {}
        self._rate_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._flush_thread: threading.Thread | None = None
        self._migration_run: bool = False
        self._wal_recovered: bool = False
        self._wal_recovery_errors: dict[str, str] = {}
        self._flush_errors: dict[str, str] = {}

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
        """Get the canonical (new-layout) parquet output path for an asset.

        Writes always go to the per-asset-class directory. For reading existing
        data on a migrated-away tree, see _find_existing_path which falls back
        to legacy cross_asset locations.
        """
        return _canonical_output_path(self.data_root, asset)

    def _ensure_migration(self) -> None:
        """Run the cross_asset -> per-class migration exactly once per engine instance."""
        if self._migration_run:
            return
        self._migration_run = True
        try:
            migrate_cross_asset_paths(self.data_root)
        except Exception as e:
            logger.warning("cross_asset migration failed (non-fatal): %s", e)

    def _load_existing(self, path: Path) -> pd.DataFrame | None:
        if path.exists():
            try:
                return pd.read_parquet(path)
            except Exception as exc:
                raise ExistingDataReadError(
                    f"existing parquet is unreadable; refusing overwrite: {path}: {exc}"
                ) from exc
        return None

    def _watermark_date(self, df: pd.DataFrame | None) -> str | None:
        if df is None or df.empty:
            return None
        return pd.to_datetime(df["date"]).max().strftime("%Y-%m-%d")

    def _watermark_proves_current(self, asset: dict, watermark: str | None) -> bool:
        if not watermark:
            return False
        expected = pd.Timestamp.now(tz="UTC").normalize() - pd.Timedelta(days=1)
        if str(asset.get("asset_class") or "") != "crypto":
            while expected.weekday() >= 5:
                expected -= pd.Timedelta(days=1)
        try:
            observed = pd.Timestamp(watermark, tz="UTC").normalize()
        except (TypeError, ValueError):
            return False
        return bool(observed >= expected)

    def _ensure_wal_dir(self) -> Path:
        """Ensure the WAL root directory exists and return its path."""
        self.WAL_DIR.mkdir(parents=True, exist_ok=True)
        return self.WAL_DIR

    def _wal_path(self, asset_id: str) -> Path:
        """Return the path to the WAL parquet file for an asset."""
        return self.WAL_DIR / asset_id / "wal.parquet"

    def _lock_path(self, asset_id: str) -> Path:
        """Return the path to the per-asset flock file."""
        return self.WAL_DIR / f"{asset_id}.lock"

    @contextlib.contextmanager
    def _flock(self, lock_path: Path):
        """Context manager: acquire exclusive flock on lock_path, release on exit.

        Creates the lock file if it does not exist. The lock is automatically
        released by the kernel when the fd is closed (process exit / crash), so
        stale lock files do not block future runs.
        """
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    def _wal_append(self, asset_id: str, df: pd.DataFrame) -> None:
        """Atomically append rows to the per-asset WAL parquet.

        Reads any existing WAL, concatenates with df, deduplicates by date
        (keep="last"), sorts by date, and writes atomically via temp+rename.
        Must be called while holding _buffer_lock (or otherwise serialized).
        """
        wal_path = self._wal_path(asset_id)
        wal_path.parent.mkdir(parents=True, exist_ok=True)
        # Hold the per-asset file lock so concurrent/cross-process appends
        # do not interleave and corrupt the WAL.
        with self._flock(self._lock_path(asset_id)):
            if wal_path.exists():
                try:
                    existing_wal = pd.read_parquet(wal_path)
                    merged = pd.concat([existing_wal, df], ignore_index=True)
                except Exception as exc:
                    raise WalReadError(
                        f"WAL is unreadable; refusing overwrite: {wal_path}: {exc}"
                    ) from exc
            else:
                merged = df.copy()
            merged = merged.drop_duplicates(subset=["date"], keep="last")
            merged = merged.sort_values("date").reset_index(drop=True)
            _atomic_write_parquet(merged, wal_path)

    def _read_wal(self, asset_id: str) -> pd.DataFrame | None:
        """Read and return the WAL data for asset_id, or None if no WAL exists."""
        wal_path = self._wal_path(asset_id)
        if not wal_path.exists():
            return None
        try:
            return pd.read_parquet(wal_path)
        except Exception as exc:
            raise WalReadError(
                f"WAL is unreadable; refusing flush: {wal_path}: {exc}"
            ) from exc

    def _delete_wal(self, asset_id: str) -> None:
        """Remove the WAL file (and its now-empty parent directory) for asset_id."""
        wal_path = self._wal_path(asset_id)
        try:
            if wal_path.exists():
                wal_path.unlink()
            parent = wal_path.parent
            # Remove asset dir if empty; ignore errors if other files remain
            try:
                parent.rmdir()
            except OSError:
                pass
        except Exception as e:
            logger.warning("Failed to delete WAL for %s: %s", asset_id, e)

    def _buffer_write(self, asset_id: str, df: pd.DataFrame) -> None:
        """Add dataframe to WAL then to in-memory buffer; flush if buffer is full.

        WAL append happens BEFORE the data touches the in-memory buffer so that
        a crash after this call returns will still be able to recover via WAL.
        """
        with self._buffer_lock:
            # Persist to WAL first (crash-safe), then update in-memory buffer.
            self._wal_append(asset_id, df)
            if asset_id in self._write_buffers:
                self._write_buffers[asset_id] = pd.concat(
                    [self._write_buffers[asset_id], df], ignore_index=True
                ).drop_duplicates(subset=["date"], keep="last")
            else:
                self._write_buffers[asset_id] = df.copy()
            buf = self._write_buffers[asset_id]
            if len(buf) >= self.config.write_buffer_max_rows:
                self._flush_asset(asset_id)

    def _merge_and_write(
        self,
        asset_id: str,
        path: Path,
        buffer_df: pd.DataFrame | None,
    ) -> str | None:
        """Merge existing parquet + WAL + buffer_df, write atomically, update watermark.

        Caller MUST hold the exclusive flock on the asset lock file before
        calling this method. This performs the entire read-concat-merge-write-
        watermark transaction.

        Returns the new watermark date string (or None if no data).
        """
        # 1. Read existing main parquet
        existing = self._load_existing(path)

        # 2. Read WAL (under lock so no concurrent append can race)
        wal_df = self._read_wal(asset_id)

        # 3. Concat all sources: existing + WAL + buffer
        frames = []
        if existing is not None and not existing.empty:
            frames.append(existing)
        if wal_df is not None and not wal_df.empty:
            frames.append(wal_df)
        if buffer_df is not None and not buffer_df.empty:
            frames.append(buffer_df)

        if not frames:
            return None

        merged = pd.concat(frames, ignore_index=True)
        merged = merged.drop_duplicates(subset=["date"], keep="last")
        merged = merged.sort_values("date").reset_index(drop=True)

        # 4. Atomic write to main parquet
        _atomic_write_parquet(merged, path)

        # 5. Update watermark in DB
        watermark = self._watermark_date(merged)
        db = self._get_db()
        db.asset_registry_update_sync_status(
            asset_id=asset_id,
            status="ok",
            watermark_date=watermark,
            rows=len(merged),
        )

        # 6. Truncate WAL (data is now durable in main parquet)
        self._delete_wal(asset_id)

        return watermark

    def _flush_asset(self, asset_id: str) -> None:
        """Flush buffered data for one asset to disk (canonical new path).

        Holds an exclusive flock across the entire read-WAL+existing, merge,
        write, watermark-update, WAL-truncate transaction to prevent concurrent
        flushes (same process or cross-process) from corrupting data.
        """
        # Pop buffer under the in-memory lock
        with self._buffer_lock:
            if asset_id in self._write_buffers:
                df = self._write_buffers.pop(asset_id)
            else:
                df = None

        if df is None or df.empty:
            # Nothing in buffer; still check if there is a WAL (e.g. recovery
            # path may call _flush_asset directly with empty buffer).
            # Only proceed to flock + merge if a WAL file actually exists.
            if not self._wal_path(asset_id).exists():
                return
            # Fall through with empty buffer; _merge_and_write handles None.

        # Resolve asset metadata and output path
        db = self._get_db()
        asset = db.asset_registry_get(asset_id)
        if not asset:
            raise RuntimeError(f"Cannot flush {asset_id}: asset not found in registry")
        path = self._asset_output_path(asset)

        # Exclusive flock across the whole durable transaction
        lock_path = self._lock_path(asset_id)
        try:
            with self._flock(lock_path):
                self._merge_and_write(asset_id, path, df)
        except Exception:
            # The WAL remains durable. Restore the in-memory buffer as well so
            # a later flush can retry without reporting a false success.
            if df is not None and not df.empty:
                with self._buffer_lock:
                    current = self._write_buffers.get(asset_id)
                    frames = [frame for frame in (current, df) if frame is not None and not frame.empty]
                    if frames:
                        self._write_buffers[asset_id] = (
                            pd.concat(frames, ignore_index=True)
                            .drop_duplicates(subset=["date"], keep="last")
                        )
            raise

    def _recover_wal(self) -> None:
        """Replay any leftover WAL segments into main parquet at startup.

        Scans WAL_DIR for per-asset wal.parquet files and merges each into
        the corresponding main parquet, then truncates the WAL. Called once
        during engine start() before any fetch work begins so a crashed
        process does not lose data that was fetched but not yet flushed.
        """
        wal_root = self.WAL_DIR
        if not wal_root.exists():
            return

        recovered = 0
        for asset_dir in sorted(wal_root.iterdir()):
            if not asset_dir.is_dir():
                continue
            wal_file = asset_dir / "wal.parquet"
            if not wal_file.exists():
                continue
            asset_id = asset_dir.name
            try:
                db = self._get_db()
                asset = db.asset_registry_get(asset_id)
                if not asset:
                    logger.warning(
                        "WAL recovery: asset %s not in registry; skipping (WAL left in place)",
                        asset_id,
                    )
                    continue
                path = self._asset_output_path(asset)
                lock_path = self._lock_path(asset_id)
                with self._flock(lock_path):
                    wm = self._merge_and_write(asset_id, path, buffer_df=None)
                logger.info(
                    "WAL recovery: replayed %s -> %s (watermark=%s)",
                    asset_id, path, wm,
                )
                recovered += 1
            except Exception as e:
                message = f"{type(e).__name__}: {e}"
                self._wal_recovery_errors[asset_id] = message
                logger.error("WAL recovery failed for %s: %s", asset_id, e)

        if recovered:
            logger.info("WAL recovery complete: %d asset(s) recovered", recovered)

    def _flush_all(self) -> dict[str, str]:
        """Flush all buffered writes and return current per-asset failures."""
        with self._buffer_lock:
            asset_ids = list(self._write_buffers.keys())
        for asset_id in asset_ids:
            try:
                self._flush_asset(asset_id)
                self._flush_errors.pop(asset_id, None)
            except Exception as e:
                self._flush_errors[asset_id] = f"{type(e).__name__}: {e}"
                logger.error("Failed to flush %s: %s", asset_id, e)
        return dict(self._flush_errors)

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

        # Canonical write path; existing lookup checks legacy fallback too.
        write_path = self._asset_output_path(asset)
        read_path = _find_existing_path(self.data_root, asset) if not full_refresh else write_path

        last_error = None
        for attempt in range(1, self.config.retry_max_attempts + 1):
            try:
                limiter.acquire()

                # Determine how many days to fetch
                existing = None
                if not full_refresh:
                    existing = self._load_existing(read_path)
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
                    if self._watermark_proves_current(asset, watermark):
                        return IngestResult(
                            asset_id=asset_id,
                            success=True,
                            rows=len(existing) if existing is not None else 0,
                            new_rows=0,
                            watermark_date=watermark,
                            metadata={"outcome": "already_current"},
                        )
                    raise UnexpectedEmptyProviderResponse(
                        f"{asset_id} provider returned zero rows while watermark={watermark or 'missing'} "
                        "does not prove the requested interval is complete"
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
        """Start the engine (allocate thread pool, recover WAL, start flush thread)."""
        if self._executor is None:
            # Run WAL recovery exactly once before any fetch work begins.
            if not self._wal_recovered:
                self._ensure_wal_dir()
                self._recover_wal()
                self._wal_recovered = True
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
            asset_id = str(asset.get("asset_id") or "")
            if asset_id in self._wal_recovery_errors:
                results.append(IngestResult(
                    asset_id=asset_id,
                    success=False,
                    error=f"WAL recovery failed: {self._wal_recovery_errors[asset_id]}",
                ))
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
        flush_errors = self._flush_all()
        for result in results:
            if result.asset_id in flush_errors:
                result.success = False
                result.error = f"durable flush failed: {flush_errors[result.asset_id]}"

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
        """Ingest all enabled assets, optionally filtered by class or symbol list.

        On the first call per engine instance this also runs the one-shot
        cross_asset -> per-class directory migration.
        """
        self._ensure_migration()

        db = self._get_db()
        all_assets = db.asset_registry_list(asset_class=asset_class, enabled_only=True)

        if symbols:
            symbol_set = {s.upper() for s in symbols}
            assets = [a for a in all_assets if a["symbol"].upper() in symbol_set]
        else:
            assets = all_assets

        owned_assets = []
        generic_assets = []
        for asset in assets:
            asset_id = str(asset.get("asset_id") or "").lower()
            owner = _SPECIALIZED_ASSET_WRITERS.get(asset_id)
            if owner:
                owned_assets.append((asset.get("asset_id"), owner))
            else:
                generic_assets.append(asset)
        assets = generic_assets
        for asset_id, owner in owned_assets:
            logger.info("Skipping %s in generic ingest; canonical writer=%s", asset_id, owner)

        if not assets:
            logger.warning("No matching assets found for class=%s symbols=%s", asset_class, symbols)
            return []

        logger.info("Starting batch ingest of %d assets", len(assets))
        return self.ingest_batch(assets, full_refresh=full_refresh, progress_cb=progress_cb)


__all__ = [
    "BatchIngestEngine",
    "BatchIngestConfig",
    "IngestResult",
    "ExistingDataReadError",
    "UnexpectedEmptyProviderResponse",
    "WalReadError",
    "migrate_cross_asset_paths",
]
