from __future__ import annotations

from pathlib import Path

from trade_py.belief import BeliefEngine
from trade_py.db.trade_db import TradeDB


def test_collect_symbols_includes_signal_universe(tmp_path) -> None:
    db = TradeDB(tmp_path)
    db.signal_upsert("2026-03-20", "000001.SZ", window_score=55)
    db.signal_upsert("2026-03-20", "000002.SZ", window_score=61)

    engine = BeliefEngine(db)
    symbols = engine._collect_symbols(Path(tmp_path), "2026-03-20")

    assert symbols == ["000001.SZ", "000002.SZ"]
