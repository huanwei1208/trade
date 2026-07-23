## 1. Governed design and consensus

- [x] 1.1 Inspect the current CLI, Web composition root, DB facade, EventBus,
  existing OpenSpec changes, quality plans, active worktrees, and data-safety
  constraints without reading or mutating real market data.
- [x] 1.2 Create the governed proposal, Design Quality Brief, explicit impact
  declaration, obligation mappings, runtime-boundary specification, and staged
  implementation plan.
- [x] 1.3 Run `./trade dev design-check converge-runtime-boundaries`, resolve all deterministic blockers/warnings, and commit the clean diagnostic design unit. `[validates:runtime.resources] [validates:runtime.http-boundary] [validates:runtime.admission] [validates:runtime.capacity-status] [validates:runtime.commands] [validation:test]`
- [x] 1.4 Run all six `review-this` roles in the isolated review worktree, synthesize consensus evidence, and resolve every P0. `[validates:runtime.resources] [validates:runtime.http-boundary] [validates:runtime.admission] [validates:runtime.capacity-status] [validates:runtime.commands] [validation:review]`
  The review must
  synthesize file/line findings, reconcile disagreements once, and resolve every
  P0. The review must explicitly cover Web resource ownership, EventBus durable
  partial admission, overload defaults, observability, news/NLP channel behavior,
  and compatibility with the active Ctrl+C and BTC Web branches.
- [x] 1.5 Record current digest-bound approval in `design-review.toml`, run
  `./trade dev design-check converge-runtime-boundaries --strict`, and begin
  production code only after strict approval passes.

## 2. Web resource lifecycle

- [x] 2.1 Rebase or integrate the accepted `wt/web-ctrlc-20260721` lifecycle behavior and add temporary-root tests that validate prompt shutdown and prevent duplicate resource cleanup. `[validates:runtime.resources] [validation:test]`
- [x] 2.2 Add and test a focused Web resource container with explicit `new/started/stopping/stopped` lifecycle, reverse-order partial-start cleanup, one owned `TradeDB`, existing services, and deterministic shutdown. `[validates:runtime.resources] [validates:runtime.commands] [validation:test]`
- [x] 2.3 Route current application dependencies through the container and test that repeated requests neither reconstruct `TradeDB` nor leak application-owned connections. `[validates:runtime.resources] [validation:test]`
- [x] 2.4 Run focused Web lifecycle/API tests and compileall, inspect the diff,
  and commit the validated resource-ownership unit.

## 3. Thin system/runtime HTTP boundary

- [x] 3.1 Extract and test one cohesive system/runtime router from `app.py`; keep `create_app()` as composition root and leave Observatory/BTC frontend ownership untouched. `[validates:runtime.http-boundary] [validation:test]`
- [x] 3.2 Move non-transport runtime behavior behind focused services and test removal of handler-local DB construction within the extracted surface. `[validates:runtime.http-boundary] [validates:runtime.resources] [validation:test]`
- [x] 3.3 Add route inventory and HTTP contract tests for paths, methods, parameters, status codes, response shapes, errors, SSE lifecycle where applicable, and capability behavior. `[validates:runtime.http-boundary] [validates:runtime.commands] [validation:test]`
- [x] 3.4 Run focused backend tests and compileall, inspect the diff, and commit
  the validated route-boundary unit.

## 4. Bounded durable EventBus admission

- [x] 4.1 Add and test typed lifecycle/admission outcomes plus a per-channel permit owner with validated finite workers/capacity and exact-once permit release. `[validates:runtime.admission] [validation:test]`
- [x] 4.2 Integrate and test admission after durable event/handler identity is known and before executor submission, preserving accepted `publish()` compatibility and typed failure behavior. `[validates:runtime.admission] [validation:test]`
- [x] 4.3 Add replay tests preserving per-handler idempotency across accepted, saturated, shutting-down, failed-submission, and partial multi-handler events; never finalize partial admission as success. `[validates:runtime.admission] [validation:test]`
- [x] 4.4 Add deterministic blocked-handler capacity tests proving admitted work never exceeds the configured bound, saturation is prompt, channels remain isolated, and permits return to zero. `[validates:runtime.admission] [validation:test]`
- [x] 4.5 Run focused EventBus/DAG/scheduler tests and compileall, inspect the
  diff, and commit the validated bounded-admission unit.

## 5. Runtime capacity observability

- [x] 5.1 Add and test a read-only process-generation capacity snapshot with lifecycle, workers, capacity, admitted/active/available counts, outcome totals, and last saturation time. `[validates:runtime.capacity-status] [validation:test]`
- [x] 5.2 Expose and test the snapshot through an additive operations/status route or field with explicit lifecycle semantics and no market-data scan or runtime write. `[validates:runtime.capacity-status] [validates:runtime.http-boundary] [validation:test]`
- [x] 5.3 Add structured, payload-safe admission logs and focused tests for healthy empty channels, saturation, unavailable runtime, process-generation reset, and bounded inspection cost. `[validates:runtime.capacity-status] [validation:test]`
- [x] 5.4 Run focused status/API tests and the bounded capacity smoke, inspect the
  diff, and commit the validated observability unit.

## 6. Final validation and delivery

- [x] 6.0 Resolve every P1 from the second frozen implementation review with
  temporary-root regression tests for command-owner overlap, terminal audit
  retry, strict/canonical payloads, semantic locked DB facades, no-handler
  replay, one-deadline shutdown, bounded runtime HTTP work, indexed sparse
  replay, process-identity claim fencing, agenda dispatch idempotency, nested
  agenda deferral, sync-state concurrency, reserved admission provenance, and
  claim-heartbeat cleanup. `[validates:runtime.resources] [validates:runtime.http-boundary] [validates:runtime.admission] [validates:runtime.capacity-status] [validates:runtime.commands] [validation:test]`
- [x] 6.1 Run focused pytest for resource lifecycle, backend route contracts, EventBus/DAG/scheduler behavior, durable command lifecycle and runtime status; run `python -m compileall trade_py trade_web tests`. `[validates:runtime.resources] [validates:runtime.http-boundary] [validates:runtime.admission] [validates:runtime.capacity-status] [validates:runtime.commands] [validation:test]`
- [x] 6.2 Run `./trade dev check --show-plan`, `./trade dev check`, and relevant
  backend smoke tests; report missing tools or unrelated baseline debt without
  weakening rules.
- [x] 6.3 Run the six-role implementation review, record consensus evidence, resolve every P0/P1, refresh changed design evidence, and rerun strict approval. `[validates:runtime.resources] [validates:runtime.http-boundary] [validates:runtime.admission] [validates:runtime.capacity-status] [validates:runtime.commands] [validation:review]`
- [x] 6.4 Run `git diff --check` and `git status -sb`, stage only intentional
  source/test/spec files, confirm no local DB/parquet/cache/build artifacts are
  tracked, and commit each validated unit with exact validation/compatibility
  notes.
- [x] 6.5 Push after three to five commits, then squash-merge only after approval;
  remove the worktree and feature branch per `AGENTS.md`.
