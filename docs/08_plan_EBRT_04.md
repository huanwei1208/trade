# EBRT_04 — Trust-Centered Architecture Refactoring

**Date**: 2026-03-19
**Status**: 🔄 In Progress

## Objective

Move from "structured outputs + richer explanations" toward a **trustable decision system** with explicit contracts, traceability, and cleaner factor/data architecture.

Three phases in priority order:

---

## Phase A — First-Class Trust Layer

**Problem**: `InferenceService.predict()` returns `{model_score, model_risk, model_version}` — no signal about how trustworthy that output is.

**Goal**: Every prediction includes a machine-readable `trust` block:
- `trust_score` ∈ [0, 1]
- `trust_level`: LOW / MEDIUM / HIGH
- `feature_coverage` — fraction of expected features with real (non-default) data
- `missing_features` — list of features not found in factor store
- `used_defaults` — list of features that fell back to neutral values
- `data_freshness_score` — based on sync_state lag
- `model_version`, `feature_schema_version`, `generation_method`
- `warnings` — structured, machine-readable

**Trust score formula**:
```
trust_score = (feature_coverage × 0.50
             + data_freshness_score × 0.30
             + 0.20)                          # base floor
            × (1 − default_fraction × 0.30)  # penalize heavy defaults
```

**New files**:
| File | Role |
|------|------|
| `trade_py/trust/__init__.py` | Public exports |
| `trade_py/trust/breakdown.py` | `TrustBreakdown` dataclass |
| `trade_py/trust/compute.py` | `compute_prediction_trust()` + helpers |

**Modified files**:
| File | Change |
|------|--------|
| `trade_web/backend/inference.py` | Add trust block to predict() output |

**Acceptance**:
- `predict()` returns dict includes `trust` key with TrustBreakdown-derived dict
- Trust score is deterministic, testable
- Warnings are structured strings, not prose

---

## Phase B — Factor Group Builders

**Problem**: `materializer.py` mixes 4 concerns (event/KG, gold sentiment, technical, instrument) in one monolithic function with no provenance tracking.

**Goal**: Each group of factors exposes a clean contract via `FactorGroupResult`:
```python
@dataclass
class FactorGroupResult:
    group_name: str
    values: pd.DataFrame          # (date, symbol) + group factor cols
    missing: list[str]            # factor names absent from source
    used_defaults: list[str]      # factor names where fallback applied
    coverage: float               # present / expected
    source_date_range: tuple[str, str] | None
```

**New files**:
| File | Role |
|------|------|
| `trade_py/factors/groups/__init__.py` | Package + re-exports |
| `trade_py/factors/groups/_base.py` | `FactorGroupResult` dataclass |
| `trade_py/factors/groups/event_features.py` | KG/event group (hop, kg_score, …, decay_factor, max_hop) |
| `trade_py/factors/groups/sentiment_features.py` | Gold bf_* factors (8 cols) |
| `trade_py/factors/groups/technical_features.py` | tech_* factors (11 cols) |
| `trade_py/factors/groups/instrument_features.py` | industry, market, window_score, net_sentiment |

**Modified files**:
| File | Change |
|------|--------|
| `trade_py/factors/materializer.py` | Thin orchestrator — calls group builders, merges, propagates coverage |
| `trade_py/factors/__init__.py` | Export FactorGroupResult |

**Constraints**:
- `FEATURE_COLS` order preserved — no silent breakage of training/inference
- `FEATURE_SCHEMA_VERSION = "v1"` constant added to definitions.py
- Coverage info flows up through `materialize_inference_factors()` return value

---

## Phase C — Data Contracts / Provenance

**Problem**: Data freshness and provenance are implicit — no shared struct propagates "how old is this data?" to the trust layer.

**Goal**: A minimal, practical contract layer consumed by the trust layer.

**New files**:
| File | Role |
|------|------|
| `trade_py/data/contracts.py` | `DataSnapshot`, `FreshnessReport`, `SourceMetadata` |

**Key dataclasses**:
```python
@dataclass
class DataSnapshot:
    dataset: str        # "kline", "signals", "sentiment_gold", …
    symbol: str | None  # None = market-wide
    as_of_date: str
    latest_available_date: str | None
    freshness_days: int | None   # None = data missing entirely
    row_count: int
    missing_columns: list[str]
    schema_version: str
    quality_flags: list[str]    # ["stale", "low_coverage", "missing_required"]

@dataclass
class FreshnessReport:
    snapshots: list[DataSnapshot]
    overall_freshness_score: float   # 0–1 weighted average
    stale_datasets: list[str]
    missing_datasets: list[str]
```

**Wiring**:
- `materialize_inference_factors()` returns `(date, count, cols, FreshnessReport)` (extended signature)
- Trust layer reads `FreshnessReport.overall_freshness_score` for `data_freshness_score`

**Modified files**:
| File | Change |
|------|--------|
| `trade_py/factors/materializer.py` | Return FreshnessReport from materialize_inference_factors |
| `trade_web/backend/inference.py` | Pass freshness into compute_prediction_trust() |

---

## Implementation Progress

| Phase | Task | Status |
|-------|------|--------|
| A | `trade_py/trust/breakdown.py` | ✅ |
| A | `trade_py/trust/compute.py` | ✅ |
| A | `trade_py/trust/__init__.py` | ✅ |
| A | Wire trust into `inference.py` | ✅ |
| B | `groups/_base.py` — FactorGroupResult | ✅ |
| B | `groups/event_features.py` | ✅ |
| B | `groups/sentiment_features.py` | ✅ |
| B | `groups/technical_features.py` | ✅ |
| B | `groups/instrument_features.py` | ✅ |
| B | Refactor `materializer.py` | ✅ |
| C | `data/contracts.py` — DataSnapshot, FreshnessReport | ✅ |
| C | Wire FreshnessReport into materializer return | ✅ |
| C | Wire freshness into trust compute | ✅ |
| Tests | `tests/test_trust_layer.py` — 23 tests | ✅ |

---

## Architecture After Refactoring

```
InferenceService.predict(symbols)
  │
  ├── db.factor_get_latest(symbol, cols)           ← raw values
  │     ↓
  │   detect missing / defaulted cols
  │     ↓
  ├── compute_prediction_trust(values, cols, ...)  ← Phase A
  │     reads: FreshnessReport (Phase C)
  │     reads: FACTOR_REGISTRY composite_trust
  │     ↓
  │   TrustBreakdown {trust_score, trust_level, coverage, ...}
  │     ↓
  └── return {model_score, model_risk, model_version, trust: {...}}

materialize_inference_factors(data_root, date)
  │
  ├── build_event_group(db, date)    → FactorGroupResult   ← Phase B
  ├── build_instrument_group(db)     → FactorGroupResult
  ├── build_sentiment_group(...)     → FactorGroupResult
  ├── build_technical_group(...)     → FactorGroupResult
  │     ↓
  ├── merge groups → DataFrame
  ├── compute FreshnessReport        ← Phase C
  └── return (date, count, FEATURE_COLS, FreshnessReport)
```
