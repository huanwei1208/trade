## ADDED Requirements

### Requirement: Skill triggers for code-producing work
The repository-local code-quality skill SHALL trigger for implementation,
refactoring, bug fixes, optimization, review fixes, and generated code that touch
Python, Shell, C/C++, Java/Maven, TypeScript/JavaScript, tests, configuration, or public
contracts in this repository.

#### Scenario: Agent is asked to add a Python service
- **WHEN** an agent begins the implementation task
- **THEN** it loads the code-quality skill and the Python/shared references before editing

#### Scenario: Mixed engine and frontend task
- **WHEN** an agent changes C++ and TypeScript files
- **THEN** it loads the shared, C++, and web references without loading unrelated language detail

#### Scenario: Java driver task
- **WHEN** an agent changes the Maven JDBC driver
- **THEN** it loads the shared and Java references and validates formatting plus the module tests

### Requirement: Skill enforces a pre-edit quality contract
Before a non-trivial edit, the skill SHALL require the agent to identify the behavior
boundary, owner module, public compatibility, failure/unknown semantics, tests, and
adjacent regression risk. It SHALL preserve unrelated dirty state and avoid broad
formatting churn.

#### Scenario: Proposed logic would be added to a CLI catch-all
- **WHEN** business logic belongs in a service or domain module
- **THEN** the skill directs the agent to keep the CLI as a facade and place behavior under the owner module with focused tests

### Requirement: Hard rules and judgment rules are distinct
The skill SHALL treat machine-detectable correctness, formatting, unsafe exception,
test isolation, and required validation failures as blockers. It SHALL treat file
size, function size, complexity, parameter count, and abstraction style as review
signals requiring contextual judgment rather than automatic rejection.

#### Scenario: Long function has no coherent extraction boundary
- **WHEN** a long function exceeds a review heuristic but extraction would fragment one state machine
- **THEN** the agent documents the rationale and tests the coherent behavior instead of performing a mechanical split

### Requirement: Financial and data safety rules remain first-class
For data, model, recommendation, causal, trust, or backtest changes, the skill SHALL
require explicit units, point-in-time behavior, evidence, confidence/calibration,
unknown/failure states, and temporary test data. It SHALL reject silent fallback or
real-data mutation that was not explicitly authorized.

#### Scenario: Model path substitutes a neutral probability after quality failure
- **WHEN** required evidence or calibration is missing
- **THEN** the skill requires an explicit unavailable reason and tests rather than allowing a silent numeric fallback

### Requirement: Completion requires reproducible evidence
The skill SHALL prohibit declaring a code task complete until the changed-file gate,
focused tests, required language build/type checks, diff hygiene, and relevant
performance sanity have been run or an explicit blocker/no-test reason is recorded.
The report SHALL list commands and outcomes.

#### Scenario: Formatter passes but behavior tests were skipped
- **WHEN** a behavior change has only formatting/lint evidence
- **THEN** the skill treats completion as incomplete until focused behavior tests pass or a concrete residual-risk exception is recorded

### Requirement: Skill metadata and references are valid
The skill SHALL contain valid name/description frontmatter, matching UI metadata,
one-level language references, and no extraneous README or process-history files. It
SHALL pass the official `quick_validate.py` validator.

#### Scenario: Skill package is validated
- **WHEN** the repository skill is ready for commit
- **THEN** quick validation succeeds and every reference named by SKILL.md exists
