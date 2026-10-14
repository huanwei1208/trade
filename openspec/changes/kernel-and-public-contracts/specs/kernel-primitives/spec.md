## ADDED Requirements

### Requirement: Kernel SHALL contain only admitted framework-free primitives

Kernel SHALL contain only identity, UTC time/deadline, digest, structural
contract error, result and envelope metadata primitives whose semantics are
identical for at least two Contexts, have no business owner and require no
third-party framework. Its module allowlist is exactly `ids`, `time`, `digest`,
`errors`, `result` and `envelope`. Kernel SHALL NOT contain generic reference,
policy, actor, provider, Dataset, Study, recommendation, portfolio, process,
HTTP, database, filesystem, DataFrame, scheduler, EventBus or native-runtime
semantics.

#### Scenario: A business value appears reusable
- **WHEN** two modules use similarly shaped values but the values have different business owners or invariants
- **THEN** the values remain in their owner contracts and are not promoted to Kernel

#### Scenario: A Kernel module is imported from an installed wheel
- **WHEN** a clean Python environment imports every public Kernel symbol
- **THEN** no `trade_py`, `trade_web`, FastAPI, Pydantic, pandas, ORM, database, native extension or application bootstrap module is imported

### Requirement: Kernel identifiers SHALL be opaque, bounded and namespace-qualified

An opaque identifier SHALL contain a namespace of 1-64 ASCII lower-case
letters/digits plus `._-` and a value of 1-128 printable ASCII characters
excluding whitespace/control. It SHALL have no ordering semantics and SHALL
serialize both fields explicitly. Generated identifiers SHALL use UUID4 without
exposing generation as business meaning. A legacy integer identifier SHALL be
represented in a named legacy namespace and SHALL NOT be silently treated as a
globally generated target identifier.

#### Scenario: A legacy Web run ID is mapped
- **WHEN** compatibility code maps `job_runs.id=17`
- **THEN** it produces an opaque identity such as namespace `legacy.job_run` and value `17` without implying UUID generation or cross-table uniqueness

#### Scenario: An invalid identifier is decoded
- **WHEN** an identifier has an empty field, unsupported character, unbounded value or unknown object shape
- **THEN** decoding fails with a structural contract error before a domain or adapter is called

### Requirement: Kernel time and deadline values SHALL preserve UTC and elapsed-time semantics

Wire instants SHALL be timezone-aware UTC values serialized in the sole
canonical form `YYYY-MM-DDTHH:MM:SS.ffffffZ`: a four-digit year from `0001`
through `9999`, seconds from `00` through `59`, exactly six fractional-second
digits including `.000000`, and the literal `Z` suffix. Version 1 wire decoding
SHALL accept only that form; it SHALL reject an offset spelling such as
`+00:00`, omitted or non-six-digit fractional seconds, precision beyond
microseconds and leap seconds. Direct Python construction SHALL accept only an
aware datetime whose UTC offset is exactly zero and SHALL preserve its
microsecond value without an implicit timezone conversion. Durations SHALL be
integer milliseconds in 1-86,400,000. A durable deadline SHALL record a UTC
wall-clock instant, while a local wait SHALL derive and consume a monotonic
remaining duration; wall-clock movement SHALL NOT extend a local wait.

#### Scenario: A naive datetime is supplied
- **WHEN** a caller constructs or decodes a time without timezone evidence
- **THEN** the Kernel rejects it rather than assuming local time or UTC

#### Scenario: Equivalent or over-precise UTC spellings are supplied
- **WHEN** a wire value uses `+00:00`, omits the six fractional digits, carries more than six fractional digits or uses a leap second
- **THEN** version 1 rejects it rather than creating a second spelling or rounding a different instant into the canonical identity

#### Scenario: Canonical fractional-second boundaries are serialized
- **WHEN** accepted UTC values carry zero, one or 999,999 microseconds
- **THEN** they serialize respectively with `.000000Z`, `.000001Z` and `.999999Z`

#### Scenario: Wall clock changes during a wait
- **WHEN** the system wall clock moves after a local deadline has been admitted
- **THEN** the wait remains bounded by the original monotonic duration and the wire receipt retains the declared UTC deadline

### Requirement: Content digests SHALL identify bytes with an explicit algorithm

A content digest SHALL include its algorithm and normalized value. Version 1
SHALL admit SHA-256 lower-case hexadecimal digests only. A digest SHALL
identify exact bytes and SHALL NOT by itself claim schema, owner, version,
quality, provenance or publication state.

#### Scenario: Equal bytes have equal content identity
- **WHEN** two owners hash the same canonical byte sequence with SHA-256
- **THEN** their content digests compare equal while their owner-specific immutable references may remain distinct

#### Scenario: A malformed digest is supplied
- **WHEN** a digest uses an unsupported algorithm, upper-case or non-hex value, or a value of the wrong length
- **THEN** construction fails without normalizing it into a different identity

### Requirement: Results and structural errors SHALL be explicit and immutable

A Kernel result SHALL contain exactly one of a value or a structural contract
error and SHALL not rely on implicit truthiness. Structural errors SHALL use a
closed safe code and detail of at most 1,024 UTF-8 bytes; they SHALL NOT
serialize a live exception, cause, traceback, SQL, path, credential or raw
payload.

#### Scenario: Both result branches are supplied
- **WHEN** construction receives both a value and an error or receives neither
- **THEN** the result is rejected as an invalid contract state

#### Scenario: An adapter exception reaches a contract boundary
- **WHEN** compatibility code catches a legacy exception
- **THEN** it maps only reviewed safe facts into an owner error contract and does not place the exception object in a Kernel result

### Requirement: Envelope metadata SHALL be transport-neutral and owner-payload typed

Kernel envelope metadata SHALL contain versioned message identity,
correlation/causation identity and `envelope_created_at` only. Creation time is
the transport-envelope construction clock and SHALL NOT be interpreted as
provider event/publication/observed/received/available time, PIT evidence or
finality. The envelope payload SHALL be supplied by a typed owner codec. Kernel
SHALL NOT dispatch, persist, retry, acknowledge or inspect business payload
dictionaries.

The v1 causal relation SHALL be exact. A root command/query receives a new
`message_id`, sets `correlation_id=message_id` and has no `causation_id`. A
child command/event receives a new `message_id`, inherits its verified parent's
`correlation_id` and sets `causation_id` to that parent's `message_id`.
Transport retry or redelivery of the same logical envelope preserves all three
identities and canonical envelope bytes; attempt metadata remains outside the
canonical envelope. A newly submitted idempotent duplicate is a new root or
child envelope under these rules, while any returned existing receipt preserves
the original admitted envelope identities. Durable replay preserves the
historical envelope identities; a message newly derived during replay follows
the child rule and points to the replayed historical `message_id`. No adapter
may accept caller payload values as trusted correlation or causation evidence.

Platform message contracts SHALL describe an owner codec with an immutable
descriptor binding owner namespace, schema name/version, payload purpose,
maximum canonical bytes, content policy and deterministic codec identity. This
child SHALL supply only the Platform-owned descriptor value/validator and pure
registry collision/freeze invariants; the later Platform foundation child SHALL
implement the Bootstrap registry builder. Bootstrap SHALL assemble and freeze
that registry before ingress, with unique keys. Kernel supplies only envelope
composition and SHALL NOT own the descriptor or registry. A codec validates
wire shape only and SHALL NOT confer authority, rights, publication, quality or
PIT proof. The immutable-ref-only rule applies to cross-Context/canonical
Platform envelopes. A Capture inbound adapter MAY boundedly receive/stage raw
push, stream, import or provider input inside Capture, but external/raw provider,
news, L2 or stream content SHALL cross the canonical boundary only as a
committed owner-controlled Capture artifact reference.

#### Scenario: An EventBus event is mapped
- **WHEN** compatibility code maps a durable legacy event
- **THEN** it copies durable metadata accepted by the owner codec and excludes the live EventBus back-reference and unreviewed arbitrary payload

#### Scenario: A caller supplies an arbitrary mapping payload
- **WHEN** no registered owner codec exists for that mapping
- **THEN** canonical envelope construction fails rather than accepting `dict[str, Any]` as a public contract

#### Scenario: A child command is emitted from a verified parent event
- **WHEN** a handler creates a new command from an admitted parent envelope
- **THEN** the command gets a new message identity, inherits the parent's correlation identity and names the parent message as its direct causation

#### Scenario: An envelope is redelivered or replayed
- **WHEN** transport redelivers the same logical envelope or an operator replays a durable historical envelope
- **THEN** the canonical message, correlation and causation identities remain unchanged and retry/replay attempt metadata stays outside the envelope

#### Scenario: Two codecs claim one wire identity
- **WHEN** Bootstrap receives duplicate owner/schema/version/purpose descriptors or a codec identity is not deterministic
- **THEN** registry assembly fails before command or event ingress starts

#### Scenario: A news body fits under the envelope limit
- **WHEN** an owner codec is asked to inline external news content rather than a committed Capture artifact reference
- **THEN** it rejects the payload because the byte budget does not grant external-content admission
