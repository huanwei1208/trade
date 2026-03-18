"""Evidence formal package — Bronze → Silver → Gold pipeline API.

Public API:
    run_ingest(date_from, date_to, data_root, **kwargs) -> dict
    run_enrich(asof_date, data_root, **kwargs) -> dict
    run_aggregate(asof_date, data_root, **kwargs) -> dict
"""
from __future__ import annotations

from trade_py.evidence.ingest import run_ingest
from trade_py.evidence.enrich import run_enrich
from trade_py.evidence.aggregate import run_aggregate

__all__ = ["run_ingest", "run_enrich", "run_aggregate"]
