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
| catalog stale / rebuilding | 503 | `CATALOG_STALE` + retry_after |
| unchanged | 304 | consistent ETag + view fingerprint |

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
