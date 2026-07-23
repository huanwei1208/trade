## ADDED Requirements

### Requirement: Trade SHALL evolve as a domain-modular monolith

The repository SHALL evolve toward `src/trade` with the business contexts
Capture, Datasets, Studies and Decision Support; technical Platform; Processes;
Interfaces; Bootstrap; and a minimal Kernel. `web/` and `engine/` SHALL remain
separate component roots. This target layout SHALL be reached incrementally and
SHALL NOT authorize a wholesale directory move.

#### Scenario: A current module is prepared for migration

- **WHEN** a child change proposes moving or extracting a current module
- **THEN** it records the module's aggregate, authoritative writer, public
  consumers, current tables/artifacts, imports, target owner, compatibility
  bridge, validation and rollback before changing its location

#### Scenario: A current directory has mixed responsibilities

- **WHEN** a directory such as `trade_py/analysis`, `trade_py/evaluation`,
  `trade_py/evidence`, `trade_py/observatory`, `trade_py/factors` or
  `trade_py/intelligence` contains files with different aggregate ownership
- **THEN** each file is classified independently and no bulk directory rename is
  treated as an architecture migration

### Requirement: Business contexts SHALL own cohesive facts and state machines

Capture SHALL own provider interaction and raw receipts; Datasets SHALL own
canonical versions, snapshots, release, quality, lineage and PIT resolution;
Studies SHALL own registered hypotheses and validation results; Decision Support
SHALL own human-assistance cases and audit. Observatory SHALL remain a product
surface and SHALL NOT become a business context.

#### Scenario: A reusable factor is introduced

- **WHEN** the factor has independent schema, lineage, versioning and release
  requirements and can be used by multiple studies
- **THEN** it is designed as a derived Dataset product rather than a Studies
  implementation detail

#### Scenario: A fold-local transform is introduced

- **WHEN** a transform exists only within one StudyRun, including a placebo,
  experimental interaction or local label
- **THEN** it remains Study-local and is not published as a Dataset product

### Requirement: Kernel SHALL remain minimal and framework-independent

Kernel SHALL contain only IDs, time, digests, errors, results and envelopes
whose semantics are identical across at least two contexts, have no business
owner and do not depend on a framework or concrete adapter.

#### Scenario: A context-specific value object appears reusable

- **WHEN** the value object still has a business owner or differs in meaning
  across contexts
- **THEN** it remains context-local even if this creates a small amount of
  duplication
