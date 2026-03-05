"""DuckDB-backed pipeline state store.

Replaces watermark JSON files with three queryable tables:
  - ingest_runs   : one row per source fetch run (success/error log)
  - coverage      : daily record counts per source (query gaps with SQL)
  - enrichment_status : per-content_hash LLM enrichment cache

DB file lives at: {data_root}/.pipeline/state.duckdb
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from pathlib import Path


class PipelineDb:
    """Thin wrapper around a DuckDB embedded database for pipeline state."""

    def __init__(self, data_root: Path) -> None:
        import duckdb
        db_path = data_root / ".pipeline" / "state.duckdb"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._con = duckdb.connect(str(db_path))
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        stmts = [
            """CREATE TABLE IF NOT EXISTS ingest_runs (
                run_id           TEXT PRIMARY KEY,
                source_id        TEXT NOT NULL,
                fetched_at       TIMESTAMPTZ NOT NULL,
                date_range_start DATE,
                date_range_end   DATE,
                records_fetched  INT DEFAULT 0,
                records_new      INT DEFAULT 0,
                status           TEXT NOT NULL,
                error            TEXT DEFAULT ''
            )""",
            """CREATE TABLE IF NOT EXISTS coverage (
                source_id    TEXT NOT NULL,
                data_date    DATE NOT NULL,
                record_count INT DEFAULT 0,
                last_updated TIMESTAMPTZ NOT NULL,
                PRIMARY KEY (source_id, data_date)
            )""",
            """CREATE TABLE IF NOT EXISTS enrichment_status (
                content_hash TEXT PRIMARY KEY,
                enriched_at  TIMESTAMPTZ NOT NULL,
                model        TEXT DEFAULT '',
                status       TEXT NOT NULL
            )""",
        ]
        for stmt in stmts:
            self._con.execute(stmt)

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
            "INSERT INTO ingest_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [str(uuid.uuid4()), source_id, datetime.now(timezone.utc),
             since, until, records_fetched, records_new, status, error],
        )

    # ------------------------------------------------------------------
    # Coverage
    # ------------------------------------------------------------------

    def update_coverage(self, source_id: str, data_date: date,
                        record_count: int) -> None:
        self._con.execute(
            """INSERT INTO coverage VALUES (?, ?, ?, ?)
               ON CONFLICT (source_id, data_date) DO UPDATE SET
                   record_count = excluded.record_count,
                   last_updated = excluded.last_updated""",
            [source_id, data_date, record_count, datetime.now(timezone.utc)],
        )

    def latest_date(self, source_id: str) -> date | None:
        """Return the most recent data_date for a source, or None."""
        row = self._con.execute(
            "SELECT MAX(data_date) FROM coverage WHERE source_id = ?",
            [source_id],
        ).fetchone()
        return row[0] if row and row[0] is not None else None

    def coverage_report(self) -> dict[str, list[dict]]:
        rows = self._con.execute(
            "SELECT source_id, data_date, record_count FROM coverage"
            " ORDER BY source_id, data_date"
        ).fetchall()
        by_source: dict[str, list[dict]] = {}
        for source_id, data_date, count in rows:
            by_source.setdefault(source_id, []).append(
                {"date": str(data_date), "count": count}
            )
        return by_source

    # ------------------------------------------------------------------
    # Enrichment status (Silver incremental cache)
    # ------------------------------------------------------------------

    def get_enriched_hashes(self, hashes: list[str]) -> set[str]:
        """Return subset of hashes that are already successfully enriched."""
        if not hashes:
            return set()
        placeholders = ",".join(["?"] * len(hashes))
        rows = self._con.execute(
            f"SELECT content_hash FROM enrichment_status"
            f" WHERE content_hash IN ({placeholders}) AND status = 'ok'",
            hashes,
        ).fetchall()
        return {r[0] for r in rows}

    def mark_enriched(self, content_hash: str, model: str,
                      status: str = "ok") -> None:
        self._con.execute(
            """INSERT INTO enrichment_status VALUES (?, ?, ?, ?)
               ON CONFLICT (content_hash) DO UPDATE SET
                   enriched_at = excluded.enriched_at,
                   model = excluded.model,
                   status = excluded.status""",
            [content_hash, datetime.now(timezone.utc), model, status],
        )

    def mark_enriched_batch(self, hashes: list[str], model: str,
                            status: str = "ok") -> None:
        now = datetime.now(timezone.utc)
        self._con.executemany(
            """INSERT INTO enrichment_status VALUES (?, ?, ?, ?)
               ON CONFLICT (content_hash) DO UPDATE SET
                   enriched_at = excluded.enriched_at,
                   model = excluded.model,
                   status = excluded.status""",
            [[h, now, model, status] for h in hashes],
        )

    def enrichment_stats(self) -> dict:
        row = self._con.execute(
            "SELECT COUNT(*), SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END)"
            " FROM enrichment_status"
        ).fetchone()
        total, ok = (row[0] or 0, row[1] or 0) if row else (0, 0)
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
