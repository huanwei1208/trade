import { useEffect, useState } from "react";

export type Locale = "zh-CN" | "en-US";
export type PageKey = "today" | "candidates" | "symbol" | "ops";
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
  recent_runs?: Array<{ job_name?: string; status?: string; started_at?: string; result_summary?: string }>;
};

export type SignalsPageData = {
  as_of?: string;
  picks?: CandidateRow[];
  dropped?: Array<{ symbol?: string }>;
  total?: number;
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
  due_agenda?: Array<Record<string, unknown>>;
  planned_events?: Array<Record<string, unknown>>;
  backups?: Array<Record<string, unknown>>;
  backup_health?: Record<string, unknown>;
};

export type DagRuntime = {
  nodes?: Array<Record<string, unknown>>;
  edges?: Array<Record<string, unknown>>;
  stage_summary?: Record<string, { total?: number; running?: number; error?: number; ok?: number; disabled?: number }>;
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

export type ReadinessStatus = "READY" | "LATE_READY" | "PARTIAL" | "MISSING" | "CHANGED" | "REPLAYING" | "REPLAYED" | "UNKNOWN";

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
      datasets?: Array<{ dataset: string; label: string; status: ReadinessStatus; affected_outputs?: string[] }>;
      constrained?: boolean;
    };
  };
  datasets: Array<{ key: string; label: string; critical: boolean; job_name?: string | null; affected_outputs?: string[] }>;
  rows: ReadinessRow[];
  recovery_history?: Record<string, ReadinessHistoryItem[]>;
};

export type ReplayPlanPayload = {
  dataset: string;
  label: string;
  job_name?: string | null;
  recommended_mode: "data_only" | "data_plus_downstream" | "full_replay";
  affected_outputs?: string[];
  downstream_nodes?: Array<{ job_name?: string; stage?: string; enabled?: boolean; avg_duration_ms?: number | null }>;
  full_chain?: Array<{ job_name?: string; stage?: string; enabled?: boolean; avg_duration_ms?: number | null }>;
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
      (typeof payload === "object" && payload && "detail" in payload && typeof payload.detail === "string" && payload.detail) ||
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

export function getSignalsPage() {
  return fetchJson<SignalsPageData>("/api/signals-page");
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

export function getDagRuntime() {
  return fetchJson<DagRuntime>("/api/dag/runtime");
}

export function getDataHealth() {
  return fetchJson<DataHealthPayload>("/api/data-health");
}

export function getWorkflows() {
  return fetchJson<WorkflowSummary[]>("/api/workflows");
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

export function postReadinessBackfill(payload: { dataset: string; date_from: string; date_to: string; mode: "data_only" | "data_plus_downstream" | "full_replay" }) {
  return fetchJson<ReadinessActionResponse>("/api/readiness/backfill", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function postReadinessReplay(payload: { dataset: string; date_from: string; date_to: string; mode: "data_only" | "data_plus_downstream" | "full_replay" }) {
  return fetchJson<ReadinessActionResponse>("/api/readiness/replay", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function postReadinessDetectChanges(payload: { dataset: string; date_from: string; date_to: string }) {
  return fetchJson<ReadinessChangePayload>("/api/readiness/detect-changes", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function isTerminalRecoveryStatus(status?: string | null) {
  const normalized = String(status || "").trim().toLowerCase();
  return normalized === "ok" || normalized === "error";
}

export function extractRecoverySteps(action?: { result?: RecoveryActionResult | null } | null) {
  return Array.isArray(action?.result?.steps) ? action.result?.steps || [] : [];
}

export function getRecoveryProgress(action?: ReadinessActionDetail | null): RecoveryProgress {
  const steps = extractRecoverySteps(action);
  const plannedSteps = (action?.job_names || []).filter(Boolean);
  const totalSteps = Math.max(plannedSteps.length, steps.length);
  const completedSteps = steps.filter((step) => String(step.status || "").toLowerCase() === "ok").length;
  const failedSteps = steps.filter((step) => String(step.status || "").toLowerCase() === "error").length;

  let activeStep =
    steps.find((step) => {
      const status = String(step.status || "").toLowerCase();
      return status === "queued" || status === "running";
    }) || null;

  if (!activeStep && action && !isTerminalRecoveryStatus(action.status) && plannedSteps.length > completedSteps) {
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
