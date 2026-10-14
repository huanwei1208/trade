# Table and Artifact Ownership

## Status and Authority

This ledger is a design attachment for `restructure-trade-architecture-v1`.
It was derived from the code-proven records in the repository-root
`architecture-baseline.toml`; it does not replace that machine-readable
baseline and does not authorize a production migration.

The baseline contains 56 logical tables: 31 `candidate` classifications and
25 `deferred` classifications. It also contains eight artifact families: six
`candidate` and two `deferred`. A candidate target is a hypothesis that the
named child change must prove through schema, writer, reader, transaction,
lineage, dual-read, restore and rollback evidence. Every deferred row is
**MIGRATION BLOCKED** until its named child performs row/field-level audit and
updates this ledger through a newly reviewed OpenSpec change.

The legacy baseline name `process-manager-and-platform-boundary` maps to two
target children:

- `platform-persistence-events-and-bootstrap-foundation` owns generic
  persistence, events, execution, scheduling, settings, backup and migration
  mechanics.
- `process-manager-boundary` owns business process state such as agenda and
  recovery workflows.

The split is explicit here because the original baseline predates the final
acyclic child graph. It does not mutate or silently reinterpret the baseline.

## Ownership Rules

1. A logical table or artifact family has one authoritative target writer.
2. Readers in another Context use contracts, immutable refs, events or a
   rebuildable projection; they do not query the owner table directly.
3. Each command commits only owner-local aggregate state, audit and outbox.
   Cross-Context work never shares a transaction.
4. Physical SQLite co-location may remain during migration, but repository and
   migration ownership are still exclusive.
5. Compatibility readers may remain during the declared window. They cannot
   become a second writer or source of truth.
6. `deferred` means preserve in place. It is not an invitation to choose the
   nearest-looking Context during implementation.

## Logical Table Ledger

`Readers` names the allowed target reader class, not every current call site.
`Writers` identifies the only future semantic writer. Legacy writers remain in
place until the owning child completes shadow/dual-read/cutover evidence.

| Table | Current owner | Classification / target Context | Target repository | Readers | Writers | Transaction boundary | Migration owner |
|---|---|---|---|---|---|---|---|
| `event_log` | `trade_py.db` | candidate / Platform Events | `EventLogRepository` | Processes and Interfaces through event/status APIs | Platform Events compatibility bridge | append/admission/delivery audit | `platform-persistence-events-and-bootstrap-foundation` |
| `event_handler_runs` | `trade_py.db` | candidate / Platform Events | `DeliveryStateRepository` | Platform dispatch/status APIs | Platform Events dispatcher | inbox claim, attempt, ack or DLQ | `platform-persistence-events-and-bootstrap-foundation` |
| `pipeline_dag` | `trade_py.db` | **deferred / MIGRATION BLOCKED** | unassigned; split scheduling mechanics from business process definitions | legacy callers only until classification | legacy writer only | unchanged legacy transaction | joint audit by Platform and Processes children |
| `asset_registry` | `trade_py.db` | candidate / Capture | `SourceManifestRepository` | Capture use cases; Processes and Interfaces through contracts | Capture | manifest version, rights policy, audit and outbox | `capture-boundary` |
| `feed_scores` | `trade_py.intelligence` | **deferred / MIGRATION BLOCKED** | unassigned; source metadata, Dataset quality and Study scoring are mixed | legacy callers only until classification | legacy writer only | unchanged independent metadata-store transaction | `capture-boundary`, with Dataset/Study consultation |
| `source_configs` | `trade_py.intelligence` | candidate / Capture | `SourceManifestRepository` | Capture use cases; Interfaces through source queries | Capture | manifest/config version, audit and outbox | `capture-boundary` |
| `catalog_meta` | `trade_py.observatory.catalog` | candidate / Datasets | `CatalogProjectionRepository` | Interfaces and Studies through bounded Dataset queries | Datasets projection use case | projection generation/CAS | `dataset-product-boundary` |
| `catalog_runs` | `trade_py.observatory.catalog` | candidate / Datasets | `CatalogProjectionRepository` | Interfaces and Studies through bounded Dataset queries | Datasets projection use case | projection generation/CAS | `dataset-product-boundary` |
| `catalog_releases` | `trade_py.observatory.catalog` | candidate / Datasets | `CatalogProjectionRepository` | Interfaces and Studies through bounded Dataset queries | Datasets projection use case | projection generation/CAS | `dataset-product-boundary` |
| `ingest_runs` | `trade_py.db.pipeline_db` | candidate / Capture | `CaptureRunRepository` | Processes and operations queries through Capture contracts | Capture | run transition, receipt and outbox | `capture-boundary` |
| `coverage` | `trade_py.db.pipeline_db` | candidate / Capture | `CaptureCheckpointRepository` | Capture planners; Processes/Interfaces through contracts | Capture | checkpoint compare-and-set and receipt | `capture-boundary` |
| `enrichment_status` | `trade_py.db.pipeline_db` | **deferred / MIGRATION BLOCKED** | unassigned; reusable Dataset derivation versus Study-local cache unresolved | legacy callers only until classification | legacy writer only | unchanged legacy transaction | `study-boundary`, with Datasets classification |
| `source_health_daily` | `trade_py.db` | candidate / Datasets | `QualityRepository` | Studies eligibility and Interfaces through Dataset queries | Datasets | quality finding/build decision and outbox | `dataset-product-boundary` |
| `source_eval_daily` | `trade_py.db` | candidate / Datasets | `QualityRepository` | Studies eligibility and Interfaces through Dataset queries | Datasets | quality finding/build decision and outbox | `dataset-product-boundary` |
| `event_eval_runs` | `trade_py.db` | candidate / Studies | `StudyRepository` | Decision Support and Interfaces through Study contracts | Studies | StudyRun validation/result and outbox | `study-boundary` |
| `dataset_snapshots` | `trade_py.db` | candidate / Datasets | `SnapshotRepository` | Studies, Decision Support and Interfaces by `DatasetSnapshotRef` | Datasets | immutable membership/digest publication | `dataset-product-boundary` |
| `daily_quality_gate` | `trade_py.db` | candidate / Datasets | `QualityRepository` | release policy and Interfaces through Dataset queries | Datasets | quality disposition and release eligibility | `dataset-product-boundary` |
| `event_templates` | `trade_py.db` | **deferred / MIGRATION BLOCKED** | unassigned; Dataset schema versus Study-local transform unresolved | legacy callers only until classification | legacy writer only | unchanged legacy transaction | `dataset-product-boundary`, with Studies consultation |
| `market_events` | `trade_py.db` | **deferred / MIGRATION BLOCKED** | unassigned; Capture, canonical Dataset and decision inputs are mixed | legacy callers only until classification | legacy writer only | unchanged legacy transaction | `dataset-product-boundary`, preceded by Capture audit |
| `event_propagations` | `trade_py.db` | **deferred / MIGRATION BLOCKED** | unassigned; graph derivation, realized labels and Study features are mixed | legacy callers only until classification | legacy writer only | unchanged legacy transaction | `dataset-product-boundary`, with Studies consultation |
| `causal_decision_snapshots` | `trade_py.db` | **deferred / MIGRATION BLOCKED** | unassigned; Dataset, Study and DecisionCase facts must be separated | legacy callers only until classification | legacy writer only | unchanged legacy transaction | `study-boundary` then `decision-support-boundary` |
| `causal_validation_outcomes` | `trade_py.db` | **deferred / MIGRATION BLOCKED** | unassigned pending formal Study validation lineage | legacy callers only until classification | legacy writer only | unchanged legacy transaction | `study-boundary` |
| `causal_reward_punishment` | `trade_py.db` | **deferred / MIGRATION BLOCKED** | unassigned; Study validation and Decision Support audit are mixed | legacy callers only until classification | legacy writer only | unchanged legacy transaction | `study-boundary` then `decision-support-boundary` |
| `factors` | `trade_py.db` | **deferred / MIGRATION BLOCKED** | unassigned; derived Dataset versus Study-local feature unresolved | legacy callers only until classification | legacy writer only | unchanged legacy transaction | `study-boundary`, with Datasets feature-rule proof |
| `factor_registry` | `trade_py.db` | **deferred / MIGRATION BLOCKED** | unassigned; published Dataset metadata versus Study registry unresolved | legacy callers only until classification | legacy writer only | unchanged legacy transaction | `study-boundary`, with Datasets feature-rule proof |
| `kg_nodes` | `trade_py.db` | **deferred / MIGRATION BLOCKED** | unassigned; reference Dataset and learned Study graph facts are mixed | legacy callers only until classification | legacy writer only | unchanged legacy transaction | `study-boundary`, with Datasets classification |
| `kg_relations` | `trade_py.db` | **deferred / MIGRATION BLOCKED** | unassigned; reference edges, learned weights and review state are mixed | legacy callers only until classification | legacy writer only | unchanged legacy transaction | `study-boundary`, with Datasets/Decision Support classification |
| `kg_edge_candidates` | `trade_py.db` | **deferred / MIGRATION BLOCKED** | unassigned; Study evidence and Decision Support review must be separated | legacy callers only until classification | legacy writer only | unchanged legacy transaction | `study-boundary` then `decision-support-boundary` |
| `model_registry` | `trade_py.db` | **deferred / MIGRATION BLOCKED** | unassigned pending StudySpec, immutable input and promotion proof | legacy callers only until classification | legacy writer only | unchanged legacy transaction | `study-boundary` |
| `model_eval_runs` | `trade_py.db` | **deferred / MIGRATION BLOCKED** | unassigned pending formal PIT/OOS validation proof | legacy callers only until classification | legacy writer only | unchanged legacy transaction | `study-boundary` |
| `ArticleEvent` | `trade_py.db` | candidate / Datasets | `DatasetRepository` | Studies and Interfaces by immutable Dataset refs/queries | Datasets | build/version/lineage/quality and outbox | `dataset-product-boundary` |
| `InfluenceSignal` | `trade_py.db` | **deferred / MIGRATION BLOCKED** | unassigned; source reliability, Dataset derivation and Study score are mixed | legacy callers only until classification | legacy writer only | unchanged legacy transaction | `study-boundary`, after Capture/Datasets audit |
| `Evidence` | `trade_py.db` | **deferred / MIGRATION BLOCKED** | unassigned; no independent Evidence Context is permitted | legacy callers only until classification | legacy writer only | unchanged legacy transaction | `study-boundary`, with Datasets/Decision Support classification |
| `BeliefState` | `trade_py.db` | **deferred / MIGRATION BLOCKED** | unassigned pending DecisionCase and Study-result provenance | legacy callers only until classification | legacy writer only | unchanged legacy transaction | `decision-support-boundary` |
| `AttentionScore` | `trade_py.db` | **deferred / MIGRATION BLOCKED** | unassigned pending DecisionCase and Study-result provenance | legacy callers only until classification | legacy writer only | unchanged legacy transaction | `decision-support-boundary` |
| `BeliefTransition` | `trade_py.db` | **deferred / MIGRATION BLOCKED** | unassigned pending DecisionCase transition and audit proof | legacy callers only until classification | legacy writer only | unchanged legacy transaction | `decision-support-boundary` |
| `QualityReport` | `trade_py.db` | candidate / Datasets | `QualityRepository` | Studies eligibility and Interfaces through Dataset queries | Datasets | report/finding/build disposition | `dataset-product-boundary` |
| `FreshnessStatus` | `trade_py.db` | candidate / Datasets | `QualityRepository` | Studies eligibility and Interfaces through Dataset queries | Datasets | availability projection generation | `dataset-product-boundary` |
| `Recommendation` | `trade_py.db` | **deferred / MIGRATION BLOCKED** | unassigned pending DecisionCase/audit and compatibility row mapping | legacy callers only until classification | legacy writer only | unchanged legacy transaction | `decision-support-boundary` |
| `RecommendationTrace` | `trade_py.db` | **deferred / MIGRATION BLOCKED** | unassigned pending rationale/audit lineage mapping | legacy callers only until classification | legacy writer only | unchanged legacy transaction | `decision-support-boundary` |
| `settings` | `trade_py.db` | candidate / Platform Settings | `SettingsRepository` | Bootstrap, Capture configuration and Interfaces through settings API | Platform Settings | setting version/CAS and audit | `platform-persistence-events-and-bootstrap-foundation` |
| `watchlist` | `trade_py.db` | candidate / Decision Support | `DecisionRepository` | Interfaces through Decision Support queries | Decision Support | case/watch transition and audit/outbox | `decision-support-boundary` |
| `signals` | `trade_py.db` | candidate / Decision Support compatibility projection | `DecisionProjectionRepository` | Interfaces; formal source remains Dataset/Study refs | Decision Support projection use case | projection generation with immutable evidence refs | `decision-support-boundary` |
| `job_runs` | `trade_py.db` | candidate / Platform Execution | `ExecutionRunRepository` | Processes and Operations status APIs | Platform Execution | execution attempt/terminal receipt | `platform-persistence-events-and-bootstrap-foundation` |
| `instruments` | `trade_py.db` | candidate / Datasets | `DatasetRepository` | Capture planning, Studies, Decision Support and Interfaces through contracts | Datasets | reference Dataset build/version/release | `dataset-product-boundary` |
| `sector_members` | `trade_py.db` | candidate / Datasets | `DatasetRepository` | Studies, Decision Support and Interfaces through contracts | Datasets | reference Dataset build/version/release | `dataset-product-boundary` |
| `sync_state` | `trade_py.db` | candidate / Capture | `CaptureCheckpointRepository` | Capture planner; Processes/Interfaces through contracts | Capture | checkpoint CAS/run receipt | `capture-boundary` |
| `trading_calendar` | `trade_py.db` | candidate / Datasets | `DatasetRepository` | Scheduling via Dataset query contract; Studies/Interfaces | Datasets | reference Dataset build/version/release | `dataset-product-boundary` |
| `planned_events` | `trade_py.db` | candidate / Datasets | `DatasetRepository` | Scheduling, Studies and Interfaces through Dataset contracts | Datasets | reference Dataset build/version/release | `dataset-product-boundary` |
| `agenda_queue` | `trade_py.db` | candidate / Processes | `ProcessRepository` | Interfaces through `ProcessView`; Platform executes commands only | Processes | idempotency claim/process step/compensation | `process-manager-boundary` |
| `backup_snapshots` | `trade_py.db` | candidate / Platform Backup | `BackupReceiptRepository` | Operations and restore APIs | Platform Backup | backup manifest/digest or restore receipt | `platform-persistence-events-and-bootstrap-foundation` |
| `ui_snapshots` | `trade_py.db` | candidate / Interfaces projection | `BffViewRepository` | Interfaces only | Interfaces projection adapter | replaceable view generation/CAS | `cli-http-sdk-compatibility` |
| `readiness_recovery_actions` | `trade_py.db` | candidate / Processes | `ProcessRepository` | Interfaces through `ProcessView` and recovery query | Processes | recovery claim/step/terminal or compensation | `process-manager-boundary` |
| `schema_migrations` | `trade_py.db` | candidate / Platform Persistence | `MigrationLedgerRepository` | Bootstrap/migration status API | Platform migration runner | migration lease/checkpoint/terminal receipt | `platform-persistence-events-and-bootstrap-foundation` |
| `signal_cache_v2` | `trade_py.db` | **deferred / MIGRATION BLOCKED** | unassigned; historical Study/Decision provenance unresolved | legacy callers only until classification | legacy writer only | unchanged legacy transaction | `decision-support-boundary`, with Studies audit |
| `bus_events` | `trade_py.db` | **deferred / MIGRATION BLOCKED** | unassigned; historical create/drop lifecycle needs runtime reconciliation | legacy forensic readers only | no new target writer until reconciliation | unchanged historical state | `platform-persistence-events-and-bootstrap-foundation` |

## Artifact Ledger

| Artifact family | Current owner | Classification / target Context | Target repository/store | Readers | Writers | Transaction / visibility boundary | Migration owner |
|---|---|---|---|---|---|---|---|
| `warehouse-parquet` | `trade_py.data.warehouse` | candidate / Datasets | `DatasetArtifactStore` | Studies, Decision Support and Interfaces only by immutable ref/query | Datasets | stage, digest, manifest, version commit and release event | `dataset-product-boundary` |
| `catalog-sqlite-projection` | `trade_py.observatory.catalog` | candidate / Datasets | `CatalogProjectionStore` | Interfaces and bounded Dataset queries | Datasets projection use case | build generation, verify, atomic activate/CAS | `dataset-product-boundary` |
| `catalog-generation-pointer` | `trade_py.observatory.catalog` | candidate / Datasets | `CatalogProjectionStore` | Interfaces and recovery/status queries | Datasets projection use case | pointer journal plus projection generation CAS | `dataset-product-boundary` |
| `crypto-ads-current-pointer` | `trade_py.data.warehouse.crypto_store` | candidate / Datasets compatibility pointer | `ReleaseRepository` compatibility adapter | legacy readers during compatibility window | Datasets only after cutover | verified release generation and pointer journal | `dataset-product-boundary` |
| `crypto-ads-validation-receipt` | `trade_py.data.warehouse.crypto_store` | candidate / Datasets | `DatasetArtifactStore` / `QualityRepository` | Datasets, Studies eligibility and Interfaces by ref | Datasets | immutable validation receipt committed before release | `dataset-product-boundary` |
| `btc-compatibility-pointer` | `trade_py.data.market.crypto` | candidate / Datasets compatibility pointer | `ReleaseRepository` compatibility adapter | current BTC CLI/Web readers during window | Datasets only after cutover | verified release generation and pointer journal | `dataset-product-boundary` |
| `kline-reconciliation-operation-pointer` | `trade_py.data.operations` | **deferred / MIGRATION BLOCKED** | unassigned; must not become Dataset authority | legacy Data Ops reader only | legacy writer only | unchanged pointer behavior | `dataset-product-boundary` |
| `kline-reconciliation-pointer` | `trade_py.utils.data_inspector` | **deferred / MIGRATION BLOCKED** | unassigned; global inspection and reconciliation are coupled | legacy inspector only | legacy writer only | unchanged pointer behavior | `dataset-product-boundary` |

## New Target Families

The desired table names below are logical contracts, not pre-approved physical
DDL. Their exact schema and storage are selected only in the owning child.

| Target family | Exclusive owner | Repository/store | Allowed cross-Context access |
|---|---|---|---|
| source manifests, capture requests/plans/runs/groups/checkpoints/artifact receipts | Capture | `SourceManifestRepository`, `CaptureRepository`, `CaptureCheckpointRepository`, `ArtifactStore` | `capture.contracts` immutable refs, commands, events and queries |
| dataset definitions/builds/versions/releases/snapshots/quality/lineage/quarantine | Datasets | `DatasetRepository`, `ReleaseRepository`, `SnapshotRepository`, `QualityRepository` | `datasets.contracts` refs, events and bounded queries |
| studies/hypotheses/specs/runs/results/validation/promotion/evidence gaps | Studies | `StudyRepository`, `StudyArtifactStore` | `studies.contracts` refs, events and bounded queries |
| decision cases/reviews/rationales/overrides/intents/expiry/audit | Decision Support | `DecisionRepository` | `decision_support.contracts` refs, events and bounded queries |
| outbox/inbox/delivery/lease/DLQ | Platform Events | Platform event stores | Platform public APIs and event envelopes |
| execution receipts | Platform Execution | `ExecutionRunRepository` | Platform public status/query APIs |
| schedules and generic fire leases | Platform Scheduling | `ScheduleRepository` | command envelope only |
| cross-Context process instances and steps | Processes | `ProcessRepository` | `ProcessView`, command/event contracts |

## Child Exit Evidence

No ownership row becomes effective until the owning child proves:

1. complete current reader/writer inventory and dynamic-SQL reconciliation;
2. additive schema or immutable artifact versioning;
3. old-reader compatibility plus new-writer exclusivity;
4. idempotent shadow/backfill and dual-read digest comparison;
5. owner-local transaction and outbox, with no cross-Context transaction;
6. temporary-root crash/restart and corrupt-predecessor fixtures;
7. backup/hash verification and restore rehearsal for durable state;
8. cutover and rollback receipts;
9. retention/lineage reachability before any deletion; and
10. a reviewed update that replaces every relevant `deferred` classification
    with a proven target or an explicit preserve/delete disposition.
