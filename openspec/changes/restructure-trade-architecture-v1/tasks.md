## 1. Governed Architecture Design

- [x] 1.1 Audit current repository structure, `AGENTS.md`, OpenSpec workflow,
  CLI facade, Python packaging, Web routes/pages, EventBus, database/schema,
  artifact stores, Observatory/PIT, notebooks and C++ boundary without mutating
  real data. Objective: establish code facts rather than rely on historic
  documents. Inputs: current source tree and OpenSpec policy. Outputs:
  current-state inventory and ownership evidence in `design.md`. Affected
  contracts: all retained public surfaces. Validation: source-only audit and
  `git status -sb` preservation check. Rollback: none because no runtime state
  changes. Completion evidence: audited paths and findings cited in
  `design.md`. [validation:test]

- [x] 1.2 Write proposal, Design Quality Brief, target architecture, dependency [validates:architecture.boundaries] [validation:test]
  graph, runtime diagrams, compatibility matrix, ownership map, risks, rollback
  and child-change plan. Objective: create an implementation-independent design
  baseline. Inputs: audited facts and `design-policy/v1.toml`. Outputs:
  governed OpenSpec proposal, design and eight capability specs. Affected
  contracts: architecture and dependency rules. Validation: OpenSpec scenario
  and Design Quality Brief completeness check. Rollback: edit only governed
  design artifacts before review. Completion evidence: required artifacts exist
  under the change directory. [validates:architecture.boundaries]
  [validation:test]

- [x] 1.3 Run `./trade dev design-check restructure-trade-architecture-v1` [validates:architecture.boundaries] [validates:migration.governance] [validation:test]
  restructure-trade-architecture-v1`, resolve deterministic blockers and assign
  every warning to design, task or explicit future follow-up. Objective: make
  the initial design evidence machine-valid. Inputs: proposal, design, specs,
  tasks and quality declaration. Outputs: passing non-strict report. Affected
  contracts: migration governance and architecture boundaries. Validation:
  design-check output and `git diff --check`. Rollback: correct only the
  governed artifacts; no source/data rollback exists. Completion evidence:
  zero blocker report saved in the design review record. [validates:architecture.boundaries]
  [validates:migration.governance] [validation:test]

- [ ] 1.4 Run the required six-role design review from an isolated review
  worktree and synthesize architecture, reliability, performance, data-quality,
  observability and news/future findings. Objective: challenge the design
  before strict approval. Inputs: frozen design artifact generation and real
  code references. Outputs: consensus report and candidate `design-review.toml`
  evidence. Affected contracts: all architecture capabilities. Validation:
  review evidence contains file/line findings, consensus counts and P0/P1/P2
  disposition. Rollback: discard review-only worktree; no production state is
  changed. Completion evidence: six judge reports and a synthesized finding
  list. [validation:review]

- [ ] 1.5 Resolve every P0 and material P1 design finding, refresh the
  non-strict design check, record digest-bound review approval and run strict
  design-check. Objective: make the architecture implementable but still
  design-only. Inputs: review consensus and current artifact digest. Outputs:
  approved `design-review.toml` and strict result. Affected contracts: all
  architecture capabilities. Validation: `./trade dev design-check
  restructure-trade-architecture-v1 --strict`. Rollback: revise governed
  artifacts and repeat review when the digest changes. Completion evidence:
  strict exit code zero and zero unresolved P0. [validation:review]

## 2. Foundational Prerequisites for Child Changes

- [ ] 2.1 Prepare `architecture-guardrails-and-baselines` as an independent [validates:architecture.boundaries] [validates:dependency.guardrails] [validation:test]
  child OpenSpec change. Objective: define static import guard, contract type
  leakage guard, DB-owner guard and baseline inventories before any module
  extraction. Inputs: dependency graph, current imports and table inventory.
  Outputs: scoped child proposal/tasks and baseline test plan. Affected
  contracts: context imports and table ownership. Validation: proposed
  architecture test validates allowed/forbidden import samples and DB owner
  fixtures. Rollback: remove only guardrail additions if they prove invalid; do
  not alter existing source ownership. Completion evidence: child scope maps
  each rule to a current path and a test fixture. [validates:architecture.boundaries]
  [validates:dependency.guardrails] [validation:test]

- [ ] 2.2 Prepare `platform-persistence-events-and-bootstrap-foundation` as [validates:platform.foundation] [validates:processes.recovery] [validates:migration.governance] [validation:test]
  an independent prerequisite child OpenSpec change. Objective: supply the
  transaction/outbox port, command ingress/OperationReceipt, inbox/lease/ack/
  DLQ delivery, EventBus bridge, DatabaseRuntime/MigrationCoordinator,
  verified backup restore and Bootstrap composition before any Context relies
  on cross-context delivery. Inputs: EventBus, `TradeDB`, migrations, runtime
  resources and backup audit. Outputs: generic public APIs, compatibility
  bridge, crash/mixed-version/restore fixture plan and capacity envelope.
  Affected contracts: event envelope, persistence transaction, operation
  receipt, migration capability and runtime composition. Validation:
  crash-after-commit, duplicate ingress, inbox dedup, lease recovery, DLQ,
  mixed-binary fence, staged corrupted-backup rejection and 1x/10x backlog
  tests. Rollback: select the legacy EventBus/TradeDB construction bridge
  without deleting outbox, receipt or restore evidence. Completion evidence:
  no Context child has to invent an atomic outbox, command handoff or runtime
  container. [validates:platform.foundation] [validates:processes.recovery]
  [validates:migration.governance] [validation:test]

- [ ] 2.3 Prepare `kernel-and-public-contracts` and [validates:architecture.boundaries] [validates:datasets.products] [validates:studies.reproducibility] [validation:test]
  `formal-pit-and-revision-semantics` as ordered independent prerequisite
  child changes. Objective: establish only justified Kernel/DTO types, then
  make required clocks fail closed and implement real as-known/latest-restated
  mapping before a formal SnapshotRef or Study migration. Inputs: existing
  ArtifactRef, SnapshotContext, PIT resolver and research workflow audit.
  Outputs: versioned DTO/policy catalog, PIT/revision contract and golden
  fixture plan. Affected contracts: DatasetSnapshotRef, policy refs,
  StudyResultRef and evidence-gap event. Validation: contract serialization,
  forbidden-type guard, raw-input rejection, null-clock/revision goldens,
  insufficient-data and deterministic rerun tests. Rollback: retain legacy
  non-formal reader and block formal release/run rather than expose an
  unproven snapshot. Completion evidence: child proposals explicitly classify
  reusable versus fold-local feature ownership and prove no missing clock is
  visible. [validates:architecture.boundaries] [validates:datasets.products]
  [validates:studies.reproducibility] [validation:test]

- [ ] 2.4 Prepare `cli-http-sdk-compatibility` as an independent child OpenSpec [validates:interfaces.compatibility] [validates:platform.foundation] [validation:test]
  change. Objective: freeze actual CLI help/parse/exit behavior, HTTP/OpenAPI/
  SSE route behavior, Web BFF payloads, Observatory capability semantics and
  notebook entry contracts before delegation. Inputs: root `trade`, CLI
  registries, FastAPI route inventory, React API consumers and current
  notebook. Outputs: compatibility matrix and snapshot fixture plan. Affected
  contracts: all retained interfaces. Validation: CLI, OpenAPI/SSE, BFF,
  ProcessView/ErrorEnvelope and SDK contract snapshot tests against temporary
  roots. Rollback: keep legacy
  interface adapter selected until snapshot parity returns. Completion evidence:
  each legacy entrance has a named adapter and retirement condition.
  [validates:interfaces.compatibility] [validates:platform.foundation]
  [validation:test]

## 3. Durable Product and Research Migration Preparation

- [ ] 3.1 Prepare `capture-boundary` implementation readiness for a pilot [validates:capture.receipts] [validates:platform.foundation] [validates:migration.governance] [validation:test]
  source after the Platform foundation and its child design are strictly
  approved. Objective: document context-owned capture tables/artifacts,
  SourceManifest rights/temporal/finality policy, provider ports,
  stage/digest/commit reconciliation, checkpoint/retry/quarantine/redrive
  policy and compatibility bridge without moving implementation in this parent
  change. Inputs: child contract, source rights audit and crypto run-store
  audit. Outputs: migration slice, additive schema plan, retention/tombstone
  plan, capacity envelope and capture fixture matrix. Affected contracts:
  CaptureArtifactRef and existing source commands. Validation: temporary-root
  replay, supersession, stream segment, no-provider replay, rights revocation,
  absent publication time, commit crash and 1x/10x admission tests defined in
  the child. Rollback: previous capture adapter and immutable prior artifacts.
  Completion evidence: child change has an owned migration/rollback design,
  policy digest and code worktree plan. [validates:capture.receipts]
  [validates:platform.foundation] [validates:migration.governance]
  [validation:test]

- [ ] 3.2 Prepare `dataset-product-boundary` as an independent child OpenSpec [validates:datasets.products] [validates:migration.governance] [validation:test]
  change. Objective: define canonical build/version/snapshot/release, quality,
  lineage, canonicalization/quality policy refs, QueryBudget, catalog rebuild
  and generation-stamped legacy pointer bridge for the same pilot source.
  Inputs: proven PIT/revision contract, Capture artifact contract, crypto run
  store and warehouse/catalog audit. Outputs: Dataset repository/migration/
  projection plan and MigrationReconciliationManifest schema. Affected
  contracts: DatasetVersionRef, DatasetSnapshotRef, quality/PIT query.
  Validation: lineage, source reconciliation, catalog rebuild, immutable build
  input, physical query-budget, pointer reconciliation and rollback fixtures.
  Rollback: restore verified prior release pointer and retain the newer
  immutable version for audit. Completion evidence: child proposal identifies
  the one Datasets transaction boundary per state transition and cannot release
  a SnapshotRef without formal PIT proof. [validates:datasets.products]
  [validates:migration.governance] [validation:test]

- [ ] 3.3 Prepare `study-boundary` implementation readiness after Dataset [validates:datasets.products] [validates:studies.reproducibility] [validation:test]
  contracts and the formal PIT/revision gate exist. Objective: specify one
  Study's preregistration, proven pinned snapshot input, feature
  classification, validation, promotion, stale result and evidence-gap flow.
  Inputs: Dataset snapshot/policy contract and current research workflow audit.
  Outputs: Study lifecycle migration plan and golden fixture matrix. Affected
  contracts: StudyResultRef and Decision Support read inputs. Validation: PIT
  proof rejection, raw-input rejection, deterministic rerun, revision
  staleness and insufficient-data tests. Rollback: preserve prior research
  query path and expose new outputs as unpublished/stale. Completion evidence:
  child proposal declares all metrics, horizon and unavailable semantics.
  [validates:datasets.products] [validates:studies.reproducibility]
  [validation:test]

- [ ] 3.4 Prepare `tests-and-legacy-cleanup` migration rehearsal criteria. [validates:migration.governance] [validation:test]
  Objective: define additive schema/version, old reader preservation,
  idempotent replay/shadow-copy, dual-read comparison, pointer switch and
  retirement checks for all later children. Inputs: table/artifact ownership map
  and platform backup behavior. Outputs: migration test harness and rollback
  checklist design. Affected contracts: SQLite/parquet readers, release
  pointers and legacy imports. Validation: migration rollback, old/new reader,
  reconciliation manifest, artifact digest, staged verified backup restore,
  protected-reference retention and projection rebuild tests. Rollback:
  restore previous generation or verified backup snapshot without deleting
  immutable records. Completion evidence: every durable child has a selected
  migration mode, mixed-version fence and rollback source.
  [validates:migration.governance] [validation:test]

## 4. Runtime and Interface Orchestration Preparation

- [ ] 4.1 Prepare `process-manager-boundary` after the Platform foundation as [validates:studies.reproducibility] [validates:processes.recovery] [validates:platform.foundation] [validation:test]
  an independent child OpenSpec change. Objective: define durable Process
  records and the normal refresh, evidence-gap, revision propagation,
  registered study, publication request, projection and daily workspace flows
  over the existing command/outbox substrate. Inputs: Platform foundation,
  EventBus/runtime/job/agenda audit and Context contracts. Outputs: process
  state schema, ActorContext/OperationReceipt/ProcessView, idempotency/
  deadline/compensation policy and temporary-root recovery fixtures. Affected
  contracts: commands, events, process receipts and schedule envelopes.
  Validation: duplicate delivery, crash-after-commit, inbox/lease recovery,
  partial fan-out, deadline, cancellation, DLQ redrive and replay tests.
  Rollback: disable new process command while retaining pending outbox/process
  facts for compatible recovery. Completion evidence: each process maps every
  step to a context command, `PublishDataset` remains a Datasets transaction,
  and there is no cross-context transaction. [validates:studies.reproducibility]
  [validates:processes.recovery] [validates:platform.foundation]
  [validation:test]

- [ ] 4.3 Prepare interface composition migration slices. Objective: select [validates:processes.recovery] [validates:interfaces.compatibility] [validation:test]
  low-risk CLI/HTTP/Web/SDK surfaces and route them through read-only query
  handles or command receipts, preserving existing compatibility adapters.
  Inputs: compatibility snapshots and Process/Platform contracts. Outputs:
  per-surface BFF/adapter sequence for Today, Observatory, Research, Data Ops
  and Operations before broader pages. Affected contracts: route payloads,
  SSE, page state and command receipts. Validation: BFF contract, GET
  read-only guard, bounded query, 1x/10x BFF/SSE shared-hub slow-client and
  compatibility snapshot tests. Rollback: route to the legacy adapter without
  removing URL/payload aliases. Completion evidence: no selected interface
  module directly queries an owner table, provider or lifecycle pointer, and
  unavailable/process errors map through the versioned compatible envelope.
  [validates:processes.recovery]
  [validates:interfaces.compatibility] [validation:test]

## 5. Final Design Approval and Handoff

- [ ] 5.1 Reconcile the approved architecture with all compatibility and [validates:interfaces.compatibility] [validates:dependency.guardrails] [validates:platform.foundation] [validation:test]
  dependency baselines. Objective: ensure the child-change order has no hidden
  import, table-owner or interface dependency. Inputs: completed design review,
  contract inventories and task graph. Outputs: final child-change ordering and
  named compatibility windows. Affected contracts: dependency guards and
  retained interfaces. Validation: architecture/import/contract snapshot
  review and `git diff --check`. Rollback: revise this architecture design and
  repeat review; no production changes are in scope. Completion evidence:
  every child can be implemented and rolled back independently, the Platform
  foundation precedes Context outbox use, and formal PIT semantics precede
  formal SnapshotRef/Study migration. [validates:interfaces.compatibility]
  [validates:dependency.guardrails] [validates:platform.foundation]
  [validation:test]

- [ ] 5.2 Record digest-bound six-role design consensus and strict approval. [validates:migration.governance] [validates:platform.foundation] [validation:review]
  Objective: formally gate implementation until the current design is
  approved. Inputs: current artifact digest, non-strict report and six judges'
  file/line evidence. Outputs: `design-review.toml`, strict gate report and
  final status. Affected contracts: all migration governance obligations.
  Validation: consensus review resolves every P0, assigns material P1 items,
  then `./trade dev design-check restructure-trade-architecture-v1 --strict`
  exits zero. Rollback: alter governed artifacts only, regenerate the digest
  and repeat review if evidence changes. Completion evidence: six approved
  roles, zero P0 and a current strict approval record.
  [validates:migration.governance] [validates:platform.foundation]
  [validation:review]
