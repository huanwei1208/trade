"""Factor registry — FactorMeta + composite trust model.

Each factor has two trust dimensions:
  measurement_trust — source reliability × data freshness    [0, 1]
  utility_trust     — rolling 60-day rank IC median, normalized [0, 1]

And a staleness dimension:
  staleness_decay   — exp(-staleness_days / 5)               [0, 1]

Composite trust = measurement × utility × staleness_decay.

utility_trust is updated weekly by ``factors.trust_update.update_utility_trust()``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


class FactorType(str, Enum):
    TECHNICAL   = "technical"
    SENTIMENT   = "sentiment"
    EVENT       = "event"
    FUNDAMENTAL = "fundamental"
    GRAPH       = "graph"
    WINDOW      = "window"
    INSTRUMENT  = "instrument"


# Default measurement_trust by factor type — reflects source reliability
_MEASUREMENT_TRUST_DEFAULTS: dict[str, float] = {
    FactorType.TECHNICAL:   0.90,   # Tushare OHLCV — reliable
    FactorType.SENTIMENT:   0.70,   # RSS scraping — noisy
    FactorType.EVENT:       0.80,   # NLP extraction confidence
    FactorType.FUNDAMENTAL: 0.90,   # Official financial data
    FactorType.GRAPH:       0.75,   # KG propagation — indirect
    FactorType.WINDOW:      0.80,   # Window scorer output
    FactorType.INSTRUMENT:  1.00,   # Reference data
}


@dataclass
class FactorMeta:
    """Trust metadata for a single factor."""

    name: str
    factor_type: FactorType
    description: str

    # Source/data reliability (set by configuration, updated rarely)
    measurement_trust: float = 1.0    # [0, 1]

    # Historical IC-based utility (updated weekly by trust_update.py)
    utility_trust: float = 0.5        # [0, 1]; default = neutral

    # Staleness: days since last update for this factor
    staleness_days: int = 0

    @property
    def staleness_decay(self) -> float:
        """Exponential decay: exp(-staleness_days / 5). No data → 1.0."""
        if self.staleness_days <= 0:
            return 1.0
        return round(math.exp(-self.staleness_days / 5.0), 6)

    @property
    def composite_trust(self) -> float:
        """measurement × utility × staleness_decay, rounded to 6dp."""
        return round(
            self.measurement_trust * self.utility_trust * self.staleness_decay,
            6,
        )

    def with_staleness(self, days: int) -> "FactorMeta":
        """Return a copy with staleness_days set."""
        from dataclasses import replace
        return replace(self, staleness_days=days)


def _build_registry() -> dict[str, "FactorMeta"]:
    """Build the default factor registry from FACTOR_DEFINITIONS."""
    from trade_py.factors.definitions import FACTOR_DEFINITIONS

    registry: dict[str, FactorMeta] = {}
    for name, spec in FACTOR_DEFINITIONS.items():
        ft_str = spec.get("factor_type", "event")
        try:
            ft = FactorType(ft_str)
        except ValueError:
            ft = FactorType.EVENT
        m_trust = _MEASUREMENT_TRUST_DEFAULTS.get(ft, 0.8)
        registry[name] = FactorMeta(
            name=name,
            factor_type=ft,
            description=spec.get("description", name),
            measurement_trust=m_trust,
            utility_trust=0.5,      # neutral default, overridden by DB
        )
    return registry


# Module-level registry — initialized once at import time
FACTOR_REGISTRY: dict[str, FactorMeta] = _build_registry()


def load_registry_from_db(db) -> dict[str, FactorMeta]:
    """Load FactorMeta from factor_registry table, merging DB trust values.

    Falls back to module-level FACTOR_REGISTRY defaults for missing columns.
    """
    try:
        rows = db.factor_registry_list()
    except Exception:
        return dict(FACTOR_REGISTRY)

    result = dict(FACTOR_REGISTRY)
    for row in rows:
        name = row.get("factor_name", "")
        if name not in result:
            continue
        meta = result[name]
        m_trust = row.get("measurement_trust")
        u_trust = row.get("utility_trust")
        if m_trust is not None:
            try:
                meta.measurement_trust = float(m_trust)
            except (TypeError, ValueError):
                pass
        if u_trust is not None:
            try:
                meta.utility_trust = float(u_trust)
            except (TypeError, ValueError):
                pass
        result[name] = meta
    return result


def composite_trust_weights(
    registry: dict[str, FactorMeta] | None = None,
) -> dict[str, float]:
    """Return {factor_name: composite_trust} for all factors in registry.

    If registry is None, uses the module-level FACTOR_REGISTRY (default trust values).
    """
    reg = registry or FACTOR_REGISTRY
    return {name: meta.composite_trust for name, meta in reg.items()}
