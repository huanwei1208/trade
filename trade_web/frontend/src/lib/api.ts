import { useEffect, useState } from "react";

export type Locale = "zh-CN" | "en-US";
export type PageKey =
  "today" | "candidates" | "symbol" | "ops" | "research" | "data" | "observatory";
export type ActionType = "ADD" | "PROBE" | "WATCH" | "REDUCE" | "NO_ACTION" | string;

export type TrustGate = {
  operational_status?: string;
  research_status?: string;
  brier_score?: number | null;
  drift_mmd?: number | null;
  eval_date?: string;
  trust_scalar?: number | null;
  trust_components?: Record<string, number>;
  freshness?: Array<{ dataset?: string; lag_days?: number | null; status?: string }>;
};

export type PipelineHealth = {
  total?: number;
  ok?: number;
  error?: number;
  running?: number;
  status?: string;
};

export type RecommendationState = "ACTIONABLE" | "CONSTRAINED" | "BROWSE_ONLY";

export type FactorSummary = {
  /** Top positive supporting factors — display as summary chips on Candidates, full decomposition on Symbol */
  positive?: string[];
  /** Top negative opposing factors */
  negative?: string[];
};

export type CandidateRow = {
  symbol?: string;
  name?: string;
  action?: ActionType;
  confidence?: string | number;
  score?: number;
  risk?: number;
  thesis?: string;
  trust_score?: number;
  trust_level?: string;
  world_state_summary?: string;
  top_invalidators?: string[];
  top_evidence?: Array<{ weight?: number; evidence_id?: string }>;
  sparkline?: Array<{ date?: string; close?: number }>;
  event_tags?: string[];
  belief_mu?: number;
  belief_sigma?: number;
  belief_delta_mu?: number | null;
  status?: string;
  // EBRT_15: richer candidate fields
  /** Factor summary: show on Candidates as chips. Full decomposition belongs on Symbol page only. */
  factor_summary?: FactorSummary;
  /** First data blocker flag for this symbol, if any */
  data_risk_flag?: string | null;
  /** Whether this recommendation is currently executable */
  recommendation_state?: RecommendationState;
};

export type TodayPageData = {
  as_of?: string;
  today_thesis?: string;
  market_regime?: string;
  blockers?: string[];
  decision_posture?: string;
  global_blocked?: boolean;
  blocker_details?: Array<{ dataset?: string; lag_days?: number | null; status?: string }>;
  safe_to_view?: string[];
  recovery_condition?: string;
  pipeline_health?: PipelineHealth;
  top_picks?: CandidateRow[];
  top_actions?: CandidateRow[];
  dropped_picks?: Array<{ symbol?: string }>;
  kline_last_date?: string;
  gate_status?: string;
  gate_reason?: string;
  trust_gate?: TrustGate;
  error_nodes?: Array<{ job_name?: string; status?: string; error_detail?: string }>;
  recent_runs?: Array<{
    job_name?: string;
    status?: string;
    started_at?: string;
    result_summary?: string;
  }>;
};

export type SignalsPageData = {
  as_of?: string;
  picks?: CandidateRow[];
  dropped?: Array<{ symbol?: string }>;
  total?: number;
  shown?: number;
  universe_total?: number;
  search?: string;
  source?: string;
};

// ── Symbol workspace types ───────────────────────────────────────────────────

export type AdjustMode = "none" | "qfq" | "hfq";
export type IndicatorMode = "rsi" | "macd" | "kdj" | "none";
export type ReasonPolarity = "support" | "oppose" | "neutral" | "warning";

export type ReasonItem = {
  id: string;
  group: string;
  polarity: ReasonPolarity;
  title: string;
  description: string;
  source?: string;
  metric_name?: string;
  metric_value?: number;
  metric_unit?: string;
  lookback?: string;
  strength?: number;
  sort_key?: number;
};

export type SymbolQuote = {
  latest_price?: number;
  prev_close?: number;
  change?: number;
  change_pct?: number;
  open?: number;
  high?: number;
  low?: number;
  volume?: number;
  amount?: number;
  turnover?: number;
  vwap?: number;
  as_of?: string;
};

export type PriceBasis = {
  adjust?: AdjustMode;
  timeframe?: string;
  latest_trade_date?: string;
  quote_as_of?: string;
};

export type KlineBar = {
  date?: string;
  open?: number;
  high?: number;
  low?: number;
  close?: number;
  volume?: number;
  amount?: number;
  turnover_rate?: number;
  prev_close?: number;
  vwap?: number;
  // Moving averages
  ma5?: number;
  ma10?: number;
  ma20?: number;
  ma60?: number;
  // RSI
  rsi14?: number;
  // MACD
  macd_dif?: number;
  macd_dea?: number;
  macd_hist?: number;
  macd_cross?: number;
  // KDJ
  kdj_k?: number;
  kdj_d?: number;
  kdj_j?: number;
  kdj_cross?: number;
};

export type EvidenceItem = {
  source?: string;
  direction?: string;
  strength?: number;
  description?: string;
  weight?: number;
};

export type ScenarioCase = {
  label?: string;
  probability?: number;
  thesis?: string;
  required_confirmations?: string[];
  invalidators?: string[];
  next_triggers?: string[];
  next_trigger_details?: NextTriggerDetail[];
};

export type ScenarioSummary = {
  symbol?: string;
  as_of_date?: string;
  base_case?: ScenarioCase;
  bull_case?: ScenarioCase;
  bear_case?: ScenarioCase;
  scenario_confidence?: number;
  dominant_scenario?: string;
  world_state_summary?: string;
};

export type NextTriggerDetail = {
  key?: string;
  current_value?: number | null;
  target_value?: number | null;
  unit?: string | null;
};

export type WorldMarketState = {
  regime?: string;
  window_score?: number | null;
  vol_ratio?: number | null;
  rationale?: string;
};

export type WorldEventState = {
  regime?: string;
  kg_score?: number | null;
  top_event_type?: string;
  event_count_recent?: number | null;
  rationale?: string;
};

export type WorldSentimentState = {
  regime?: string;
  belief_mu?: number | null;
  net_sentiment?: number | null;
  belief_sigma?: number | null;
  rationale?: string;
};

export type WorldTechnicalState = {
  regime?: string;
  rsi_14?: number | null;
  macd_signal?: number | null;
  rationale?: string;
};

export type WorldLiquidityState = {
  regime?: string;
  vol_ratio?: number | null;
  rationale?: string;
};

export type WorldUncertaintyState = {
  level?: string;
  belief_sigma?: number | null;
  trust_score?: number | null;
  rationale?: string;
};

export type WorldState = {
  symbol?: string;
  as_of_date?: string;
  market_regime?: string;
  event_regime?: string;
  sentiment_regime?: string;
  technical_regime?: string;
  liquidity_regime?: string;
  uncertainty_level?: string;
  uncertainty_score?: number;
  data_quality_score?: number;
  trust_score?: number;
  state_summary?: string;
  blockers?: string[];
  supporting_signals?: Array<Record<string, unknown>>;
  opposing_signals?: Array<Record<string, unknown>>;
  market_state?: WorldMarketState;
  event_state?: WorldEventState;
  sentiment_state?: WorldSentimentState;
  technical_state?: WorldTechnicalState;
  liquidity_state?: WorldLiquidityState;
  uncertainty_state?: WorldUncertaintyState;
  data_quality_state?: {
    score?: number;
    freshness_score?: number;
    missing_datasets?: string[];
    stale_datasets?: string[];
    rationale?: string;
  };
};

export type DecisionExplanation = {
  symbol?: string;
  as_of?: string;
  action?: ActionType;
  action_confidence?: string;
  thesis?: string;
  world_state_summary?: string;
  state_rationale?: string;
  trust?: {
    trust_score?: number;
    trust_level?: string;
    components?: Record<string, number>;
  };
  data_quality_notes?: string[];
  input_warnings?: string[];
  evidence_for?: EvidenceItem[];
  evidence_against?: EvidenceItem[];
  invalidators?: string[];
  next_triggers?: string[];
  next_trigger_details?: NextTriggerDetail[];
  scenario_summary?: ScenarioSummary | null;
  world_state?: WorldState | null;
  warnings?: string[];
  reason_groups?: Record<string, ReasonItem[]>;
};

export type KlineResponse = {
  symbol?: string;
  as_of?: string;
  name?: string;
  ohlcv?: KlineBar[];
  indicators?: Record<string, number>;
  // New: per-symbol quote and price basis metadata
  quote?: SymbolQuote;
  price_basis?: PriceBasis;
  // New: grouped factual reasons
  reason_groups?: Record<string, ReasonItem[]>;
  event_markers?: Array<{ date?: string; event_type?: string; kg_score?: number; title?: string }>;
  belief_overlay?: Array<{ date?: string; mu?: number; sigma?: number }>;
  prediction?: Record<string, unknown>;
  world_state?: WorldState;
  action?: {
    action?: ActionType;
    confidence?: string;
    score?: number;
    risk?: number;
    position_hint?: string;
    reason?: string;
    no_action_reason?: string;
    invalidators?: string[];
    next_triggers?: string[];
    supporting_factors?: string[];
    opposing_factors?: string[];
  };
  recommendation?: Record<string, unknown>;
  explanation?: Partial<DecisionExplanation>;
};

// ── Belief graph types ────────────────────────────────────────────────────────

export type BeliefHistoryPoint = {
  date?: string;
  mu?: number;
  sigma?: number;
  confidence?: number;
  delta_mu?: number;
};

export type FinalBeliefNode = {
  score?: number;
  confidence?: number;
  trust?: number;
  delta?: number;
};

export type SubBeliefNode = {
  id?: string;
  name_zh?: string;
  name_en?: string;
  score?: number;
  weight?: number;
  source?: string;
};

export type FactorNode = {
  id?: string;
  name?: string;
  score?: number;
  weight?: number;
  direction?: number;
  evidence_type?: string;
};

export type ProvenanceEdge = {
  from?: string;
  to?: string;
  weight?: number;
};

export type BeliefGraphResponse = {
  symbol?: string;
  as_of?: string;
  final_belief?: FinalBeliefNode;
  sub_beliefs?: SubBeliefNode[];
  factors?: FactorNode[];
  history?: BeliefHistoryPoint[];
  provenance_edges?: ProvenanceEdge[];
};

// Workspace tab type
export type WorkspaceTab = "decision" | "belief" | "evidence" | "data-ops";

// ── Symbol evidence types (EBRT_14) ──────────────────────────────────────────

export type SymbolMarketEvent = {
  id?: string;
  date?: string;
  event_type?: string;
  entity_id?: string;
  magnitude?: number;
  confidence?: number;
  sentiment_score?: number;
  news_volume?: number;
  summary?: string;
  source?: string;
};

export type SymbolEvidenceItem = {
  id?: string;
  date?: string;
  evidence_type?: string;
  direction?: number;
  strength?: number;
  reliability?: number;
  novelty?: number;
  source?: string;
};

export type SymbolAttentionItem = {
  id?: string;
  evidence_type?: string;
  weight?: number;
  direction?: number;
  source?: string;
};

export type SymbolEvidenceResponse = {
  symbol?: string;
  as_of?: string;
  sector_code?: string | null;
  market_events?: SymbolMarketEvent[];
  evidence_items?: SymbolEvidenceItem[];
  attention_items?: SymbolAttentionItem[];
};

export type PeerEntry = {
  symbol?: string;
  name?: string;
  action?: ActionType;
  conviction?: string;
  score?: number;
  risk?: number;
  window_score?: number | null;
  net_sentiment?: number | null;
  belief_mu?: number | null;
  belief_confidence?: number | null;
  kline_last_date?: string | null;
};

export type SymbolSectorResponse = {
  symbol?: string;
  as_of?: string;
  sector_code?: string | null;
  sector_name?: string | null;
  sector_sentiment?: number;
  sector_event_count?: number;
  peers?: PeerEntry[];
};

// ── Symbol data ops types (EBRT_14) ──────────────────────────────────────────

export type DataOpsDomain = {
  id?: string;
  name_zh?: string;
  name_en?: string;
  last_date?: string | null;
  lag_days?: number | null;
  row_count?: number | null;
  status?: string;
  source?: string;
  can_repull?: boolean;
};

export type SymbolDataOpsResponse = {
  symbol?: string;
  as_of?: string;
  domains?: DataOpsDomain[];
};

export type DataOpsRepairResponse = {
  accepted?: boolean;
  job_id?: string;
  message?: string;
  updated?: string[];
};

export type TrustOverview = {
  as_of?: string;
  trust_scalar?: number | null;
  coverage?: number | null;
  trend?: Array<{ eval_date?: string; trust_scalar?: number; coverage?: number }>;
};

export type StatusPayload = {
  status?: string;
  data_root?: string;
  today?: string;
  inference_models?: string[];
  models_loaded_at?: string;
  quality_gate?: {
    status?: string;
    reason_summary?: string;
    metrics_json?: Record<string, unknown>;
  };
  data_quality_gate?: {
    status?: string;
    reason_codes?: string[];
    components?: Record<string, unknown>;
    recovery_plan?: Array<{
      component?: string;
      command?: string[];
      mode?: string;
      detail?: string;
    }>;
  };
  data_status?: Record<string, unknown>;
  due_agenda?: Array<Record<string, unknown>>;
  planned_events?: Array<Record<string, unknown>>;
  backups?: Array<Record<string, unknown>>;
  backup_health?: Record<string, unknown>;
};

export type AutomationScheduleItem = {
  id?: string;
  topic?: string;
  label?: string;
  time?: string;
  cadence?: string;
  trading_day_only?: boolean;
  market_hours_only?: boolean;
  description?: string;
  currently_eligible?: boolean;
  state_hint?: string;
};

export type AutomationOverviewPayload = {
  today?: string;
  latest_market_asof?: string;
  latest_trading_day?: string;
  is_trading_day_today?: boolean;
  web_runs_scheduler?: boolean;
  requires_daemon?: boolean;
  daemon_command?: string;
  calendar?: Array<Record<string, unknown>>;
  schedules?: AutomationScheduleItem[];
  due_agenda?: Array<Record<string, unknown>>;
  recent_agenda?: Array<Record<string, unknown>>;
  recent_events?: Array<Record<string, unknown>>;
};

export type DagRuntime = {
  nodes?: Array<Record<string, unknown>>;
  edges?: Array<Record<string, unknown>>;
  stage_summary?: Record<
    string,
    { total?: number; running?: number; error?: number; ok?: number; disabled?: number }
  >;
};

export type DataHealthPayload = {
  datasets?: Array<{
    id?: string;
    name?: string;
    domain?: string;
    refresh_target?: string;
    lineage?: string;
    freshness_date?: string | null;
    lag_days?: number | null;
    coverage_pct?: number | null;
    rows?: number | null;
    count?: number | null;
    status?: string;
    notes?: string[];
  }>;
  domains?: Record<string, { count?: number; ok?: number; partial?: number; error?: number }>;
  highlights?: Array<{ kind?: string; title?: string; value?: number }>;
  summary?: { total?: number; ok?: number; partial?: number; error?: number };
  as_of?: string;
};

export type WorkflowSummary = Record<string, unknown>;
export type WorkflowDetailPayload = WorkflowSummary & {
  root_event_id?: number;
  title?: string;
  topic?: string;
  status?: string;
  created_at?: string;
  started_at?: string;
  completed_at?: string;
  progress?: {
    total?: number;
    completed?: number;
    running?: number;
    error?: number;
  };
  nodes?: Array<Record<string, unknown>>;
};

export type OpsNodeType = "source" | "feature" | "factor" | "model" | "decision" | "workflow";
export type OpsLayerKey = OpsNodeType;
export type OpsRuntimeStatus = "ok" | "running" | "partial" | "error" | "unknown";

export type OpsOutputSummary = {
  primary?: string;
  secondary?: string | null;
  metric?: number | string | null;
  changed?: boolean | null;
};

export type OpsComputeNode = {
  id: string;
  name: string;
  type: OpsNodeType;
  layer: OpsLayerKey;
  description?: string;
  latest_status?: OpsRuntimeStatus;
  last_run_at?: string | null;
  latest_output_summary?: OpsOutputSummary | null;
  previous_output_summary?: OpsOutputSummary | null;
  delta_summary?: string | null;
  upstream_ids?: string[];
  downstream_ids?: string[];
  can_backfill?: boolean;
  can_replay?: boolean;
  can_compare?: boolean;
  mapped_dataset?: string | null;
  mapped_job_names?: string[];
  representative_symbol?: string | null;
};

export type OpsLayerGroup = {
  key: OpsLayerKey;
  label: string;
  nodes: OpsComputeNode[];
};

export type OpsComputeLayersPayload = {
  as_of?: string;
  previous_as_of?: string | null;
  representative_symbol?: string | null;
  layers: OpsLayerGroup[];
  nodes: OpsComputeNode[];
};

export type OpsDependencyNode = {
  id: string;
  name: string;
  type: OpsNodeType;
  layer: OpsLayerKey;
  description?: string;
};

export type OpsDependencyEdge = {
  from: string;
  to: string;
};

export type OpsDependencyPathPayload = {
  selected_node_ids: string[];
  nodes: OpsDependencyNode[];
  edges: OpsDependencyEdge[];
  upstream_ids: string[];
  downstream_ids: string[];
};

export type OpsNodeResultPayload = OpsComputeNode & {
  as_of?: string;
  previous_as_of?: string | null;
  representative_symbol?: string | null;
  dependency_path?: OpsDependencyPathPayload;
  details?: Record<string, unknown> & { kind?: string };
};

export type OpsReplayMode = "selected_only" | "selected_plus_downstream" | "full_chain";
export type OpsReplayAction = "repair" | "recompute";

export type OpsSelectedCell = {
  id?: string;
  dataset?: string;
  date?: string;
};

export type OpsReplayJob = {
  job_name?: string;
  mapped_from?: string;
  layer?: OpsLayerKey;
  node_type?: OpsNodeType;
  avg_duration_ms?: number | null;
};

export type OpsReplayPreviewPayload = {
  selected_nodes: Array<{
    id: string;
    name: string;
    type: OpsNodeType;
    layer: OpsLayerKey;
  }>;
  selected_cells: OpsSelectedCell[];
  mode: OpsReplayMode;
  action: OpsReplayAction;
  date_from: string;
  date_to: string;
  nodes_to_run: OpsReplayJob[];
  downstream_affected: Array<{
    id: string;
    name: string;
    type: OpsNodeType;
    layer: OpsLayerKey;
  }>;
  warnings: string[];
  estimated_scope: {
    selected_count?: number;
    node_count?: number;
    job_count?: number;
    layers?: OpsLayerKey[];
    estimated_duration_ms?: number | null;
  };
};

export type OpsReplayExecuteResponse = {
  accepted: boolean;
  workflow_event_id: number;
  preview: OpsReplayPreviewPayload;
};

export type ReadinessStatus =
  "READY" | "LATE_READY" | "PARTIAL" | "MISSING" | "CHANGED" | "REPLAYING" | "REPLAYED" | "UNKNOWN";

export type ReadinessHistoryItem = {
  ts?: string;
  action?: string;
  reason_code?: string | null;
  duration_ms?: number | null;
  api_calls_actual?: number | null;
  error?: string | null;
  status?: string | null;
};

export type RecoveryStep = {
  job_name?: string | null;
  status?: string | null;
  summary?: string | null;
  duration_ms?: number | null;
};

export type RecoveryActionResult = {
  steps?: RecoveryStep[];
  duration_ms?: number | null;
};

export type ReadinessCell = {
  id: string;
  dataset: string;
  date: string;
  status: ReadinessStatus;
  row_count?: number | null;
  expected_count?: number | null;
  coverage_pct?: number | null;
  lag_days?: number | null;
  source_last_date?: string | null;
  last_backfill_at?: string | null;
  affected_outputs?: string[];
  history?: ReadinessHistoryItem[];
  reason_codes?: string[];
  changed_since_last_ready?: boolean;
  fingerprint?: string | null;
};

export type ReadinessRow = {
  dataset: string;
  label: string;
  critical: boolean;
  job_name?: string | null;
  impacts?: string[];
  cells: ReadinessCell[];
};

export type ReadinessGridPayload = {
  as_of?: string;
  range: {
    days: number;
    end_date: string;
    dates: string[];
  };
  summary: {
    overall_readiness_pct?: number | null;
    blocked_days?: number;
    unstable_datasets?: Array<{ dataset: string; label: string; issue_count: number }>;
    today_impact?: {
      date?: string;
      affected_outputs?: string[];
      datasets?: Array<{
        dataset: string;
        label: string;
        status: ReadinessStatus;
        affected_outputs?: string[];
      }>;
      constrained?: boolean;
    };
  };
  datasets: Array<{
    key: string;
    label: string;
    critical: boolean;
    job_name?: string | null;
    affected_outputs?: string[];
  }>;
  rows: ReadinessRow[];
  recovery_history?: Record<string, ReadinessHistoryItem[]>;
};

export type ReplayPlanPayload = {
  dataset: string;
  label: string;
  job_name?: string | null;
  recommended_mode: "data_only" | "data_plus_downstream" | "full_replay";
  affected_outputs?: string[];
  downstream_nodes?: Array<{
    job_name?: string;
    stage?: string;
    enabled?: boolean;
    avg_duration_ms?: number | null;
  }>;
  full_chain?: Array<{
    job_name?: string;
    stage?: string;
    enabled?: boolean;
    avg_duration_ms?: number | null;
  }>;
  date_from: string;
  date_to: string;
  estimated_duration_ms?: number | null;
};

export type ReadinessActionResponse = {
  accepted: boolean;
  action_id: number;
  plan: ReplayPlanPayload;
};

export type ReadinessActionDetail = {
  id: number;
  dataset: string;
  date_from: string;
  date_to: string;
  action_type: string;
  mode: string;
  status: string;
  requested_at: string;
  updated_at: string;
  job_names_json?: string;
  affected_outputs_json?: string;
  result_json?: string;
  job_names?: string[];
  affected_outputs?: string[];
  result?: RecoveryActionResult | null;
  summary?: string | null;
  error?: string | null;
  fingerprint_before?: string | null;
  fingerprint_after?: string | null;
};

export type ReadinessHistoryPayload = {
  items: ReadinessActionDetail[];
};

export type ReadinessChangePayload = {
  dataset: string;
  date_from: string;
  date_to: string;
  items: Array<{
    dataset: string;
    date: string;
    current_fingerprint?: string | null;
    previous_fingerprint?: string | null;
    changed: boolean;
    last_action_id?: number | null;
    last_action_status?: string | null;
  }>;
};

export type RecoveryProgress = {
  totalSteps: number;
  completedSteps: number;
  failedSteps: number;
  steps: RecoveryStep[];
  activeStep: RecoveryStep | null;
  progressRatio: number | null;
};

export type EventsPagePayload = {
  as_of?: string;
  workflows?: WorkflowSummary[];
  focus?: Record<string, unknown> | null;
  dag?: DagRuntime;
  today_events?: Array<Record<string, unknown>>;
  recent_market_events?: Array<Record<string, unknown>>;
  due_agenda?: Array<Record<string, unknown>>;
  planned_events?: Array<Record<string, unknown>>;
  failed_nodes?: Array<Record<string, unknown>>;
};

export type ResearchTableSummary = {
  layer: string;
  table: string;
  exists: boolean;
  row_count: number;
  path: string;
};

export type ResearchTablesPayload = {
  warehouse_root?: string;
  layers?: Array<{ layer: string; tables: ResearchTableSummary[] }>;
};

export type ResearchTablePayload = {
  warehouse_root?: string;
  layer?: string;
  table?: string;
  row_count?: number;
  columns?: string[];
  rows?: Array<Record<string, unknown>>;
};

export class ApiError extends Error {
  status?: number;
  detail?: unknown;

  constructor(message: string, status?: number, detail?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

function readCache<T>(cacheKey?: string): T | null {
  if (!cacheKey || typeof window === "undefined") {
    return null;
  }
  try {
    const raw = window.localStorage.getItem(cacheKey);
    if (!raw) {
      return null;
    }
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

function writeCache<T>(cacheKey: string | undefined, value: T) {
  if (!cacheKey || typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(cacheKey, JSON.stringify(value));
  } catch {
    // ignore cache failures
  }
}

function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) {
    return error;
  }
  if (error instanceof Error) {
    return new ApiError(error.message);
  }
  return new ApiError("Unknown error");
}

export async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: {
        Accept: "application/json",
        ...(init?.headers ?? {}),
      },
      cache: "no-store",
    });
  } catch {
    throw new ApiError("Network request failed. Check whether the backend is reachable.");
  }

  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text) as unknown;
    } catch {
      payload = text;
    }
  }

  if (!response.ok) {
    const message =
      (typeof payload === "object" &&
        payload &&
        "detail" in payload &&
        typeof payload.detail === "string" &&
        payload.detail) ||
      response.statusText ||
      "Request failed";
    throw new ApiError(message, response.status, payload);
  }

  return payload as T;
}

type ResourceState<T> = {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
  revalidating: boolean;
  stale: boolean;
  fromCache: boolean;
};

type ResourceOptions = {
  enabled?: boolean;
  deps?: unknown[];
  cacheKey?: string;
};

export function useApiResource<T>(path: string | null, options: ResourceOptions = {}) {
  const { enabled = true, deps = [], cacheKey } = options;
  const cached = readCache<T>(cacheKey);
  const [state, setState] = useState<ResourceState<T>>({
    data: cached,
    error: null,
    loading: Boolean(path && enabled && !cached),
    revalidating: false,
    stale: Boolean(cached),
    fromCache: Boolean(cached),
  });
  const [version, setVersion] = useState(0);

  useEffect(() => {
    if (!path || !enabled) {
      return;
    }
    const controller = new AbortController();
    const cachedValue = readCache<T>(cacheKey);
    if (cachedValue) {
      setState((current) => ({
        ...current,
        data: current.data ?? cachedValue,
        loading: false,
        revalidating: true,
        stale: true,
        fromCache: true,
        error: null,
      }));
    } else {
      setState((current) => ({
        ...current,
        loading: true,
        revalidating: false,
        error: null,
      }));
    }

    fetchJson<T>(path, { signal: controller.signal })
      .then((data) => {
        writeCache(cacheKey, data);
        setState({
          data,
          error: null,
          loading: false,
          revalidating: false,
          stale: false,
          fromCache: false,
        });
      })
      .catch((error) => {
        if (controller.signal.aborted) {
          return;
        }
        setState((current) => ({
          data: current.data,
          error: toApiError(error),
          loading: false,
          revalidating: false,
          stale: Boolean(current.data),
          fromCache: current.fromCache,
        }));
      });

    return () => {
      controller.abort();
    };
  }, [cacheKey, enabled, path, version, ...deps]);

  return {
    ...state,
    retry: () => setVersion((current) => current + 1),
  };
}

export function getTodayPage() {
  return fetchJson<TodayPageData>("/api/today-page");
}

export function getSignalsPage(options?: { search?: string; limit?: number }) {
  const params = new URLSearchParams();
  const search = String(options?.search || "").trim();
  const limit = Number(options?.limit || 0);
  if (search) {
    params.set("search", search);
  }
  if (Number.isFinite(limit) && limit > 0) {
    params.set("limit", String(limit));
  }
  const suffix = params.toString();
  return fetchJson<SignalsPageData>(`/api/signals-page${suffix ? `?${suffix}` : ""}`);
}

export function getExplain(symbol: string) {
  return fetchJson<DecisionExplanation>(`/api/explain/${symbol}`);
}

export function getState(symbol: string) {
  return fetchJson<WorldState>(`/api/state/${symbol}`);
}

export function getKline(symbol: string) {
  return fetchJson<KlineResponse>(`/api/kline/${symbol}`);
}

export function getTrustOverview() {
  return fetchJson<TrustOverview>("/api/trust/overview");
}

export function getStatus() {
  return fetchJson<StatusPayload>("/api/status");
}

export function getAutomationOverview() {
  return fetchJson<AutomationOverviewPayload>("/api/automation/overview");
}

export function getDagRuntime() {
  return fetchJson<DagRuntime>("/api/dag/runtime");
}

export function getDataHealth() {
  return fetchJson<DataHealthPayload>("/api/data-health");
}

export function getWorkflows() {
  return fetchJson<WorkflowSummary[]>("/api/workflows");
}

export function getWorkflowDetail(rootEventId: number) {
  return fetchJson<WorkflowDetailPayload>(`/api/workflows/${rootEventId}`);
}

export function getEventsPage() {
  return fetchJson<EventsPagePayload>("/api/events-page");
}

export function getReadinessGrid(days = 30, endDate?: string) {
  const query = new URLSearchParams({ days: String(days) });
  if (endDate) {
    query.set("end_date", endDate);
  }
  return fetchJson<ReadinessGridPayload>(`/api/readiness-grid?${query.toString()}`);
}

export function getOpsComputeLayers(date?: string) {
  const query = new URLSearchParams();
  if (date) {
    query.set("date", date);
  }
  const suffix = query.toString();
  return fetchJson<OpsComputeLayersPayload>(`/api/ops/compute-layers${suffix ? `?${suffix}` : ""}`);
}

export function getOpsNodeResult(nodeId: string, date?: string) {
  const query = new URLSearchParams();
  if (date) {
    query.set("date", date);
  }
  const suffix = query.toString();
  return fetchJson<OpsNodeResultPayload>(
    `/api/ops/node/${encodeURIComponent(nodeId)}${suffix ? `?${suffix}` : ""}`,
  );
}

export function getOpsDependencyPath(nodeIds: string[]) {
  const query = new URLSearchParams({ node_ids: nodeIds.join(",") });
  return fetchJson<OpsDependencyPathPayload>(`/api/ops/dependency-path?${query.toString()}`);
}

export function postOpsReplayPreview(payload: {
  selected_node_ids?: string[];
  selected_cells?: OpsSelectedCell[];
  date_from: string;
  date_to: string;
  mode: OpsReplayMode;
  action: OpsReplayAction;
}) {
  return fetchJson<OpsReplayPreviewPayload>("/api/ops/replay/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function postOpsReplayExecute(payload: {
  selected_node_ids?: string[];
  selected_cells?: OpsSelectedCell[];
  date_from: string;
  date_to: string;
  mode: OpsReplayMode;
  action: OpsReplayAction;
}) {
  return fetchJson<OpsReplayExecuteResponse>("/api/ops/replay/execute", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function getReadinessReplayPlan(dataset: string, dateFrom: string, dateTo?: string) {
  const query = new URLSearchParams({ dataset, date_from: dateFrom, date_to: dateTo || dateFrom });
  return fetchJson<ReplayPlanPayload>(`/api/readiness/replay-plan?${query.toString()}`);
}

export function getReadinessHistory(dataset?: string, date?: string) {
  const query = new URLSearchParams();
  if (dataset) {
    query.set("dataset", dataset);
  }
  if (date) {
    query.set("date", date);
  }
  return fetchJson<ReadinessHistoryPayload>(`/api/readiness/history?${query.toString()}`);
}

export function postReadinessBackfill(payload: {
  dataset: string;
  date_from: string;
  date_to: string;
  mode: "data_only" | "data_plus_downstream" | "full_replay";
}) {
  return fetchJson<ReadinessActionResponse>("/api/readiness/backfill", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function postReadinessReplay(payload: {
  dataset: string;
  date_from: string;
  date_to: string;
  mode: "data_only" | "data_plus_downstream" | "full_replay";
}) {
  return fetchJson<ReadinessActionResponse>("/api/readiness/replay", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function postReadinessDetectChanges(payload: {
  dataset: string;
  date_from: string;
  date_to: string;
}) {
  return fetchJson<ReadinessChangePayload>("/api/readiness/detect-changes", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function isTerminalRecoveryStatus(status?: string | null) {
  const normalized = String(status || "")
    .trim()
    .toLowerCase();
  return normalized === "ok" || normalized === "error";
}

export function isTerminalWorkflowStatus(status?: string | null) {
  return isTerminalRecoveryStatus(status);
}

export function extractRecoverySteps(action?: { result?: RecoveryActionResult | null } | null) {
  return Array.isArray(action?.result?.steps) ? action.result?.steps || [] : [];
}

export function getRecoveryProgress(action?: ReadinessActionDetail | null): RecoveryProgress {
  const steps = extractRecoverySteps(action);
  const plannedSteps = (action?.job_names || []).filter(Boolean);
  const totalSteps = Math.max(plannedSteps.length, steps.length);
  const completedSteps = steps.filter(
    (step) => String(step.status || "").toLowerCase() === "ok",
  ).length;
  const failedSteps = steps.filter(
    (step) => String(step.status || "").toLowerCase() === "error",
  ).length;

  let activeStep =
    steps.find((step) => {
      const status = String(step.status || "").toLowerCase();
      return status === "queued" || status === "running";
    }) || null;

  if (
    !activeStep &&
    action &&
    !isTerminalRecoveryStatus(action.status) &&
    plannedSteps.length > completedSteps
  ) {
    activeStep = {
      job_name: plannedSteps[completedSteps],
      status: String(action.status || "running").toLowerCase(),
      summary: null,
      duration_ms: null,
    };
  }

  return {
    totalSteps,
    completedSteps,
    failedSteps,
    steps,
    activeStep,
    progressRatio: totalSteps > 0 ? completedSteps / totalSteps : null,
  };
}

// ── Data observability types ────────────────────────────────────────────────

export type DataAssetHealth = "ok" | "stale" | "missing" | "error";

export type DataAsset = {
  asset_id: string;
  asset_class: string;
  symbol: string;
  venue: string;
  data_types: string[];
  total_rows: number;
  first_date: string | null;
  last_date: string | null;
  lag_days: number;
  health: DataAssetHealth;
};

export type DataAssetsPayload = {
  assets: DataAsset[];
  summary: {
    total_assets: number;
    ok: number;
    stale: number;
    missing: number;
    error?: number;
  };
};

export type KlineRow = {
  date: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  volume: number | null;
};

export type DataKlineSource = {
  channel: "published" | "observed";
  label: string;
  last_date?: string | null;
  published_last_date?: string | null;
  lifecycle_state?: string | null;
  quality_state?: string | null;
  freshness_state?: string | null;
  run_id?: string | null;
  reason_codes?: string[];
};

export type DataKlinePayload = {
  asset_id: string;
  symbol: string;
  interval: string;
  rows: KlineRow[];
  source?: DataKlineSource;
};

export type DataAssetObservability = {
  asset_id: string;
  status: "confirmed" | "unavailable";
  channel: "observed";
  last_date: string | null;
  published_last_date: string | null;
  lag_days: number | null;
  lifecycle_state: string | null;
  quality_state: string | null;
  freshness_state: string | null;
  run_id: string | null;
  reason_codes: string[];
  message?: string;
};

export type DataGap = {
  start: string;
  end: string;
  days: number;
};

export type DataGapsPayload = {
  asset_id: string;
  expected_dates: number;
  present_dates: number;
  coverage_pct: number;
  gaps: DataGap[];
  longest_gap_days: number;
};

export type NewsArticle = {
  title: string;
  source: string;
  published_at: string;
  url: string;
  sentiment_score: number | null;
  summary: string;
};

export type DataNewsPayload = {
  articles: NewsArticle[];
  total: number;
};

export type CoverageCell = {
  present: number;
  total: number;
  pct: number;
};

export type CoverageAssetClass = {
  name: string;
  total_assets: number;
  data_types: Record<string, CoverageCell>;
};

export type DataCoveragePayload = {
  asset_classes: CoverageAssetClass[];
};

// ── Data observability API helpers ──────────────────────────────────────────

export function getDataAssets() {
  return fetchJson<DataAssetsPayload>("/api/data/assets");
}

export function getDataKline(assetId: string, days = 30) {
  const query = new URLSearchParams({ days: String(days) });
  return fetchJson<DataKlinePayload>(
    `/api/data/kline/${encodeURIComponent(assetId)}?${query.toString()}`,
  );
}

export function getDataGaps(assetId: string) {
  return fetchJson<DataGapsPayload>(`/api/data/gaps/${encodeURIComponent(assetId)}`);
}

export function getDataNews(source = "", days = 3, limit = 30) {
  const query = new URLSearchParams({ days: String(days), limit: String(limit) });
  if (source) {
    query.set("source", source);
  }
  return fetchJson<DataNewsPayload>(`/api/data/news?${query.toString()}`);
}

export function getDataCoverage() {
  return fetchJson<DataCoveragePayload>("/api/data/coverage");
}

// ── BTC Observatory (WP4/WP5/WP8) ────────────────────────────────────────────
// Read-only surfaces over /api/v1/observatory/*. These types mirror the frozen
// backend contracts (openspec/changes/btc-observatory-research-lab-v1/
// frozen_contracts.md). Prices/volumes/ratios arrive as decimal-preserving
// STRINGS (never floats) and nullable fields are `null` — never 0/"".

export const OBS_ASSET_PATH = "crypto.BTC";
const OBS_BASE = `/api/v1/observatory/assets/${OBS_ASSET_PATH}`;

// Rollout capability/readiness (RA.1, docs/27 Phase A). The frontend uses this
// read-only probe to decide whether to advertise Observatory navigation. It is
// reachable even when the feature is disabled so nav and routes stay consistent.
export type ObsCapabilityState =
  "disabled" | "catalog_missing" | "catalog_stale" | "catalog_corrupt" | "ready" | "error";

export type ObsCapability = {
  enabled: boolean;
  state: ObsCapabilityState;
  show_nav: boolean;
  generation_id?: string | null;
  reason_code?: string;
};

export function observatoryCapabilityPath(): string {
  return `/api/v1/observatory/capability`;
}

export type ObsChannel = "formal" | "evaluated_candidate" | "observed";
export type ObsLens = "overview" | "trust" | "runs" | "research";
export type ObsAvailabilityState = "present" | "missing" | "unobserved" | "unknown";
export type ObsRevisionState = "unchanged" | "added" | "removed" | "changed" | "unknown";
export type ObsRenderRole =
  | "formal_baseline"
  | "candidate_overlap"
  | "candidate_only"
  | "observed_overlap"
  | "observed_only"
  | null;

export type ObsContract = {
  asset_id?: string;
  display_symbol?: string;
  contract_version?: string;
  primary_provider?: string;
  primary_instrument?: string;
  shadow_provider?: string;
  shadow_instrument?: string;
  quote?: string;
  primary_interval?: string;
  shadow_interval?: string;
};

export type ObsPurposeFitness = {
  purpose: string;
  allowed: boolean;
  status?: string;
  reason_codes?: string[];
  evidence_refs?: string[];
};

export type ObsArtifactRef = {
  name?: string;
  sha256?: string;
  relative_path?: string;
};

export type ObsExcludedDate = {
  date?: string;
  exclusion_reason?: string;
  quality_flags?: string[];
  evidence_refs?: string[];
  marker_position?: string | null;
};

export type ObsSemanticChannelRef = {
  run_id?: string;
  watermark?: string | null;
  release_id?: string | null;
  reason_codes?: string[];
};

export type ObsContext = {
  snapshot_id?: string;
  resolved_channel?: string;
  run_id?: string | null;
  release_id?: string | null;
  contract?: ObsContract;
  market_watermark?: string | null;
  input_watermarks?: Record<string, string | null>;
  output_watermark?: string | null;
  requested_knowledge_as_of?: string | null;
  effective_knowledge_cut?: string | null;
  relevant_fact_sequence?: number | null;
  knowledge_mode?: string;
  revision_policy?: string;
  pit_coverage_status?: string;
  created_at?: string | null;
  certified_at?: string | null;
  published_at?: string | null;
  rendered_at?: string | null;
  lifecycle_state?: string;
  quality_state?: string;
  freshness_state?: string;
  compatibility_state?: string;
  acquisition_state?: string;
  purpose_fitness?: ObsPurposeFitness[];
  artifact_refs?: ObsArtifactRef[];
  findings_summary?: Record<string, unknown>;
  excluded_dates?: ObsExcludedDate[];
  reason_codes?: string[];
  view_fingerprint?: string;
  etag?: string;
  evidence_coverage?: Record<string, unknown>;
  semantic_channels?: {
    formal?: ObsSemanticChannelRef;
    evaluated_candidate?: ObsSemanticChannelRef;
    observed?: ObsSemanticChannelRef;
  };
};

export type ObsSeriesRow = {
  date?: string;
  open?: string | null;
  high?: string | null;
  low?: string | null;
  close?: string | null;
  volume?: string | null;
  provider?: string | null;
  instrument?: string | null;
  quote?: string | null;
  available_at?: string | null;
  fetched_at?: string | null;
  source_run_id?: string | null;
  membership?: string[];
  availability_state?: ObsAvailabilityState;
  quality_flags?: string[];
  revision_state?: ObsRevisionState;
  render_role?: ObsRenderRole;
  metrics?: Record<string, unknown>;
};

export type ObsLayer = {
  channel?: string;
  context?: ObsContext;
  rows?: ObsSeriesRow[];
} | null;

export type ObsCompositeSeries = {
  view: "composite";
  asset_id?: string;
  etag?: string;
  fingerprint_basis?: string;
  layers?: {
    formal?: ObsLayer;
    evaluated_candidate?: ObsLayer;
    latest_observed?: ObsLayer;
  };
  reason_codes?: string[];
  view_fingerprint?: string;
};

export type ObsSingleSeries = {
  view: string;
  context?: ObsContext;
  rows?: ObsSeriesRow[];
  pit_valid?: boolean;
  reason_codes?: string[];
  view_fingerprint?: string;
  etag?: string;
};

export type ObsDateEvidence = {
  date?: string;
  snapshot_id?: string;
  run_id?: string | null;
  ohlcv?: ObsSeriesRow | null;
  reconciliation?: Record<string, string | null> | null;
  revision?: Record<string, string | null> | null;
  run_lineage?: string[];
  research_visibility?: "not_visible" | "pending" | "matured";
  reason_codes?: string[];
};

export type ObsGate = {
  gate?: string;
  status?: string;
  reason_code?: string | null;
  detail?: string | null;
  metrics?: Record<string, unknown> | null;
};

export type ObsFinding = {
  finding_id?: string;
  gate?: string;
  severity?: string;
  reason_code?: string | null;
  affected_dates?: string[];
  evidence_refs?: string[];
};

export type ObsTrust = {
  snapshot_id?: string;
  run_id?: string | null;
  gates?: ObsGate[];
  findings?: ObsFinding[];
  acquisition_state?: string;
  quality_state?: string;
};

export type ObsRunSummary = {
  run_id?: string;
  created_at?: string | null;
  market_watermark?: string | null;
  data_readiness?: string | null;
  quality_state?: string;
  lifecycle_state?: string;
  canonical_rows?: number | null;
};

export type ObsRunsPayload = {
  runs?: ObsRunSummary[];
  next_cursor?: string | null;
  catalog_fingerprint?: string;
};

export type ObsRunDetail = ObsRunSummary & {
  acquisition_state?: string;
  code_revision?: string | null;
  artifact_refs?: Array<{ name?: string; sha256?: string }>;
  gates?: ObsGate[];
};

export type ObsRunDiffSide = {
  run_id?: string;
  watermark?: string | null;
  canonical_rows?: number | null;
  canonical_hash?: string | null;
  code_revision?: string | null;
  config_hash?: string | null;
  schema_hash?: string | null;
};

export type ObsRunDiff = {
  base?: ObsRunDiffSide;
  compare?: ObsRunDiffSide;
  added_dates?: string[];
  removed_dates?: string[];
  changed_dates?: Array<{ date?: string; base_close?: string; compare_close?: string }>;
  gate_changes?: Record<string, { base?: unknown; compare?: unknown }>;
  code_changed?: boolean;
  config_changed?: boolean;
  schema_changed?: boolean;
};

export type ObsHypothesis = {
  hypothesis_id?: string;
  hypothesis_version?: string;
  statement?: string;
  directional?: boolean;
  research_state?: string;
  current_research_run_id?: string | null;
};

export type ObsHypothesesPayload = {
  hypotheses?: ObsHypothesis[];
};

export type ObsResearchRun = {
  research_run_id?: string;
  hypothesis_id?: string;
  hypothesis_version?: string;
  validation_run_id?: string | null;
  generation_id?: string | null;
  dataset_snapshot_id?: string | null;
  knowledge_as_of?: string | null;
  research_state?: string;
  is_current?: boolean;
  metrics?: Record<string, string | null>;
  evidence_refs?: string[];
};

export type ObsErrorPayload = {
  reason_codes?: string[];
  message?: string;
  evidence_refs?: string[];
  retryable?: boolean;
};

function obsQuery(params: Record<string, string | undefined | null>): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      query.set(key, value);
    }
  }
  const suffix = query.toString();
  return suffix ? `?${suffix}` : "";
}

export function observatoryContextPath(opts: {
  channel?: ObsChannel;
  knowledgeAsOf?: string;
  snapshotId?: string;
  runId?: string;
}): string {
  return `${OBS_BASE}/context${obsQuery({
    channel: opts.channel,
    knowledge_as_of: opts.knowledgeAsOf,
    snapshot_id: opts.snapshotId,
    run_id: opts.runId,
  })}`;
}

export function observatorySeriesPath(opts: {
  view?: "composite" | ObsChannel;
  knowledgeAsOf?: string;
  includeQuarantined?: boolean;
  from?: string;
  to?: string;
  snapshotId?: string;
  runId?: string;
}): string {
  return `${OBS_BASE}/series${obsQuery({
    view: opts.view,
    knowledge_as_of: opts.knowledgeAsOf,
    include_quarantined: opts.includeQuarantined ? "true" : undefined,
    from: opts.from,
    to: opts.to,
    snapshot_id: opts.snapshotId,
    run_id: opts.runId,
  })}`;
}

function dateLagDays(value: string | null | undefined): number | null {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return null;
  }
  const parsed = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== value) {
    return null;
  }
  const today = new Date();
  const todayUtc = Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate());
  return Math.floor((todayUtc - parsed.getTime()) / 86_400_000);
}

function decimalStringToNumber(value: string | null | undefined): number | null {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function observedRowToKline(row: ObsSeriesRow): KlineRow | null {
  const date = String(row.date || "");
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || row.availability_state !== "present") {
    return null;
  }
  return {
    date,
    open: decimalStringToNumber(row.open),
    high: decimalStringToNumber(row.high),
    low: decimalStringToNumber(row.low),
    close: decimalStringToNumber(row.close),
    volume: decimalStringToNumber(row.volume),
  };
}

function klineWindowStart(days: number): string {
  const safeDays = Math.max(1, Math.min(intLike(days, 30), 3650));
  const start = new Date();
  start.setUTCDate(start.getUTCDate() - safeDays * 2);
  return start.toISOString().slice(0, 10);
}

function intLike(value: number, fallback: number): number {
  if (!Number.isFinite(value)) {
    return fallback;
  }
  return Math.trunc(value);
}

export async function getBtcDataObservability(): Promise<DataAssetObservability> {
  try {
    const context = await fetchJson<ObsContext>(
      observatoryContextPath({ channel: "observed", knowledgeAsOf: "latest" }),
    );
    const lastDate =
      context.market_watermark ||
      context.output_watermark ||
      context.semantic_channels?.observed?.watermark ||
      null;
    return {
      asset_id: OBS_ASSET_PATH,
      status: "confirmed",
      channel: "observed",
      last_date: lastDate,
      published_last_date: context.semantic_channels?.formal?.watermark || null,
      lag_days: dateLagDays(lastDate),
      lifecycle_state: context.lifecycle_state || null,
      quality_state: context.quality_state || null,
      freshness_state: context.freshness_state || null,
      run_id: context.run_id || null,
      reason_codes: context.reason_codes || [],
    };
  } catch (error) {
    return {
      asset_id: OBS_ASSET_PATH,
      status: "unavailable",
      channel: "observed",
      last_date: null,
      published_last_date: null,
      lag_days: null,
      lifecycle_state: null,
      quality_state: null,
      freshness_state: null,
      run_id: null,
      reason_codes: [],
      message: error instanceof Error ? error.message : "BTC observed status is unavailable.",
    };
  }
}

export async function getBtcObservedKline(days = 30): Promise<DataKlinePayload> {
  const safeDays = Math.max(1, Math.min(intLike(days, 30), 3650));
  const series = await fetchJson<ObsSingleSeries>(
    observatorySeriesPath({
      view: "observed",
      knowledgeAsOf: "latest",
      from: klineWindowStart(safeDays),
    }),
  );
  const rows = (series.rows || [])
    .map(observedRowToKline)
    .filter((row): row is KlineRow => row !== null)
    .sort((left, right) => left.date.localeCompare(right.date))
    .slice(-safeDays);
  const context = series.context;
  const lastDate = rows[rows.length - 1]?.date || context?.market_watermark || null;
  return {
    asset_id: OBS_ASSET_PATH,
    symbol: context?.contract?.display_symbol || "BTC",
    interval: context?.contract?.primary_interval || "1d",
    rows,
    source: {
      channel: "observed",
      label: "Observed BTC",
      last_date: lastDate,
      published_last_date: context?.semantic_channels?.formal?.watermark || null,
      lifecycle_state: context?.lifecycle_state || null,
      quality_state: context?.quality_state || null,
      freshness_state: context?.freshness_state || null,
      run_id: context?.run_id || null,
      reason_codes: series.reason_codes || context?.reason_codes || [],
    },
  };
}

export function getDataKlineForAsset(assetId: string, days = 30): Promise<DataKlinePayload> {
  return assetId === OBS_ASSET_PATH ? getBtcObservedKline(days) : getDataKline(assetId, days);
}

export function observatoryDatePath(
  marketDate: string,
  opts: { channel?: ObsChannel; snapshotId?: string } = {},
): string {
  return `${OBS_BASE}/dates/${encodeURIComponent(marketDate)}${obsQuery({
    channel: opts.channel,
    snapshot_id: opts.snapshotId,
  })}`;
}

export function observatoryTrustPath(
  opts: { channel?: ObsChannel; snapshotId?: string } = {},
): string {
  return `${OBS_BASE}/trust${obsQuery({ channel: opts.channel, snapshot_id: opts.snapshotId })}`;
}

export function observatoryRunsPath(opts: { cursor?: string; limit?: number } = {}): string {
  return `${OBS_BASE}/runs${obsQuery({
    cursor: opts.cursor,
    limit: opts.limit ? String(opts.limit) : undefined,
  })}`;
}

export function observatoryRunDetailPath(runId: string): string {
  return `/api/v1/observatory/runs/${encodeURIComponent(runId)}`;
}

export function observatoryRunDiffPath(base: string, compare: string): string {
  return `/api/v1/observatory/runs/diff${obsQuery({ base, compare })}`;
}

export function observatoryHypothesesPath(): string {
  return `${OBS_BASE}/hypotheses`;
}

export function observatoryResearchRunPath(researchRunId: string): string {
  return `/api/v1/observatory/research-runs/${encodeURIComponent(researchRunId)}`;
}
