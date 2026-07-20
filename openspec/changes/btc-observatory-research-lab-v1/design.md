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
   **Superseded 2026-07-20** by the Phase B immutable-generation layout below: the
   single mutable `catalog.sqlite` + `generation.json` pair becomes a typed
   `catalog-current.json` pointer plus install-once
   `generations/catalog-<generation_id>.{sqlite,manifest.json}` artifacts. The old
   pair is retained read-only as a legacy pair. See "Phase B immutable-generation
   layout".
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

### Phase B immutable-generation layout (frozen 2026-07-20)

The consensus review on 2026-07-20 (score 3.3/10) found the WP1 storage decision
(§31.1: one mutable `catalog.sqlite` in-place plus one `generation.json` written by
each read via `build_catalog()`) does not deliver the immutable generations, CAS,
corruption detection, or asset isolation the specs require (F6/F7/F8/F17). Phase B
freezes the following replacement. The precise contract clauses (scope tuple,
version constants, verification chain, publish protocol, read barrier, rollback
rules, legacy-fact policy, envelope) live in `frozen_contracts.md` §"Phase B
generation contracts"; this section records the design rationale and the old→new
equivalence/supersession mapping.

Layout under `<data_root>/market/crypto/observatory/`:

- `catalog-current.json` — typed, CAS-switched pointer (the only mutable file).
- `generations/catalog-<generation_id>.sqlite` — install-once immutable DB.
- `generations/catalog-<generation_id>.manifest.json` — install-once immutable
  generation manifest.
- `.candidate-<uuid>/` — hidden, same-filesystem temp for the in-progress build.

Every generation is bound to a `CatalogScope`
`(asset_id, data_family, source_contract_version, scope_policy_version)`; the only
Phase B scope is `(crypto.BTC, market_assurance, btc-data-v1, obs-scope-v1)`.
`news`/`sentiment`/`research` are distinct `data_family` values that never enter the
BTC market ledger/head/quality/ETag and are out of Phase B business scope.

Rationale highlights (see frozen_contracts.md for the binding text):

- **Immutability + CAS**: publishers materialize a candidate on the same
  filesystem, verify it fully (integrity_check + logical hash + file SHA-256, fsync)
  outside the lock, then under the exclusive BTC assurance lock re-confirm the live
  fingerprint + expected-previous and CAS the pointer as the last step. No
  shared→exclusive upgrade; install-once (never overwrite). This removes the
  in-place `unlink`/overwrite of F7 and retains every prior generation.
- **Whole-chain verification**: reads verify
  `pointer → manifest → file SHA-256 → catalog_meta → deserialized logical hash`
  and fail closed on any break (`CATALOG_CORRUPT`). The `logical_content_hash`
  covers all resolver fields, so a tampered ordinary business row fails the read
  (fixes F6/F8/F9).
- **Read barrier**: a shared-lock reader freezes one pointer, opens one immutable
  generation, deserializes one `CatalogReadSnapshot`, and shares it across
  resolver/query/diff/SDK with zero `build_catalog()` and zero writes. This
  replaces `load_catalog_checked()`'s per-read `build_catalog()` (RA.3).
- **Asset scope**: manifests/audits/fingerprints/PKs/releases are scoped by
  `asset_id`; new audits live under `audit/by-asset/crypto.BTC/{publish,rollback}/`
  so scope is decidable before parsing; unattributable legacy global audits are
  fail-closed migration blockers (fixes F17).

Old → new equivalence / supersession mapping:

| WP1 design (superseded) | Phase B design (frozen) | Relationship |
| --- | --- | --- |
| `catalog.sqlite` (single, overwritten in place) | `generations/catalog-<generation_id>.sqlite` (install-once, retained) | supersedes; old file kept read-only as legacy pair |
| `generation.json` (untyped pointer, `_cas_generation`) | `catalog-current.json` (typed, scoped, CAS pointer) | supersedes; new pointer carries `CatalogScope` + schema versions |
| `_GENERATION_KEYS` (schema/fingerprint/generation_id/content_hash) | generation manifest identity set (adds scope, projection/pointer/manifest versions, file SHA-256, fact-set hash) | extends; superset, whole-chain verified |
| `load_catalog_checked()` calls `build_catalog()` per read | read barrier deserializes one immutable `CatalogReadSnapshot` | supersedes; zero build/zero write on reads |
| `rebuild()` overwrites live DB then CAS pointer | candidate build → verify/fsync → exclusive re-confirm → install-once → CAS pointer | supersedes; atomic, non-destructive |
| global `audit/{publish,rollback}/*.json` scanned unscoped | `audit/by-asset/crypto.BTC/{publish,rollback}/` + whitelisted legacy adaptation | extends; legacy pair retained read-only, unattributable = blocker |
| implicit "BTC only" | explicit `CatalogScope`; `news`/`sentiment`/`research` are other `data_family` | extends; cross-family isolation frozen |

Migration behavior: when only the legacy `catalog.sqlite` + `generation.json` pair
exists (no `catalog-current.json`), reads diagnose `CATALOG_STALE` with a
`legacy_catalog_requires_rebuild` marker and the operator rebuilds into the new
layout out of band. New read code never migrates the legacy pair inside a GET/SDK
read and never deletes it.

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
- **Concurrency**: reads take the existing shared BTC assurance lock, freeze one
  typed pointer, and open exactly one immutable generation (Phase B read barrier);
  publishers verify a candidate outside the lock, then under the exclusive lock
  re-confirm the live fingerprint + expected-previous and CAS the
  `catalog-current.json` pointer as the last step, so readers never observe a mixed
  generation and a lost CAS is a stable `CATALOG_CAS_CONFLICT`.

## Migration Plan

Schema-versioned, additive, reversible: (1) generate an evidence coverage report
from frozen fixtures and a read-only real sample; (2) `rebuild --dry-run` to a
same-filesystem candidate with `CatalogScope`, source fingerprint, and row counts;
(3) dual-read reconciliation of Formal identity, Candidate, watermarks, hashes,
findings, error semantics; (4) install the immutable
`generations/catalog-<generation_id>.{sqlite,manifest.json}` (install-once) and CAS
the `catalog-current.json` pointer, retaining all prior generations; (5)
feature-flag the Web routes separately from the Catalog schema switch; (6)
publish/rollback and Catalog update stay generation-consistent for readers. The
legacy `catalog.sqlite` + `generation.json` pair is retained read-only; when only
the legacy pair exists, reads diagnose `CATALOG_STALE` with
`legacy_catalog_requires_rebuild` and the operator rebuilds into the new layout out
of band (never migrated inside a GET/SDK read).

Rollback: disable new nav/routes and restore the old Web API adapter for a route
rollback; a Catalog `catalog rollback --to-generation <id>` is a pointer-only CAS
back to a prior generation that shares the current `CatalogScope` and
`source_fingerprint` (a projection/policy rollback), retaining every generation for
forensics, keeping all new manifests/receipts, and leaving the Formal Baseline
unchanged. A target built from a different `source_fingerprint` is rejected
(`CATALOG_ROLLBACK_REJECTED`); Formal/source truth rollback goes only through
`BtcRunStore` authoritative rollback, after which a new generation is built.

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
