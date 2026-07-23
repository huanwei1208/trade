from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from trade_py.data.operations.contracts import ExitCode, OperationResult
from trade_py.data.operations.profiles import PROFILES
from trade_py.data.operations.sqlite_ro import connect_read_only


_DATASET_DIRS = {
    "kline": ("market", "kline"),
    "index": ("market", "index"),
    "fund-flow": ("market", "fund_flow"),
    "northbound": ("market", "northbound"),
    "crypto": ("market", "crypto"),
    "fx": ("market", "fx"),
    "commodity": ("market", "commodity"),
    "fundamental": ("market", "fundamental"),
    "macro": ("market", "macro"),
}


def _directory_metadata(path: Path) -> dict[str, Any]:
    if not path.is_dir():
        return {"observed": False, "files": 0, "bytes": 0, "latest_mtime": None}
    files = 0
    total_bytes = 0
    latest_mtime = 0.0
    try:
        with os.scandir(path) as entries:
            for entry in entries:
                if not entry.is_file(follow_symlinks=False) or not entry.name.endswith(".parquet"):
                    continue
                files += 1
                stat = entry.stat(follow_symlinks=False)
                total_bytes += int(stat.st_size)
                latest_mtime = max(latest_mtime, float(stat.st_mtime))
    except OSError as exc:
        return {
            "observed": True,
            "files": files,
            "bytes": total_bytes,
            "latest_mtime": None,
            "error": f"{type(exc).__name__}: {exc}",
        }
    return {
        "observed": True,
        "files": files,
        "bytes": total_bytes,
        "latest_mtime": (
            datetime.fromtimestamp(latest_mtime, tz=timezone.utc).isoformat()
            if latest_mtime
            else None
        ),
    }


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return bool(
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
    )


def _database_metadata(db_path: Path) -> dict[str, Any]:
    if not db_path.is_file():
        return {"observed": False, "path": str(db_path)}
    payload: dict[str, Any] = {
        "observed": True,
        "path": str(db_path),
        "bytes": db_path.stat().st_size,
        "mode": None,
        "assets": [],
        "latest_jobs": {},
    }
    try:
        conn, mode = connect_read_only(db_path)
        payload["mode"] = mode
        conn.row_factory = sqlite3.Row
        try:
            if _table_exists(conn, "asset_registry"):
                rows = conn.execute(
                    "SELECT asset_class, COUNT(*) AS total, "
                    "SUM(CASE WHEN enabled=1 THEN 1 ELSE 0 END) AS enabled, "
                    "MAX(watermark_date) AS watermark, "
                    "SUM(CASE WHEN last_sync_status='error' THEN 1 ELSE 0 END) AS errors "
                    "FROM asset_registry GROUP BY asset_class ORDER BY asset_class"
                ).fetchall()
                payload["assets"] = [dict(row) for row in rows]
            if _table_exists(conn, "job_runs"):
                job_names = sorted(
                    {step.job_name for profile in PROFILES.values() for step in profile.steps}
                )
                placeholders = ",".join("?" for _ in job_names)
                rows = conn.execute(
                    "SELECT j.job_name, j.status, j.started_at, j.completed_at, "
                    "j.elapsed_ms, j.result_summary FROM job_runs j "
                    "JOIN (SELECT job_name, MAX(id) AS id FROM job_runs "
                    f"WHERE job_name IN ({placeholders}) GROUP BY job_name) latest "
                    "ON latest.id=j.id ORDER BY j.job_name",
                    job_names,
                ).fetchall()
                payload["latest_jobs"] = {row["job_name"]: dict(row) for row in rows}
        finally:
            conn.close()
    except (OSError, sqlite3.Error) as exc:
        payload["error"] = f"{type(exc).__name__}: {exc}"
    return payload


def _btc_pointer(root: Path) -> dict[str, Any]:
    pointer_path = root / "market" / "crypto" / "btc_current.json"
    if not pointer_path.is_file():
        return {"observed": False, "path": str(pointer_path)}
    try:
        value = json.loads(pointer_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("expected JSON object")
        return {
            "observed": True,
            "path": str(pointer_path),
            "run_id": value.get("run_id"),
            "manifest_path": value.get("manifest_path"),
            "canonical_hash": value.get("canonical_hash"),
        }
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return {
            "observed": True,
            "path": str(pointer_path),
            "error": f"{type(exc).__name__}: {exc}",
        }


def _profile_status(name: str, latest_jobs: dict[str, Any]) -> dict[str, Any]:
    profile = PROFILES[name]
    steps = []
    for step in profile.steps:
        job = latest_jobs.get(step.job_name)
        steps.append(
            {
                "step_id": step.step_id,
                "job_name": step.job_name,
                "status": str(job.get("status")) if job else "unknown",
                "completed_at": job.get("completed_at") if job else None,
            }
        )
    observed = [step for step in steps if step["status"] != "unknown"]
    if any(step["status"] == "error" for step in observed):
        status = "fail"
    elif len(observed) == len(steps) and all(step["status"] == "ok" for step in observed):
        status = "pass"
    elif observed:
        status = "warn"
    else:
        status = "unknown"
    return {"status": status, "steps": steps}


def read_status(data_root: str | Path) -> OperationResult:
    """Read compact operational metadata without creating or migrating anything."""
    started = time.monotonic()
    root = Path(data_root)
    db = _database_metadata(root / ".db" / "trade.db")
    artifacts = {
        name: _directory_metadata(root.joinpath(*parts))
        for name, parts in _DATASET_DIRS.items()
    }
    latest_jobs = db.get("latest_jobs") or {}
    profiles = {name: _profile_status(name, latest_jobs) for name in PROFILES}
    observed = bool(root.exists() and (db.get("observed") or any(
        item.get("files", 0) for item in artifacts.values()
    )))
    errors = [
        str(item.get("error"))
        for item in [db, *artifacts.values()]
        if item.get("error")
    ]
    if errors or any(profile["status"] == "fail" for profile in profiles.values()):
        status = "fail"
        exit_code = ExitCode.FAILURE
    elif not observed or any(profile["status"] in {"unknown", "warn"} for profile in profiles.values()):
        status = "warn"
        exit_code = ExitCode.WARN
    else:
        status = "pass"
        exit_code = ExitCode.PASS
    return OperationResult(
        operation="status",
        status=status,
        exit_code=int(exit_code),
        observed=observed,
        elapsed_ms=int((time.monotonic() - started) * 1000),
        evidence={
            "data_root": str(root),
            "database": db,
            "artifacts": artifacts,
            "btc": _btc_pointer(root),
            "profiles": profiles,
            "errors": errors,
        },
    )
