## Context

The BTC assurance pipeline (docs/23, change `crypto-data-assurance-and-validation-v1`)
already emits immutable runs under `data/market/crypto/runs/btc/<run_id>/` with
`manifest.json`, `canonical/primary/shadow/reconciliation/revisions.parquet`, and
`raw/`; a mutable `btc_current.json` pointer; and publish/rollback audits under
`data/market/crypto/audit/`. The H1 study persists through
`trade_py/data/warehouse/crypto_store.py` with a `validation_run_id`,
`generation_id`, and the `_crypto_validation_current.json` pointer moved atomically
by the existing lifecycle. This change adds a read-only projection + resolution
layer on top of those immutable facts. It does not change the write side except for
three explicitly-approved additive write sides.

Grounding facts verified on 2026-07-19 (must not be hardcoded into logic):
manifests carry `created_at`, `data_readiness`, `watermark`, `gates[D0..D4]`,
`health`, `artifact_hashes`, `acquisition_evidence.as_of` but NOT `staged_at`,
`assurance_completed_at`, or `capture_completed_at`. Canonical parquet columns:
`date, open, high, low, close, volume, provider, venue, instrument, base_asset,
quote_asset, interval, bar_open_at, bar_close_at, is_final, fetched_at,
available_at, payload_hash, schema_version, run_id`. This drives the legacy
timestamp adapter (§7.7) and the four-clocks contract.

## Goals / Non-Goals

Goals: one shared snapshot-resolution kernel for Web and Jupyter; orthogonal
read-side state; layered composite; point-in-time reconstruction; H1 research
evidence bound to immutable snapshots; fail-closed read-only safety.

Non-Goals (see proposal): automatic trading, real-time/tick monitoring, indicator
walls, single trust score, browser-side formal metrics, auto-promoting notebook
conclusions, empty all-asset platform, deleting existing pages in round one.

## Decisions

### Ownership and module boundaries

| Responsibility | Owner |
| --- | --- |
| Snapshot domain, channels, four clocks, purpose fitness, state axes | `trade_py/observatory/domain/` |
| Catalog projection/rebuild/reconcile | `trade_py/observatory/catalog/` |
| Artifact verification and snapshot resolution | `trade_py/observatory/service/` |
| Run/date/trust/research query facade + read-only SDK | `trade_py/observatory/query/` |
| PIT resolution, knowledge mode, revision policy, fingerprints | `trade_py/observatory/pit/` |
| Crypto research workflow adapter over H1 | `trade_py/observatory/research/` |
| FastAPI routes/schemas | `trade_web/backend/observatory/` |
| React workspace | `trade_web/frontend/src/pages/observatory/` |
| Shared chart/evidence components | `trade_web/frontend/src/components/observatory/` |
| Thin notebook/template | `research/notebooks/` |
| Contract/fixture tests | `tests/observatory/` + `tests/test_btc_observatory_*` |

Avoid: growing `trade_web/backend/app.py`; stuffing all frontend logic into
`DataPage.tsx`; writing SQL in services; duplicating formal feature logic in the
notebook; introducing a second implicit source of truth.

### Implementation choices frozen in M0 (§31)

1. **Snapshot Catalog storage**: a standalone rebuildable SQLite database at
   `data/market/crypto/observatory/catalog.sqlite` (outside `trade.db`), additive
   and reversible; never required for correctness since it is a projection.
2. **React main chart**: extend the existing SVG chart implementation; no new
   charting dependency in V1.
3. **Notebook home**: `research/notebooks/`; JupyterLab is a dev-only optional
   dependency, not required for the SDK or Web.
4. **Content-addressed raw storage**: reserved only in V1; no migration of existing
   artifacts. The domain model references artifacts by run-relative path + SHA-256
   so a future CAS migration is additive.
5. **Old Data/Research pages**: retained additively with an Observatory deep link;
   no full-page redirect in V1; final deprecation deferred to M6.
6. **Latest Attempt**: V1 downgrades to **Latest Completed Staged Run**. Additive
   attempt receipts are deferred; the Acquisition Calendar shows pre-stage states as
   `unsupported`/`unknown`. The deferred attempt-receipt task and its crash/reconcile
   tests are recorded below and are NOT unconditional acceptance items.

### Snapshot Catalog schema (v1)

Tables (all projected, rebuildable): `runs` (run_id, watermark, created_at,
data_readiness, canonical_hash, primary_hash, shadow_hash, contract_version,
gate summary, artifact refs, legacy time provenance), `gates`, `findings`,
`releases` (release_id, run_id, published_at, previous_release, audit ref,
rollback eligibility), `revisions_index`, and `research_runs` (mirror of the H1
receipt/pointer). A `catalog_meta` row holds `catalog_schema_version`,
`source_fingerprint` (hash of the sorted manifest/audit set), and
`generation_id`.

### Selector resolution and ordering (frozen)

- Latest Observed order key: `(market_watermark, effective_as_of,
  capture_completed_at, run_id)` descending.
- Evaluated Candidate order key: `(assurance_completed_at, staged_at, run_id)`
  descending.
- Latest Staged order key: `(staged_at, manifest.created_at, run_id)` descending.
- Formal Baseline: resolved from publication/rollback ledger, not "latest ready".
- Legacy null ordering: business key first, then `created_at`, then `run_id`;
  never mtime.

### Data flow

`immutable manifests/audits -> Catalog projection -> Snapshot Resolver ->
{FastAPI routes, Python SDK} -> {React Observatory, Jupyter notebook}`. Only the
resolver maps semantic channels to immutable runs; browser and notebook never parse
the current pointer or join file paths. The composite is a comparison projection and
never a dataset.

## Risks / Trade-offs

- **Legacy time imprecision**: mitigated by the versioned adapter, `LEGACY_TIME_
  UNPROVEN`, and returning `PIT_NOT_PROVEN` instead of guessing. Trade-off: some
  historical installation-observed queries are honestly unavailable.
- **Catalog drift**: mitigated by source fingerprint verification and
  `CATALOG_STALE` on reads; the Catalog is always rebuildable from immutable facts.
- **Dual write authority for H1**: avoided by making the research adapter mirror the
  existing pointer/receipt only; the existing lifecycle + atomic writer stays the
  single current-selection authority.
- **Concurrency**: reads use the existing shared lock and read one complete Catalog
  generation via generation CAS; publish/rebuild never leaves a mixed generation.

## Migration Plan

Schema-versioned, additive, reversible: (1) generate an evidence coverage report
from frozen fixtures and a read-only real sample; (2) `rebuild --dry-run` to a temp
Catalog with source fingerprint and row counts; (3) dual-read reconciliation of
Formal identity, Candidate, watermarks, hashes, findings, error semantics; (4)
atomic generation pointer/CAS switch retaining the prior generation;
(5) feature-flag the Web routes separately from the Catalog schema switch;
(6) publish/rollback and Catalog update stay generation-consistent for readers.

Rollback: disable new nav/routes, restore the old Web API adapter, switch back to
the prior Catalog generation while retaining the new one for forensics, keep all
new manifests/receipts, and leave the Formal Baseline unchanged.

## Deferred tasks (recorded, not unconditional acceptance items)

- **Additive attempt receipts** and the Latest Attempt product promise, including
  crash/abandoned reconciliation tests and the associated UI/E2E acceptance. V1 uses
  Latest Completed Staged Run instead.
- Two-dimensional Revision Surface (V1 ships a revision timeline + diff table with a
  surface-capable data contract).
- Content-addressed raw storage migration.

## Open Questions

None blocking. Directory names may be adjusted during design review provided the
ownership boundaries and contracts above are preserved; any rename must be recorded
as an equivalence mapping in tasks.
