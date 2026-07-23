## 1. Governed design approval

- [x] 1.1 Confirm the isolated worktree is clean except for this change and
  preserve unrelated user/runtime state.
- [x] 1.2 Complete proposal, Design Quality Brief, capability spec, obligation
  mappings, and public-contract evidence.
- [x] 1.3 Run diagnostic `./trade dev design-check improve-openspec-workflow` and resolve deterministic findings. `[validates:openspec.status-service] [validates:openspec.public-cli] [validation:test]`
- [ ] 1.4 Run the six-role design consensus review in a separate review worktree, resolve every P0, record digest-bound evidence, and pass current-date strict design approval. `[validates:openspec.review-evidence] [validation:review]`

## 2. Read-only status service

- [ ] 2.1 Add typed `trade_py/devtools/openspec_status/` report and adapter
  boundaries for native list, status, validation, and design-quality evidence.
- [ ] 2.2 Implement bounded native subprocess execution, required JSON-shape
  validation, explicit unavailable/error records, and deterministic ordering.
- [ ] 2.3 Implement lifecycle and next-action derivation that keeps authoring,
  task completion, validation, and governance evidence distinct.
- [ ] 2.4 Add focused service tests for authoring, review, implementation, archive-ready, blocked, historical ungoverned, empty scope, timeout, malformed response, unknown change, and partial list failure. `[validates:openspec.status-service] [validation:test]`
- [ ] 2.5 Run focused service pytest and compileall, then commit the validated implementation unit. `[validates:openspec.status-service] [validation:test]`

## 3. Public CLI and reporting

- [ ] 3.1 Add lazy `./trade dev openspec [change] [--format text|json]`
  parsing and dispatch without importing DB/runtime modules.
- [ ] 3.2 Add deterministic text rendering and
  `trade.openspec.workflow.v1` JSON with stable exit precedence.
- [ ] 3.3 Add parser, lazy-import/no-DB, text/JSON, list/single, unknown-change, and shell-routing tests. `[validates:openspec.public-cli] [validation:test]`
- [ ] 3.4 Run focused CLI pytest and real repository text/JSON smoke checks, then commit the validated CLI unit. `[validates:openspec.public-cli] [validation:test]`

## 4. Completion and integration

- [ ] 4.1 Run `openspec validate improve-openspec-workflow --strict`, `./trade dev check --show-plan`, `./trade dev check`, focused pytest, `python -m compileall trade_py tests`, and `git diff --check`. `[validates:openspec.status-service] [validates:openspec.public-cli] [validation:test]`
- [ ] 4.2 Run the six-role implementation review against the final diff, resolve every P0, refresh review evidence if governed artifacts changed, and rerun strict design approval. `[validates:openspec.review-evidence] [validation:review]`
- [ ] 4.3 Record exact validation outcomes, compatibility/data/performance
  risks, review findings, and residual follow-ups; update completed task
  checkboxes.
- [ ] 4.4 Recheck worktree status, stage only intentional files, and commit the
  final validated unit.
- [ ] 4.5 Push the feature branch, create a GitHub pull request against
  `master`, and retain squash-merge plus source-branch deletion as the merge
  policy.
