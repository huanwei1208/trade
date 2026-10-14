## ADDED Requirements

### Requirement: The optional native extension SHALL use the distinct `_trade_native` module name

The optional C++ extension SHALL use `_trade_native` for its target, output artifact and nanobind/Python initializer.
The extension SHALL NOT use
`trade_py`, `trade` or a Context package name. Importing the Python
distribution SHALL not implicitly import native code.

Before enablement, implementation SHALL reconcile the actual tracked binding
sources, build target, initializer symbol, artifact name, wheel member and
supported Python ABI/platform tags. Missing or inconsistent binding sources
SHALL leave native capability unavailable and SHALL NOT be repaired with
invented generated source.

#### Scenario: Binding sources referenced by CMake are absent
- **WHEN** the build graph references binding sources that are not present in the reviewed source generation
- **THEN** the native slice remains blocked, reports the missing sources and leaves all Python behavior on its existing path

#### Scenario: Target and initializer names differ
- **WHEN** CMake emits `_trade_native` but the compiled initializer or wheel member exposes another module name
- **THEN** clean-install validation rejects the artifact before any adapter can select it

#### Scenario: The native artifact is not installed
- **WHEN** an environment uses a supported pure Python installation
- **THEN** native capability reports unavailable with no package import failure and no silent claim that the C++ implementation executed

### Requirement: Native code SHALL be consumed only by Context-owned adapters behind Ports

Native imports SHALL exist only in approved Context-owned `adapters/native` modules.
Only approved adapters owned by Capture, Datasets, Studies or Decision Support
MAY import `_trade_native`. Domain, use-case, contracts,
Ports, Processes, Platform, Interfaces, Bootstrap and compatibility modules
SHALL NOT import it directly.

Each native adapter SHALL implement an owner Port and map values, errors,
timeouts and unavailable states without leaking native object types into
contracts or domain code.

#### Scenario: A Study use case requests native calculation
- **WHEN** the configured Studies adapter supports the operation
- **THEN** the use case calls its Studies Port and receives owner-domain values without importing or exposing `_trade_native`

#### Scenario: A domain module imports the extension
- **WHEN** the architecture guard detects `_trade_native` outside an approved owner adapter
- **THEN** validation fails and the module cannot become target-authoritative

### Requirement: Native selection SHALL preserve semantics and expose availability

For every selected native operation, the owner SHALL define deterministic
Python/native differential fixtures, accepted numeric tolerance where
applicable, error mapping, input bounds and unsupported-platform behavior.
Native selection SHALL NOT silently change an algorithm, unit, timezone,
ordering, missing-value policy, PIT/revision policy, recommendation or
decision behavior.

#### Scenario: Python and native outputs differ outside the owner tolerance
- **WHEN** a differential fixture detects a semantic, ordering, error or numeric mismatch
- **THEN** native activation is blocked and the existing reviewed implementation remains authoritative

#### Scenario: Native execution fails at runtime
- **WHEN** the extension is present but an operation returns an unsupported, invalid or internal failure
- **THEN** the owner adapter returns the reviewed explicit state and SHALL NOT silently substitute another implementation unless owner policy and receipt explicitly authorize that fallback

### Requirement: Legacy native probing SHALL retire only after clean import proof

The current `trade_py` self-import probe SHALL NOT be treated as native
availability. It may be replaced by an explicit compatibility capability probe
only after `_trade_native` builds and imports in a clean environment. The
compatibility probe SHALL be side-effect free and SHALL not expose the native
module as the `trade_py` package.

#### Scenario: The legacy package imports itself
- **WHEN** availability code observes only the already-initializing `trade_py` package
- **THEN** it reports no proof of native capability and cannot return that package as a C++ binding

#### Scenario: A clean native wheel is installed
- **WHEN** `_trade_native` imports and its capability/version metadata match the reviewed adapter contract
- **THEN** the compatibility probe may report available while Python package identity and extension identity remain distinct
