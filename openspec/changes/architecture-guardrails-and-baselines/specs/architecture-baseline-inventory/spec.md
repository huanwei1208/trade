## ADDED Requirements

### Requirement: The legacy architecture baseline SHALL be source-verified and non-authoritative

The repository SHALL maintain a versioned architecture baseline that records
current package roots, schema-definition sources, physical table
classifications, native binding facts, and compatibility-pointer facts. The
quality gate SHALL validate each entry against source text only. The baseline
SHALL not initialize an application, open a database, read an artifact, or
claim final runtime ownership.

#### Scenario: A baseline table source changes

- **WHEN** a child moves or rewrites a source-defined table declaration
- **THEN** the baseline validation fails until that child updates the declared
  source fact, classification, compatibility note, and focused migration
  evidence in the same reviewed change

#### Scenario: A table requires further classification

- **WHEN** the current source inventory identifies a KG, causal, factor, or
  historical recommendation record whose target Context is not yet proven
- **THEN** the baseline marks it `deferred`, and no target module treats the
  declaration as authority to read or write that record

### Requirement: Compatibility and native baseline facts SHALL remain explicit

The baseline SHALL record the current BTC compatibility pointer and C++ Python
binding target as source facts. A later Dataset, package-layout, or native
child SHALL retain the legacy fact until it passes its own compatibility,
native-boundary, and rollback criteria.

#### Scenario: A package transition proposes a native rename

- **WHEN** a package-layout child replaces the `trade_py` native binding target
- **THEN** it updates the baseline only after source/editable/wheel and
  C++/Python differential evidence proves the `_trade_native` boundary and
  retains a compatible rollback path

#### Scenario: A Dataset release replaces the BTC pointer

- **WHEN** a Dataset migration proposes a replacement for the recorded BTC
  compatibility pointer
- **THEN** it preserves the current pointer as a compatibility reader or
  rollback source until dual-read comparison or a readiness-gated switch has
  passed
