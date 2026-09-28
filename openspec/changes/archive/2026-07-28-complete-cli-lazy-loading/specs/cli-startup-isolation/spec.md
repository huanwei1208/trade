## ADDED Requirements

### Requirement: Selected-domain lazy loading
The root CLI SHALL parse domain selection and top-level help without importing unselected canonical or legacy domain modules.

#### Scenario: Top-level help
- **WHEN** a user requests root help
- **THEN** the CLI prints help without importing data, web, research, job, evaluation, or model runtime stacks

#### Scenario: Selected domain
- **WHEN** a user invokes one canonical domain
- **THEN** the CLI imports and dispatches only that domain module

#### Scenario: Unrelated optional dependency failure
- **WHEN** an optional dependency for an unselected domain is unavailable
- **THEN** unrelated domain help and commands remain usable

### Requirement: Help is read-only and runtime-independent
Domain help SHALL parse before DB, bus, scheduler, provider, model, or evaluation runtime initialization.

#### Scenario: Run help
- **WHEN** a user invokes `trade run --help`
- **THEN** help exits successfully without creating or migrating a data root

#### Scenario: Evaluation help
- **WHEN** a user invokes canonical or legacy evaluation help
- **THEN** help exits successfully without importing the evaluation service implementation

### Requirement: Canonical and legacy routing compatibility
The CLI SHALL preserve canonical command behavior and legacy aliases while emitting deprecation warnings only for deprecated entrypoints.

#### Scenario: Canonical research command
- **WHEN** a user invokes `trade research model`, `factor`, or `evaluate`
- **THEN** the selected command uses canonical help/prog text and emits no deprecation warning

#### Scenario: Legacy research alias
- **WHEN** a user invokes the old top-level model, factor, or evaluate domain
- **THEN** the command remains callable and emits its migration warning

#### Scenario: Direct execution
- **WHEN** the CLI main file or module is executed directly
- **THEN** absolute dynamic imports preserve the supported dispatch behavior

### Requirement: Deferred-import correctness
Moving imports SHALL NOT widen silent fallback behavior or leave runtime annotations unresolved.

#### Scenario: Settings dependency failure
- **WHEN** the K-line settings dependency cannot be imported
- **THEN** the failure surfaces instead of silently selecting the default start date

#### Scenario: Runtime annotation inspection
- **WHEN** runtime type hints are inspected on affected evaluation or KG helpers
- **THEN** all referenced annotation names resolve successfully

### Requirement: Generated local state stays out of commits
Repository ignore rules SHALL exclude known editor and generated data artifacts without ignoring source modules or reviewed fixtures.

#### Scenario: Local runtime files
- **WHEN** `.nvim` state, repository-local runtime DB files, or legacy generated cross-asset parquet files exist
- **THEN** Git does not present them as source changes
