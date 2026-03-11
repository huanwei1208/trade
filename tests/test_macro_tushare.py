from __future__ import annotations

import pandas as pd

from trade_py.data.market.macro.tushare import MacroFetcher


def test_resolve_date_column_is_case_insensitive() -> None:
    raw = pd.DataFrame({"MONTH": ["202501"], "VALUE": [1]})

    assert MacroFetcher._resolve_date_column(raw, "month") == "MONTH"
    assert MacroFetcher._resolve_date_column(raw, "year") is None
