# Runtime Boundary Convergence Design Review

Review baseline: `a193407b7bc663506a98cd75ef428a3ed2bed832`

Artifact digest:
`sha256:c48815d5d6691d7cca7385c85fcebc7d7d9c76195abb86a7666fe1386dcbcd7f`

Panel: reliability, performance, architecture, data quality, observability, and
news/future integration.

Scores: reliability `9.0`, performance `9.0`, architecture `9.0`, data quality
`9.2`, observability `9.0`, news/future `9.4` (mean `9.1/10`).

Final status: approved for implementation with no P0 or P1 findings.

## Consensus strengths

- Durable SQLite event and per-handler rows remain authoritative; permits,
  futures, executor queues, and counters cannot imply successful completion.
- Web resources receive one explicit lifecycle owner, with admission and runtime
  services stopping before the owned database.
- Admission is finite and isolated by channel, while accepted publish calls,
  event identities, replay, route contracts, and persistent formats remain
  compatible.
- Capacity status distinguishes unavailable, healthy empty, saturated, stopping,
  and stopped process state without scanning market data or exposing payloads.
- The rollout is sliced, testable, and reversible without a schema migration or a
  whole-project rewrite.

## Accepted findings

| ID | Role | Priority | Finding | Required implementation evidence |
|---|---|---:|---|---|
| REVIEW-001 | performance | P1 | Capacity defaults and prompt saturation need measured limits rather than an unsupported throughput claim. | Block workers, submit past every configured bound, assert channel isolation and exact permit return, and record a deterministic local saturation-latency assertion. |
| REVIEW-002 | data quality | P1 | Replay and duplicate claims must stay deterministic for partially completed multi-handler events. | Cover partial parent state, replay of only non-OK handlers, and concurrent duplicate handler claims against a temporary SQLite database. |
| REVIEW-003 | architecture | P2 | Extraction must not create router coupling to EventBus internals or a second runtime owner. | Keep `create_app()` as the sole composition root and test one container lifecycle plus public facade use. |
| REVIEW-004 | observability | P2 | Operators must see process-generation resets and unavailable state rather than fabricated zero capacity. | Exercise fresh generation, stopped/unavailable runtime, healthy empty channels, and saturation in status contract tests. |
| REVIEW-005 | news/future | P2 | Future provider-backed news ingestion would require a new external-event/PIT/model applicability review. | Keep this change generic and re-run design governance before adding sources, refresh pipelines, or decision semantics. |

All findings are non-blocking because the governed tasks already require their
test evidence. They are accepted implementation obligations, not waivers from
validation.

## Role conclusions

- **Reliability:** approved `9/10`. No P0/P1 blocker. The state machine defines
  replayable saturation, shutdown, failed submission, partial admission, reverse
  startup cleanup, and durable crash recovery.
- **Performance:** approved `9/10`. No P0/P1 blocker. Finite per-channel bounds,
  O(1) admission, O(channel count) snapshots, and deterministic blocked-worker
  tests replace unbounded executor growth.
- **Architecture:** approved `9/10`. No P0/P1 blocker. Ownership remains cohesive:
  `create_app()` composes, the runtime package owns Web resources and one router,
  `trade_py.bus` owns dispatch, and `TradeDB` stays the persistence facade.
- **Data quality:** approved `9.2/10`. No P0/P1 blocker. Existing durable IDs,
  per-handler idempotency, SQLite locking, replay, and no-migration constraints
  remain explicit.
- **Observability:** approved `9/10`. No P0/P1 blocker. The proposed generation,
  lifecycle, bounded capacity, outcome counters, payload-safe logs, and
  unavailable semantics are sufficient for diagnosis.
- **News/future:** approved `9.4/10`. No P0/P1 blocker. No source, payload,
  timestamp, PIT, model, or trading semantics change; the NLP channel only gains
  generic bounded admission and isolation.

## Implementation order

1. Integrate the accepted shutdown contract and add the explicit Web resource
   owner.
2. Extract one system/runtime router behind owned services and contract tests.
3. Add typed bounded EventBus admission with replay and partial-failure tests.
4. Add the read-only capacity snapshot, route, logs, and bounded smoke.
5. Run the six-role implementation review, strict design approval, code-quality
   gates, and the completion audit before squash merge.

## Final implementation review: blocked snapshot

Reviewed implementation: `17b3a46a46306f5d51284ceb6c56749f2166071c`

Review worktree:
`/data00/home/guohuanwei.cztj/git_files/trade-wt-review-project-redesign-final-20260721`

Scores: reliability `6.0`, performance `6.5`, architecture `6.0`, data
quality `6.0`, observability `6.5`, news/future `7.2` (mean `6.4/10`).

Status: blocked with no P0 and twelve deduplicated P1 findings. The reports
agreed that bounded live admission, durable per-handler claims, payload
quarantine, process-group shutdown and capacity snapshots were strong, but
recovery fairness and complete runtime ownership were not ready to merge.

| ID | Consensus | P1 finding | Required resolution |
|---|---:|---|---|
| IMPL-001 | 2 judges | A transient claim-renewal exception stops the heartbeat and can permit stale concurrent execution. | Continue renewal with bounded backoff, make definitive ownership loss fail closed, and prove a second connection cannot execute concurrently. |
| IMPL-002 | 4 judges | Every bounded replay pass restarts at zero, so unavailable or saturated low-ID handlers can starve later channels indefinitely. | Keep bounded rotating keyset progress with safe wraparound and prove a later recoverable channel advances past more than one replay budget of blocked rows. |
| IMPL-003 | 1 judge | A child-handoff exception after a successful DAG job overwrites the run as error and reruns business work. | Preserve committed success and retry only the idempotent child handoff. |
| IMPL-004 | 1 judge | Agenda event-persistence exceptions escape after rows are marked queued, stranding the batch and stopping the daemon. | Contain the exception and restore current plus unattempted unpublished rows to pending. |
| IMPL-005 | 2 judges | Detached Web workflow processes and process-local command ownership are not crash-safe or durably queryable. | Supervise parent loss, reconcile stale ownership, use existing `job_runs`, and return a stable run identity with terminal state. |
| IMPL-006 | 2 judges | HTTP overload text and `Retry-After` invite a second POST after the first event is already durable. | Identify the existing deferred event and remove resubmission guidance. |
| IMPL-007 | 1 judge | Shared Web services perform unlocked private SQLite access despite one cross-thread `TradeDB` owner. | Add locked public facade methods and remove the unlocked runtime reads/writes. |
| IMPL-008 | 1 judge | A failed container stop is permanently stuck in `stopping` and cannot retry cleanup. | Serialize retry of unfinished command, bus and DB ownership stages through `stopped`. |
| IMPL-009 | 1 judge | `RuntimeCommandRunner` and the additive `/api/run` contract were implemented after the approved design snapshot. | Amend proposal, design, spec, impact evidence and obligations, then refresh digest-bound approval. |
| IMPL-010 | 1 judge | Live publication accepts or coerces non-object JSON that restart replay quarantines. | Enforce one object-only contract before insertion and keep historical malformed rows fail closed. |
| IMPL-011 | 1 judge | News notification fan-out aborts after the first admission failure. | Handle each durable notification independently, continue the fan-out, and close locally owned resources deterministically. |
| IMPL-012 | full-suite evidence | A pre-existing DAG test fake implements only `publish`, so the new idempotent child-handoff contract breaks the full suite. | Update the fake to the public child-handoff contract and retain the original DAG identity assertions. |

The findings are grouped into eight implementation units: EventBus lease and
fair replay, DAG and agenda recovery, payload parity, news and HTTP admission,
shared DB facade, retryable resource shutdown, durable crash-safe command
ownership, and governed contract evidence. All P1 findings require resolution
and another six-role review of a new frozen snapshot before merge.

The same snapshot passed the affected 83-test suite, compileall and the
changed-scope eight-step quality gate. A repository-wide pytest run found
`913 passed, 1 failed`; the single failure is IMPL-012. `./trade dev check
--all` also reported unrelated baseline/tooling debt in C++, BTC/Observatory,
shell and frontend surfaces; none of those files are changed by this proposal,
and no rules were weakened.

## Second implementation review: blocked snapshot

Reviewed implementation: `88e53d781a5bc594d43f1866d4cb87109ce9cabf`

Review worktree:
`/data00/home/guohuanwei.cztj/git_files/trade-wt-review-project-redesign-r2-20260721`

Scores: reliability `5.0`, performance `6.5`, architecture `6.0`, data
quality `5.0`, observability `6.0`, news/future `7.0` (mean `5.9/10`).

Status: blocked with no P0 and sixteen deduplicated P1 findings. The reports
confirmed that the first review's fair replay, transient renewal retry, DAG
handoff, producer containment, durable command rows, shutdown retry, and
payload-safe overload fixes materially improved the implementation. Fault
injection, overlapping-owner, long-outage, and large-history probes found
additional ownership and durability windows that the first regression set did
not cover.

| ID | Consensus | P1 finding | Required resolution |
|---|---:|---|---|
| IMPL2-001 | 4 judges | A second live Web command owner can bulk-reconcile the first owner's running rows as terminated. | Hold exclusive per-data-root command ownership before reconciliation and admission; release it only after durable terminal cleanup. |
| IMPL2-002 | 4 judges | A failed command terminal write is logged and abandoned while shutdown succeeds. | Retain exact pending completion state, retry it idempotently, and keep shutdown retryable and fail-closed while durable truth is missing. |
| IMPL2-003 | 3 judges | Falsy non-object HTTP payloads are coerced to an empty object. | Distinguish omission from explicit input and reject every supplied non-object before event or command persistence. |
| IMPL2-004 | 1 judge | Command audit persistence failures are mislabeled as spawn failures and raw internal errors reach HTTP clients. | Use distinct stable outcome/reason codes, sanitize public messages, and keep root causes in correlated server logs. |
| IMPL2-005 | 1 judge | Several Web request paths still use the shared SQLite connection through private unlocked calls. | Replace every Web `._conn` access with locked public runtime read facades and enforce the boundary in tests. |
| IMPL2-006 | 1 judge | A no-handler event rejected during shutdown is advertised as replayable but excluded from restart replay. | Keep the same durable event identity replayable and prove a later registered handler completes it. |
| IMPL2-007 | 2 judges | Resource shutdown has no owner-level wall-clock deadline and can report stopped with a live claim heartbeat. | Bound the full command/EventBus shutdown, track heartbeats and queued work, retain the DB on incomplete cleanup, and allow retry. |
| IMPL2-008 | 1 judge | Runtime HTTP/SSE inputs allow unbounded work, calendar is N+1, and heavy status scans block the event loop. | Add public bounds, use one calendar range query, and move/coalesce heavy status work off the event loop. |
| IMPL2-009 | 1 judge | Replay result count is bounded but candidate SQL cost grows with completed event history. | Use indexed replay candidate selection and large-history query-plan/performance coverage. |
| IMPL2-010 | 1 judge | A renewal outage beyond lease expiry permits a second runtime to reclaim while the first handler still executes. | Fence claims with durable process identity and refuse stale reclaim while that exact owner remains alive. |
| IMPL2-011 | 1 judge | An agenda publish exception after durable insertion restores the row and creates duplicate durable work. | Give agenda dispatch a deterministic durable key and recover the existing event after ambiguous exceptions. |
| IMPL2-012 | 1 judge | Nested agenda trigger saturation leaves the agenda row running after its durable child is deferred. | Use typed child admission and persist a truthful terminal/deferred agenda outcome once the child identity exists. |
| IMPL2-013 | 2 judges | Deterministic child payload validation occurs after insertion and poisons the handoff identity. | Validate and canonicalize object payloads before child insertion; quarantine malformed historical rows. |
| IMPL2-014 | 1 judge | Shared sync-state read/write helpers still bypass the connection lock. | Lock every sync-state facade and add concurrent reader/writer tests. |
| IMPL2-015 | 1 judge | Live handlers receive the caller's mutable dictionary rather than the persisted JSON snapshot. | Serialize once and dispatch a decoded canonical snapshot so live and replay evidence are identical. |
| IMPL2-016 | 1 judge | Automatic replay classifies failures from untrusted handler exception-text prefixes. | Persist reserved runtime-admission provenance and keep arbitrary handler/provider exceptions terminal. |

The review also identified P2 follow-ups: remove the CLI's private EventBus
fallback authority, add command run correlation and degraded health reason
codes, replace per-claim heartbeat threads with a fixed renewal scheduler,
support explicit subscriber/provider identities, and continue incremental
route extraction. These do not waive any P1 and must not delay the required
new frozen review.

The frozen snapshot passed 121 changed-surface tests, Ruff, BasedPyright,
compileall, and the non-strict design diagnostic. A repository-wide run found
`940 passed, 4 failed`: one newly added test-isolation failure was fixed in
`da626d0`; the other three are the pre-existing `add-design-quality-gates`
approval becoming stale on `2026-07-21` because its evidence is dated
`2026-07-20`. No baseline approval evidence or unrelated worktree was changed.

## Final implementation review: approved after resolution

Final implementation: `a510effc9d2b1bb10c48ed3fcad3d8e95f359e07`

Final review worktree:
`/data00/home/guohuanwei.cztj/git_files/trade-wt-review-project-redesign-r6-20260721`

The completed six-role R5 panel reviewed `02906cfb3a2317a19dffe8cbe3a4ba0169097af7`.
It approved reliability, data quality, observability, and news/future integration,
and blocked performance plus architecture pending two resolutions. The R6 delta
contains only the reviewed performance correction:

- calendar, agenda, and backup SQLite reads now run through
  `asyncio.to_thread` in `RuntimeService`;
- the runtime router awaits those service methods without changing paths,
  defaults, bounds, or response contracts; and
- a deterministic concurrency test proves all three reads enter worker threads
  while the event loop remains able to release them.

The architecture disagreement received the required reconciliation against the
governed proposal and design. This change explicitly rejects a big-bang Web
rewrite and owns the incremental system/runtime surface extracted from
`app.py`. Unchanged legacy `readiness.py` and `ops_workspace.py` SQL is baseline
debt outside this change; the changed runtime surface is enforced by
`test_web_db_boundaries.py` and uses semantic locked `TradeDB` facades. Expanding
this proposal to all Web modules would violate its stated non-goals and the
repository's narrow-change rule.

Several additional R6 incremental judge attempts remained stuck in the agent
notification layer and produced no reports. They are not counted as approvals.
The approval below is the synthesis of the six completed R5 role reports, the
resolved R6 performance diff, the scope reconciliation, and the final immutable
validation evidence. No missing report is represented as a successful judge.

Scores after resolution: reliability `8.7`, performance `8.8`, architecture
`8.5`, data quality `9.1`, observability `8.0`, news/future `8.5` (mean
`8.6/10`).

Status: approved with no P0 or P1 findings remaining.

| ID | Role | Priority | Finding | Resolution |
|---|---|---:|---|---|
| FINAL-001 | reliability / data quality | P1 | Reusing one idempotency identity could silently return a different payload; Python equality also conflated nested JSON booleans and numbers, and historical non-finite constants could reach replay handlers. | Compare strict semantic JSON with boolean/number type preservation, reject non-finite live and replay values, retain malformed-history quarantine, and cover once plus child identities. |
| FINAL-002 | performance | P1 | Calendar, agenda, and backup routes executed synchronous SQLite reads on the FastAPI event loop. | Offload all three reads in `RuntimeService`, await them in the router, and prove concurrent worker-thread execution. |
| FINAL-003 | architecture | P1 | A judge treated private SQL in unchanged legacy Web modules as part of this runtime migration. | Reconciled as outside the explicitly incremental `app.py` system/runtime scope; the changed surface has semantic facade enforcement and no private SQL escape hatch. |
| FINAL-004 | observability | P2 | EventBus capacity does not yet include a separate command-runner capacity section, and CLI shutdown lacks a full subprocess integration test. | Accepted follow-up; command saturation is still explicit through stable HTTP outcomes and durable `job_runs`, while container shutdown has focused deadline/retry coverage. |
| FINAL-005 | news/future | P2 | News tests do not exercise every urgent/Fear-and-Greed fan-out permutation. | Accepted follow-up; current per-notification continuation, NLP isolation, strict payloads, and durable replay are covered without changing source, PIT, model, or trading semantics. |

Final validation at the R6-equivalent feature HEAD:

- all 16 redesign-owned test files: `214 passed`;
- repository-wide pytest: `1034 passed, 3 failed`; all three failures are the
  unchanged `add-design-quality-gates` current-date approval debt, confirmed by
  `core.review.stale`;
- changed-scope BasedPyright: `0 errors, 0 warnings, 0 notes`;
- changed-scope Ruff format and lint: passed;
- `python -m compileall -q trade_py trade_web tests`: passed;
- non-strict design diagnostic: `0 blockers, 0 warnings`;
- `git diff --check`: passed.

No schema, index, DB version, parquet, model, source-provider, PIT, trading, or
C++ engine behavior changed.
