## ADDED Requirements

### Requirement: Actor context SHALL be established from trusted adapter evidence

`ActorContext` SHALL identify origin, principal kind and identifier, authority
scopes, bounded delegation, assurance, provenance and establishment time.
Mutation authority SHALL be established only from adapter-controlled CLI,
authenticated HTTP/SDK, registered scheduler, verified parent-event or
Bootstrap system evidence. Caller payload fields SHALL NOT establish identity
or authority. A decoded wire actor SHALL remain unverified until re-established
against trusted local evidence.

For mutating command idempotency, the adapter SHALL also establish an immutable
`IdempotencySubjectV1` with exact fields `schema_version=1`,
`owner_namespace`, `tenant_id`, `principal_kind`, `principal_id` and an ordered
tuple of zero to eight `delegated_subject_ids`. Namespace and every identity
SHALL use bounded Kernel values. Only `authenticated` and `system` principals
are valid idempotency subjects; anonymous and unknown actors SHALL NOT submit a
mutating command. The canonical subject SHALL exclude origin, authority scopes,
assurance, provenance verifier/evidence identity, establishment/expiry time and
credentials. Reauthentication and permission-scope changes for the same
tenant/principal/delegation therefore retain one subject; a different tenant,
principal or ordered delegation subject chain is a different subject.
Its wire bytes SHALL be the exact bounded canonical JSON object for those six
fields, with `delegated_subject_ids` always present as an array. The
idempotency HMAC input SHALL be the ordered sequence of domain,
canonical-subject bytes, UTF-8 command idempotency scope and raw key bytes, with
each component prefixed by its unsigned four-byte big-endian byte length. No
delimiter, `str()` conversion, omitted empty array or alternate field set is
admitted.

Provenance SHALL be a bounded `ActorProvenanceRef`, not an arbitrary mapping.
It SHALL contain a closed provenance type, bounded verifier namespace, opaque
evidence ID, establishment time, optional expiry and stable reason code, and
its canonical form SHALL be at most 1,024 bytes. It SHALL contain no credential,
raw claim set, environment dump or parent payload.
Authority scopes SHALL be 1-96 ASCII lower-case letters/digits plus `._:-`,
sorted and unique, with at most 32 entries. Delegation SHALL contain at most
eight provenance references.

`origin` SHALL describe the verified admission channel, not a product protocol.
GraphQL over authenticated HTTP remains `http`; a local TUI remains `cli`;
MCP uses its actual authenticated `http`, `sdk` or `cli` channel; and a remote
worker uses its verified Platform execution/event channel. A new origin enum
requires a distinct trust-establishment semantic and a new schema version.

Durable replay SHALL separate immutable historical attribution from current
execution authority. The replayed historical envelope and historical actor
bytes remain unchanged, but the decoded historical actor is attribution-only
and unverified. A new `ReplayContextV1` SHALL contain the current replay request
message/correlation/optional-causation tuple, historical message identity,
historical actor attribution, current verified `replay_initiator`, and immutable
replay policy reference. Current causation SHALL be absent for a root replay
request and equal its direct parent for a child request. Retry/redelivery SHALL
preserve that current tuple. Re-dispatch and every replay-derived command SHALL
be authorized from the current replay initiator plus owner/Process policy; they
SHALL NOT copy authority scopes or assurance from the historical actor.
Revoked/expired historical provenance does not erase attribution and does not
grant current authority. Replay never changes the historical idempotency
subject; a newly derived mutating command establishes its own current
idempotency subject.

A direct command redispatch SHALL use an exact `ReplayAdmissionV1` containing
`schema_version=1`, `ReplayContextV1`, historical message/correlation/optional
causation identities, the canonical historical-envelope `ContentDigest`,
required historical operation identity, current `IdempotencySubjectV1` and one
finite `Deadline`. `ReplayContextV1` SHALL be the single source of the current
replay initiator and immutable replay policy reference; `ReplayAdmissionV1`
SHALL NOT duplicate either value. The outer historical message identity SHALL
equal the context's historical message identity, and the current subject SHALL
be derived from that context's verified replay initiator under the ordinary
subject rules. Before opening a replay transaction or reading/disclosing an
operation or claim, the adapter SHALL verify those bindings, the digest and
complete historical identity tuple and authorize the current initiator, subject
and policy.

Direct redispatch SHALL be resolve-only and consume one monotonic remaining
deadline. One admission SHALL start at most one Platform owner-local replay
transaction, perform at most one audit-key lookup and at most one required
operation/claim lookup, and perform no persistence retry or background
continuation. Its durable replay-audit key SHALL be exactly
`(owner_namespace, replay_request_message_id)`. The transaction SHALL check that
key before an operation lookup. A prior row whose internal admission binding
digest differs SHALL return `REPLAY_ADMISSION_CONFLICT` without looking up the
requested operation. The internal binding digest SHALL be SHA-256 over the exact
byte sequence ASCII `trade.replay-admission-binding.v1`, one NUL byte and the
canonical `ReplayAdmissionV1` identity/authority/content fields with only
`deadline` omitted. Excluding the attempt deadline SHALL permit the same request
and binding to retry with a fresh finite deadline, but every retry SHALL be
reauthorized before the key lookup. The digest SHALL be authorization-neutral
and SHALL NOT enter a public error, receipt, metric, log or cross-Context
projection.

For a new replay-audit key, the transaction SHALL resolve the required
command-equivalent operation/claim exactly once. If it is absent, replay SHALL
return `REPLAY_OPERATION_NOT_FOUND` and create no claim, operation, receipt or
resolved-audit fact. If it exists, the same transaction SHALL commit one
replay-audit fact before returning the unchanged historical
`OperationReceipt`; it SHALL NOT rewrite that receipt's historical actor or
causal identities. The replay-audit fact SHALL be at most 2,048 canonical bytes
and contain only schema/version, static owner namespace, current replay request
message/correlation/optional direct causation, historical message and operation
identities, historical-envelope digest, internal admission binding digest,
current safe principal identity, immutable policy reference, `resolved` outcome
and `occurred_at: UtcInstant`. For a new key, the Platform owner SHALL sample
`occurred_at` exactly once after the operation/claim resolves successfully and
immediately before constructing the audit fact to commit. Clock failure SHALL
return `REPLAY_AUDIT_UNAVAILABLE`, commit no replay-audit fact and return no
receipt. This value SHALL mean only the Platform owner's first replay-audit
observation time; it SHALL NOT be interpreted as historical event,
provider/source, publication, received, available, PIT, deadline,
transaction-completion or response time. A same-key, same-binding
retry/redelivery SHALL preserve the originally committed `occurred_at` and
resolve that existing audit and the same receipt in the single transaction
without another wall-clock sample or a second audit row.

If that clock sample fails, the transaction cannot start or commit within the
remaining deadline, or persistence fails, replay SHALL return
`REPLAY_AUDIT_UNAVAILABLE` with no receipt or operation/process link. It SHALL
NOT silently succeed, retry or continue in the background. A crash before
commit SHALL leave no replay-audit fact. A crash after commit but before
response SHALL recover through the same-key, same-binding path. The owner SHALL
make at most one bounded failure signal to the same Platform operator health
owner required for admission-audit failure; runtime adoption SHALL remain
blocked until that bounded health query exists. Authorization denial SHALL
occur before the replay transaction and SHALL disclose no existence fact.
Re-executing work requires a new
replay-derived command under the ordinary child-message rule with current actor,
subject, policy and immutable input references.

#### Scenario: A payload claims an administrator actor
- **WHEN** a command body contains actor, user, principal or authority fields that are not established by the adapter
- **THEN** those fields confer no authority and the mutation is denied or attributed to the separately established actor

#### Scenario: A verified scheduler submits a command
- **WHEN** Platform Scheduling creates a command from a registered schedule and lease
- **THEN** it establishes a system actor whose provenance links to that schedule identity without embedding credentials

#### Scenario: An anonymous query is allowed
- **WHEN** an interface policy explicitly permits an anonymous read-only query
- **THEN** the actor is marked `anonymous` with `anonymous_allowed` assurance and receives only the declared query scope

#### Scenario: A principal reauthenticates or changes permission scopes
- **WHEN** the same verified tenant, principal and delegation subject chain receives new provenance or a different authority-scope set
- **THEN** its idempotency subject remains byte-identical while the current command is separately authorized against the current scopes

#### Scenario: Two principals have equal permissions
- **WHEN** two verified principals in one tenant have identical authority scopes or one principal acts in two different tenants
- **THEN** their idempotency subjects remain distinct and one principal cannot resolve the other's claim

#### Scenario: An anonymous actor submits a mutation
- **WHEN** an anonymous or unknown actor attempts command admission
- **THEN** authorization rejects it before idempotency fingerprinting and no anonymous shared subject is constructed

#### Scenario: Expired or revoked historical provenance is replayed
- **WHEN** a durable command or event is replayed after its historical actor provenance expires or is revoked
- **THEN** the historical actor remains immutable attribution, while replay execution requires a separately verified replay initiator and current owner/Process authorization

#### Scenario: Direct replay resolves an existing operation
- **WHEN** an authorized ReplayAdmission matches an immutable historical command and an existing command-equivalent operation
- **THEN** one replay-audit transaction commits the current request causal tuple, initiator and policy before the original receipt is returned unchanged

#### Scenario: Direct replay has no existing operation
- **WHEN** an authorized ReplayAdmission has a valid historical envelope but no historical operation or claim
- **THEN** replay returns `REPLAY_OPERATION_NOT_FOUND` and creates no claim, operation, receipt or resolved-audit fact

#### Scenario: Replay authorization is denied
- **WHEN** the current replay initiator, subject or policy is not authorized
- **THEN** replay denies the request before a replay transaction starts or operation or claim existence is read or disclosed

#### Scenario: Replay audit persistence is unavailable
- **WHEN** the first-audit wall-clock sample fails, the single replay transaction cannot start or commit within the remaining deadline, or persistence fails
- **THEN** replay returns `REPLAY_AUDIT_UNAVAILABLE` without a receipt, operation/process link, retry, background continuation or unaudited success

#### Scenario: Replay response is lost after audit commit
- **WHEN** the owner commits the resolved replay audit and crashes before the historical receipt response arrives
- **THEN** retry/redelivery with the same current request tuple and binding preserves the first `occurred_at` and resolves the same audit and receipt without another wall-clock sample or a second audit row

#### Scenario: Replay audit time is not market time
- **WHEN** a consumer reads replay-audit `occurred_at`
- **THEN** it is interpreted only as the Platform owner's first replay-audit observation time and never as historical event, provider/source, publication, received, available, PIT, deadline, transaction-completion or response time

#### Scenario: A replay request identity is reused for another binding
- **WHEN** an existing replay-audit key is submitted with a different historical digest, identity, operation, current subject, actor or policy binding
- **THEN** replay returns `REPLAY_ADMISSION_CONFLICT` before looking up the requested operation and does not expose the internal binding digest

#### Scenario: A future interface protocol establishes an actor
- **WHEN** GraphQL, TUI, MCP or a remote worker submits through an existing verified transport
- **THEN** origin records the verified transport trust semantic and does not create a protocol-branded origin without a schema change

### Requirement: Command and query envelopes SHALL use typed owner payloads

Command and query envelopes SHALL compose Kernel metadata, trusted
`ActorContext`, a finite deadline and one typed owner DTO. The pre-admission
envelope SHALL expose deterministic canonical payload bytes and schema identity,
but SHALL NOT expose or precompute a keyed command fingerprint. Platform
ingress derives that fingerprint only after a stable idempotency result under
the exact rules below. Envelopes SHALL NOT expose raw idempotency secrets, live
callbacks, framework request objects or arbitrary payload dictionaries.

Public command and idempotency fingerprints SHALL use exact
`FingerprintV1 {algorithm, domain, key_version, value}` values. `algorithm`
SHALL be `hmac-sha256-v1`; domains SHALL be distinct
`trade.command.v1` and `trade.idempotency.v1`; value SHALL be lower-case
64-character hexadecimal; and key version SHALL be an integer
1-2,147,483,647. The secret SHALL contain at least 256 CSPRNG-generated bits,
remain behind a Platform ingress secret-store port and be absent from every
wire/log value.

The key set SHALL have exactly one active write version, at most three retained
read-only versions and a monotonically increasing `key_set_generation` in the
range 1-9,223,372,036,854,775,807. Rotation and admission SHALL use the same
owner-local CAS/lock; rotation SHALL atomically advance generation with the key
set. One command admission SHALL make at most three total claim attempts,
including the initial attempt. Each attempt SHALL start at most one claim transaction,
read one generation, derive at most four HMAC candidates and perform one
candidate query. A changed generation SHALL end and roll back that attempt;
re-derivation SHALL occur only in the next attempt. Claim attempts,
transaction/CAS acquisition, any contention backoff, one optional refusal-audit
transaction and telemetry SHALL consume one `CommandEnvelope` monotonic
remaining deadline.
Across three attempts, admission SHALL derive at most twelve idempotency-
candidate HMACs. After a final stable zero-match result, admission SHALL derive
exactly one command-fingerprint HMAC using the unchanged active key before
atomically creating the claim, operation and receipt. After a final stable
one-match result, admission SHALL derive exactly one command-fingerprint HMAC
using that claim's recorded key before returning either the original receipt or
`IDEMPOTENCY_COMMAND_CONFLICT`. Total HMAC derivations SHALL therefore be at
most thirteen. Multi-match corruption, exhausted contention and every
pre-admission rejection SHALL perform zero command-fingerprint HMAC
derivations. `IDEMPOTENCY_AUDIT_UNAVAILABLE` after a provisional command
conflict preserves the one command HMAC already required to detect that
conflict; audit-unavailable after provisional corruption or contention has zero
command HMACs.

In one owner-local admission transaction, ingress SHALL read generation, derive
and query candidate idempotency fingerprints for every active or retained key
before creating a claim, and apply this exact result product: zero matches
revalidates unchanged generation then creates one active-version claim; one
match validates the command identity then returns the original receipt; more
than one match always returns `IDEMPOTENCY_CLAIM_CORRUPT` and creates nothing,
even if rows point to one operation. A one-match claim SHALL bind `command_name`,
`operation_kind` and its original canonical command fingerprint. Ingress SHALL
recompute the current command fingerprint with that claim's recorded key
version. Any mismatch SHALL return stable `IDEMPOTENCY_COMMAND_CONFLICT`,
without returning the old receipt or creating a new operation.

If generation changes before zero-match insertion, admission SHALL roll back and
end the current attempt. A later attempt MAY re-derive every candidate from the
new key set within the same deadline. If the third claim attempt or shared
deadline is exhausted before a stable result, admission SHALL form a
provisional `IDEMPOTENCY_KEYSET_CONTENTION` refusal, create no claim, operation
or receipt, and start no background continuation. It SHALL return that reason
only after its refusal audit commits within the remaining shared deadline. If
no time remains to start/commit that audit, or the audit transaction fails,
admission SHALL return `IDEMPOTENCY_AUDIT_UNAVAILABLE` instead. Existing
receipts SHALL retain their original version and SHALL NOT be rewritten during
rotation. Each key SHALL be retained for at least the owner operation-retention
horizon; retirement SHALL fail if safe retention cannot fit the four-version
bound. A retired unknown version SHALL report unavailable rather than recompute
with the current key. An unkeyed digest SHALL NOT be published for low-entropy
idempotency keys or commands. The Platform command-admission claim SHALL be
uniquely scoped by the canonical `IdempotencySubjectV1`, command idempotency
scope and keyed raw-key fingerprint. It is distinct from a Processes-owned
workflow/process-start claim. Processes SHALL use an internal owner-local
`ProcessStartKeyV1` with exact fields `schema_version=1`, bounded process type,
triggering Platform operation identity and an owner-defined immutable
workflow-key `ContentDigest`. Process type SHALL be a 1-96 character ASCII
lower-case token using letters/digits plus `._:-`; operation identity SHALL be
an `OpaqueId`; and workflow-key digest SHALL be SHA-256. Its canonical bytes
SHALL use exact JSON v1 and
the complete tuple SHALL be the ProcessRepository/inbox unique key. It SHALL
have no HMAC, secret, public fingerprint domain or `ProcessView` field.
Processes SHALL NOT store or reuse the raw interface idempotency key, Platform
HMAC fingerprint or secret, and it deduplicates durable handoff/process creation
only. Platform owns command claims/OperationReceipt in a Platform repository
transaction; Processes owns the process-start claim, inbox acceptance and
initial ProcessView atomically in a later ProcessRepository transaction. No
shared transaction or cross-owner write is permitted.

#### Scenario: A command is retried after transport timeout
- **WHEN** the same idempotency subject, canonical command and idempotency identity are resubmitted
- **THEN** command ingress can resolve the same digest and existing operation without depending on transport retry metadata

#### Scenario: A retry crosses an HMAC key rotation
- **WHEN** a raw idempotency identity was admitted with a retained key and is retried after a new write key becomes active
- **THEN** the same transaction finds the retained-version claim, verifies the same command identity and returns the original receipt rather than creating an active-version duplicate

#### Scenario: An idempotency identity is reused for a different command
- **WHEN** one claim matches but command name, operation kind or the recomputed canonical command fingerprint differs
- **THEN** ingress returns `IDEMPOTENCY_COMMAND_CONFLICT` without the old receipt and creates no operation

#### Scenario: Retained versions resolve multiple claims
- **WHEN** candidate fingerprints for one raw identity match more than one durable claim, including duplicate rows linked to one operation
- **THEN** ingress returns `IDEMPOTENCY_CLAIM_CORRUPT` and creates no new operation

#### Scenario: Rotation races a paused zero-match admission
- **WHEN** an admission reads generation N and pauses before insert while rotation and another admission commit generation N+1
- **THEN** the paused admission fails generation revalidation, rolls back and re-derives candidates so exactly one durable claim exists

#### Scenario: Rotation contention exhausts admission
- **WHEN** key-set generation changes through the third admission attempt and the contention refusal audit commits within the remaining shared deadline
- **THEN** ingress returns `IDEMPOTENCY_KEYSET_CONTENTION` without a claim, operation, receipt or background continuation
- **AND THEN** one admission has performed no more than twelve idempotency-candidate HMAC derivations, zero command-fingerprint HMAC derivations, three candidate queries, three claim transaction/CAS acquisitions and one refusal-audit transaction

#### Scenario: A stable replay follows generation retries
- **WHEN** two attempts end on generation changes and the third finds exactly one command-equivalent claim
- **THEN** admission performs at most twelve idempotency-candidate HMAC derivations plus one command-fingerprint HMAC, thirteen total, before returning the original receipt

#### Scenario: A stable creation follows generation retries
- **WHEN** two attempts end on generation changes and the third has zero matches under an unchanged active generation
- **THEN** admission performs at most twelve idempotency-candidate HMAC derivations plus one command-fingerprint HMAC, thirteen total, before atomically creating the claim, operation and initial receipt

#### Scenario: A stable command conflict follows generation retries
- **WHEN** two attempts end on generation changes and the third finds exactly one claim whose command identity differs
- **THEN** admission performs at most twelve idempotency-candidate HMAC derivations plus exactly one command-fingerprint HMAC, thirteen total, and returns no old receipt or new operation

#### Scenario: A corrupt claim set or audit-unavailable refusal is returned
- **WHEN** the stable result has multiple claims or a required refusal audit cannot commit
- **THEN** corruption-to-audit-unavailable performs zero command-fingerprint HMAC derivations, while conflict-to-audit-unavailable retains exactly the one command HMAC already used to detect conflict; neither exposes a command fingerprint

#### Scenario: A durable operation handoff is delivered twice to Processes
- **WHEN** the same triggering operation and immutable workflow key reach a Process Manager more than once
- **THEN** Processes resolves one owner-local ProcessStartKey claim and existing ProcessView without reading or writing the Platform command-admission claim

#### Scenario: Deadline expires before contention audit
- **WHEN** claim contention leaves no remaining time to start and commit its refusal audit
- **THEN** ingress returns `IDEMPOTENCY_AUDIT_UNAVAILABLE` without starting another transaction or reporting contention as durably recorded

#### Scenario: A framework object enters a command
- **WHEN** a DTO contains a FastAPI request, Pydantic model, ORM object, DataFrame, connection, filesystem path or service object
- **THEN** contract validation or the architecture guard rejects it before serialization

#### Scenario: A public observer guesses a low-entropy key
- **WHEN** an observer has a receipt fingerprint and guesses a likely raw idempotency key
- **THEN** the receipt exposes no unkeyed digest with which that guess can be verified offline

### Requirement: Operation receipts SHALL report durable admission and terminal state truthfully

An `OperationReceipt` SHALL contain version, operation identity and kind,
command fingerprint, trusted actor, admitted request message identity,
correlation identity, optional direct-causation identity, scoped idempotency
fingerprint, closed operation state, safe reason, timestamps and optional
process linkage. These message, correlation and optional causation values SHALL
be copied from the envelope that created the operation; causation SHALL be
absent for a root envelope and SHALL equal the direct parent for a child
envelope. A receipt SHALL exist only after durable admission identity is
created. Only a command-equivalent duplicate admission SHALL return the
existing receipt, preserving the original admitted request and causal
identities rather than replacing them with the duplicate request's identities;
an idempotency identity reused for another command SHALL return the conflict
error below without that receipt. Raw payloads and raw idempotency keys SHALL
NOT be exposed.
Platform command ingress SHALL be the sole future authority and writer for
command-admission idempotency claims, operation identity and every initial,
intermediate and terminal `OperationReceipt`. Processes SHALL own its separate
`ProcessStartKeyV1`/inbox claims, Process Manager workflow state and
`ProcessView`; it SHALL NOT create, rewrite or become a second source of truth
for an OperationReceipt. Platform and Processes SHALL link by opaque identity
plus durable command/event handoff, not a shared transaction.
The Platform-owned optional process link SHALL be `OpaqueId | None`; Platform
SHALL NOT import the Processes-owned `ProcessId`.

Before a Platform or Processes child creates a repository, the parent
architecture ownership matrix SHALL be governedly clarified to split Platform
operation-receipt ownership from Processes workflow ownership. Until then, this
child SHALL remain contract-only and SHALL authorize no durable writer.

The exact allowed state transitions SHALL be:
`requested -> accepted|failed|cancelled|deadline_exceeded`;
`accepted -> running|waiting|retry_scheduled|blocked|completed|failed|cancelled|deadline_exceeded`;
`running -> waiting|retry_scheduled|compensation_pending|blocked|completed|failed|cancelled|deadline_exceeded`;
`waiting -> running|retry_scheduled|blocked|failed|cancelled|deadline_exceeded`;
`retry_scheduled -> running|waiting|blocked|failed|cancelled|deadline_exceeded`;
`compensation_pending -> compensated|blocked|failed|deadline_exceeded`;
`blocked -> running|retry_scheduled|compensation_pending|failed|cancelled|deadline_exceeded`.
Terminal states SHALL have no outgoing transition. An identical state may be
re-observed only without changing terminal facts.

The exact Process state relation SHALL omit `accepted`:
`requested -> running|waiting|failed|cancelled|deadline_exceeded`; every other
non-terminal relation is the corresponding Operation relation above with no
edge to/from `accepted`. `terminal_at` SHALL be absent for non-terminal states,
required exactly once for terminal states and ordered after start/acceptance
and no later than `updated_at`.
An owner `deadline_exceeded` terminal state SHALL require either exit of every
owned worker or durable fencing that prevents every recorded residual worker
from writing. A caller observation timeout SHALL NOT transition an operation or
process to owner `deadline_exceeded`.

#### Scenario: Persistence fails before operation identity is committed
- **WHEN** command ingress cannot durably claim an operation
- **THEN** it returns an `ErrorEnvelope` without fabricating an operation receipt or operation ID

#### Scenario: A duplicate accepted command is observed
- **WHEN** the same scoped idempotency identity is admitted again
- **THEN** the existing operation receipt is returned and no second owner transaction is created

#### Scenario: An operation reaches a terminal state
- **WHEN** an operation becomes completed, compensated, failed, cancelled or deadline-exceeded
- **THEN** its terminal timestamp is set once and no later transition returns it to running or waiting

#### Scenario: Caller observation expires while the owner still runs
- **WHEN** the observation deadline expires before a newer owner state and the worker has neither exited nor been durably write-fenced
- **THEN** the query reports `not_observed` while owner state remains non-terminal

#### Scenario: A Process Manager advances its workflow
- **WHEN** Processes records a new current step or terminal Process state
- **THEN** it updates only its Process Manager record and ProcessView, and any OperationReceipt change requires a separate Platform-owned transition through durable handoff

### Requirement: Process views SHALL be bounded read-only recovery projections

A `ProcessView` SHALL expose schema version, process identity/type, triggering
Platform operation identity, correlation/optional causation, closed process and
observation states, current step, top-level reason code,
retry/limit/next-attempt, deadline, last safe error, compensation and
dead-letter states, no more than 50 ordered transitions, permitted recovery
actions and timestamps. It SHALL NOT expose either owner's idempotency
fingerprint, `ProcessStartKeyV1`, workflow key, raw command/event payload, SQL,
credentials, business-table rows, artifact bytes or traceback. Querying the
view SHALL NOT execute a recovery action.

The top-level reason code SHALL be required for `blocked`, `retry_scheduled`,
`failed`, `cancelled` and `deadline_exceeded`; optional for
`compensation_pending`; and forbidden for `requested`, `running`, `waiting`,
`completed` and `compensated`. A matching safe error may add details but SHALL
NOT replace the process-level reason.

Process history SHALL return the latest at most 50 transitions ordered by
strictly increasing owner sequence and SHALL include `total_count`,
`returned_count`, `first_sequence`, `last_sequence` and
`omitted_before_count`. Counts SHALL be integers 0-2,147,483,647 and sequences
0-9,223,372,036,854,775,807. Empty and non-empty window invariants SHALL be
validated exactly; duplicate/decreasing sequences SHALL be rejected.

Recovery capability SHALL use at most 16 Processes-owned
`RecoveryActionDescriptor` values containing owner, closed action, opaque
target, policy namespace/version, reason, expiry and required actor scope.
Closed generic actions SHALL distinguish `redeliver_message`,
`replay_immutable_input` and `request_new_external_interaction`; the generic
word `redrive` SHALL NOT combine these semantics. Owner namespace and later
owner commands supply Capture/event business meaning. A descriptor SHALL
neither authorize nor execute its action.

#### Scenario: A process is blocked
- **WHEN** an operator queries a blocked process
- **THEN** the view reports the blocking reason, deadline, last observed step and permitted recovery actions without retrying, redriving or mutating the process

#### Scenario: Process history exceeds the wire budget
- **WHEN** more than 50 transitions exist
- **THEN** the owner returns a deterministic bounded window plus truncation metadata and retains full durable history outside the public DTO

#### Scenario: A process cannot be observed
- **WHEN** the process query store is unavailable or no observation completes before the caller deadline
- **THEN** the view or error reports `unavailable` or `not_observed` and does not represent the result as empty, healthy or completed

### Requirement: Status families SHALL remain orthogonal and closed

The system SHALL represent admission, operation, process, observation,
query-condition, control and shutdown states as separate closed enums.
`unknown`, `not_observed` and
`unavailable` SHALL remain distinct from `empty`, `partial`, `stale`,
`quarantined`, `blocked`, success and terminal error. Adding an enum value SHALL
require a new wire-schema version and compatibility review.

`QueryStatus` SHALL be a tagged union with this exact state product:
`observed/present` and `observed/empty` forbid an error;
`observed/partial`, `observed/stale`, `observed/quarantined` and
`observed/blocked` require errors categorized respectively as `unavailable`,
`stale`, `quarantined` and `blocked`; `not_observed`, `unavailable` and
`unknown` forbid a condition and require errors categorized respectively as
`timeout`, `unavailable` and `internal`. Every error's observation state SHALL
match the QueryStatus observation. Every unlisted combination SHALL be
rejected.

#### Scenario: A query returns no business rows
- **WHEN** the owner successfully observes a valid empty result
- **THEN** it reports observation `observed` and condition `empty`, not `unknown` or `unavailable`

#### Scenario: A legacy status is unknown
- **WHEN** a mapper encounters a status not covered by its reviewed source version
- **THEN** it fails closed to an unknown observation plus a safe error and never maps the status to success

#### Scenario: A legacy process is terminated
- **WHEN** a legacy row says `terminated` without durable cancellation intent and terminal cancellation evidence
- **THEN** the target contract does not claim `cancelled` and reports conservative failed or unknown terminal observation

### Requirement: Error envelopes SHALL be safe, versioned and transport-neutral

`ErrorEnvelope` SHALL contain exact schema name/version, stable reason code,
closed category and observation state, retryability and optional bounded
retry-after, `request_message_id`, correlation/optional causation and
operation/process links, occurrence time, safe message and safe recovery hint.
For an error caused while handling a specific admitted or rejected envelope,
`request_message_id` SHALL equal that envelope's message identity,
`correlation_id` SHALL equal its correlation identity, and `causation_id` SHALL
be absent for a root envelope or equal its direct parent for a child envelope.
These are the safe concrete request links when no operation/process identity
exists. It SHALL NOT contain arbitrary extra fields, raw exception text,
traceback, credential, SQL, path or raw payload. HTTP status, CLI exit code and
SSE framing SHALL remain interface-adapter mappings.

Reason codes SHALL be 1-96 ASCII upper-case letters/digits plus `._-`;
`retry_after_ms` SHALL be absent or an integer 0-86,400,000; safe message and
recovery hint SHALL each be at most 1,024 UTF-8 bytes.

In addition to required schema/version/reason/occurred-at/safe-message fields,
replay and idempotency admission SHALL use these exact closed products for
category, observation, retry fields, public links and safe recovery hint. Every
unlisted field combination SHALL be rejected:

- `REPLAY_OPERATION_NOT_FOUND`: category `invalid`, observation `observed`,
  `retryable=false`, no retry-after, required current replay
  request/correlation and root-absent or child-present causation, no
  operation/process ID, and a safe hint to verify the historical operation or
  submit a newly authorized replay-derived command.
- `REPLAY_ADMISSION_CONFLICT`: category `conflict`, observation `observed`,
  `retryable=false`, no retry-after, required current replay
  request/correlation and root-absent or child-present causation, no
  operation/process ID, and a safe hint to retry the original replay binding or
  use a new replay request identity.
- `REPLAY_AUDIT_UNAVAILABLE`: category `unavailable`, observation `unavailable`,
  `retryable=true`, required `retry_after_ms` in 1-1,000, required current
  replay request/correlation and root-absent or child-present causation, no
  operation/process ID, and a safe hint to inspect Platform replay-audit
  persistence and retry the same replay request after recovery.

- `IDEMPOTENCY_COMMAND_CONFLICT`: category `conflict`, observation `observed`,
  `retryable=false`, no retry-after, required current request/correlation and
  root-absent or child-present causation, no operation/process ID, and a safe
  hint to submit the original command or a new idempotency identity.
- `IDEMPOTENCY_CLAIM_CORRUPT`: category `internal`, observation `observed`,
  `retryable=false`, no retry-after, required current request/correlation and
  root-absent or child-present causation, no operation/process ID, and a safe
  hint requiring audited operator inspection.
- `IDEMPOTENCY_KEYSET_CONTENTION`: category `unavailable`, observation
  `unavailable`, `retryable=true`, required `retry_after_ms` in 1-1,000,
  required current request/correlation and root-absent or child-present
  causation, no operation/process ID, and a safe hint to retry the same
  command/identity with a fresh finite deadline.
- `IDEMPOTENCY_AUDIT_UNAVAILABLE`: category `unavailable`, observation
  `unavailable`, `retryable=true`, required `retry_after_ms` in 1-1,000,
  required current request/correlation and root-absent or child-present
  causation, no operation/process ID, and a safe hint to inspect Platform
  persistence and retry after recovery.

These errors SHALL contain no old receipt, raw key, command/replay payload,
internal replay binding digest, claim internals, actor identifier or
fingerprint. The future Platform persistence owner SHALL record one immutable
admission-audit fact for every terminal idempotency conflict, corruption and
contention outcome before returning that exact outcome. The fact SHALL use one
optional repository transaction after the claim attempt ends, SHALL have
canonical size at most 2,048 bytes, and SHALL contain
only schema/version, reason, request/correlation/optional causation identities,
static owner namespace, sorted matched key versions (at most four), key-set
generation, attempt count and occurred-at. The causal fields SHALL exactly copy
the current command envelope, with causation absent for a root and present for a
child. It SHALL contain no raw key, command
DTO/payload, provider/source body, artifact bytes, actor identifier, credential,
path or fingerprint. It SHALL be visible only through an authorized Platform
operator audit query and SHALL NOT enter an `ErrorEnvelope`, HTTP/SDK response
or cross-Context projection. The audit transaction SHALL NOT create or reopen a claim,
operation, receipt or dispatch. If the audit fact cannot start or commit within
the remaining deadline, admission SHALL return
`IDEMPOTENCY_AUDIT_UNAVAILABLE` instead and SHALL still create no claim,
operation or receipt. The provisional conflict, corruption or contention reason
SHALL NOT be returned as durably recorded in that case. One admission SHALL
therefore start at most three claim
transactions plus one refusal-audit transaction. The owner SHALL expose only the
low-cardinality counter `platform_idempotency_admission_outcomes_total` with
`owner_namespace` and the closed outcome
`created|replayed|command_conflict|claim_corrupt|keyset_contention|audit_unavailable`
as labels. This counter records only the final admission result; generation
retries are represented only by the bounded numeric `attempt_count` in the
event/audit and SHALL NOT replace the terminal outcome. The counter, one bounded
structured event and, for corruption, one integrity alert SHALL each be
attempted at most once, synchronously under the same remaining deadline, with
no retry or background continuation. The event SHALL contain only reason,
request/correlation/optional causation, owner, sorted matched key versions (at
most four), key-set generation and attempt count. Telemetry emission failure SHALL
surface once to the owner health/audit channel and SHALL NOT convert a refusal
to success or permit claim creation. The
`platform-persistence-events-and-bootstrap-foundation` child SHALL own a
bounded, operator-authorized health observation for this failure and SHALL
freeze its reason/state/query contract before runtime adoption; until then no
production ingress may wire this telemetry path.

#### Scenario: An Observatory error is mapped
- **WHEN** a legacy `ObservatoryError` contains reason, message, evidence refs and arbitrary extra fields
- **THEN** the mapper emits only whitelisted safe fields and uses a stable generic message if the original message is not proven safe

#### Scenario: A retry-after value is present
- **WHEN** a retryable saturation or availability failure has an owner-approved finite delay
- **THEN** the envelope carries bounded integer milliseconds and the HTTP adapter may preserve its existing `Retry-After` representation

#### Scenario: Idempotency errors are encoded
- **WHEN** admission reports a command conflict, corrupt claim set, exhausted key-set contention or unavailable refusal audit
- **THEN** the exact reason/category/observation/retry/link/recovery product above is emitted, its request/correlation/optional causation links copy the current command envelope, and every forbidden combination is rejected

#### Scenario: Replay errors are encoded
- **WHEN** replay reports a missing operation, conflicting replay binding or unavailable replay audit
- **THEN** the exact reason/category/observation/retry/link/recovery product above is emitted, its request/correlation/optional causation links copy the current ReplayContext, no receipt or operation/process link is present, and the internal binding digest is not disclosed

#### Scenario: Generation retries end in a stable result
- **WHEN** one or two key-set generation changes precede a stable creation, replay or refusal
- **THEN** the one admission outcome counter records only that final result while bounded attempt count preserves retry evidence

#### Scenario: Claim corruption is observed
- **WHEN** more than one candidate claim matches
- **THEN** the owner records one 2,048-byte-bounded allowlisted terminal refusal and attempts one closed low-cardinality counter, one redacted bounded event and one integrity alert under the same remaining deadline
- **AND THEN** telemetry is neither retried nor continued in a background task

#### Scenario: Terminal refusal audit cannot commit
- **WHEN** the owner cannot durably record the conflict, corruption or contention refusal before the shared deadline
- **THEN** admission returns `IDEMPOTENCY_AUDIT_UNAVAILABLE` with no claim, operation or receipt and surfaces the audit failure without reporting the underlying refusal as durably recorded

#### Scenario: Refusal audit outcome priority is deterministic
- **WHEN** three contention attempts finish and audit either commits, has no remaining start budget, or fails within its remaining budget
- **THEN** golden fixtures return respectively `IDEMPOTENCY_KEYSET_CONTENTION`, `IDEMPOTENCY_AUDIT_UNAVAILABLE`, and `IDEMPOTENCY_AUDIT_UNAVAILABLE`

### Requirement: Cancellation SHALL distinguish request acceptance from terminal cancellation

A cancellation API SHALL return an exact immutable `ControlReceipt` v1 with:
schema name/version, control identity/kind, `request_message_id`,
correlation/optional causation, trusted initiator, exactly one operation or
opaque process target, requested/finished times, finite control deadline, closed
disposition, stable reason code, optional `target_terminal_receipt_id`, and
optional safe `ErrorEnvelope`. The request/correlation/causation identities
SHALL copy the admitted control envelope. A control is an ordinary admitted
Platform command, and its exact durable control-claim identity SHALL be that
command's operation identity plus control kind and exactly one target identity.
Every returned disposition SHALL be atomically persisted with that exact
control claim. For `accepted`, the same owner-local transaction SHALL also
create durable intent and dispatch/outbox; every other disposition SHALL create
neither. If the claim and immutable receipt cannot commit, the API SHALL return
a retryable `CONTROL_RECEIPT_UNAVAILABLE` `ErrorEnvelope` and no
`ControlReceipt`, intent or outbox. A
retried/redelivered/replayed logical envelope preserves its receipt; a newly
submitted duplicate has a new request identity but returns the original control
receipt only when ordinary command idempotency resolves the same operation and
exact control claim, without rewriting original attribution.

The v1 disposition product SHALL be exact:

- `accepted`: reason `CONTROL_ACCEPTED`; safe error and terminal receipt link
  forbidden; intent is durably admitted but target terminal state is unproved.
- `already_terminal`: reason `CONTROL_ALREADY_TERMINAL`; required immutable
  `target_terminal_receipt_id`; safe error forbidden; the link proves the target
  was terminal before this control.
- `denied`: reason `CONTROL_DENIED`; required observed/denied non-retryable
  safe error; terminal receipt link forbidden; no control intent is written.
- `not_found`: reason `CONTROL_TARGET_NOT_FOUND`; required observed/invalid
  non-retryable safe error; terminal receipt link forbidden; no intent is
  written.
- `unavailable`: reason `CONTROL_UNAVAILABLE`; required unavailable/unavailable
  retryable safe error and bounded retry-after; terminal receipt link forbidden;
  the durable outcome proves no intent or outbox was committed and no terminal
  target claim is made.
- `deadline_exceeded`: reason `CONTROL_DEADLINE_EXCEEDED`; required
  not-observed/timeout retryable safe error; terminal receipt link forbidden;
  a reserved finalization budget commits the durable no-intent outcome before
  the control deadline; the last target link is retained and no terminal target
  claim is made.

Every disposition requires `finished_at` no earlier than `requested_at`; every
unlisted reason/error/link combination is rejected. `accepted` SHALL mean only
that cancellation intent was durably admitted. An operation or process SHALL
enter `cancelled` only after the owner records terminal cancellation evidence.
Signal delivery, caller disconnect or observation timeout alone SHALL NOT prove
cancellation. Once intent commits, the API SHALL return or recover `accepted`
even if delivery or application later reaches a deadline; finite observation
reports that later state and SHALL NOT replace the accepted receipt with
`unavailable` or `deadline_exceeded`. A crash before the atomic intent
transaction commits leaves no control claim, receipt, intent or outbox; a crash
after any receipt transaction commits recovers the same disposition, and only
an accepted disposition recovers intent and dispatch. Every control deadline
SHALL reserve finite receipt-finalization budget and SHALL NOT begin a target
step that consumes that reserve.

#### Scenario: A cancel request is accepted while work is still running
- **WHEN** the owner durably records cancellation intent before work exits
- **THEN** the control receipt is accepted while the operation remains running or waiting until a terminal owner receipt is observed

#### Scenario: Cancellation control times out
- **WHEN** the owner cannot resolve a durable control disposition before the control deadline but reserved receipt-finalization budget remains
- **THEN** one durable deadline-exceeded or unavailable receipt commits with no intent/outbox and does not claim the work was cancelled

#### Scenario: Control application outlives admission
- **WHEN** intent and the accepted receipt commit but delivery or target application does not finish within a caller observation deadline
- **THEN** duplicate control admission returns the same accepted receipt and finite observation reports the non-terminal or timeout state separately

#### Scenario: Control admission crashes at the intent boundary
- **WHEN** the owner crashes immediately before or after the atomic control-receipt transaction commits
- **THEN** recovery observes respectively no claim/receipt/intent/outbox or the same durable disposition, with intent/outbox present exactly for accepted

#### Scenario: Control receipt persistence fails
- **WHEN** the owner cannot commit the control claim and immutable receipt within the reserved deadline budget
- **THEN** it returns `CONTROL_RECEIPT_UNAVAILABLE` as an ErrorEnvelope with no ControlReceipt, intent or outbox

#### Scenario: Multiple child controls share one parent
- **WHEN** two control commands inherit one correlation and causation but have different request message identities
- **THEN** their receipts remain distinguishable by request identity, and retry/redelivery preserves each original receipt identity

#### Scenario: A replay-derived control is authorized
- **WHEN** replay processing derives a new cancellation or shutdown control
- **THEN** the receipt attributes the new request to the current verified replay initiator while historical attribution remains only in ReplayContext

### Requirement: Shutdown SHALL have one finite deadline and explicit residual ownership

A shutdown API SHALL close admission and return a `ShutdownReceipt` containing
owner namespace/instance identity, fence generation, control/correlation/
optional causation identity, the exact original `request_message_id`, trusted
initiator, optional operation/process links, request/deadline/finished time,
closed shutdown state/current stage/reason, graceful/forced termination counts,
bounded residual owners, owner-scoped recovery descriptors and a safe error.
`completed` SHALL require stage `done`, zero live owned work, durable terminal
audit, released non-reentrant resources and release of only the matching
generation fence. Deadline-exceeded, incomplete or failed shutdown SHALL retain
owner fencing and report stage/reason/residual/recovery facts.

The trusted initiator SHALL be the bounded credential-free `ActorContext` that
requested shutdown. `control_id` SHALL resolve for the receipt retention period
to an immutable actor-bearing `ControlReceipt` with the same request message,
initiator, correlation and causation. A mismatch SHALL be corruption. The
causation field SHALL be absent in both records for a root control and equal the
direct parent in both records for a child control. The
optional Platform process link SHALL be `OpaqueId | None` and SHALL NOT require
a Platform import of Processes contracts.

Fence generation SHALL be an integer 1-9,223,372,036,854,775,807 durably
claimed before admission. Every write or terminal receipt from an older
generation SHALL be rejected. Crash takeover may claim only the next generation
after durable proof that the prior lease expired or was revoked, and SHALL
record takeover causation; restart SHALL NOT reuse owner instance or generation.

Residual ownership SHALL use only `process_group`, `executor_task`,
`python_thread`, `persistence_audit`, `writer_lease` and `inflight_start`, with
at most 16 entries. Each entry SHALL contain count 1-2,147,483,647 and a
non-secret `OpaqueId` inspection selector. Platform-owned
`ShutdownRecoveryAction` SHALL use at most 16 entries and only
`inspect_residual`, `retry_terminal_audit`, `terminate_process_group`,
`retry_shutdown_with_deadline`, `revoke_expired_writer_lease` or
`operator_intervention`, plus target/reason/expiry/scope. It SHALL be
informational and SHALL NOT depend on Processes contracts. Shutdown stages
SHALL be `close_admission`, `request_graceful`, `force_process_tree`,
`drain_delivery`, `commit_terminal_audit`, `release_resources`,
`release_fence` or `done`.

The shutdown state product SHALL be exact. `completed` requires `done`,
`SHUTDOWN_COMPLETED`, no safe error, zero residual/recovery entries, durable
terminal audit, released resources and release of only the matching fence.
`deadline_exceeded` requires a non-`done` stage,
`SHUTDOWN_DEADLINE_EXCEEDED`, an observed timeout error, at least one residual
and applicable recovery action, and a retained fence. `incomplete` requires a
non-`done` stage, a stable non-deadline reason, an observed blocked or
unavailable error, at least one residual and applicable recovery action, and a
retained fence. `failed` requires a non-`done` stage, a stable failure reason,
an observed internal or unavailable error, at least one residual (including
writer/audit ownership when appropriate), an applicable recovery action and a
retained fence. Every unlisted state/stage/reason/error/residual/recovery/fence
combination SHALL be rejected.

Every potentially blocking shutdown stage, including lock acquisition,
persistence retry, queue drain, thread/future/executor/subprocess wait and
process-tree termination, SHALL consume the remaining shared deadline. A
bounded public API SHALL NOT perform an unbounded join after its deadline.

#### Scenario: A child process ignores graceful termination
- **WHEN** the child remains alive after the graceful portion of the shared deadline
- **THEN** the process owner applies its reviewed forced process-tree policy within the same deadline and records the outcome and residual ownership

#### Scenario: An executor task cannot be interrupted
- **WHEN** executor shutdown would wait beyond the shared deadline
- **THEN** shutdown returns incomplete or deadline-exceeded without an unbounded `shutdown(wait=True)`, keeps the ownership fence closed and reports the residual task

#### Scenario: Multiple callers request shutdown
- **WHEN** concurrent callers stop the same owner
- **THEN** they observe the same bounded stop attempt or its terminal receipt and no caller waits indefinitely on another caller

#### Scenario: Shutdown completes
- **WHEN** all owned work is terminal, durable receipts are committed and non-reentrant resources are released before the deadline
- **THEN** exactly one completed shutdown receipt reports zero residual owners

#### Scenario: A stale owner writes after takeover
- **WHEN** generation N+1 has durably taken over and generation N attempts a state or terminal-audit write
- **THEN** the repository rejects the stale writer and the N+1 receipt retains takeover causation

#### Scenario: A runtime adopts the control contract
- **WHEN** EventBus, Web resources, RuntimeCommandRunner or FastAPI lifespan would route through these contracts
- **THEN** adoption is blocked until `runtime-owner-shutdown-and-recovery-hardening-v1` has strict approval and passing persistence-retry, concurrent-stop, startup-cleanup, executor-tail, monotonic-wait, crash-takeover and real signal-to-reap fixtures
