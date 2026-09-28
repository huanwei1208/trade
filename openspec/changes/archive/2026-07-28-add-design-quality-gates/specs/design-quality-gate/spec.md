## ADDED Requirements

### Requirement: Immutable versioned design policy profiles
The repository SHALL store constraints in immutable version paths such as `design-policy/v1.toml` with stable namespaced rule IDs, severity, required evidence, resource limits, and exception constraints. Core, contract, storage, forecast, and external-event profiles SHALL compose without duplicating rule ownership.

#### Scenario: Policy is invalid or unsupported
- **WHEN** the selected policy is missing, malformed, mutable-by-alias, duplicated, contains unsupported severity, or exceeds the supported version window
- **THEN** the checker reports a repository configuration error and exits with code `2`

#### Scenario: All-mode sees an immutable policy
- **WHEN** an all-mode quality plan selects an unchanged existing policy version
- **THEN** inventory selection does not report an immutable edit, while a real modification or deletion in Git delta is blocked

### Requirement: Structured governance and applicability
Each governed change SHALL contain `design-quality.toml` with schema/policy versions, every supported impact declared as applicable or not applicable with a substantive reason, and stable obligations mapped to owner, paths, contracts, failure states, spec requirements, and validation tasks.

#### Scenario: New change omits governance
- **WHEN** changed-scope selection identifies a newly added OpenSpec change without `design-quality.toml`
- **THEN** strict changed-scope checking emits a governance blocker instead of treating the change as historical or passed

#### Scenario: Applicability declaration is incomplete
- **WHEN** a governed change omits an impact, gives an unknown value, or provides an empty/N-A-only reason
- **THEN** the checker fails closed with a stable applicability finding

### Requirement: Evidence completeness rather than architectural proof
Executable rules SHALL validate structured evidence, ownership, mappings, and obvious contradictions, but SHALL NOT claim to prove dependency truth, source-of-truth uniqueness, cycle freedom, or architectural optimality without source-derived evidence. Semantic architecture judgment SHALL remain owned by consensus review.

#### Scenario: Brief claims no dependency cycle
- **WHEN** a design contains a prose claim that dependencies are acyclic but provides no owned boundary/evidence mapping
- **THEN** the checker reports missing evidence rather than certifying that the architecture is cycle-free

### Requirement: Bounded deterministic read-only snapshots
The checker SHALL read only the selected immutable policy and allowlisted change artifacts; reject unsafe slugs, traversal, absolute paths, symlinked changes/artifacts, resource-limit breaches, and concurrent artifact changes; bound capability and reachable Git-tree enumeration before sorting/allocation; batch-check historical blob sizes before bounded reads; and SHALL NOT access real DB/parquet assets, source trees, or networks.

#### Scenario: Same snapshot is checked twice
- **WHEN** identical artifact content, options, policy, and effective date are evaluated repeatedly
- **THEN** status, applicability, findings, ordering, exception states, artifact digest, and serialized output are identical

#### Scenario: Artifact changes during evaluation
- **WHEN** an allowlisted artifact changes between snapshot read and completion verification
- **THEN** the checker exits with code `2` and does not approve the mixed-generation design

#### Scenario: Change path escapes or links outside governance root
- **WHEN** a change slug/path is absolute, contains traversal, resolves outside `openspec/changes`, or any selected change/artifact is a symlink
- **THEN** the checker refuses the input with exit code `2`

### Requirement: Stable direct CLI contract
The repository SHALL expose `./trade dev design-check <change> [--strict] [--format text|json] [--as-of YYYY-MM-DD]` through `uv run --frozen --no-sync`, with exit `0` for pass, `1` for change-owned policy rejection, and `2` for invocation or repository configuration errors.

#### Scenario: Strict design contains an unresolved warning
- **WHEN** strict mode evaluates a governed design with a warning and no valid exception
- **THEN** the command emits the warning and exits with code `1`

#### Scenario: Non-strict design contains only warnings
- **WHEN** non-strict mode evaluates a governed design with warnings but no blockers
- **THEN** the command emits the warnings and exits with code `0` for pre-review diagnostics

#### Scenario: CI replays exception expiry
- **WHEN** the command is invoked with `--as-of YYYY-MM-DD`
- **THEN** non-strict output is marked replay/diagnostic and uses that UTC effective date for expiry decisions

#### Scenario: Historical date requests strict approval
- **WHEN** `--strict` is combined with an effective date other than the current UTC date
- **THEN** the command rejects approval with exit code `2`; automatic changed-scope approval never accepts an effective-date override

### Requirement: Machine-readable report and parent integration
JSON output SHALL include schema/checker/policy versions, policy/artifact digests, change names, strict flag, effective date, governance status, applied profiles, ordered findings, artifact inventory, exception states, review provenance for approvals, and summary counts. Parent quality JSON SHALL carry the bounded design report as structured versioned details rather than opaque or truncated JSON text, and SHALL validate the complete v1 field/type contract before trusting its state.

#### Scenario: CI requests JSON
- **WHEN** either direct design-check or changed-scope quality is invoked with JSON output
- **THEN** standard output contains one valid report object whose structured design findings, digests, counts, and remediation are machine-addressable

#### Scenario: Child envelope contradicts itself
- **WHEN** child return code, top-level exit, report exits, error records, summary counts, batch width, real date values, required audit fields, approval commit status, governance/finding state, or finding suppression state disagree or an invoked batch returns empty success
- **THEN** the parent classifies the step as infrastructure failure and never reports a pass

### Requirement: Supplemental aggregate changed-scope contributor
Changed-scope planning SHALL preserve exclusive language/shared file ownership and separately run an aggregate contributor once for all sorted unique applicable OpenSpec changes. The contributor SHALL always run strict, handle 2/10/100 changes without omission, and preserve nested exit `1` as quality and `2` as infrastructure.

#### Scenario: Governed design changes with Python and Markdown
- **WHEN** changed scope contains governed artifacts plus Python and Markdown files
- **THEN** the plan contains one strict design batch step and all ordinary Python/shared checks without ownership theft or duplicate design steps

#### Scenario: Multiple governed changes are modified
- **WHEN** changed scope contains artifacts from multiple governed changes
- **THEN** one bounded batch step evaluates every sorted unique change and aggregate exit precedence is preserved

#### Scenario: Child closes output before hanging or floods structured output
- **WHEN** the aggregate child closes both pipes before its deadline or exceeds the structured stdout limit and continues running
- **THEN** the parent preserves the original timeout, terminates the process group, and returns a bounded infrastructure failure

#### Scenario: Historical ungoverned change is untouched or edited
- **WHEN** a pre-governance historical change has not been explicitly migrated and is not newly added
- **THEN** its existing shared checks remain while design governance reports `NOT_GOVERNED` rather than `PASS` or automatic rejection

### Requirement: Governance deletion cannot bypass checking
Scope selection SHALL preserve added and deleted path metadata separately from ordinary live source ownership. Deleting a governed marker or required artifact SHALL trigger design checking and fail closed unless an explicit supported archive/migration operation retains auditable governance evidence.

#### Scenario: Marker is deleted
- **WHEN** committed, staged, or unstaged changed scope deletes `design-quality.toml`
- **THEN** the aggregate contributor still selects that change and emits a governance-removal blocker

### Requirement: Digest-bound six-role review evidence
Strict implementation approval SHALL require `design-review.toml` with schema/policy version, current portable policy/design artifact digests, a full reviewed commit SHA, six required role results, finding IDs, severity/priority/consensus count, resolution status/evidence, and final `approved` state. The attested digest SHALL exclude the review file itself. A reachable reviewed commit SHALL receive an additional exact policy blob and complete governed inventory/content check.

#### Scenario: Review evidence is missing, stale, or unresolved
- **WHEN** strict approval has fewer than six complete roles, an artifact digest mismatch, final blocked status, or an unresolved P0 finding
- **THEN** the checker emits a blocker and refuses implementation approval

#### Scenario: Squash removes the reviewed feature commit
- **WHEN** approved artifacts are squash-merged unchanged and a fresh clone cannot resolve the original reviewed commit
- **THEN** strict approval verifies the portable policy/artifact digests, records the commit as unreachable, and remains reproducible

### Requirement: Owned and expiring warning exceptions
An exception SHALL apply only to a suppressible warning and SHALL name rule ID, owner, non-empty reason, and valid expiry. Invalid, expired, unknown, or blocker-targeting change exceptions SHALL be visible policy findings with exit `1`; applied and soon-expiring exceptions SHALL remain visible in reports.

#### Scenario: Warning exception expires
- **WHEN** strict mode encounters an otherwise matching exception whose expiry precedes the effective date
- **THEN** the warning remains unresolved, the exception is reported as expired, and the command exits with code `1`

### Requirement: Point-in-time and predictive evidence profile
When point-in-time or predictive impact applies, the design SHALL map typed decision/event/publication/first-seen/available/revision clocks, each bound to its distinct policy-approved source/fallback/timezone/confidence; knowledge mode; revision/universe policy; controlled coverage, maturity, calibration, and unavailable states; leakage tests; evidence identity; out-of-sample population/window/horizon/method/metrics/positive sample count/uncertainty/regime slices/baseline; and promotion criteria. `no_numeric_fallback` SHALL be boolean true. Missing, pending, stale, or uncalibrated state SHALL NOT become an ordinary numeric prediction or success state.

#### Scenario: Forecast claims validation without auditable calibration
- **WHEN** a predictive design omits evidence identity, out-of-sample/calibration fields, baseline, coverage, or explicit unavailable behavior
- **THEN** the forecast profile emits hard evidence blockers and does not allow a validated claim

### Requirement: Persistent-write safety profile
When persistent-write or schema-migration impact applies, the design SHALL map authoritative writer, idempotency/retry key, concurrency control, staging/validation, atomic visibility, crash windows, corruption preservation, partial-result aggregation, reader consistency, backup/hash, small-sample verification, rollback, and audit evidence. Schema migration SHALL additionally require typed version preservation, backward and forward compatibility modes, dual-read/write, non-destructive checkpointed backfill, readiness-gated cutover, restorable rollback, and a bounded legacy-retirement window.

#### Scenario: Write path can publish mixed generations
- **WHEN** a design adds persistent writes without single-writer authority, staging validation, atomic activation, or reader consistency evidence
- **THEN** the storage profile emits a non-suppressible blocker

### Requirement: External-event data profile
When news, social, macro, on-chain, or third-party event-data impact applies, the design SHALL map typed event/publication/first-seen/available/revision clocks bound to their distinct sources; a known stable source ID and source kind; verified/contracted/public-record provenance bound to the same source ID and a non-placeholder reference; approved licensing; the complete nonempty/empty/partial/unavailable/rate-limited/invalid/stale state set; finite bounded quota/cost/concurrency/retry/circuit/queue values; enabled idempotency with source/event keys, bounded deduplication, durable/transactional persistence, and controlled conflict handling; mandatory backpressure/DLQ/replay/tombstone behavior; correction/finality enums; and explicit degraded/unavailable outcomes.

#### Scenario: Missing source time falls back to now
- **WHEN** an external-event design substitutes ingestion time for missing publication/event time without an explicit estimated timestamp and provenance state
- **THEN** the external-event profile emits a temporal-integrity blocker

### Requirement: Cross-artifact obligation consistency
Each applicable safety obligation SHALL reference owned paths/contracts, at least one matching spec requirement/scenario, and at least one validation task whose text contains `[validates:<obligation-id>]` plus `[validation:test]` with test/check/smoke semantics or `[validation:review]` with evidence/finding/consensus semantics. Contradictory declarations, missing references, decorative task references, or orphan safety obligations SHALL block approval.

#### Scenario: Proposal claims no migration while design adds writes
- **WHEN** applicability, proposal, design, specs, tasks, or obligation mappings disagree on persistent-write/schema/public-contract impact
- **THEN** the checker reports a stable cross-artifact contradiction or orphan-obligation blocker

#### Scenario: Requirement or task identifier is duplicated
- **WHEN** a capability repeats a requirement identifier, even if only one copy has a scenario, or tasks repeat an identifier
- **THEN** obligation resolution reports an ambiguity blocker rather than silently folding duplicates

### Requirement: Bounded evaluation capacity
Policy v1 SHALL cap allowlisted artifacts at 128 files, 256 KiB per file, 2 MiB total per change, 200 emitted findings, 100 changes per batch, and 16 MiB artifact bytes per batch unless a future immutable policy version changes those reviewed limits. Batch count, bounded directory/tree enumeration, metadata/byte budgets, and historical Git blob sizes SHALL be checked before artifact bodies are read. Reviewed blobs SHALL be fetched in bounded batches rather than one process per artifact.

#### Scenario: Change contains an oversized artifact or deep unrelated executable
- **WHEN** an allowlisted artifact exceeds a configured limit or an unrelated executable exists under the change directory
- **THEN** the checker fails closed for the oversized allowed input and ignores the non-allowlisted executable without reading it

#### Scenario: Batch exceeds aggregate limits
- **WHEN** a batch contains more than 100 changes or more than 16 MiB of allowlisted artifact bytes
- **THEN** the checker exits with code `2` before reading artifact bodies and reports the applicable aggregate limit
