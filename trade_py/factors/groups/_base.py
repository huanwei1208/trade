"""FactorGroupResult — contract type returned by every group builder."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class FactorGroupResult:
    """Result of a single factor-group builder.

    Attributes
    ----------
    group_name : str
        Human-readable group identifier (e.g. "event", "sentiment_gold").
    values : pd.DataFrame
        DataFrame with columns [date, symbol, <factor_cols>].
        Always contains all expected factor columns; missing rows are absent
        (not padded) — the orchestrator handles left-join + fill.
    expected_cols : list[str]
        The full list of factor column names this group is responsible for.
    missing : list[str]
        Factor names where the *source* had no data at all (group-level gap).
    used_defaults : list[str]
        Factor names where source data existed but fell back to neutral defaults.
    coverage : float
        Fraction of expected_cols with real (non-default) data.
        Range [0, 1]; 0.0 = no data, 1.0 = all columns populated.
    source_date_range : tuple[str, str] | None
        (earliest_date, latest_date) of the underlying data loaded, or None.
    """

    group_name: str
    values: pd.DataFrame
    expected_cols: list[str]
    missing: list[str] = field(default_factory=list)
    used_defaults: list[str] = field(default_factory=list)
    coverage: float = 1.0
    source_date_range: tuple[str, str] | None = None

    @classmethod
    def empty(cls, group_name: str, expected_cols: list[str]) -> "FactorGroupResult":
        """Return an empty result (no data available for this group)."""
        return cls(
            group_name=group_name,
            values=pd.DataFrame(columns=["date", "symbol"] + expected_cols),
            expected_cols=expected_cols,
            missing=list(expected_cols),
            used_defaults=[],
            coverage=0.0,
            source_date_range=None,
        )
