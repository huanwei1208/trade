## 1. Policy and core evaluator

- [x] 1.1 Recheck the isolated worktree and preserve unrelated runtime/user state before staging.
- [x] 1.2 Add immutable `design-policy/v1.toml` namespaced profiles plus Python 3.10-compatible policy/marker/obligation/review loaders with focused schema tests.
- [x] 1.3 Implement bounded allowlisted snapshot loading, safe slug/path/symlink handling, per-change/batch resource limits, deterministic diagnostic replay versus current-date approval, and owned/expiring exception semantics.
- [x] 1.4 Implement Brief/obligation consistency, point-in-time/predictive, persistent-write/schema, public-contract, and external-event evidence profiles with stable positive/negative fixtures.
- [x] 1.5 Validate the core package with focused pytest and compileall, then commit the validated unit. `[validates:design.direct-cli] [validates:design.review-evidence] [validation:test]`

## 2. Public CLI and quality integration

- [x] 2.1 Add lazy frozen/no-sync `./trade dev design-check <change> [--strict] [--format text|json] [--as-of YYYY-MM-DD]` routing, update root/dev help with the single pre-code sequence, and preserve stable exit semantics with no DB/runtime imports.
- [x] 2.2 Add deterministic text/JSON reporting with digests, applicability, artifact inventory, exception state, structured parent details, remediation, and bounded counts.
- [x] 2.3 Extend quality scope with added/deleted metadata and add a supplemental aggregate contributor that runs one strict batch for sorted changes without stealing file ownership.
- [x] 2.4 Add exact nested return-code mapping and structured step details while preserving existing provider ordering and aggregate precedence.
- [x] 2.5 Add root/dev help contract, CLI/no-DB/frozen wrapper, historical strict rejection, deletion bypass, multi-change 2/10/100/over-limit, structured report, and quality-planner/executor tests. `[validates:design.direct-cli] [validates:design.changed-scope] [validation:test]`
- [x] 2.6 Validate the public command and contributor with focused pytest and smoke commands, then commit the validated unit. `[validates:design.direct-cli] [validates:design.changed-scope] [validation:test]`

## 3. Agent workflow and governance

- [x] 3.1 Scaffold `.codex/skills/design-quality/` with the official skill creator and define the pre-review -> consensus -> digest evidence -> strict approval handoff to `code-quality`.
- [x] 3.2 Update `AGENTS.md` and OpenSpec governance so new medium/large changes require explicit applicability/obligations, governed Brief, fresh six-role evidence, and strict approval.
- [x] 3.3 Add skill forward tests and run the official skill validator against the repository-local skill. `[validates:design.review-evidence] [validates:design.agent-workflow] [validation:test]`
- [x] 3.4 Validate documentation/config consistency and strict OpenSpec validation, then commit the validated unit. `[validates:design.review-evidence] [validates:design.agent-workflow] [validation:test]`

## 4. Completion and integration

- [x] 4.1 Run the six-role implementation review and identify policy mutability, changed-scope, snapshot, strict-governance, structured-output, evidence-schema, and timeout bypasses before merge.
- [x] 4.2 Close every implementation-review P0 with focused regression tests, including immutable policy digest/edit binding, merge-base new-change detection, no-follow snapshot verification, direct strict governance, bounded output, deadline preservation, and `--all` delta separation.
- [x] 4.3 Close actionable P1 semantic gaps for policy-driven structured evidence, exact capability/requirement/scenario/task references, duplicate identifiers, batch envelope consistency, 2/10/100 live evaluation, and early oversized-output termination.
- [x] 4.4 Complete the final six-role digest-bound review with no unresolved P0 and record accepted residual risks.
- [x] 4.5 Run focused and forward pytest, touched-file BasedPyright, Ruff, `python -m compileall trade_py tests`, `./trade dev check`, CLI text/JSON smoke, skill validation, and strict OpenSpec validation. `[validates:design.direct-cli] [validates:design.changed-scope] [validates:design.agent-workflow] [validation:test]`
- [x] 4.6 Record final review scores, finding resolutions, exact validation, compatibility/data/calibration risks, and follow-ups in `design-review.toml` and the human review summary. `[validates:design.review-evidence] [validation:review]`
- [x] 4.7 Inspect final status/diff, stage only intentional files, update all completed task checkboxes, and commit the validation summary.
- [x] 4.8 Push the feature branch after three to five commits, squash-merge it to `master`, push `master`, and remove the merged worktree/branches.
