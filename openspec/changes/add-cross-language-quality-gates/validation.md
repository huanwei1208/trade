# Validation Record

## Changed-scope hard gate

- `./trade dev check --show-plan` produced a non-executing plan for 65 eligible files and 14 deterministic steps.
- `./trade dev check --show-plan --format json` produced the versioned machine-readable plan without executing tools.
- The final `./trade dev check` passed: 66 files, 14 results. The gate covered Ruff, BasedPyright, Python syntax, configuration and lock consistency, suppression and text audits, ShellCheck and Bash syntax, Spotless, ESLint, Prettier, and TypeScript.
- `./trade dev fix` passed before the final check and only rewrote selected owned files.
- Protected runtime data, databases, parquet, model artifacts, vendor trees, generated trees, and fixtures were not mutated.

## Full-repository audit and migration debt

`./trade dev check --all` intentionally remains a hard audit. It inspected 688 eligible files, produced 22 results in 27.9 seconds, and exited `2` because infrastructure failures take precedence over quality failures.

Infrastructure and C++ blockers:

- `clang-format` is not installed; the report emitted the exact setup hint.
- CMake configuration cannot link the configured Clang 13/libc++ probe because `-lc++` is unavailable. Build and ctest were therefore dependency-skipped, not reported as passing.

Existing first-party debt exposed without suppressions or bulk rewrites:

- BasedPyright reports legacy type mismatches in `scripts/` and existing tests.
- Ruff reports legacy formatting and import-order debt.
- Text hygiene reports trailing whitespace in `docs/16_plan_EBRT_12_restore_latest_recommendation.md` and `trade_py/db/migrations.py`.
- ShellCheck reports SC2046 in the existing `build_clang.sh` command.
- ESLint reports unused variables in existing frontend components; Prettier reports existing formatting debt.
- Java formatting/tests, Python syntax, configuration parsing, lock consistency, suppression audit, Bash syntax, frontend build, and TypeScript all passed in full-audit mode.

Diagnostics are deliberately output-bounded, so the command output is the source of truth for the next migration batch rather than an inferred total from the displayed examples.

## Regression and compatibility checks

- `.venv/bin/pytest tests/test_cli_contracts.py tests/test_quality_scope.py tests/test_quality_planner.py tests/test_quality_executor.py tests/test_quality_runner.py tests/test_quality_internal.py tests/test_quality_config_contracts.py tests/test_quality_performance.py tests/test_dev_quality_cli.py tests/test_cli_lazy_loading.py -q`: 63 passed.
- `PYTHONDONTWRITEBYTECODE=1 python -m compileall -q trade_py trade_web tests`: passed.
- `npm run build` in `trade_web/frontend`: passed; Vite transformed 102 modules.
- `mvn -o -q spotless:check test` in `engine/tradedb-driver`: passed on Java 8; 3 module tests were previously observed passing while priming the offline cache.
- `openspec validate add-cross-language-quality-gates --strict --no-interactive`: the change is valid. Its optional PostHog flush could not reach the network and did not affect validation.
- `git diff --check`: passed.

The frontend gate uses pure-JavaScript Prettier, ESLint, and TypeScript because locally tested Biome native releases require a newer glibc than this Debian 10 host. Java pins Spotless 2.30.0 and google-java-format 1.7 for Java 8 compatibility.

## Performance sanity review

Performance-smoke coverage: **added**.

- A synthetic 2,000-path repository test verifies NUL-safe, byte-bounded path batching with no batch above 1,024 bytes.
- A no-op scope test enforces at most 10 Git subprocesses and a 2,000 ms discovery budget.
- An executor test enforces the configured lightweight concurrency bound while heavy steps remain serialized by design.
- Changed-scope execution completed in 5.9 seconds on this host; the full audit completed in 27.9 seconds despite the legacy failures.

## Residual risk

- `--all` will stay red until the recorded legacy debt and C++ host prerequisites are addressed in deliberate, reviewable batches.
- The performance budgets are host-level smoke thresholds, not benchmark guarantees across every CI machine.
- The initial online Maven priming step is still required on a fresh machine before the documented offline Java checks can run.

## Master integration — 2026-07-20

- The Observatory Vitest/Playwright dependencies and the quality Prettier/ESLint dependencies were combined in one regenerated `package-lock.json`; 39 frontend unit tests and the 111-module production build passed together.
- BasedPyright now receives `--project pyproject.toml`, so an ignored personal `pyrightconfig.json` cannot override repository policy.
- Python 3.10 TOML loading uses the conditional `tomli` compatibility dependency; Python 3.11+ keeps the standard-library `tomllib` path.
- The integrated changed-scope gate passed for 67 files and 14 results. The focused quality/CLI suite passed 63 tests, Python compileall passed, Java offline Spotless/tests passed, and strict OpenSpec validation passed.
