from __future__ import annotations

from trade_py.db.trade_db import TradeDB
from trade_web.backend.readiness import _collect_recovery_actions


def test_collect_recovery_actions_clips_long_ranges_to_requested_window(tmp_path) -> None:
    db = TradeDB(tmp_path)
    with db._conn_lock:
        db._conn.execute(
            """
            INSERT INTO readiness_recovery_actions (
                dataset, date_from, date_to, action_type, mode, status,
                requested_at, updated_at, job_names_json, affected_outputs_json,
                request_json, fingerprint_before, fingerprint_after, result_json, summary
            ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, '[]', '[]', '{}', ?, ?, '{}', ?)
            """,
            (
                "kline",
                "2026-01-30",
                "2026-03-20",
                "backfill",
                "data_only",
                "ok",
                "fp-before",
                "fp-after",
                "range repair",
            ),
        )
        db._conn.commit()

    by_cell, by_dataset = _collect_recovery_actions(db, "2026-02-20", "2026-03-20")

    assert "kline" in by_dataset
    assert by_cell[("kline", "2026-03-20")][0]["summary"] == "range repair"
