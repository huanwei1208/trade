## Why

The repository can now observe and update local market data, but its current prediction path is not research-ready: the daily factor and feature snapshots are stale, the event-propagation labels contain extreme outliers, the five-day risk threshold uses inconsistent units between training and evaluation, and the active model reports are based on too few distinct validation days. The next change must establish an auditable point-in-time forecasting loop before any output is presented as evidence about future direction, turning zones, or downside risk.

## What Changes

- Add a versioned point-in-time daily research dataset for an initial A-share universe consisting of CSI 300 constituents plus the local watchlist, with explicit universe membership, adjustment provenance, feature availability, label maturity, and data lineage.
- Normalize return semantics to decimal units (`0.05 == 5%`), quarantine impossible or unexplained price/return observations, and prevent training or promotion while research-data gates fail.
- Add baseline-first 1-day, 5-day, and 20-day direction and excess-return forecasts with expanding purged walk-forward validation, regime/sector slices, baseline comparison, calibration, and explicit candidate/monitoring/validated/rejected states.
- Add probabilistic local-low/local-high zone and downside-risk outputs, including return quantiles, drawdown probability, expected adverse excursion, and volatility regime; exact top/bottom claims are explicitly out of scope.
- Persist immutable forecast snapshots before outcomes are known, attach matured outcomes later without mutating the original forecast, and expose read-only status/show/rank/risk/validate/outcomes CLI queries.
- Reuse the existing factor registry, model registry, evaluation, evidence, causal, and research warehouse infrastructure behind new stable research-domain boundaries. Existing event/KG/belief outputs remain optional evidence and may not bypass forecast validation gates.
- Add additive TradeDB schema only for dataset versions, forecast snapshots, matured outcomes, and validation runs. Any real-data rebuild or migration requires backup, dry-run, small-sample verification, replay/hash comparison, and rollback to the prior active dataset/model version.
- Preserve existing `trade data`, recommendation, Today/Candidates/Symbol/Ops, and causal APIs. Forecast v1 is decision support only: no automatic trading, portfolio optimization, forced buy/sell labels, or automatic model promotion.

## Capabilities

### New Capabilities

- `point-in-time-research-dataset`: Defines universe, price-adjustment, feature availability, label-unit, lineage, replay, anomaly-quarantine, and readiness contracts for daily forecasting data.
- `multi-horizon-forecasting`: Defines baseline-first 1d/5d/20d direction and excess-return targets, purged walk-forward validation, calibration, slicing, and promotion states.
- `turning-zone-risk-forecasting`: Defines probabilistic local-extremum-zone, return-quantile, drawdown, adverse-excursion, and volatility-regime outputs and validation.
- `forecast-observability`: Defines immutable forecast/outcome/validation records, fail-closed status semantics, evidence and confidence fields, and read-only CLI contracts.

### Modified Capabilities

- None. Existing data operations, Crypto validation, recommendation, and causal contracts remain compatible and are consumed only through additive boundaries.

## Impact

- **Python/domain:** new research-dataset and forecast domain/service/repository modules; focused changes to factor materialization, model training/evaluation, and research CLI routing.
- **Data/DB:** additive local schema and derived parquet artifacts under the configured data root; no generated data is committed. Historical source data is read-only input, and derived research versions are reversible.
- **CLI:** additive `trade research dataset ...` and `trade research forecast ...` surfaces; existing commands retain behavior.
- **API/Web:** no required Web change in this implementation slice. A later change may expose the same read-only forecast contracts in the Research page.
- **Financial semantics:** every output carries evidence, data/model versions, horizon, probability or interval, calibration/validation state, and explicit blocked/unknown reasons. Existing heuristic recommendation and causal values remain labeled as heuristic and cannot be promoted as calibrated forecasts.
- **Compatibility risks:** return-unit migration, adjustment/corporate-action handling, point-in-time universe construction, rare-event labels, and historical model comparisons can invalidate existing derived labels and model scores. Rollout therefore uses new versioned artifacts and shadow mode rather than in-place reinterpretation.
