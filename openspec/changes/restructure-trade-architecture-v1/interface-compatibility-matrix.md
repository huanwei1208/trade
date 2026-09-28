# Interface Compatibility Matrix

## Purpose and Audit Basis

This attachment is the design baseline for preserving Trade's current public
surfaces while implementation moves behind Context contracts, Process Managers
and Platform APIs. It does not authorize a route, command or payload change.

| Item | Audited fact |
|---|---|
| Source commit | `cb6cb248f07594734ae7ff72e2aa44d719c54d87` |
| CLI registry | `trade_py/cli/main.py` and root `trade` |
| HTTP registry | `trade_web/backend/app.py`, `runtime/router.py`, `observatory/router.py` |
| React consumers | `trade_web/frontend/src/lib/api.ts`, tracked pages and components |
| SDK/notebook | `trade_py/observatory/query/sdk.py`, `research/notebooks/btc_h1_observatory.py` |
| Registration probe | factory construction only; no lifespan entry and no production data access |

The compatibility child SHALL regenerate this inventory from the registered
FastAPI application and CLI parser, then freeze representative request,
response, error, header and exit-code goldens before delegating a handler.
Current routes have no `response_model`, and `app.openapi()` fails on the
function-local `PredictRequest` forward reference. Until that defect is fixed,
the registered route table plus payload goldens is authoritative. An OpenAPI
failure is a blocker, not permission to omit `/predict` or write an empty
snapshot.

## Compatibility Ownership and Retirement Rule

| Surface | Compatibility owner | Frozen contract | Target delegation | Minimum retirement condition |
|---|---|---|---|---|
| Root executable | root `trade` facade | setup/build/test/run dispatch, exit codes, environment forwarding | Bootstrap and `interfaces/cli` | replacement is documented, parser/exit goldens pass for one release window, and usage evidence meets the child policy |
| Canonical and legacy CLI | `interfaces/cli/compat` | names, aliases, flags, defaults, stdout/stderr shape, exit codes | Context command/query handles, Processes, Platform status | each command has an equivalent, migration guide, telemetry/usage evidence and at least 30-day compatibility window |
| HTTP and SSE | `interfaces/http/compat` | method/path, input location/default/validation, status/header/error/payload and stream semantics | Context use cases/queries, Processes and Platform query APIs | registry, OpenAPI, golden response and React contract parity pass; no known consumer remains on the legacy adapter |
| Product pages/BFF | `interfaces/http/bff` and React surface | page URL/deep links, URL/local state, DTO fields and explicit failure states | bounded query composition only | new BFF/page passes old/new goldens, accessibility, responsive and rollback selection tests |
| Python SDK | `interfaces/sdk` | stable import, typed DTO/ref/query/command surface and errors | the same handles used by CLI/HTTP | internal import consumers have migrated and compatibility imports pass the declared window |
| Notebook | SDK compatibility adapter | executable entry, parameters and visible result schema | `interfaces/sdk` only | notebook runs without `sys.path`, repository scan, direct parquet/repository or adapter import |
| Imports/uploads | `interfaces/imports` | source identity, filename/content metadata and caller-visible receipt | `RequestCapture(mode="import")` | every ingress returns a Capture receipt and formal builds prove immutable refs |
| Scheduler/events | `interfaces/schedules`, `interfaces/events` | schedule/topic/event ID/envelope/cursor and admission errors | command envelopes and Process Managers | direct job callback has no remaining owner and replay/idempotency fixtures pass |

No compatibility surface may be deleted because a module or directory moved.
Retirement is per command or route, never by broad wildcard.

## CLI Registry

The help comment says "10 domains", but the actual parser registers thirteen
visible domains and eight hidden shims. Compatibility follows the parser.

### Canonical domains

| Command | Current role | Target owner/delegation | Required fixtures | Removal |
|---|---|---|---|---|
| `trade run` | DAG, daily, agenda, job, belief, recommendation and picks triggers | Processes command ingress; Context commands for owner-local behavior | parser/help, flags, accepted/refused receipt, exit code | no planned removal; subcommands may deprecate individually |
| `trade status` | health, data, jobs and freshness | read-only Platform/Process/Context status queries | text/JSON, unavailable state and exit-code goldens | no planned removal |
| `trade data` | capture, sync, backfill, warehouse, realtime, news and BTC operations | Capture and Datasets commands/queries through compat | every retained subcommand, replay/import receipt and data-root isolation | only an individual alias after equivalent command and migration window |
| `trade show` | read-only DAG, calendar, agenda, event, run, backup and quality views | Platform/Process/Context queries | output ordering, filters, empty/unavailable and exit codes | no planned removal |
| `trade research` | model, factor and evaluation entry | Studies; reusable inputs through Datasets contracts | command/alias, SnapshotRef input and deterministic-result fixtures | external name remains while internal owner becomes Studies |
| `trade kg` | learned graph candidates, review, promotion and snapshot | classify each action between Datasets, Studies and Decision Support | per-subcommand owner, state transition and legacy output snapshots | only after the file/table owner audit and explicit replacement |
| `trade observatory` | BTC catalog, snapshot, research and projection operations | Datasets/Studies queries and commands behind compat | catalog/research output, capability and immutable-ref goldens | product-neutral replacement plus compatibility window |
| `trade config` | settings, source registry, watch list and DAG switches | Platform Settings, Capture SourceManifest and compatible command adapters | secret redaction, get/set/unset/source flags and exit codes | no planned removal |
| `trade event` | trigger, run, event list, DAG compatibility and backfill | Platform Events/Scheduling plus Process ingress | topic/envelope/admission/replay/idempotency snapshots | legacy subcommands only after command-envelope parity |
| `trade backup` | create, push, restore and list | Platform Backup | manifest/hash, safe staged restore, refusal and exit codes | no planned removal |
| `trade start` | EventBus daemon | Bootstrap runtime composition | startup/readiness/signal/one-deadline shutdown receipt | no planned removal |
| `trade web` | FastAPI/React process | Bootstrap plus Interfaces HTTP | bind/startup/readiness/repeated-signal/bounded-shutdown fixtures | no planned removal |
| `trade dev` | quality, OpenSpec and review tooling | developer interface, not a business Context | command discovery and governance exit codes | no planned removal |

### Hidden legacy domains

| Shim | Current canonical direction | Compatibility evidence | Deletion condition |
|---|---|---|---|
| `doctor` | `status` | warning, forwarded args/output and exit parity | usage threshold, migration notice and one release window |
| `inspect` | `show` | all inspect subcommands and warning snapshot | same |
| `daily` | `run` / `status` | forwarded daily workflow and failure parity | same |
| `ops` | `status` / `run` / `show` | status/backfill/inspect/freshness forwarding | same |
| `account` | `config watch` / picks view | add/remove/list/set/get/suggest behavior | explicit replacement for every subcommand |
| `model` | `research model` | all model aliases, output and exit parity | same |
| `factor` | `research factor` | status/evaluate/IC aliases | same |
| `evaluate` | `research evaluate` | daily/source/event/model/gate aliases | same |

## HTTP Registration Modes

The four FastAPI documentation/schema routes are not counted as business
`APIRoute` entries.

| Mode | `app.routes` | Business routes | Contract |
|---|---:|---:|---|
| Observatory default-off | 72 | 68 | all base routes plus capability probe with disabled or catalog state; no BTC data routes |
| Observatory enabled | 81 | 77 | all base routes, capability probe and nine read-only BTC routes |
| Enabled registration error | 72 | 68 | all base routes plus capability `state=error`; no partially registered BTC data surface |

All modes preserve the root/SPA routes and two SSE routes. The capability probe
is always present. A compatibility test SHALL compare route method, path,
endpoint signature, schema visibility and registration mode. It SHALL also
exercise representative payload/error goldens because every audited business
route currently has `response_model=None`.

### Common HTTP behavior

- Normal JSON routes return `200` unless the table below names another result.
- FastAPI validation currently returns its framework `422` detail payload.
  Compatibility adapters preserve that shape until a versioned ErrorEnvelope
  transition is separately approved.
- Explicit `HTTPException` errors currently use `{"detail": <string>}`.
  Network/client parsing in `api.ts` consumes that string when present.
- Command admission can return a structured refusal. `/api/run` returns `503`
  with `accepted=false`, `outcome`, `message`, `reason_code`, `run_id`,
  `status`, and optional `Retry-After`. Event admission errors must be frozen
  from their current response helper.
- Existing broad exception handlers on state/explanation/causal paths return
  `500` with current detail text. Extraction must map safe errors without
  silently changing client-visible status or pretending failure is empty.
- Read-only target BFFs never inherit current GET-side mutations. Compatibility
  may preserve the response while dispatching an explicit command, then
  deprecate write-on-GET only through a child public-contract change.
- A JSON field currently consumed by React cannot change number/string/null
  semantics during structural migration. In particular, Observatory
  OHLCV/ratio values remain decimal-preserving strings and nullable values
  remain `null`, never synthetic `0` or `""`.

## Base HTTP Route Inventory

The following tables account for all 68 business routes in default/error mode:
seven Runtime router routes, sixty application routes including root and SPA
fallback, and one Observatory capability route.

### Runtime, calendar, agenda and backup: 7 routes

| Method and path | Inputs and current result | Target delegation | Golden/compatibility check |
|---|---|---|---|
| `GET /api/status` | no input; runtime status payload | bounded Platform/Process/Context status composition | payload, explicit unavailable, no writes |
| `GET /api/runtime/capacity` | no input; capacity snapshot | Platform Execution/Events status | limits, in-flight and saturation fields |
| `GET /api/events/stream` | `after_id=0` (`>=0`), `limit=50` (`1..500`), `poll_seconds=2.0` (`0.25..60`) | shared bounded Platform Events SSE hub | headers, event/cursor/reconnect, disconnect and slow-client tests |
| `GET /api/runtime/stream` | `scope="report"`, `poll_seconds=2.0` (`0.25..60`) | shared bounded Platform/Process status SSE hub | headers, scope, heartbeat/disconnect and resync |
| `GET /api/calendar` | `date_str=null`, `days=5` (`0..366`) | Datasets calendar query or owned projection | query defaults and date payload |
| `GET /api/agenda` | `limit=50` (`1..500`), `status=null` | Platform Scheduling/Process query | filters, ordering, empty/unavailable |
| `GET /api/backups` | `limit=20` (`1..500`), `status=null` | Platform Backup query | status/filter and safe metadata |

Both SSE routes keep `text/event-stream`, `Cache-Control: no-cache`,
`Connection: keep-alive` and `X-Accel-Buffering: no`. The target declares
identity/instance connection caps, per-client item and byte queues, heartbeat,
idle timeout, cursor expiry/resync and slow-client disconnect. It must not
create one database poller per connected client.

### DAG, command, event and workflow control: 16 routes

| Method and path | Inputs, status and current payload identity | Target delegation |
|---|---|---|
| `GET /api/dag` | `all=false`; `{stages,total}` | Platform Scheduling/Process projection; current GET must become read-only |
| `GET /api/dag/runtime` | `limit=200` (`1..500`); runtime nodes; currently marks stale records | Process/Platform query plus separately admitted stale transition |
| `POST /api/dag/{dag_id}/enable` | integer path; `{id,enabled:true}` | versioned schedule/config command |
| `POST /api/dag/{dag_id}/disable` | integer path; `{id,enabled:false}` | versioned schedule/config command |
| `PATCH /api/dag/{dag_id}/config` | body `config` object; `400` invalid object, `404` missing row; `{id,config}` | schedule definition command |
| `POST /api/dag/{dag_id}/run` | body `mode=self|upstream|downstream|full`, optional payload/date range; `400/404/409` plus admission refusal; accepted event/target identity | Process command ingress |
| `POST /api/trigger` | body requires `topic`, optional payload; `400` or admission refusal; event ID/topic | Platform Events ingress |
| `POST /api/run` | body requires `target`, optional payload and integer `limit=10` (`1..500`); `400`; accepted PID/run ID or structured `503` refusal | Platform Execution/Process command |
| `GET /api/events` | `limit=50` (`1..500`), `topic=null`; currently marks stale events | Platform Events query plus explicit owner command for stale transition |
| `GET /api/workflows` | `limit=20` (`1..500`); currently marks stale state | Process query |
| `GET /api/workflows/{root_event_id}` | integer path; `404`; currently marks stale state | Process query |
| `POST /api/workflows/{root_event_id}/rerun-node` | body `dag_id` or `node_id`, `mode`; `400/404/409` or admission refusal; accepted event identity | Process command |
| `GET /api/runs` | `limit=50` (`1..500`), `stage=null`; currently marks stale runs | Platform Execution/Process query |
| `GET /api/models` | no input; model registry list | Studies model/result query |
| `GET /api/automation/overview` | no input; calendar/schedule/agenda/event overview | bounded Platform/Process BFF |
| `GET /api/events-page` | no input; cached page payload; currently marks stale state | Interfaces Operations BFF |

Golden coverage freezes every body alias, accepted/refused payload, admission
reason/status/header, run/event correlation, query ordering and current
GET-side mutation debt. The target query path may not mutate stale state.

### Reports, data readiness, replay and operations: 18 routes

| Method and path | Inputs, status and payload identity | Target delegation |
|---|---|---|
| `GET /api/report-page` | no input; cached report page; current stale marking | Today/Operations BFF over owner queries |
| `GET /api/kg-page` | no input; cached KG page | Datasets/Studies/Decision Support BFF after file classification |
| `GET /api/overview` | alias of report page | compat alias to the same BFF |
| `GET /api/hive` | alias of data health | compat alias to Datasets quality query |
| `GET /api/data-health` | no input; cached health payload; current stale marking | Datasets quality/readiness BFF |
| `GET /api/research/warehouse/tables` | no input; warehouse table inventory | Studies query over published Dataset refs |
| `GET /api/research/warehouse/{layer}/{table}` | path plus `limit=100`; `404` for invalid selection | Studies query; prohibit arbitrary path/repository access |
| `GET /api/readiness-grid` | `days=30`, `end_date=null`, `datasets=null`; unsupported days coerce to 30 | Data Ops BFF over Capture/Datasets/Processes |
| `GET /api/readiness/replay-plan` | required `dataset`; optional `date`, `date_from`, `date_to` | read-only Process planning query |
| `GET /api/readiness/history` | `dataset=null`, `date=null`, `limit=40` | Process/operation receipt query |
| `POST /api/readiness/detect-changes` | body dataset/date range; `400` for missing required values | Datasets comparison command/query with receipt |
| `POST /api/readiness/backfill` | body dataset/date range and `mode=data_only|data_plus_downstream|full_replay`; `400`; accepted action ID/plan | Capture/Dataset Process command |
| `POST /api/readiness/replay` | same modes, default `data_plus_downstream`; `400`; accepted action ID/plan | replay Process command |
| `GET /api/ops/compute-layers` | `date=null`; compute graph payload | Operations BFF over Process/Dataset/Study state |
| `GET /api/ops/node/{node_id:path}/result` | path plus `date=null`; `404` invalid node | bounded owner query |
| `GET /api/ops/dependency-path` | required comma-separated `node_ids`; `400` empty | Process dependency query |
| `POST /api/ops/replay/preview` | selected node/cell IDs, date range, mode/action; `400` | read-only Process command preview |
| `POST /api/ops/replay/execute` | same selection; `400`; execution response | Process command receipt |

Replay/background work must be Bootstrap-owned and recoverable; a daemon thread
spawned by a router is not the target design.

### Prediction, Today, research, decision and trust: 15 routes

| Method and path | Inputs, status and payload identity | Target delegation |
|---|---|---|
| `POST /predict` | typed body `{symbols: string[], date?: string}`; `400` empty symbols; prediction list/object | Studies inference port/query; retain route while OpenAPI model is repaired |
| `POST /predict/reload` | no input; `{reloaded,models}` | explicit Studies model-generation command |
| `GET /api/belief/{symbol}` | path plus `days=30`; `400` empty symbol; belief history/attention/recommendation | Studies + Decision Support BFF |
| `GET /api/today-page` | no input; cached page DTO | Today BFF: Datasets + Studies + Decision Support + Platform |
| `GET /api/signals-page` | `search=null`, `limit=300`, currently clamped to `50..2000` | Studies/Decision Support query |
| `GET /api/state/{symbol}` | path, `date=null`; `400/500`; WorldState DTO | Studies query |
| `GET /api/explain/{symbol}` | path, `date=null`; `400/500`; DecisionExplanation DTO | Decision Support view over immutable refs |
| `GET /api/causal/{symbol}` | path; `date`, `persist=false`, `validate=false`, `horizons="1,5,20"`; `400/500` | read query plus compat-dispatched command when `persist=true` |
| `GET /api/causal/{symbol}/validation` | path; `date`, `snapshot_id`, `horizons`, `persist=true`; `400/500` | read query plus compat command; default write-on-GET remains explicit debt |
| `GET /api/actions-page` | no input; action candidates and rationale | Decision Support BFF; no trade execution expansion |
| `GET /api/trust/overview` | no input; scalar/coverage/trend with current zero fallbacks | Datasets + Studies + Decision Support Trust BFF; absent input becomes unavailable, not trusted zero |
| `GET /api/belief-graph/{symbol}` | path plus `days=30`; `400`; graph/provenance DTO | Studies/Decision Support BFF |
| `GET /api/symbol-evidence/{symbol}` | path plus `days=30`; `400`; market/evidence/attention lists | Datasets/Studies query |
| `GET /api/symbol-sector/{symbol}` | path plus `peer_limit=10`; `400`; sector/peer DTO | Datasets/Studies/Decision Support query |
| `GET /api/symbol-data-ops/{symbol}` | path; `400`; per-domain freshness/coverage/actionability | Data Ops BFF over Capture/Datasets/Processes |

Structural migration freezes current payloads first. Semantic debts such as a
trust zero fallback or write-on-GET cannot be silently "fixed" inside the
architecture move; their versioned successor must expose explicit
unavailable/command receipts while the compatibility adapter preserves the old
contract until its separately approved removal.

### Symbol commands, K-line and data inventory: 9 routes

| Method and path | Inputs, status and payload identity | Target delegation |
|---|---|---|
| `POST /api/symbol-data-ops/repull` | JSON `{symbol,domains}`; `422` malformed JSON, `400` missing symbol, admission refusal; accepted job ID/message | `RequestCapture`/Process command |
| `POST /api/symbol-data-ops/replay` | same body/errors; accepted job ID/message | replay Process command |
| `POST /api/symbol-data-ops/mark-verified` | same body/errors; accepted updated domain list/message | Datasets quality review command, never a router table write |
| `GET /api/kline/{symbol}` | `days=60`, `date=null`, `adjust=qfq`, `timeframe=daily`; invalid adjust coerces to qfq; `400` empty symbol | Datasets market query with compatibility DTO |
| `GET /api/data/assets` | no input; asset inventory/summary | Data Ops BFF over Capture/Datasets |
| `GET /api/data/kline/{asset_id:path}` | `days=30` clamped `1..3650`; `400` empty ID; OHLCV rows | Datasets query; no direct parquet read |
| `GET /api/data/gaps/{asset_id:path}` | path; `400` empty ID; expected/present/coverage/gaps | Datasets quality query |
| `GET /api/data/news` | `source=""`, `days=3` clamped `1..30`, `limit=30` clamped `1..200`; article list/total | Datasets news product query |
| `GET /api/data/coverage` | no input; class/type coverage matrix | Datasets quality projection |

Direct parquet scans and fallback-to-empty behavior are current facts, not
target architecture. The compatibility child freezes old responses; owner
queries return typed partial/unavailable/error states and the adapter maps them
without claiming missing data is a successful formal result.

### Root, SPA and capability: 3 base routes

| Method and path | Contract | Target delegation |
|---|---|---|
| `GET /` | serves the selected React `index.html`, otherwise `{"message":"Trade DAG API","docs":"/docs"}`; excluded from OpenAPI | Interfaces HTTP/static adapter |
| `GET /{full_path:path}` | last route; serves SPA index for non-API paths, `404` for API/docs/OpenAPI paths or missing index; excluded from OpenAPI | Interfaces HTTP/static adapter |
| `GET /api/v1/observatory/capability` | always registered; states `disabled`, `catalog_missing`, `catalog_stale`, `catalog_corrupt`, `ready`, `error`; fields include `enabled`, `state`, `show_nav`, optional generation/reason | Interfaces capability query over Datasets projection health |

The heading count excludes the always-on capability cross-surface from the
root/SPA pair: sixty application routes plus seven Runtime routes plus this
capability route equals the 68-route base inventory.

## Enabled-Only BTC Observatory Routes

These nine routes exist only when full Observatory registration succeeds.
They are read-only compatibility endpoints and remain the rollback surface for
the BTC workspace child.

| Method and path | Frozen inputs | Result, cache and errors | Target delegation |
|---|---|---|---|
| `GET /api/v1/observatory/assets/crypto.BTC/context` | `channel=observed`, `knowledge_as_of=latest`, `knowledge_mode=installation_observed`, `revision_policy=as_known`, optional `snapshot_id`, `run_id`; `If-None-Match` | one context/snapshot identity, decimal-safe metadata, `ETag`/`304`; typed `400/404/409/422/503` | Datasets snapshot/context query |
| `GET /api/v1/observatory/assets/crypto.BTC/series` | `view=composite`, same knowledge/revision selectors, `include_quarantined=false`, optional snapshot/run, `from`, `to`; `If-None-Match` | composite or single-channel rows, `ETag`/`304`; same typed errors | Datasets immutable series query |
| `GET /api/v1/observatory/assets/crypto.BTC/dates/{market_date}` | date path, `snapshot_id=null`, `channel=formal` | OHLCV/reconciliation/revision/lineage/research visibility | Datasets date evidence query |
| `GET /api/v1/observatory/assets/crypto.BTC/trust` | `snapshot_id=null`, `channel=formal` | gate/finding/acquisition/quality evidence | Datasets quality/PIT query |
| `GET /api/v1/observatory/assets/crypto.BTC/runs` | `cursor=null`, `limit=50` (`<=500`) | ordered run summaries, next cursor and catalog fingerprint | Capture/Datasets lineage projection query |
| `GET /api/v1/observatory/runs/diff` | required `base`, `compare` | added/removed/changed dates, gate/config/code/schema changes | Datasets version/revision diff query |
| `GET /api/v1/observatory/runs/{run_id}` | run ID path | run detail, artifact refs and gates | Capture/Datasets lineage query |
| `GET /api/v1/observatory/assets/crypto.BTC/hypotheses` | no input | hypothesis ID/version/statement/state/current run | Studies hypothesis query |
| `GET /api/v1/observatory/research-runs/{research_run_id}` | research run ID path | Study snapshot/knowledge/result state/metrics/evidence refs | Studies result query |

The frozen reason mapping includes `400` invalid selector, `404` missing
snapshot/channel, `409` invalid pointer/hash/manifest/stale dataset, `422`
unproven PIT/quality/research/composite/restatement/legacy time and `503`
stale catalog. `CATALOG_STALE` carries `Retry-After`. The error payload retains
reason codes, message, evidence refs and retryability as applicable. Unknown
reason codes currently map to `400`.

The React cache is request-identity and byte bounded. A `304` without a valid
exact-identity cached body is not current truth and triggers a complete request.
The target workspace keeps this rule and never reuses stale capability
authorization.

## Web Page and BFF Matrix

| Surface | Current routes/components | Target composition | Frozen UX/DTO behavior | Forbidden |
|---|---|---|---|---|
| Today | `TodayPage`, `/api/today-page`, trust/operations regions | Datasets + Studies + Decision Support + Platform | route, page fields, partial/unavailable regions | provider call, repair or release transition |
| Observatory / BTC Workspace | four lenses, capability plus nine granular routes | Datasets + Studies, Decision Support only when a reviewed decision view is shown | capability fail-closed, `obsLens` URL/local state, immutable identity, decimal strings, ETag, deep links | bounded Context creation, direct repository/parquet/provider |
| Assurance / Data Quality | readiness/data-health/trust regions | Datasets | gate findings, quality/revision/PIT evidence and explicit unavailable | direct quality writes or scalar-only trust |
| Research | `ResearchPage`, warehouse and Observatory research routes | Studies over `DatasetSnapshotRef` | hypothesis/result/validation identity and deterministic state | moving-latest or raw artifact input |
| Symbol Workspace | K-line, state, explanation, belief, evidence, sector and data ops tabs | Datasets + Studies + Decision Support | selected symbol/date/tab, response goldens and partial tabs | arbitrary DB/parquet access |
| Signals / Candidates | `CandidatesPage`, `/api/signals-page`, explain | Studies + Decision Support | search/limit/selection and explanation DTO | creating a formal decision in a read |
| Actions | `/api/actions-page` and decision widgets | Decision Support | action/rationale/confidence compatibility view | order execution or portfolio mutation |
| Trust | `/api/trust/overview`, quality widgets | Datasets + Studies + Decision Support | component evidence and unavailable state in successor | absent input represented as trustworthy zero |
| Data Ops | assets/gaps/readiness/symbol repair | Capture + Datasets + Processes | preview/receipt/recovery links | router-owned background thread, provider/table access |
| Operations | `OpsPage`, status/events/workflows/runtime/SSE | Platform + Processes | filters, cursors, admission errors and live status | business aggregate write from GET |
| Settings | config/source/DAG UI regions | Platform Settings + Capture SourceManifest | redaction, validation and versioned source policy | direct source-registry SQL |

Every BFF declares finite parallel-query count, result/window limit, deadline,
cache/coalescing key and response byte budget. It may check permission, call
queries in parallel, map DTOs, shape responses and attach cache metadata. It
may not call a provider, repair data, publish a Dataset, execute a Study,
create/transition a DecisionCase or move a lifecycle pointer.

### BTC observation and analysis UI v1

The child redesigns the existing product surface, not the business domains.
The first viewport is a working BTC analysis surface with one truth bar and
four work views:

| View | Question | Query owners | Required evidence |
|---|---|---|---|
| Market | What did BTC do in this evidence state? | Datasets | snapshot, channel, watermarks, OHLCV/volume, return/drawdown/volatility provenance |
| Quality | Can this state be used for the selected purpose? | Datasets | acquisition, freshness, PIT, reconciliation, quarantine, revisions and reason codes |
| Research | What was tested and what remains unknown? | Studies | StudySpec, pinned SnapshotRef, sample/OOS, benchmark/placebo/walk-forward, uncertainty, stale/insufficient/EvidenceGap |
| Lineage | What changed and what depends on it? | Datasets + Studies | captures, builds, releases, revisions, affected results and projection generation |

The preferred bounded endpoint is
`GET /api/v1/observatory/assets/crypto.BTC/workspace`, or an equivalent
child-approved batch query. It returns one `BtcWorkspaceView` identity and
independent typed panel states. The BFF resolves identity once and rejects a
panel with a different SnapshotRef, knowledge cut, revision policy or
projection generation. Existing granular routes remain available and selectable
for rollback.

Validation covers disabled/error/ready capability, old/new payload goldens,
URL/local restore, decimal precision, ETag exact identity, snapshot mismatch,
partial/stale/quarantined panels, bounded fan-out, keyboard/ARIA behavior,
desktop/mobile screenshots, stable chart dimensions, no overlap and nonblank
canvas pixels.

## SDK, Notebook and Import Compatibility

| Entry | Current fact | Target contract | Validation and rollback |
|---|---|---|---|
| Observatory Python SDK | read-only BTC query seed in `trade_py.observatory.query.sdk` | versioned `interfaces/sdk` refs/query DTOs used by CLI/HTTP too | import/signature/serialization/error snapshot; preserve compatibility import |
| BTC notebook | mutates `sys.path` and can reach repository internals | installed SDK only; explicit data root/capability through public config | clean-environment run proves no path mutation, repo scan, parquet/repository/adapter import |
| CLI file/local directory import | current command-specific ingestion | `RequestCapture(mode="import")` | digest/source/policy receipt and provider-not-called replay fixture |
| Web upload/API multipart | transport-specific file handling | same Capture command and receipt | filename/content digest, size/permission/error golden |
| SDK/notebook import | may currently call internals | same Capture command | typed receipt and immutable artifact ref |

A file never becomes a formal DatasetVersion directly. Dataset builds accept
only immutable `CaptureArtifactRef`, `DatasetVersionRef` or
`DatasetSnapshotRef`.

## Scheduler and Event Compatibility

| Current entry | Frozen contract | Target | Required recovery evidence |
|---|---|---|---|
| schedules/agenda | schedule identity, next/missed fire, status and catch-up behavior | Platform Scheduling emits a command envelope | lease expiry, missed-fire/catch-up and duplicate command |
| EventBus publish | topic, event/parent identity, payload and admission refusal | Platform Events durable ingress/outbox/inbox | crash after commit, duplicate ingress, bounded payload and safe redelivery |
| event handlers/job registry | topic-to-job compatibility | thin decoder invokes Process Manager or owner command | handler crash, lease recovery, no embedded workflow |
| replay/backfill | event/root/node/date identity | Process command with immutable refs | idempotent replay, partial failure and no provider call for Capture replay |
| SSE event cursor | `after_id`, event framing and reconnect | shared projection/delivery hub | cursor expiry/resync, slow client and bounded queues |

Schedulers do not call providers or business repositories. Event handlers
decode, claim, invoke and record an outcome; they do not contain the whole
workflow. Topic/event identity remains readable through compatibility adapters
until every producer and consumer has passed mixed-version replay.

## Compatibility Test and Deletion Ledger

Before any handler switches, the child records:

1. CLI parser/help/output/exit snapshots for thirteen canonical domains and
   eight shims.
2. FastAPI route registry snapshots for default-off, enabled and enabled-error
   modes with exact counts `68/77/68`.
3. Repaired OpenAPI snapshot reconciled to the registered table, with
   `/predict` present.
4. Representative success, validation, explicit error, admission-refusal,
   capability and ETag/304 goldens for every route family.
5. Both SSE header/event/cursor/disconnect/slow-client contracts.
6. React BFF DTO and page-state goldens for every product surface.
7. SDK import/serialization/error and clean Notebook fixtures.
8. Import-to-Capture receipt and provider-free replay fixtures.
9. Schedule/event mixed-version, idempotency and recovery fixtures.
10. A mutation ledger naming old handler, new handler, selector generation,
    compatibility period, owner, rollback command and observed consumers.

A compatibility entry can be removed only when its named successor exists,
forward and rollback paths pass, usage evidence meets policy, retention/audit
requirements are satisfied, documentation has shipped, and the minimum window
has elapsed. Unknown consumers, broken OpenAPI, an incomplete route mode,
missing payload golden or an unresolved write-on-GET path blocks deletion.
