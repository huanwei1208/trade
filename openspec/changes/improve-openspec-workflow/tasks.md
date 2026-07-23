## 1. Governed design approval

- [x] 1.1 Confirm the isolated worktree is clean except for this change and
  preserve unrelated user/runtime state.
- [x] 1.2 Complete proposal, Design Quality Brief, capability spec, obligation
  mappings, and public-contract evidence.
- [x] 1.3 Run diagnostic `./trade dev design-check improve-openspec-workflow` and resolve deterministic findings. `[validates:openspec.status-service] [validates:openspec.public-cli] [validation:test]`
- [ ] 1.4 Run the six-role design consensus review in a separate review worktree, resolve every P0, record digest-bound evidence, and pass current-date strict design approval. `[validates:openspec.review-evidence] [validation:review]`

## 2. Read-only status service

- [ ] 2.1 Add typed `trade_py/devtools/openspec_status/` report and adapter
  boundaries for snapshot-bound native list/status/validation and complete
  design-quality reports.
- [ ] 2.2 Extract the shared Git-base governance-requirement resolver and fail
  closed for new changes, deleted markers, existing governed changes, and
  unavailable provenance.
- [ ] 2.3 Implement the four-worker bounded process executor with streaming
  output limits, process-group TERM/KILL/reap, interrupt cleanup, and a
  command-wide deadline.
- [ ] 2.4 Implement the reviewed lifecycle/next-action table, task-bearing
  `spec-driven` strategy, immutable native snapshot, digest drift rejection,
  strict batch design evaluation, and explicit unavailable records.
- [ ] 2.5 Add focused service/executor tests for every lifecycle row, review-only versus non-review strict findings, new versus historical governance, marker deletion, unsupported schema, evidence drift, midnight date capture, empty scope, native and active-design-batch timeout/reap, output flooding, inherited pipes, interrupt cleanup, unknown change, partial failure, exact 16 MiB/one-byte-over report bounds, and deterministic 10/100-change capacity. `[validates:openspec.status-service] [validates:openspec.concurrent-collection] [validation:test]`
- [ ] 2.6 Run focused service pytest and compileall, then commit the validated implementation unit. `[validates:openspec.status-service] [validates:openspec.concurrent-collection] [validation:test]`

## 3. Public CLI and reporting

- [ ] 3.1 Add lazy `./trade dev openspec [change] [--format text|json]`
  parsing plus `uv run --frozen --no-sync` shell routing without runtime imports.
- [ ] 3.2 Add deterministic text rendering and the complete typed
  `trade.openspec.workflow.v1` contract with unmodified embedded design reports,
  native issue omission counts, nullable unavailable evidence, fixed oversized
  error output, and stable exit precedence.
- [ ] 3.3 Add parser, runtime import-boundary, text/JSON schema, list/single, unknown-change, partial-error, frozen/no-sync, and shell-help tests. `[validates:openspec.public-cli] [validation:test]`
- [ ] 3.4 Run focused CLI pytest and real repository text/JSON smoke checks, then commit the validated CLI unit. `[validates:openspec.public-cli] [validation:test]`

## 4. Completion and integration

- [ ] 4.1 Run `openspec validate improve-openspec-workflow --strict`, `./trade dev check --show-plan`, `./trade dev check`, focused pytest including executor/capacity coverage, `python -m compileall trade_py tests`, and `git diff --check`. `[validates:openspec.status-service] [validates:openspec.public-cli] [validates:openspec.concurrent-collection] [validation:test]`
- [ ] 4.2 Run the six-role implementation review against the final diff, resolve every P0, refresh review evidence if governed artifacts changed, and rerun strict design approval. `[validates:openspec.review-evidence] [validation:review]`
- [ ] 4.3 Record exact validation outcomes, compatibility/data/performance
  risks, review findings, and residual follow-ups; update completed task
  checkboxes.
- [ ] 4.4 Recheck worktree status, stage only intentional files, and commit the
  final validated unit.
- [ ] 4.5 Push the feature branch, create a GitHub pull request against
  `master`, and retain squash-merge plus source-branch deletion as the merge
  policy.
