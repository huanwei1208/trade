# WP9 Dual-Read Compatibility & Rollout Report

Read-only comparison of the new resolver against the legacy single-`current`
read model, plus feature-flag and rollback verification. All checks run against
frozen fixtures and a read-only real-data sample; no real `data/` is mutated.

## Dual-read reconciliation (new resolver vs legacy current)

| Fact | New resolver (Formal channel) | Legacy `btc_current.json` | Agrees |
| --- | --- | --- | --- |
| formal run id | publication-ledger active release run | `current.run_id` | yes (test) |
| canonical file-bytes hash | `artifact_refs[canonical].sha256` | `current.canonical_sha256` | yes (test) |
| market watermark | manifest `watermark` of formal run | manifest `watermark` | yes (test) |

Verified by `tests/observatory/test_dual_read_compat.py`:
- `test_dual_read_formal_identity_agrees`
- `test_dual_read_watermark_agrees`
- `test_dual_read_report_structure`

## Feature flag

`TRADE_OBSERVATORY_ENABLED=0` leaves the `/api/v1/observatory/*` routes
unregistered (guard in `trade_web/backend/app.py`). The old
`/api/data/kline/crypto.BTC` and Data/Research/Ops pages remain untouched and
additive. Verified by `test_feature_flag_disables_routes`.

## Rollback drill

- Catalog generation switch is CAS-based; the prior generation's immutable facts
  are never deleted (`test_rollback_generation_preserved`, `test_facts_not_deleted_on_rebuild`).
- Formal Baseline is unchanged by any catalog update/rebuild.
- Rollback restores the prior Web adapter (feature flag) and prior Catalog
  generation without touching provider artifacts.

## Performance smoke (frozen envelope §20.4)

Recorded by `tests/observatory/test_perf_smoke.py` (CI scale = 2,000 manifests;
envelope target = 10,000, recorded in the emitted report):

| Operation | Envelope target | Observed (CI, 2k) | Constraint |
| --- | --- | --- | --- |
| Catalog full rebuild | <=60 s @ 10k | well under 30 s @ 2k | deterministic content hash |
| context/status | 0 parquet opens | 0 parquet opens (asserted) | catalog/manifest summary only |
| 3-layer composite | <=1.5 s cold | well under 10 s CI bound | three independent layers |

The 0-parquet-open invariant for `context` is enforced by
`test_context_does_not_open_parquet` (regression: the PIT `context()` path was
refactored to `resolve_context_only`, which reads no series artifact).

## Residual notes

- Row-level metrics (return/drawdown/RV) are not yet in the series payload; the
  frontend displays them as unavailable rather than recomputing in the browser
  (read-only invariant). Enriching the facade metrics is a follow-up within the
  frozen contract.
- Attempt receipts remain deferred (Latest Completed Staged Run in V1); the
  Acquisition Calendar shows pre-stage states as unsupported/unknown.
