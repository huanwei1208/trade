# EBRT 16 - Recovery Observability Closeout

## Goal

Close the last operational gap after the latest-recommendation recovery pass:

- make manual readiness recovery/replay visible in the shared workflow plane
- ensure `Pipeline` and `Workflows` reflect the same real recovery execution
- verify the full tab-level API surface again after a live recovery run

## Progress

- [x] inspect readiness executor and shared `job_runs` / `event_log` / workflow aggregation paths
- [x] wire recovery root events, step events, and `job_runs` into `execute_recovery_action()`
- [x] add synthetic workflow fallback so non-DAG recovery roots still render meaningful workflow progress
- [x] update Ops workflows list to show workflow titles and readable root-cause summaries
- [x] run targeted pytest, frontend build, and live API verification after a real recovery action
- [ ] commit the closeout batch

## Expected Outcome

After this pass:

- readiness recovery no longer lives only inside `readiness_recovery_actions`
- `Workflows` shows recovery as a recommendation-restoration workflow
- `Pipeline` sees the underlying job runs created by recovery
- `events-page` gets richer workflow context from the same shared trace

## Verification

Real local verification ran against `./trade web --port 8092`.

- submitted `POST /api/readiness/replay` for `dataset=recommendation`, `2026-03-20`
- action `33` completed with `status=ok`
- recovery history returned `workflow_event_id=195`
- `GET /api/workflows?limit=5` exposed:
  - title `Restore the latest recommendation from Recommendation`
  - status `ok`
  - progress `1/1`
- `GET /api/workflows/195` returned the synthetic recovery workflow detail with node `evaluate_daily`
- `GET /api/dag/runtime?limit=120` showed the latest `evaluate_daily` run and summary
- `GET /api/events-page` included the same recovery workflow title/status
- Today / Candidates / Symbol / Ops API surfaces were re-checked and returned usable data for `2026-03-20`
