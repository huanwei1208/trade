# 22 Plan - Analysis-First Research System

## Goal

Re-center TradeDB from a recommendation-first decision workspace into an
analysis-first research system for:

- Crypto
- AI
- Banks

The system should help a user discover information, explore market structure,
test hypotheses, validate signals, and monitor existing position risk. It should
not automatically trade, rebalance, or issue mandatory buy/sell instructions.

Chinese summary:

> 以分析为核心的市场研究系统，先覆盖 Crypto、AI、Banks 三个方向；分析结果必须可解释、可探索、可验证；已有仓位只做风险监控和人工决策辅助。

## Direction Change

Existing Today / Candidates / Symbol / Ops, recommendation, belief, KG, quality
gate, readiness, and recovery capabilities remain valuable infrastructure. They
are no longer the primary product direction.

The primary product direction is now:

```text
source catalog
-> ODS / DWD / DWS / ADS warehouse
-> EDA and statistical signals
-> hypothesis generation
-> validation
-> explanation / attribution
-> position-risk awareness
```

Recommendation may remain as a downstream view or historical artifact, but new
work should not optimize the project around making recommendation the central
object.

## Non-Goals

- No automatic trading.
- No forced buy/sell recommendations.
- No automatic rebalancing.
- No dependency on LLMs, paid APIs, online Google Sheets, or external network for
  tests.
- No large-scale rewrite of existing architecture.
- No removal of Today / Candidates / Symbol / Ops.
- No breakage of CLI, Web, evaluation, readiness, or warehouse tests.
- No complex asset allocation engine in the first version.

## Current Assets To Preserve

### Existing Operating Surface

The earlier EBRT work produced a useful operational base:

- Web shell with Today / Candidates / Symbol / Ops.
- Readiness grid, recovery actions, replay plans, and workflow audit.
- Quality gate and trust reporting.
- Event extraction, KG propagation, belief, recommendation, and validation
  records.

These should be preserved as supporting surfaces. Ops remains the place to
inspect data quality, workflow state, and recovery. Today / Candidates / Symbol
remain available, but should not drive the next architecture decisions.

### Existing Research Warehouse Seed

The current `trade_py.data.warehouse` package already provides the first
file-backed analysis loop:

- `dim.dim_data_source`
- `ods.ods_rss_entry_raw`
- `dwd.dwd_article`
- `dwd.dwd_article_quality_check`
- `dwd.dwd_article_semantic_check`
- `dwd.dwd_article_sector_relevance`
- `dws.dws_sector_topic_daily`
- `ads.ads_data_signal_report`
- `ads.ads_source_value_report`
- `ads.ads_warehouse_validation_report`

The CLI entry:

```bash
trade data warehouse materialize-rss --catalog feeds.csv --entries rss_entries.csv
```

is the first local, deterministic path for materializing analysis data without
external network dependency.

## Source Catalog Position

The RSS source list is a simple record of candidate sources. It is not a full
configuration center and must not become an online runtime dependency.

Rules:

- Treat Google Sheet exports as one input format only.
- Support local CSV / JSON inputs as the durable path.
- Store normalized source metadata in `dim_data_source`.
- Keep source value hypotheses in warehouse metadata or dimensions.
- Do not require online Google Sheets for tests or normal local runs.

## Warehouse Layer Contract

Use the domestic warehouse layering vocabulary for analysis data:

```text
ODS  - raw facts as received, retained before cleaning
DIM  - conformed dimensions and analysis metadata
DWD  - cleaned atomic facts with quality and semantic checks
DWS  - subject-level aggregates and statistical structures
ADS  - analysis-facing signals, reports, validation, and evidence
```

Layer responsibilities:

| Layer | Responsibility |
| --- | --- |
| ODS | Preserve every captured source row, even dirty or malformed rows. |
| DIM | Define sectors, sources, topics, assets, features, and hypotheses. |
| DWD | Normalize fields, record quality checks, semantic NULLs, relevance. |
| DWS | Compute ratios, baselines, z-scores, concentration, co-movement. |
| ADS | Explain why signals may matter, validate them, and expose queryable outputs. |

Critical rule:

> Cleaning must never block ODS ingestion. Cleaning only controls promotion into
> DWD / DWS / ADS.

## Analysis Domains

### Crypto

Purpose:

- Analyze risk appetite, liquidity sensitivity, volatility regimes, regulation,
  and cross-asset relationships.

First deterministic signals:

- BTC / ETH trend and volatility regime.
- Crypto news / regulation burst.
- Risk appetite divergence versus Nasdaq, gold, USD, and rates.
- Institutional flow or ETF-related attention when data is available locally.

### AI

Purpose:

- Analyze technology trend, compute demand, cloud capex, semiconductor supply
  chain, application adoption, and China-specific translation.

First deterministic signals:

- AI topic burst.
- Source consensus across technical and market sources.
- Entity co-mention: OpenAI / NVIDIA / cloud / capex / chips.
- China relevance for AI industry and policy context.

### Banks

Purpose:

- Analyze rates, credit risk, real-estate exposure, policy easing/tightening,
  dividend / defensive behavior, and institution accumulation patterns.

First deterministic signals:

- Credit-risk news density.
- Policy easing / tightening signal.
- Real-estate risk signal.
- Institution accumulation when local transaction/flow data is available.
- Defensive sentiment under risk-off regimes.

## Analysis Output Contract

Every new analysis output should include:

- `evidence`: source rows, feature rows, or metric rows that support it.
- `reason`: human-readable explanation of why it may matter.
- `validation_status`: `candidate`, `validated`, `rejected`, or `monitoring`.

EDA alone is not enough. EDA should lead to one of:

- a hypothesis,
- a validation task,
- a signal report,
- an attribution record,
- or a rejected/retired data source.

## Validation Model

Validation should remain deterministic for v1.

Initial validation types:

- Coverage and freshness.
- Semantic quality and NULL reasons.
- Ratio / z-score / percentile anomaly.
- RankIC / IC when market target data exists.
- Forward return spread by quantile.
- Stability across rolling windows.
- Association and lag relationship.

The existing evaluation modules are still centered on source/event/model/gate
quality. New research validation should extend this concept for analysis
warehouse outputs without replacing the existing quality gate.

Recommended first ADS validation tables:

- `ads_source_value_report`
- `ads_data_signal_report`
- `ads_feature_value_report`
- `ads_association_result`
- `ads_hypothesis_validation_report`

## Position-Risk Awareness

Position risk is a secondary line because the user already has positions.

First version responsibilities:

- Know which assets are held or watched.
- Link assets to Crypto / AI / Banks sectors and topics.
- Surface new evidence that affects a position thesis.
- Identify risk warnings and invalidators.
- Support manual review before the user acts.

Non-responsibilities:

- No automatic trade execution.
- No automatic portfolio optimizer.
- No forced action labels.

Potential output language:

- `needs_review`
- `risk_increased`
- `thesis_strengthened`
- `thesis_weakened`
- `invalidator_candidate`
- `watch_only`

Avoid framing these as mandatory buy/sell instructions.

## Web And CLI Direction

### CLI

CLI should expose deterministic, file-backed, local workflows first:

- materialize warehouse data,
- inspect warehouse validation,
- run signal validation,
- inspect source value reports.

The existing `trade data warehouse materialize-rss` is the first example.

### Web

Existing pages remain. Future analysis-first Web surfaces should be additive:

- Research overview.
- Sector workbench for Crypto / AI / Banks.
- Source value explorer.
- Signal validation explorer.
- Position-risk watch surface.

Do not remove Today / Candidates / Symbol / Ops while this transition is in
progress.

## Worktree And Multi-Agent Rule

All ongoing structure optimization for this project should happen in an isolated
TradeDB worktree, not in the main checkout used by other agents.

Current safe worktree:

```text
/tmp/trade-structure-opt
```

Rules:

- Do not edit `nvim-config` or `neovim` repositories from this workflow.
- Do not use shared worktrees for broad refactors.
- Keep each structural change small and committed.
- Run focused tests and full Python tests before each commit when Python code is
  touched.
- Leave unrelated untracked generated files alone.

## M0 Completion Criteria

- Direction document exists and records the analysis-first target.
- Non-goals are explicit.
- Existing EBRT surfaces are preserved as supporting infrastructure.
- Warehouse layering is defined with ODS / DIM / DWD / DWS / ADS terms.
- Crypto / AI / Banks are the first domains.
- RSS source list is defined as an input, not an online dependency.
- Position risk is scoped as monitoring and manual decision support only.
- Worktree isolation rule is documented.

## Next Milestones

### M1 - Research Domain Skeleton

- Add `dim_sector` and `dim_topic` helpers for Crypto / AI / Banks.
- Move hard-coded sector keywords out of `articles.py` into a small deterministic
  profile module or local config fixture.
- Keep local CSV / JSON tests as the only required test input.

### M2 - Warehouse Validation Expansion

- Add feature value report table shape.
- Add association result table shape.
- Add first deterministic validations for topic burst and source consensus.

### M3 - Position Context

- Add local position/watchlist research context.
- Link position rows to sector/topic profiles.
- Generate first `ads_position_risk_signal` candidate output.

### M4 - Research Web Surface

- Add read-only API endpoints for warehouse ADS outputs.
- Add a research workbench page without removing existing pages.

## Implementation Status

Current branch:

```text
trade-structure-opt
```

Completed implementation commits:

- `b45d6eb Add research sector profiles`
  - Added deterministic Crypto / AI / Banks research profiles.
  - Materializes `dim_sector` and `dim_topic`.
- `6d7d513 Add deterministic research validation outputs`
  - Added ADS feature value, association, and hypothesis validation reports.
  - Ensures outputs include evidence, reason, and validation status.
- `5ccb9ae Add position risk research context`
  - Added local position/watchlist context.
  - Materializes `dim_position` and `ads_position_risk_signal`.
  - Uses manual-review language only; no trade actions are produced.
- `b18cab7 Expose read-only research warehouse APIs`
  - Added read-only backend research warehouse table listing and table read APIs.
- `73db3ac Add research warehouse web page`
  - Added a read-only Research page.
  - Existing Today / Candidates / Symbol / Ops pages remain in place.

Final validation performed after implementation:

- `uv run --with pytest pytest -q`
- `npm --prefix trade_web/frontend run build`

This completes the M1-M4 implementation plan for the first analysis-first
research-system slice.

## Data Supplementation Status - 2026-07-09

The one-year data supplementation goal is active and is being handled as a
controlled, resumable backfill rather than a high-QPS crawl.

Current local data state after the latest controlled run:

- K-line files: 5,702 symbols, 7,618,551 rows, date range
  `2020-01-02 -> 2026-07-09`.
- K-line tracked symbols in `sync_state`: 5,489.
- SH/SZ tracked symbols: 5,191.
- Symbols with latest K-line date on or after `2026-07-01`: 3,429.
- Symbols with latest K-line date equal to `2026-07-09`: 3,424.
- BJ or other non-SH/SZ symbols: 298, currently maxing at `2026-03-23`.

Controlled Tencent K-line fallback result:

- Provider: `tencent`.
- Mode: `incremental`.
- Batch policy: 100 symbols per batch, serial execution, `delay_ms=300`.
- Thirty-three SH/SZ batches completed with 3,300 requested symbols, 3,300
  successes, 0 failures, 2 empty returns, and 239,781 added rows.
- Empty returns observed for `603056.SH` and `002231.SZ`; these should be
  checked against instrument/listing status before repeated retries.

Remaining backfill constraints:

- Tushare remains unavailable because the configured token is rejected by the
  server.
- Akshare and Baostock were unreliable in this environment during the latest
  retry attempts.
- Tencent is currently the stable SH/SZ fallback, but it should continue to run
  in small serial batches with explicit delay and stop-on-throttle behavior.
- BJ symbols need a separate provider strategy because the current Tencent
  provider supports SH/SZ only.

The detailed local audit is kept at:

```text
data/warehouse/ads/backfill_audit_2026-07-09.json
```

That audit file is intentionally under ignored generated data. This document is
the tracked project-level summary.
