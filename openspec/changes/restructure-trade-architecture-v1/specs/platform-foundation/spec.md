## ADDED Requirements

### Requirement: Platform persistence and events SHALL precede Context extraction

Platform SHALL provide a minimal public persistence and events foundation
before Capture, Datasets, Studies or Decision Support owns a new durable
transition. The
foundation. The foundation SHALL provide a context-local transaction port that
atomically commits the owner's aggregate transition, immutable receipt/audit
record and outbox record; it SHALL NOT provide a business repository or a
cross-context transaction. The foundation SHALL also provide durable command
ingress idempotency, consumer inbox/receipt deduplication, lease/ack recovery,
ordered delivery policy, bounded retry and a dead-letter/redrive record.

#### Scenario: A process dies after a context transaction commits

- **WHEN** Capture, Datasets, Studies or Decision Support commits local state,
  audit evidence and an outbox record, and the dispatcher dies before consumer
  acknowledgement
- **THEN** a later dispatcher lease recovery delivers the same immutable
  envelope to an inbox-deduplicated consumer, records exactly one effective
  consumer receipt and does not repeat the context transition

#### Scenario: Delivery exhausts its policy

- **WHEN** an outbox envelope exceeds its declared retry, ordering or deadline
  policy
- **THEN** Platform records a bounded dead-letter entry with correlation,
  causation, payload digest and failure reason, requires an audited redrive
  command, and never drops or silently reorders the envelope

### Requirement: Artifact commit visibility SHALL be crash-recoverable

Capture SHALL use a prepare, verify, commit-marker and receipt protocol for
artifact bytes stored outside the context database. A receipt/outbox record
SHALL reference only a verified committed artifact. Startup reconciliation SHALL
classify prepared, orphaned, digest-mismatched and receipt-without-artifact
states deterministically, preserve diagnostics and either safely recover or
quarantine them without publishing an ambiguous reference.

#### Scenario: The runtime fails between raw-byte staging and receipt commit

- **WHEN** a Capture worker stages raw bytes and crashes before the context
  receipt transaction commits
- **THEN** reconciliation identifies the staged artifact as prepared or
  orphaned, performs no Dataset publication, and records an idempotent
  recovery or quarantine outcome before the request may be retried

#### Scenario: The database receipt exists but artifact verification fails

- **WHEN** recovery resolves a committed Capture receipt whose referenced
  artifact is absent or whose digest differs from the recorded digest
- **THEN** the receipt is marked integrity-failed or quarantined, all formal
  downstream consumption is blocked, and recovery preserves the mismatch
  evidence rather than substituting another artifact

### Requirement: Migration startup SHALL be coordinated and mixed-version safe

Platform Persistence SHALL provide a `DatabaseRuntime` and
`MigrationCoordinator` that select explicit read-only, compatible-writer or
migration-leader startup modes. A migration leader lock, schema capability
generation and supported minimum/maximum generation SHALL fence incompatible
writers. Context migration registration SHALL remain context-owned, while the
coordinator runs registrations in a declared dependency order. The legacy
`TradeDB` facade SHALL delegate through compatible context repositories during
the transition and SHALL NOT initialize or migrate all business domains as an
implicit side effect.

#### Scenario: Two binary generations start against one SQLite database

- **WHEN** a process with an older supported generation and a process requiring
  a newer migration generation start concurrently
- **THEN** only the elected migration leader may change schema, an incompatible
  writer is rejected or starts read-only with a stable reason code, and no
  mixed-generation business write is accepted outside the compatibility range

#### Scenario: A context migration is interrupted

- **WHEN** a registered context migration stops before its checkpointed replay
  or compatibility bridge is ready
- **THEN** the coordinator records the checkpoint and capability state, the
  old compatible reader remains available, and a retry resumes idempotently
  without reapplying destructive work

### Requirement: Platform composition SHALL have one explicit Bootstrap owner

`bootstrap` SHALL be the only production composition root for CLI, Web,
worker, scheduler and native lifecycle assembly. It SHALL wire concrete
repositories, adapters, Platform implementations, context use cases and
Process Managers through declared capabilities. Existing `trade_py` and
`trade_web` construction paths SHALL remain compatibility shims until their
selected entrypoints are delegated; no Interface child may create a second
runtime container or bypass Bootstrap.

#### Scenario: An HTTP route is migrated to a new BFF

- **WHEN** an existing FastAPI route is delegated to an Interfaces BFF
- **THEN** the BFF obtains a query/use-case handle from Bootstrap, does not
  instantiate a `TradeDB`, EventBus, provider client or native binding itself,
  and preserves its legacy route contract through the compatibility adapter
