## 1. Governed design approval

- [x] 1.1 Inspect repository state, existing agent rules, OpenSpec configuration,
  script language, hooks, CI, tests, and quality policy in an isolated worktree.
- [x] 1.2 Complete proposal, Design Quality Brief, capability spec, obligation
  mappings, alternatives, risks, and rollback plan.
- [x] 1.3 Run diagnostic `./trade dev design-check add-openspec-coordination`, validate the governed artifacts, and resolve deterministic findings. `[validates:coord.ownership] [validates:coord.boundaries] [validation:test]`
- [ ] 1.4 Run six-role design consensus review in a separate review worktree, resolve every P0 finding, record digest-bound review evidence, and pass current-date strict approval. `[validates:coord.review] [validation:review]`

## 2. Coordination runtime

- [ ] 2.1 Implement validated Git/worktree discovery, common-dir layout,
  per-change locks, bounded JSON parsing, atomic replace, epoch allocation, and
  history records.
- [ ] 2.2 Implement claim, read-only status, fenced assertion, owner-only
  release, confirmed takeover, no-expiry semantics, and clear errors.
- [ ] 2.3 Implement argv-preserving owned `run` with pre/post assertion and audit,
  plus operation-scoped `run-global` with nonblocking or finite-wait locking.
- [ ] 2.4 Add temporary-repository tests for first/concurrent/independent claim, owner and epoch checks, takeover fencing, release, branch/worktree mismatch, traversal, corrupt JSON, atomic records, command audit, global locks, and no timeout cleanup. `[validates:coord.ownership] [validates:coord.execution] [validation:test]`

## 3. Git and agent boundaries

- [ ] 3.1 Implement staged and base/head Git boundary checking for worker,
  coordinator, shared spec/config, archive, deletion, and rename paths.
- [ ] 3.2 Add an independently invoked CI workflow and a tracked pre-commit hook
  with an explicit installer; do not depend on manual `.git/hooks` edits.
- [ ] 3.3 Merge coordinator, worker, direct-state-edit, takeover, fenced-agent,
  and no-child-change constraints into `AGENTS.md` and `openspec/config.yaml`.
- [ ] 3.4 Add boundary, hook, CI, and policy tests using temporary repositories and static tracked-file assertions. `[validates:coord.boundaries] [validates:coord.policy] [validation:test]`

## 4. Documentation and completion

- [ ] 4.1 Add operator documentation for claim identity retention, assertions,
  release, old-worktree inspection, explicit takeover, resumed-window fencing,
  worker prohibitions, shared locks, hooks, errors, and the complete two-window
  example.
- [ ] 4.2 Run and validate focused pytest, compileall, native OpenSpec strict validation, `./trade dev check --show-plan`, `./trade dev check`, strict design approval, and `git diff --check`. `[validates:coord.ownership] [validates:coord.execution] [validates:coord.boundaries] [validates:coord.policy] [validation:test]`
- [ ] 4.3 Run the six-role implementation review against the final diff, resolve every P0 finding, refresh stale design evidence if artifacts changed, and rerun strict approval. `[validates:coord.review] [validation:review]`
- [ ] 4.4 Inspect final status and diff, report exact validation outcomes and
  residual limits, and leave changes uncommitted as explicitly requested.
