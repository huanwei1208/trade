# Frozen Contracts (WP0)

Status: FROZEN in M0. WP1-WP9 consume these verbatim.

## Reason codes (frozen enum)

Snapshot/error reason codes:

- `SNAPSHOT_NOT_FOUND`
- `CURRENT_POINTER_INVALID`
- `ARTIFACT_HASH_MISMATCH`
- `MANIFEST_INVALID`
- `CHANNEL_UNAVAILABLE`
- `PIT_NOT_PROVEN`
- `DATASET_STALE`
- `QUALITY_BLOCKED`
- `RESEARCH_NOT_ELIGIBLE`
- `INVALID_SNAPSHOT_SELECTOR`
- `COMPOSITE_NOT_DATASET`
- `CATALOG_STALE`
- `RESTATED_NOT_PIT`
- `LEGACY_TIME_UNPROVEN`

Phase B generation integrity codes (frozen 2026-07-20, additive; the codes above
are unchanged):

- `CATALOG_CORRUPT` — a committed generation's pointer/switch-receipt/manifest/SQLite
  /`catalog_meta`/logical-hash chain does not reconcile (missing, wrong-type,
  integrity-check failure, identity disagreement). Fail closed; never a stale
  success.
- `CATALOG_CAS_CONFLICT` — a publish/rollback pointer compare-and-swap observed a
  different expected-previous pointer SHA than the one it froze, or a different
  target; a concurrent committer won.
- `CATALOG_ROLLBACK_REJECTED` — the single primary code for a pointer-only rollback
  target that is not a committed, reachable, reader-supported projection of the
  current authoritative BTC fact set (stale `source_fingerprint`, different scope,
  unsupported version, or uncommitted/unreachable target). It is not a Formal/source
  rollback and does NOT also return `CATALOG_STALE`.
- `CATALOG_LOCK_TIMEOUT` — the shared/exclusive BTC assurance lock could not be
  acquired within the operation/read deadline.

Every error response returns `reason_codes` (list), `evidence_refs` (list), and
`retryable` (bool). Empty arrays never impersonate success.

## HTTP status mapping (frozen)

| Situation | HTTP | Contract |
| --- | --- | --- |
| invalid params/identity | 400 | stable reason_code, no local path leak |
| snapshot/run/release missing | 404 | `SNAPSHOT_NOT_FOUND` |
| PIT unprovable | 422 | `PIT_NOT_PROVEN` + coverage interval |
| quality/research policy blocked | 422 | blocker + evidence + retryable |
| pointer/hash/manifest integrity error | 409 | fail closed, no stale-success |
| generation integrity corrupt | 409 | `CATALOG_CORRUPT`, fail closed, no partial 200 |
| catalog stale / rebuilding | 503 | `CATALOG_STALE` + retry_after |
| lock unavailable within read deadline | 503 | `CATALOG_LOCK_TIMEOUT` + retry_after |
| unchanged | 304 | consistent ETag + view fingerprint |

Phase B generation-integrity HTTP rule (frozen 2026-07-20): `CATALOG_CORRUPT`,
`CURRENT_POINTER_INVALID`, `MANIFEST_INVALID`, and `ARTIFACT_HASH_MISMATCH` are
integrity failures that MUST surface as 409 on every read; `CATALOG_STALE` and
`CATALOG_LOCK_TIMEOUT` are retryable availability failures that MUST surface as
503 with `retry_after`. Only business-availability codes (`CHANNEL_UNAVAILABLE`,
`QUALITY_BLOCKED`) may degrade a lens; a pointer/manifest/artifact/generation
integrity error MUST NOT be swallowed into a partial 200, a `null` layer, or an
older-run fallback. `CATALOG_CAS_CONFLICT` and `CATALOG_ROLLBACK_REJECTED` are
write/operation codes and have no read (GET) surface — GET/SDK/Web reads never
publish or roll back (see CLI mapping below).

## CLI exit-code mapping (frozen)

The `./trade observatory catalog` and `./trade research btc` commands map outcomes
to stable process exit codes so deployment gates can branch without parsing text.
A `--json` invocation MUST emit exactly one structured envelope (see Operation
result envelope below) on stdout and MUST NOT leak a Python traceback to stdout.

| Exit code | Meaning | Example |
| --- | --- | --- |
| 0 | success / informational status (non-strict) | `status` (human), successful `rebuild`/`rollback` |
| 2 | usage error (bad flags, conflicting selectors) | unknown flag, `--to-generation` missing |
| 3 | strict gate: enabled but not ready | `status --strict` on missing/stale/corrupt catalog |
| 4 | integrity / non-retryable operation failure | `CATALOG_CORRUPT`, `MANIFEST_INVALID`, `ARTIFACT_HASH_MISMATCH`, `CURRENT_POINTER_INVALID`, `CATALOG_ROLLBACK_REJECTED` |
| 5 | retryable concurrency / lock failure | `CATALOG_CAS_CONFLICT`, `CATALOG_LOCK_TIMEOUT`, `CATALOG_STALE` |

## Serialization (frozen)

- Times: UTC RFC 3339 with `Z`. Market dates: `YYYY-MM-DD`.
- Prices/volumes/ratios serialized as JSON strings (decimal-preserving) to avoid
  float rounding divergence before hashing.
- Nullable fields are `null`, never `0` / empty string / empty array.
- List endpoints: fixed sort key + `run_id`/id tie-break, cursor pagination stable
  within one Catalog fingerprint.

## Selector predicates and order keys (frozen)

Lifecycle channel: `observed | evaluated_candidate | formal | exact run/release`.
Knowledge cut: `latest | knowledge_as_of=T`. Revision policy:
`as_known | latest_restated`.

| Reference | Order key (descending) |
| --- | --- |
| Latest Observed | `(market_watermark, effective_as_of, capture_completed_at, run_id)` |
| Evaluated Candidate | `(assurance_completed_at, staged_at, run_id)` |
| Latest Staged | `(staged_at, manifest.created_at, run_id)` |
| Formal Baseline | publication/rollback ledger active release (not "latest ready") |
| Legacy null tie-break | business key, then `created_at`, then `run_id`; never mtime |

## Snapshot identity (frozen)

`snapshot_id = sha256(normalized_serialization(` asset contract id/version,
resolved run/release ids, artifact SHA-256s in stable order, effective knowledge
cut, knowledge_mode, revision_policy, quarantine/inclusion policy, resolver policy
version `))`.

Excluded from `snapshot_id`: `requested_at`, `rendered_at`, page ranges, chart
metrics, sort order.

`view_fingerprint = sha256(` snapshot_id, participating operational/quality fact
fingerprints, date range, metric versions, lens, pagination/sort, serialization
version `)`.

`latest` freezes at request start to the asset-scoped relevant fact
sequence/effective knowledge cut and concrete run/release ids.

## State axes (frozen; `mapping_policy_version = obs-map-v1`)

| Axis | States |
| --- | --- |
| acquisition_state | not_attempted / running / succeeded / partial / empty / failed / abandoned / unknown |
| quality_state | not_evaluated / assured / degraded / insufficient / invalid / unknown |
| lifecycle_state | staged / published / superseded / rolled_back / unknown |
| research_state | exploratory / eligible / candidate / monitoring / validated / rejected / blocked / unknown |
| freshness_state | fresh / stale / unknown |
| compatibility_state | compatible / contract_stale / replay_mismatch / unknown |

Manifest mapping (value preserved + mapping_policy_version):

| manifest fact | quality_state | limit |
| --- | --- | --- |
| assurance not run | not_evaluated | never infer ready |
| data_readiness=ready | assured | still needs release receipt to be Formal |
| data_readiness=degraded | degraded | observable, not auto-publishable |
| data_readiness=insufficient_data | insufficient | not failure/zero-sample |
| data_readiness=invalid | invalid | evidence kept, not canonical layer |
| manifest missing/unknown version | unknown | fail closed |

## Purpose fitness (frozen initial policy)

| Purpose | Initial requirement |
| --- | --- |
| manual_observation | at least a normalized final bar; all warnings continuously visible |
| exploratory_research | fixed immutable run; explicit quarantine/provisional state |
| formal_system_consumption | only Published Current / Formal Baseline |
| strict_research | fixed formal snapshot + point-in-time + sample + research gates |
| automated_decision | independent authorization; not auto-enabled by data existence or validated research |

Response: `{allowed, status, reason_codes, evidence_refs}`. Unidirectional; never
writes back to data_readiness/release/research lifecycle.

## Frontend test runner (frozen)

- Unit: **Vitest** (`npm run test:unit`)
- E2E: **Playwright** (`npm run test:e2e`)
- Accessibility: **axe** (`npm run test:a11y`), independently executable even if
  merged into E2E.

CI and local use the same commands. WP4 lands these three scripts in
`trade_web/frontend/package.json`.

## Phase B generation contracts (frozen 2026-07-20)

Status: FROZEN. These clauses harden the Catalog into an immutable, scoped,
CAS-published, fail-closed read projection with a provable committed history. They
resolve the 2026-07-20 consensus review (score 3.3/10) P0 findings F6/F7/F8/F9/F17
and the 2026-07-20 B0 contract audit. RA.2 and RA.3 remain UNCHECKED; this is a
contract/design freeze only — no Python/TS/test implementation lands in Batch B0.
Where a clause tightens an earlier WP1 note (single `catalog.sqlite`, single
`generation.json`, `obs-catalog-v1`), the earlier note is superseded per the
equivalence mapping in `design.md`.

Phase B version constants (frozen initial values):

| Constant | Initial value |
| --- | --- |
| `scope_policy_version` | `obs-scope-v1` |
| `projection_policy_version` | `obs-projection-v1` (current) |
| `pointer_schema_version` | `obs-pointer-v1` |
| `manifest_schema_version` | `obs-genmanifest-v2` |
| `switch_receipt_schema_version` | `obs-switch-v1` |
| `catalog_schema_version` | `obs-catalog-v2` |

Version-vs-identity rule (frozen): `generation_id` is derived ONLY from the full
`CatalogScope` (therefore `source_contract_version` + `scope_policy_version`),
`catalog_schema_version`, `manifest_schema_version`, `projection_policy_version`,
`source_fingerprint`, and the full `logical_content_hash` (see B.3). Bumping any of
those ⇒ a new `generation_id`. `pointer_schema_version` and
`switch_receipt_schema_version` are compatibility / commit-envelope versions and do
NOT by themselves change `generation_id`. `catalog_schema_version = obs-catalog-v2`
because the earlier mutable WP1 SQLite already used `obs-catalog-v1`; the new
full lossless codec MUST use `obs-catalog-v2` so there is no semantic collision on
the same version string. `manifest_schema_version = obs-genmanifest-v2` and
`switch_receipt_schema_version = obs-switch-v1` are the immutable commit-envelope
schemas introduced by this freeze.

### B.1 Catalog scope (frozen)

- Every generation is bound to a `CatalogScope` tuple:
  `(asset_id, data_family, source_contract_version, scope_policy_version)`.
- The ONLY scope implemented in Phase B is
  `(crypto.BTC, market_assurance, btc-data-v1, obs-scope-v1)`. `btc-data-v1`
  accepts the legacy contract version as a compatible alias; no other
  `source_contract_version` is served.
- `data_family = market_assurance` is the BTC Formal market ledger/head family.
  `news`, `sentiment`, and `research` are DIFFERENT `data_family` values. They
  MUST NOT enter the BTC Formal market ledger, active head, quality axes, `ETag`,
  `snapshot_id`, `view_fingerprint`, or `source_fingerprint`, and Phase B does not
  implement their business.
- `CatalogScope` is carried by the generation manifest, the SQLite primary keys,
  the `source_fingerprint`, and the relevant fact set. A fact whose scope does not
  match the generation scope is out-of-scope and never contributes to it.

### B.2 Layout and migration (frozen)

New on-disk layout under `<data_root>/market/crypto/observatory/`:

| Path | Role | Mutability |
| --- | --- | --- |
| `catalog-current.json` | current-generation typed pointer | the ONLY mutable file; CAS-switched |
| `commits/catalog-switch-<operation_id>.json` | immutable switch receipt (publish/rollback) | install-once immutable; hash-linked chain |
| `generations/catalog-<generation_id>.sqlite` | materialized projection DB | immutable once installed |
| `generations/catalog-<generation_id>.manifest.json` | generation manifest | immutable once installed |
| `.candidate-<uuid>/` (hidden temp) | in-progress candidate build | same filesystem; renamed/cleaned, never served |

- `catalog-current.json` is the ONLY mutable file. Every other artifact —
  generations and switch receipts — is install-once immutable.
- Each committed pointer switch (publish or rollback) writes ONE immutable
  `commits/catalog-switch-<operation_id>.json` receipt. Receipts are hash-linked
  into a chain (see B.3); the pointer pins the head receipt's SHA-256. A generation
  is "committed" ONLY if it appears as a `to_generation_id` in the receipt chain
  reachable from the current pointer head.

- The candidate DB + manifest are materialized in a hidden temp directory ON THE
  SAME FILESYSTEM as `generations/`, so the final install is an atomic rename, not
  a cross-device copy.
- Immutable artifacts are install-once: a publisher MUST NOT overwrite an existing
  `catalog-<generation_id>.sqlite`, `.manifest.json`, or
  `commits/catalog-switch-<operation_id>.json`. Recomputing the same
  `generation_id` is an idempotent no-op install (see B.4), never an overwrite.
- Orphans (frozen): a generation or switch-receipt artifact that is present on disk
  but NOT reachable from the current pointer head via the receipt chain is an
  orphan (e.g. a crash after installing artifacts but before the pointer CAS). An
  orphan is DIAGNOSED only — never served, never auto-deleted. This closes the
  crash-after-install-before-CAS ambiguity: an installed-but-uncommitted generation
  has no committed switch receipt reachable from the head and is therefore not
  "committed" and not servable.
- The legacy single-file pair `catalog.sqlite` + `generation.json` is retained
  read-only as a legacy pair. New read code MUST NOT overwrite, delete, or migrate
  it, and MUST NOT migrate inside a GET/SDK read. When ONLY the legacy pair exists
  (no `catalog-current.json`), the read diagnosis is `CATALOG_STALE` with a stable
  `legacy_catalog_requires_rebuild` marker; the operator rebuilds into the new
  layout out of band.
- The old→new design equivalence/supersession mapping is recorded in `design.md`
  (§ "Phase B immutable-generation layout").

### B.3 Identity, pointer, receipts, and integrity (frozen)

- `generation_id` is a normalized, deterministic derivation over: the full
  `CatalogScope` (asset + scope tuple, therefore `source_contract_version` +
  `scope_policy_version`), `catalog_schema_version`, `manifest_schema_version`,
  `projection_policy_version`, `source_fingerprint`, and the full
  `logical_content_hash`. Same inputs ⇒ same `generation_id` (idempotent rebuild);
  any change to one of those inputs ⇒ a new `generation_id`.
  `pointer_schema_version` and `switch_receipt_schema_version` are
  compatibility / commit-envelope versions and do NOT by themselves change
  `generation_id`.
- Typed pointer (frozen). `catalog-current.json` is the ONLY mutable file and MUST
  carry at least: `pointer_schema_version`, `asset_id`, `catalog_scope`,
  `catalog_schema_version`, `manifest_schema_version`, `projection_policy_version`,
  `source_fingerprint`, `current_generation_id`, `current_manifest_ref`,
  `current_manifest_sha256`, `previous_generation_id`, `head_commit_ref`,
  `head_commit_sha256`, `switch_sequence`, and `switched_at`. The pointer pins the
  head switch receipt via `head_commit_ref` + `head_commit_sha256`.
- Immutable switch receipt (frozen). Each committed pointer switch writes ONE
  install-once `commits/catalog-switch-<operation_id>.json` whose bytes are
  canonical JSON and MUST carry at least: `switch_receipt_schema_version`,
  `operation_id`, `operation` (`publish` | `rollback`), `asset_id`,
  `catalog_scope`, `sequence`, `previous_commit_ref`, `previous_commit_sha256`,
  `from_generation_id`, `to_generation_id`, `to_manifest_ref`,
  `to_manifest_sha256`, `source_fingerprint`, `expected_pointer_sha256` (an
  explicit `null` sentinel when the expected prior pointer was absent), and
  `occurred_at`.
- Committed history (frozen). Receipts form a hash-linked chain: each receipt names
  its `previous_commit_ref` + `previous_commit_sha256`, and the pointer pins the
  head receipt's SHA-256. A generation is "committed" ONLY if it appears as a
  `to_generation_id` in the receipt chain reachable from the current pointer head.
  A rollback target MUST be a reachable committed generation. Installed
  generation/receipt artifacts that are NOT reachable from the pointer head are
  orphans: diagnosed only, never served and never deleted. This closes the
  crash-after-install-before-CAS ambiguity.
- The immutable generation manifest MUST carry at least: `asset_id`, full
  `CatalogScope`, `pointer_schema_version`, `manifest_schema_version`,
  `catalog_schema_version`, `projection_policy_version`, `generation_id`,
  `source_fingerprint`, `logical_content_hash`, the SQLite file SHA-256,
  the SQLite DB filename, the fact count, and the fact-set hash.
- The frozen verification chain, applied whole on every read (B.4):
  `catalog-current.json` (typed pointer) → head switch receipt / link consistency
  → immutable generation manifest → SQLite file SHA-256 → SQLite `catalog_meta`
  identity → deserialized canonical `logical_content_hash`. Any break in this chain
  is `CATALOG_CORRUPT` (409 / CLI exit 4). No link may be skipped. A normal GET
  need only verify the pointer's head receipt (pointer ↔ head receipt link
  consistency), NOT scan the full receipt history; only rollback/history
  diagnostics traverse the whole chain.
- `logical_content_hash` covers EVERY field the resolver needs, canonicalized in a
  stable order: runs; contracts; the four clocks + provenance; gates; findings;
  artifact refs; the release-event ledger (`release_events`) and the active release
  head (`active_release_head`) as SEPARATE elements; the revision index
  (`revisions_index`); the authoritative source `btc_current.json` snapshot; and
  the relevant fact set. Here "current pointer"/"source snapshot" means the
  AUTHORITATIVE source `btc_current.json` snapshot, NEVER `catalog-current.json`
  (that self-reference is prohibited so a pointer-only rollback does not change the
  logical hash). No OHLCV payload is stored inside the Catalog SQLite; OHLCV lives
  in referenced external artifacts (governed by the external-artifact integrity
  rule in B.7). Hashing only a subset of these Catalog fields is prohibited — a
  tampered ordinary Catalog row (e.g. a single gate result, finding, clock,
  artifact ref, or release target) MUST change the hash and fail the read closed.

### B.4 Durable publish, CAS, and locks (frozen)

- The Catalog reuses and PUBLICLY exposes the SAME lock owner as BTC assurance:
  `BtcRunStore` at `trade_py/data/market/crypto/store.py`, lockfile
  `<crypto_root>/.btc-assurance.lock`, public `shared_lock()`, exclusive owner.
  A ready Catalog with no lockfile is a fail-closed error; a GET MUST NOT create
  the lockfile.
- Write protocol (publish/rebuild/update), frozen durable ordering:
  1. Under a **shared** lock, freeze both a scoped `SourceSnapshot` and the
     expected Catalog pointer (its exact SHA-256, or the absent sentinel) from ONE
     batch of raw bytes.
  2. **Outside the lock**: project and materialize the candidate SQLite; commit and
     close its transaction, then `fsync` the candidate DB; write the canonical
     generation manifest, `flush`+`fsync` it; `fsync` the candidate directory. A
     shared→exclusive upgrade is PROHIBITED (release shared, then acquire
     exclusive).
  3. Under an **exclusive** lock, recheck the EXACT live source fingerprint and the
     EXACT expected pointer SHA-256 (or absent sentinel) that were frozen in step 1.
  4. Install the immutable DB and manifest with no-overwrite atomic renames; if an
     artifact with the same `generation_id` already exists, verify byte/hash
     identity (idempotent no-op) rather than overwriting; `fsync` `generations/`
     after BOTH names are durable.
  5. Write the immutable switch receipt to a temp file, `flush`+`fsync` it, then
     no-overwrite atomic-rename it into `commits/`; `fsync` `commits/`.
  6. Write the pointer to a temp file, `flush`+`fsync` it, and as the LAST step
     atomically replace `catalog-current.json`; `fsync` the `observatory/` parent
     directory.
  A crash BEFORE the pointer replacement (step 6) leaves the OLD pointer valid and
  the new generation/receipt artifacts orphaned; a crash AFTER it leaves the
  complete new chain (pointer → head receipt → generation) valid. Candidate-temp
  cleanup is allowed; GC of committed or orphaned generation/receipt artifacts is
  NOT.
- CAS result (frozen). The exclusive-lock CAS freezes and compares the EXACT prior
  pointer SHA-256 (or the absent sentinel), not only the `generation_id`:
  - If the exclusive recheck observes that `current_generation_id` already equals
    the fully verified candidate AND the source fingerprint and scope match, the
    operation returns a success **no-op** with `changed=false` / `committed=false`
    and creates NO second committed switch receipt.
  - Only when the observed current pointer points to a DIFFERENT target (a
    different `to_generation_id`/pointer SHA than the one it froze) or the source
    fingerprint changed is the result a stable `CATALOG_CAS_CONFLICT` (CLI exit 5),
    never a silent overwrite.
  - Two writers computing the SAME candidate `generation_id` may each report an
    idempotent no-op install of the artifacts, but only ONE committed pointer
    switch (and thus one new receipt) occurs; the other observes the no-op success
    above (if its expected-prior still matches) or `CATALOG_CAS_CONFLICT`.
- Read barrier (frozen): a reader takes a strict **shared** lock, freezes ONE typed
  pointer once, verifies pointer ↔ head switch receipt link consistency, opens and
  verifies ONE immutable generation, deserializes ONE `CatalogReadSnapshot`, and
  reconciles BTC `current`/ledger/manifest identity. Resolver, query, diff, and SDK
  all reuse that one snapshot. A normal GET verifies only the head receipt, not the
  full receipt history. The read path does ZERO `build_catalog()` and ZERO writes.
  The lock covers only the freeze/open/verify critical section; parquet/JSON
  response bytes are produced OUTSIDE the lock, on the already-verified immutable
  refs. The existing research GET/H1 adapter is read-only under its OWN
  receipt/pointer contract, OUTSIDE `CatalogReadSnapshot`, and is not part of this
  single-market-generation read barrier (see B.6).
- Retention (frozen): Phase B retains ALL committed generations. There is no
  destructive GC. An orphan generation file (present on disk but not referenced by
  the pointer chain) is DIAGNOSED only — never auto-served and never auto-deleted.

### B.5 Rollback vs stale (frozen)

- A `catalog rollback` is **pointer-only** and is allowed ONLY when the target
  generation: (a) has the SAME `CatalogScope`, (b) is reader-supported — its
  `catalog_schema_version`, `manifest_schema_version`, and
  `projection_policy_version` are in the explicit reader compatibility registry —
  (c) has `target.source_fingerprint == the current authoritative BTC fact set`,
  AND (d) is a committed generation reachable from the current pointer head via the
  receipt chain. It is a projection/policy rollback, NOT a Formal truth rollback.
- The reader compatibility registry is explicit. The normal writer emits ONLY the
  current projection policy (`obs-projection-v1`); the acceptance fixture MAY
  register a SECOND supported projection policy through the SAME registry (no
  bypass) so a real same-fact-set pointer rollback between two supported
  projections of ONE authoritative fact set can be exercised.
- A rollback target that is stale (different `source_fingerprint`), a different
  scope, unsupported by the reader registry, or not a committed/reachable
  generation MUST be rejected with the single primary reason code
  `CATALOG_ROLLBACK_REJECTED` (CLI exit 4). It MUST NOT also return
  `CATALOG_STALE`. There is NO "pinned" mode that silently serves a stale fact
  head.
- Formal/source rollback is a SEPARATE operation that goes only through
  `BtcRunStore` authoritative rollback. It produces a new ledger fact; a new
  Catalog generation is then built on top of that new authoritative fact set.
- CLI contract (frozen; no HTTP write endpoint exists):
  `./trade observatory catalog rollback --to-generation <id> [--expected-current <id>] [--dry-run] --json`.

### B.6 Asset and legacy-fact policy (frozen)

- Every new BTC generation manifest, `catalog-current.json` pointer, publish audit,
  and rollback audit MUST carry `asset_id = crypto.BTC`.
- New audits are written into a scope-decidable-before-parse, asset-scoped
  namespace. Frozen path:
  `<crypto_root>/audit/by-asset/crypto.BTC/{publish,rollback}/`. The `crypto.BTC`
  path segment makes the asset scope decidable from the path alone, before parsing
  the file body.
- Legacy per-run adaptation: a legacy `runs/btc/<run_id>/manifest.json` is adapted
  ONLY when the on-path `run_id` equals the payload `run_id` AND the BTC
  contract/provider schema is provable from the payload. Otherwise it is an
  explicit invalid fact.
- Legacy GLOBAL audit adaptation (`audit/publish/*.json`, `audit/rollback/*.json`,
  unscoped): a legacy global authoritative file is accepted into the BTC scope ONLY
  when it is parseable, its `event_type` is in the whitelist
  `{btc_canonical_publish, btc_canonical_rollback, btc_legacy_predecessor_rollback}`,
  and it references a BTC-scoped run. Files that explicitly name another asset are
  excluded and never enter the BTC fingerprint. A legacy global authoritative file
  that is unparseable or unattributable is a FAIL-CLOSED migration blocker
  (`MANIFEST_INVALID` / `CATALOG_CORRUPT`), not a skipped `continue`. After cutover,
  writing a new UNSCOPED authoritative event is prohibited.
- Cross-asset isolation: a scoped malformed fact blocks only its own scope. An ETH
  (or any non-BTC) manifest/audit MUST NOT change the BTC `source_fingerprint`,
  active release, snapshot, or `ETag`.
- Release modelling: the release-event ledger (`release_events`) is modelled
  SEPARATELY from the active Formal head (`active_release_head`). A rollback event
  ACTIVATES `to_run_id` (it does not blank the active head); the sole exception is
  an explicit legacy→none rollback whose target is "no active head".
- Market v2 logical scope (frozen). The `obs-catalog-v2` market catalog is a full
  lossless projection of ONLY `crypto.BTC` / `market_assurance`. It MUST NOT contain
  `research_runs`. Its logical tables/sections are: `runs`, `contracts`, the four
  clocks + provenance, `gates`, `findings`, artifact refs, `release_events` and
  `active_release_head` (separate), `revisions_index`, the authoritative source
  `btc_current` snapshot, and the relevant fact set. No OHLCV payload is stored in
  the Catalog SQLite; OHLCV remains in referenced external artifacts.
- Research adapter isolation (frozen). The existing research GET / H1 adapter
  remains read-only under its OWN receipt/pointer contract, OUTSIDE
  `CatalogReadSnapshot`. It MUST NOT affect the market Catalog `source_fingerprint`,
  `logical_content_hash`, snapshot/`ETag`, or active head, and it is NOT part of the
  Phase B single-market-generation read barrier (B.4). The earlier general rule
  still holds: research reads do no writes and no network. No cross-scope join is
  implemented in Phase B.

### B.7 Operation result envelope and diagnosis fields (frozen)

- A `--json` failure MUST print exactly ONE structured envelope on stdout with at
  least `reason_codes` (list), `evidence_refs` (list), and `retryable` (bool). No
  Python traceback may reach stdout.
- The unified `CatalogDiagnosis` / operation-result object carries: `failure_stage`;
  `current_generation`, `previous_generation`, `target_generation`; `expected` vs
  `observed`; `operation_id`; `asset_id` + `CatalogScope`; and timing/integrity
  telemetry (`elapsed_ms`, `lock_wait_ms`, `db_bytes`, integrity-check result).
  External output MUST NOT leak absolute filesystem paths (evidence refs are
  run-relative / opaque ids).
- Degradation boundary (frozen): only business-availability codes
  (`CHANNEL_UNAVAILABLE`, `QUALITY_BLOCKED`) may degrade a lens. Catalog / pointer /
  manifest / artifact / generation integrity errors MUST propagate to 409/503 and
  MUST NOT produce a partial 200, a `null` layer, or an old-run fallback.
- External-artifact integrity (frozen, normative MUST). After a single market
  `CatalogReadSnapshot` freezes its artifact refs, every participating external
  artifact — canonical, primary, shadow, reconciliation, or revisions — MUST be
  opened and read exactly once, and the EXACT bytes / file descriptor used to parse
  or build the response MUST be SHA-256 checked against the frozen ref OUTSIDE the
  shared lock. Any mismatch or missing participating artifact is
  `ARTIFACT_HASH_MISMATCH` and MUST abort the ENTIRE GET / SDK / diff / composite
  response; there is never a partial 200, a `null` layer, or an old fallback. (An
  OHLCV tamper is caught by THIS external-artifact rule, because OHLCV is not stored
  inside the Catalog SQLite; a tampered Catalog row such as a gate/finding/clock/
  artifact-ref/release target is caught by the `logical_content_hash` chain in
  B.3.)

### B.7a Primary reason-code precedence (frozen)

When more than one condition could apply, a read/operation returns exactly ONE
primary result, in this precedence order (higher wins). `reason_codes` is always a
plural list, but the primary code is deterministic:

1. malformed / unsupported `catalog-current.json` pointer ⇒ `CURRENT_POINTER_INVALID`
   (HTTP 409 / CLI 4).
2. broken switch receipt, generation manifest, or SQLite / file / `catalog_meta` /
   logical-hash chain ⇒ `CATALOG_CORRUPT` (HTTP 409 / CLI 4).
3. malformed / unattributable authoritative source run manifest or audit during
   build / freshness check ⇒ `MANIFEST_INVALID` (HTTP 409 / CLI 4).
4. a participating source artifact's bytes mismatch or are missing ⇒
   `ARTIFACT_HASH_MISMATCH` (HTTP 409 / CLI 4).
5. a valid projection whose `source_fingerprint` is behind the live authoritative
   facts ⇒ `CATALOG_STALE` (HTTP 503 / CLI 5; `status --strict` remains CLI 3).
6. a ready pointer exists but `.btc-assurance.lock` is absent ⇒ `CATALOG_CORRUPT`
   with `failure_stage=assurance_lock_missing` (HTTP 409 / CLI 4); a GET never
   creates the lockfile.
7. an existing lock cannot be acquired before the deadline ⇒ `CATALOG_LOCK_TIMEOUT`
   (HTTP 503 / CLI 5).
8. a stale / different-scope / unsupported / uncommitted rollback target ⇒ primary
   `CATALOG_ROLLBACK_REJECTED` only (CLI 4); it does NOT also return
   `CATALOG_STALE`.

`logical_content_hash` "current pointer" always means the AUTHORITATIVE source
`btc_current.json` snapshot, NEVER `catalog-current.json` (see B.3), so a
pointer-only rollback neither self-references nor changes the logical hash.

### B.8 Phase B acceptance surface (frozen list)

The Phase B acceptance/verification documentation MUST enumerate at least: full
SQLite roundtrip; ordinary Catalog-row tamper (a gate/finding/clock/artifact-ref/
release target caught by the logical hash); external-artifact tamper (canonical,
primary, shadow, reconciliation, revisions — including an OHLCV tamper caught by the
external-artifact SHA-256 rule) each failing closed with `ARTIFACT_HASH_MISMATCH`;
corrupt DB; broken/orphaned switch receipt and pointer↔head-receipt disagreement;
multi-process concurrent CAS (including the same-candidate success no-op); a
crash-after-install-before-CAS orphan that is diagnosed but never served;
publish/rebuild/read barrier; crash failpoints across the fsync window; a REAL
supported-projection rollback of the SAME authoritative fact set (via a second
registered projection policy) plus stale/uncommitted-target rejection
(`CATALOG_ROLLBACK_REJECTED`); pointer/receipt/ledger/manifest/hash disagreement;
malformed newest manifest/audit; ETH isolation; a proof that all reads do ZERO
`build_catalog()` and ZERO writes; and legacy-pair migration behavior.

Phase B rollback-test wording (frozen): the real rollback test asserts a
"supported projection rollback of the SAME authoritative fact set". It MUST NOT
require switching back to an older Formal/source fact head and then remaining
`ready` — that path is `CATALOG_ROLLBACK_REJECTED`.
