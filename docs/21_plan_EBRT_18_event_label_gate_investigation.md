# EBRT 18 Event Label Gate Investigation

## Goal

Investigate why `avg_actual_return_5d` and `labeled_propagation_ratio` were `0.0`,
and confirm whether the problem was:

1. no mature propagation labels being written back, or
2. evaluation/query logic reading the wrong source.

## Findings

- `event_propagations` was not globally unlabeled.
  - Full table: `2,376,847` rows
  - Rows with `actual_return_5d` present: `58,074`
- The research window used by the `2026-03-20` quality gate had zero mature labels before repair:
  - window: `2025-10-24 -> 2026-02-20`
  - rows: `799,452`
  - labeled rows: `0`
- Root cause: recovery/job orchestration dropped the requested date range.
  - `kg_propagate`, `event_backfill`, and `build_labels` all called
    `backfill_events(data_root)` without forwarding `date_from/date_to`
  - `backfill_events(data_root)` with no range only fills:
    - `today - 7` calendar days for `actual_return_5d`
    - `today - 28` calendar days for `actual_return_20d`
  - That explains why only very recent dates had labels and older research windows stayed at `0.0`

## Fix

- Updated job wrappers to pass explicit ranges through to `backfill_events(...)`
  - `trade_py/jobs/__init__.py`
  - `_job_event_backfill(...)`
  - `_job_build_labels(...)`
  - `_job_kg_propagate(...)`
- Added regression coverage:
  - `tests/test_jobs.py::test_kg_propagate_job_forwards_range`

## Verification

- Ran range backfill for the research window:
  - `backfill_events('data', start='2025-10-24', end='2026-02-20')`
- After backfill started, the research window became labeled again:
  - rows: `799,452`
  - labeled rows: `67,370`
  - labeled ratio: `0.0843`
  - avg `actual_return_5d`: `5.8742`
  - avg `actual_return_20d`: `3.4655`
- Re-ran `evaluate_daily('data', eval_date='2026-03-20', use_cache=False)`
- `daily_quality_gate` for `2026-03-20` became:
  - `status = ok`
  - `reason_summary = ''`

## Remaining semantic mismatch

- `Today` still showed `DEGRADED/global_blocked=true` after the gate recovered.
- Cause:
  - `Today` reads `trust_gate` from `QualityReport`
  - `QualityReport.research_status` is computed from `brier_score + drift_mmd`
  - for `2026-03-20`, `drift_mmd = 0.3924`, so `QualityReport` still says `research_status=partial`
- This is separate from the event-label maturity issue.

## Commands

- `uv run pytest tests/test_jobs.py tests/test_kline_sync_service.py tests/test_factor_groups.py -q`
- `python -m compileall trade_py/jobs/__init__.py`
- `uv run python - <<'PY' ... backfill_events('data', start='2025-10-24', end='2026-02-20') ... PY`
- `uv run python - <<'PY' ... evaluate_daily('data', eval_date='2026-03-20', use_cache=False) ... PY`

