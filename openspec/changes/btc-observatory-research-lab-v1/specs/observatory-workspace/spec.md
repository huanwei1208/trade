## ADDED Requirements

### Requirement: Observatory context API exposes the full truth surface
The system SHALL provide `GET /api/v1/observatory/assets/crypto.BTC/context`
returning the semantic channels with latest attempt/staged references, the
Snapshot Context, purpose fitness, primary blockers, a deterministic what-changed
summary, active alerts, and supported lenses/ranges. It SHALL NOT return only an
"updated time".

#### Scenario: Truth bar shows all watermarks
- **WHEN** a client requests context at latest
- **THEN** the response includes expected latest completed bar, Latest Observed, Latest Staged, Evaluated Candidate, and Formal Baseline watermarks with freshness, compatibility, and integrity

#### Scenario: Why-not-formal is explained
- **WHEN** the Candidate is unpublished
- **THEN** the context returns the primary publication blocker with reason codes and evidence references

### Requirement: Series API returns layered composite or single-snapshot rows
The system SHALL provide `GET /api/v1/observatory/assets/crypto.BTC/series`
supporting `view=composite|observed|evaluated_candidate|formal` with
`knowledge_as_of`, `knowledge_mode`, and `revision_policy` parameters.
`view=composite` SHALL return independent layers; single-snapshot queries SHALL
return rows. Both SHALL use membership, availability_state, quality_flags, and
revision_state, and SHALL NOT return a merged `row_state`. Responses SHALL carry an
ETag and snapshot/view fingerprint.

#### Scenario: Composite with observed-only tail
- **WHEN** requesting `view=composite` where observed data extends past the candidate watermark
- **THEN** the response returns formal, candidate, and observed layers with an observed-only tail and no merged OHLCV

#### Scenario: Missing dates are not interpolated
- **WHEN** a series has missing market dates
- **THEN** the response marks them missing and does not forward-fill or interpolate

#### Scenario: Quarantined rows excluded from values but visible as markers
- **WHEN** `include_quarantined=false`
- **THEN** quarantined dates are excluded from OHLCV/metrics but returned as `excluded_dates` with reason, quality flags, evidence, and marker position

#### Scenario: Invalid composite selector
- **WHEN** `view=composite` is combined with an exact snapshot/run/release identity
- **THEN** the response returns `INVALID_SNAPSHOT_SELECTOR`

### Requirement: Date evidence, trust, and runs APIs support drill-down
The system SHALL provide date-evidence, trust, runs, run-detail, and run-diff
endpoints that trace any drawn bar to provider/run/artifact hash, and SHALL
strictly validate run ids against a format and a root-directory boundary to reject
path traversal.

#### Scenario: Date evidence drill-down
- **WHEN** a client requests `dates/2026-07-18?snapshot_id=...`
- **THEN** the response returns primary/shadow evidence, basis, times, findings, revision history, run lineage, and research visibility

#### Scenario: Run diff beyond watermark
- **WHEN** two runs are diffed
- **THEN** the response includes added/removed dates, changed OHLCV, quarantine changes, provider/schema/config/code changes, watermarks, coverage, artifact hashes, and gate/finding changes

#### Scenario: Path traversal rejected
- **WHEN** a run id contains path traversal characters
- **THEN** the request is rejected with a stable reason code and no local path is leaked

### Requirement: Acquisition calendar respects attempt-receipt availability
The system SHALL aggregate the Acquisition Calendar by real acquisition date,
counting at most one qualified acquisition day per date while keeping run detail
drillable. If attempt receipts are not implemented in V1, the Calendar SHALL show
only completed facts provable from immutable manifests/audits and SHALL display
pre-stage states as `unsupported`/`unknown` rather than painting "no record" as
failed.

#### Scenario: Multiple reruns on one day
- **WHEN** a date has multiple qualified runs
- **THEN** the Acquisition Calendar counts one qualified acquisition day and still exposes each run in drill-down

#### Scenario: Pre-stage state without attempt receipts
- **WHEN** attempt receipts are not implemented and a date has no completed manifest
- **THEN** the Calendar shows `unsupported`/`unknown` for that date and does not display it as failed

### Requirement: HTTP, serialization, and pagination contract is frozen
The system SHALL map errors to stable HTTP statuses and reason codes: 400 for
invalid params/identity, 404 `SNAPSHOT_NOT_FOUND`, 422 `PIT_NOT_PROVEN` with
coverage interval, 422 quality/research blockers with evidence and retryability,
409 for pointer/hash/manifest integrity failures, 503 `CATALOG_STALE` with
retry_after, and 304 with a consistent ETag/view fingerprint. Times SHALL be UTC
RFC 3339 with `Z`; market dates SHALL be `YYYY-MM-DD`. Nullable fields SHALL be
`null`, never `0`/empty string/empty array. Lists SHALL use a fixed sort key with
id tie-break and cursor pagination stable within a Catalog fingerprint.

#### Scenario: Integrity failure returns 409, not stale success
- **WHEN** an artifact hash mismatch is detected
- **THEN** the API returns 409 with fail-closed reason codes and does not return a stale cached success

#### Scenario: Unchanged resource returns 304
- **WHEN** a client re-requests with a matching ETag and no relevant fact change
- **THEN** the API returns 304 with a consistent view fingerprint

#### Scenario: Stable cursor pagination
- **WHEN** a client pages through runs/findings within one Catalog fingerprint
- **THEN** no row is duplicated or skipped across pages

### Requirement: Overview renders three layers with non-color semantics
The system SHALL render an Overview with a persistent Snapshot Context Bar, a
composite main chart with independent formal/candidate/observed layers and a formal
watermark divider, a market summary, purpose fitness, why-not-formal, and a
deterministic what-changed panel, restorable from a fixed URL. Status SHALL be
expressed with text, icon, and texture in addition to color, and a Candidate SHALL
never be renderable as Published.

#### Scenario: Observed exceeds formal watermark
- **WHEN** observed watermark exceeds formal watermark
- **THEN** the Overview shows an observed-only tail with a distinct texture and does not present it as published

#### Scenario: Non-color quarantine and revision
- **WHEN** a date is quarantined or revised
- **THEN** the chart marks it with a non-color shape and links back to the Date Evidence lens

### Requirement: Web reads are read-only and consume the shared kernel
The system SHALL ensure Web surfaces perform only read-only operations, consume the
same snapshot/metric contract as the SDK, and never join file paths, recompute
formal metrics in the browser, or trigger sync/publish/rollback. `app.py` SHALL
perform only minimal route registration for the observatory router.

#### Scenario: Open in Lab is a deep link only
- **WHEN** a user activates Open in Lab
- **THEN** the Web returns a deep link/params/command that fixes `snapshot_id` and does not start a process, create a notebook, write files, or register a research run
