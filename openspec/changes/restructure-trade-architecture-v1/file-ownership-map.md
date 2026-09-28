# File Ownership Map

## Purpose

This attachment classifies the actual mixed legacy files audited for
`restructure-trade-architecture-v1`. It is a migration decision input, not a
move manifest. A target of `split` or `deferred` expressly prohibits moving the
file wholesale. Package shells and compatibility shims remain until their
public imports have snapshots and a retirement window.

The method is:

1. identify the file's current reads, writes, provider calls and public imports;
2. classify each behavior by semantic fact owner;
3. assign a single candidate owner only when the whole behavior is cohesive;
4. mark the file `split` when one file crosses owners;
5. mark it `deferred` when evidence cannot yet distinguish the owner;
6. require immutable input, owner-local repository, compatibility and rollback
   proof before movement; and
7. re-run import, DB-owner and read-only guards after every extraction.

No classification is based only on a directory name.

## `trade_py/analysis`

| Current file | Observed responsibility | Classification / candidate owner | Required proof before extraction |
|---|---|---|---|
| `analysis/__init__.py` | package export shell | compatibility shell | import inventory and forwarding-window snapshot |
| `analysis/crypto_validation.py` | provider-independent BTC walk-forward, placebo, bootstrap and multiple-testing validation over DataFrames | Studies | registered StudySpec, `DatasetSnapshotRef` input, deterministic environment and rerun golden |
| `analysis/devil_advocate.py` | challenged rationale and counterargument generation | Decision Support candidate | immutable Study/Dataset refs, append-only rationale, actor/audit and no execution |
| `analysis/factor_evaluation.py` | factor status and IC evaluation from moving feature files | Studies | pinned snapshot, preregistered metric/label, no path discovery |
| `analysis/factor_quantile.py` | quantile-return evaluation from Gold/K-line paths | Studies | PIT snapshot, universe/label maturity and deterministic OOS golden |
| `analysis/feature_builder.py` | technical/semantic feature definitions plus direct parquet, DB and fundamental access | **split: Datasets reusable feature product; Studies run-local transforms; adapter reads** | separate pure transforms from input ports; apply reusable-feature ownership rule; eliminate path/provider access |
| `analysis/intraday_runtime.py` | provider load, watchlist/signal SQL, factor computation and parquet/factor persistence | **split: Capture + Datasets + Decision Support query + Process** | Capture receipt, immutable intraday Dataset build, bounded process and no `db._conn` |
| `analysis/knowledge_graph.py` | reference graph, propagation calculation, `TradeDB` load and snapshot file persistence | **split/deferred: Datasets reference graph + Studies learned behavior** | row-level KG table map, immutable graph schema/lineage and Study validation |
| `analysis/label_builder.py` | future-return labels read from K-line and written to parquet | Studies by default; Dataset only if independently published | label maturity/PIT policy, fold isolation, immutable input and no moving output |
| `analysis/model_trainer.py` | time-series training and model artifact persistence from direct files | Studies | registered spec, snapshot-only input, OOS/calibration evidence and model artifact ref |
| `analysis/multi_persona.py` | multi-perspective decision debate | Decision Support candidate | immutable inputs, bounded model provenance, rationale/audit and unavailable state |
| `analysis/patience_tracker.py` | mutable follow-up JSON plus direct K-line inspection | **split/deferred: Decision Support follow-up + Dataset query** | DecisionCase/expiry mapping, append-only transition and no direct parquet |
| `analysis/propagation_runtime.py` | compatibility re-export across factors/materialization/inference persistence | compatibility shell over split owners | caller/import inventory; extracted Datasets/Studies/Decision Support APIs |
| `analysis/propagation_training.py` | model fitting, temporal split, evaluation, promotion and direct DB/file artifacts | Studies | StudySpec, immutable snapshots, OOS/label maturity, promotion receipt and artifact port |
| `analysis/sentiment_ic.py` | sentiment-return IC/decay evaluation from moving files | Studies | PIT source/label snapshots, preregistered horizons and deterministic rerun |

## `trade_py/evaluation`

| Current file | Observed responsibility | Classification / candidate owner | Required proof before extraction |
|---|---|---|---|
| `evaluation/__init__.py` | public evaluation exports | compatibility shell | import inventory and forwarding-window snapshot |
| `evaluation/events.py` | event prediction evaluation and mutable evaluation records | Studies | `DatasetSnapshotRef`, matured labels, OOS metrics and owner-local result repository |
| `evaluation/gate.py` | combines source quality, model/research outcomes and writes gate state | **split: Datasets release quality + Studies validation** | separate Dataset quality disposition from Study conclusions and Process sequencing |
| `evaluation/models.py` | loads model/features, creates snapshot-like metadata and writes model evaluations | Studies | formal Dataset snapshot, model/spec identity, OOS/calibration and deterministic rerun |
| `evaluation/service.py` | catch-all daily orchestration, caching, snapshot/gate writes and partial handling | **split: Processes + Datasets + Studies** | replace with explicit commands/events/process steps; one transaction owner per step |
| `evaluation/sources.py` | direct Bronze/Silver/ingest reads and source health writes | Datasets quality, with Capture receipt inputs | immutable Capture/Dataset refs, owner-local quality policy and no pipeline DB scan |
| `evaluation/trust.py` | freshness/evidence/model/ops/recommendation metrics, source updates and QualityReport write | **split/deferred: Datasets + Studies + Decision Support + Platform** | component-by-component authority; explicit unavailable values; no scalar fallback or cross-owner SQL |
| `evaluation/utils.py` | cached outcome reads, file/DB watermarks, fingerprints and metric helpers | **split** | move pure metric functions to their owner; replace global cache/path/DB helpers with ports |

## `trade_py/evidence`

The legacy name does not authorize a top-level Evidence Context.

| Current file | Observed responsibility | Classification / candidate owner | Required proof before extraction |
|---|---|---|---|
| `evidence/__init__.py` | package export shell | compatibility shell | import inventory and forwarding-window snapshot |
| `evidence/ingest.py` | batch/stream ingestion facade | Capture candidate | SourceManifest, request/run/artifact/checkpoint and provider-free replay |
| `evidence/enrich.py` | semantic enrichment command | Datasets derived product unless proven run-local | model/prompt/parser/environment lineage and immutable input refs |
| `evidence/aggregate.py` | reusable aggregation/materialization command | Datasets derived product unless proven run-local | schema/identity/unit/time policy, lineage and release contract |
| `evidence/quality.py` | smoothing reads and rewrites Gold parquet in place | Datasets, but current behavior is migration-blocked | immutable derived version instead of in-place rewrite, quality/derivation receipt and rollback |

## `trade_py/factors`

| Current file | Observed responsibility | Classification / candidate owner | Required proof before extraction |
|---|---|---|---|
| `factors/__init__.py` | public factor exports | compatibility shell | import inventory and forwarding-window snapshot |
| `factors/definitions.py` | reusable feature names/default metadata | Datasets candidate when published | versioned schema/units/lineage and independent consumers |
| `factors/encoder.py` | categorical transform plus mutable map files | **split: Datasets published transform or Studies fold-local encoder** | training-fold isolation; immutable map artifact if published |
| `factors/groups/__init__.py` | factor-group exports | compatibility shell | import inventory and forwarding-window snapshot |
| `factors/groups/_base.py` | DataFrame result carrier/default fill behavior | owner-local type, not Kernel | prove Dataset publication or Study-local use; do not expose DataFrame cross-Context |
| `factors/groups/crypto_features.py` | direct crypto/news path fallback and reusable feature calculation | Datasets candidate | immutable input refs, no fallback path scan, schema/lineage and release |
| `factors/groups/event_features.py` | direct event SQL and feature/label construction | **split: Datasets reusable feature + Studies label/local transform** | owner query ports, PIT/label maturity and feature ownership decision |
| `factors/groups/instrument_features.py` | direct instrument/signal SQL and reusable features | **split: Datasets reference/features + Decision Support signal input** | replace raw connection, immutable refs and no decision table read in Dataset build |
| `factors/groups/sentiment_features.py` | direct Gold parquet scan and sentiment features | Datasets candidate | versioned semantic input/output, lineage and no moving glob |
| `factors/groups/technical_features.py` | direct K-line scan and technical features | Datasets candidate | immutable OHLCV input, schema/unit/version and Python/native differential test |
| `factors/inference_bridge.py` | reads/writes signals through `TradeDB` and `db._conn` | **split: Study result projection + Decision Support compatibility view** | immutable StudyResultRef, one projection writer and removal of connection penetration |
| `factors/materializer.py` | global DB reads, group composition and mutable factor materialization | **split/deferred: Datasets + Studies + Decision Support inputs** | source-by-source owner ports, reusable/local classification and immutable build inputs |
| `factors/registry.py` | factor metadata plus DB-backed trust weights | **split: Datasets schema registry + Studies validation metadata** | one authoritative metadata fact per row and no shared mutable registry |
| `factors/technical.py` | direct K-line load and reusable transform | Datasets candidate | immutable Dataset input, versioned transform and no path discovery |
| `factors/trust_update.py` | factor IC validation and direct registry trust mutation | **split: Studies validation + Datasets metadata projection** | StudyResult/PromotionReceipt, projection-only update and no direct DDL/SQL |

## `trade_py/intelligence`

| Current file | Observed responsibility | Classification / candidate owner | Required proof before extraction |
|---|---|---|---|
| `intelligence/__init__.py` | package exports | compatibility shell | import inventory and forwarding-window snapshot |
| `intelligence/base_factors.py` | deterministic article semantic derivation | Datasets derived product candidate | model/parser/policy identity, immutable input and output schema |
| `intelligence/crypto_base_factors.py` | deterministic crypto news semantic derivation | Datasets derived product candidate | source precision, model/parser/policy lineage and immutable output |
| `intelligence/enricher.py` | text-to-symbol/sector derivation with direct DB reference lookup | Datasets derived product | versioned reference Dataset, derivation receipt and no raw DB path |
| `intelligence/feed_score.py` | feed-score data type and calculation input | **deferred owner-local type** | distinguish Capture operational score, Dataset quality and Study evaluation |
| `intelligence/feed_scorer.py` | source scoring, reliability mutation and InfluenceSignal persistence | **split/deferred: Capture + Datasets + Studies** | separate transport health, quality product and validated research score; preserve all clocks |
| `intelligence/meta_store.py` | global SQLite wrapper, schema bootstrap and implicit DuckDB migration for mixed tables | **split/deferred; no replacement global facade** | table-by-table ownership, explicit governed migration, restore and writer reconciliation |
| `intelligence/nlp_train.py` | model training from direct Bronze/Silver paths and ONNX output | Studies | registered StudySpec, SnapshotRefs, OOS evaluation and immutable model artifact |
| `intelligence/raw_record.py` | raw record DTO with collapsed publication clock | Capture contract candidate after redesign | independent provider/event/observed/received/available/revision clocks and rights |
| `intelligence/schema.py` | DDL for mixed `feed_scores` and `source_configs` | **split/deferred** | owner-local migrations after both tables are classified |
| `intelligence/clients/__init__.py` | LLM provider factory | Capture adapter shell | SourceManifest capability and adapter contract; no business semantics |
| `intelligence/clients/base.py` | provider response parsing plus sentiment result type | **split: Capture transport + Datasets semantic parser** | raw receipt before parsing; parser/model version and typed failure separation |
| `intelligence/clients/anthropic.py` | Anthropic network adapter | Capture adapter | quota, timeout, circuit, rights and provider-free replay receipt |
| `intelligence/clients/ollama.py` | Ollama network adapter | Capture adapter | timeout/process isolation, request/response receipt and replay |
| `intelligence/graph/__init__.py` | graph exports | compatibility shell | import inventory and forwarding-window snapshot |
| `intelligence/graph/builder.py` | builds a reference graph JSON artifact | Datasets candidate | immutable input, schema/lineage and versioned graph Dataset |
| `intelligence/graph/learned.py` | direct DB/path reads, feature/label building, model fit and candidate generation | **split: Studies + Datasets inputs + Decision Support review output** | SnapshotRefs, OOS validation, immutable candidate result and reviewed promotion path |

## `trade_py/observatory`

Observatory remains a product surface and compatibility namespace, not a
bounded Context.

| Current file | Observed responsibility | Classification / candidate owner | Required proof before extraction |
|---|---|---|---|
| `observatory/__init__.py` | package shell | compatibility shell | import inventory and forwarding-window snapshot |
| `observatory/catalog/__init__.py` | catalog exports | compatibility shell | import inventory and forwarding-window snapshot |
| `observatory/catalog/legacy_time.py` | derives proxy times from legacy manifests | Datasets compatibility adapter | formal clock contract, precision/provenance and fail-closed PIT |
| `observatory/catalog/projection.py` | rebuilds runs/releases/artifact refs from manifests and pointers | Datasets projection | immutable source refs, bounded rebuild and generation receipt |
| `observatory/catalog/store.py` | writes/reads catalog SQLite and generation pointer; readiness scans live files | Datasets projection adapter | bounded indexed read, atomic generation activation, scrub/recovery and no second authority |
| `observatory/domain/__init__.py` | mixed DTO exports | compatibility shell | type-by-type owner map and serialization snapshots |
| `observatory/domain/models.py` | Artifact/Run/Release/Snapshot/Research and display models mixed in one module | **split: Datasets contracts + Studies contracts + Interface DTOs** | no internal aggregate leakage; immutable refs and exact compatibility mapping |
| `observatory/domain/state_mapping.py` | maps manifest/provider facts to quality/lifecycle/display states | **split: Datasets state + Interface presentation mapping** | owner state machine precedes DTO mapping; no UI-derived authority |
| `observatory/domain/vocab.py` | mixed acquisition, quality, research, availability and render vocabulary | **split into owner contracts; compatibility aliases remain** | semantic owner and versioned serialization for each enum |
| `observatory/pit/__init__.py` | PIT exports | compatibility shell | import inventory and forwarding-window snapshot |
| `observatory/pit/coverage.py` | temporal evidence coverage and PIT eligibility | Datasets | formal temporal/revision spec, immutable lineage and goldens |
| `observatory/pit/resolver.py` | PIT filtering with current missing-clock/restatement gaps | Datasets | `formal-pit-and-revision-semantics` strict approval and implementation evidence |
| `observatory/query/__init__.py` | query exports | compatibility shell | import inventory and forwarding-window snapshot |
| `observatory/query/diff.py` | direct artifact run diff | Interfaces query over Datasets | bounded Dataset diff query, hash verification and no path reads |
| `observatory/query/facade.py` | serializes and composes resolver, PIT, artifact and Study reads | Interfaces BFF/query compatibility | owner query handles, one snapshot identity, bounded fan-out and DTO goldens |
| `observatory/query/sdk.py` | current read-only Python SDK around internal resolver | Interfaces SDK compatibility | stable public contracts, no internal repository/path import and notebook tests |
| `observatory/research/__init__.py` | research exports | compatibility shell | import inventory and forwarding-window snapshot |
| `observatory/research/adapter.py` | reads current H1 validation/research artifacts | Studies compatibility adapter | StudyResultRef and DatasetSnapshotRef mapping; no moving pointer input |
| `observatory/research/workflow.py` | run/import/promote plus direct exploratory receipt files | **split: Capture import + Studies run/promotion + Process sequencing** | import Capture receipt, clean rerun, Study repository and owner-local transactions |
| `observatory/service/__init__.py` | service exports | compatibility shell | import inventory and forwarding-window snapshot |
| `observatory/service/artifacts.py` | verifies/reads canonical and auxiliary run parquet | Datasets adapter | all artifacts hash/manifest bound, immutable refs and bounded read port |
| `observatory/service/identity.py` | computes snapshot/view/ETag fingerprints | **split: Dataset ref identity + Interface view identity** | canonical digest schema for each owner; no broad Kernel promotion |
| `observatory/service/purpose_fitness.py` | maps quality/coverage to allowed purposes | Datasets | versioned eligibility policy and explicit unavailable/reason states |
| `observatory/service/resolver.py` | selects releases/runs, reads artifacts and shapes layered comparisons | **split: Datasets resolution + Interfaces render composition** | owner query split, formal PIT/revision proof and one immutable identity |

## Boundary Entry Points Outside the Six Mixed Directories

| Current path or family | Current role | Target disposition |
|---|---|---|
| `trade_py/db/trade_db.py`, CRUD mixins and `migrations.py` | global schema/repository/migration facade | retain compatibility; extract table by table to owner repositories; Platform provides primitives only |
| `trade_py/db/pipeline_db.py` | Capture/run/coverage/enrichment mix | split by table ledger; no whole-file move |
| `trade_py/bus/*` | admission, event records, scheduler and handlers | Platform Events/Scheduling mechanics; business handlers move to Context use cases/Processes |
| `trade_py/jobs/__init__.py` | job registry and cross-domain execution | split into owner use cases and Process commands; Platform owns generic execution only |
| `trade_py/cli/*.py` | stable commands plus direct orchestration/SQL/provider behavior | `interfaces/cli/compat`; delegate one command/query at a time and preserve snapshots |
| `trade_py/data/market/crypto/providers.py`, `akshare.py`, provider parts of `service.py` | BTC provider interaction | Capture adapters and use cases |
| `trade_py/data/market/crypto/store.py`, canonical/assurance parts of `service.py` | raw and canonical artifacts, manifests, release pointer | split Capture raw receipt from Datasets build/release compatibility |
| `trade_py/data/warehouse/*` | acquisition, canonicalization, materialization, reports and pointers | split Capture interaction from Datasets products and Studies-only outputs using producer ledger |
| `trade_web/backend/app.py` | application composition, routers, direct DB/parquet and commands | split Interfaces compatibility/BFF from Bootstrap; no business ownership |
| `trade_web/backend/runtime/*` | runtime queries, command child, startup autofill and resource lifecycle | split Interfaces/Platform/Processes; Bootstrap becomes single shutdown owner |
| `trade_web/backend/observatory/*` | capability gate and BTC product router | Interfaces HTTP/BFF compatibility |
| `trade_web/frontend/src/pages/*` | product surfaces | remain under `web/`; consume versioned BFF/contracts, never become Contexts |
| `engine/*` | C++ calculation implementation | Context-specific native adapters behind ports; future module name `_trade_native` |

## Migration Block

A child may move or copy behavior only when its proposal lists:

- the exact source declarations and callers;
- the target aggregate/use case/port/adapter;
- old and new writer ownership;
- public import/CLI/HTTP/data compatibility;
- immutable reference and time semantics;
- focused unit/contract/golden/integration tests;
- cutover receipt and rollback selector; and
- deletion/retention evidence for the old path.

Until then, these paths remain in place. Directory cleanup is the last
consequence of proven ownership, never the first migration step.
