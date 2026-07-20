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

- `CATALOG_CORRUPT` — a committed generation's pointer/manifest/SQLite/`catalog_meta`
  /logical-hash chain does not reconcile (missing, wrong-type, integrity-check
  failure, identity disagreement). Fail closed; never a stale success.
- `CATALOG_CAS_CONFLICT` — a publish/rollback pointer compare-and-swap observed a
  different expected-previous than the one it froze; a concurrent committer won.
- `CATALOG_ROLLBACK_REJECTED` — a pointer-only rollback target is not a supported
  projection of the current authoritative BTC fact set (scope, reader support, or
  `source_fingerprint` mismatch). It is not a Formal/source rollback.
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
CAS-published, fail-closed read projection. They resolve the 2026-07-20 consensus
review (score 3.3/10) P0 findings F6/F7/F8/F9/F17. RA.2 and RA.3 remain UNCHECKED;
this is a contract/design freeze only — no Python/TS/test implementation lands in
Batch B0. Where a clause tightens an earlier WP1 note (single `catalog.sqlite`,
single `generation.json`), the earlier note is superseded per the equivalence
mapping in `design.md`.

Phase B version constants (frozen initial values; bump any one ⇒ new
`generation_id`):

| Constant | Initial value |
| --- | --- |
| `scope_policy_version` | `obs-scope-v1` |
| `projection_policy_version` | `obs-projection-v1` |
| `pointer_schema_version` | `obs-pointer-v1` |
| `manifest_schema_version` | `obs-genmanifest-v1` |
| `catalog_schema_version` | `obs-catalog-v1` (unchanged from WP1) |

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
| `catalog-current.json` | current-generation pointer (typed) | mutable pointer, CAS-switched |
| `generations/catalog-<generation_id>.sqlite` | materialized projection DB | immutable once installed |
| `generations/catalog-<generation_id>.manifest.json` | generation manifest | immutable once installed |
| `.candidate-<uuid>/` (hidden temp) | in-progress candidate build | same filesystem; renamed/cleaned, never served |

- The candidate DB + manifest are materialized in a hidden temp directory ON THE
  SAME FILESYSTEM as `generations/`, so the final install is an atomic rename, not
  a cross-device copy.
- Immutable artifacts are install-once: a publisher MUST NOT overwrite an existing
  `catalog-<generation_id>.sqlite` or `.manifest.json`. Recomputing the same
  `generation_id` is an idempotent no-op install (see B.4), never an overwrite.
- The legacy single-file pair `catalog.sqlite` + `generation.json` is retained
  read-only as a legacy pair. New read code MUST NOT overwrite, delete, or migrate
  it, and MUST NOT migrate inside a GET/SDK read. When ONLY the legacy pair exists
  (no `catalog-current.json`), the read diagnosis is `CATALOG_STALE` with a stable
  `legacy_catalog_requires_rebuild` marker; the operator rebuilds into the new
  layout out of band.
- The old→new design equivalence/supersession mapping is recorded in `design.md`
  (§ "Phase B immutable-generation layout").

### B.3 Identity and integrity (frozen)

- `generation_id` is a normalized, deterministic derivation over:
  `CatalogScope` (asset + scope tuple), `catalog_schema_version`,
  `projection_policy_version`, `source_fingerprint`, and the full
  `logical_content_hash`. Same inputs ⇒ same `generation_id` (idempotent rebuild);
  any input change ⇒ a new `generation_id`.
- The immutable generation manifest MUST carry at least: `asset_id`, full
  `CatalogScope`, `pointer_schema_version`, `manifest_schema_version`,
  `catalog_schema_version`, `projection_policy_version`, `generation_id`,
  `source_fingerprint`, `logical_content_hash`, the SQLite file SHA-256,
  the SQLite DB filename, the fact count, and the fact-set hash.
- The frozen verification chain, applied whole on every read (B.5):
  `catalog-current.json` (typed pointer) → immutable generation manifest →
  SQLite file SHA-256 → SQLite `catalog_meta` identity → deserialized canonical
  `logical_content_hash`. Any break in this chain is `CATALOG_CORRUPT` (409 / CLI
  exit 4). No link may be skipped.
- `logical_content_hash` covers EVERY field the resolver needs, canonicalized in a
  stable order: runs; contracts; the four clocks + provenance; gates; findings;
  artifact refs; releases; the release-event ledger + active head; the revision
  index; the current pointer; and the relevant fact set. Hashing only a subset of
  fields is prohibited — a tampered "ordinary business row" (e.g. a single OHLCV
  value or gate result) MUST change the hash and fail the read closed.

### B.4 Durable publish, CAS, and locks (frozen)

- The Catalog reuses and PUBLICLY exposes the SAME lock owner as BTC assurance:
  `BtcRunStore` at `trade_py/data/market/crypto/store.py`, lockfile
  `<crypto_root>/.btc-assurance.lock`, public `shared_lock()`, exclusive owner.
  A ready Catalog with no lockfile is a fail-closed error; a GET MUST NOT create
  the lockfile.
- Write protocol (publish/rebuild/update), frozen ordering:
  1. Under a **shared** lock, freeze both a scoped `SourceSnapshot` and the
     expected Catalog pointer from ONE batch of raw bytes.
  2. **Outside the lock**: project, materialize the candidate DB, close the
     transaction, verify integrity + `logical_content_hash` + file SHA-256, and
     `fsync` the candidate file.
  3. Under an **exclusive** lock: re-read the live source fingerprint and the
     expected-previous pointer and re-confirm both. A shared→exclusive upgrade is
     PROHIBITED (release shared, then acquire exclusive).
  4. Install the immutable DB + manifest (install-once; never overwrite), then as
     the LAST step CAS the `catalog-current.json` pointer. `flush`/`fsync` the
     pointer file and its parent directory.
- Concurrency outcomes (frozen):
  - Two writers computing the SAME candidate `generation_id` may each report an
    idempotent no-op install, but only ONE committed pointer switch occurs.
  - A CAS whose observed expected-previous differs from the one it froze, or whose
    target differs, is a stable `CATALOG_CAS_CONFLICT` (CLI exit 5), never a silent
    overwrite.
- Read barrier (frozen): a reader takes a strict **shared** lock, freezes ONE typed
  pointer once, opens and verifies ONE immutable generation, deserializes ONE
  `CatalogReadSnapshot`, and reconciles BTC `current`/ledger/manifest identity.
  Resolver, query, diff, and SDK all reuse that one snapshot. The read path does
  ZERO `build_catalog()` and ZERO writes. The lock covers only the
  freeze/open/verify critical section; parquet/JSON response bytes are produced
  OUTSIDE the lock, on the already-verified immutable refs.
- Retention (frozen): Phase B retains ALL committed generations. There is no
  destructive GC. An orphan generation file (present on disk but not referenced by
  the pointer chain) is DIAGNOSED only — never auto-served and never auto-deleted.

### B.5 Rollback vs stale (frozen)

- A `catalog rollback` is **pointer-only** and is allowed ONLY when the target
  generation: (a) has the SAME `CatalogScope`, (b) is reader-supported
  (`catalog_schema_version`/`pointer_schema_version` in range), AND (c) has
  `target.source_fingerprint == the current authoritative BTC fact set`. It is a
  projection/policy rollback (e.g. projection or policy version), NOT a Formal
  truth rollback.
- A historical generation built from a DIFFERENT `source_fingerprint` MUST be
  rejected as `CATALOG_ROLLBACK_REJECTED` / `CATALOG_STALE` (CLI exit 4). There is
  NO "pinned" mode that silently serves a stale fact head.
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
- Release modelling: the release-event ledger is modelled SEPARATELY from the
  active Formal head. A rollback event ACTIVATES `to_run_id` (it does not blank the
  active head); the sole exception is an explicit legacy→none rollback whose target
  is "no active head".

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

### B.8 Phase B acceptance surface (frozen list)

The Phase B acceptance/verification documentation MUST enumerate at least: full
SQLite roundtrip; ordinary business-row tamper; corrupt DB; multi-process
concurrent CAS; publish/rebuild/read barrier; crash failpoints across the
fsync window; a REAL supported-projection rollback of the SAME authoritative fact
set plus stale-target rejection; pointer/ledger/manifest/hash disagreement; five
classes of artifact tamper (canonical, primary, shadow, reconciliation, revisions);
malformed newest manifest/audit; ETH isolation; a proof that all reads do ZERO
`build_catalog()` and ZERO writes; and legacy-pair migration behavior.

Phase B rollback-test wording (frozen): the real rollback test asserts a
"supported projection rollback of the SAME authoritative fact set". It MUST NOT
require switching back to an older Formal/source fact head and then remaining
`ready` — that path is `CATALOG_ROLLBACK_REJECTED`.
