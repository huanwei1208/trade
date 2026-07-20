---
name: code-quality
description: Enforce repository-specific design, implementation, formatting, lint, type, test, data-safety, and completion gates for code-producing work in trade. Use for implementations, refactors, bug fixes, optimizations, review fixes, or generated code that touch Python, Shell, C/C++, Java/Maven, TypeScript/JavaScript, tests, configuration, CLI/API/DB/data contracts, or cross-language workflows.
---

# Code Quality

Prevent a syntactically valid patch from being treated as a finished change when its
ownership, failure behavior, tests, or language checks are weak.

For a medium/large change, use `$design-quality` first and begin this workflow only
after its digest-bound strict approval passes. If implementation changes approved
design artifacts or architecture assumptions, return to `$design-quality`; do not
silently absorb design drift here.

## Load the relevant rules

Read [references/shared.md](references/shared.md) for every task. Then read only the
references matching the changed files:

- Python or Python tests: [references/python.md](references/python.md)
- `trade` or Shell scripts: [references/shell.md](references/shell.md)
- C/C++ or CMake: [references/cpp.md](references/cpp.md)
- Java or Maven: [references/java.md](references/java.md)
- TypeScript/JavaScript/React: [references/web.md](references/web.md)

For mixed changes, load every applicable reference. Treat an unrecognized first-party
source language as a blocker: extend the quality provider and this routing list before
declaring completion.

## Work in this order

1. Run `git status -sb`; preserve unrelated changes, local data, caches, and generated
   artifacts.
2. For small non-trivial work not governed by `$design-quality`, state a short quality
   brief before editing:
   - behavior and non-goals;
   - owner module and public compatibility;
   - failure/unknown semantics;
   - focused tests and adjacent regression risks;
   - performance and data-safety concerns.
3. Inspect the actual caller, owner, tests, and native tool configuration. Do not infer
   architecture from filenames alone.
4. Keep facades thin. Put business behavior, persistence, adapters, and UI state in
   their owner modules. Do not grow a catch-all to save a file creation.
5. Implement the smallest coherent slice with tests. Preserve normal adjacent
   behavior and explicit unknown/failure states.
6. Inspect the diff before formatting. Use `./trade dev fix` only when source mutation
   is intended; never stage or commit formatter output blindly.
7. Run `./trade dev check --show-plan`, then `./trade dev check`. Run focused behavior
   tests and the language-specific build/type checks from the loaded references.
8. Run `./trade dev check --all` as a hard debt/readiness audit when requested or
   before a baseline-clean rollout. A nonzero result is evidence of remaining debt,
   never a passing gate.
9. Run `git diff --check` and a final `git status -sb`. Stage only intentional files.

## Distinguish blockers from judgment

Block completion on failed formatting/lint/type/syntax/build tests, unsafe exception
handling, hidden writes, real-data test mutation, missing behavior tests, global
suppressions, silent fallback, unsupported source files, or an unexplained skipped
required check.

Treat file/function size, complexity, nesting, parameter count, and abstraction count
as review signals. Refactor when a coherent boundary exists. If extraction would
fragment one state machine or obscure invariants, keep it together and document the
rationale with tests. Do not perform mechanical splitting to satisfy a number.

## Protect validation integrity

- A formatter pass is not behavior validation.
- A mock-only unit test is not enough when a public CLI/API/storage boundary changed.
- Never weaken a rule, add a blanket ignore, or update a golden file only to turn the
  gate green. Use the narrowest suppression with rule, scope, reason, owner, and
  expiry.
- For financial/data/model changes, require explicit units, point-in-time behavior,
  evidence, calibration/confidence, and unavailable reasons. Never replace missing
  evidence with a neutral numeric value.
- Use temporary roots/DBs/fixtures in tests. Real `data/`, DB, parquet, model, vendor,
  and generated-source paths are not formatter targets.

## Report completion

Report:

- what changed and where ownership lives;
- exact checks/tests and outcomes;
- quality-gate status and any missing tools;
- compatibility, data, performance, and suppression risks;
- any skipped validation with a concrete reason and follow-up.

Do not say the task is complete while a required check is failing or an implementation
task remains.
