from __future__ import annotations

import sqlite3
from pathlib import Path


def connect_read_only(path: Path, *, timeout: float = 0.2) -> tuple[sqlite3.Connection, str]:
    """Open SQLite without writes while preserving visibility of an active WAL."""

    wal_path = Path(f"{path}-wal")
    shm_path = Path(f"{path}-shm")
    if wal_path.exists() and shm_path.exists():
        suffix = "?mode=ro"
        mode = "ro-wal-aware"
    elif not wal_path.exists() or wal_path.stat().st_size == 0:
        # With no pending WAL frames, immutable mode prevents SQLite from
        # creating empty -wal/-shm sidecars for a database configured as WAL.
        suffix = "?mode=ro&immutable=1"
        mode = "ro-immutable-no-wal"
    else:
        raise sqlite3.OperationalError(
            f"non-empty WAL has no shared-memory sidecar: {wal_path}"
        )
    uri = f"file:{path.resolve().as_posix()}{suffix}"
    return sqlite3.connect(uri, uri=True, timeout=timeout), mode
