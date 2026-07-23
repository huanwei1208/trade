# BTC Observatory Correctness Remediation Execution Plan

> Status: execution-ready handoff for an implementation agent
> Baseline commit: `73ade2a` (`feat(observatory): BTC Observatory & Research Lab V1`)
> Implementation branch: `wt/btc-observatory-p0-fixes-20260720`
> Recommended worktree: `/tmp/trade-wt-btc-observatory-p0-fixes`
> Contract source: `openspec/changes/btc-observatory-research-lab-v1/`
> Reviewer/acceptance owner: Codex

## 0. Instructions to the implementation agent

Read these files completely before editing:

1. `AGENTS.md`
2. this document
3. `openspec/changes/btc-observatory-research-lab-v1/proposal.md`
4. `openspec/changes/btc-observatory-research-lab-v1/design.md`
5. `openspec/changes/btc-observatory-research-lab-v1/frozen_contracts.md`
6. all specs under `openspec/changes/btc-observatory-research-lab-v1/specs/`
7. `openspec/changes/btc-observatory-research-lab-v1/tasks.md`

Execute one phase at a time. For every phase:

1. Add regression tests that reproduce the stated failures.
2. Implement the smallest coherent production change that satisfies the frozen
   behavior, without weakening the tests or changing expected semantics.
3. Run the phase validation commands.
4. Review `git diff --check` and `git status -sb`.
5. Commit the validated phase as one logical commit with validation and
   compatibility notes in the commit body.
6. Stop and hand the commit to Codex for review. Do not begin the next phase until
   Codex returns `ACCEPTED`.

If a frozen contract is internally impossible or conflicts with real source facts,
do not silently redefine it. Write a short design-decision proposal under the
existing OpenSpec change, leave the phase uncommitted, and stop for review.

## 1. Objective

Turn the current BTC Observatory from a tested UI/projection scaffold into a
trustworthy, reproducible and operable read/research system.

Completion means all of the following are true:

- A public command shown in docs or Web works through the real `./trade` wrapper.
- A returned immutable snapshot can be replayed exactly across Web, SDK and
  Jupyter.
- Historical point-in-time queries cannot see later runs, releases, revisions,
  findings, watermarks or research outcomes.
- Missing clock evidence fails closed instead of being treated as visible.
- Readers use one complete Catalog generation and never rebuild the projection on
  a GET/SDK path.
- Pointer, release, manifest and all rendered evidence artifacts are verified as
  one consistent read transaction.
- Per-date quarantine, missingness and revisions are visible rather than removed
  from the observation surface.
- A committed Research run really executes the H1 kernel and persists through the
  existing authority; it is not a plan or placeholder receipt.
- Web rollout, ETag, range handling and performance behavior work against a real
  backend, not only mocked browser fixtures.

## 2. Current confirmed failures

The implementation agent must treat these as reproduction targets, not as optional
review comments.

| ID | Severity | Confirmed failure |
| --- | --- | --- |
| F1 | CRIT | Unknown `snapshot_id` is ignored and resolves to the moving channel. |
| F2 | CRIT | A 2020 `market_available` request resolves a release published in 2026. |
| F3 | CRIT | SDK, Web single-series and composite use different PIT paths and return different histories. |
| F4 | CRIT | `research run --commit` returns delegation strings without executing or persisting H1. |
| F5 | CRIT | `promote --commit` writes a receipt saying a clean rerun is still required. |
| F6 | CRIT | Catalog SQLite can be corrupt or absent while `verify` reports current and reads succeed. |
| F7 | CRIT | Catalog "CAS" overwrites one database and retains no rollback generation. |
| F8 | CRIT | Pointer/release/artifact inconsistency is not verified as one transaction. |
| F9 | CRIT | Composite and Date Evidence swallow integrity errors into partial HTTP 200/null responses. |
| F10 | HIGH | Official `./trade observatory` and `./trade research btc` commands are unreachable. |
| F11 | HIGH | Real BTC D3 reconciliation has five warning dates, but Observatory reports zero excluded dates and zero row quality flags. |
| F12 | HIGH | Rows are hard-coded as `present`, `unchanged`, and lifecycle membership such as `staged`. |
| F13 | HIGH | Market Summary formal metrics are not populated. |
| F14 | HIGH | Backend defaults Observatory on, frontend always advertises it, while the real data root has no Catalog. |
| F15 | HIGH | Every request rescans manifests; ETag is checked after expensive work and the frontend sends `no-store`. |
| F16 | HIGH | The performance test claims 10k coverage while using 2k manifests and relaxed bounds. |
| F17 | HIGH | Global crypto audit scanning is not asset-scoped; a later ETH publish can corrupt BTC Formal resolution. |

Known real-data probe facts from 2026-07-20:

- Catalog dry-run finds 9 BTC runs and 2 releases.
- Unknown snapshot `definitely-not-a-real-snapshot` resolves successfully today;
  it must become `SNAPSHOT_NOT_FOUND`.
- A historical cut `2020-01-01T00:00:00Z` currently resolves a release published
  in 2026; it must not do so.
- Run `cdbbb5c608ba22b1c4aa06b0` has D3 `warn_rows=5`; current projection returns
  725 values, zero excluded dates, zero quality-flagged rows and all revisions as
  `unchanged`.

## 3. Hard constraints

### 3.1 Safety

- Never write to the real `data/` tree during tests or probes.
- Tests use `tmp_path`, frozen fixtures or a temporary copy/symlink layout.
- Real-data checks are explicitly read-only. Catalog real-data validation uses
  `--dry-run` unless the user separately authorizes a live rebuild.
- No provider network calls, sync, publication, rollback or database migration from
  a GET, SDK read, Web render or test.
- Do not commit generated Catalogs, parquet data, browser output, caches, notebooks
  outputs, `.venv`, `node_modules` or local configuration.

### 3.2 Semantic integrity

- Do not use filesystem mtime as a business clock.
- Do not catch integrity errors merely to keep a chart visible.
- Do not treat a missing `available_at`, `fetched_at`, first-seen or revision clock
  as visible/proven.
- Do not forward-fill or interpolate missing market dates.
- Do not merge Formal, Candidate and Observed OHLCV into one truth.
- Do not recompute formal indicators in the browser.
- Do not add a second H1 current pointer or bypass
  `persist_crypto_validation_outputs()`.
- Do not make other-asset manifests or audits affect BTC snapshot identity, ETag or
  active release.

### 3.3 Testing integrity

- Do not update an expected fixture to match known-wrong behavior.
- Do not replace a real contract assertion with `assert key in payload`.
- Do not make required E2E tests self-skip when backend wiring is absent.
- Mocked UI tests may remain, but they do not count as real-stack acceptance.
- A task checkbox may be marked complete only after its exact acceptance commands
  pass.

## 4. OpenSpec remediation bookkeeping

At the beginning of Phase A, append a section named
`Audit Remediation — 2026-07-20` to
`openspec/changes/btc-observatory-research-lab-v1/tasks.md`.

Add unchecked tasks for:

- RA.1 public CLI and rollout readiness
- RA.2 immutable Catalog generations, CAS, asset scope and rollback
- RA.3 fail-closed consistent read transaction
- RA.4 immutable snapshot replay and one shared PIT kernel
- RA.5 real revision/evidence coverage and per-date row semantics
- RA.6 real H1 run/import/promote workflow
- RA.7 ETag/range/performance/telemetry
- RA.8 real-stack integration, real-data read-only probe and final consensus review

Do not erase the old checked history. The remediation section records that the
2026-07-20 audit invalidated the earlier completion claim. Mark each RA task only
when the corresponding phase below is accepted by Codex.

## 5. Phase A — Public CLI and safe rollout boundary

### Goal

Make every advertised command reachable and ensure an unprepared installation does
not expose a broken Observatory page by default.

### Required implementation

1. Add `observatory` to the root `trade` wrapper dispatch and help output.
2. Add `btc` to the canonical `trade research` command group while retaining
   existing `model`, `factor` and `evaluate` behavior.
3. Route `trade research btc {run,import,promote}` into one reusable BTC research
   parser; do not duplicate workflow logic between CLI modules.
4. Make Observatory rollout explicitly enabled rather than default-on.
5. Add a lightweight backend capability/readiness response used by the frontend to
   decide whether to show Observatory navigation. It must distinguish:
   `disabled`, `catalog_missing`, `catalog_stale`, `catalog_corrupt`, `ready`, and
   `error`. `error` is the enabled-but-route-registration-failed fail-closed state:
   when the feature is on but data-route/facade registration raised, `/capability`
   still answers `state=error` with `show_nav=false` and a stable
   `reason_code=route_registration_failed` (never `str(exc)`/paths; the full
   exception is logged server-side), so a broken deploy never advertises a
   non-functional Observatory and the probe never silently disappears.
6. Startup and the new capability/readiness probe must not auto-build the Catalog:
   the probe is strictly no-build and read-only (pointer + SQLite integrity/meta
   inspection only). Phase A scope is limited to this NEW startup/capability path.
   It does NOT claim that every pre-existing data GET path is already build-free:
   the pre-existing data-route in-memory projection remains default-off in Phase A
   (rollout is explicitly enabled) and is removed/replaced by the immutable
   generation read side in Phase B (RA.2/RA.3). Do not mark those data GET paths
   fixed here.
7. Add a strict Catalog status/verify mode suitable for deployment gates: missing,
   stale or corrupt returns non-zero and emits structured JSON; a human
   informational status may retain a non-strict zero mode for compatibility.

### Tests required

- Subprocess tests invoke the real `./trade`, not `trade_py.cli.*.main()` directly.
- `./trade observatory catalog status --data-root <fixture> --json` reaches the
  Observatory parser.
- `./trade research btc run --dry-run --data-root <fixture> --json` reaches the BTC
  workflow.
- Existing research groups still parse and existing CLI contract tests pass.
- Backend route registration is tested with the feature disabled and enabled.
- Frontend nav is hidden for disabled/unready and shown only for ready.
- No test mutates real data.

### Focused validation

```bash
uv run --extra dev pytest \
  tests/observatory/test_catalog_cli.py \
  tests/test_btc_observatory_research.py \
  tests/test_btc_observatory_api.py \
  tests/test_cli_contracts.py \
  tests/test_cli_lazy_loading.py -q

python -m compileall trade_py trade_web tests
npm --prefix trade_web/frontend run test:unit
```

### Commit

`fix(observatory): wire public CLI and gate rollout readiness`

Stop for Codex review.

## 6. Phase B — Immutable Catalog generations and consistent integrity

### Goal

Make Catalog SQLite an actual read projection with immutable generations,
corruption detection, asset isolation, concurrency safety and reversible switching.

> **Batch B0 (contract freeze, 2026-07-20)**: before any Python/TS/test change, the
> Phase B generation contracts are frozen in
> `openspec/changes/btc-observatory-research-lab-v1/frozen_contracts.md`
> (§"Phase B generation contracts"), `design.md` (§"Phase B immutable-generation
> layout"), and `specs/snapshot-semantics/spec.md`. The design below consumes those
> frozen clauses verbatim; RA.2/RA.3 stay unchecked until the implementation batch is
> accepted by Codex.

### Required design

All clause numbers below are frozen in `frozen_contracts.md` §"Phase B generation
contracts" (B.1–B.8, including the B.7a primary reason-code precedence); this list
is the execution view, not a second source of truth.

1. **Scope (B.1)**: bind every generation to
   `CatalogScope = (asset_id, data_family, source_contract_version,
   scope_policy_version)`. The only Phase B scope is
   `(crypto.BTC, market_assurance, btc-data-v1, obs-scope-v1)` via a versioned scope
   adapter (`btc-data-v1` accepts the legacy contract version). `news`/`sentiment`/
   `research` are different `data_family` values and never enter the BTC market
   ledger/head, quality, ETag, or fingerprint; their business is out of Phase B.
2. **Layout (B.2)**: use a mutable typed pointer `observatory/catalog-current.json`
   (the only mutable file), install-once immutable
   `observatory/generations/catalog-<generation_id>.{sqlite,manifest.json}`, and
   install-once immutable `observatory/commits/catalog-switch-<operation_id>.json`
   switch receipts forming a hash-linked committed history that the pointer head
   pins. Materialize the candidate in a hidden same-filesystem temp. Never overwrite
   or unlink a live generation or receipt. Retain the legacy `catalog.sqlite` +
   `generation.json` pair read-only; when only the legacy pair exists, diagnose
   `CATALOG_STALE` + `legacy_catalog_requires_rebuild` and never migrate inside a
   GET/SDK read.
3. **Identity/integrity (B.3)**: derive `generation_id` from the full scope, catalog
   schema version (`obs-catalog-v2`), manifest schema version, projection policy
   version, source fingerprint, and the full `logical_content_hash`
   (`pointer_schema_version` and `switch_receipt_schema_version` do NOT by themselves
   change it). The typed pointer carries scope, schema versions, current/previous
   generation ids, and `head_commit_ref`/`head_commit_sha256`; each canonical-JSON
   switch receipt carries its schema version, `operation_id`, `operation`, scope,
   `sequence`, previous commit ref+sha, from/to generation ids, to-manifest ref+sha,
   source fingerprint, `expected_pointer_sha256` (null sentinel when absent), and
   `occurred_at`. The manifest carries scope, pointer/manifest/schema/projection
   versions, `generation_id`, `source_fingerprint`, `logical_content_hash`, SQLite
   SHA-256, DB filename, fact count, and fact-set hash. The verification chain,
   applied on every read (B.4), is
   `pointer -> head switch receipt -> manifest -> file SHA-256 -> catalog_meta -> deserialized logical hash`
   (a normal GET verifies only the head receipt; diagnostics traverse the chain). The
   logical hash covers all Catalog resolver fields (runs, contracts, four clocks +
   provenance, gates, findings, artifact refs, `release_events` + `active_release_head`
   separately, revisions index, the authoritative source `btc_current` snapshot, and
   the relevant fact set) — never a subset and never `catalog-current.json`; no OHLCV
   payload is stored inside the Catalog SQLite.
4. **Durable publish/CAS/locks (B.4)**: reuse and publicly expose the BTC assurance
   lock owner (`BtcRunStore`, `.btc-assurance.lock`). Freeze a scoped
   `SourceSnapshot` + the exact expected pointer SHA (or absent sentinel) under a
   shared lock from one byte batch; outside the lock project/commit/close/fsync the
   candidate DB, write+fsync the manifest, and fsync the candidate dir (no
   shared→exclusive upgrade); under an exclusive lock recheck the exact live
   fingerprint and exact expected pointer SHA; install immutable DB + manifest
   install-once (no-overwrite renames, fsync `generations/`); write the immutable
   switch receipt into `commits/` (fsync); replace `catalog-current.json` last, fsync
   file and `observatory/` parent. A recheck that finds the current generation
   already equals the verified candidate (matching source/scope) is a success no-op
   (`changed=false`/`committed=false`) with no second receipt; a different observed
   target/pointer SHA or changed source is `CATALOG_CAS_CONFLICT`. A crash before the
   pointer replacement leaves the old pointer valid and new artifacts orphaned; after
   it the complete new chain is valid. A ready Catalog with no lockfile fails closed;
   GET never creates the lockfile. Retain all committed generations/receipts (no
   destructive GC); orphans are diagnosed, never served or deleted.
5. **Read barrier (B.4)**: market readers take a strict shared lock, freeze one typed
   pointer, verify pointer ↔ head switch receipt link consistency, open and verify
   one immutable generation, deserialize one `CatalogReadSnapshot`, and reconcile BTC
   `current`/ledger/manifest identity; resolver/query/diff/SDK reuse it. A normal GET
   verifies only the head receipt, not the full history. Reads do zero
   `build_catalog()` and zero writes; the lock covers only freeze/open/verify, and
   response bytes are built outside the lock on immutable refs.
   `load_catalog_checked()` deserializes the selected SQLite projection instead of
   calling `build_catalog()`. The existing research GET/H1 adapter is read-only under
   its own receipt/pointer contract, outside `CatalogReadSnapshot` and outside this
   market read barrier, and does not affect the market Catalog source/logical hash,
   snapshot/ETag, or active head.
6. **Rollback vs stale (B.5)**: `catalog rollback` is pointer-only and allowed only
   when the target shares scope, is reader-supported, has
   `source_fingerprint == current authoritative BTC fact set`, and is a committed
   generation reachable from the pointer head — a projection/policy rollback, not a
   Formal truth rollback. A stale/different-scope/unsupported/uncommitted target is
   the single primary code `CATALOG_ROLLBACK_REJECTED` (it does not also return
   `CATALOG_STALE`); no pinned mode silently serves a stale head. The reader
   compatibility registry is explicit; the acceptance fixture may register a second
   supported projection policy through the same registry (no bypass) to exercise a
   real same-fact-set rollback, while the normal writer emits only the current
   projection policy. Formal/source rollback goes only through `BtcRunStore`
   authoritative rollback, producing a new ledger fact before a new generation is
   built. CLI:
   `./trade observatory catalog rollback --to-generation <id> [--expected-current <id>] [--dry-run] --json`; no HTTP write endpoint.
7. **Asset/legacy fact policy (B.6)**: new manifest/pointer/publish/rollback audits
   carry `asset_id=crypto.BTC` and land under
   `audit/by-asset/crypto.BTC/{publish,rollback}/` (scope decidable before parse).
   Legacy per-run manifests adapt only when path run id == payload run id and BTC
   contract/provider schema is provable. Legacy global `audit/{publish,rollback}`
   accepts only parseable records with `event_type` in
   `{btc_canonical_publish, btc_canonical_rollback, btc_legacy_predecessor_rollback}`
   that reference a BTC-scoped run; other assets are excluded from the BTC
   fingerprint. Unparseable/unattributable legacy global authoritative files fail
   closed as migration blockers; unscoped authoritative writes are prohibited after
   cutover. A scoped malformed fact blocks only its own scope. The `release_events`
   ledger is modelled separately from the `active_release_head`; a rollback event
   activates `to_run_id` (legacy-to-none excepted).
8. **Fail-closed reconciliation (B.3/B.7)**: reconcile `btc_current.json`, active
   release receipt, manifest run/hash, and required artifacts within the same read
   transaction. After the snapshot freezes its refs, every participating external
   artifact (canonical, primary, shadow, reconciliation, revisions) MUST be opened
   and read once and the exact bytes used to build the response SHA-256 checked
   against the frozen ref outside the lock; any mismatch/missing participating
   artifact is `ARTIFACT_HASH_MISMATCH` and aborts the entire GET/SDK/diff/composite
   response (no partial 200/`null`/old fallback). An OHLCV tamper is caught by this
   external-artifact rule (OHLCV is not inside the Catalog SQLite); a tampered Catalog
   row (gate/finding/clock/artifact-ref/release target) is caught by the logical
   hash. Malformed authoritative manifests/audits are explicit invalid facts or block
   generation publication — never a silent `continue` that exposes an older run.

### Failure behavior

Reason codes and their HTTP/CLI mappings are frozen in `frozen_contracts.md`
(§"HTTP status mapping" and §"CLI exit-code mapping").

- missing/stale projection, or only-legacy pair: `CATALOG_STALE` / HTTP 503
- lock unavailable within read deadline: `CATALOG_LOCK_TIMEOUT` / HTTP 503
- generation chain corrupt
  (pointer/switch-receipt/manifest/SQLite/`catalog_meta`/logical hash):
  `CATALOG_CORRUPT` / HTTP 409
- malformed manifest or ledger: `MANIFEST_INVALID` / HTTP 409
- pointer disagreement: `CURRENT_POINTER_INVALID` / HTTP 409
- artifact mismatch: `ARTIFACT_HASH_MISMATCH` / HTTP 409
- publish CAS lost: `CATALOG_CAS_CONFLICT` / CLI exit 5 (write path only, no GET)
- rollback target not a supported projection: `CATALOG_ROLLBACK_REJECTED` / CLI
  exit 4 (write path only, no GET)
- no fallback to another run or a partial HTTP 200/`null` layer for integrity
  failures; only `CHANNEL_UNAVAILABLE`/`QUALITY_BLOCKED` business-availability codes
  may degrade a lens
- `--json` failures emit exactly one structured envelope
  (`reason_codes`/`evidence_refs`/`retryable` plus the unified `CatalogDiagnosis`
  fields) and never leak a traceback or absolute path to stdout

### Tests required

The frozen acceptance surface is `frozen_contracts.md` §B.8. Phase B implementation
must cover at least:

- full SQLite roundtrip (rebuild → install → read equals source facts)
- ordinary Catalog-row tamper (gate/finding/clock/artifact-ref/release target)
  detected via the logical content hash
- corrupt SQLite fails verify and read (`CATALOG_CORRUPT`)
- broken/orphaned switch receipt and pointer↔head-receipt disagreement fail closed;
  a crash-after-install-before-CAS orphan is diagnosed but never served
- multi-process concurrent CAS: cannot overwrite/mix generations; one committed
  switch, the loser gets `CATALOG_CAS_CONFLICT`; the same-candidate publisher gets a
  success no-op with no second receipt
- publish/rebuild/read barrier (lock order; reader sees one complete generation)
- crash failpoints across the fsync window leave no half-installed generation
- real supported-projection rollback of the SAME authoritative fact set via a real
  pointer switch (second projection registered through the reader registry), plus
  stale/uncommitted-target rejection (`CATALOG_ROLLBACK_REJECTED`)
- pointer/receipt/ledger/manifest/hash disagreement fails closed
- five classes of external-artifact tamper (canonical, primary, shadow,
  reconciliation, revisions — including an OHLCV tamper) each fail closed with
  `ARTIFACT_HASH_MISMATCH`
- malformed newest manifest/audit does not disappear and expose an older run as
  latest; unattributable legacy global audit is a fail-closed migration blocker
- ETH isolation: an unrelated ETH audit leaves the BTC fingerprint, active release,
  and ETag unchanged
- read-path test asserts zero `build_catalog()` calls and zero writes
- legacy-pair migration behavior (only-legacy pair ⇒ `CATALOG_STALE` +
  `legacy_catalog_requires_rebuild`, no in-read migration/delete)

> **Rollback-test wording (frozen)**: the real rollback test asserts a "supported
> projection rollback of the SAME authoritative fact set". It MUST NOT require
> switching back to an older Formal/source fact head and then remaining `ready`;
> that path is `CATALOG_ROLLBACK_REJECTED`.

### Focused validation

```bash
uv run --extra dev pytest \
  tests/test_btc_observatory_catalog.py \
  tests/test_btc_observatory_snapshot_resolver.py \
  tests/observatory/test_catalog_cli.py \
  tests/observatory/test_dual_read_compat.py -q

python -m compileall trade_py trade_web tests
```

### Commit

`fix(observatory): make catalog generations atomic and verifiable`

Stop for Codex review.

## 7. Phase C — Immutable snapshot replay and one PIT read kernel

### Goal

Make Web, Python SDK, composite, Date Evidence, Trust and Research resolve through
one frozen Catalog generation and one point-in-time implementation.

### Required architecture

1. Introduce one read owner, such as `ObservatoryReadKernel`, responsible for:
   Catalog generation freeze, selector validation, channel resolution, lifecycle
   visibility, clock validation, revision selection, artifact verification, context,
   rows and view fingerprints.
2. Delete/bypass no alternative resolution behavior. Web, SDK, composite, date,
   trust and research snapshot binding delegate to the same kernel.
3. Define a typed selector union so exact snapshot, exact run, exact release and
   channel selection cannot be ambiguously combined.
4. Introduce an immutable `SnapshotDescriptor` containing every normalized input to
   the frozen snapshot hash plus the concrete generation/run/release identities.
5. Return both `snapshot_id` and its replay descriptor/token. On replay, recompute
   the hash and reject descriptor mismatch. Do not use process-local registries and
   do not write a registry from GET/SDK reads.
6. Preserve compatibility for IDs that can be deterministically found in the
   current Catalog; an unknown standalone ID must return `SNAPSHOT_NOT_FOUND`, never
   a channel result.
7. If the descriptor/token shape requires an additive OpenSpec clarification,
   write it and stop for Codex approval before changing the public API.
8. Parse all timestamps into timezone-aware UTC datetimes before comparison.
9. A missing clock required by the chosen knowledge mode is unknown/unproven and
   excluded or returns `PIT_NOT_PROVEN`; it is never visible by default.
10. Publication, certification, findings, revision and research lifecycle facts are
    constrained by knowledge cut regardless of market knowledge mode.
11. `market_available` affects row availability only; it does not make later-created
    runs or later-published releases historically visible.
12. Composite independently applies the same PIT resolution to every layer.
13. Context semantic channel references use the request's frozen generation, cut,
    mode and policy rather than latest.
14. Implement `as_known` using a real revision ledger. If evidence is insufficient,
    return `PIT_NOT_PROVEN`; do not return current rows with an `as_known` label.
15. `latest_restated` must actually select the latest restated row versions and
    persistently carry `RESTATED_NOT_PIT`.

### Tests required

- unknown snapshot ID returns 404/reason code
- descriptor/hash mismatch returns invalid selector or integrity error
- a snapshot remains identical after a later run/publish is added
- Formal snapshot ID replay cannot resolve Observed
- Web and SDK return identical context and rows for the same descriptor
- composite and single-layer rows agree for the same layer snapshot
- 2020 cut cannot see a 2026 run or release
- later findings, watermarks and semantic channel refs are absent at historical T
- missing `available_at`/`fetched_at` is not visible
- later revision does not change `as_known` at earlier T
- exact run/release is still subject to visibility rules
- same frozen input yields identical snapshot/view fingerprint and ETag

### Focused validation

```bash
uv run --extra dev pytest \
  tests/observatory/test_pit_resolver.py \
  tests/observatory/test_sdk_readonly.py \
  tests/test_btc_observatory_snapshot_resolver.py \
  tests/test_btc_observatory_api.py -q

python -m compileall trade_py trade_web tests
```

### Commit

`fix(observatory): unify immutable snapshot and PIT resolution`

Stop for Codex review.

## 8. Phase D — Per-date evidence, quality, revision and metrics

### Goal

Make the visualization expose data uncertainty instead of hiding it.

### Required implementation

1. Build a per-date fact projection from canonical, reconciliation, revisions,
   gates/findings and channel membership.
2. The date universe includes present canonical dates plus missing/quarantined/
   revised dates evidenced by reconciliation and revision artifacts.
3. A missing/quarantined date is returned with null OHLCV and an explicit
   `availability_state`; it is not interpolated.
4. D3 `status=pass` with warning rows must still create per-date findings and
   excluded markers.
5. Membership means semantic membership (`formal`, `evaluated_candidate`,
   `observed`), not run lifecycle (`staged`, `published`). One run may belong to
   multiple semantic channels.
6. Derive `revision_state` from actual revision evidence.
7. Date Evidence returns provider, basis, all four clocks, reconciliation,
   revision chain, findings, artifact hashes and lineage. Evidence read/hash errors
   fail closed.
8. Compute versioned Market Summary metrics in Python from the selected immutable
   snapshot: latest close, 1D/7D/30D returns, window drawdown and RV20 percentile.
9. Metrics exclude unavailable/quarantined values and include metric version and
   window definition. The browser only formats returned decimal strings.
10. Compatibility state compares against real current contract/code/replay evidence;
    when evidence is absent it is `unknown`, not tautologically compatible.

### Tests required

- frozen D3 pass-with-five-warnings fixture yields five excluded markers
- missing dates appear as non-present rows with null values
- quarantine toggle never turns quarantined values into formal metrics silently
- revision states match revisions artifact
- semantic membership is correct when one run is both Formal and Observed
- metrics match independent Python golden calculations
- Date Evidence detects reconciliation/revisions tampering
- real BTC read-only probe reports the five warnings for
  `cdbbb5c608ba22b1c4aa06b0`

### Focused validation

```bash
uv run --extra dev pytest \
  tests/test_btc_observatory_snapshot_resolver.py \
  tests/test_btc_observatory_api.py \
  tests/observatory/test_state_mapping.py \
  tests/observatory/test_pit_resolver.py -q

npm --prefix trade_web/frontend run test:unit
```

### Commit

`fix(observatory): project honest date quality and formal metrics`

Stop for Codex review.

## 9. Phase E — Real H1 Research workflow

### Goal

Make `run`, `import` and `promote` perform their documented workflows while keeping
the existing H1 lifecycle and pointer as the single authority.

### Required implementation

1. Reconcile the adapter schema with actual H1 output fields; do not invent CI,
   sample or snapshot fields that the authority does not persist.
2. Add snapshot descriptor/id and knowledge mode/cut to additive immutable H1
   manifest/receipt metadata where required for reproducibility.
3. `run --dry-run` resolves and validates but writes nothing.
4. `run --commit`:
   - resolves one immutable PIT-eligible snapshot through the shared kernel
   - revalidates all artifacts and hypothesis version
   - executes the versioned H1 kernel in an isolated temporary directory
   - validates outputs before publication
   - calls the existing `persist_crypto_validation_outputs()` authority
   - lets existing lifecycle logic alone decide `activate_run`
   - leaves no registered half state on failure
5. `import` validates descriptor/hash/code/environment/hypothesis identity and writes
   an append-only exploratory receipt. Same ID cannot be overwritten with a new
   timestamp or different content.
6. `promote` performs a real clean-environment rerun from the imported contract. It
   appends a promotion receipt only after success and never rewrites the source run.
7. Research GET/SDK/Web paths remain read-only.
8. The Research UI renders no fixed placeholder forest plot. Plot only evidence from
   a bound ResearchRun artifact; otherwise show an explicit empty/blocked state.

### Tests required

- dry-run zero-write/zero-pointer-change
- committed run invokes kernel and authority exactly once
- committed run persists bound snapshot identity and returns stored metrics
- failure at each temp/output/persistence step leaves no partial registered run
- inactive result does not move pointer
- active result pointer is moved only by existing authority
- duplicate import is idempotent; conflicting import is rejected
- promotion proves clean rerun occurred before receipt
- Research UI empty state contains no fabricated intervals

### Focused validation

```bash
uv run --extra dev pytest \
  tests/test_btc_observatory_research.py \
  tests/test_crypto_research_validation.py \
  tests/test_research_warehouse.py -q

python -m compileall trade_py trade_web tests
npm --prefix trade_web/frontend run test:unit
```

### Commit

`fix(observatory): execute reproducible H1 research workflows`

Stop for Codex review.

## 10. Phase F — Web pinning, ETag, performance and telemetry

### Goal

Make one rendered page internally consistent and make unchanged/ranged requests
cheap enough for normal operation.

### Required implementation

1. Bootstrap an Observatory page from one frozen Catalog generation/context.
2. Pass concrete snapshot descriptors/IDs to series, Date Evidence, Trust and
   Research requests. A publish between requests cannot mix generations on one page.
3. Return a cheap view fingerprint from generation + selector + relevant fact hashes
   before reading parquet or serializing a large payload.
4. Handle `If-None-Match` before expensive work. Define consistent `Cache-Control`
   and `Vary` behavior.
5. Frontend caches `{URL, ETag, payload}`, sends conditional requests and reuses the
   prior payload on 304. Do not use one fixed localStorage key across selectors.
6. Default series range to 90D and enforce a documented maximum span/response size.
7. Frontend Range sends actual `from/to`; server filters early with column/date
   projection rather than full-frame `iterrows()` filtering.
8. `All` uses a bounded summary/downsample contract while Date Evidence remains
   exact.
9. Avoid unconditional duplicate Context/Composite/Formal requests on every lens.
10. Add structured telemetry for request latency/status/reason code, generation,
    Catalog age/staleness, integrity failures, suppressed layers, 304 hit ratio and
    channel watermark lag.
11. Route registration/import errors are logged and reflected in capability status;
    never silently swallowed.

### Performance acceptance

Use the frozen envelope in docs/26 without reducing scale or relaxing bounds:

- 10k manifests Catalog rebuild/update/verify
- warm context p95 <= 100ms on the recorded test machine
- 730-day three-layer cold composite <= 1.5s
- conditional 304 path performs zero parquet opens and avoids payload construction
- record response bytes, peak RSS, file-open count and timing distribution
- run diff is actually measured
- frontend interaction latency is measured against the real backend fixture

If the machine cannot satisfy an absolute bound, report the measured evidence and
stop for a contract decision. Do not silently change 10k to 2k or 1.5s to 10s.

### Tests required

- backend spy proves 304 skips parquet/payload work
- frontend sends and handles ETag/304 correctly
- cache is selector-specific
- 30D/90D/1Y/All produce bounded, correct requests
- one page remains generation-consistent across a simulated publish
- lens switching does not issue unnecessary full-series requests
- telemetry emits stable reason codes without leaking local filesystem paths
- 10k performance report includes all required measurements

### Validation

```bash
uv run --extra dev pytest tests/observatory/test_perf_smoke.py -q -s
uv run --extra dev pytest tests/test_btc_observatory_api.py -q

npm --prefix trade_web/frontend run build
npm --prefix trade_web/frontend run test:unit
npm --prefix trade_web/frontend run test:e2e
npm --prefix trade_web/frontend run test:a11y
```

### Commit

`fix(observatory): pin web views and enforce cache performance`

Stop for Codex review.

## 11. Phase G — Real-stack acceptance and closeout

### Required integration suite

Keep mocked component/E2E tests, then add a mandatory real-stack smoke that starts a
temporary FastAPI backend with a temporary Catalog and the real frontend build.

It must cover:

- feature disabled: nav hidden and routes/capability consistent
- feature enabled + missing/stale Catalog: explicit unavailable state/503
- ready Catalog: Overview renders real backend payload
- conditional request: 200 then 304
- immutable URL replay after a later publish
- artifact corruption: 409 and no stale/partial chart
- historical replay: no future rows/findings/channel references
- Date Evidence warning/revision markers
- Research empty state and one persisted H1 fixture
- Catalog forward switch and real rollback switch

### Full validation

```bash
git status -sb
git diff --check

uv run --extra dev pytest -q
python -m compileall trade_py trade_web tests

npm --prefix trade_web/frontend run build
npm --prefix trade_web/frontend run test:unit
npm --prefix trade_web/frontend run test:e2e
npm --prefix trade_web/frontend run test:a11y

openspec validate btc-observatory-research-lab-v1 --strict

./trade observatory catalog rebuild \
  --data-root /data00/home/guohuanwei.cztj/git_files/trade/data \
  --dry-run --json
```

The final real-data command is read-only. Do not run a committed rebuild against the
real data root without separate user authorization.

### Required final review

Before merge, run the repository `review-this` six-role consensus review in a fresh
review worktree. All CRIT/HIGH findings must be fixed or explicitly blocked with an
approved residual-risk decision. Re-run the specific real-data probes listed in
Section 2.

### Final commit/merge policy

1. Feature branch commits remain one validated logical unit per phase.
2. Push after 3-5 commits according to `AGENTS.md`.
3. Do not merge while any RA task is unchecked except explicitly deferred DF tasks.
4. Merge back with `git merge --squash` only after final acceptance.
5. Remove the worktree/branch only after the squash commit is validated and pushed.

## 12. Codex review checklist for every phase

Codex will independently check:

- Diff scope matches the current phase.
- No frozen contract was weakened to fit implementation.
- New tests fail against baseline behavior and pass after the fix.
- Error handling is fail-closed for integrity and honestly unknown for missing
  evidence.
- Tests do not write real data or make provider network calls.
- Web/SDK/Jupyter use the same concrete snapshot semantics.
- Backward compatibility is explicit for CLI, API, SQLite layout and H1 receipts.
- Focused tests, compile/typecheck and relevant smoke probes pass.
- Commit contains only intentional files and documents validation results.

Possible review outcomes:

- `ACCEPTED`: phase may be committed/next phase may begin.
- `CHANGES_REQUESTED`: agent fixes only listed findings and resubmits.
- `DESIGN_BLOCKED`: agent stops coding until OpenSpec decision is approved.

## 13. Agent handoff report template

After each phase, return exactly:

```text
Phase:
Commit (or uncommitted if review requested before commit):

Changed files:
- ...

Behavior implemented:
- ...

Tests added/updated:
- test name: contract proven

Validation commands and results:
- command: result

Compatibility/data-safety notes:
- ...

Known residual risks:
- ...

OpenSpec tasks marked complete:
- ...
```

Do not report a phase complete using only a file list or a green test count. State
the user-visible/data-semantic behavior that was proven.
