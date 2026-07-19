# Implementation Tasks

## WP0 - OpenSpec and semantic freeze

- [x] 0.1 Write proposal, design, and three capability specs (snapshot-semantics, observatory-workspace, point-in-time-research-lab)
- [x] 0.2 Record supersession of CoinGecko/cross_asset provider/path narrative; keep D0-D5, H1, publish safety in force
- [x] 0.3 Freeze the crypto.BTC / OKX BTC-USDT / Binance BTCUSDT identity map (identity_map.md)
- [x] 0.4 Freeze reason codes, HTTP golden schema, selector predicates/order, knowledge mode, revision policy, snapshot identity, purpose fitness, H1 identity adapter, frontend runner (frozen_contracts.md)
- [x] 0.5 Produce the PIT evidence coverage report generator and a committed sample report (pit_evidence_coverage.md)
- [x] 0.6 Decide Latest Attempt downgrade to Latest Completed Staged Run; record deferred attempt-receipt task
- [x] 0.7 `openspec validate btc-observatory-research-lab-v1 --strict` passes

## WP1 - Attempt and Catalog projection

- [x] 1.1 Define observatory domain models (CaptureAttempt, ObservationRun, QualityFinding, Release, ResearchRun, four clocks) — tests: `tests/observatory/test_domain.py`
- [x] 1.2 Legacy timestamp adapter with provenance/precision and no mtime — tests: `tests/observatory/test_legacy_time_adapter.py`
- [x] 1.3 Rebuildable Snapshot Catalog projection with schema version + source fingerprint — tests: `tests/test_btc_observatory_catalog.py`
- [x] 1.4 CLI `trade observatory catalog {rebuild,update,verify,status}` with dry-run and generation CAS — tests: `tests/observatory/test_catalog_cli.py`
- [x] 1.5 Determinism, corruption recovery, stale detection, incremental==full — tests: `tests/test_btc_observatory_catalog.py`

## WP2 - Resolver and SDK

- [x] 2.1 Channel resolution (observed/evaluated_candidate/formal/exact) with frozen order keys — tests: `tests/test_btc_observatory_snapshot_resolver.py`
- [x] 2.2 State axes + freshness/compatibility + purpose fitness mapping (mapping_policy_version) — tests: `tests/observatory/test_state_mapping.py`
- [x] 2.3 Snapshot identity hash + latest-alias freeze + view fingerprint — tests: `tests/test_btc_observatory_snapshot_resolver.py`
- [x] 2.4 Layered composite comparison, COMPOSITE_NOT_DATASET, invalid-candidate no-regress — tests: `tests/test_btc_observatory_snapshot_resolver.py`
- [x] 2.5 Artifact/hash/shared-lock verification + fail-closed; BTC lowercase path fix — tests: `tests/test_btc_observatory_snapshot_resolver.py`
- [x] 2.6 Read-only Python SDK (`observe.asset(...).snapshot(...)`) with zero-write/zero-network tests — tests: `tests/observatory/test_sdk_readonly.py`

## WP3 - API

- [x] 3.1 FastAPI observatory router (context/series/dates/trust/runs/diff/hypotheses/research-runs) — tests: `tests/test_btc_observatory_api.py`
- [x] 3.2 OpenAPI golden success/degraded/error fixtures + HTTP status/reason mapping — tests: `tests/test_btc_observatory_api.py`
- [x] 3.3 ETag/304, stable cursor pagination, path traversal rejection, CATALOG_STALE — tests: `tests/test_btc_observatory_api.py`
- [x] 3.4 Minimal `app.py` registration only (no logic) — tests: `tests/test_btc_observatory_api.py`

## WP6 - Point-in-Time

- [x] 6.1 Dual knowledge_mode as-of resolution (market_available, installation_observed) — tests: `tests/observatory/test_pit_resolver.py`
- [x] 6.2 Revision validity, as_known vs latest_restated (RESTATED_NOT_PIT) — tests: `tests/observatory/test_pit_resolver.py`
- [x] 6.3 Evidence coverage + PIT_NOT_PROVEN + backfilled/PIT-unproven — tests: `tests/observatory/test_pit_resolver.py`
- [x] 6.4 Deterministic snapshot/view fingerprint replay + future-fact invisibility — tests: `tests/observatory/test_pit_resolver.py`

## WP7 - Crypto research workflow

- [x] 7.1 Versioned kernel adapter over existing H1 identity/current pointer — tests: `tests/test_btc_observatory_research.py`
- [x] 7.2 CLI `trade research btc {run,import,promote}` with dry-run + atomic receipts — tests: `tests/test_btc_observatory_research.py`
- [x] 7.3 Failed-run no-half-state, promote appends receipt, single current authority — tests: `tests/test_btc_observatory_research.py`

## WP4/WP5 - Web surfaces

- [x] 4.1 Snapshot Context Bar + three-layer composite + market summary + why-not-formal + what-changed + URL restore — tests: frontend unit/e2e
- [x] 4.2 Trust/Lineage: calendars, Date Evidence, basis/revision, run diff — tests: frontend unit/e2e
- [x] 4.3 Non-color accessibility, Candidate texture/watermark, observed-only layer — tests: a11y
- [x] 4.4 Frontend test runner (Vitest + Playwright + axe) with `test:unit`/`test:e2e`/`test:a11y` scripts — tests: build/typecheck

## WP8 - Research UI + thin notebook

- [x] 8.1 H1 hypothesis evidence UI (sample/fold/effect/CI/placebo/multiple-testing) — tests: frontend unit
- [x] 8.2 Open in Lab deep link + thin reproducible notebook template — tests: notebook smoke/repro
- [x] 8.3 Observe/Investigate future-label leakage is zero (DOM + API) — tests: e2e + api

## WP9 - Compatibility, performance, rollout

- [x] 9.1 Dual-read report (old vs new resolver) on read-only real sample — tests: `tests/observatory/test_dual_read_compat.py`
- [x] 9.2 Feature flag for Web routes; deprecated `/api/data/kline/crypto.BTC` retained — tests: `tests/test_btc_observatory_api.py`
- [x] 9.3 Performance smoke against frozen benchmark envelope (10k manifests, 730-day 3-layer composite, run diff, ETag/304) — tests: `tests/observatory/test_perf_smoke.py`
- [x] 9.4 Rollback drill (generation + route), no facts deleted; final full validation — tests: `tests/observatory/test_dual_read_compat.py`

## Verification and delivery

- [x] V.1 Working-tree safety check before staging; only intentional files staged
- [x] V.2 Focused pytest + `python -m compileall trade_py trade_web tests`
- [x] V.3 Frontend build/typecheck + Vitest/Playwright/axe targets
- [x] V.4 `openspec validate btc-observatory-research-lab-v1 --strict`
- [x] V.5 Commit validated rounds per WP; push every 3-5 commits; squash-merge to master

## Deferred (recorded, not unconditional acceptance)

- [ ] DF.1 Additive attempt receipts + Latest Attempt promise + crash/abandoned reconcile tests (V1 uses Latest Completed Staged Run)
- [ ] DF.2 Two-dimensional Revision Surface (V1 ships timeline + diff table on a surface-capable contract)
- [ ] DF.3 Content-addressed raw storage migration
