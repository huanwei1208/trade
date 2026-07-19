// Deterministic fixtures for observatory tests. Shapes mirror the frozen backend
// contracts exactly (see frozen_contracts.md and the WP3 facade). The composite
// fixture deliberately sets observed_watermark (2026-07-18) AHEAD of the formal
// watermark (2026-07-11) with a candidate + observed-only tail, one quarantined
// date, one revised date, and one MISSING date to exercise every invariant.

import type {
  ObsCompositeSeries,
  ObsContext,
  ObsDateEvidence,
  ObsHypothesesPayload,
  ObsResearchRun,
  ObsRunDiff,
  ObsRunsPayload,
  ObsSeriesRow,
  ObsSingleSeries,
  ObsTrust,
} from "../lib/api";

function row(date: string, close: string | null, over: Partial<ObsSeriesRow> = {}): ObsSeriesRow {
  return {
    date,
    open: close,
    high: close,
    low: close,
    close,
    volume: "1000",
    provider: "okx",
    instrument: "BTC-USDT",
    quote: "USDT",
    available_at: `${date}T00:05:00Z`,
    fetched_at: `${date}T00:06:00Z`,
    source_run_id: "run_formal",
    membership: ["formal"],
    availability_state: "present",
    quality_flags: [],
    revision_state: "unchanged",
    render_role: "formal_baseline",
    metrics: {},
    ...over,
  };
}

export const CONTRACT = {
  asset_id: "crypto.BTC",
  display_symbol: "BTC",
  contract_version: "v1",
  primary_provider: "okx",
  primary_instrument: "BTC-USDT",
  shadow_provider: "binance",
  shadow_instrument: "BTCUSDT",
  quote: "USDT",
  primary_interval: "1Dutc",
  shadow_interval: "1d",
};

export const CONTEXT_FIXTURE: ObsContext = {
  snapshot_id: "snapshot_observed_0001",
  resolved_channel: "observed",
  run_id: "run_observed",
  release_id: null,
  contract: CONTRACT,
  market_watermark: "2026-07-18",
  input_watermarks: { primary: "2026-07-18", shadow: "2026-07-18" },
  output_watermark: "2026-07-18",
  requested_knowledge_as_of: "latest",
  effective_knowledge_cut: "2026-07-18T00:00:00Z",
  relevant_fact_sequence: 42,
  knowledge_mode: "installation_observed",
  revision_policy: "as_known",
  pit_coverage_status: "proven",
  created_at: "2026-07-18T01:00:00Z",
  certified_at: null,
  published_at: null,
  rendered_at: "2026-07-19T09:00:00Z",
  lifecycle_state: "staged",
  quality_state: "degraded",
  freshness_state: "fresh",
  compatibility_state: "compatible",
  acquisition_state: "succeeded",
  purpose_fitness: [
    { purpose: "manual_observation", allowed: true, status: "allowed", reason_codes: [], evidence_refs: [] },
    { purpose: "exploratory_research", allowed: true, status: "allowed", reason_codes: [], evidence_refs: [] },
    {
      purpose: "formal_system_consumption",
      allowed: false,
      status: "blocked",
      reason_codes: ["CHANNEL_UNAVAILABLE"],
      evidence_refs: ["release_ledger"],
    },
    {
      purpose: "strict_research",
      allowed: false,
      status: "blocked",
      reason_codes: ["RESEARCH_NOT_ELIGIBLE"],
      evidence_refs: [],
    },
  ],
  artifact_refs: [{ name: "canonical", sha256: "abc123def456", relative_path: "runs/run_observed/canonical.parquet" }],
  findings_summary: { acquisition_stability: "3 / 29 real success days" },
  excluded_dates: [
    { date: "2026-07-15", exclusion_reason: "quarantined", quality_flags: ["quarantined"], evidence_refs: [], marker_position: null },
  ],
  reason_codes: [],
  view_fingerprint: "vf_context_0001",
  etag: "etag_context_0001",
  evidence_coverage: { earliest_proven_knowledge_time: "2024-01-01T00:00:00Z" },
  semantic_channels: {
    formal: { run_id: "run_formal", watermark: "2026-07-11", release_id: "release_0007" },
    evaluated_candidate: { run_id: "run_candidate", watermark: "2026-07-18", release_id: null },
    observed: { run_id: "run_observed", watermark: "2026-07-18", release_id: null },
  },
};

// Formal layer: 2026-07-09 .. 2026-07-11 (baseline, watermark 07-11).
const FORMAL_ROWS: ObsSeriesRow[] = [
  row("2026-07-09", "58000", { source_run_id: "run_formal", membership: ["formal"] }),
  row("2026-07-10", "59000", { source_run_id: "run_formal", membership: ["formal"] }),
  row("2026-07-11", "60000", { source_run_id: "run_formal", membership: ["formal"] }),
];

// Candidate layer: overlaps formal + extends to 07-14, includes a MISSING date
// (07-13) that MUST break the line (no interpolation), plus a revised overlap.
const CANDIDATE_ROWS: ObsSeriesRow[] = [
  row("2026-07-10", "59050", { source_run_id: "run_candidate", membership: ["evaluated_candidate"], render_role: "candidate_overlap", revision_state: "changed" }),
  row("2026-07-11", "60000", { source_run_id: "run_candidate", membership: ["evaluated_candidate"], render_role: "candidate_overlap" }),
  row("2026-07-12", "61000", { source_run_id: "run_candidate", membership: ["evaluated_candidate"], render_role: "candidate_only" }),
  row("2026-07-13", null, {
    source_run_id: "run_candidate",
    membership: ["evaluated_candidate"],
    render_role: "candidate_only",
    availability_state: "missing",
    quality_flags: [],
  }),
  row("2026-07-14", "62000", { source_run_id: "run_candidate", membership: ["evaluated_candidate"], render_role: "candidate_only" }),
];

// Observed layer: extends beyond candidate to 07-18 (observed-only tail),
// with a quarantined date (07-15) and a revised date (07-17).
const OBSERVED_ROWS: ObsSeriesRow[] = [
  row("2026-07-14", "62010", { source_run_id: "run_observed", membership: ["latest_observed"], render_role: "observed_overlap" }),
  row("2026-07-15", "62500", {
    source_run_id: "run_observed",
    membership: ["latest_observed"],
    render_role: "observed_only",
    quality_flags: ["quarantined"],
  }),
  row("2026-07-16", "63000", { source_run_id: "run_observed", membership: ["latest_observed"], render_role: "observed_only" }),
  row("2026-07-17", "63500", {
    source_run_id: "run_observed",
    membership: ["latest_observed"],
    render_role: "observed_only",
    revision_state: "changed",
  }),
  row("2026-07-18", "64000", { source_run_id: "run_observed", membership: ["latest_observed"], render_role: "observed_only" }),
];

export const COMPOSITE_FIXTURE: ObsCompositeSeries = {
  view: "composite",
  asset_id: "crypto.BTC",
  etag: "etag_composite_0001",
  fingerprint_basis: "fb_composite_0001",
  layers: {
    formal: { channel: "formal", context: { ...CONTEXT_FIXTURE, resolved_channel: "formal", market_watermark: "2026-07-11" }, rows: FORMAL_ROWS },
    evaluated_candidate: { channel: "evaluated_candidate", context: { ...CONTEXT_FIXTURE, resolved_channel: "evaluated_candidate" }, rows: CANDIDATE_ROWS },
    latest_observed: { channel: "latest_observed", context: CONTEXT_FIXTURE, rows: OBSERVED_ROWS },
  },
  reason_codes: [],
  view_fingerprint: "vf_composite_0001",
};

export const FORMAL_SERIES_FIXTURE: ObsSingleSeries = {
  view: "formal",
  context: { ...CONTEXT_FIXTURE, resolved_channel: "formal", market_watermark: "2026-07-11" },
  rows: FORMAL_ROWS.map((r, i) => ({
    ...r,
    metrics:
      i === FORMAL_ROWS.length - 1
        ? { return_1d: "1.69", return_7d: "3.44", return_30d: "12.10", drawdown: "-4.20", rv20_percentile: "72" }
        : {},
  })),
  pit_valid: true,
  reason_codes: [],
  view_fingerprint: "vf_formal_0001",
  etag: "etag_formal_0001",
};

export const DATE_EVIDENCE_FIXTURE: ObsDateEvidence = {
  date: "2026-07-15",
  snapshot_id: "snapshot_observed_0001",
  run_id: "run_observed",
  ohlcv: OBSERVED_ROWS[1],
  reconciliation: { basis_bps: "12.5", aligned: "true" },
  revision: { revision_state: "unchanged", old_close: null, new_close: null },
  run_lineage: ["run_observed"],
  research_visibility: "not_visible",
  reason_codes: [],
};

export const TRUST_FIXTURE: ObsTrust = {
  snapshot_id: "snapshot_observed_0001",
  run_id: "run_observed",
  gates: [
    { gate: "contract", status: "pass", reason_code: null, detail: "identity verified", metrics: {} },
    { gate: "acquisition", status: "warn", reason_code: "D1_INSUFFICIENT", detail: "3 / 29 real success days", metrics: { success_days: 3 } },
    { gate: "structure", status: "pass", reason_code: null, detail: "schema ok", metrics: {} },
    { gate: "cross_source", status: "pass", reason_code: null, detail: "basis within band", metrics: {} },
    { gate: "revision", status: "warn", reason_code: "REVISION_DETECTED", detail: "1 revised date", metrics: {} },
    { gate: "publish", status: "block", reason_code: "CHANNEL_UNAVAILABLE", detail: "not published", metrics: {} },
  ],
  findings: [
    {
      finding_id: "f001",
      gate: "acquisition",
      severity: "warn",
      reason_code: "D1_INSUFFICIENT",
      affected_dates: ["2026-07-12", "2026-07-13"],
      evidence_refs: ["run_candidate"],
    },
  ],
  acquisition_state: "succeeded",
  quality_state: "degraded",
};

export const RUNS_FIXTURE: ObsRunsPayload = {
  runs: [
    { run_id: "run_observed", created_at: "2026-07-18T01:00:00Z", market_watermark: "2026-07-18", data_readiness: "degraded", quality_state: "degraded", lifecycle_state: "staged", canonical_rows: 725 },
    { run_id: "run_candidate", created_at: "2026-07-17T01:00:00Z", market_watermark: "2026-07-14", data_readiness: "degraded", quality_state: "degraded", lifecycle_state: "staged", canonical_rows: 720 },
    { run_id: "run_formal", created_at: "2026-07-11T01:00:00Z", market_watermark: "2026-07-11", data_readiness: "ready", quality_state: "assured", lifecycle_state: "published", canonical_rows: 730 },
  ],
  next_cursor: null,
  catalog_fingerprint: "catalog_fp_0001",
};

export const RUN_DETAIL_FIXTURE = {
  run_id: "run_observed",
  created_at: "2026-07-18T01:00:00Z",
  market_watermark: "2026-07-18",
  data_readiness: "degraded",
  quality_state: "degraded",
  lifecycle_state: "staged",
  acquisition_state: "succeeded",
  canonical_rows: 725,
  code_revision: "abc123",
  artifact_refs: [{ name: "canonical", sha256: "abc123def456" }],
  gates: TRUST_FIXTURE.gates,
};

export const RUN_DIFF_FIXTURE: ObsRunDiff = {
  base: { run_id: "run_formal", watermark: "2026-07-11", canonical_rows: 730, canonical_hash: "hf", code_revision: "aaa", config_hash: "c1", schema_hash: "s1" },
  compare: { run_id: "run_observed", watermark: "2026-07-18", canonical_rows: 725, canonical_hash: "ho", code_revision: "bbb", config_hash: "c1", schema_hash: "s1" },
  added_dates: ["2026-07-12", "2026-07-14", "2026-07-16", "2026-07-17", "2026-07-18"],
  removed_dates: ["2026-07-05"],
  changed_dates: [{ date: "2026-07-10", base_close: "59000", compare_close: "59050" }],
  gate_changes: { publish: { base: ["pass", null], compare: ["block", "CHANNEL_UNAVAILABLE"] } },
  code_changed: true,
  config_changed: false,
  schema_changed: false,
};

export const HYPOTHESES_FIXTURE: ObsHypothesesPayload = {
  hypotheses: [
    {
      hypothesis_id: "H1",
      hypothesis_version: "btc-vol-persistence-v1",
      statement:
        "After BTC 20-day realized volatility enters a high-volatility regime, is the next seven full-UTC-day realized volatility significantly and stably higher than normal days?",
      directional: false,
      research_state: "candidate",
      current_research_run_id: "H1:gen_0007",
    },
  ],
};

export const RESEARCH_RUN_FIXTURE: ObsResearchRun = {
  research_run_id: "H1:gen_0007",
  hypothesis_id: "H1",
  hypothesis_version: "btc-vol-persistence-v1",
  validation_run_id: "val_0007",
  generation_id: "gen_0007",
  dataset_snapshot_id: "snapshot_formal_0007",
  knowledge_as_of: "2026-07-11T00:00:00Z",
  research_state: "candidate",
  is_current: true,
  metrics: {
    effect_ratio: "1.42",
    ci_low: "1.05",
    ci_high: "1.93",
    q_value: "0.031",
    sample_size: "58",
    data_readiness: "degraded",
  },
  evidence_refs: ["receipts/h1_gen_0007.json"],
};
