# EBRT_12 — Restore Latest Recommendation Flow

**Date**: 2026-03-21  
**Status**: ✅ Completed

---

## 1. Objective

Tighten the product around one concrete operator goal:

1. restore the latest recommendation,
2. show whether the current symbol recommendation is fresh enough to trust,
3. show live execution progress while recovery is running,
4. verify the real API payloads instead of guessing shapes.

---

## 2. Real API findings

Verified against a live local backend started with `./trade web --port 8091`.

### Readiness / recovery

- `GET /api/readiness-grid?days=30` returns usable readiness rows with real `history`, `changed_since_last_ready`, `affected_outputs`, and today impact.
- `GET /api/readiness/history?dataset=recommendation&date=2026-03-20` returns rich action items with:
  - `status`
  - `job_names`
  - `result.duration_ms`
  - `result.steps[]`
  - `fingerprint_before`
  - `fingerprint_after`
- `GET /api/readiness/replay-plan?...` returns:
  - `job_name`
  - `downstream_nodes`
  - `full_chain`
  - `affected_outputs`
  - `estimated_duration_ms`
- `POST /api/readiness/detect-changes` returns real fingerprint comparison payloads.
- `POST /api/readiness/backfill` and `POST /api/readiness/replay` both accepted real requests in this environment.

### Symbol

- `GET /api/kline/002455.SZ` returned:
  - `as_of`
  - empty `ohlcv`
  - `world_state`
  - `action.no_action_reason`
  - embedded partial explanation
- `GET /api/explain/002455.SZ` returned:
  - `input_warnings`
  - `invalidators`
  - `world_state.data_quality_state`
- `GET /api/state/002455.SZ` returned:
  - `blockers`
  - `data_quality_state.score`
  - `data_quality_state.freshness_score`
  - `missing_datasets`
  - `stale_datasets`

These real payloads are now the basis of the frontend wiring.

---

## 3. Focused implementation

### Recovery UX

- Added typed recovery action/result/step models in frontend API types.
- Added an execution progress card for the latest/current recovery run.
- Switched Ops recovery history to the real `GET /api/readiness/history` endpoint for the selected dataset/day.
- Added polling while the latest recovery action is `queued` / `running`.
- Stopped polling on terminal states and refreshed readiness grid again on completion.
- Reframed recovery actions around restoring the latest recommendation, not generic backstage replay.

### Symbol freshness gate

- Added a top-of-page freshness banner driven by:
  - `state.data_quality_state`
  - `state.blockers`
  - `explanation.input_warnings`
  - `kline.ohlcv`
- The banner now tells the user:
  - fresh enough / degraded / constrained
  - missing datasets
  - stale datasets
  - what to do next
- Added direct actions:
  - open readiness
  - open recovery
  - retry current symbol resources

### Data label cleanup

- Dataset display now normalizes `tushare_*` aliases so symbol freshness warnings do not leak raw backend names unchanged.

---

## 4. Verification log

- `./trade web --port 8091`
- `curl http://127.0.0.1:8091/api/readiness-grid?days=30`
- `curl http://127.0.0.1:8091/api/readiness/history?dataset=recommendation&date=2026-03-20`
- `curl http://127.0.0.1:8091/api/readiness/replay-plan?dataset=recommendation&date_from=2026-03-20&date_to=2026-03-20`
- `curl -X POST http://127.0.0.1:8091/api/readiness/detect-changes ...`
- `curl -X POST http://127.0.0.1:8091/api/readiness/backfill ...`
- `curl -X POST http://127.0.0.1:8091/api/readiness/replay ...`
- `curl http://127.0.0.1:8091/api/kline/002455.SZ`
- `curl http://127.0.0.1:8091/api/explain/002455.SZ`
- `curl http://127.0.0.1:8091/api/state/002455.SZ`
- `cd trade_web/frontend && npm run build`
- `uv run pytest tests/test_world_state.py tests/test_explanation.py`

---

## 5. Narrow test addition

Added a contract test ensuring `build_world_state(... freshness_missing / freshness_stale ...)` serializes:

- `data_quality_state.missing_datasets`
- `data_quality_state.stale_datasets`
- `blockers` containing `missing_datasets:...`

This protects the Symbol freshness gate’s structured dependency.
