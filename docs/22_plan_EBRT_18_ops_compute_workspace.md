# EBRT_18 Ops Compute Workspace

## Goal

Focused redesign of the Ops workspace from a flat readiness-first page into a computation operations workspace:

- Readiness Matrix
- Compute Layers
- Replay Builder
- Trust / Calibration
- Workflow / Audit

## Progress

- [x] Add backend ops workspace taxonomy and compute-layer payloads
- [x] Add backend node result / dependency path / replay preview / replay execute APIs
- [x] Add backend tests for compute-layer grouping, replay preview, and batch workflow trace
- [x] Redesign Ops tabs to `overview / readiness / compute / replay / trust / audit`
- [x] Add node type taxonomy in frontend: source / feature / factor / model / decision / workflow
- [x] Group readiness rows by layer and add row-level node selection
- [x] Add compute-layer result browser with inspector
- [x] Add replay builder with multi-select, scope preview, and workflow progress
- [x] Update zh-CN / en-US copy for new Ops semantics
- [x] Run frontend build
- [x] Run targeted pytest
- [x] Verify live Ops APIs locally

## Verified

- `GET /api/ops/compute-layers`
- `GET /api/ops/node/{id}/result`
- `GET /api/ops/dependency-path`
- `POST /api/ops/replay/preview`
- `POST /api/ops/replay/execute`
- `GET /api/workflows/{id}`
- existing Ops dependencies:
  - `GET /api/readiness-grid?days=30`
  - `GET /api/status`
  - `GET /api/workflows?limit=3`

## Notes

- Readiness remains a health matrix, not a result viewer.
- Compute results now live in a dedicated compute-layer view and inspector.
- Replay builder uses the existing workflow/event/job infrastructure rather than inventing a second execution-status system.
- This is still not a full graph editor; dependency visualization is a compact path panel, not a full interactive DAG canvas.
