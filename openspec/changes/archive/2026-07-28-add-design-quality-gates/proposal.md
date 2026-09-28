## Why

The repository now rejects low-quality implementation at the language/tooling boundary, but an agent can still produce a structurally poor design that passes formatting and tests: unclear ownership, duplicated sources of truth, reversed dependencies, unspecified failure states, unbounded cost, or a public contract with no migration path. Design quality must become an auditable pre-code gate instead of relying on prose scattered across `AGENTS.md`, OpenSpec defaults, and post-hoc review prompts.

## What Changes

- Add a repository-local `design-quality` skill that runs before non-trivial design or implementation and requires a concise Design Quality Brief grounded in current code.
- Add immutable, namespaced `design-policy/v1.toml` constraints separating hard evidence blockers from warning-first structural heuristics and time-bounded exceptions.
- Add read-only `./trade dev design-check <change> [--strict] [--format text|json]` with deterministic reports and stable rule IDs.
- Add per-change `design-quality.toml` applicability/obligation declarations and a digest-bound `design-review.toml` consensus record.
- Integrate strict design checking through an aggregate changed-scope contributor whenever a governed/new OpenSpec design changes, including governance deletion attempts.
- Strengthen OpenSpec and `AGENTS.md` so medium/large changes cannot start implementation with unresolved design blockers or unowned strict warnings.
- Add repository tests and forward tests against data, forecasting, Web/API, and mixed-language design scenarios.

**BREAKING (developer workflow):** new medium/large OpenSpec changes must contain the governed Design Quality Brief and pass strict design review before implementation. Runtime product behavior is unchanged.

Non-goals: automatically proving that a design is optimal; replacing human judgment or the six-role `review-this` consensus; rewriting all historical OpenSpec changes; imposing a universal architecture independent of the owning domain; changing trading, DB, data, API, Web, or engine runtime semantics.

## Capabilities

### New Capabilities

- `design-quality-agent-workflow`: Pre-code structure pass, mandatory Design Quality Brief, applicability profiles, warning resolution, two-phase review, and digest-bound evidence.
- `design-quality-gate`: Immutable policy profiles, deterministic CLI/JSON contract, aggregate changed-scope integration, exceptions, and failure semantics.

## Impact

- Agent workflow: `AGENTS.md`, `.codex/skills/design-quality/`, and existing `review-this` handoff rules.
- OpenSpec: `openspec/config.yaml`, `design-quality.toml`, `design-review.toml`, a required Design Quality Brief structure, and strict approval validation before implementation.
- Developer tooling: `trade`, `trade_py/cli/dev.py`, focused `trade_py/devtools/design_quality/` modules, immutable `design-policy/v1.toml`, an aggregate plan-contributor seam, and explicit nested exit-code/result handling.
- Tests: temporary change fixtures, CLI/lazy-loading/no-DB coverage, policy/parser/report tests, automatic quality-plan routing, and skill forward tests.
- Compatibility: additive CLI and deterministic JSON schema; existing `trade dev check|fix|quality|review` behavior remains. Historical changes are not bulk-rewritten and only become governed when explicitly migrated or used as the target of strict design approval.
- Data safety: all design checks are filesystem read-only, never construct `TradeDB`, never inspect real parquet/DB contents, and never use network access.
