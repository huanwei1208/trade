#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pandas as pd

from trade_py.data.paths import KLINE_DIR, KLINE_MANIFEST
from trade_py.db.instruments_db import InstrumentsDB

COLUMN_ORDER = [
    "symbol", "date", "open", "high", "low", "close",
    "volume", "amount", "turnover_rate", "prev_close", "vwap",
]


@dataclass
class SymbolMigration:
    symbol: str
    rows: int
    date_min: str | None
    date_max: str | None
    source_files: int
    source_bytes: int
    output_bytes: int = 0
    skipped: bool = False
    error: str | None = None


def _safe_symbol(symbol: str) -> str:
    return symbol.replace(".", "_")


def _canonical_symbol(name: str) -> str:
    if "." in name:
        return name
    if "_" not in name:
        return name
    head, tail = name.rsplit("_", 1)
    return f"{head}.{tail}"


def _normalize_frame(symbol: str, frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=COLUMN_ORDER)
    work = frame.copy()
    work["symbol"] = symbol
    work["date"] = work["date"].astype(str).str[:10]
    work = work.dropna(subset=["date"])
    work = work.drop_duplicates(subset=["date"], keep="last")
    work = work.sort_values("date").reset_index(drop=True)
    for col in COLUMN_ORDER:
        if col not in work.columns:
            work[col] = 0.0 if col != "symbol" else symbol
    work["symbol"] = work["symbol"].fillna(symbol)
    return work[COLUMN_ORDER]


def _build_source_index(kline_root: Path) -> dict[str, list[Path]]:
    monthly: dict[str, list[Path]] = {}
    for path in sorted(kline_root.glob("20??-??/*.parquet")):
        monthly.setdefault(path.stem, []).append(path)

    indexed = {safe: paths for safe, paths in monthly.items()}
    for path in sorted(kline_root.glob("*.parquet")):
        if path.name == "_manifest.json":
            continue
        indexed.setdefault(path.stem, [path])
    return indexed


def _iter_symbols(source_index: dict[str, list[Path]], data_root: Path) -> list[str]:
    symbols: set[str] = {_canonical_symbol(name) for name in source_index.keys()}
    try:
        db = InstrumentsDB(data_root)
        symbols.update(db.get_all_symbols())
    except Exception:
        pass
    return sorted(symbols)


def _read_symbol_sources(symbol: str, source_index: dict[str, list[Path]]) -> tuple[pd.DataFrame, list[Path]]:
    sources = source_index.get(_safe_symbol(symbol), [])
    if not sources:
        return pd.DataFrame(columns=COLUMN_ORDER), []
    frames = [pd.read_parquet(path) for path in sources]
    return _normalize_frame(symbol, pd.concat(frames, ignore_index=True)), sources


def _write_symbol_flat(kline_root: Path, symbol: str, frame: pd.DataFrame) -> int:
    safe = _safe_symbol(symbol)
    target = kline_root / f"{safe}.parquet"
    temp = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
    frame.to_parquet(temp, index=False)
    temp.replace(target)
    return target.stat().st_size


def _write_manifest(data_root: Path, entries: dict[str, dict[str, object]]) -> None:
    manifest_path = KLINE_MANIFEST(data_root)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    payload = {
        "dataset": "kline",
        "layout": "per_symbol",
        "schema_version": 2,
        "columns": COLUMN_ORDER,
        "primary_key": ["symbol", "date"],
        "last_compaction": now,
        "entries": entries,
    }
    temp = manifest_path.with_name(f".{manifest_path.name}.{uuid4().hex}.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(manifest_path)


def _archive_monthly_dirs(data_root: Path, kline_root: Path) -> int:
    archive_root = data_root.parent / f"{data_root.name}_archive" / "kline_monthly"
    archive_root.mkdir(parents=True, exist_ok=True)
    moved = 0
    for month_dir in sorted(kline_root.glob("20??-??")):
        if not month_dir.is_dir():
            continue
        target = archive_root / month_dir.name
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(month_dir), str(target))
        moved += 1
    return moved


def _migrate_one(symbol: str, source_index: dict[str, list[Path]]) -> tuple[pd.DataFrame, SymbolMigration]:
    try:
        frame, sources = _read_symbol_sources(symbol, source_index)
        if frame.empty:
            return frame, SymbolMigration(symbol=symbol, rows=0, date_min=None, date_max=None, source_files=0, source_bytes=0, skipped=True)
        source_bytes = sum(path.stat().st_size for path in sources if path.exists())
        result = SymbolMigration(
            symbol=symbol,
            rows=len(frame),
            date_min=str(frame["date"].min()) if not frame.empty else None,
            date_max=str(frame["date"].max()) if not frame.empty else None,
            source_files=len(sources),
            source_bytes=source_bytes,
        )
        return frame, result
    except Exception as exc:
        return pd.DataFrame(columns=COLUMN_ORDER), SymbolMigration(
            symbol=symbol,
            rows=0,
            date_min=None,
            date_max=None,
            source_files=0,
            source_bytes=0,
            error=f"{type(exc).__name__}: {exc}",
        )


def run(args: argparse.Namespace) -> int:
    data_root = Path(args.data_root)
    kline_root = KLINE_DIR(data_root)
    kline_root.mkdir(parents=True, exist_ok=True)
    source_index = _build_source_index(kline_root)
    symbols = _iter_symbols(source_index, data_root)
    if args.symbols:
        wanted = {_canonical_symbol(item.strip()) for item in args.symbols.split(",") if item.strip()}
        symbols = [symbol for symbol in symbols if symbol in wanted]
    if args.limit:
        symbols = symbols[: max(0, int(args.limit))]
    entries: dict[str, dict[str, object]] = {}
    results: list[SymbolMigration] = []

    with ThreadPoolExecutor(max_workers=max(1, int(args.parallel))) as executor:
        for frame, result in executor.map(lambda sym: _migrate_one(sym, source_index), symbols):
            results.append(result)
            if result.error or result.skipped:
                continue
            if not args.dry_run:
                result.output_bytes = _write_symbol_flat(kline_root, result.symbol, frame)
            entries[_safe_symbol(result.symbol)] = {
                "rows": result.rows,
                "date_min": result.date_min,
                "date_max": result.date_max,
                "bytes": result.output_bytes if not args.dry_run else result.source_bytes,
                "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            }

    if not args.dry_run:
        _write_manifest(data_root, entries)
        archived = _archive_monthly_dirs(data_root, kline_root) if args.archive_monthly else 0
    else:
        archived = 0

    summary = {
        "symbols_total": len(symbols),
        "symbols_migrated": sum(1 for item in results if not item.skipped and not item.error),
        "symbols_skipped": sum(1 for item in results if item.skipped),
        "symbols_failed": sum(1 for item in results if item.error),
        "total_rows": sum(item.rows for item in results if not item.error),
        "source_files": sum(item.source_files for item in results if not item.error),
        "source_bytes": sum(item.source_bytes for item in results if not item.error),
        "output_bytes": sum(item.output_bytes for item in results if not item.error),
        "archived_month_dirs": archived,
        "dry_run": bool(args.dry_run),
        "failures": [item.__dict__ for item in results if item.error][:20],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if summary["symbols_failed"] else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Consolidate monthly kline shards into per-symbol parquet files.")
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--parallel", type=int, default=4)
    parser.add_argument("--archive-monthly", action="store_true", help="Move legacy YYYY-MM directories to a sibling data_archive directory after a successful run.")
    parser.add_argument("--symbols", default="", help="Optional comma-separated symbol list for focused verification.")
    parser.add_argument("--limit", type=int, default=0, help="Optional symbol limit for focused verification.")
    return parser


if __name__ == "__main__":
    raise SystemExit(run(build_parser().parse_args()))
