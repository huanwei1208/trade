from __future__ import annotations

import sqlite3

from trade_py.factors.groups.event_features import build_event_group


def test_build_event_group_keeps_one_row_per_symbol_date() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE event_propagations (
            event_id INTEGER,
            symbol TEXT,
            hop INTEGER,
            kg_score REAL,
            event_date TEXT
        );
        CREATE TABLE market_events (
            event_id INTEGER PRIMARY KEY,
            event_type TEXT,
            magnitude REAL,
            confidence REAL,
            breadth TEXT,
            news_volume REAL
        );
        CREATE TABLE event_templates (
            event_type TEXT PRIMARY KEY,
            decay_factor REAL,
            max_hop INTEGER
        );
        """
    )
    conn.executemany(
        "INSERT INTO market_events(event_id, event_type, magnitude, confidence, breadth, news_volume) VALUES (?, ?, ?, ?, ?, ?)",
        [
            (1, "earnings", 0.3, 0.8, "single", 4.0),
            (2, "policy", 0.9, 0.7, "sector", 10.0),
        ],
    )
    conn.executemany(
        "INSERT INTO event_templates(event_type, decay_factor, max_hop) VALUES (?, ?, ?)",
        [
            ("earnings", 0.6, 2),
            ("policy", 0.4, 3),
        ],
    )
    conn.executemany(
        "INSERT INTO event_propagations(event_id, symbol, hop, kg_score, event_date) VALUES (?, ?, ?, ?, ?)",
        [
            (1, "603083.SH", 2, 0.25, "2026-03-20"),
            (2, "603083.SH", 1, 0.90, "2026-03-20"),
            (1, "000001.SZ", 1, 0.10, "2026-03-20"),
        ],
    )

    result = build_event_group(
        conn,
        "2026-03-20",
        maps={"event_type": {"earnings": 1, "policy": 2}, "breadth": {"single": 1, "sector": 2}},
    )

    assert len(result.values) == 2
    chosen = result.values[result.values["symbol"] == "603083.SH"].iloc[0]
    assert chosen["kg_score"] == 0.90
    assert chosen["hop"] == 1
    assert chosen["event_type_code"] == 2
    assert chosen["breadth_code"] == 2
