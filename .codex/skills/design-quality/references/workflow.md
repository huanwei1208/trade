# Governed workflow

## Phase 1: evidence and proposal

1. Create a dedicated branch/worktree as required by `AGENTS.md`.
2. Inspect real modules and contracts; do not infer ownership from names.
3. Create or update the OpenSpec proposal, design, specs, tasks,
   `design-quality.toml`, and eventually `design-review.toml`.
4. Declare all policy v1 impacts and map every behavior obligation to concrete owners,
   paths, contracts, failure states, spec requirements, and validation task IDs. The
   referenced task text must carry `[validates:<obligation-id>]` and either
   `[validation:test]` with real test/check/smoke semantics or `[validation:review]`
   with evidence/finding/consensus semantics; a generic use of "review" is not enough.
5. Run `./trade dev design-check <change>` until deterministic diagnostics have no
   unresolved blockers and all warnings have an owned resolution or valid exception.

The repository policy is `design-policy/v1.toml`; it is the executable source of
profile names, rule IDs, limits, artifact allowlists, and evidence terms. Do not copy
or locally reinterpret its values in a change.

## Phase 2: consensus and strict approval

1. Follow `.agents/skills/review-this/SKILL.md` in a separate review worktree.
2. Use all six required roles: reliability, performance, architecture, data quality,
   observability, and news/future integration.
3. Make judges cite current files and distinguish P0/P1/P2 findings.
4. Resolve every P0 and reconcile contradictions once when needed.
5. Record each judge, status, artifact digest, reviewed commit/date, and finding
   resolution in `design-review.toml`.
6. Run `./trade dev design-check <change> --strict`. Exit `0` is approval, `1` is a
   change-owned policy failure, and `2` is invocation/repository-policy failure.

Strict approval is current-date and portable-content-digest-bound. A reachable reviewed
commit also receives an exact policy/artifact tree check; after squash makes that
commit unreachable, a fresh clone still verifies matching portable digests. Editing
governed artifacts after review invalidates approval even if prose still looks similar.

## Phase 3: implementation handoff

Invoke `$code-quality`. Keep CLI/API facades thin, domain behavior in owner modules,
and persistence in repositories/adapters. Add focused behavior tests for every change.
Run `./trade dev check --show-plan` and `./trade dev check` plus relevant language
tests/builds. The changed-scope gate adds one strict design batch without stealing
language/shared file ownership.

## Phase 4: merge review

Before merge, review the implemented diff with all six roles, fix P0 findings, rerun
focused/forward validation and strict design checking, then squash-merge per
`AGENTS.md`. Record exact commands, outcomes, compatibility/data/calibration risks,
and follow-ups.
