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

- **Isolation via git worktree (MANDATORY for code changes, optional for docs)**:
  - All code-affecting changes (Python/C++/TS/JS business logic, test code, build scripts, CMake/dependency config, DB schema, API contracts, runtime configuration, core engine/decision/data access logic) MUST create and use a dedicated git worktree on a new branch before making any changes. This prevents multi-agent interference and keeps the main working tree runtime clean and completely unaffected by in-progress development. Naming convention: `wt/<feature-slug>-<yyyymmdd>`. Example: `git worktree add ../trade-wt-asset-split -b wt/asset-split-20260712`. Never commit directly to master/main from a worktree until the branch is ready for merge.
  - Exemption: Pure documentation changes (content in `docs/`/`openspec/`, README updates, comment additions/corrections, Markdown formatting/typo fixes, agent rule documentation updates that do not touch executable code or runtime config logic) may be modified and committed directly in the master working tree without a dedicated worktree.
  - Mixed code + documentation changes always fall under the mandatory worktree rule.
- **Commit after every implementation unit (MANDATORY)**: After each logically complete change (module added, bug fixed, refactor step done), commit immediately. Do not accumulate uncommitted changes. Commit messages should clearly state scope, validation, and compatibility notes.
- **Push every 3–5 commits (MANDATORY)**: After accumulating 3 to 5 local commits on a feature branch, push the branch to the remote to prevent work loss. Use `git push -u origin <branch>` for the first push, then `git push` thereafter.
- **Create a pull request after push (MANDATORY)**: After pushing a feature
  branch, create a pull request against `master` instead of stopping at the
  remote branch. If the local environment lacks authenticated GitHub PR tooling,
  state the blocker clearly and provide the PR creation URL. Prefer squash merge
  for the PR and delete the source branch after it is merged.
- **Project-local GitHub CLI for PRs (MANDATORY)**: Use the official GitHub CLI
  binary at `.cache/github-cli/gh_2.65.0_linux_amd64/bin/gh` when it exists; do
  not use `/usr/local/bin/gh`, which may be a non-GitHub internal tool. Before
  installing another copy, check the project-local binary with
  `.cache/github-cli/gh_2.65.0_linux_amd64/bin/gh --version` and check auth with
  `.cache/github-cli/gh_2.65.0_linux_amd64/bin/gh auth status`. Only install a
  new project-local GitHub CLI into ignored `.cache/github-cli/` if the existing
  project-local binary is absent or not the official GitHub CLI. If auth is
  missing, ask the user to authenticate that project-local binary and retry PR
  creation after every pushed feature branch.
- **Unit tests required (MANDATORY)**: Every behavior change must have corresponding unit tests added or updated near the touched path. If tests are deferred for a specific reason, explicitly state the no-test reason and residual risk, and create a follow-up task tracking the missing coverage.
- Start with `git status -sb` in the active worktree. Do not overwrite, delete, or stage unrelated dirty work. Treat untracked local data, `.nvim/`, cache, and generated artifacts as user/runtime state unless the task explicitly targets them.
- If `AGENTS.md` or an equivalent project instruction file is absent in a new
  repository, initialize the agent environment before adding persistent
  workflow preferences.
- Prefer stable boundaries over broad rewrites: route behavior through CLI/API facades, keep business logic in service/domain modules, keep DB/data access in owner modules, and keep C++ engine changes inside `engine/`.
- Do not grow catch-all files. Split by domain, service, adapter, repository, or UI surface when a module starts mixing responsibilities.
- Public contracts need compatibility thought before code: CLI arguments, API payloads, DB schema, parquet layout, and engine interfaces must document migration/default/fallback behavior.
- For recommendation, causal, trust, backtest, or quality-gate work, expose input evidence, confidence/calibration state, and unknown/failure states. Do not present heuristic scaffolding as a validated model.

## Intelligent Decision & Deep Thinking Mandate (MANDATORY)
All changes must be classified first before any action is taken. No direct code edits are allowed until the change tier and required process are confirmed. You MUST apply deep, deliberate reasoning (extended chain of thought) for non-trivial changes instead of rushing to implementation.

### Change Tier Classification (decide FIRST before any edits):
| Tier | Definition | Required Process |
|------|------------|------------------|
| **Trivial (Doc-only)** | Pure documentation changes as defined in the worktree exemption rule: content in `docs/`/`openspec/`, README updates, comment fixes, Markdown adjustments, rule documentation updates with no executable code/config logic changes. | No worktree, no OpenSpec, no deep planning required. Modify directly on master. |
| **Trivial (Code)** | Single-file, low-risk code changes that do not alter external behavior: <br>1. Typo/obvious one-line bugfix within a single function <br>2. Log/metric string adjustments, error message improvements <br>3. Adding/modifying test cases for existing logic without changing production code <br>4. Independent utility function/helper addition with no core logic invasion | Must use dedicated worktree. No OpenSpec required. Proceed after a brief (1-2 paragraph) impact assessment. |
| **Non-trivial** | Any change that meets ANY of the following criteria: <br>1. Root cause of a bug is unclear / requires investigation <br>2. There are ≥2 viable implementation approaches with meaningful tradeoffs <br>3. Changes touch core trading logic, signal calculation, order execution, risk control paths <br>4. Cross-module changes (touch ≥2 top-level directories e.g. `trade_py` + `engine`, API + service layer) <br>5. Performance, concurrency, memory, or reliability-related changes <br>6. Public contract changes (API payloads, CLI args, DB schema, data formats) <br>7. Data migration, data format change, or changes affecting data consistency/capital safety <br>8. C++ engine core logic modifications | MUST enter planning/deep thinking mode first: explicitly outline problem analysis, alternative approaches, tradeoff comparison, selected solution rationale, impact surface, risk points, and rollback plan BEFORE writing any code or OpenSpec proposal. MUST use dedicated worktree. MUST create an OpenSpec proposal before implementation. |

### Hard Rules:
- If you are unsure which tier a change belongs to, **always default to the Non-trivial tier**: it is always safe to do more planning first, never skip deep thinking/OpenSpec for ambiguous changes.
- Deep thinking output must be concrete, not vague: do not skip tradeoff analysis or risk assessment for non-trivial changes.
- OpenSpec proposals for non-trivial changes must directly incorporate the deep thinking output (tradeoffs, risk, rollback plan) from the planning phase.

## Review Before Implementation (MANDATORY for medium/large changes)

- Use `.codex/skills/design-quality/SKILL.md` before implementation. Create a
  governed OpenSpec change with explicit impact applicability, obligation mappings,
  a substantive Design Quality Brief, and digest-bound review evidence.
- Run `./trade dev design-check <change>` before review and
  `./trade dev design-check <change> --strict` after review. Do not begin code until
  strict approval passes. A historical `--as-of` result is diagnostic only.
- Before implementing medium or large changes, run the **multi-agent consensus review** using the `review-this` skill (see `.agents/skills/review-this/SKILL.md`).
- Launch 6 specialized judge agents (reliability, performance, architecture, data-quality, observability, news-sentiment) in parallel against a review worktree.
- Synthesize consensus; fix P0 findings before proceeding.
- The skill is invoked automatically when the task matches the criteria; you can also trigger it with `trade dev review`.
- If approved design artifacts or architecture assumptions change during
  implementation, stop, refresh consensus evidence, and regain strict approval.
- Run the six-role review again against the implemented diff before merge and resolve
  every P0 finding.

## OpenSpec

- **OpenSpec Mandatory Trigger Rule**: All Non-trivial tier changes (as defined in the Intelligent Decision & Deep Thinking Mandate section) MUST create an OpenSpec proposal before any code changes are written. This is a hard requirement, no exceptions. If you are unsure whether a change qualifies as Non-trivial, create an OpenSpec proposal.
- Trivial code fixes may proceed directly after identifying target behavior and focused validation, no OpenSpec required.
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

## Code Quality Skill (MANDATORY)

- For medium/large work, the design-quality gate precedes this implementation gate;
  code-quality does not replace architecture review or authorize design drift.
- Use `.codex/skills/code-quality/SKILL.md` for every implementation, refactor,
  bug fix, optimization, review fix, or generated-code task that touches Python,
  Shell, C/C++, Java/Maven, TypeScript/JavaScript, tests, configuration, or public
  contracts.
- Load the shared reference and only the relevant language references before
  editing. For mixed-language changes, load every applicable reference.
- Before completion run `./trade dev check --show-plan`, `./trade dev check`, focused
  behavior tests, required language build/type checks, and `git diff --check`.
- `./trade dev fix` is explicit source mutation. Inspect its diff; it never authorizes
  staging or committing formatter output blindly.
- A failing `./trade dev check --all` is a hard debt/readiness result, not a pass.
  Do not weaken rules or add blanket suppressions merely to make it green.
- The quality gate supplements rather than replaces the six-role review, focused
  tests, data-safety rules, and language-specific validation below.

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
- **Merge via rebase + squash (MANDATORY)**: When bringing a feature branch back
  to master, use `git checkout master && git merge --squash <branch>` to collapse
  the worktree's WIP commits into a single clean commit on master. After squash-merge,
  delete the feature branch (`git branch -D <branch>`) and remove the worktree
  (`git worktree remove <path>`). Do NOT use fast-forward or regular merge that
  preserves intermediate commit noise on master. The master history should read
  as a clean sequence of logical changes.
