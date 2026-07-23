# Restructure Trade Architecture v1

## Why

Trade is a mixed trading research system with a Python control plane, a Bash
CLI facade, FastAPI/React product surfaces, SQLite and parquet persistence,
notebooks, schedulers and a C++ engine. The current repository has useful
local boundaries, but actual code audit shows that lifecycle, data-product
ownership and cross-surface composition are still concentrated in several
large, cross-domain entry points:

- `trade_py/db/trade_db.py` is a roughly 4,690-line global `TradeDB` facade.
  Construction opens SQLite and can run schema initialization, migrations,
  indexes and default seed work. Its methods and mixins own records from
  unrelated business areas.
- `trade_py/cli/data.py` is roughly 2,725 lines and combines compatibility
  commands, updates, DB access, operational reporting and direct orchestration.
  `trade_py/cli/research.py` and `trade_py/cli/observatory.py` retain related
  compatibility behavior in separate locations.
- `trade_web/backend/app.py` is a roughly 3,781-line FastAPI composition and
  route module. It mixes BFF reads, direct SQLite and parquet access, state
  mutation, runtime operations and workflow launches. Some GET routes mark
  stale state, so a query can write.
- `trade_py/data/access/gateway.py` allows read-looking methods such as
  `get_kline`, `get_fund_flow` and `ensure_sentiment_gold_date` to fetch,
  repair or write. This makes query cost, data freshness and side effects
  unclear to callers.
- `trade_py/data/market/crypto` already has raw payload digests, staged runs,
  manifests, current publication pointers and revision/gate concepts, but
  captures and dataset publication are coupled in the same service/store area.
- Observatory already has immutable artifact references, release/snapshot
  concepts, a catalog projection and a read-only query facade. It is a valuable
  product/query surface, not an appropriate future bounded context. Its PIT
  resolver currently treats a missing timestamp as visible and does not yet
  implement a distinct `latest_restated` revision transformation.
- `trade_py/bus` already provides durable event records, bounded channel
  admission and replay, while `trade_py/jobs/__init__.py` remains a large
  registry/execution concentration directly coupled to the bus.
- `research/notebooks/btc_h1_observatory.py` modifies `sys.path` and reads
  repository structure directly. The CMake Python-binding plan names an
  extension `trade_py`, while `trade_py/__init__.py` self-imports that package
  as a native-extension probe; neither is a stable native boundary.

These are code-audit facts, not conclusions drawn from historical plans. The
repository must preserve its currently useful CLI, HTTP, Web, SDK, notebook,
scheduler and event surfaces while establishing a long-lived architecture that
has unambiguous ownership, immutable inputs for formal data and research work,
and a safe path for incremental change.

## What Changes

This change produces the governed architecture and migration design for an
incremental domain-modular monolith. It does **not** implement the architecture
or alter production behavior.

The target Python architecture is:

```text
src/trade/
  kernel/
  capture/
  datasets/
  studies/
  decision_support/
  processes/
  platform/
  interfaces/
  bootstrap/
```

`web/`, `engine/`, `tests/`, `tools/`, `examples/`, `docs/`, `openspec/`,
`config/` and `deployment/` remain separate repository-level concerns. The
eventual `src/trade` layout is a staged destination; current `trade_py`,
`trade_web/backend`, existing executable names and import paths remain
compatible throughout the migration window.

The design establishes:

- Four business bounded contexts: Capture, Datasets, Studies and Decision
  Support. Each uses a local `contracts`, `domain`, `use_cases`, `ports` and
  `adapters` cell. Context contracts are the only cross-context import surface.
- A deliberately small `kernel` for IDs, time, digests, errors, results and
  envelopes only where semantics are truly identical and have no business
  owner.
- Immutable capture artifacts, dataset versions/snapshots and study results,
  with explicit references, lineage, revision/supersession and point-in-time
  semantics. Formal Study runs accept only `DatasetSnapshotRef`.
- A separate `processes` area that owns cross-context, long-running flows using
  commands, past-tense events, outbox delivery and immutable references. The
  design covers refresh, evidence-gap closure, revision propagation, registered
  study execution, publication, projection rebuilding and daily workspace
  generation.
- A technical-only `platform` that provides execution, events, scheduling,
  persistence, settings and backup capabilities without business vocabulary.
- `interfaces` as compatibility-preserving CLI, HTTP, SDK, event, schedule and
  import adapters. Pages are BFF/query compositions; they do not become
  bounded contexts or direct table owners.
- A table-and-artifact ownership model, query/command separation, database
  migration ownership rules and architecture guardrails.
- A detailed compatibility matrix for existing CLI commands, HTTP/SSE behavior,
  current Web page surfaces, Observatory queries, SDK/notebooks, imports,
  scheduler and event admission.
- A phased child-change sequence that avoids a big-bang move and defines
  validation, data safety, rollout and rollback for every implementation
  slice.

Eight capabilities are introduced as architecture requirements:

1. `repository-architecture`
2. `capture-contract`
3. `dataset-product-lifecycle`
4. `study-lifecycle`
5. `process-orchestration`
6. `interface-compatibility`
7. `dependency-guardrails`
8. `migration-governance`

## Design Scope

This is a Non-trivial architecture change. Its future implementation affects
public contracts, durable state ownership, migration ownership, point-in-time
and revision semantics, research/model inputs, external event data and runtime
concurrency. The design therefore declares all seven design-policy impacts:

- **Public contract:** stable CLI, HTTP/SSE, Web, SDK, notebook, scheduler and
  event-entry behavior must remain compatible through adapters and snapshots.
- **Persistent write:** context-owned repositories, outbox and lifecycle
  transactions replace cross-domain facade access without changing
  authoritative history silently.
- **Schema migration:** logical table owners and context-owned migrations will
  be introduced incrementally against the existing SQLite database.
- **Point in time:** snapshots, knowledge time, available/observed/event time,
  revisions and fail-closed missing-time behavior are formalized.
- **Predictive model:** study hypotheses, feature/label definitions,
  validation, promotion and stale-result propagation gain explicit lifecycle
  contracts.
- **External event data:** capture formalizes pull, push, stream, import,
  replay, backfill, raw receipts, checkpoints and provider revision behavior.
- **Runtime concurrency:** process managers, outbox dispatch, scheduling,
  retries, idempotency and recovery create durable non-linear workflows.

## Non-Goals

- No production Python, C++, TypeScript, JavaScript, shell, configuration,
  database schema, migration, data artifact, import or runtime behavior is
  changed in this architecture-design change.
- No source directory is moved, no import is bulk-edited and no public CLI,
  HTTP, SSE, SDK, notebook, scheduler or event contract is removed.
- No real data, production database or generated parquet is read for mutation,
  changed or committed.
- No recommendation or execution logic is expanded, replaced or validated as a
  trading model.
- No new independent `evidence`, `quality`, `assurance`, `observatory`,
  `shared`, `common`, `utils`, `helpers`, `services` or `manager` domain is
  created.
- No distributed queue, database replacement, C++ algorithm rewrite or
  big-bang package rename is proposed as a prerequisite.

## Compatibility and Rollout Intent

Existing public entrances stay externally stable while their implementation
gradually delegates to context contracts, use cases and BFF/query handles:

- The `trade` Bash facade retains `run`, `status`, `data`, `show`, `research`,
  `kg`, `observatory`, `config`, `event`, `backup`, `start`, `web` and `dev`.
  `interfaces/cli/compat` will preserve command aliases and argument behavior
  until published removal criteria are met.
- Existing HTTP paths, methods, inputs, status codes, response shapes, SSE
  behavior, capability gates and error envelopes are inventoried before
  extraction. `interfaces/http/compat` forwards legacy forms to new
  use-case/query contracts.
- Current React pages keep their route and response expectations. Their BFF
  implementations compose context-owned query handles rather than directly
  reading business tables, scanning parquet, calling providers or writing
  lifecycle pointers.
- Observatory becomes a compatibility/BFF surface over Datasets and Studies;
  it is not a fifth business context.
- SDK and notebooks use the same approved query/use-case contracts as CLI and
  Web. File upload, multipart, local-directory and notebook imports become
  `RequestCapture(mode="import")`, never a direct formal dataset write.
- Scheduler emits commands only. Event handlers decode, invoke a process
  manager and persist handling results; neither takes on end-to-end business
  orchestration.

The implementation is intentionally split into independently reviewable child
changes. Every slice will use a dedicated worktree, focused tests, compatibility
snapshots, temporary data roots and a reverse-order code rollback path. No
existing entry point is deleted until its compatibility matrix, contract tests
and published removal conditions are satisfied.

## Validation

This design change is complete only when its governed artifacts pass the
repository workflow:

1. `./trade dev design-check restructure-trade-architecture-v1`
2. An independent six-role review worktree covering architecture, reliability,
   performance, data quality, observability and news/temporal semantics.
3. P0 findings resolved; material P1 findings incorporated into the design,
   task plan or an explicit child-change follow-up.
4. A refreshed non-strict design check.
5. `./trade dev design-check restructure-trade-architecture-v1 --strict`

Future implementation changes must additionally run the repository's code
quality plan/check, focused behavior tests, language-specific checks,
compatibility snapshots, `git diff --check` and a second implementation-diff
six-role review before merge.
