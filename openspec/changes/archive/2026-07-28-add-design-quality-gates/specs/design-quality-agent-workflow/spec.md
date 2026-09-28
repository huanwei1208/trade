## ADDED Requirements

### Requirement: Two-phase pre-code design workflow
The repository-local skill SHALL require agents to inspect current repository structure, declare structured applicability/obligations, write a Design Quality Brief, run a non-strict pre-review check with zero blockers, complete consensus review, record digest-bound review evidence, and pass strict implementation approval before implementing a medium or large change.

#### Scenario: Agent starts a governed change
- **WHEN** an agent prepares a medium or large implementation
- **THEN** the skill requires repository evidence, governed structured artifacts, pre-review output, six-role review, fresh approval evidence, and strict checker output before code changes begin

### Requirement: Design Quality Brief coverage
The workflow SHALL require explicit evidence for requirements and acceptance, ownership and boundaries, data and state invariants, contracts and compatibility, failure and recovery, performance and capacity, observability and operations, validation, alternatives and trade-offs, and rollout and rollback.

#### Scenario: A design omits failure behavior
- **WHEN** a governed design has no substantive failure and recovery section
- **THEN** the workflow reports a blocking finding and does not approve implementation

### Requirement: Domain-sensitive financial design evidence
Explicit impacts SHALL select point-in-time/predictive, persistent-write/schema, public-contract, or external-event profiles. Financial/predictive designs SHALL provide the full temporal, evidence identity, calibration lifecycle, unavailable-state, and heuristic-versus-validated evidence required by the selected policy profile.

#### Scenario: Forecast design claims predictive value without calibration
- **WHEN** a forecast design omits calibration state or labels unvalidated heuristics as validated output
- **THEN** the workflow rejects the design with stable financial-semantics rule IDs

### Requirement: Human review remains authoritative
The skill SHALL describe automated evidence approval as necessary but insufficient and SHALL preserve six-role consensus review. Findings SHALL be recorded with stable IDs and current artifact digest; unresolved P0, incomplete roles, stale evidence, or blocked final status SHALL prevent strict implementation approval.

#### Scenario: Pre-review check passes but review finds a P0 issue
- **WHEN** the non-strict pre-review check has no blockers and a consensus judge records a P0 finding
- **THEN** implementation remains blocked until the finding is resolved and re-reviewed

### Requirement: Minimal and referenced guidance
The skill SHALL form one canonical design phase that hands off to the existing code-quality implementation phase, keep the main workflow concise, reference immutable policy/profile material, and avoid duplicating the full registry or competing implementation guidance in `SKILL.md`.

#### Scenario: Policy rule changes
- **WHEN** a maintainer changes a rule ID or severity
- **THEN** the versioned policy and tests are the authoritative update surface, while the skill continues to reference the registry
