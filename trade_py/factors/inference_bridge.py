"""Bridge between factor store and InferenceService for prediction sync."""
from __future__ import annotations

import logging

from trade_py.db.trade_db import TradeDB

logger = logging.getLogger(__name__)


def sync_signal_predictions(data_root: str, date_str: str | None = None) -> tuple[str, int]:
    """Run InferenceService.predict() and write model_score back to signals table."""
    db = TradeDB(data_root)
    target_date = date_str or db._conn.execute("SELECT MAX(date) FROM signals").fetchone()[0]
    if not target_date:
        return "", 0
    symbols = [
        str(r[0])
        for r in db._conn.execute(
            "SELECT symbol FROM signals WHERE date = ? ORDER BY symbol",
            (target_date,),
        ).fetchall()
    ]
    if not symbols:
        return target_date, 0

    from trade_web.backend.inference import InferenceService

    service = InferenceService(data_root)
    preds = service.predict(symbols, target_date)
    updated = 0
    for symbol, payload in preds.items():
        if payload.get("model_score") is None:
            continue
        db.signal_upsert(
            target_date,
            symbol,
            model_score=payload.get("model_score"),
            model_risk=payload.get("model_risk"),
            model_version=payload.get("model_version"),
        )
        updated += 1
    return target_date, updated
