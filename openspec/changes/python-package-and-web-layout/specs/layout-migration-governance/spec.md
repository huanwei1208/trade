## ADDED Requirements

### Requirement: Every current path SHALL have a source-evidenced disposition before movement or retirement

Each candidate path SHALL be classified using current consumers, state transitions, table and
artifact access, transaction behavior, provider/framework/native dependencies,
commands/events/queries, import side effects, semantic owner, target cell,
compatibility obligation, validation and rollback. Scheduler, event, news and
sentiment paths SHALL additionally record clock source/timezone,
source/publication/observed/knowledge/partition times, lateness/finality,
replay range and idempotency identity in a typed per-path temporal manifest.
The manifest SHALL also bind a canonical semantic registration order containing
schedule ID, topic, owner, conditional capability, predecessor/successor
constraints and digest rather than relying on incidental source order.

A path SHALL have exactly one of: `owner_ready`, `compatibility`,
`split_required`, `tool`, `deployment`, `example`, `test`, `historical`,
`blocked` or `retireable`. A directory name alone SHALL not determine the
disposition.

#### Scenario: An Observatory file is classified
- **WHEN** the file composes HTTP/SDK queries rather than owning a business aggregate
- **THEN** it is classified as an Interface/BFF compatibility path and not as an Observatory bounded Context

#### Scenario: A root script mutates data
- **WHEN** a root script can relocate data paths or mutate durable business data or metadata
- **THEN** it remains blocked or moves only under its owning migration change with backup, dry-run, verification and rollback evidence

#### Scenario: Historical material contains a still-referenced decision
- **WHEN** a governed document or source comment links to an `_bmad-output` file
- **THEN** the valid decision is extracted with provenance and the historical file is retained until link and retention checks pass

#### Scenario: A scheduler or news path lacks temporal semantics
- **WHEN** classification cannot prove timezone or process-local clock, DST/misfire/catch-up policy, partition/finality rule, replay range or idempotency identity applicable to that path
- **THEN** the path remains `blocked` until its Scheduler, Capture or Dataset owner child freezes those semantics

#### Scenario: A temporal negative fixture is ambiguous
- **WHEN** missing or ambiguous timezone, DST fold/gap, restart misfire, unbounded catch-up, registration-order drift, late correction/tombstone, replay-boundary or duplicate source-event identity cannot be classified deterministically
- **THEN** the path remains `blocked`, its authority does not advance and the owner child must resolve the temporal manifest rather than inherit process-local behavior

### Requirement: Notebook and SDK consumers SHALL use installed public contracts

Target notebooks and examples SHALL import an installed SDK shared with CLI and
HTTP Interface adapters. They SHALL NOT modify `sys.path`, search repository
parents, scan source files, read formal parquet directly, import repositories
or adapters, or rely on current working directory.

Notebook validation SHALL execute from a clean working directory against
temporary immutable fixtures and compare explicit reference identity, status
and error semantics. Notebook movement SHALL not change a moving `latest` read
into a formal reproducible result. An SDK snapshot handle SHALL resolve at most
once, pin the resolved snapshot/run/release/artifact generation for its complete
lifetime and return an explicit stale/conflict failure rather than mix
generations.

#### Scenario: The installed SDK is not ready
- **WHEN** a notebook still requires a legacy internal resolver or repository path
- **THEN** the notebook remains at its current path and no source-path workaround is added to the target example

#### Scenario: The same immutable snapshot is opened from Web and notebook
- **WHEN** both consumers use the same reviewed snapshot reference and knowledge policy
- **THEN** they observe the same snapshot identity, lifecycle/quality state and owner query semantics through public contracts

#### Scenario: Current release changes while a handle is in use
- **WHEN** the formal/current release advances between context, bars, findings and research queries on one SDK handle
- **THEN** every query uses the handle's pinned snapshot/run/release/artifact refs or returns an explicit stale/conflict result, and no response combines two generations

### Requirement: Root scripts SHALL be classified by operational ownership

Each root script SHALL be inventoried as one of:

- public CLI adapter;
- owner-specific migration;
- deployment/operations tool;
- example;
- historical one-time utility;
- blocked mixed-responsibility code.

A script SHALL not remain an installable package merely because current
setuptools discovery includes `scripts*`. Migration scripts SHALL never be
imported as business libraries. Backup code SHALL separate Platform technical
capability from business repository ownership before movement.

#### Scenario: A migration script is present in a wheel
- **WHEN** a clean wheel contains a destructive one-time migration that was not explicitly approved as an installed command
- **THEN** the wheel-member guard fails and reports that script

#### Scenario: A backup script mixes driver and TradeDB operations
- **WHEN** classification finds technical remote storage plus business database access
- **THEN** it is split-required and remains at the compatibility path until both owners and contracts exist

### Requirement: Test layout migration SHALL preserve component ownership and collection evidence

Tests SHALL move gradually into `unit`, `integration`, `contract`,
`architecture`, `golden`, `e2e` and `fixtures` according to behavior, while
Python, frontend and C++ component runners retain appropriate ownership.
Production movement and broad test reclassification SHALL not occur in the
same migration slice.

Each test-layout slice SHALL record old/new node mapping, collection count,
marker/fixture resolution, data/network isolation and focused behavior result.
No test SHALL be dropped, duplicated or silently deselected because its path
changed.

#### Scenario: A test file moves to a category directory
- **WHEN** pytest collection runs before and after the slice
- **THEN** every reviewed old test maps to exactly one new test node and no unrelated node disappears or duplicates

#### Scenario: A frontend or C++ test is classified
- **WHEN** the test belongs to Vite/Vitest/Playwright or CMake/ctest
- **THEN** it remains with that component runner and is referenced by repository validation rather than copied into Python pytest

### Requirement: Migration validation SHALL be bounded, deterministic and process-clean

Package/layout inventories SHALL use sorted Git-tracked paths and fixed
selection rules. One authority slice SHALL contain no more than 50 production
modules and 500 consumer records. Validation SHALL not randomly sample or
silently truncate; exceeding a bound SHALL require a smaller explicit slice.
One shared tree index SHALL be built per repository tree/scanner/rules digest,
and deterministic owner/module partitions SHALL reuse it rather than rescan
the whole tree per slice.

Build, install, import, ASGI, browser and native checks SHALL run in terminable
process groups with finite deadlines. Timeout, test failure, contract mismatch,
tool failure and unavailable prerequisite SHALL be reported as distinct
states. Reaching a deadline SHALL terminate the process tree and retain partial
reports without advancing authority.

The complete validation scheduler SHALL enforce the reviewed per-validation-
process-tree worker, heavy-job, RSS, temporary-disk and queue-deadline bounds.
It SHALL NOT claim cross-invocation or host-global admission without a
separately reviewed shared lease. Startup/import
benchmarks SHALL bind runner image, toolchain and dependency lock and SHALL
enforce reviewed p50/p95, RSS and imported-module thresholds. Current and
synthetic ten-times source indexes SHALL enforce the reviewed scan-count,
wall-time and RSS bounds. Resource or performance overflow SHALL fail as
`capacity_refusal`; it SHALL NOT drop checks or samples.

Reports SHALL model `migration_state`, `execution_state`, `startup_state`,
`failure_class`, `rollback_state`, `reconciliation_state` and
`operator_action` as separate closed fields. `startup_state` SHALL be one of
`not_started`, `starting`,
`started_healthy`, `started_degraded`, `failed` or `stopped`, with bounded
reason codes and degraded component identities. Reports SHALL include a tool
exit code when one exists, a bounded failure detail, `partial_evidence_ref`,
and active/prior generation identities. Lifecycle and startup state SHALL NOT
overwrite or imply an execution, failure or rollback result.

#### Scenario: A package smoke process hangs
- **WHEN** an install, import, console, ASGI or native command exceeds its reviewed deadline
- **THEN** the whole owned process group and descendants are terminated with bounded TERM-to-KILL escalation, zero residual PIDs are verified, `execution_state=stopped`, `failure_class=timeout`, completed evidence is retained and no module authority advances

#### Scenario: The candidate slice exceeds the consumer budget
- **WHEN** more than 500 current consumers map to the slice
- **THEN** validation refuses the slice and requires a narrower deterministic grouping rather than taking the first 500 or sampling

#### Scenario: A rollback succeeds after validation failed
- **WHEN** the reviewed exact-predecessor or current-composition compensation target is selected after a contract mismatch
- **THEN** the report retains `failure_class=contract_mismatch`, records `rollback_state=succeeded` independently and does not relabel the failed validation as passed

#### Scenario: Startup remains available after automation failure
- **WHEN** core resources start but a compatible startup automation component fails
- **THEN** the report uses `startup_state=started_degraded`, names the bounded component/reason, remains running and reports neither `started_healthy` nor fatal startup

#### Scenario: Validation process-tree capacity is exhausted
- **WHEN** worker, heavy-job, RSS, temporary-disk or queue-deadline admission would exceed its reviewed bound
- **THEN** no additional child starts, admitted process groups are cleaned, partial evidence is retained and the attempt reports `capacity_refusal` rather than silently omitting validation

### Requirement: Migration evidence SHALL bind inventory, activation and outcomes

Before cutover, each authority attempt SHALL produce one immutable,
digest-bound `PreparedEvidenceRef`. It SHALL bind the operation and attempt
identities, activation-plan digest, immutable inputs and intended target,
expected generation/revision/fence, stable deployment-unit identity,
invocation token and owner-adapter command digests. It SHALL NOT contain a
placeholder for selector, process, verification or terminal outcomes that do
not yet exist. Selector and phase records SHALL retain the prepared ref or
operation identity.

After `verified` or a terminal failure/rollback outcome, each completed
attempt SHALL produce one immutable, digest-bound `MigrationEvidenceRef`. It
SHALL bind the exact `PreparedEvidenceRef`, source commit/tree, policy and
approved design digest, complete `ConsumerInventoryRef`, authority and
package/Web/native generation refs, activation-plan digest, selectors observed
before and after including generation/revision/fence, operation ID, ordered
activation-phase and process receipts, toolchain and ordered command
identities, monotonic deadline policy, per-check typed outcomes,
shutdown/escalation/residual-process receipt, partial-evidence refs and final
report digest. The authority record MAY link the final ref; no plan, selector
or earlier immutable receipt SHALL be overwritten to insert it.

`ConsumerInventoryRef` SHALL bind scanner version/source digest, included roots,
explicit exclusions, selection-rules digest, UTC generation time, counts,
completeness state and sorted entry/report digests. Activation SHALL admit only
a `complete` inventory from the same repository tree and scanner rules, no more
than 24 hours old. Scan error SHALL be `tool_failed`, never an empty inventory.

#### Scenario: Source changes after consumer scanning
- **WHEN** the repository tree, scanner, rules or scope differs from the inventory reference used by activation
- **THEN** the attempt is refused as stale and a fresh complete inventory is required

#### Scenario: Individual checks pass without one evidence manifest
- **WHEN** wheel, CLI and import logs exist but are not bound into one valid `MigrationEvidenceRef`
- **THEN** module authority remains unchanged because uncorrelated command success is not activation evidence

### Requirement: Every migration slice SHALL be independently reversible

Each slice SHALL name its prior authority, target authority, activation
condition, rollback trigger, closed selector scope, retained compatibility
path and post-rollback validation. Python modules and ASGI/backend SHALL share
one immutable `python_deployment` selector; they SHALL be independently
reversible as logical deltas through compensating successor generations, not
independently selectable runtime implementations. Frontend build and an
explicitly reviewed finite native capability MAY have independent selectors.

Each slice SHALL publish an immutable `LayoutActivationPlanV1` with the exact
selector mechanism and precedence, expected current generation, target and
rollback or compensation target, current composition-manifest digest, desired
slice delta, expected selector revision, idempotent operation ID, owner-adapter
activation and rollback argv digests, immutable input refs, operator, deadline
and post-action checks. After the plan digest is known, the attempt SHALL
create `PreparedEvidenceRef` binding the plan and operation; the plan SHALL NOT
embed that prepared ref. Activation SHALL use linearizable compare-and-set
semantics on both expected generation and revision, allocate exactly the next
monotonic revision/fence, and SHALL reject moving package
specifiers, unverified `latest` paths, arbitrary selector scopes and one global
selector for all scopes.
Repeating one operation ID with identical inputs SHALL return the committed
selector; reusing it with different inputs SHALL fail. Rollback SHALL be a new
forward revision and SHALL never decrement a fence. When later accepted
Python/ASGI slices exist, rollback SHALL build and verify a new immutable
generation from the current composition with only the failed delta reversed;
it SHALL NOT select a historical full generation that removes later slices.

The Python/ASGI selector SHALL be an immutable virtualenv or container
generation while retaining `trade_web:create_app`; the Web selector precedence
SHALL remain `--web-dist`, then `TRADE_WEB_DIST`, then a reviewed default
generation; native selection SHALL be bound to the owning adapter and the exact
artifact in the selected Python generation.

Rollback SHALL not require database migration, artifact deletion, provider
access or reversal of previously completed semantic owner migrations.

#### Scenario: A post-cutover consumer is discovered
- **WHEN** an unsupported or missed consumer fails after target authority activation
- **THEN** the affected module returns to its prior authority or forwarding state, the consumer inventory is updated and only that slice is revalidated

#### Scenario: Rollback validation fails
- **WHEN** a Python/ASGI compensation generation or independently selected prior Web/native reference does not restore its recorded imports/contracts
- **THEN** rollout halts, the bridge remains installed and the failure is P0 until the prior authority is recoverable

#### Scenario: Another operator changed the active generation
- **WHEN** activation observes a current generation or revision different from the plan's expected selector
- **THEN** it performs no switch and requires a newly reviewed plan rather than overwriting the concurrent decision

#### Scenario: An older Python slice fails after later slices were accepted
- **WHEN** slices A, B and the ASGI factory were accepted in successive Python deployment generations and A must be reversed
- **THEN** rollback builds a new successor whose composition preserves B and ASGI exactly, reverses only A, passes the complete focused matrix and is selected by a higher revision

#### Scenario: A delayed process reports startup
- **WHEN** a process-start or verification receipt carries a revision older than the current selector fence
- **THEN** the receipt is rejected, authority does not advance and the stale process is reported for bounded teardown

### Requirement: Deployment selector state SHALL be durable, fenced and crash-recoverable

Real authority changes SHALL use one explicitly configured deployment layout
control store outside the repository, package generation and business-data
root. The policy-free deployment layout controller SHALL be the sole selector
and operation writer. It SHALL accept only finite scope identities and opaque
generation/plan/evidence digests and SHALL NOT import application packages or
interpret Python module, ASGI, Web, native or business policy. Typed
slice-owner adapters SHALL own planning, activation, verification and
compensation and depend on the store port, never the reverse. A service manager
MAY write only its own fenced start-intent/process receipt, and layout status
SHALL remain read-only.

The store SHALL use owner-only directories/files, reject symlinks, non-regular
files, traversal and oversized identities/records, and retain one
digest-verified current selector per scope. Per-scope locking plus
same-directory staging, flush, fsync, atomic replace and directory fsync SHALL
make selector CAS linearizable. Malformed, missing-field, wrong-owner or
inconsistent predecessor state SHALL be preserved and SHALL block mutation
without automatic repair.

Every operation SHALL append immutable, digest-bound `prepared ->
selector_committed -> start_intent_recorded -> process_started -> verified`
receipts keyed by operation ID. Before service-manager invocation, the start
intent SHALL durably bind a stable deployment-unit identity and invocation
token to operation, generation, revision/fence and exact owner-adapter command
digest. Only `verified` may advance authority. Startup reconciliation SHALL
compare the current selector, operation phase, stable unit/token, process
generation/fence and evidence digest before accepting another mutation. It
SHALL adopt one matching live instance, prove absence before retrying the
identical invocation, perform verified fenced teardown before rollback, or
stop as `reconciliation_required`; it SHALL NOT infer absence from a missing
receipt or overwrite ambiguous state.

Current selectors SHALL be retained indefinitely. Operation/process/evidence
records SHALL remain for at least the longer of 90 days, the rollback support
window and every referencing bridge's compatibility window. Referenced or
unresolved records SHALL not be collected.

#### Scenario: The controller loses the CAS response
- **WHEN** selector publication committed but the controller crashes or loses the response before recording the next phase
- **THEN** retrying the same operation ID returns the same committed revision and reconciliation continues without a second selector transition

#### Scenario: The controller crashes after selector commit
- **WHEN** the selector references the target revision but no matching process-start receipt exists
- **THEN** reconciliation first resolves the stable deployment-unit identity and invocation token, adopts a matching live instance or proves absence before retry, and admits neither a duplicate runtime owner nor an unrelated activation

#### Scenario: Spawn succeeds but its response is lost
- **WHEN** the service manager spawns the target and fails before returning or persisting `process_started`
- **THEN** recovery finds and adopts the one process matching the durable intent, or performs verified fenced teardown before rollback; it never starts the predecessor or a second target concurrently

#### Scenario: Selector state is corrupt
- **WHEN** the current selector, phase receipt or process receipt is malformed, digest-mismatched, symlinked, oversized or internally inconsistent
- **THEN** mutation stops, the predecessor bytes are preserved, status reports invalid control state and no automatic repair or generation guess occurs

### Requirement: Concrete authority changes SHALL have digest-bound implementation children

This parent SHALL implement only additive package-discovery proof, immutable
read-only evidence vocabulary/validators, deterministic source
inventory/authority guards and read-only diagnostics. Selector CAS, mutable
operation journals, start-intent/service-manager protocols, reconciliation
transitions, retention commands and slice-specific activation/compensation
plans SHALL be implemented and versioned only by
`layout-selector-control-plane`. Native activation, each owner-ready
Python transfer, SDK/notebook transfer, ASGI/Bootstrap transfer, frontend
physical/default transfer and test/tool topology mutation SHALL each use the
mandatory implementation child class defined by the design.

Each child SHALL freeze before code its exact files/exports, prerequisite and
source SHAs, consumer/tree index, authority and generation refs, selector
expectations, activation/rollback argv, performance baseline, focused topology
and rollback proof. It SHALL pass its own six-role review and strict design
approval.

#### Scenario: A new owner-ready module is selected after parent approval
- **WHEN** an implementation proposes a concrete module not frozen in a strictly approved owner-slice child
- **THEN** no source move, forwarder or authority record may be implemented under the parent digest

#### Scenario: A frontend move and default switch are proposed together
- **WHEN** physical workspace movement and deployment default activation do not have independently reversible reviewed generations
- **THEN** the combined change is rejected even if frontend tests pass

#### Scenario: Plugin, MCP or remote-worker code is proposed
- **WHEN** an implementation introduces plugin entry points, MCP transports or remote-worker protocol dependencies without a strict-approved `optional-interface-extension-boundary` child
- **THEN** package discovery, dependency guards and compatibility forwarders reject the change and no optional handler is registered

### Requirement: Layout status SHALL be read-only, typed and actionable

The additive `./trade dev layout-status [--json]` command SHALL read only
selected deployment control/evidence records and source manifests. It SHALL not access a
provider, business DB, parquet, repair, build, activate or roll back. Its
versioned JSON SHALL expose generation and selector identities, evidence and
inventory refs, bridge coverage, orthogonal state fields, exit code, partial
evidence and operator action without credentials, user data or stack traces.
One invocation SHALL read at most 32 explicitly referenced regular records,
follow at most eight reference levels, admit at most 256 KiB per canonical
JSON record and 4 MiB in aggregate, and finish read/validation within a
five-second monotonic deadline. It SHALL NOT walk directories, scan repository
history, enumerate `/proc` or service-manager state, follow symlinks or probe
live processes. A limit breach SHALL return exit `2`.

`reconciliation_state` SHALL be the closed enum `not_required`, `pending`,
`adopted`, `absence_proved`, `fenced_teardown`, `required` or `failed`.
`pending` SHALL bind one consistent unfinished operation. `adopted` SHALL bind
exactly one live instance to the durable intent, token, generation, revision
and fence. `absence_proved` SHALL reject a live instance or unsuperseded
`process_started`; it MAY include a historical `process_started` only when a
causally later terminal receipt binds the same operation, deployment unit,
token, generation, revision and fence and proves no live descendant remains.
`fenced_teardown` SHALL bind the stale fence, complete
shutdown receipt and zero residue. `required` SHALL identify a contradiction,
deadline miss or ambiguous external result without claiming recovery.
`failed` SHALL bind a terminal unsuccessful reconciliation attempt. The parent
diagnostic SHALL only validate and report these immutable outcomes; it SHALL
not perform adoption, retry, teardown, repair or selector mutation.

`LayoutStatusConstraintsV1` SHALL be the versioned, dependency-free legality
and derivation oracle. It SHALL classify every declared value of every state
axis as `healthy` or `valid_attention`, validate the complete
reconciliation-to-migration/execution/failure/rollback/startup constraint
table and its receipt predicates, and classify unknown values or failed
cross-axis predicates as `invalid`. `operator_action` SHALL be uniquely
derived by the versioned priority table; it SHALL distinguish
`resume_reconciliation`, `retry_identical_invocation` and
`execute_reviewed_rollback`. A supplied action that differs from the derived
one SHALL be invalid.

The per-axis classification SHALL be:

- migration: `retireable` is healthy; every other declared migration value is
  attention;
- execution: `passed` is healthy; `not_run`, `running`, `failed` and `stopped`
  are attention;
- failure: `none` is healthy; every other declared failure class is attention;
- rollback: `not_required` and `succeeded` are healthy; `ready`, `requested`,
  `running`, `failed` and `unknown` are attention;
- startup: `started_healthy` is healthy; `not_started`, `starting`,
  `started_degraded`, `failed` and `stopped` are attention;
- reconciliation: `not_required` and `adopted` are healthy; `pending`,
  `absence_proved`, `fenced_teardown`, `required` and `failed` are attention.

The reconciliation constraint sets SHALL be:

- `pending`: migration `inventoried|prepared|shadow_verified`, execution
  `not_run|running|stopped`, rollback `not_required`, startup
  `not_started|starting|started_healthy|started_degraded|stopped`;
- `adopted`: migration
  `prepared|shadow_verified|legacy_forwarding|target_authoritative`, execution
  `running|passed`, rollback `not_required`, startup
  `started_healthy|started_degraded`;
- `absence_proved`: migration `inventoried|prepared|shadow_verified`,
  execution `not_run|stopped`, rollback `not_required`, startup
  `not_started|stopped`;
- `fenced_teardown`: migration `prepared|shadow_verified`, execution
  `stopped`, rollback `ready`, startup `stopped`;
- `required|failed`: migration `inventoried|prepared|shadow_verified`,
  execution `failed|stopped`, any declared rollback value and any declared
  startup value;
- `not_required`: any declared value that satisfies the generic predicates.

`pending`, `adopted`, `absence_proved` and `fenced_teardown` SHALL require
`failure_class=none`; `required|failed` SHALL require their declared non-none
reconciliation failure classes. `execution_state=passed` SHALL require
`failure_class=none`, and a non-none failure SHALL NOT coexist with `passed`.
`target_authoritative|retireable` SHALL require execution `passed`, failure
`none`, rollback `not_required` and reconciliation `not_required|adopted`.
Every product of declared values satisfying these generic predicates and its
reconciliation constraint set SHALL be valid; implementations SHALL NOT add
unversioned local allow/deny rules.

`operator_action` SHALL be one of `none`, `wait`, `continue_validation`,
`resume_reconciliation`, `retry_identical_invocation`,
`repair_prerequisite`, `narrow_slice`, `execute_reviewed_rollback` or
`investigate`. The first matching rule SHALL derive it: reconciliation
`required|failed` maps unavailable prerequisite to `repair_prerequisite` and
all other allowed failures to `investigate`; then `fenced_teardown` maps to
`execute_reviewed_rollback`; `absence_proved` to
`retry_identical_invocation`; `pending` to `resume_reconciliation`; remaining
unavailable prerequisite to `repair_prerequisite`; capacity refusal to
`narrow_slice`; any other failure, rollback `failed|unknown` or startup
`started_degraded|failed|stopped` to `investigate`; rollback `ready` to
`execute_reviewed_rollback`; rollback `requested|running`, execution `running`
or startup `starting` to `wait`; any remaining attention value to
`continue_validation`; and an all-healthy report to `none`.

Exit aggregation SHALL be total and order-independent: any `invalid` result
returns `2`; otherwise any `valid_attention` value returns `1`; otherwise all
values are `healthy` and the report returns `0`. Human and JSON output SHALL
expose identical enum, uniquely derived action and exit semantics. The
rollback action SHALL reference only the scope-specific reviewed plan. For a
`python_deployment` with later accepted slices, a historical predecessor
target SHALL be invalid; the plan SHALL name a newly verified successor from
the current composition.

#### Scenario: An operator inspects a failed cutover
- **WHEN** layout status reads a valid evidence manifest with a timeout and successful rollback
- **THEN** it reports the timeout and rollback independently, names the active reviewed rollback target plus predecessor lineage and returns exit 1 with the uniquely derived operator action

#### Scenario: Status evidence is malformed
- **WHEN** a selector or digest does not match the evidence schema
- **THEN** the command performs no repair, returns exit 2 and identifies the invalid evidence class without leaking raw payloads

#### Scenario: A lost spawn response is reconciled by adoption
- **WHEN** immutable evidence contains exactly one process matching the durable intent, invocation token, generation, revision and fence and records `reconciliation_state=adopted`
- **THEN** layout status reports adoption without starting or stopping a process, and it returns exit 0 only when every other independent state is successful

#### Scenario: Reconciliation needs operator investigation
- **WHEN** valid evidence records a selector/process fence contradiction as `reconciliation_state=required`, a non-none reconciliation failure class and `operator_action=investigate`
- **THEN** human and JSON output preserve those values, return exit 1 and perform no repair or mutation

#### Scenario: A reconciliation state product is forbidden
- **WHEN** evidence uses an unknown reconciliation enum, claims `adopted` without one matching process receipt, combines `absence_proved` with a live or unsuperseded matching process-start receipt, claims `fenced_teardown` with residue, combines `required` or `failed` with passed/authoritative/retireable state, supplies a non-derived action, or targets a historical Python predecessor that would remove a later accepted slice
- **THEN** validation rejects the report, returns exit 2 and does not reinterpret the record as a valid operator-recoverable state

#### Scenario: A historical process start is superseded by absence proof
- **WHEN** one historical `process_started` receipt is followed by a bounded terminal receipt with the exact same operation, deployment unit, invocation token, generation, revision and fence and zero live descendants
- **THEN** `absence_proved` is a valid attention state with action `retry_identical_invocation`; a missing, mismatched or nonterminal superseding receipt is invalid

#### Scenario: Finite state products are exhaustively classified
- **WHEN** the pure legality oracle enumerates every declared state-axis value product
- **THEN** each product has exactly one healthy, attention or invalid classification, one derived action and one exit result independent of evaluation order; representative human and JSON goldens match the oracle

### Requirement: Package and layout operations SHALL not access real business data

Source audit and package/layout validation SHALL not open real business data or provider state.
Package builds, wheel installs, Web builds, import tests and layout guards
SHALL not open real DB, parquet, manifest, pointer or provider
state. Tests SHALL use temporary roots and explicit fake or immutable fixtures.

#### Scenario: A compatibility smoke tries to initialize TradeDB
- **WHEN** package, import or route-registration validation opens a real or default data root
- **THEN** the guard fails the test and requires dependency injection or a temporary fixture before continuing

#### Scenario: A Web route requires data for its golden
- **WHEN** contract validation needs representative payload state
- **THEN** it uses the frozen temporary fixture generation and does not repair, backfill or refresh real data
