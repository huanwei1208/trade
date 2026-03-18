"""SQLite-backed MetaStore implementation.

The class name is kept for compatibility, but the storage backend is SQLite
with WAL enabled to avoid DuckDB file-lock contention during concurrent CLI use.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from trade_py.intelligence.feed_score import FeedScore
from trade_py.intelligence import schema as _ddl


def _sqlite_path(data_root: Path) -> Path:
    new_path = data_root / ".db" / "feed.db"
    legacy_sqlite = data_root / ".meta" / "meta.db"
    if new_path.exists() or not legacy_sqlite.exists():
        return new_path
    return legacy_sqlite


def _legacy_duckdb_paths(data_root: Path) -> list[Path]:
    return [
        data_root / ".db" / "feed.duckdb",
        data_root / ".meta" / "meta.duckdb",
    ]


class DuckDbMetaStore:
    """Compatibility wrapper; actual backend is SQLite."""

    def __init__(self, data_root: Path) -> None:
        db_path = _sqlite_path(data_root)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._con = sqlite3.connect(str(db_path), timeout=30, check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        self._con.execute("PRAGMA journal_mode=WAL")
        self._con.execute("PRAGMA synchronous=NORMAL")
        self._con.execute("PRAGMA busy_timeout=30000")
        for stmt in _ddl.ALL:
            self._con.execute(stmt)
        self._con.commit()
        self._maybe_migrate_legacy(data_root)

    def _maybe_migrate_legacy(self, data_root: Path) -> None:
        row = self._con.execute("SELECT COUNT(*) AS cnt FROM feed_scores").fetchone()
        if row and int(row["cnt"] or 0) > 0:
            return
        for legacy_path in _legacy_duckdb_paths(data_root):
            if not legacy_path.exists():
                continue
            try:
                import duckdb

                con = duckdb.connect(str(legacy_path), read_only=True)
                score_rows = con.execute(
                    """
                    SELECT feed_name, CAST(computed_at AS VARCHAR), coverage_30d,
                           uniqueness, signal_density, reliability,
                           timeliness_minutes, composite, notes
                    FROM feed_scores
                    """
                ).fetchall()
                config_rows = con.execute(
                    """
                    SELECT source_id, CAST(updated_at AS VARCHAR), config_json
                    FROM source_configs
                    """
                ).fetchall()
                con.close()
            except Exception:
                continue
            if score_rows:
                self._con.executemany(
                    """
                    INSERT OR IGNORE INTO feed_scores
                    (feed_name, computed_at, coverage_30d, uniqueness, signal_density,
                     reliability, timeliness_minutes, composite, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    score_rows,
                )
            if config_rows:
                self._con.executemany(
                    """
                    INSERT OR IGNORE INTO source_configs
                    (source_id, updated_at, config_json)
                    VALUES (?, ?, ?)
                    """,
                    config_rows,
                )
            self._con.commit()
            return

    # ------------------------------------------------------------------
    # Feed scores
    # ------------------------------------------------------------------

    def get_feed_score(self, feed_name: str) -> FeedScore | None:
        row = self._con.execute(
            "SELECT * FROM feed_scores WHERE feed_name = ?", [feed_name]
        ).fetchone()
        if row is None:
            return None
        return self._row_to_score(dict(row))

    def upsert_feed_score(self, score: FeedScore) -> None:
        computed_at = score.computed_at.isoformat() if isinstance(score.computed_at, datetime) else str(score.computed_at)
        self._con.execute(
            """INSERT INTO feed_scores VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT (feed_name) DO UPDATE SET
                   computed_at=excluded.computed_at,
                   coverage_30d=excluded.coverage_30d,
                   uniqueness=excluded.uniqueness,
                   signal_density=excluded.signal_density,
                   reliability=excluded.reliability,
                   timeliness_minutes=excluded.timeliness_minutes,
                   composite=excluded.composite,
                   notes=excluded.notes""",
            [score.feed_name, computed_at,
             score.coverage_30d, score.uniqueness, score.signal_density,
             score.reliability, score.timeliness_minutes, score.composite,
             score.notes],
        )
        self._con.commit()

    def list_feed_scores(self) -> list[FeedScore]:
        rows = self._con.execute("SELECT * FROM feed_scores").fetchall()
        return [self._row_to_score(dict(r)) for r in rows]

    @staticmethod
    def _row_to_score(row: dict) -> FeedScore:
        computed_at = row["computed_at"]
        if isinstance(computed_at, str):
            try:
                computed_at = datetime.fromisoformat(computed_at.replace("Z", "+00:00"))
            except Exception:
                computed_at = datetime.now(timezone.utc)
        return FeedScore(
            feed_name=row["feed_name"],
            computed_at=computed_at,
            coverage_30d=float(row.get("coverage_30d", 0.0)),
            uniqueness=float(row.get("uniqueness", 0.0)),
            signal_density=float(row.get("signal_density", 0.0)),
            reliability=float(row.get("reliability", 0.0)),
            timeliness_minutes=float(row.get("timeliness_minutes", 0.0)),
            composite=float(row.get("composite", 0.0)),
            notes=str(row.get("notes", "")),
        )

    # ------------------------------------------------------------------
    # Source configs
    # ------------------------------------------------------------------

    def get_source_config(self, source_id: str) -> dict | None:
        row = self._con.execute(
            "SELECT config_json FROM source_configs WHERE source_id = ?", [source_id]
        ).fetchone()
        if row is None:
            return None
        return json.loads(row["config_json"])

    def upsert_source_config(self, source_id: str, config: dict) -> None:
        self._con.execute(
            """INSERT INTO source_configs VALUES (?, ?, ?)
               ON CONFLICT (source_id) DO UPDATE SET
                   updated_at=excluded.updated_at,
                   config_json=excluded.config_json""",
            [source_id, datetime.now(timezone.utc).isoformat(), json.dumps(config)],
        )
        self._con.commit()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        self._con.close()

    def __enter__(self) -> "DuckDbMetaStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
