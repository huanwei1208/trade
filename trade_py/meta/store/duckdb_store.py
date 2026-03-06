"""DuckDB-backed MetaStore implementation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from trade_py.meta.feed.score import FeedScore
from trade_py.meta.schema import meta_store as _ddl


class DuckDbMetaStore:
    """Persists feed scores and source configs in a DuckDB file.

    DB file: {data_root}/.meta/meta.duckdb
    """

    def __init__(self, data_root: Path) -> None:
        import duckdb
        db_path = data_root / ".meta" / "meta.duckdb"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._con = duckdb.connect(str(db_path))
        for stmt in _ddl.ALL:
            self._con.execute(stmt)

    # ------------------------------------------------------------------
    # Feed scores
    # ------------------------------------------------------------------

    def get_feed_score(self, feed_name: str) -> FeedScore | None:
        row = self._con.execute(
            "SELECT * FROM feed_scores WHERE feed_name = ?", [feed_name]
        ).fetchone()
        if row is None:
            return None
        cols = [d[0] for d in self._con.description]
        return self._row_to_score(dict(zip(cols, row)))

    def upsert_feed_score(self, score: FeedScore) -> None:
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
            [score.feed_name, score.computed_at,
             score.coverage_30d, score.uniqueness, score.signal_density,
             score.reliability, score.timeliness_minutes, score.composite,
             score.notes],
        )

    def list_feed_scores(self) -> list[FeedScore]:
        rows = self._con.execute("SELECT * FROM feed_scores").fetchall()
        cols = [d[0] for d in self._con.description]
        return [self._row_to_score(dict(zip(cols, r))) for r in rows]

    @staticmethod
    def _row_to_score(row: dict) -> FeedScore:
        return FeedScore(
            feed_name=row["feed_name"],
            computed_at=row["computed_at"],
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
        return json.loads(row[0])

    def upsert_source_config(self, source_id: str, config: dict) -> None:
        self._con.execute(
            """INSERT INTO source_configs VALUES (?, ?, ?)
               ON CONFLICT (source_id) DO UPDATE SET
                   updated_at=excluded.updated_at,
                   config_json=excluded.config_json""",
            [source_id, datetime.now(timezone.utc), json.dumps(config)],
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        self._con.close()

    def __enter__(self) -> "DuckDbMetaStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
