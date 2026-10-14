## ADDED Requirements

### Requirement: Command ingress SHALL durably admit one operation identity

After the explicit prerequisite gate passes, Platform command ingress SHALL accept
only the framework-free Kernel `CommandEnvelope[T]` carrying a trusted
`ActorContext`, correlation and causation identities, canonical command fingerprint,
scoped idempotency fingerprint and finite monotonic deadline from Kernel V21
candidate commit `3cdb25e0ad8a377d8ece0469333a582700f5bf2b` and portable artifact
digest
`sha256:a7ec722f8e922cdc8630920a771b7a43a0945c0e765dd2347ac51c7bd316e75b`.
The owning ingress repository SHALL use that exact generation's bounded
key-generation admission algorithm.
One admission SHALL share the command's remaining monotonic deadline across at most
three claim attempts, each with at most one claim transaction, plus at most one
separate refusal-audit transaction after the final claim attempt ends. A generation
change SHALL roll back and end the current claim attempt; candidate re-derivation
SHALL occur only in a later attempt. A stable claim transaction SHALL either:

- create one immutable operation identity plus initial `OperationReceipt` and owner
  command outbox record;
- return the existing receipt for a command-equivalent duplicate; or
- produce a provisional conflict, corrupt-claim or contention refusal without
  fabricating an operation.

Ingress SHALL return a provisional refusal only after its bounded refusal audit
commits within the same remaining deadline. When no audit-start/commit budget remains
or that transaction fails, `IDEMPOTENCY_AUDIT_UNAVAILABLE` SHALL take precedence.
Neither path SHALL create a claim, operation, receipt, dispatch, retry or background
continuation. A deadline exhausted before any provisional conflict, corruption or
contention outcome exists SHALL return the approved Kernel deadline result. Once such
a provisional refusal exists, deadline expiry before its audit commits SHALL return
exactly `IDEMPOTENCY_AUDIT_UNAVAILABLE`; it SHALL NOT fall back to the provisional
reason or a generic deadline result.

Every claim and refusal-audit transaction SHALL set SQLite busy/lock wait to no more
than the remaining monotonic budget, recheck that budget immediately after acquiring
the write lock and immediately before commit, and roll back when exhausted.
Precomputation and key derivation SHALL occur before the write lock. The selected
`CapacityProfile` SHALL bound statements, rows, write-lock hold time and jittered
retry delay below the operation deadline. Refusal telemetry SHALL be one best-effort
safe structured event plus one low-cardinality counter carrying owner, stable outcome
family and telemetry-emission outcome; telemetry failure SHALL neither retry nor
change the caller result.

Ingress SHALL NOT synchronously execute a Context use case, call a provider, dispatch
an in-memory handler, expose raw command payload/idempotency secret or keep an HTTP,
CLI or scheduler caller attached to the eventual workflow. A formal
`OperationReceipt` SHALL not be derived from legacy `job_runs` or PID admission.

#### Scenario: The same command is admitted twice
- **WHEN** an actor repeats an equivalent command under the same scoped idempotency identity
- **THEN** ingress returns the first durable `OperationReceipt`, emits no second command outbox record and performs no second Context transition

#### Scenario: The identity is reused for another command
- **WHEN** the scoped idempotency identity resolves to a different canonical command fingerprint
- **THEN** ingress returns `IDEMPOTENCY_COMMAND_CONFLICT` without an operation identity, command payload or raw key

#### Scenario: The caller deadline expires before admission commits
- **WHEN** the shared monotonic deadline is exhausted before durable admission and before any provisional refusal exists
- **THEN** ingress returns the approved Kernel deadline result, rolls back the claim attempt and leaves no operation, receipt or dispatch

#### Scenario: The write lock outlives the admission budget
- **WHEN** another connection holds the SQLite write lock until the remaining monotonic admission budget expires
- **THEN** the waiting transaction stops within that budget, commits no claim or refusal audit, starts no background continuation and returns the deadline or audit-unavailable result determined by whether a provisional refusal already existed

#### Scenario: Rotation changes generation in every attempt
- **WHEN** generation changes during each of the three claim transactions and the separate contention refusal audit commits within the remaining deadline
- **THEN** ingress returns `IDEMPOTENCY_KEYSET_CONTENTION` after no more than three claim transactions plus one refusal-audit transaction and creates no operation, receipt or background continuation

#### Scenario: Refusal audit has no remaining budget
- **WHEN** a conflict, corruption or contention claim attempt ends but the shared deadline cannot start and commit its audit
- **THEN** ingress returns `IDEMPOTENCY_AUDIT_UNAVAILABLE`, starts no additional transaction and does not report the provisional reason as durably recorded

### Requirement: Outbox dispatch SHALL use durable leases and bounded outcomes

Every outbox record SHALL contain envelope schema/version, message identity, owner
namespace, message kind and payload digest, correlation/causation, operation/process
links, ordering declaration, priority, not-before time, finite deadline, retry policy
reference, created time, an owner-declared opaque `delivery_class_ref`, an optional
opaque `delivery_constraint_ref`, and immutable payload bytes or an owner-verifiable
immutable payload reference. Platform SHALL not interpret business or rights
semantics in those references. A local adapter SHALL admit a record only when its
selected versioned `DeliveryCapacityProfile` proves the declared class and constraint
capabilities. The profile SHALL bound item/byte backlog, claim-scan rows,
claimed/inflight rows per ordering key and class, worker/queue concurrency, poison-key
cooldown, weighted or round-robin fairness, reserved control capacity and maximum
starvation interval. Saturation or a capability mismatch SHALL produce an explicit
reject, defer or unavailable receipt; one hot key or bulk class SHALL not consume
reserved control/correction capacity. A dispatcher SHALL claim a bounded batch using
an owner instance, fence generation, lease token and expiry through a bounded keyset
scan and the profile's deterministic fairness policy.

Delivery SHALL transition through the closed technical states `pending`, `leased`,
`delivered`, `retry_scheduled`, `dead_lettered` and `cancelled`. Lease renewal,
acknowledgement, retry scheduling and terminalization SHALL compare the lease token
and fence. A crash before acknowledgement SHALL make the record reclaimable after
proven lease expiry. Retry count, backoff, deadline and maximum elapsed age SHALL be
finite. No transient persistence error SHALL create an unbounded retry loop inside a
worker or shutdown call; unresolved terminal persistence SHALL retain a durable
technical owner/residual state for later recovery.

This V1 delivery contract SHALL mean direct local owner invocation and
acknowledgement only. A broker publish acknowledgement or remote-worker handoff
SHALL NOT be mapped to `delivered`, nor SHALL a remote adapter reuse this state
machine. Before such an adapter exists, a separate reviewed contract SHALL define
idempotent publication identity, adapter capability/version and constraint
attestation, durable handoff receipt, broker position/digest, reconciliation and an
end-to-end effective receipt.

#### Scenario: A dispatcher crashes after consumer execution starts
- **WHEN** the delivery lease expires without a committed acknowledgement
- **THEN** another fenced dispatcher may reclaim the same immutable envelope and inbox deduplication prevents a second effective consumer transition

#### Scenario: Retry budget is exhausted
- **WHEN** the next attempt would exceed attempts, elapsed age or envelope deadline
- **THEN** Platform records one dead-letter outcome with safe failure facts and does not silently drop, continue or relabel the message as delivered

#### Scenario: Terminal persistence remains unavailable
- **WHEN** the dispatcher cannot commit ack, retry or dead-letter state within its remaining deadline
- **THEN** it stops synchronous retry, preserves lease/residual ownership evidence and returns an explicit unavailable or incomplete result for reconciliation

#### Scenario: A bulk stream competes with control traffic
- **WHEN** one high-volume opaque delivery class fills its bounded backlog while a reserved control class is eligible
- **THEN** the deterministic scheduler preserves the declared control capacity and maximum starvation interval, rejects or defers excess bulk work, and records class-level bounded capacity evidence without inspecting either payload

#### Scenario: A future adapter reports broker acceptance
- **WHEN** an adapter has only a broker publication acknowledgement and no end-to-end effective local receipt
- **THEN** Platform refuses to mark the V1 record `delivered` and requires the separately approved remote-handoff contract

### Requirement: Inbox consumption SHALL make duplicate delivery ineffective

Before invoking an owner use case, a consumer adapter SHALL validate the envelope
schema, payload digest, target owner, message kind and deadline. The owner local
transaction SHALL insert or compare a durable inbox identity and atomically commit
the effective owner transition, owner audit/receipt, ordered-consumer head and
outgoing outbox. The inbox identity SHALL be `(consumer_effect_namespace,
message_id)`, where `consumer_effect_namespace` is an immutable owner-qualified
identity for one effective transition and is not an implementation, deployment or
schema version. It SHALL store target owner, message kind, schema, immutable payload
digest, first consumer contract version, effect-contract digest,
compatibility-policy digest and first effective receipt. The recorded compatibility
policy SHALL be immutable and addressable for the inbox retention period.
Compatibility SHALL be decided directionally from the immutable tuple
`(recorded_contract_version, current_contract_version, effect_contract_digest)` by
that recorded policy digest; a current policy replacement SHALL NOT reinterpret an
existing row. Missing recorded policy evidence SHALL quarantine the duplicate as
`consumer_compatibility_unverifiable`. Replacing a policy for existing effects SHALL
require an explicit owner migration receipt that preserves the old decision
evidence. Contract version and
compatibility-policy digest SHALL NOT participate in uniqueness.

An exact duplicate under the same contract version, or a duplicate whose current
consumer version declares the recorded version compatible through the pinned
owner compatibility policy and unchanged effect-contract digest, SHALL return the
existing receipt without invoking the transition. A duplicate identity with an
incompatible consumer version, another effect-contract digest, payload digest,
target, message kind or schema SHALL be quarantined as corruption. A compatible
binary upgrade SHALL preserve the effect namespace. An intentionally different
effect SHALL use a new owner-defined effect namespace and an explicit owner/process
migration; incrementing a version SHALL never reapply old messages. Handler code
SHALL not acknowledge outside the owner transaction and SHALL not embed
cross-Context orchestration.

#### Scenario: An exact message is delivered twice
- **WHEN** the same consumer receives the same message ID and payload digest after the first local commit
- **THEN** the second delivery returns the recorded inbox receipt and performs no owner write or child emission

#### Scenario: A compatible consumer binary is deployed
- **WHEN** a newer consumer contract version receives a message already applied by a recorded compatible version under the same effect namespace, effect digest and pinned compatibility policy
- **THEN** it returns the first receipt and performs no owner write even though the implementation version changed

#### Scenario: The current compatibility policy changed
- **WHEN** a duplicate arrives after the owner publishes a different current compatibility policy
- **THEN** the consumer evaluates the immutable recorded policy digest or fails closed when it is unavailable, and does not reinterpret or reapply the first effective transition

#### Scenario: A consumer changes effective semantics
- **WHEN** a consumer version is not compatible with the recorded effect contract or attempts to reuse its effect namespace for another effect digest
- **THEN** delivery quarantines the mismatch and does not treat a version change as permission to invoke the owner again

#### Scenario: A duplicate identity has different bytes
- **WHEN** a message ID already exists for the consumer but schema, target or payload digest differs
- **THEN** consumption fails closed to quarantine/dead-letter evidence and does not call the owner use case

#### Scenario: The owner transaction rolls back
- **WHEN** the Context invariant or outbox insertion fails before commit
- **THEN** inbox acknowledgement is absent, the delivery remains retryable under policy and no partial business state is visible

### Requirement: Ordering SHALL be explicit, durable and bounded

Every message SHALL declare either `unordered` or an `OrderingContractRef`. An
`OrderingContract` SHALL contain contract version/digest, producer namespace,
ordering scope/key digest, producer fence epoch, transactionally assigned positive
sequence, consumer expected sequence, duplicate/stale policy, finite gap timeout,
maximum buffered gap count/bytes and head-of-line failure policy.

The producer SHALL allocate sequence in the same local transaction as its outbox
record. An ordered consumer SHALL atomically compare/update its expected sequence with
the inbox receipt and owner transition. It SHALL not apply N+1 before required
handling of N. Duplicate/stale, gap, epoch regression and head-of-line expiry SHALL
produce explicit receipt, retry, quarantine, reconciliation or dead-letter outcomes.
No implementation SHALL keep the only gap state in process memory or allow one key
to monopolize all dispatcher capacity.

Dead-lettering sequence N SHALL retain the durable consumer head at N and SHALL NOT
make N+1 eligible. Redelivery of N SHALL create a new delivery attempt generation
while preserving N's original producer epoch and sequence. The head SHALL advance
only when N commits effectively or an authorized owner issues
`ResolveOrderingGap(expected_head=N, evidence_generation,
ordering_contract_digest, reason, deadline)`. A received immutable N that exhausts
delivery policy MAY create a dead-letter generation and MAY be redelivered. An N that
never arrived SHALL instead create an immutable `OrderingGapRecord` with ordering
contract, producer/key/epoch, expected sequence, first/last observation, timeout or
buffer evidence, reconciliation attempts, safe reason and its own gap generation; it
SHALL NOT fabricate a message ID, envelope, payload digest or dead letter and cannot
be redelivered. The command SHALL compare the current dead-letter generation for a
received N or gap generation for an absent N. It SHALL be allowed only when the pinned
head-of-line policy explicitly permits `skip_with_tombstone`; it SHALL compare-and-swap
the expected head and evidence generation and atomically append an immutable
`OrderingGapResolutionReceipt` before setting expected sequence to N+1. That receipt
is technical sequence evidence and SHALL NOT tombstone Capture content, rights or
lineage. Platform SHALL
reject the command when skip is forbidden, evidence changed, authorization is absent
or another resolution won. It SHALL never infer skip from timeout, DLQ presence or
operator query.

#### Scenario: N+1 arrives before N after restart
- **WHEN** durable expected sequence is N and N+1 is delivered first
- **THEN** the consumer records a bounded gap outcome, does not invoke the owner transition for N+1 and waits/reconciles only until the contract's finite limit

#### Scenario: A producer restarts with a stale epoch
- **WHEN** an outbox append presents an epoch lower than the durable producer fence
- **THEN** the append is rolled back and no duplicate sequence enters delivery

#### Scenario: A gap exhausts its policy
- **WHEN** N never arrives before the finite gap timeout or buffer budget
- **THEN** the head-of-line policy creates or advances an `OrderingGapRecord`, requests audited producer reconciliation, retains expected sequence N and does not invent a dead letter or silently apply N+1

#### Scenario: An ordered dead letter is redelivered
- **WHEN** an operator redelivers a received immutable sequence N that later entered the DLQ
- **THEN** a new attempt uses the original producer epoch and sequence N, and N+1 remains blocked until N commits effectively

#### Scenario: An owner resolves an allowed permanent gap
- **WHEN** the pinned ordering contract permits `skip_with_tombstone` and an authorized command matches expected sequence N and the current dead-letter or absent-gap generation
- **THEN** Platform atomically records one `OrderingGapResolutionReceipt`, advances expected sequence to N+1 once and exposes the skipped position and evidence kind in audit/status

### Requirement: Dead-letter and redelivery SHALL be explicit operator controls

A dead-letter record SHALL preserve message/envelope identity, owner and consumer,
correlation/causation, operation/process links, payload digest only, ordering
position, attempt/lease history summary, policy reference, terminal safe reason,
dead-letter time and eligible recovery actions. Payload bytes, credentials,
tracebacks and raw idempotency keys SHALL not enter list/status projections.

Redelivery SHALL require a new audited `RedeliverMessage` command with trusted actor,
reason, exact dead-letter identity, expected dead-letter generation and finite
deadline. It SHALL create a new delivery attempt linked to the immutable original;
it SHALL NOT modify the original payload, rewind a business aggregate, refetch an
external source or combine `redeliver_message` with
`replay_immutable_input`/`request_new_external_interaction`.
For an ordered message, redelivery SHALL preserve the original epoch and sequence and
SHALL NOT itself resolve the head. `ResolveOrderingGap` SHALL be a separate audited
owner-authorized command with the ordering restrictions above; generic DLQ operators
SHALL not receive implicit skip authority.

An `OrderingGapRecord` for a never-received sequence SHALL be listed by the ordering
gap query, not the DLQ query. It SHALL support reconciliation and authorized
resolution but SHALL never advertise redelivery because no immutable message exists.

#### Scenario: An operator inspects the DLQ
- **WHEN** an authorized Platform query lists dead letters
- **THEN** it returns bounded safe metadata and explicit recovery eligibility without payload content or automatic side effects

#### Scenario: Two operators redeliver concurrently
- **WHEN** both commands target the same dead-letter generation
- **THEN** compare-and-swap admits at most one new attempt and the other receives the existing receipt or a stable generation conflict

#### Scenario: A source must be contacted again
- **WHEN** recovery requires a fresh provider interaction rather than delivery of the original immutable message
- **THEN** Platform rejects `RedeliverMessage` for that purpose and requires the owning Process/Capture command path

### Requirement: Shutdown-link integrity signals SHALL have exactly one fenced delivery attempt

The Kernel SHALL remain the owner of the immutable shutdown-link corruption
identity, idempotency-key derivation and pure
`ShutdownLinkQueryResultV1`/`ShutdownLinkIntegrityObservationV1` values. Platform
Execution Operation Control SHALL be the sole writer of the integrity observation,
claim and terminal signal disposition. It SHALL use the Platform local transaction
and outbox participant without transferring ownership of the generic outbox table.
Platform Events SHALL deliver the admitted signal only through the dedicated
one-attempt capability described here and SHALL expose its bounded operator-health
projection.

For one exact safe corruption identity, the first composed query SHALL atomically
create or resolve one `ShutdownLinkIntegrityObservationV1` and one linked outbox
signal. Concurrent and repeated reads SHALL return that same observation and outbox.
Before any external delivery call, one owner transaction SHALL compare
`pending -> claimed`, bind the stable signal ID, current owner instance/fence,
trusted claim time, finite claim expiry and `attempt_count=1`. Only that live claim
MAY invoke one bounded external call. A stale owner/fence or second claim SHALL be
rejected before invocation.

The closed disposition graph SHALL be:

```text
pending -> claimed -> delivered
                   -> delivery_failed
                   -> delivery_outcome_unknown
```

A synchronous external result SHALL terminalize as `delivered` or
`delivery_failed`. A crash before claim leaves `pending` eligible for its first and
only claim. A crash, process disappearance or claim expiry after `claimed` but
before a terminal commit SHALL terminalize the same observation as
`delivery_outcome_unknown`. This dedicated signal SHALL NOT use ordinary
at-least-once `leased -> pending` recovery, generic retry scheduling, dead-letter
redelivery or a background continuation after claim. No automatic second external
call is permitted, including when it is unknown whether the first call was sent.

The composed query's corruption result remains unavailable regardless of signal
disposition. `delivery_failed` and `delivery_outcome_unknown` SHALL remain visible in
the authorized operator-health projection and SHALL not be reported as delivered,
healthy or retried. Any operator acknowledgement SHALL be a separate future
authorized contract and cannot rewrite this history.

The first observation transaction SHALL use the one trusted `UtcInstant` supplied
by the Kernel contract for both observation and error evidence. If trusted wall time
is unavailable, Platform SHALL return exactly
`SHUTDOWN_LINK_INTEGRITY_CLOCK_UNAVAILABLE`, create no observation/outbox and make no
signal call. If the observation/outbox transaction cannot commit under its finite
deadline, Platform SHALL return exactly
`SHUTDOWN_LINK_INTEGRITY_AUDIT_UNAVAILABLE`, with no receipt/observation/claim or
background work. Public/operator projections SHALL contain no credential, raw actor
evidence, payload, callback, exception text, path or mismatched field value.

#### Scenario: Two queries observe one corrupt shutdown link
- **WHEN** concurrent composed queries resolve the same exact safe corruption identity
- **THEN** one observation and one outbox signal exist, both queries return the unavailable corruption product, and at most one fenced claim can invoke externally

#### Scenario: The owner crashes before claiming the signal
- **WHEN** the observation/outbox committed but no `pending -> claimed` transaction committed
- **THEN** the same pending observation remains eligible for its first claim and no duplicate observation/outbox is created

#### Scenario: The process disappears after signal claim
- **WHEN** claim expiry is reached without a durable terminal result, whether before or after the external send
- **THEN** the observation becomes `delivery_outcome_unknown`, remains operator-visible and never triggers an automatic second external call

#### Scenario: The external delivery returns failure
- **WHEN** the one bounded call returns a synchronous failure
- **THEN** the observation terminalizes as `delivery_failed` without generic retry, DLQ redelivery or a healthy query result

#### Scenario: Integrity audit persistence is unavailable
- **WHEN** the first observation/outbox transaction cannot commit within its deadline
- **THEN** the exact audit-unavailable product is returned and no signal is claimed, delivered or retried

### Requirement: Compatibility EventBus SHALL remain a bounded bridge

The implementation SHALL introduce Platform delivery beside the current
`trade_py.bus.EventBus`; it SHALL not reinterpret legacy `event_log` and
`event_handler_runs` rows as complete formal outbox/inbox/ordering records. A
compatibility adapter MAY map proven legacy admission/status facts lossily, delegate
selected legacy topics, or mirror a message only with a durable one-way bridge
identity and payload-digest comparison.

Current topic names, CLI behavior, Web event status and replay behavior SHALL remain
unchanged until their named interface/process children pass snapshots. Business
`Topic` constants, DAG handler factories and `pipeline_dag` orchestration SHALL not
move into Platform Events. Adoption by current runtime owners SHALL remain blocked on
`runtime-owner-shutdown-and-recovery-hardening-v1`.

#### Scenario: A legacy event is mirrored
- **WHEN** an approved bridge maps one legacy event to a Platform envelope
- **THEN** it records one bridge identity and digest so restart cannot create another effective Platform message

#### Scenario: A legacy row lacks formal metadata
- **WHEN** actor, canonical command fingerprint, ordering or payload-proof facts are absent
- **THEN** the adapter exposes a legacy observation or unknown field and does not fabricate a formal receipt or ordering guarantee

#### Scenario: EventBus shutdown is still on the legacy runtime
- **WHEN** the Platform delivery implementation exists but shutdown hardening is not strictly approved and implemented
- **THEN** current EventBus/Web/CLI owners remain on their legacy behavior and the foundation is not reported as a shutdown fix
