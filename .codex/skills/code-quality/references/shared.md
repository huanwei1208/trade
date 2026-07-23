# Shared rules

## Boundaries

- Keep `trade` and `trade_py/cli/*` as parsing/routing facades.
- Keep domain/service behavior out of CLI, HTTP handler, and persistence modules.
- Keep SQL and DB lifecycle in owner repositories/DB modules.
- Keep engine implementation inside `engine/` and frontend state/presentation inside
  `trade_web/frontend/src/`.
- Preserve public CLI, API, DB, parquet, model, and engine contracts or document the
  migration/default/fallback explicitly.

## Correctness blockers

- Reject swallowed exceptions, ambiguous units, implicit timezone conversion,
  mutable global state without ownership, hidden I/O, and silent partial success.
- Preserve root cause and context in errors; do not log and discard a required
  failure.
- Make retries bounded and idempotent. Make writes atomic or recoverable.
- Represent unavailable/unknown separately from zero, empty, neutral, or `watch`.
- Never mutate vendored/generated source, runtime data, models, DBs, or parquet unless
  the task explicitly targets them with backup/dry-run/verification/rollback.

## Tests

- Add or update tests for every behavior change near the owning path.
- Cover success, boundary, invalid input, unavailable dependency, and failure/rollback
  behavior as applicable.
- Use temporary repositories, roots, DBs, and fixtures. Do not depend on live network
  or real local data for unit tests.
- Test public CLI/API/storage contracts at the boundary in addition to pure helpers.
- Keep deterministic clocks, randomness, ordering, locale, and timezone behavior.

## Review signals

Investigate functions above roughly 60 lines, files above roughly 600 lines,
complexity above roughly 10, deep nesting, more than roughly 7 parameters, repeated
conditionals, and mixed I/O/domain/rendering. These are prompts to find a coherent
boundary, not automatic failures.

## Suppressions and generated changes

- Prefer fixing the cause. If a suppression is necessary, narrow it to one rule and
  the smallest path/line, with reason, owner, and expiry.
- Reject blanket Ruff/BasedPyright/Prettier/ESLint/formatter/NOLINT exclusions added for a green
  run.
- Inspect lockfiles and generated config changes for an intentional owner change;
  never hand-edit opaque generated sections.

## Completion fallback

If `./trade dev check` is unavailable on an older branch, run the applicable native
commands from the language reference plus `git diff --check`. Record that the unified
gate was unavailable; do not claim it passed.
