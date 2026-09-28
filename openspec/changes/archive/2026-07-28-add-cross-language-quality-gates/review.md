# Six-role consensus review

Review baseline: `5f7daea`

Review worktree: `/tmp/trade-wt-review-code-quality-gates`

Method: two concurrency-limited waves, six independent read-only judges, identical
code snapshot.

## Scores

| Role | Score |
| --- | ---: |
| Reliability | 5/10 |
| Performance | 6/10 |
| Architecture | 6/10 |
| Data quality | 4/10 |
| Observability | 5/10 |
| Future integration | 5/10 |

Consensus average: 5.2/10 before resolution.

## P0 consensus and resolution

- Quality commands could fall through to TradeDB creation/migrations. Resolved in
  design/spec/tasks by requiring shell and Python pre-DB dispatch plus no-DB tests.
- “Read-only” contradicted compile/build caches. Resolved by protecting tracked
  source/config and runtime/data/model state while declaring permitted ignored build
  outputs in every step/plan.
- Vendor/generated ownership was undefined. Resolved with versioned ownership
  configuration, mutation-ineligible vendor/generated paths, and scope tests.
- Step dependencies, timeouts, output bounds, native exits, and aggregate precedence
  were ambiguous. Resolved with typed steps, dependency-aware execution, bounded
  concurrency, process-group timeouts, and `2 > 1 > 0` precedence.
- The machine-readable promise had no schema. Resolved with deterministic versioned
  JSON, stable check IDs, provenance, scope fingerprint, tool versions, exclusions,
  diagnostics, and remediation codes.
- Canonical setup did not install Python quality tools and check could implicitly
  sync. Resolved with explicit dev-extra setup and frozen/no-sync quality dispatch.
- `--all` was both required and allowed to fail. Resolved by making it a truthful
  hard debt audit that exits nonzero; only a later green-baseline change may make it
  mandatory pre-merge.

## Merit-based P0 additions

- Java/Maven source existed but was absent from the matrix. Added a Java provider and
  reference, plus uncovered-source failure for future languages.
- Git path handling did not cover NUL delimiters, option-like filenames, symlinks,
  containment, or argument limits. Added safe selection, batching, and tests.
- A central quality module would become a catch-all. Replaced with a package and
  provider registry.
- Existing `trade dev review` resolves/reuses worktrees unsafely. Included a focused
  repository-locator and stale-worktree fix with tests.

## P1 retained for implementation/follow-up

- Suppression-diff governance and semantic config/lock consistency checks.
- Path-based financial focused-test policy beyond the existing skill and mandatory
  test rules.
- Quantitative large-repository/no-op performance budgets.
- Optional CI/SARIF/JUnit publication after the local deterministic contract is
  stable.
