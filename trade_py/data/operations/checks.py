from __future__ import annotations

import json
import sqlite3
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from trade_py.data.operations.contracts import ExitCode, OperationResult
from trade_py.data.operations.profiles import get_profile
from trade_py.data.operations.sqlite_ro import connect_read_only


_STEP_DATASETS = {
    "kline": (("market", "kline"),),
    "index": (("market", "index"),),
    "fund-flow": (("market", "fund_flow"),),
    "northbound": (("market", "northbound"),),
    "btc-assurance": (("market", "crypto", "btc.parquet"),),
    "crypto-assets": (
        ("market", "crypto", "eth.parquet"),
        ("market", "crypto", "sol.parquet"),
        ("market", "crypto", "bnb.parquet"),
        ("market", "crypto", "xrp.parquet"),
    ),
    "fundamental": (("market", "fundamental"),),
    "macro": (("market", "macro"),),
}

_FRESHNESS_WARN_DAYS = {
    "kline": 7,
    "index": 7,
    "fund-flow": 7,
    "northbound": 7,
    "btc-assurance": 2,
    "crypto-assets": 2,
    "fundamental": 120,
    "macro": 120,
}


def _parquet_files(path: Path) -> Iterable[Path]:
    if path.is_file() and path.suffix == ".parquet":
        yield path
    elif path.is_dir():
        yield from sorted(path.glob("*.parquet"))


def _parquet_envelope(path: Path) -> tuple[str, str]:
    try:
        size = path.stat().st_size
        if size < 12:
            return "fail", f"file too small ({size} bytes)"
        with path.open("rb") as handle:
            head = handle.read(4)
            handle.seek(-4, 2)
            tail = handle.read(4)
        if head != b"PAR1" or tail != b"PAR1":
            return "fail", "invalid parquet envelope"
        return "pass", f"{size} bytes"
    except OSError as exc:
        return "fail", f"{type(exc).__name__}: {exc}"


def _schema_check(path: Path) -> tuple[str, str, list[str]]:
    try:
        import pyarrow.parquet as pq

        names = list(pq.ParquetFile(path).schema.names)
        date_columns = {"date", "trade_date", "bar_open_at"}
        if not date_columns.intersection(names):
            return "warn", "no recognized date column", names
        return "pass", f"columns={len(names)}", names
    except Exception as exc:
        return "fail", f"{type(exc).__name__}: {exc}", []


def _footer_watermark(path: Path, columns: list[str]) -> str | None:
    date_column = next((name for name in ("date", "trade_date", "bar_open_at") if name in columns), None)
    if date_column is None:
        return None
    try:
        import pyarrow.parquet as pq

        parquet = pq.ParquetFile(path)
        column_index = parquet.schema_arrow.get_field_index(date_column)
        maxima = []
        for row_group in range(parquet.metadata.num_row_groups):
            stats = parquet.metadata.row_group(row_group).column(column_index).statistics
            if stats is not None and stats.has_min_max and stats.max is not None:
                maxima.append(stats.max)
        if not maxima:
            return None
        return str(max(maxima))[:10]
    except Exception:
        return None


def _freshness_item(step_id: str, path: Path, watermark: str | None) -> dict[str, Any]:
    if not watermark:
        return {
            "name": f"freshness:{step_id}:{path.name}",
            "status": "unknown",
            "detail": "footer watermark unavailable",
        }
    try:
        observed = date.fromisoformat(watermark[:10])
        lag_days = max((datetime.now(timezone.utc).date() - observed).days, 0)
    except ValueError:
        return {
            "name": f"freshness:{step_id}:{path.name}",
            "status": "warn",
            "detail": f"invalid watermark={watermark}",
        }
    maximum = _FRESHNESS_WARN_DAYS[step_id]
    return {
        "name": f"freshness:{step_id}:{path.name}",
        "status": "pass" if lag_days <= maximum else "warn",
        "detail": f"watermark={watermark} lag_days={lag_days} warn_after={maximum}",
    }


def _value_check(path: Path, columns: list[str]) -> tuple[str, str]:
    date_column = next((name for name in ("date", "trade_date", "bar_open_at") if name in columns), None)
    if date_column is None:
        return "warn", "value scan skipped: no date column"
    escaped = str(path).replace("'", "''")
    try:
        import duckdb

        conn = duckdb.connect(":memory:")
        try:
            row = conn.execute(
                f"SELECT COUNT(*) AS rows, COUNT(DISTINCT {date_column}) AS dates, "
                f"SUM(CASE WHEN {date_column} IS NULL THEN 1 ELSE 0 END) AS null_dates "
                f"FROM read_parquet('{escaped}')"
            ).fetchone()
            if not row:
                return "fail", "value scan returned no evidence"
            rows, dates, null_dates = (int(value or 0) for value in row)
            if rows == 0:
                return "warn", "zero rows"
            if null_dates:
                return "fail", f"rows={rows} distinct_dates={dates} null_dates={null_dates}"
            if {"open", "high", "low", "close"}.issubset(columns):
                invalid = conn.execute(
                    f"SELECT COUNT(*) FROM read_parquet('{escaped}') WHERE "
                    "open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL OR "
                    "open<=0 OR high<=0 OR low<=0 OR close<=0 OR high<low"
                ).fetchone()[0]
                if int(invalid or 0):
                    return "fail", f"rows={rows} distinct_dates={dates} invalid_ohlc={invalid}"
            return "pass", f"rows={rows} distinct_dates={dates} null_dates=0"
        finally:
            conn.close()
    except Exception as exc:
        return "fail", f"{type(exc).__name__}: {exc}"


def _database_check(root: Path) -> dict[str, Any]:
    path = root / ".db" / "trade.db"
    if not path.is_file():
        return {"name": "trade-db", "status": "unknown", "detail": "database missing"}
    try:
        conn, _mode = connect_read_only(path)
        try:
            quick = conn.execute("PRAGMA quick_check").fetchone()
            tables = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
        finally:
            conn.close()
        missing = sorted({"job_runs", "asset_registry", "schema_migrations"} - tables)
        if not quick or quick[0] != "ok":
            return {"name": "trade-db", "status": "fail", "detail": str(quick)}
        if missing:
            return {"name": "trade-db", "status": "warn", "detail": f"missing tables={missing}"}
        return {"name": "trade-db", "status": "pass", "detail": "quick_check=ok"}
    except sqlite3.Error as exc:
        return {"name": "trade-db", "status": "fail", "detail": f"{type(exc).__name__}: {exc}"}


def _btc_pointer_check(root: Path) -> dict[str, Any]:
    path = root / "market" / "crypto" / "btc_current.json"
    if not path.is_file():
        return {"name": "btc-pointer", "status": "unknown", "detail": "pointer missing"}
    try:
        pointer = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(pointer, dict) or not pointer.get("run_id"):
            raise ValueError("missing run_id")
        manifest_path = Path(str(pointer.get("manifest_path") or ""))
        if not manifest_path.is_file():
            return {
                "name": "btc-pointer",
                "status": "fail",
                "detail": f"manifest missing: {manifest_path}",
            }
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        readiness = str(manifest.get("data_readiness") or "unknown")
        status = (
            "pass"
            if readiness == "ready"
            else ("fail" if readiness == "invalid" else "warn")
        )
        current_created = str(manifest.get("created_at") or "")
        newest: dict[str, Any] | None = None
        newest_path: Path | None = None
        runs_root = root / "market" / "crypto" / "runs" / "btc"
        for candidate_path in runs_root.glob("*/manifest.json"):
            try:
                candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
            if newest is None or str(candidate.get("created_at") or "") > str(
                newest.get("created_at") or ""
            ):
                newest = candidate
                newest_path = candidate_path
        detail = f"run_id={pointer['run_id']} readiness={readiness}"
        if (
            newest is not None
            and str(newest.get("run_id") or "") != str(pointer["run_id"])
            and str(newest.get("created_at") or "") > current_created
        ):
            candidate_readiness = str(newest.get("data_readiness") or "unknown")
            failed_gates = [
                f"{gate.get('gate')}:{gate.get('reason_code')}"
                for gate in (newest.get("gates") or [])
                if gate.get("status") != "pass"
            ]
            if candidate_readiness == "invalid":
                status = "fail"
            elif status == "pass":
                status = "warn"
            detail += (
                f"; latest_candidate={newest.get('run_id')} "
                f"readiness={candidate_readiness} gates={','.join(failed_gates) or '-'} "
                f"manifest={newest_path}"
            )
        return {
            "name": "btc-pointer",
            "status": status,
            "detail": detail,
        }
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return {"name": "btc-pointer", "status": "fail", "detail": f"{type(exc).__name__}: {exc}"}


def _kline_reconciliation_check(root: Path) -> dict[str, Any]:
    path = root / "market" / "kline" / "reconciliation" / "current.json"
    if not path.is_file():
        return {"name": "kline-reconciliation", "status": "unknown", "detail": "artifact missing"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        schema = str(payload.get("schema_version") or "")
        metrics = payload.get("metrics") or {}
        checked = int(metrics.get("checked_rows") or 0)
        blocked = int(metrics.get("block_rows") or 0)
        state = str(payload.get("status") or "unknown")
        if schema != "kline-reconciliation-v1" or checked <= 0:
            status = "fail"
        elif state == "pass" and blocked == 0:
            status = "pass"
        else:
            status = "fail"
        return {
            "name": "kline-reconciliation",
            "status": status,
            "detail": f"schema={schema or '-'} status={state} checked={checked} blocked={blocked}",
        }
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return {
            "name": "kline-reconciliation",
            "status": "fail",
            "detail": f"{type(exc).__name__}: {exc}",
        }


def run_check(data_root: str | Path, *, profile_name: str = "all", full: bool = False) -> OperationResult:
    """Run read-only structural checks, optionally adding bounded value scans."""
    started = time.monotonic()
    root = Path(data_root)
    profile = get_profile(profile_name)
    items: list[dict[str, Any]] = [_database_check(root)]
    if profile_name in {"core", "all"}:
        items.append(_kline_reconciliation_check(root))
    if profile_name in {"crypto", "all"}:
        items.append(_btc_pointer_check(root))

    seen: set[Path] = set()
    for step in profile.steps:
        paths = [root.joinpath(*parts) for parts in _STEP_DATASETS[step.step_id]]
        matched = [file for path in paths for file in _parquet_files(path)]
        if not matched:
            items.append({
                "name": step.step_id,
                "status": "unknown",
                "detail": f"no parquet evidence at {', '.join(str(path) for path in paths)}",
            })
            continue
        for path in matched:
            if path in seen:
                continue
            seen.add(path)
            envelope_status, envelope_detail = _parquet_envelope(path)
            if envelope_status == "fail":
                items.append({"name": str(path), "status": "fail", "detail": envelope_detail})
                continue
            schema_status, schema_detail, columns = _schema_check(path)
            status = schema_status
            detail = f"{envelope_detail}; {schema_detail}"
            items.append(_freshness_item(step.step_id, path, _footer_watermark(path, columns)))
            if full and schema_status != "fail":
                value_status, value_detail = _value_check(path, columns)
                detail = f"{detail}; {value_detail}"
                if value_status == "fail" or (value_status == "warn" and status == "pass"):
                    status = value_status
            items.append({"name": str(path), "status": status, "detail": detail})

    counts = {
        state: sum(1 for item in items if item["status"] == state)
        for state in ("pass", "warn", "fail", "unknown")
    }
    if counts["fail"]:
        status = "fail"
        exit_code = ExitCode.FAILURE
    elif counts["warn"] or counts["unknown"]:
        status = "warn"
        exit_code = ExitCode.WARN
    else:
        status = "pass"
        exit_code = ExitCode.PASS
    return OperationResult(
        operation="check-full" if full else "check",
        profile=profile.name,
        profile_version=profile.version,
        status=status,
        exit_code=int(exit_code),
        observed=bool(seen or (root / ".db" / "trade.db").exists()),
        elapsed_ms=int((time.monotonic() - started) * 1000),
        evidence={"counts": counts, "checked_files": len(seen), "items": items},
    )
