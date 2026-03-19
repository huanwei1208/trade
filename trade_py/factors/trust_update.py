"""Factor utility-trust updater — runs weekly.

Reads the ``factors`` table to compute a rolling rank-IC for each factor
over the past ``lookback_days``.  IC is then normalized to [0, 1] and written
back to the ``factor_registry`` table as ``utility_trust``.

Public API
----------
    update_utility_trust(data_root, lookback_days=60) -> dict[str, float]
        Compute IC for every factor in factor_registry and persist utility_trust.

    compute_factor_ic(data_root, lookback_days=60) -> dict[str, float | None]
        Compute only; do not write to DB.
"""
from __future__ import annotations

import logging
import math
from datetime import date, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ── IC computation ─────────────────────────────────────────────────────────────

def _rolling_rank_ic(
    conn,
    factor_name: str,
    start_date: str,
    end_date: str,
    return_col: str = "actual_return_5d",
) -> float | None:
    """Compute rolling rank IC for one factor vs. 5-day actual return.

    Reads ``factors`` JOIN ``event_propagations`` to pair factor values with
    realized returns.  Returns None if fewer than 20 valid cross-sections.
    """
    try:
        rows = conn.execute(
            """
            WITH factor_vals AS (
                SELECT f.date, f.symbol, f.value AS factor_value
                FROM factors f
                WHERE f.factor_name = ?
                  AND f.date >= ? AND f.date <= ?
                  AND f.value IS NOT NULL
            ),
            returns AS (
                SELECT ep.event_date AS date, ep.symbol,
                       AVG(ep.actual_return_5d) AS ret
                FROM event_propagations ep
                WHERE ep.event_date >= ? AND ep.event_date <= ?
                  AND ep.actual_return_5d IS NOT NULL
                GROUP BY ep.event_date, ep.symbol
            )
            SELECT fv.date, fv.symbol, fv.factor_value, r.ret
            FROM factor_vals fv
            JOIN returns r ON r.date = fv.date AND r.symbol = fv.symbol
            """,
            (factor_name, start_date, end_date, start_date, end_date),
        ).fetchall()
    except Exception as exc:
        logger.debug("IC query error for %s: %s", factor_name, exc)
        return None

    if not rows:
        return None

    # Group by date and compute cross-sectional rank correlation
    from collections import defaultdict
    by_date: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for r in rows:
        try:
            by_date[str(r[0])].append((float(r[2]), float(r[3])))
        except (TypeError, ValueError):
            pass

    ics: list[float] = []
    for pairs in by_date.values():
        if len(pairs) < 5:
            continue
        factor_vals = [p[0] for p in pairs]
        ret_vals = [p[1] for p in pairs]
        ic = _spearman(factor_vals, ret_vals)
        if ic is not None:
            ics.append(ic)

    if len(ics) < 5:
        return None
    # Median IC
    ics.sort()
    mid = len(ics) // 2
    if len(ics) % 2 == 0:
        median = (ics[mid - 1] + ics[mid]) / 2.0
    else:
        median = ics[mid]
    return round(median, 6)


def _spearman(x: list[float], y: list[float]) -> float | None:
    """Simple Spearman correlation between two lists."""
    n = len(x)
    if n < 3:
        return None
    rx = _rank_list(x)
    ry = _rank_list(y)
    mean_r = (n + 1) / 2.0
    num = sum((rx[i] - mean_r) * (ry[i] - mean_r) for i in range(n))
    denom_x = math.sqrt(sum((rx[i] - mean_r) ** 2 for i in range(n)))
    denom_y = math.sqrt(sum((ry[i] - mean_r) ** 2 for i in range(n)))
    if denom_x < 1e-9 or denom_y < 1e-9:
        return None
    return round(num / (denom_x * denom_y), 6)


def _rank_list(vals: list[float]) -> list[float]:
    """Return rank list (1-based, average ties)."""
    n = len(vals)
    indexed = sorted(enumerate(vals), key=lambda t: t[1])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j < n - 1 and indexed[j + 1][1] == indexed[j][1]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[indexed[k][0]] = avg_rank
        i = j + 1
    return ranks


def _ic_to_utility_trust(ic: float | None) -> float:
    """Map rank IC ∈ [-1, 1] to utility_trust ∈ [0, 1].

    IC=0 (no predictive power) → 0.5 (neutral).
    IC=0.1 (good factor IC) → ~0.77.
    IC=-0.1 (reverse predictive) → ~0.23.
    Formula: sigmoid(IC * 10) mapped to [0, 1].
    """
    if ic is None:
        return 0.5
    ic = max(-1.0, min(1.0, ic))
    # sigmoid(10 × IC)
    try:
        sig = 1.0 / (1.0 + math.exp(-10.0 * ic))
    except OverflowError:
        sig = 0.0 if ic < 0 else 1.0
    return round(sig, 6)


# ── Public API ─────────────────────────────────────────────────────────────────

def compute_factor_ic(
    data_root: str | Path,
    lookback_days: int = 60,
) -> dict[str, float | None]:
    """Compute rolling rank IC for all registered factors.

    Returns {factor_name: median_ic | None}.
    No DB writes.
    """
    from trade_py.db.trade_db import TradeDB
    from trade_py.factors.definitions import FEATURE_COLS

    db = TradeDB(data_root)
    end_date = date.today().isoformat()
    start_date = (date.today() - timedelta(days=lookback_days)).isoformat()

    results: dict[str, float | None] = {}
    for factor_name in FEATURE_COLS:
        ic = _rolling_rank_ic(db._conn, factor_name, start_date, end_date)
        results[factor_name] = ic
        logger.debug("factor IC: %s = %s", factor_name, ic)

    return results


def update_utility_trust(
    data_root: str | Path,
    lookback_days: int = 60,
) -> dict[str, float]:
    """Compute IC and write utility_trust to factor_registry table.

    Returns {factor_name: utility_trust} for all updated factors.
    """
    from trade_py.db.trade_db import TradeDB
    from trade_py.factors.registry import FACTOR_REGISTRY, _MEASUREMENT_TRUST_DEFAULTS, FactorType

    db = TradeDB(data_root)

    ic_map = compute_factor_ic(data_root, lookback_days=lookback_days)

    updated: dict[str, float] = {}
    rows_to_write: list[dict[str, Any]] = []

    for factor_name, ic in ic_map.items():
        u_trust = _ic_to_utility_trust(ic)
        meta = FACTOR_REGISTRY.get(factor_name)
        m_trust = (
            meta.measurement_trust if meta
            else _MEASUREMENT_TRUST_DEFAULTS.get(FactorType.EVENT, 0.8)
        )
        rows_to_write.append({
            "factor_name": factor_name,
            "factor_type": meta.factor_type.value if meta else "event",
            "factor_layer": "feature_store",
            "description": meta.description if meta else factor_name,
            "source": "factors",
            "utility_trust": u_trust,
            "measurement_trust": m_trust,
        })
        updated[factor_name] = u_trust
        logger.debug("utility_trust %s: IC=%.4f → %.4f", factor_name,
                     ic if ic is not None else float("nan"), u_trust)

    # Write to DB — uses extended upsert that includes trust columns
    if rows_to_write:
        _factor_registry_upsert_with_trust(db, rows_to_write)

    logger.info(
        "update_utility_trust: updated %d factors (lookback=%d days)",
        len(updated), lookback_days,
    )
    return updated


def _factor_registry_upsert_with_trust(db, rows: list[dict]) -> None:
    """Upsert factor_registry rows including utility_trust + measurement_trust.

    Handles the case where these columns may not yet exist (migration guard).
    """
    conn = db._conn
    # Check if trust columns exist
    existing_cols = {r[1] for r in conn.execute("PRAGMA table_info(factor_registry)").fetchall()}
    has_u_trust = "utility_trust" in existing_cols
    has_m_trust = "measurement_trust" in existing_cols

    for row in rows:
        if has_u_trust and has_m_trust:
            conn.execute(
                """
                INSERT INTO factor_registry
                    (factor_name, factor_type, factor_layer, description, source,
                     utility_trust, measurement_trust, updated_at)
                VALUES (:factor_name, :factor_type, :factor_layer, :description, :source,
                        :utility_trust, :measurement_trust, CURRENT_TIMESTAMP)
                ON CONFLICT(factor_name) DO UPDATE SET
                    factor_type=excluded.factor_type,
                    description=excluded.description,
                    utility_trust=excluded.utility_trust,
                    measurement_trust=excluded.measurement_trust,
                    updated_at=CURRENT_TIMESTAMP
                """,
                row,
            )
        elif has_u_trust:
            conn.execute(
                """
                INSERT INTO factor_registry
                    (factor_name, factor_type, factor_layer, description, source,
                     utility_trust, updated_at)
                VALUES (:factor_name, :factor_type, :factor_layer, :description, :source,
                        :utility_trust, CURRENT_TIMESTAMP)
                ON CONFLICT(factor_name) DO UPDATE SET
                    factor_type=excluded.factor_type,
                    utility_trust=excluded.utility_trust,
                    updated_at=CURRENT_TIMESTAMP
                """,
                row,
            )
        else:
            # Trust columns not yet migrated — just update without them
            conn.execute(
                """
                INSERT INTO factor_registry
                    (factor_name, factor_type, factor_layer, description, source, updated_at)
                VALUES (:factor_name, :factor_type, :factor_layer, :description, :source,
                        CURRENT_TIMESTAMP)
                ON CONFLICT(factor_name) DO UPDATE SET
                    factor_type=excluded.factor_type,
                    updated_at=CURRENT_TIMESTAMP
                """,
                row,
            )
    conn.commit()
