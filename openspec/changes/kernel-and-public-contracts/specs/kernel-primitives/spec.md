## ADDED Requirements

### Requirement: Kernel SHALL contain only admitted framework-free primitives

Kernel SHALL contain only identity, UTC time/deadline, digest, structural
contract error, result, envelope metadata and immutable-reference identity
primitives whose semantics are identical for at least two Contexts, have no
business owner and require no third-party framework. Kernel SHALL NOT contain
provider, Dataset, Study, recommendation, portfolio, process, HTTP, database,
filesystem, DataFrame, scheduler, EventBus or native-runtime semantics.

#### Scenario: A business value appears reusable
- **WHEN** two modules use similarly shaped values but the values have different business owners or invariants
- **THEN** the values remain in their owner contracts and are not promoted to Kernel

#### Scenario: A Kernel module is imported from an installed wheel
- **WHEN** a clean Python environment imports every public Kernel symbol
- **THEN** no `trade_py`, `trade_web`, FastAPI, Pydantic, pandas, ORM, database, native extension or application bootstrap module is imported

### Requirement: Kernel identifiers SHALL be opaque, bounded and namespace-qualified

An opaque identifier SHALL contain a non-empty bounded ASCII namespace and
value, SHALL have no ordering semantics, and SHALL serialize both fields
explicitly. Generated identifiers SHALL use UUID4 without exposing generation
as business meaning. A legacy integer identifier SHALL be represented in a
named legacy namespace and SHALL NOT be silently treated as a globally
generated target identifier.

#### Scenario: A legacy Web run ID is mapped
- **WHEN** compatibility code maps `job_runs.id=17`
- **THEN** it produces an opaque identity such as namespace `legacy.job_run` and value `17` without implying UUID generation or cross-table uniqueness

#### Scenario: An invalid identifier is decoded
- **WHEN** an identifier has an empty field, unsupported character, unbounded value or unknown object shape
- **THEN** decoding fails with a structural contract error before a domain or adapter is called

### Requirement: Kernel time and deadline values SHALL preserve UTC and elapsed-time semantics

Wire instants SHALL be timezone-aware UTC values serialized as RFC3339 with a
`Z` suffix. Durations SHALL be positive bounded integer milliseconds. A
durable deadline SHALL record a UTC wall-clock instant, while a local wait
SHALL derive and consume a monotonic remaining duration; wall-clock movement
SHALL NOT extend a local wait.

#### Scenario: A naive datetime is supplied
- **WHEN** a caller constructs or decodes a time without timezone evidence
- **THEN** the Kernel rejects it rather than assuming local time or UTC

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
closed safe code and bounded detail; they SHALL NOT serialize a live exception,
cause, traceback, SQL, path, credential or raw payload.

#### Scenario: Both result branches are supplied
- **WHEN** construction receives both a value and an error or receives neither
- **THEN** the result is rejected as an invalid contract state

#### Scenario: An adapter exception reaches a contract boundary
- **WHEN** compatibility code catches a legacy exception
- **THEN** it maps only reviewed safe facts into an owner error contract and does not place the exception object in a Kernel result

### Requirement: Envelope metadata SHALL be transport-neutral and owner-payload typed

Kernel envelope metadata SHALL contain versioned message identity,
correlation/causation identity and creation time only. The envelope payload
SHALL be supplied by a typed owner codec. Kernel SHALL NOT dispatch, persist,
retry, acknowledge or inspect business payload dictionaries.

#### Scenario: An EventBus event is mapped
- **WHEN** compatibility code maps a durable legacy event
- **THEN** it copies durable metadata accepted by the owner codec and excludes the live EventBus back-reference and unreviewed arbitrary payload

#### Scenario: A caller supplies an arbitrary mapping payload
- **WHEN** no registered owner codec exists for that mapping
- **THEN** canonical envelope construction fails rather than accepting `dict[str, Any]` as a public contract
