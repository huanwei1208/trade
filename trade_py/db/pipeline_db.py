"""SQLite-backed pipeline state store.

High-frequency pipeline state is kept in SQLite with WAL enabled so multiple
CLI commands can read/write without DuckDB's single-writer file lock.

Legacy DuckDB files are migrated once on first open:
  - {data_root}/.db/pipeline.duckdb
  - {data_root}/.pipeline/state.duckdb
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import date, datetime, timezone
from pathlib import Path


def _sqlite_path(data_root: Path) -> Path:
    new_path = data_root / ".db" / "pipeline.db"
    legacy_sqlite = data_root / ".pipeline" / "state.db"
    if new_path.exists() or not legacy_sqlite.exists():
        return new_path
    return legacy_sqlite


def _legacy_duckdb_paths(data_root: Path) -> list[Path]:
    return [
        data_root / ".db" / "pipeline.duckdb",
        data_root / ".pipeline" / "state.duckdb",
    ]


class PipelineDb:
    """Thin wrapper around a local SQLite database for pipeline state."""

    def __init__(self, data_root: Path) -> None:
        db_path = _sqlite_path(data_root)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._con = sqlite3.connect(str(db_path), timeout=30, check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        self._con.execute("PRAGMA journal_mode=WAL")
        self._con.execute("PRAGMA synchronous=NORMAL")
        self._con.execute("PRAGMA busy_timeout=30000")
        self._con.execute("PRAGMA temp_store=MEMORY")
        self._ensure_schema()
        self._maybe_migrate_legacy(data_root)

    def _ensure_schema(self) -> None:
        stmts = [
            """CREATE TABLE IF NOT EXISTS ingest_runs (
                run_id           TEXT PRIMARY KEY,
                source_id        TEXT NOT NULL,
                fetched_at       TEXT NOT NULL,
                date_range_start TEXT,
                date_range_end   TEXT,
                records_fetched  INTEGER DEFAULT 0,
                records_new      INTEGER DEFAULT 0,
                status           TEXT NOT NULL,
                error            TEXT DEFAULT ''
            )""",
            """CREATE TABLE IF NOT EXISTS coverage (
                source_id    TEXT NOT NULL,
                data_date    TEXT NOT NULL,
                record_count INTEGER DEFAULT 0,
                last_updated TEXT NOT NULL,
                PRIMARY KEY (source_id, data_date)
            )""",
            """CREATE TABLE IF NOT EXISTS enrichment_status (
                content_hash TEXT PRIMARY KEY,
                enriched_at  TEXT NOT NULL,
                model        TEXT DEFAULT '',
                status       TEXT NOT NULL
            )""",
        ]
        for stmt in stmts:
            self._con.execute(stmt)
        self._con.commit()

    def _maybe_migrate_legacy(self, data_root: Path) -> None:
        row = self._con.execute(
            "SELECT COUNT(*) AS cnt FROM ingest_runs"
        ).fetchone()
        if row and int(row["cnt"] or 0) > 0:
            return
        for legacy_path in _legacy_duckdb_paths(data_root):
            if not legacy_path.exists():
                continue
            try:
                import duckdb

                con = duckdb.connect(str(legacy_path), read_only=True)
                ingest_rows = con.execute(
                    """
                    SELECT run_id, source_id, CAST(fetched_at AS VARCHAR),
                           CAST(date_range_start AS VARCHAR), CAST(date_range_end AS VARCHAR),
                           records_fetched, records_new, status, error
                    FROM ingest_runs
                    """
                ).fetchall()
                coverage_rows = con.execute(
                    """
                    SELECT source_id, CAST(data_date AS VARCHAR), record_count,
                           CAST(last_updated AS VARCHAR)
                    FROM coverage
                    """
                ).fetchall()
                enrich_rows = con.execute(
                    """
                    SELECT content_hash, CAST(enriched_at AS VARCHAR), model, status
                    FROM enrichment_status
                    """
                ).fetchall()
                con.close()
            except Exception:
                continue

            if ingest_rows:
                self._con.executemany(
                    """
                    INSERT OR IGNORE INTO ingest_runs
                    (run_id, source_id, fetched_at, date_range_start, date_range_end,
                     records_fetched, records_new, status, error)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ingest_rows,
                )
            if coverage_rows:
                self._con.executemany(
                    """
                    INSERT OR IGNORE INTO coverage
                    (source_id, data_date, record_count, last_updated)
                    VALUES (?, ?, ?, ?)
                    """,
                    coverage_rows,
                )
            if enrich_rows:
                self._con.executemany(
                    """
                    INSERT OR IGNORE INTO enrichment_status
                    (content_hash, enriched_at, model, status)
                    VALUES (?, ?, ?, ?)
                    """,
                    enrich_rows,
                )
            self._con.commit()
            return

    # ------------------------------------------------------------------
    # Ingest runs
    # ------------------------------------------------------------------

    def record_run(
        self,
        source_id: str,
        since: date,
        until: date,
        records_fetched: int,
        records_new: int,
        status: str,
        error: str = "",
    ) -> None:
        self._con.execute(
            """
            INSERT INTO ingest_runs
            (run_id, source_id, fetched_at, date_range_start, date_range_end,
             records_fetched, records_new, status, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                str(uuid.uuid4()),
                source_id,
                datetime.now(timezone.utc).isoformat(),
                since.isoformat(),
                until.isoformat(),
                records_fetched,
                records_new,
                status,
                error,
            ],
        )
        self._con.commit()

    # ------------------------------------------------------------------
    # Coverage
    # ------------------------------------------------------------------

    def update_coverage(self, source_id: str, data_date: date, record_count: int) -> None:
        self._con.execute(
            """
            INSERT INTO coverage VALUES (?, ?, ?, ?)
            ON CONFLICT (source_id, data_date) DO UPDATE SET
                record_count = excluded.record_count,
                last_updated = excluded.last_updated
            """,
            [
                source_id,
                data_date.isoformat(),
                record_count,
                datetime.now(timezone.utc).isoformat(),
            ],
        )
        self._con.commit()

    def latest_date(self, source_id: str) -> date | None:
        row = self._con.execute(
            "SELECT MAX(data_date) AS max_date FROM coverage WHERE source_id = ?",
            [source_id],
        ).fetchone()
        if not row or row["max_date"] is None:
            return None
        return date.fromisoformat(str(row["max_date"]))

    def coverage_report(self) -> dict[str, list[dict]]:
        rows = self._con.execute(
            "SELECT source_id, data_date, record_count FROM coverage ORDER BY source_id, data_date"
        ).fetchall()
        by_source: dict[str, list[dict]] = {}
        for row in rows:
            by_source.setdefault(str(row["source_id"]), []).append(
                {"date": str(row["data_date"]), "count": int(row["record_count"] or 0)}
            )
        return by_source

    # ------------------------------------------------------------------
    # Enrichment status (Silver incremental cache)
    # ------------------------------------------------------------------

    def get_enriched_hashes(self, hashes: list[str]) -> set[str]:
        if not hashes:
            return set()
        placeholders = ",".join(["?"] * len(hashes))
        rows = self._con.execute(
            f"SELECT content_hash FROM enrichment_status WHERE content_hash IN ({placeholders}) AND status='ok'",
            hashes,
        ).fetchall()
        return {str(r["content_hash"]) for r in rows}

    def mark_enriched(self, content_hash: str, model: str, status: str = "ok") -> None:
        self._con.execute(
            """
            INSERT INTO enrichment_status VALUES (?, ?, ?, ?)
            ON CONFLICT (content_hash) DO UPDATE SET
                enriched_at = excluded.enriched_at,
                model = excluded.model,
                status = excluded.status
            """,
            [content_hash, datetime.now(timezone.utc).isoformat(), model, status],
        )
        self._con.commit()

    def mark_enriched_batch(self, hashes: list[str], model: str, status: str = "ok") -> None:
        if not hashes:
            return
        now = datetime.now(timezone.utc).isoformat()
        self._con.executemany(
            """
            INSERT INTO enrichment_status VALUES (?, ?, ?, ?)
            ON CONFLICT (content_hash) DO UPDATE SET
                enriched_at = excluded.enriched_at,
                model = excluded.model,
                status = excluded.status
            """,
            [[h, now, model, status] for h in hashes],
        )
        self._con.commit()

    def enrichment_stats(self) -> dict:
        row = self._con.execute(
            "SELECT COUNT(*) AS total, SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END) AS ok FROM enrichment_status"
        ).fetchone()
        total = int(row["total"] or 0) if row else 0
        ok = int(row["ok"] or 0) if row else 0
        return {"total": total, "ok": ok, "error": total - ok}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        self._con.close()

    def __enter__(self) -> "PipelineDb":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
