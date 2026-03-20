# EBRT_09 — Readiness Freeze Fix

**Date**: 2026-03-20
**Status**: ✅ Completed

---

## 1. Problem

Clicking the Ops readiness surface could stall the page instead of opening a usable audit/recovery workspace.

The failure had two real causes:

1. `build_readiness_grid()` in the backend lost its return payload, so the readiness API path was structurally broken.
2. The frontend opened readiness and immediately triggered extra heavy change-detection work, while also writing focused selection state back upward more often than necessary.

---

## 2. Fix scope

### Backend

- [x] Restore the actual `build_readiness_grid()` return payload
- [x] Remove the misplaced return block from `execute_recovery_action()`
- [x] Add caching for daily sentiment file discovery
- [x] Reduce `detect_changed_data()` from per-day grid rebuilds to chunked range reads
- [x] Avoid unnecessary sentiment file scans for unrelated dataset-only checks

### Frontend

- [x] Stop auto-running `detect-changes` on initial readiness open
- [x] Only run explicit change detection for recovery mode or non-default ranges
- [x] Seed changed-state UI from existing cell semantics first
- [x] Avoid unnecessary parent focus rewrites when focus is already synchronized
- [x] Keep polling refresh behavior but remove unnecessary effect churn

---

## 3. Files touched

- `trade_web/backend/readiness.py`
- `trade_web/frontend/src/pages/OpsPage.tsx`

---

## 4. Verification

- [x] `cd trade_web/frontend && npm run build`
- [x] `python -m compileall trade_web/backend/readiness.py trade_web/backend/app.py`

---

## 5. Outcome

Readiness now opens without the initial self-inflicted heavy request burst, and the backend responds with a proper grid payload again. The recovery flow remains available, but expensive change-detection work is deferred to the moments where the user is actually performing recovery analysis.
