# Implementation Tasks

## 1. Governed design and review

- [x] 1.1 Inspect the existing BTC Observatory API, frontend route, data contracts, tests, navigation gate, and current worktree status without reading or mutating real market data.
- [x] 1.2 Create the governed proposal, Design Quality Brief, explicit impact declaration, obligation mapping, and task-oriented workspace specification.
- [x] 1.3 Run `./trade dev design-check btc-research-workspace`, resolve all deterministic findings, and record the clean diagnostic report.
- [ ] 1.4 Run the required six-role consensus review in the separate review worktree, synthesize findings, resolve every P0, reconcile the selected-snapshot/PIT, request-ownership, bounded-render, and future-data-family findings, and write digest-bound approval evidence. `[validates:btc-workspace.lifecycle-truth] [validates:btc-workspace.snapshot-coherence] [validates:btc-workspace.safe-navigation] [validates:btc-workspace.research-boundary] [validation:review]`
- [ ] 1.5 Run `./trade dev design-check btc-research-workspace --strict` and begin code only after strict approval passes.

## 2. Frontend implementation

- [ ] 2.1 Add one page-level keyed Observatory GET resource contract that owns canonical request identity, structured safe error extraction, AbortController cancellation, confirmed/loading/unavailable/failed state, and bounded same-identity ETag memory reuse. Do not persist Observatory payloads to localStorage or render an old identity as current. `[validates:btc-workspace.lifecycle-truth] [validates:btc-workspace.snapshot-coherence] [validation:test]`
- [ ] 2.2 Refactor task-oriented Market, Assurance/Gates, Assurance/Run Lineage, and Research containers so all request orchestration lives under `pages/observatory/`; convert `components/observatory/` to presentation-only inputs. Preserve independent lifecycle layers, explicit panel failure states, direct `runs` URL compatibility, and non-directional H1 presentation. `[validates:btc-workspace.lifecycle-truth] [validates:btc-workspace.research-boundary] [validation:test]`
- [ ] 2.3 Resolve selected-channel Context first and pin selected-channel series, Trust, and Date Evidence to its `snapshot_id`; validate returned identities and block `PIT_NOT_PROVEN`/mismatch/failure states. Keep composite an explicitly separate same-selector comparison and label global Lineage/Research as separately scoped evidence. `[validates:btc-workspace.snapshot-coherence] [validation:test]`
- [ ] 2.4 Add scoped Market/Assurance controls, Context-derived `from`/`to` windows, display-only chart/coverage budgets, accessible keyboard date inspection, and structured error/denied-capability notices. Remove browser-computed market extrema and make committed knowledge input avoid per-keystroke reads. `[validates:btc-workspace.lifecycle-truth] [validates:btc-workspace.safe-navigation] [validation:test]`
- [ ] 2.5 Add or update focused unit tests for the default Market hierarchy; stable four-lens URL mapping; snapshot propagation; PIT/quality/catalog/integrity/missing/quarantine/revision states; out-of-order request abort; cache-key/304 truthfulness; mode request matrix; bounded rendering; keyboard date inspection; and research non-recommendation/scoped-provenance language. `[validates:btc-workspace.lifecycle-truth] [validates:btc-workspace.snapshot-coherence] [validates:btc-workspace.safe-navigation] [validates:btc-workspace.research-boundary] [validation:test]`
- [ ] 2.6 Inspect the focused diff, run formatting only through existing repository tools, and commit the validated frontend implementation unit with compatibility and test notes.

## 3. Validation and delivery

- [ ] 3.1 Run focused frontend unit tests, `npm --prefix trade_web/frontend run typecheck`, `npm --prefix trade_web/frontend run build`, and capability/URL/PIT request regression tests; verify the workspace has no API or data write side effect. `[validates:btc-workspace.lifecycle-truth] [validates:btc-workspace.snapshot-coherence] [validates:btc-workspace.safe-navigation] [validation:test]`
- [ ] 3.2 Run existing frontend E2E and a11y tests with selector-aware mock assertions, including denied direct links, snapshot-pinned date evidence, keyboard selection, error states, and H1 scope language. If the environment cannot run them, preserve the tests and record the exact blocker and residual risk. `[validates:btc-workspace.research-boundary] [validation:test]`
- [ ] 3.3 Run `./trade dev check --show-plan`, `./trade dev check`, `git diff --check`, and final `git status -sb`; do not stage unrelated runtime or generated files.
- [ ] 3.4 Run the six-role review against the implemented diff, resolve every P0, refresh approval evidence if governed artifacts changed, and rerun strict design approval. `[validates:btc-workspace.lifecycle-truth] [validates:btc-workspace.snapshot-coherence] [validates:btc-workspace.safe-navigation] [validates:btc-workspace.research-boundary] [validation:review]`
- [ ] 3.5 Commit validated delivery work, push after three to five commits if reached, and report the feature-branch state without merging to `master`.
