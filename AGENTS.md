# Agent Guide

This repository is a mixed trading system with Python services and CLI,
FastAPI/web surfaces, local data assets, and a C++ engine. Keep changes
evidence-driven, auditable, and easy to review.

## Repository Shape

- `trade`: unified project entrypoint for doctor/setup/build/test/run workflows.
- `trade_py/`: Python domain, services, data access, jobs, CLI, DB, and decision logic.
- `trade_web/`: backend API and frontend workspace surfaces.
- `engine/`: C++ engine, CMake presets, headers, sources, and ctest suites.
- `tests/`: Python pytest coverage for contracts, services, data, and web behavior.
- `docs/`: historical and active design/EBRT plans.
- `openspec/`: spec-driven change proposals for larger work.

## Change Rules

- **Isolation via git worktree (MANDATORY)**: Every feature/refactor/bugfix implementation MUST create and use a dedicated git worktree on a new branch before making any code changes. This prevents multi-agent interference and keeps the main working tree clean. Naming convention: `wt/<feature-slug>-<yyyymmdd>`. Example: `git worktree add ../trade-wt-asset-split -b wt/asset-split-20260712`. Never commit directly to master/main from a worktree until the branch is ready for PR/merge.
- **Commit after every implementation unit (MANDATORY)**: After each logically complete change (module added, bug fixed, refactor step done), commit immediately. Do not accumulate uncommitted changes. Commit messages should clearly state scope, validation, and compatibility notes.
- **Push every 3–5 commits (MANDATORY)**: After accumulating 3 to 5 local commits on a feature branch, push the branch to the remote to prevent work loss. Use `git push -u origin <branch>` for the first push, then `git push` thereafter.
- **Unit tests required (MANDATORY)**: Every behavior change must have corresponding unit tests added or updated near the touched path. If tests are deferred for a specific reason, explicitly state the no-test reason and residual risk, and create a follow-up task tracking the missing coverage.
- Start with `git status -sb` in the active worktree. Do not overwrite, delete, or stage unrelated dirty work. Treat untracked local data, `.nvim/`, cache, and generated artifacts as user/runtime state unless the task explicitly targets them.
- Prefer stable boundaries over broad rewrites: route behavior through CLI/API facades, keep business logic in service/domain modules, keep DB/data access in owner modules, and keep C++ engine changes inside `engine/`.
- Do not grow catch-all files. Split by domain, service, adapter, repository, or UI surface when a module starts mixing responsibilities.
- Public contracts need compatibility thought before code: CLI arguments, API payloads, DB schema, parquet layout, and engine interfaces must document migration/default/fallback behavior.
- For recommendation, causal, trust, backtest, or quality-gate work, expose input evidence, confidence/calibration state, and unknown/failure states. Do not present heuristic scaffolding as a validated model.

## Review Before Implementation (MANDATORY for medium/large changes)

- Before implementing medium or large changes, run the **multi-agent consensus review** using the `review-this` skill (see `.agents/skills/review-this/SKILL.md`).
- Launch 6 specialized judge agents (reliability, performance, architecture, data-quality, observability, news-sentiment) in parallel against a review worktree.
- Synthesize consensus; fix P0 findings before proceeding.
- The skill is invoked automatically when the task matches the criteria; you can also trigger it with `trade dev review`.

## OpenSpec

- Small local fixes may proceed directly after identifying target behavior and
  focused validation.
- Use OpenSpec before medium or large changes, especially DB/schema migrations,
  data storage changes, trading-decision semantics, Web API contracts, C++
  engine behavior, workflow orchestration, or cross-module refactors.
- A proposal must define what changes, why it matters, non-goals, affected
  contracts, validation, data-safety plan, and rollout/rollback notes.
- Implementation tasks must map to concrete tests, smoke checks, or an explicit
  no-test reason.

## Data Safety

- Default to read-only access for real `data/`, DB files, and generated parquet.
- Data migrations require backup or reversible snapshot, dry-run behavior where
  practical, a small-sample verification, and a rollback note.
- Tests must use temporary directories or fixtures, not production data roots,
  unless the user explicitly asks for a live-data probe.
- Do not commit generated local data unless the task explicitly requires a small
  fixture and the fixture is reviewed as part of the change.

## Testing

- Python changes: run focused `uv run pytest tests/<target>.py -q`; for shared
  modules also run `python -m compileall trade_py trade_web tests`.
- C++ engine changes: run the relevant CMake build/ctest path, normally
  `./trade test linux-clang` after configure/build prerequisites are satisfied.
- Web backend changes: run focused backend pytest and smoke changed API routes
  when practical.
- Frontend changes: run the frontend build/typecheck path from
  `trade_web/frontend`.
- Every behavior change needs coverage near the touched path. If no test is
  added, state the concrete reason and residual risk.

## Completion

- Stage only intentional files. Keep unrelated untracked data and local config
  out of commits.
- Commit validated changes by default. The commit body should list scope,
  validation commands and outcomes, compatibility/data risks, and follow-ups.
- If validation fails, do not commit unless the user explicitly requests a
  failing checkpoint.
