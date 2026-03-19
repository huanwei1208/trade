import ELK from "elkjs/lib/elk.bundled.js";
import { useEffect, useMemo, useRef, useState } from "react";
import type { MouseEvent as ReactMouseEvent, ReactNode } from "react";

type Locale = "zh-CN" | "en";
type PageKey = "today" | "candidates" | "symbol" | "ops";
type EventsViewKey = "market" | "dag";
type GraphNodeKind = "task" | "topic";

type SignalPick = {
  symbol?: string;
  name?: string;
  status?: "new" | "continued";
  adj_score?: number;
  model_score?: number;
  window_score?: number;
  event_kg_score?: number;
  net_sentiment?: number;
  event_type?: string;
  model_risk?: number;
  industry?: number;
  date?: string;
};

// ── EBRT types ──────────────────────────────────────────────────────────────

type TrustGate = {
  operational_status?: "ok" | "degraded" | "blocked" | string;
  research_status?: "ok" | "partial" | "blocked" | string;
  brier_score?: number | null;
  drift_mmd?: number | null;
  eval_date?: string;
  freshness?: Array<{ dataset: string; lag_days?: number | null; status?: string }>;
};

type EBRTPick = SignalPick & {
  action?: "buy" | "sell" | "watch" | "avoid" | string;
  conviction?: "high" | "mid" | "low" | string;
  score?: number;
  risk?: number;
  belief_mu?: number;
  belief_sigma?: number;
  belief_delta_mu?: number;
  reasons?: Array<{ description: string; weight?: number; evidence_type?: string }>;
  top_evidence?: Array<{ weight?: number; evidence_id?: string }>;
};

type TodayPage = {
  as_of?: string;
  pipeline_health?: {
    total: number;
    ok: number;
    error: number;
    running: number;
    status: string;
  };
  top_picks?: (SignalPick | EBRTPick)[];
  dropped_picks?: { symbol: string }[];
  gate_status?: string;
  gate_reason?: string;
  kline_last_date?: string;
  trust_gate?: TrustGate;
  error_nodes?: Array<{ job_name?: string; status?: string }>;
  recent_runs?: Array<{ job_name?: string; status?: string; started_at?: string; result_summary?: string }>;
  // EBRT_06 enrichment
  today_thesis?: string;
  market_regime?: string;
  blockers?: string[];
  top_actions?: CandidateRow[];
};

type SignalsPage = {
  as_of?: string;
  picks?: CandidateRow[];
  dropped?: { symbol: string }[];
  total?: number;
  source?: "ebrt" | "signals";
};

type KlineBar = {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

type KlineData = {
  symbol?: string;
  name?: string;
  ohlcv?: KlineBar[];
  indicators?: {
    rsi_14?: number;
    vol_ratio?: number;
    dist_52w_low?: number;
  };
  recommendation?: {
    conviction?: string;
    bullish_dims?: number;
    reasons?: string[];
    hist_event_stats?: {
      event_type?: string;
      hist_count?: number;
      hist_ret_5d_avg?: number | null;
    };
  };
  event_markers?: Array<{ date: string; event_type: string; magnitude: number; kg_score: number }>;
  latest_signal?: {
    model_score?: number;
    window_score?: number;
    event_kg_score?: number;
    net_sentiment?: number;
  };
  belief_overlay?: Array<{ date: string; mu: number; sigma: number; delta_mu?: number | null }>;
  ebrt_recommendation?: {
    action?: string;
    conviction?: string;
    score?: number;
    risk?: number;
    belief_mu?: number;
    belief_sigma?: number;
    belief_delta_mu?: number | null;
    reasons?: Array<{ description: string; weight?: number; evidence_type?: string }>;
  };
  explanation?: DecisionExplanation;
};

// ── EBRT_06 types ────────────────────────────────────────────────────────────
type EvidenceItem = {
  source?: string;
  direction?: string;
  strength?: number;
  description?: string;
  weight?: number;
};

type DecisionExplanation = {
  symbol?: string;
  as_of?: string;
  action?: string;
  action_confidence?: number;
  thesis?: string;
  world_state_summary?: string;
  state_rationale?: string;
  trust?: {
    trust_level?: string;
    trust_scalar?: number;
    trust_components?: Record<string, number>;
  };
  evidence_for?: EvidenceItem[];
  evidence_against?: EvidenceItem[];
  invalidators?: string[];
  next_triggers?: string[];
  scenario_summary?: string;
  warnings?: string[];
  data_quality_notes?: string[];
  input_warnings?: string[];
};

type CandidateRow = {
  symbol?: string;
  name?: string;
  action?: string;
  confidence?: number;
  score?: number;
  risk?: number;
  thesis?: string;
  trust_score?: number;
  trust_level?: string;
  world_state_summary?: string;
  top_invalidators?: string[];
  // legacy fields kept for backward compat
  status?: string;
  adj_score?: number;
  model_score?: number;
  window_score?: number;
  event_kg_score?: number;
  net_sentiment?: number;
  belief_mu?: number;
  belief_sigma?: number;
  belief_delta_mu?: number | null;
  reasons?: Array<{ description: string; weight?: number; evidence_type?: string }>;
  top_evidence?: Array<{ weight?: number; evidence_id?: string }>;
};

type DagNode = {
  id?: number;
  dag_id?: number;
  job_name?: string;
  stage?: string;
  source?: string;
  emits?: string;
  status?: string;
  enabled?: number;
  sync_source?: string;
  sync_dataset?: string;
  config_json?: string;
  mode?: string;
  error_detail?: string;
  error?: string;
  result_summary?: string;
  recent_ok_count?: number;
  recent_error_count?: number;
  last_run?: { id?: number; started_at?: string; completed_at?: string; result_summary?: string; elapsed_ms?: number | null; status?: string } | null;
  last_source_event?: { created_at?: string; status?: string } | null;
  job_run?: { started_at?: string; completed_at?: string; result_summary?: string; status?: string } | null;
  source_event?: { topic?: string; status?: string; payload_json?: Record<string, any>; created_at?: string } | null;
};

type DagEdge = { from: string; to: string; kind?: string };

type GraphNode = {
  key: string;
  kind: GraphNodeKind;
  label: string;
  subtitle: string;
  status: string;
  detail: string;
  stage: string;
  x: number;
  y: number;
  width: number;
  height: number;
  dagId?: number;
};

type GraphEdge = {
  key: string;
  from: string;
  to: string;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  status: string;
  points?: Array<{ x: number; y: number }>;
};

type DagLayout = {
  width: number;
  height: number;
  levels: Array<{ depth: number; label: string; x: number; width: number }>;
  nodes: GraphNode[];
  edges: GraphEdge[];
};

type PositionOverrideMap = Record<string, { x: number; y: number }>;

type Dict = Record<string, string>;

const I18N: Record<Locale, Dict> = {
  "zh-CN": {
    title: "TradeDB",
    subtitle: "今日 / 候选 / 运营",
    language: "语言",
    refresh: "刷新",
    today: "今日",
    picks: "选股",
    candidates: "候选",
    ops: "运营",
    symbol: "标的",
    pipeline: "流水线",
    topPicks: "今日推荐",
    droppedPicks: "跌出推荐",
    newTag: "新",
    continuedTag: "持续",
    klineDays: "K线日期",
    modelScore: "模型分",
    windowScore: "窗口分",
    kgScore: "事件分",
    conviction: "确信度",
    reasons: "推荐理由",
    configNode: "配置节点",
    backfillNode: "回补",
    execTime: "执行时间",
    dataDate: "数据日期",
    saveConfig: "保存配置",
    confirmBackfill: "确认回补",
    cancel: "取消",
    report: "报表",
    events: "事件",
    kg: "KG",
    loading: "加载中...",
    noData: "暂无数据",
    operational: "运营态",
    research: "研究态",
    overall: "总体",
    reason: "结论",
    rootCauses: "根因",
    topSignals: "重点信号",
    modelSignals: "模型分",
    kgSignals: "事件 KG 分",
    todayEvents: "今日事件",
    plannedEvents: "未来事件",
    recentEvents: "最近事件流",
    dataHealth: "数据健康",
    workflowProgress: "流程进度",
    runActions: "运行操作",
    runSync: "全量同步",
    runClose: "收盘链路",
    runEvening: "晚间链路",
    runAgenda: "派发 Agenda",
    workflows: "工作流",
    dagRuntime: "DAG 运行态",
    dagGraph: "DAG 视图",
    workflowDag: "工作流 DAG",
    globalDag: "全局 DAG",
    workflowHistory: "历史工作流",
    finalResults: "最终事件结果",
    failedNodes: "失败节点",
    rerun: "重跑节点",
    execute: "执行",
    rerunUpstream: "补前继链路",
    rerunDownstream: "续跑后继链路",
    rerunFull: "整条链路重跑",
    source: "来源",
    stage: "阶段",
    status: "状态",
    progress: "进度",
    error: "错误",
    agenda: "Agenda",
    focusWorkflow: "当前工作流",
    activeGraph: "当前图谱",
    activeRelations: "已上线边",
    topPropagation: "传播最多标的",
    relationTypes: "边类型分布",
    snapshot: "快照",
    generatedAt: "生成时间",
    nodeDetail: "节点详情",
    execution: "执行信息",
    replayLineage: "重跑链路",
    sourceEvent: "源事件",
    selectNode: "选择一个节点",
    selectNodeHint: "点击 DAG 节点后，可在这里查看详情、错误摘要和重跑操作。",
    latestRun: "最近运行",
    upstream: "上游",
    downstream: "下游",
    counts: "统计",
    noRootCause: "当前没有明显根因，最近工作流基本健康。",
    dailyEvents: "每日事件流",
    liveWorkflows: "运行中的工作流",
    failedCount: "失败节点数",
    agendaCount: "待执行 Agenda",
    eventCount: "事件数",
    focusHint: "点击 DAG 节点查看详情；失败节点可直接重跑并续跑下游。",
    restoreState: "页面状态已自动恢复",
    dragHint: "节点可拖拽调整位置，布局会保存在本地。",
    liveStatus: "实时状态",
    connected: "已连接",
    disconnected: "已断开",
    connecting: "连接中",
    lastUpdate: "最后刷新",
    runtimeProgress: "运行进度",
    marketView: "行情 / 事件",
    dagView: "DAG",
    autoLayout: "自动排版",
  },
  en: {
    title: "TradeDB",
    subtitle: "Today / Candidates / Ops",
    language: "Language",
    refresh: "Refresh",
    today: "Today",
    picks: "Picks",
    candidates: "Candidates",
    ops: "Ops",
    symbol: "Symbol",
    pipeline: "Pipeline",
    topPicks: "Top Picks",
    droppedPicks: "Dropped Picks",
    newTag: "New",
    continuedTag: "Cont.",
    klineDays: "K-line Date",
    modelScore: "Model",
    windowScore: "Window",
    kgScore: "KG",
    conviction: "Conviction",
    reasons: "Reasons",
    configNode: "Config Node",
    backfillNode: "Backfill",
    execTime: "Exec Time",
    dataDate: "Data Date",
    saveConfig: "Save Config",
    confirmBackfill: "Confirm Backfill",
    cancel: "Cancel",
    report: "Report",
    events: "Events",
    kg: "KG",
    loading: "Loading...",
    noData: "No data",
    operational: "Operational",
    research: "Research",
    overall: "Overall",
    reason: "Conclusion",
    rootCauses: "Root causes",
    topSignals: "Top signals",
    modelSignals: "Model score",
    kgSignals: "Event KG score",
    todayEvents: "Today events",
    plannedEvents: "Planned events",
    recentEvents: "Recent event stream",
    dataHealth: "Data health",
    workflowProgress: "Workflow progress",
    runActions: "Run actions",
    runSync: "Run sync",
    runClose: "Run close",
    runEvening: "Run evening",
    runAgenda: "Run agenda",
    workflows: "Workflows",
    dagRuntime: "DAG runtime",
    dagGraph: "DAG view",
    workflowDag: "Workflow DAG",
    globalDag: "Global DAG",
    workflowHistory: "Workflow history",
    finalResults: "Final outcomes",
    failedNodes: "Failed nodes",
    rerun: "Rerun node",
    execute: "Run",
    rerunUpstream: "Backfill upstream chain",
    rerunDownstream: "Continue downstream chain",
    rerunFull: "Replay full workflow",
    source: "Source",
    stage: "Stage",
    status: "Status",
    progress: "Progress",
    error: "Error",
    agenda: "Agenda",
    focusWorkflow: "Focused workflow",
    activeGraph: "Active graph",
    activeRelations: "Active relations",
    topPropagation: "Top propagated symbols",
    relationTypes: "Relation types",
    snapshot: "Snapshot",
    generatedAt: "Generated at",
    nodeDetail: "Node detail",
    execution: "Execution",
    replayLineage: "Replay lineage",
    sourceEvent: "Source event",
    selectNode: "Select a node",
    selectNodeHint: "Click a DAG node to inspect details, error summary, and replay actions here.",
    latestRun: "Latest run",
    upstream: "Upstream",
    downstream: "Downstream",
    counts: "Counts",
    noRootCause: "No major blocker right now. Recent workflows are mostly healthy.",
    dailyEvents: "Daily event stream",
    liveWorkflows: "Running workflows",
    failedCount: "Failed nodes",
    agendaCount: "Due agenda",
    eventCount: "Event count",
    focusHint: "Click a DAG node to inspect it; failed nodes can be rerun with downstream continuation.",
    restoreState: "Page state was restored automatically",
    dragHint: "Nodes are draggable; the layout is saved locally.",
    liveStatus: "Live status",
    connected: "Connected",
    disconnected: "Disconnected",
    connecting: "Connecting",
    lastUpdate: "Last update",
    runtimeProgress: "Runtime progress",
    marketView: "Market / Events",
    dagView: "DAG",
    autoLayout: "Auto layout",
  },
};

type TranslationKey = keyof (typeof I18N)["zh-CN"];

const PAGES: Array<{ key: PageKey; label: TranslationKey }> = [
  { key: "today", label: "today" },
  { key: "candidates", label: "candidates" },
  { key: "ops", label: "ops" },
];

const ELK_LAYOUT = new ELK();

function statusClass(status: unknown) {
  const value = String(status || "unknown").toLowerCase();
  if (["ok", "done", "active"].includes(value)) return "ok";
  if (["running", "live"].includes(value)) return "running";
  if (["partial"].includes(value)) return "partial";
  if (["error", "failed", "degraded", "blocked_by_dependency"].includes(value)) return "error";
  return "pending";
}

async function apiFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json() as Promise<T>;
}

function formatDateTime(value: unknown) {
  if (!value) return "-";
  return String(value).slice(0, 19);
}

function shortText(value: unknown, limit = 120) {
  const text = String(value || "").trim();
  if (!text) return "-";
  return text.length > limit ? `${text.slice(0, limit)}…` : text;
}

function slugStage(value: unknown) {
  return String(value || "unknown").trim() || "unknown";
}

function stageTitle(value: unknown) {
  const text = String(value || "").trim();
  if (!text) return "Unknown";
  return text
    .split(/[_\-.]/g)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function estimateNodeBox(parts: Array<string | undefined>, kind: GraphNodeKind) {
  const content = parts.filter(Boolean).join(" ");
  const longest = Math.max(...parts.map((part) => String(part || "").length), 0);
  const total = content.length;
  const width = Math.max(
    kind === "topic" ? 208 : 232,
    Math.min(kind === "topic" ? 280 : 348, 180 + longest * 4.6),
  );
  const charsPerLine = Math.max(20, Math.floor((width - 44) / 7));
  const estimatedLines = Math.max(
    kind === "topic" ? 2 : 3,
    Math.ceil(total / charsPerLine),
  );
  const height = Math.max(
    kind === "topic" ? 72 : 108,
    Math.min(kind === "topic" ? 132 : 180, 56 + estimatedLines * 18),
  );
  return { width, height };
}

async function buildDagLayout(
  rows: DagNode[],
  rawEdges: DagEdge[],
  focusDagIds?: Set<number>,
  overrides?: PositionOverrideMap,
): Promise<DagLayout> {
  const padX = 36;
  const padY = 56;
  const topicNodes = new Map<string, GraphNode>();
  const taskNodes = new Map<string, GraphNode>();
  const emittedByTopic = new Map<string, GraphNode[]>();
  const predecessors = new Map<string, Set<string>>();
  const successors = new Map<string, Set<string>>();

  for (const row of rows) {
    const dagId = Number(row.dag_id ?? row.id ?? 0) || undefined;
    const key = `task:${dagId ?? row.job_name ?? Math.random().toString(36)}`;
    const stage = slugStage(row.stage);
    const taskBox = estimateNodeBox(
      [
        String(row.job_name || row.stage || "task"),
        `${row.stage || "-"} · ${row.source || "-"}`,
        String(row.error_detail || row.error || row.result_summary || row.last_run?.result_summary || ""),
      ],
      "task",
    );
    const taskNode: GraphNode = {
      key,
      kind: "task",
      label: String(row.job_name || row.stage || "task"),
      subtitle: `${row.stage || "-"} · ${row.source || "-"}`,
      status: String(row.status || "unknown"),
      detail: String(row.error_detail || row.error || row.result_summary || row.last_run?.result_summary || ""),
      stage,
      x: 0,
      y: 0,
      width: taskBox.width,
      height: taskBox.height,
      dagId,
    };
    taskNodes.set(key, taskNode);
    predecessors.set(key, predecessors.get(key) || new Set());
    successors.set(key, successors.get(key) || new Set());
    if (row.emits) {
      const topic = String(row.emits);
      const current = emittedByTopic.get(topic) || [];
      current.push(taskNode);
      emittedByTopic.set(topic, current);
    }
  }

  const edges: Array<{ from: string; to: string }> = [];
  const edgeKeys = new Set<string>();
  const addEdge = (from: string, to: string) => {
    const key = `${from}->${to}`;
    if (edgeKeys.has(key) || from === to) return;
    edgeKeys.add(key);
    edges.push({ from, to });
    predecessors.set(to, new Set([...(predecessors.get(to) || []), from]));
    successors.set(from, new Set([...(successors.get(from) || []), to]));
  };

  const findTaskNodeByJobName = (jobName: string) => {
    for (const node of taskNodes.values()) {
      if (node.label === jobName) return node;
    }
    return null;
  };

  for (const row of rows) {
    const dagId = Number(row.dag_id ?? row.id ?? 0) || undefined;
    const taskKey = `task:${dagId ?? row.job_name ?? "unknown"}`;
    const sourceTopic = String(row.source || "");
    if (sourceTopic) {
      const upstream = emittedByTopic.get(sourceTopic) || [];
      if (upstream.length) {
        for (const node of upstream) addEdge(node.key, taskKey);
      } else {
        const topicKey = `topic:${sourceTopic}`;
        if (!topicNodes.has(topicKey)) {
          const topicBox = estimateNodeBox(
            [sourceTopic, "trigger/topic"],
            "topic",
          );
          topicNodes.set(topicKey, {
            key: topicKey,
            kind: "topic",
            label: sourceTopic,
            subtitle: "trigger/topic",
            status: String(row.last_source_event?.status || "pending"),
            detail: "",
            stage: "source",
            x: 0,
            y: 0,
            width: topicBox.width,
            height: topicBox.height,
            dagId: undefined,
          });
          predecessors.set(topicKey, predecessors.get(topicKey) || new Set());
          successors.set(topicKey, successors.get(topicKey) || new Set());
        }
        addEdge(topicKey, taskKey);
      }
    }
  }

  for (const edge of rawEdges || []) {
    if (edge.kind !== "source") continue;
    const fromTask = findTaskNodeByJobName(String(edge.from || ""));
    const toTask = findTaskNodeByJobName(String(edge.to || ""));
    if (fromTask && toTask) addEdge(fromTask.key, toTask.key);
  }

  const allNodes = [...topicNodes.values(), ...taskNodes.values()];
  const elkGraph = {
    id: "root",
    layoutOptions: {
      "elk.algorithm": "layered",
      "elk.direction": "RIGHT",
      "elk.spacing.nodeNode": "42",
      "elk.layered.spacing.nodeNodeBetweenLayers": "124",
      "elk.spacing.edgeNode": "28",
      "elk.layered.crossingMinimization.strategy": "LAYER_SWEEP",
      "elk.layered.nodePlacement.strategy": "NETWORK_SIMPLEX",
      "elk.padding": `[top=${padY},left=${padX},bottom=${padY},right=${padX}]`,
    },
    children: allNodes.map((node) => ({
      id: node.key,
      width: node.width,
      height: node.height,
    })),
    edges: edges.map((edge) => ({
      id: `${edge.from}->${edge.to}`,
      sources: [edge.from],
      targets: [edge.to],
    })),
  };
  const layoutGraph = await ELK_LAYOUT.layout(elkGraph as any);
  const layoutNodes = new Map(
    (layoutGraph.children || []).map((item: any) => [
      String(item.id),
      { x: Number(item.x || 0), y: Number(item.y || 0) },
    ]),
  );
  const layoutEdges = new Map(
    (layoutGraph.edges || []).map((item: any) => [
      String(item.id),
      item,
    ]),
  );

  const roots = allNodes
    .filter((node) => (predecessors.get(node.key)?.size || 0) === 0)
    .sort((a, b) => a.label.localeCompare(b.label));
  const depthByNode = new Map<string, number>();
  const queue = [...roots.map((node) => node.key)];
  for (const key of queue) depthByNode.set(key, 0);
  while (queue.length) {
    const current = queue.shift()!;
    const currentDepth = depthByNode.get(current) || 0;
    for (const next of successors.get(current) || []) {
      const proposed = currentDepth + 1;
      if ((depthByNode.get(next) ?? -1) < proposed) {
        depthByNode.set(next, proposed);
      }
      queue.push(next);
    }
  }
  for (const node of allNodes) {
    if (!depthByNode.has(node.key)) depthByNode.set(node.key, 0);
  }

  const levelsMap = new Map<number, GraphNode[]>();
  let maxRight = 0;
  let maxBottom = 0;
  for (const node of allNodes) {
    const layoutNode = layoutNodes.get(node.key);
    const override = overrides?.[node.key];
    node.x = override?.x ?? (layoutNode?.x ?? padX);
    node.y = override?.y ?? (layoutNode?.y ?? padY);
    const depth = depthByNode.get(node.key) || 0;
    const bucket = levelsMap.get(depth) || [];
    bucket.push(node);
    levelsMap.set(depth, bucket);
    maxRight = Math.max(maxRight, node.x + node.width);
    maxBottom = Math.max(maxBottom, node.y + node.height);
  }

  const levelKeys = Array.from(levelsMap.keys()).sort((a, b) => a - b);
  const levels = levelKeys.map((depth, index) => {
    const bucket = levelsMap.get(depth) || [];
    const taskStages = Array.from(new Set(bucket.filter((node) => node.kind === "task").map((node) => node.stage)));
    const label = bucket.every((node) => node.kind === "topic")
      ? "Sources"
      : taskStages.length === 1
      ? stageTitle(taskStages[0])
      : taskStages.length
      ? taskStages.slice(0, 2).map((value) => stageTitle(value)).join(" / ")
      : `Layer ${index + 1}`;
    const left = Math.min(...bucket.map((node) => node.x));
    const right = Math.max(...bucket.map((node) => node.x + node.width));
    return {
      depth,
      label,
      x: left,
      width: Math.max(232, right - left),
    };
  });

  const width = Math.max(980, Math.ceil(maxRight + padX));
  const height = Math.max(420, Math.ceil(maxBottom + padY));
  const graphEdges: GraphEdge[] = edges
    .map((edge) => {
      const from = allNodes.find((node) => node.key === edge.from);
      const to = allNodes.find((node) => node.key === edge.to);
      if (!from || !to) return null;
      const status = to.status === "error" || from.status === "error" ? "error" : (to.status === "running" || from.status === "running" ? "running" : "ok");
      const edgeLayout = layoutEdges.get(`${edge.from}->${edge.to}`) as { sections?: Array<any> } | undefined;
      const section = edgeLayout?.sections?.[0];
      const points = section
        ? [
            section.startPoint,
            ...(section.bendPoints || []),
            section.endPoint,
          ].map((point: any) => ({ x: Number(point.x || 0), y: Number(point.y || 0) }))
        : undefined;
      return {
        key: `${edge.from}->${edge.to}`,
        from: edge.from,
        to: edge.to,
        x1: from.x + from.width,
        y1: from.y + from.height / 2,
        x2: to.x,
        y2: to.y + to.height / 2,
        status,
        points,
      };
    })
    .filter(Boolean) as GraphEdge[];

  return { width, height, levels, nodes: allNodes, edges: graphEdges };
}

function App() {
  const [locale, setLocale] = useState<Locale>((localStorage.getItem("trade_locale") as Locale) || "zh-CN");
  const [page, setPage] = useState<PageKey>(() => {
    const stored = localStorage.getItem("trade_page") as PageKey;
    // Migrate old page names after rename
    if (stored === "picks" as string) return "candidates";
    if (stored === "pipeline" as string) return "ops";
    if (["today", "candidates", "ops"].includes(stored)) return stored;
    return "today";
  });
  const [eventsPage, setEventsPage] = useState<any>(null);
  const [todayData, setTodayData] = useState<TodayPage | null>(null);
  const [signalsData, setSignalsData] = useState<SignalsPage | null>(null);
  const [signalsError, setSignalsError] = useState<string | null>(null);
  const [pipelineHover, setPipelineHover] = useState<string | null>(null);
  const [pipelineHoverPos, setPipelineHoverPos] = useState<{ x: number; y: number }>({ x: 0, y: 0 });
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);
  const [klineData, setKlineData] = useState<KlineData | null>(null);
  const [klineLoading, setKlineLoading] = useState(false);
  // EBRT_06: symbol page navigation
  const [symbolTarget, setSymbolTarget] = useState<string | null>(null);
  const [symbolName, setSymbolName] = useState<string | null>(null);
  const [symbolPrevPage, setSymbolPrevPage] = useState<"today" | "candidates">("today");
  const [symbolKline, setSymbolKline] = useState<KlineData | null>(null);
  const [symbolExplain, setSymbolExplain] = useState<DecisionExplanation | null>(null);
  const [symbolLoading, setSymbolLoading] = useState(false);
  // EBRT_06: candidates page
  const [candidateFilter, setCandidateFilter] = useState<"ALL" | "ADD" | "PROBE" | "WATCH">("ALL");
  const [candidateSidePick, setCandidateSidePick] = useState<CandidateRow | null>(null);
  const [configPanelDagId, setConfigPanelDagId] = useState<number | null>(null);
  const [configPanelValue, setConfigPanelValue] = useState<string>("{}");
  const [backfillDagId, setBackfillDagId] = useState<number | null>(null);
  const [backfillFrom, setBackfillFrom] = useState<string>("");
  const [backfillTo, setBackfillTo] = useState<string>("");
  const [workflowDetail, setWorkflowDetail] = useState<any>(null);
  const [selectedDagKey, setSelectedDagKey] = useState<string>("");
  const [eventsView, setEventsView] = useState<EventsViewKey>(
    (localStorage.getItem("trade_events_view") as EventsViewKey) || "market",
  );
  const [selectedWorkflowId, setSelectedWorkflowId] = useState<number | null>(() => {
    const raw = localStorage.getItem("trade_events_selected_workflow");
    return raw ? Number(raw) || null : null;
  });
  const [graphOverrides, setGraphOverrides] = useState<Record<string, PositionOverrideMap>>(() => {
    try {
      return JSON.parse(localStorage.getItem("trade_graph_positions") || "{}");
    } catch {
      return {};
    }
  });
  const [globalGraph, setGlobalGraph] = useState<DagLayout>({ width: 980, height: 420, levels: [], nodes: [], edges: [] });
  const [toast, setToast] = useState("");
  const [loading, setLoading] = useState<Record<string, boolean>>({});
  const [streamState, setStreamState] = useState<{
    scope: string;
    status: "connecting" | "connected" | "disconnected";
    lastUpdate: string | null;
    sequence: number;
  }>({ scope: "report", status: "connecting", lastUpdate: null, sequence: 0 });
  const [streamRetryTick, setStreamRetryTick] = useState(0);
  const refreshTimerRef = useRef<number | null>(null);
  const streamRetryTimerRef = useRef<number | null>(null);
  const flyoutTimerRef = useRef<number | null>(null);
  const pipelineHoverTimerRef = useRef<number | null>(null);
  const [pinnedDagKey, setPinnedDagKey] = useState<string>("");

  const t = (key: TranslationKey) => I18N[locale][key];
  const workflowRows: DagNode[] = workflowDetail?.nodes || [];
  const focusDagIds = useMemo(
    () => new Set(workflowRows.map((row) => Number(row.dag_id ?? row.id ?? 0)).filter(Boolean)),
    [workflowRows],
  );
  const globalGraphKey = useMemo(
    () => `global:${eventsPage?.as_of || "events"}`,
    [eventsPage?.as_of],
  );
  const selectedGlobalGraphNode = globalGraph.nodes.find((node) => node.key === selectedDagKey) || null;

  useEffect(() => {
    localStorage.setItem("trade_locale", locale);
  }, [locale]);

  useEffect(() => {
    localStorage.setItem("trade_page", page);
  }, [page]);

  useEffect(() => {
    localStorage.setItem("trade_events_view", eventsView);
  }, [eventsView]);

  useEffect(() => {
    if (selectedWorkflowId != null) {
      localStorage.setItem("trade_events_selected_workflow", String(selectedWorkflowId));
    }
  }, [selectedWorkflowId]);

  useEffect(() => {
    localStorage.setItem("trade_graph_positions", JSON.stringify(graphOverrides));
  }, [graphOverrides]);

  useEffect(() => {
    let cancelled = false;
    void buildDagLayout(
      (eventsPage?.dag?.nodes || []) as DagNode[],
      (eventsPage?.dag?.edges || []) as DagEdge[],
      focusDagIds,
      graphOverrides[globalGraphKey] || {},
    ).then((layout) => {
      if (!cancelled) setGlobalGraph(layout);
    });
    return () => {
      cancelled = true;
    };
  }, [eventsPage?.dag?.nodes, eventsPage?.dag?.edges, focusDagIds, graphOverrides, globalGraphKey]);

  useEffect(() => {
    void loadTodayData();
  }, []);

  useEffect(() => {
    if (page === "today" && !todayData) void loadTodayData();
    if (page === "candidates" && !signalsData) void loadSignalsData();
    if (page === "ops" && !eventsPage) void loadEvents();
  }, [page]);

  useEffect(() => {
    if (page !== "today" && page !== "ops") return;
    const scope = page === "today" ? "report" : "events";
    setStreamState((prev) => ({
      scope,
      status: "connecting",
      lastUpdate: prev.scope === scope ? prev.lastUpdate : null,
      sequence: prev.sequence,
    }));
    const source = new EventSource(`/api/runtime/stream?scope=${scope}`);
    source.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        setStreamState((prev) => ({
          scope,
          status: "connected",
          lastUpdate: String(payload?.ts || new Date().toISOString()),
          sequence: prev.sequence + 1,
        }));
        if (refreshTimerRef.current) window.clearTimeout(refreshTimerRef.current);
        refreshTimerRef.current = window.setTimeout(() => {
          if (page === "ops") {
            void loadEvents();
          } else {
            void loadTodayData();
          }
        }, 350);
      } catch {
        // ignore malformed rows
      }
    };
    source.onerror = () => {
      setStreamState((prev) => ({
        ...prev,
        scope,
        status: "disconnected",
      }));
      source.close();
      if (streamRetryTimerRef.current) {
        window.clearTimeout(streamRetryTimerRef.current);
      }
      streamRetryTimerRef.current = window.setTimeout(() => {
        setStreamRetryTick((value) => value + 1);
      }, 1500);
    };
    return () => {
      source.close();
      if (refreshTimerRef.current) {
        window.clearTimeout(refreshTimerRef.current);
        refreshTimerRef.current = null;
      }
      if (streamRetryTimerRef.current) {
        window.clearTimeout(streamRetryTimerRef.current);
        streamRetryTimerRef.current = null;
      }
    };
  }, [page, streamRetryTick]);

  useEffect(() => {
    if (page !== "ops") return;
    const handle = window.setInterval(() => {
      void loadEvents();
    }, 15000);
    return () => window.clearInterval(handle);
  }, [page, selectedWorkflowId]);

  useEffect(() => {
    if (!workflowDetail?.nodes?.length) {
      setSelectedDagKey("");
      setPinnedDagKey("");
      return;
    }
    const preferred = workflowDetail.nodes.find((node: any) => String(node.status || "") === "error") || workflowDetail.nodes[0];
    setSelectedDagKey(`task:${preferred.dag_id ?? preferred.id ?? preferred.job_name}`);
    setPinnedDagKey("");
  }, [workflowDetail?.root_event_id]);

  useEffect(() => () => {
    if (refreshTimerRef.current) {
      window.clearTimeout(refreshTimerRef.current);
    }
    if (streamRetryTimerRef.current) {
      window.clearTimeout(streamRetryTimerRef.current);
    }
    if (flyoutTimerRef.current) {
      window.clearTimeout(flyoutTimerRef.current);
    }
  }, []);

  function pushToast(message: string) {
    setToast(message);
    window.setTimeout(() => setToast(""), 2400);
  }

  function clearFlyoutTimer() {
    if (flyoutTimerRef.current) {
      window.clearTimeout(flyoutTimerRef.current);
      flyoutTimerRef.current = null;
    }
  }

  function openDagFlyout(nodeKey: string) {
    clearFlyoutTimer();
    setSelectedDagKey(nodeKey);
  }

  function scheduleDagFlyoutClose() {
    clearFlyoutTimer();
    if (pinnedDagKey) return;
    flyoutTimerRef.current = window.setTimeout(() => {
      setSelectedDagKey("");
    }, 140);
  }

  function togglePinnedFlyout(nodeKey: string) {
    clearFlyoutTimer();
    setPinnedDagKey((current) => {
      if (current === nodeKey) {
        return "";
      }
      setSelectedDagKey(nodeKey);
      return nodeKey;
    });
  }

  async function loadEvents() {
    setLoading((prev) => ({ ...prev, events: true }));
    try {
      const payload = await apiFetch<any>("/api/events-page");
      setEventsPage(payload);
      const workflows = payload?.workflows || [];
      const remembered = selectedWorkflowId && workflows.some((row: any) => Number(row.root_event_id) === selectedWorkflowId)
        ? selectedWorkflowId
        : null;
      if (remembered) {
        await loadWorkflowDetail(remembered, { silent: true });
      } else {
        const focus = payload?.focus || null;
        setWorkflowDetail(focus);
        setSelectedWorkflowId(focus?.root_event_id ? Number(focus.root_event_id) : null);
      }
    } finally {
      setLoading((prev) => ({ ...prev, events: false }));
    }
  }

  async function loadTodayData() {
    setLoading((prev) => ({ ...prev, today: true }));
    try {
      const data = await apiFetch<TodayPage>("/api/today-page");
      setTodayData(data);
    } finally {
      setLoading((prev) => ({ ...prev, today: false }));
    }
  }

  async function loadSignalsData() {
    setLoading((prev) => ({ ...prev, signals: true }));
    setSignalsError(null);
    try {
      const data = await apiFetch<SignalsPage>("/api/signals-page");
      setSignalsData(data);
    } catch (err) {
      setSignalsError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading((prev) => ({ ...prev, signals: false }));
    }
  }

  async function loadKlineData(symbol: string) {
    setKlineLoading(true);
    setSelectedSymbol(symbol);
    try {
      const data = await apiFetch<KlineData>(`/api/kline/${symbol}?days=60`);
      setKlineData(data);
    } finally {
      setKlineLoading(false);
    }
  }

  async function navigateSymbol(symbol: string, name: string | undefined, from: "today" | "candidates") {
    setSymbolTarget(symbol);
    setSymbolName(name || null);
    setSymbolPrevPage(from);
    setSymbolKline(null);
    setSymbolExplain(null);
    setSymbolLoading(true);
    setPage("symbol");
    try {
      const [kline, explain] = await Promise.allSettled([
        apiFetch<KlineData>(`/api/kline/${symbol}?days=90`),
        apiFetch<DecisionExplanation>(`/api/explain/${symbol}`),
      ]);
      if (kline.status === "fulfilled") setSymbolKline(kline.value);
      if (explain.status === "fulfilled") setSymbolExplain(explain.value);
    } finally {
      setSymbolLoading(false);
    }
  }

  async function saveConfig(dagId: number) {
    try {
      const config = JSON.parse(configPanelValue);
      await apiFetch(`/api/dag/${dagId}/config`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ config }),
      });
      setConfigPanelDagId(null);
      alert("配置已保存");
    } catch (e) {
      alert(`保存失败: ${e}`);
    }
  }

  async function runBackfill(dagId: number) {
    if (!backfillFrom || !backfillTo) {
      alert("请选择日期范围");
      return;
    }
    await apiFetch(`/api/dag/${dagId}/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        mode: "self",
        date_from: backfillFrom,
        date_to: backfillTo,
      }),
    });
    setBackfillDagId(null);
    alert(`回补任务已提交: ${backfillFrom} ~ ${backfillTo}`);
  }

  async function loadWorkflowDetail(rootEventId: number, options?: { silent?: boolean }) {
    if (!options?.silent) {
      setLoading((prev) => ({ ...prev, workflow: true }));
    }
    try {
      setWorkflowDetail(await apiFetch(`/api/workflows/${rootEventId}`));
      setSelectedWorkflowId(rootEventId);
    } finally {
      if (!options?.silent) {
        setLoading((prev) => ({ ...prev, workflow: false }));
      }
    }
  }

  async function runTarget(target: string) {
    await apiFetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target, payload: {}, limit: 10 }),
    });
    pushToast(`${t("runActions")}: ${target}`);
    if (page === "ops") void loadEvents();
    if (page === "today") void loadTodayData();
  }

  async function rerunNode(rootEventId: number, dagId: number, mode: "self" | "upstream" | "downstream" | "full" = "self") {
    await apiFetch(`/api/workflows/${rootEventId}/rerun-node`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dag_id: dagId, mode }),
    });
    pushToast(`${t("rerun")}: ${dagId} · ${mode}`);
    await loadEvents();
    await loadTodayData();
  }

  async function runDagNode(dagId: number, mode: "self" | "upstream" | "downstream" | "full" = "self") {
    await apiFetch(`/api/dag/${dagId}/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode, payload: {} }),
    });
    pushToast(`run: ${dagId} · ${mode}`);
    await loadEvents();
    await loadTodayData();
  }

  function updateGraphNodePosition(graphKey: string, nodeKey: string, x: number, y: number) {
    setGraphOverrides((prev) => ({
      ...prev,
      [graphKey]: {
        ...(prev[graphKey] || {}),
        [nodeKey]: { x, y },
      },
    }));
  }

  function resetGraphLayout(graphKey: string) {
    setGraphOverrides((prev) => {
      if (!(graphKey in prev)) return prev;
      const next = { ...prev };
      delete next[graphKey];
      return next;
    });
  }

  async function refreshCurrent() {
    if (page === "today") return loadTodayData();
    if (page === "candidates") return loadSignalsData();
    if (page === "ops") return loadEvents();
    if (page === "symbol" && symbolTarget) return navigateSymbol(symbolTarget, symbolName || undefined, symbolPrevPage);
    return loadTodayData();
  }

  function CandlestickChart({ bars }: { bars: KlineBar[] }) {
    const last30 = bars.slice(-30);
    if (!last30.length) return <div className="chart-empty">无K线数据</div>;
    const width = 450, height = 180, padX = 20, padY = 10;
    const highs = last30.map((b) => b.high).filter((v) => v > 0);
    const lows = last30.map((b) => b.low).filter((v) => v > 0);
    if (!highs.length) return null;
    const maxH = Math.max(...highs);
    const minL = Math.min(...lows);
    const rangeH = maxH - minL || 1;
    const scaleY = (v: number) => padY + ((maxH - v) / rangeH) * (height - padY * 2);
    const barW = Math.max(2, Math.floor((width - padX * 2) / last30.length) - 1);
    return (
      <svg width={width} height={height} className="candlestick-chart">
        {last30.map((bar, i) => {
          const x = padX + i * ((width - padX * 2) / last30.length);
          const isUp = bar.close >= bar.open;
          const color = isUp ? "#22c55e" : "#ef4444";
          const bodyTop = scaleY(Math.max(bar.open, bar.close));
          const bodyBot = scaleY(Math.min(bar.open, bar.close));
          const bodyH = Math.max(1, bodyBot - bodyTop);
          return (
            <g key={i}>
              <line x1={x + barW / 2} y1={scaleY(bar.high)} x2={x + barW / 2} y2={scaleY(bar.low)} stroke={color} strokeWidth="1" />
              <rect x={x} y={bodyTop} width={barW} height={bodyH} fill={color} opacity={0.85} />
            </g>
          );
        })}
      </svg>
    );
  }

  function renderSignals(rows: any[], scoreKey: string) {
    if (!rows?.length) return <div className="empty">{t("noData")}</div>;
    return (
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Score</th>
              <th>Window</th>
              <th>Event</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={`${scoreKey}-${row.date}-${row.symbol}`}>
                <td>{row.symbol}</td>
                <td>{row[scoreKey] ?? "-"}</td>
                <td>{row.window_score ?? "-"}</td>
                <td>{row.event_type || "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  function renderToday() {
    if (loading.today && !todayData) return <div className="empty">{t("loading")}</div>;
    if (!todayData) return <div className="empty">{t("noData")}</div>;
    const ph = todayData.pipeline_health;
    const errorNodes = todayData.error_nodes || [];
    const topPicks = todayData.top_picks || [];
    const topActions = todayData.top_actions || [];
    const droppedPicks = todayData.dropped_picks || [];
    const phStatus = ph ? (ph.error > 0 ? "error" : ph.running > 0 ? "running" : "ok") : "unknown";
    const newCount = topPicks.filter(p => p.status === "new").length;
    const blockers = todayData.blockers || [];
    const thesis = todayData.today_thesis || "";
    const regime = todayData.market_regime || "";
    const tg = todayData.trust_gate;
    const tStar: number | null = (tg as any)?.trust_scalar ?? null;
    const tStarClass = tStar == null ? "" : tStar >= 0.7 ? "trust-ok" : tStar >= 0.5 ? "trust-warn" : "trust-err";

    return (
      <div className="today-page">
        {/* ── Decision header row ── */}
        <div className="today-decision-header">
          {regime && (
            <span className="today-regime-pill">{regime}</span>
          )}
          {tStar != null && (
            <span className={`trust-scalar-badge ${tStarClass}`}>T*={tStar.toFixed(2)}</span>
          )}
          <span className="today-as-of">{todayData.as_of || ""}</span>
        </div>

        {/* ── Thesis ── */}
        {thesis && (
          <div className="today-thesis">{thesis}</div>
        )}

        {/* ── Blockers strip ── */}
        {blockers.length > 0 && (
          <div className="today-blocker-strip">
            <span className="today-blocker-label">⚠ 阻断</span>
            {blockers.map((b, i) => (
              <span key={i} className="today-blocker-item">{b}</span>
            ))}
          </div>
        )}

        {/* ── Stat strip ── */}
        <div className="today-stat-strip">
          <div className="today-stat">
            <div className="today-stat-label">数据截至</div>
            <div className="today-stat-value">{todayData.kline_last_date || "—"}</div>
          </div>
          <div className={`today-stat today-stat-${phStatus}`}>
            <div className="today-stat-label">流水线</div>
            <div className="today-stat-value">{ph ? `${ph.ok} / ${ph.total}` : "—"}</div>
            <div className="today-stat-sub">
              {ph?.error ? <span style={{ color: "var(--err)" }}>{ph.error} 失败</span> : "全部正常"}
            </div>
          </div>
          <div className="today-stat">
            <div className="today-stat-label">质量门控</div>
            <div className={`today-stat-value today-gate-${statusClass(todayData.gate_status || "unknown")}`}>
              {todayData.gate_status || "—"}
            </div>
            {todayData.gate_reason ? (
              <div className="today-stat-sub">{shortText(todayData.gate_reason, 32)}</div>
            ) : null}
          </div>
          <div className="today-stat">
            <div className="today-stat-label">今日推荐</div>
            <div className="today-stat-value">{topPicks.length > 0 ? `${topPicks.length} 支` : "—"}</div>
            <div className="today-stat-sub">{newCount > 0 ? `${newCount} 支新上榜` : "无新上榜"}</div>
          </div>
        </div>

        {/* ── EBRT Trust Gate ── */}
        {todayData.trust_gate && (todayData.trust_gate.operational_status || todayData.trust_gate.research_status) && (() => {
          const tg = todayData.trust_gate!;
          const opStatus = tg.operational_status || "unknown";
          const resStatus = tg.research_status || "unknown";
          const opClass = opStatus === "ok" ? "trust-ok" : opStatus === "degraded" ? "trust-warn" : "trust-err";
          const resClass = resStatus === "ok" ? "trust-ok" : resStatus === "partial" ? "trust-warn" : "trust-err";
          const fresh = tg.freshness || [];
          const tStar: number | null = (tg as any).trust_scalar ?? null;
          const tComp: Record<string, number> = (tg as any).trust_components || {};
          const tStarClass = tStar == null ? "" : tStar >= 0.7 ? "trust-ok" : tStar >= 0.5 ? "trust-warn" : "trust-err";
          const compLabels: Record<string, string> = {
            fresh: "新鲜", evidence: "证据", model: "模型",
            calib: "校准", drift: "漂移", ops: "运营", explain: "解释",
          };
          return (
            <div className="trust-gate-wrap">
              <div className="trust-gate-bar">
                <span className="trust-gate-title">Trust Gate</span>
                {tStar != null && (
                  <span className={`trust-scalar-badge ${tStarClass}`}>T*={tStar.toFixed(2)}</span>
                )}
                <span className={`trust-badge ${opClass}`}>运营 {opStatus}</span>
                <span className={`trust-badge ${resClass}`}>研究 {resStatus}</span>
                {tg.brier_score != null && (
                  <span className="trust-metric">Brier: {tg.brier_score.toFixed(3)}</span>
                )}
                {tg.drift_mmd != null && (
                  <span className="trust-metric">Drift: {tg.drift_mmd.toFixed(3)}</span>
                )}
                {fresh.length > 0 && (
                  <span className="trust-freshness">
                    {fresh.map(f => (
                      <span key={f.dataset} className={`trust-fresh-item trust-fresh-${f.status || "unknown"}`}>
                        {f.dataset} {f.lag_days != null ? `${f.lag_days}d` : "?"}
                      </span>
                    ))}
                  </span>
                )}
              </div>
              {Object.keys(tComp).length > 0 && (
                <div className="trust-components-row">
                  {Object.entries(compLabels).map(([k, label]) => {
                    const val = tComp[k] ?? 0;
                    const pct = Math.round(val * 100);
                    const cls = val >= 0.7 ? "trust-comp-ok" : val >= 0.5 ? "trust-comp-warn" : "trust-comp-err";
                    return (
                      <div key={k} className="trust-component-item">
                        <span className="trust-comp-label">{label}</span>
                        <div className="trust-comp-bar-bg">
                          <div className={`trust-comp-bar-fill ${cls}`} style={{ width: `${pct}%` }} />
                        </div>
                        <span className="trust-comp-val">{val.toFixed(2)}</span>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })()}

        {/* ── Error alert ── */}
        {errorNodes.length > 0 && (
          <div className="today-alert-strip">
            <span className="today-alert-label">⚠ 失败节点</span>
            {errorNodes.map((node, idx) => (
              <span key={idx} className="today-alert-node">{node.job_name || "unknown"}</span>
            ))}
          </div>
        )}

        {/* ── Action cards (EBRT_06 enriched) or legacy picks ── */}
        <div className="today-picks-panel">
          <div className="today-picks-header">
            <span className="today-section-title">{t("topPicks")}</span>
            <span className="today-section-date">{todayData.as_of || ""}</span>
            <button type="button" className="today-picks-all-btn" onClick={() => setPage("candidates")}>
              查看全部 →
            </button>
          </div>
          {topActions.length > 0 ? (
            /* EBRT_06 enriched action cards */
            <div className="today-action-cards">
              {topActions.map((pick, idx) => {
                const action = pick.action || "";
                const conf = pick.confidence ?? 0;
                const trust = pick.trust_score ?? 0;
                const trustCls = trust >= 0.7 ? "trust-ok" : trust >= 0.5 ? "trust-warn" : "trust-err";
                return (
                  <div
                    key={idx}
                    className="today-action-card"
                    onClick={() => pick.symbol && void navigateSymbol(pick.symbol, pick.name, "today")}
                  >
                    <div className="today-action-card-top">
                      <span className={`action-chip action-chip-${action.toLowerCase()}`}>{action || "—"}</span>
                      <span className={`trust-badge ${trustCls}`} style={{ fontSize: "10px" }}>T*={trust.toFixed(2)}</span>
                    </div>
                    <div className="today-action-card-symbol">{pick.symbol}</div>
                    <div className="today-action-card-name">{pick.name || "—"}</div>
                    <div className="today-action-card-conf">
                      <div className="today-pick-bar" style={{ flex: 1 }}>
                        <div className="today-pick-bar-fill" style={{ width: `${Math.round(conf * 100)}%` }} />
                      </div>
                      <span style={{ fontSize: "11px", color: "var(--muted)", minWidth: 32 }}>{Math.round(conf * 100)}%</span>
                    </div>
                    {pick.thesis && (
                      <div className="today-action-card-thesis">{shortText(pick.thesis, 60)}</div>
                    )}
                    {(pick.top_invalidators || []).length > 0 && (
                      <div className="today-action-card-inv">
                        {(pick.top_invalidators || []).map((inv, ii) => (
                          <span key={ii} className="today-inv-chip">{inv}</span>
                        ))}
                      </div>
                    )}
                    <div className="today-action-card-arrow">→</div>
                  </div>
                );
              })}
            </div>
          ) : topPicks.length > 0 ? (
            /* Legacy pick list */
            <div className="today-pick-list">
              {topPicks.map((pick, idx) => {
                const ep = pick as EBRTPick;
                const isEbrt = ep.action != null || ep.belief_mu != null;
                const rawScore = ep.score ?? pick.adj_score ?? pick.model_score ?? 0;
                const barPct = Math.min(rawScore > 1 ? rawScore : rawScore * 100, 100);
                const action = ep.action || "";
                const dmu = ep.belief_delta_mu;
                return (
                  <div
                    key={idx}
                    className="today-pick-card"
                    onClick={() => {
                      if (pick.symbol) void navigateSymbol(pick.symbol, pick.name, "today");
                    }}
                  >
                    <div className="today-pick-rank">#{idx + 1}</div>
                    <div className="today-pick-badge-wrap">
                      {isEbrt && action ? (
                        <span className={`today-pick-action action-${action}`}>{action}</span>
                      ) : pick.status === "new" ? (
                        <span className="badge-new">{t("newTag")}</span>
                      ) : (
                        <span className="badge-continued">{t("continuedTag")}</span>
                      )}
                    </div>
                    <div className="today-pick-identity">
                      <span className="today-pick-symbol">{pick.symbol}</span>
                      <span className="today-pick-name">{pick.name || "—"}</span>
                    </div>
                    <div className="today-pick-bar-wrap">
                      <div className="today-pick-bar">
                        <div className="today-pick-bar-fill" style={{ width: `${barPct}%` }} />
                      </div>
                      <span className="today-pick-score">
                        {rawScore > 1 ? rawScore.toFixed(1) : rawScore.toFixed(2)}
                      </span>
                    </div>
                    {isEbrt && ep.belief_mu != null ? (
                      <div className="today-pick-belief">
                        <span className="belief-mu-val">μ {ep.belief_mu >= 0 ? "+" : ""}{ep.belief_mu.toFixed(3)}</span>
                        {dmu != null && (
                          <span className={dmu >= 0 ? "belief-delta-pos" : "belief-delta-neg"}>
                            Δ{dmu >= 0 ? "+" : ""}{dmu.toFixed(3)}
                          </span>
                        )}
                        {ep.belief_sigma != null && (
                          <span className="belief-sigma-val">σ={ep.belief_sigma.toFixed(2)}</span>
                        )}
                      </div>
                    ) : (
                      <div className="today-pick-metrics">
                        {pick.model_score != null && (
                          <span className="today-pick-chip">
                            模 {pick.model_score > 1 ? pick.model_score.toFixed(0) : pick.model_score.toFixed(2)}
                          </span>
                        )}
                        {pick.window_score != null && (
                          <span className="today-pick-chip">技 {Math.round(pick.window_score)}</span>
                        )}
                        {pick.net_sentiment != null && (
                          <span className={`today-pick-chip ${pick.net_sentiment >= 0 ? "chip-pos" : "chip-neg"}`}>
                            情 {pick.net_sentiment >= 0 ? "+" : ""}{pick.net_sentiment.toFixed(2)}
                          </span>
                        )}
                      </div>
                    )}
                    <button
                      type="button"
                      className="today-pick-detail-btn"
                      onClick={e => {
                        e.stopPropagation();
                        if (pick.symbol) void navigateSymbol(pick.symbol, pick.name, "today");
                      }}
                    >
                      详情 →
                    </button>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="empty">{t("noData")}</div>
          )}
          {droppedPicks.length > 0 && (
            <div className="today-dropped">
              <span className="today-dropped-label">今日跌出</span>
              {droppedPicks.map((item, idx) => (
                <span key={idx} className="badge-dropped">{item.symbol}</span>
              ))}
            </div>
          )}
        </div>

        {/* ── Recent runs (compact, collapsed) ── */}
        {(todayData.recent_runs || []).length > 0 && (
          <details className="today-runs-details">
            <summary className="today-runs-summary">
              最近运行 ({(todayData.recent_runs || []).length})
            </summary>
            <div className="today-runs-list">
              {(todayData.recent_runs || []).map((run, idx) => (
                <div key={idx} className="today-run-row">
                  <span className="today-run-job">{run.job_name || "—"}</span>
                  <span className={`pill ${statusClass(run.status)}`} style={{ fontSize: "10px" }}>{run.status}</span>
                  <span className="today-run-time">{formatDateTime(run.started_at)}</span>
                  <span className="today-run-summary">{shortText(run.result_summary, 80)}</span>
                </div>
              ))}
            </div>
          </details>
        )}
      </div>
    );
  }

  function renderCandidates() {
    if (loading.signals && !signalsData) return <div className="empty">{t("loading")}</div>;
    if (signalsError) return (
      <div className="empty" style={{ color: "var(--err)", whiteSpace: "pre-wrap", padding: "20px 24px" }}>
        <strong>候选数据加载失败</strong><br />{signalsError}
      </div>
    );
    if (!signalsData) return <div className="empty">{t("noData")}</div>;
    const allPicks: CandidateRow[] = signalsData.picks || [];
    const isEbrtSource = signalsData.source === "ebrt";
    // EBRT_06: action filter
    const FILTER_ACTIONS = ["ALL", "ADD", "PROBE", "WATCH"] as const;
    const visiblePicks = candidateFilter === "ALL"
      ? allPicks
      : allPicks.filter(p => (p.action || "").toUpperCase() === candidateFilter);
    const hasEnrichedAction = allPicks.some(p => p.action);
    const sidePick = candidateSidePick;

    return (
      <div className="candidates-layout">
        {/* ── Action filter pills ── */}
        {hasEnrichedAction && (
          <div className="cand-filter-row">
            {FILTER_ACTIONS.map(f => (
              <button
                key={f}
                type="button"
                className={`cand-filter-pill${candidateFilter === f ? " active" : ""}`}
                onClick={() => setCandidateFilter(f)}
              >
                {f}
              </button>
            ))}
          </div>
        )}

        <div className="candidates-body">
          {/* ── Table ── */}
          <div className="picks-table-wrap">
            <table className="picks-table">
              <thead>
                <tr className="picks-ebrt-header">
                  <th>代码</th>
                  <th>名称</th>
                  <th>操作</th>
                  <th>确信度</th>
                  <th>Trust</th>
                  <th>论点</th>
                  <th>否决因子</th>
                </tr>
              </thead>
              <tbody>
                {visiblePicks.map((pick, idx) => {
                  const action = pick.action || (pick as EBRTPick).action || "";
                  const conf = pick.confidence ?? 0;
                  const trust = pick.trust_score ?? 0;
                  const trustCls = trust >= 0.7 ? "trust-ok" : trust >= 0.5 ? "trust-warn" : "trust-err";
                  const isSelected = candidateSidePick?.symbol === pick.symbol;
                  return (
                    <tr
                      key={idx}
                      className={`clickable-row${isSelected ? " selected" : ""}`}
                      onClick={() => setCandidateSidePick(isSelected ? null : pick)}
                    >
                      <td style={{ fontWeight: 600, fontSize: "13px" }}>{pick.symbol || "-"}</td>
                      <td>{pick.name || "-"}</td>
                      <td>
                        {action ? (
                          <span className={`action-chip action-chip-${action.toLowerCase()}`}>{action}</span>
                        ) : (pick as EBRTPick).conviction ? (
                          <span className={`conviction-badge conviction-${(pick as EBRTPick).conviction || ""}`}>
                            {(pick as EBRTPick).conviction}
                          </span>
                        ) : pick.status === "new" ? (
                          <span className="badge-new">{t("newTag")}</span>
                        ) : "-"}
                      </td>
                      <td>
                        {conf > 0 ? (
                          <span style={{ fontSize: "12px" }}>{Math.round(conf * 100)}%</span>
                        ) : (pick as EBRTPick).score != null ? (
                          <span style={{ fontSize: "12px" }}>{(pick as EBRTPick).score!.toFixed(3)}</span>
                        ) : "-"}
                      </td>
                      <td>
                        {trust > 0 ? (
                          <span className={`trust-badge ${trustCls}`} style={{ fontSize: "10px" }}>{trust.toFixed(2)}</span>
                        ) : "-"}
                      </td>
                      <td style={{ maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontSize: "11px", color: "var(--muted)" }}>
                        {shortText(pick.thesis || pick.world_state_summary || (pick as EBRTPick).belief_mu != null ? `μ=${(pick as EBRTPick).belief_mu?.toFixed(3)}` : "", 60)}
                      </td>
                      <td style={{ fontSize: "11px", color: "var(--muted)" }}>
                        {(pick.top_invalidators || []).slice(0, 2).join(", ") || "-"}
                      </td>
                    </tr>
                  );
                })}
                {!visiblePicks.length && (
                  <tr><td colSpan={7} className="empty">{t("noData")}</td></tr>
                )}
              </tbody>
            </table>
          </div>

          {/* ── Side panel ── */}
          <div className="picks-side-panel">
            {!sidePick ? (
              <div style={{ color: "var(--muted)", fontSize: "13px", marginTop: 20, textAlign: "center" }}>
                点击左侧表格行查看摘要
              </div>
            ) : (
              <div>
                <div className="kline-panel-header">
                  <span className="sym-name">{sidePick.name || sidePick.symbol}</span>
                  <span className="sym-code">{sidePick.symbol}</span>
                </div>
                {sidePick.action && (
                  <div style={{ display: "flex", alignItems: "center", gap: 8, margin: "8px 0", flexWrap: "wrap" }}>
                    <span className={`action-chip action-chip-${(sidePick.action || "").toLowerCase()}`}>{sidePick.action}</span>
                    {sidePick.confidence != null && (
                      <span className="ind-chip">确信度 {Math.round(sidePick.confidence * 100)}%</span>
                    )}
                    {sidePick.trust_score != null && (() => {
                      const t2 = sidePick.trust_score!;
                      const cls = t2 >= 0.7 ? "trust-ok" : t2 >= 0.5 ? "trust-warn" : "trust-err";
                      return <span className={`trust-badge ${cls}`} style={{ fontSize: "11px" }}>T*={t2.toFixed(2)}</span>;
                    })()}
                  </div>
                )}
                {sidePick.thesis && (
                  <div style={{ fontSize: "12px", color: "var(--muted)", margin: "6px 0", lineHeight: 1.5 }}>
                    {sidePick.thesis}
                  </div>
                )}
                {(sidePick.top_invalidators || []).length > 0 && (
                  <div style={{ marginTop: 6 }}>
                    <div style={{ fontSize: "10px", textTransform: "uppercase", color: "var(--muted)", marginBottom: 3 }}>否决因子</div>
                    {(sidePick.top_invalidators || []).map((inv, i) => (
                      <div key={i} style={{ fontSize: "11px", padding: "2px 0" }}>• {inv}</div>
                    ))}
                  </div>
                )}
                {sidePick.world_state_summary && (
                  <div style={{ marginTop: 8, fontSize: "11px", color: "var(--muted)", lineHeight: 1.5 }}>
                    {sidePick.world_state_summary}
                  </div>
                )}
                {/* Legacy belief fields */}
                {(sidePick as EBRTPick).belief_mu != null && (
                  <div className="today-pick-belief" style={{ marginTop: 8 }}>
                    <span className="belief-mu-val">μ {(sidePick as EBRTPick).belief_mu! >= 0 ? "+" : ""}{(sidePick as EBRTPick).belief_mu!.toFixed(3)}</span>
                    {(sidePick as EBRTPick).belief_delta_mu != null && (() => {
                      const d = (sidePick as EBRTPick).belief_delta_mu!;
                      return <span className={d! >= 0 ? "belief-delta-pos" : "belief-delta-neg"}>Δ{d! >= 0 ? "+" : ""}{d!.toFixed(3)}</span>;
                    })()}
                    {(sidePick as EBRTPick).belief_sigma != null && (
                      <span className="belief-sigma-val">σ={(sidePick as EBRTPick).belief_sigma!.toFixed(2)}</span>
                    )}
                  </div>
                )}
                {sidePick.symbol && (
                  <button
                    type="button"
                    style={{ marginTop: 12, width: "100%" }}
                    onClick={() => void navigateSymbol(sidePick.symbol!, sidePick.name, "candidates")}
                  >
                    完整详情 →
                  </button>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }

  function renderSymbol() {
    const sym = symbolTarget;
    if (!sym) return <div className="empty">{t("noData")}</div>;
    const kline = symbolKline;
    const explain = symbolExplain;
    const action = explain?.action || kline?.ebrt_recommendation?.action || "";
    const conf = explain?.action_confidence ?? 0;
    const trust = explain?.trust;
    const trustScalar = trust?.trust_scalar ?? 0;
    const trustLevel = trust?.trust_level || "";
    const trustCls = trustScalar >= 0.7 ? "trust-ok" : trustScalar >= 0.5 ? "trust-warn" : "trust-err";
    const ohlcv = kline?.ohlcv || [];
    const eventMarkers = kline?.event_markers || [];
    const beliefOverlay = kline?.belief_overlay || [];
    const invalidators = explain?.invalidators || [];
    const evidenceFor = explain?.evidence_for || [];
    const evidenceAgainst = explain?.evidence_against || [];
    const asOf = explain?.as_of || kline?.ebrt_recommendation ? "" : "";

    // SVG chart dimensions
    const chartW = 560, mainH = 200, volH = 48, padX = 16, padYMain = 8;
    const bars = ohlcv.slice(-60);
    const barW = bars.length ? Math.max(2, Math.floor((chartW - padX * 2) / bars.length) - 1) : 6;
    const highs = bars.map(b => b.high).filter(v => v > 0);
    const lows = bars.map(b => b.low).filter(v => v > 0);
    const vols = bars.map(b => b.volume || 0);
    const maxH = highs.length ? Math.max(...highs) : 1;
    const minL = lows.length ? Math.min(...lows) : 0;
    const rangeH = maxH - minL || 1;
    const maxVol = vols.length ? Math.max(...vols, 1) : 1;
    const scaleY = (v: number) => padYMain + ((maxH - v) / rangeH) * (mainH - padYMain * 2);
    const scaleX = (i: number) => padX + i * ((chartW - padX * 2) / Math.max(bars.length - 1, 1));

    // Belief overlay
    const muPoints = beliefOverlay.map((b, i) => `${scaleX(i)},${scaleY(b.mu)}`).join(" ");
    const sigmaPath = beliefOverlay.length > 1
      ? `M ${beliefOverlay.map((b, i) => `${scaleX(i)},${scaleY(b.mu + b.sigma)}`).join(" L ")} L ${[...beliefOverlay].reverse().map((b, i) => `${scaleX(beliefOverlay.length - 1 - i)},${scaleY(b.mu - b.sigma)}`).join(" L ")} Z`
      : "";

    // Decision zone color
    const zoneFill = action === "ADD" ? "rgba(40, 200, 100, 0.07)"
      : (action === "PROBE" || action === "WATCH") ? "rgba(255, 180, 50, 0.07)"
      : "transparent";

    // Event marker date → bar index map
    const dateToIdx = new Map(bars.map((b, i) => [b.date, i]));

    return (
      <div className="symbol-page">
        {/* ── Header ── */}
        <div className="symbol-header">
          <button
            type="button"
            className="symbol-back-btn"
            onClick={() => setPage(symbolPrevPage)}
          >
            ← 返回
          </button>
          <span className="symbol-header-sym">{sym}</span>
          {symbolName && <span className="symbol-header-name">{symbolName}</span>}
          {action && (
            <span className={`action-chip action-chip-${action.toLowerCase()}`}>{action}</span>
          )}
          {conf > 0 && <span className="ind-chip">{Math.round(conf * 100)}%</span>}
          {trustScalar > 0 && (
            <span className={`trust-badge ${trustCls}`}>{trustLevel || "T*"} {trustScalar.toFixed(2)}</span>
          )}
          {symbolLoading && <span style={{ color: "var(--muted)", fontSize: "12px" }}>加载中…</span>}
        </div>

        {/* ── Thesis ── */}
        {explain?.thesis && (
          <div className="symbol-thesis">{explain.thesis}</div>
        )}

        {/* ── Invalidators ── */}
        {invalidators.length > 0 && (
          <div className="symbol-invalidators">
            {invalidators.map((inv, i) => (
              <span key={i} className="today-inv-chip">• {inv}</span>
            ))}
          </div>
        )}

        {/* ── Body: chart + explanation ── */}
        <div className="symbol-body">
          {/* ── Chart ── */}
          <div className="symbol-chart-col">
            {/* Regime labels */}
            {explain?.world_state_summary && (
              <div className="symbol-regime-labels">{explain.world_state_summary}</div>
            )}
            {bars.length > 0 ? (
              <svg
                width={chartW}
                height={mainH + volH + 12}
                className="symbol-chart-svg"
                viewBox={`0 0 ${chartW} ${mainH + volH + 12}`}
                style={{ width: "100%", height: "auto" }}
              >
                {/* Decision zone background */}
                {zoneFill !== "transparent" && (
                  <rect x={padX} y={padYMain} width={chartW - padX * 2} height={mainH - padYMain * 2} fill={zoneFill} />
                )}

                {/* Sigma band */}
                {sigmaPath && (
                  <path d={sigmaPath} fill="rgba(42, 157, 255, 0.08)" stroke="none" />
                )}

                {/* Candlesticks */}
                {bars.map((bar, i) => {
                  const x = padX + i * ((chartW - padX * 2) / bars.length);
                  const isUp = bar.close >= bar.open;
                  const color = isUp ? "#22c55e" : "#ef4444";
                  const bodyTop = scaleY(Math.max(bar.open, bar.close));
                  const bodyBot = scaleY(Math.min(bar.open, bar.close));
                  const bodyHeight = Math.max(1, bodyBot - bodyTop);
                  return (
                    <g key={i}>
                      <line x1={x + barW / 2} y1={scaleY(bar.high)} x2={x + barW / 2} y2={scaleY(bar.low)} stroke={color} strokeWidth="1" />
                      <rect x={x} y={bodyTop} width={barW} height={bodyHeight} fill={color} opacity={0.85} />
                    </g>
                  );
                })}

                {/* Belief mu line */}
                {beliefOverlay.length > 1 && (
                  <polyline
                    points={muPoints}
                    fill="none"
                    stroke="rgba(42, 157, 255, 0.85)"
                    strokeWidth="1.5"
                    strokeDasharray="4 2"
                  />
                )}

                {/* Event markers */}
                {eventMarkers.map((em, i) => {
                  const idx = dateToIdx.get(em.date);
                  if (idx == null) return null;
                  const x = padX + idx * ((chartW - padX * 2) / bars.length) + barW / 2;
                  const isPos = em.magnitude > 0;
                  const isNeg = em.magnitude < 0;
                  const markerY = isPos ? scaleY(bars[idx]?.high || maxH) - 10 : scaleY(bars[idx]?.low || minL) + 14;
                  return (
                    <text
                      key={i}
                      x={x}
                      y={markerY}
                      textAnchor="middle"
                      fontSize="11"
                      fill={isPos ? "#22c55e" : isNeg ? "#ef4444" : "var(--muted)"}
                    >
                      {isPos ? "△" : isNeg ? "▽" : "○"}
                    </text>
                  );
                })}

                {/* Trust badge in corner */}
                {trustScalar > 0 && (
                  <>
                    <rect x={chartW - 62} y={4} width={58} height={18} rx={4} fill="rgba(0,0,0,0.55)" />
                    <text x={chartW - 33} y={16} textAnchor="middle" fontSize="10" fill={trustScalar >= 0.7 ? "#28c864" : trustScalar >= 0.5 ? "#ffb432" : "#ff5050"}>
                      T*={trustScalar.toFixed(2)}
                    </text>
                  </>
                )}

                {/* Volume sub-panel */}
                {vols.some(v => v > 0) && bars.map((bar, i) => {
                  const x = padX + i * ((chartW - padX * 2) / bars.length);
                  const volBarH = Math.max(1, (bar.volume / maxVol) * (volH - 4));
                  const isUp = bar.close >= bar.open;
                  return (
                    <rect
                      key={`vol-${i}`}
                      x={x}
                      y={mainH + 8 + (volH - 4 - volBarH)}
                      width={barW}
                      height={volBarH}
                      fill={isUp ? "rgba(34, 197, 94, 0.45)" : "rgba(239, 68, 68, 0.45)"}
                    />
                  );
                })}
              </svg>
            ) : symbolLoading ? (
              <div className="chart-empty">{t("loading")}</div>
            ) : (
              <div className="chart-empty">无K线数据</div>
            )}

            {/* Indicators row */}
            {kline?.indicators && (
              <div className="indicators-row" style={{ marginTop: 6 }}>
                {kline.indicators.rsi_14 != null && (
                  <span className="ind-chip">RSI {kline.indicators.rsi_14.toFixed(1)}</span>
                )}
                {kline.indicators.vol_ratio != null && (
                  <span className="ind-chip">量比 {kline.indicators.vol_ratio.toFixed(2)}</span>
                )}
                {kline.indicators.dist_52w_low != null && (
                  <span className="ind-chip">距52低 {(kline.indicators.dist_52w_low * 100).toFixed(1)}%</span>
                )}
              </div>
            )}
          </div>

          {/* ── Explanation panel ── */}
          <div className="symbol-explain-col">
            {/* Evidence For */}
            {evidenceFor.length > 0 && (
              <div className="symbol-section">
                <div className="symbol-section-title" style={{ color: "var(--ok)" }}>支持证据</div>
                {evidenceFor.slice(0, 4).map((e, i) => (
                  <div key={i} className="symbol-evidence-item">
                    <span className="symbol-evidence-dir symbol-ev-pos">▲</span>
                    <span className="symbol-evidence-text">{e.description || e.source || "-"}</span>
                    {e.strength != null && (
                      <span className="symbol-evidence-str">{e.strength.toFixed(2)}</span>
                    )}
                  </div>
                ))}
              </div>
            )}

            {/* Evidence Against */}
            {evidenceAgainst.length > 0 && (
              <div className="symbol-section">
                <div className="symbol-section-title" style={{ color: "var(--err)" }}>反向证据</div>
                {evidenceAgainst.slice(0, 4).map((e, i) => (
                  <div key={i} className="symbol-evidence-item">
                    <span className="symbol-evidence-dir symbol-ev-neg">▼</span>
                    <span className="symbol-evidence-text">{e.description || e.source || "-"}</span>
                    {e.strength != null && (
                      <span className="symbol-evidence-str">{e.strength.toFixed(2)}</span>
                    )}
                  </div>
                ))}
              </div>
            )}

            {/* Scenario */}
            {explain?.scenario_summary && (
              <div className="symbol-section">
                <div className="symbol-section-title">情景摘要</div>
                <div style={{ fontSize: "12px", color: "var(--muted)", lineHeight: 1.5 }}>
                  {explain.scenario_summary}
                </div>
              </div>
            )}

            {/* Next Triggers */}
            {(explain?.next_triggers || []).length > 0 && (
              <div className="symbol-section">
                <div className="symbol-section-title">下一触发点</div>
                {(explain?.next_triggers || []).map((t2, i) => (
                  <div key={i} style={{ fontSize: "11px", color: "var(--muted)", padding: "2px 0" }}>• {t2}</div>
                ))}
              </div>
            )}

            {/* Warnings / Data Quality */}
            {((explain?.warnings || []).length > 0 || (explain?.data_quality_notes || []).length > 0) && (
              <div className="symbol-section">
                <div className="symbol-section-title" style={{ color: "var(--warn)" }}>数据/警告</div>
                {[...(explain?.warnings || []), ...(explain?.data_quality_notes || [])].map((w, i) => (
                  <div key={i} style={{ fontSize: "11px", color: "var(--warn)", padding: "2px 0" }}>⚠ {w}</div>
                ))}
              </div>
            )}

            {/* Blockers / Invalidators */}
            {invalidators.length > 0 && (
              <div className="symbol-section">
                <div className="symbol-section-title" style={{ color: "var(--err)" }}>否决因子</div>
                {invalidators.map((inv, i) => (
                  <div key={i} style={{ fontSize: "11px", color: "var(--err)", padding: "2px 0" }}>✕ {inv}</div>
                ))}
              </div>
            )}

            {/* Trust components */}
            {trust?.trust_components && Object.keys(trust.trust_components).length > 0 && (
              <div className="symbol-section">
                <div className="symbol-section-title">Trust 分量</div>
                <div className="trust-gate-wrap" style={{ margin: 0 }}>
                  <div className="trust-components-row" style={{ borderRadius: 8, border: "1px solid var(--line)", borderTop: "none" }}>
                    {Object.entries(trust.trust_components).map(([k, v]) => {
                      const cls = v >= 0.7 ? "trust-comp-ok" : v >= 0.5 ? "trust-comp-warn" : "trust-comp-err";
                      return (
                        <div key={k} className="trust-component-item">
                          <span className="trust-comp-label">{k}</span>
                          <div className="trust-comp-bar-bg">
                            <div className={`trust-comp-bar-fill ${cls}`} style={{ width: `${Math.round(v * 100)}%` }} />
                          </div>
                          <span className="trust-comp-val">{v.toFixed(2)}</span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            )}

            {/* No explanation fallback */}
            {!explain && !symbolLoading && (
              <div style={{ color: "var(--muted)", fontSize: "12px", marginTop: 20, textAlign: "center" }}>
                暂无解释数据
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }

  // Legacy renderPicks kept for internal kline side-panel in old flows
  function renderPicks() {
    if (loading.signals && !signalsData) return <div className="empty">{t("loading")}</div>;
    if (signalsError) return (
      <div className="empty" style={{ color: "var(--err)", whiteSpace: "pre-wrap", padding: "20px 24px" }}>
        <strong>选股数据加载失败</strong><br />{signalsError}
      </div>
    );
    if (!signalsData) return <div className="empty">{t("noData")}</div>;
    const picks = signalsData.picks || [];
    const isEbrtSource = signalsData.source === "ebrt";
    const conviction = klineData?.recommendation?.conviction || klineData?.ebrt_recommendation?.conviction || "";
    return (
      <div className="picks-layout">
        <div className="picks-table-wrap">
          <table className="picks-table">
            <thead>
              {isEbrtSource ? (
                <tr className="picks-ebrt-header">
                  <th>代码</th>
                  <th>名称</th>
                  <th>操作</th>
                  <th>确信度</th>
                  <th>综合分</th>
                  <th>信念 μ</th>
                  <th>Δμ</th>
                  <th>σ</th>
                  <th>风险</th>
                </tr>
              ) : (
                <tr>
                  <th>代码</th>
                  <th>名称</th>
                  <th>状态</th>
                  <th>综合分</th>
                  <th>{t("modelScore")}</th>
                  <th>{t("windowScore")}</th>
                  <th>{t("kgScore")}</th>
                  <th>情绪</th>
                  <th>事件</th>
                </tr>
              )}
            </thead>
            <tbody>
              {picks.map((pick, idx) => {
                const ep = pick as EBRTPick;
                const isSelected = selectedSymbol === pick.symbol;
                if (isEbrtSource) {
                  const action = ep.action || "";
                  const dmu = ep.belief_delta_mu;
                  return [
                    <tr
                      key={`pick-${idx}`}
                      className={isSelected ? "selected" : ""}
                      onClick={() => { if (pick.symbol) void loadKlineData(pick.symbol); }}
                    >
                      <td style={{ fontWeight: 600, fontSize: "13px" }}>{pick.symbol || "-"}</td>
                      <td>{pick.name || "-"}</td>
                      <td><span className={`today-pick-action action-${action}`}>{action || "-"}</span></td>
                      <td><span className={`conviction-badge conviction-${ep.conviction || ""}`}>{ep.conviction || "-"}</span></td>
                      <td>{ep.score != null ? ep.score.toFixed(3) : "-"}</td>
                      <td>
                        {ep.belief_mu != null ? (
                          <span className={ep.belief_mu >= 0 ? "belief-delta-pos" : "belief-delta-neg"}>
                            {ep.belief_mu >= 0 ? "+" : ""}{ep.belief_mu.toFixed(3)}
                          </span>
                        ) : "-"}
                      </td>
                      <td>
                        {dmu != null ? (
                          <span className={dmu >= 0 ? "belief-delta-pos" : "belief-delta-neg"}>
                            {dmu >= 0 ? "+" : ""}{dmu.toFixed(3)}
                          </span>
                        ) : "-"}
                      </td>
                      <td>{ep.belief_sigma != null ? ep.belief_sigma.toFixed(3) : "-"}</td>
                      <td>{ep.risk != null ? ep.risk.toFixed(3) : "-"}</td>
                    </tr>,
                    isSelected && (ep.reasons?.length || ep.top_evidence?.length) ? (
                      <tr key={`belief-${idx}`} className="picks-belief-row">
                        <td colSpan={9}>
                          {ep.reasons && ep.reasons.length > 0 && (
                            <div className="picks-belief-summary">
                              <span style={{ fontWeight: 600 }}>推荐理由:</span>
                              <ul className="picks-evidence-list">
                                {ep.reasons.slice(0, 3).map((r, ri) => (
                                  <li key={ri}>{r.evidence_type && <span style={{ opacity: 0.6 }}>[{r.evidence_type}]</span>} {r.description}</li>
                                ))}
                              </ul>
                            </div>
                          )}
                          {ep.top_evidence && ep.top_evidence.length > 0 && (
                            <div className="picks-belief-summary" style={{ marginTop: 4 }}>
                              <span style={{ fontWeight: 600 }}>Top Evidence:</span>
                              <ul className="picks-evidence-list">
                                {ep.top_evidence.slice(0, 3).map((e, ei) => (
                                  <li key={ei}>
                                    <span className="picks-evidence-attn">{e.weight != null ? e.weight.toFixed(3) : "-"}</span>
                                    {e.evidence_id || "-"}
                                  </li>
                                ))}
                              </ul>
                            </div>
                          )}
                        </td>
                      </tr>
                    ) : null,
                  ];
                }
                return (
                  <tr
                    key={idx}
                    className={isSelected ? "selected" : ""}
                    onClick={() => { if (pick.symbol) void loadKlineData(pick.symbol); }}
                  >
                    <td style={{ fontWeight: 600, fontSize: "13px" }}>{pick.symbol || "-"}</td>
                    <td>{pick.name || "-"}</td>
                    <td>
                      {pick.status === "new" ? (
                        <span className="badge-new">{t("newTag")}</span>
                      ) : (
                        <span className="badge-continued">{t("continuedTag")}</span>
                      )}
                    </td>
                    <td>{pick.adj_score != null ? pick.adj_score.toFixed(3) : "-"}</td>
                    <td>{pick.model_score != null ? pick.model_score.toFixed(3) : "-"}</td>
                    <td>{pick.window_score != null ? pick.window_score.toFixed(3) : "-"}</td>
                    <td>{pick.event_kg_score != null ? pick.event_kg_score.toFixed(3) : "-"}</td>
                    <td>{pick.net_sentiment != null ? pick.net_sentiment.toFixed(2) : "-"}</td>
                    <td>{(pick as any).event_type || "-"}</td>
                  </tr>
                );
              })}
              {!picks.length && (
                <tr><td colSpan={9} className="empty">{t("noData")}</td></tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="picks-side-panel">
          {!selectedSymbol ? (
            <div style={{ color: "var(--muted)", fontSize: "13px", marginTop: 20, textAlign: "center" }}>
              点击左侧表格行查看K线详情
            </div>
          ) : klineLoading ? (
            <div style={{ color: "var(--muted)", fontSize: "13px", marginTop: 20, textAlign: "center" }}>{t("loading")}</div>
          ) : klineData ? (
            <>
              <div className="kline-panel-header">
                <span className="sym-name">{klineData.name || selectedSymbol}</span>
                <span className="sym-code">{klineData.symbol || selectedSymbol}</span>
              </div>
              {klineData.ohlcv && klineData.ohlcv.length > 0 && (
                <CandlestickChart bars={klineData.ohlcv} />
              )}
              {klineData.indicators && (
                <div className="indicators-row">
                  {klineData.indicators.rsi_14 != null && (
                    <span className="ind-chip">RSI: {klineData.indicators.rsi_14.toFixed(1)}</span>
                  )}
                  {klineData.indicators.vol_ratio != null && (
                    <span className="ind-chip">量比: {klineData.indicators.vol_ratio.toFixed(2)}</span>
                  )}
                  {klineData.indicators.dist_52w_low != null && (
                    <span className="ind-chip">距52周低: {(klineData.indicators.dist_52w_low * 100).toFixed(1)}%</span>
                  )}
                </div>
              )}
              {klineData.ebrt_recommendation && (
                <div style={{ marginTop: 10, padding: "8px 10px", background: "var(--surface2, rgba(255,255,255,0.03))", borderRadius: 6 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6, flexWrap: "wrap" }}>
                    {klineData.ebrt_recommendation.action && (
                      <span className={`today-pick-action action-${klineData.ebrt_recommendation.action}`}>
                        {klineData.ebrt_recommendation.action}
                      </span>
                    )}
                    <span className={`conviction-badge conviction-${klineData.ebrt_recommendation.conviction || ""}`}>
                      {klineData.ebrt_recommendation.conviction || "-"}
                    </span>
                    {klineData.ebrt_recommendation.score != null && (
                      <span className="ind-chip">score: {klineData.ebrt_recommendation.score.toFixed(3)}</span>
                    )}
                    {klineData.ebrt_recommendation.risk != null && (
                      <span className="ind-chip">risk: {klineData.ebrt_recommendation.risk.toFixed(3)}</span>
                    )}
                  </div>
                  <div className="today-pick-belief" style={{ marginTop: 4 }}>
                    {klineData.ebrt_recommendation.belief_mu != null && (
                      <span className="belief-mu-val">μ {klineData.ebrt_recommendation.belief_mu >= 0 ? "+" : ""}{klineData.ebrt_recommendation.belief_mu.toFixed(3)}</span>
                    )}
                    {klineData.ebrt_recommendation.belief_delta_mu != null && (() => {
                      const d = klineData.ebrt_recommendation!.belief_delta_mu!;
                      return <span className={d >= 0 ? "belief-delta-pos" : "belief-delta-neg"}>Δ{d >= 0 ? "+" : ""}{d.toFixed(3)}</span>;
                    })()}
                    {klineData.ebrt_recommendation.belief_sigma != null && (
                      <span className="belief-sigma-val">σ={klineData.ebrt_recommendation.belief_sigma.toFixed(2)}</span>
                    )}
                  </div>
                  {(klineData.ebrt_recommendation.reasons || []).length > 0 && (
                    <ul className="picks-evidence-list" style={{ marginTop: 6 }}>
                      {(klineData.ebrt_recommendation.reasons || []).slice(0, 3).map((r, ri) => (
                        <li key={ri}>{r.evidence_type && <span style={{ opacity: 0.6 }}>[{r.evidence_type}]</span>} {r.description}</li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
              {!klineData.ebrt_recommendation && klineData.recommendation && (
                <div style={{ marginTop: 10 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                    <span style={{ fontSize: "12px", color: "var(--muted)" }}>{t("conviction")}:</span>
                    <span className={`conviction-badge conviction-${conviction}`}>{conviction || "-"}</span>
                  </div>
                  {(klineData.recommendation.reasons || []).length > 0 && (
                    <ul className="reasons-list">
                      {(klineData.recommendation.reasons || []).map((reason, idx) => (
                        <li key={idx}>{reason}</li>
                      ))}
                    </ul>
                  )}
                  {klineData.recommendation.hist_event_stats && (
                    <div style={{ fontSize: "11px", color: "var(--muted)", marginTop: 4 }}>
                      历史{klineData.recommendation.hist_event_stats.event_type}事件:
                      {" "}{klineData.recommendation.hist_event_stats.hist_count}次,
                      5日均收益: {klineData.recommendation.hist_event_stats.hist_ret_5d_avg != null
                        ? `+${klineData.recommendation.hist_event_stats.hist_ret_5d_avg.toFixed(1)}%`
                        : "-"}
                    </div>
                  )}
                </div>
              )}
              {(klineData as any).prediction && (
                <div style={{ marginTop: 12, fontSize: "12px" }}>
                  <div style={{ color: "var(--muted)", marginBottom: 4 }}>预测 (legacy)</div>
                  <div style={{ display: "flex", gap: 12 }}>
                    {(klineData as any).prediction.predicted_return_5d != null && (
                      <span className="ind-chip">5日: {((klineData as any).prediction.predicted_return_5d * 100).toFixed(2)}%</span>
                    )}
                  </div>
                </div>
              )}
              {klineData.latest_signal && (
                <div style={{ marginTop: 12, fontSize: "11px", color: "var(--muted)" }}>
                  <div>模型: {klineData.latest_signal.model_score?.toFixed(3) ?? "-"} | 窗口: {klineData.latest_signal.window_score?.toFixed(3) ?? "-"} | 事件: {klineData.latest_signal.event_kg_score?.toFixed(3) ?? "-"} | 情绪: {klineData.latest_signal.net_sentiment?.toFixed(2) ?? "-"}</div>
                </div>
              )}
            </>
          ) : null}
        </div>
      </div>
    );
  }

  function renderDagGraph(
    layout: DagLayout,
    options?: {
      graphKey: string;
      selectedKey?: string;
      onSelect?: (key: string) => void;
      flyout?: ReactNode;
      onNodeMove?: (nodeKey: string, x: number, y: number) => void;
      onHoverStart?: (key: string) => void;
      onHoverEnd?: () => void;
      onPin?: (key: string) => void;
      focusDagIds?: Set<number>;
      onExecute?: (node: GraphNode) => void;
    },
  ) {
    if (!layout.nodes.length) return <div className="empty">{t("noData")}</div>;

    function startDrag(event: ReactMouseEvent<HTMLDivElement>, node: GraphNode) {
      if (!options?.onNodeMove) return;
      if ((event.target as HTMLElement).closest(".dag-node-quick-action")) return;
      const originX = event.clientX;
      const originY = event.clientY;
      const startX = node.x;
      const startY = node.y;
      const move = (moveEvent: MouseEvent) => {
        const nextX = startX + moveEvent.clientX - originX;
        const nextY = startY + moveEvent.clientY - originY;
        const clampedX = Math.max(12, Math.min(layout.width - node.width - 12, nextX));
        const clampedY = Math.max(52, Math.min(layout.height - node.height - 16, nextY));
        options.onNodeMove?.(
          node.key,
          clampedX,
          clampedY,
        );
      };
      const up = () => {
        window.removeEventListener("mousemove", move);
        window.removeEventListener("mouseup", up);
      };
      window.addEventListener("mousemove", move);
      window.addEventListener("mouseup", up);
    }

    return (
      <div className="dag-shell">
        <div className="dag-canvas">
          <div className="dag-board" style={{ width: `${layout.width}px`, height: `${layout.height}px` }}>
            <div className="dag-level-header">
            {layout.levels.map((level) => (
              <div key={`level-${level.depth}`} className="dag-level-pill" style={{ left: `${level.x}px` }}>
                {level.label}
              </div>
            ))}
            </div>
            <svg className="dag-svg" viewBox={`0 0 ${layout.width} ${layout.height}`} preserveAspectRatio="none">
            {layout.edges.map((edge) => {
              const path = edge.points?.length
                ? edge.points.map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`).join(" ")
                : (() => {
                    const midX = edge.x1 + Math.max(32, (edge.x2 - edge.x1) / 2);
                    return `M ${edge.x1} ${edge.y1} C ${midX} ${edge.y1}, ${midX} ${edge.y2}, ${edge.x2} ${edge.y2}`;
                  })();
              return (
                <path
                  key={edge.key}
                  d={path}
                  className={`dag-edge ${statusClass(edge.status)}`}
                />
              );
            })}
            </svg>
            {layout.nodes.map((node) => {
              const isFocused = node.dagId && options?.focusDagIds?.size ? options.focusDagIds.has(node.dagId) : false;
              const shouldDim = options?.focusDagIds?.size && node.kind === "task" && !isFocused;
              return (
                <div
                  role="button"
                  tabIndex={0}
                  key={node.key}
                  className={[
                    "dag-node",
                    node.kind,
                    statusClass(node.status),
                    options?.selectedKey === node.key ? "selected" : "",
                    isFocused ? "focused" : "",
                    shouldDim ? "dimmed" : "",
                  ].filter(Boolean).join(" ")}
                  style={{ left: `${node.x}px`, top: `${node.y}px`, width: `${node.width}px`, height: `${node.height}px` }}
                  onClick={() => {
                    options?.onSelect?.(node.key);
                    options?.onPin?.(node.key);
                  }}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      options?.onSelect?.(node.key);
                      options?.onPin?.(node.key);
                    }
                  }}
                  onMouseDown={(event) => startDrag(event, node)}
                  onMouseEnter={() => options?.onHoverStart?.(node.key)}
                  onMouseLeave={() => options?.onHoverEnd?.()}
                >
                  <div className="dag-node-top">
                    <span className="dag-node-title">{node.label}</span>
                    <div className="dag-node-meta">
                      <span className={`pill ${statusClass(node.status)}`}>{node.status}</span>
                      {node.kind === "task" && node.dagId ? (
                        <button
                          type="button"
                          className="dag-node-quick-action"
                          onClick={(event) => {
                            event.stopPropagation();
                            options?.onExecute?.(node);
                          }}
                        >
                          {t("execute")}
                        </button>
                      ) : null}
                    </div>
                  </div>
                  <div className="dag-node-subtitle">{shortText(node.subtitle, 54)}</div>
                  <div className={`dag-node-detail ${node.status === "error" ? "error-text" : ""}`}>{shortText(node.detail || "-", 96)}</div>
                </div>
              );
            })}
            {options?.flyout}
          </div>
        </div>
      </div>
    );
  }

  function renderNodeFlyout(
    layout: DagLayout,
    node: GraphNode | null,
    rows: DagNode[],
    options?: { rootEventId?: number; graphKey?: string; readOnly?: boolean; workflowNodeIds?: Set<number> },
  ) {
    if (!node) return null;
    const flyoutWidth = 308;
    const row = rows.find((item) => `task:${item.dag_id ?? item.id ?? item.job_name}` === node.key);
    const preferredLeft = node.x + node.width + 18;
    const flippedLeft = Math.max(16, node.x - flyoutWidth - 18);
    const flyoutStyle = {
      left: `${preferredLeft + flyoutWidth > layout.width ? flippedLeft : preferredLeft}px`,
      top: `${Math.max(16, node.y)}px`,
    };
    if (!row) {
      return (
        <div className="dag-flyout" style={flyoutStyle}>
          <div className="list-card flyout-card">
            <div className="panel-title">{node.label}</div>
            <div className="muted-line">{node.subtitle}</div>
            <div className="muted-line">{node.detail || "-"}</div>
          </div>
        </div>
      );
    }
    const inWorkflow = row.dag_id && options?.workflowNodeIds?.has(Number(row.dag_id));
    return (
      <div
        className="dag-flyout"
        style={flyoutStyle}
        onMouseEnter={() => clearFlyoutTimer()}
        onMouseLeave={() => scheduleDagFlyoutClose()}
      >
        <div className="list-stack">
          <div className="list-card flyout-card">
            <div className="stat-label">{t("nodeDetail")}</div>
            <div className="node-header">
              <div>
                <div className="panel-title">{row.job_name}</div>
                <div className="muted-line">{row.stage} · {row.source || "-"}</div>
              </div>
              <span className={`pill ${statusClass(row.status)}`}>{row.status}</span>
            </div>
            <div className={`muted-line ${row.error || row.error_detail ? "error-text" : ""}`}>
              {shortText(row.error || row.error_detail || row.result_summary || row.last_run?.result_summary || "-", 240)}
            </div>
            <div className="detail-metrics">
              <div><span className="stat-label">{t("latestRun")}</span><span>{formatDateTime(row.last_run?.started_at || row.last_source_event?.created_at)}</span></div>
              <div><span className="stat-label">{t("counts")}</span><span>{row.recent_ok_count ?? 0} ok / {row.recent_error_count ?? 0} err</span></div>
              <div><span className="stat-label">emits</span><span>{row.emits || "-"}</span></div>
            </div>
            {row.dag_id && !options?.readOnly ? (
              <div className="node-actions">
                <button
                  type="button"
                  onClick={() => inWorkflow && options?.rootEventId
                    ? void rerunNode(options.rootEventId, row.dag_id!, "self")
                    : void runDagNode(row.dag_id!, "self")}
                >
                  {t("rerun")}
                </button>
                <button
                  type="button"
                  onClick={() => inWorkflow && options?.rootEventId
                    ? void rerunNode(options.rootEventId, row.dag_id!, "upstream")
                    : void runDagNode(row.dag_id!, "upstream")}
                >
                  {t("rerunUpstream")}
                </button>
                <button
                  type="button"
                  onClick={() => inWorkflow && options?.rootEventId
                    ? void rerunNode(options.rootEventId, row.dag_id!, "downstream")
                    : void runDagNode(row.dag_id!, "downstream")}
                >
                  {t("rerunDownstream")}
                </button>
                <button
                  type="button"
                  onClick={() => inWorkflow && options?.rootEventId
                    ? void rerunNode(options.rootEventId, row.dag_id!, "full")
                    : void runDagNode(row.dag_id!, "full")}
                >
                  {t("rerunFull")}
                </button>
              </div>
            ) : null}
          </div>
        </div>
      </div>
    );
  }

  function renderNodeSidebar(
    row: DagNode | null,
    options?: { rootEventId?: number; workflowNodeIds?: Set<number>; workflow?: any | null },
  ) {
    if (!row || !row.dag_id) {
      return (
        <div className="list-card">
          <div className="stat-label">{t("nodeDetail")}</div>
          <div className="panel-title">{t("selectNode")}</div>
          <div className="muted-line">{t("selectNodeHint")}</div>
        </div>
      );
    }
    const inWorkflow = Boolean(options?.workflowNodeIds?.has(Number(row.dag_id)));
    const workflowReplay = options?.workflow?.payload_json?._replay || {};
    const sourceDispatch = row.source_event?.payload_json?._dispatch || {};
    const rootCause = shortText(
      row.error
      || row.error_detail
      || row.job_run?.result_summary
      || options?.workflow?.root_cause?.message
      || options?.workflow?.root_cause?.error
      || "-",
      260,
    );
    const replaySummary = [
      workflowReplay.mode ? `workflow:${workflowReplay.mode}` : "",
      sourceDispatch.mode ? `source:${sourceDispatch.mode}` : "",
      sourceDispatch.target_dag_id ? `target:${sourceDispatch.target_dag_id}` : "",
    ].filter(Boolean).join(" · ");
    return (
      <div className="list-stack">
        <div className="list-card">
          <div className="stat-label">{t("nodeDetail")}</div>
          <div className="node-header">
            <div>
              <div className="panel-title">{row.job_name}</div>
              <div className="muted-line">{row.stage} · {row.source || "-"}</div>
            </div>
            <span className={`pill ${statusClass(row.status)}`}>{row.status || "-"}</span>
          </div>
          <div className="detail-metrics">
            <div><span className="stat-label">{t("latestRun")}</span><span>{formatDateTime(row.job_run?.started_at || row.last_run?.started_at || row.last_source_event?.created_at)}</span></div>
            <div><span className="stat-label">{t("sourceEvent")}</span><span>{row.source_event?.topic || row.source || "-"}</span></div>
            <div><span className="stat-label">emits</span><span>{row.emits || "-"}</span></div>
          </div>
        </div>
        <div className="list-card">
          <div className="stat-label">{t("rootCauses")}</div>
          <div className={`muted-line ${rootCause !== "-" ? "error-text" : ""}`}>{rootCause}</div>
        </div>
        <div className="list-card">
          <div className="stat-label">{t("execution")}</div>
          <div className="muted-line">{shortText(row.job_run?.result_summary || row.last_run?.result_summary || "-", 220)}</div>
          <div className="detail-metrics">
            <div><span className="stat-label">{t("counts")}</span><span>{row.recent_ok_count ?? 0} ok / {row.recent_error_count ?? 0} err</span></div>
            <div><span className="stat-label">{t("progress")}</span><span>{inWorkflow ? "workflow focus" : "global dag"}</span></div>
          </div>
        </div>
        <div className="list-card">
          <div className="stat-label">{t("replayLineage")}</div>
          <div className="muted-line">{replaySummary || "-"}</div>
        </div>
        <div className="list-card">
          <div className="node-actions">
            <button
              type="button"
              onClick={() => inWorkflow && options?.rootEventId
                ? void rerunNode(options.rootEventId, row.dag_id!, "self")
                : void runDagNode(row.dag_id!, "self")}
            >
              {t("rerun")}
            </button>
            <button
              type="button"
              onClick={() => inWorkflow && options?.rootEventId
                ? void rerunNode(options.rootEventId, row.dag_id!, "upstream")
                : void runDagNode(row.dag_id!, "upstream")}
            >
              {t("rerunUpstream")}
            </button>
            <button
              type="button"
              onClick={() => inWorkflow && options?.rootEventId
                ? void rerunNode(options.rootEventId, row.dag_id!, "downstream")
                : void runDagNode(row.dag_id!, "downstream")}
            >
              {t("rerunDownstream")}
            </button>
            <button
              type="button"
              onClick={() => inWorkflow && options?.rootEventId
                ? void rerunNode(options.rootEventId, row.dag_id!, "full")
                : void runDagNode(row.dag_id!, "full")}
            >
              {t("rerunFull")}
            </button>
          </div>
        </div>
      </div>
    );
  }

  function renderOps() {
    if (loading.events && !eventsPage) return <div className="empty">{t("loading")}</div>;
    if (!eventsPage) return <div className="empty">{t("noData")}</div>;

    const allNodes = (eventsPage?.dag?.nodes || []) as DagNode[];

    // Deduplicate by job_name, keeping latest run, skip disabled
    const dedupMap = new Map<string, DagNode>();
    for (const n of allNodes) {
      if (n.enabled === 0) continue;
      const jn = String(n.job_name || "");
      const existing = dedupMap.get(jn);
      const nRunId = n.last_run?.id || 0;
      const existRunId = existing?.last_run?.id || 0;
      if (!existing || nRunId > existRunId) dedupMap.set(jn, n);
    }

    const fetchNodes = Array.from(dedupMap.values())
      .filter((n) => n.stage === "fetch")
      .sort((a, b) => (a.id || 0) - (b.id || 0));

    const computeAllNodes = Array.from(dedupMap.values()).filter(
      (n) => n.stage === "compute" || n.stage === "train",
    );

    // Build compute→compute chains
    const emitToJob = new Map<string, string>();
    for (const n of computeAllNodes) {
      if (n.emits) emitToJob.set(String(n.emits), String(n.job_name || ""));
    }
    const hasComputePred = new Set<string>();
    for (const n of computeAllNodes) {
      if (n.source && emitToJob.has(String(n.source))) {
        hasComputePred.add(String(n.job_name || ""));
      }
    }
    const jobToNext = new Map<string, string>();
    for (const n of computeAllNodes) {
      if (n.source && emitToJob.has(String(n.source))) {
        const prev = emitToJob.get(String(n.source))!;
        jobToNext.set(prev, String(n.job_name || ""));
      }
    }
    const nodeByJob = new Map(computeAllNodes.map((n) => [String(n.job_name || ""), n]));
    const visited = new Set<string>();
    const chains: DagNode[][] = [];
    const roots = computeAllNodes.filter((n) => !hasComputePred.has(String(n.job_name || "")));
    for (const root of roots) {
      const chain: DagNode[] = [];
      let cur: string | undefined = String(root.job_name || "");
      while (cur && !visited.has(cur) && nodeByJob.has(cur)) {
        chain.push(nodeByJob.get(cur)!);
        visited.add(cur);
        cur = jobToNext.get(cur);
      }
      if (chain.length) chains.push(chain);
    }

    function fmtElapsed(ms?: number | null): string {
      if (!ms) return "";
      return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
    }

    const hoveredNode = pipelineHover ? (dedupMap.get(pipelineHover) ?? null) : null;
    const hoveredDagId = hoveredNode ? Number(hoveredNode.dag_id ?? hoveredNode.id ?? 0) || null : null;

    function renderPanel(node: DagNode) {
      const lr = node.last_run;
      const dagId = Number(node.dag_id ?? node.id ?? 0) || null;
      return (
        <div className="pipeline-panel">
          <div className="pipeline-panel-header">
            <span className={`node-dot ${statusClass(node.status)}`} />
            <span className="pipeline-panel-title">{node.job_name}</span>
            <span className={`pill ${statusClass(node.status)}`}>{node.status}</span>
          </div>
          <div className="pipeline-panel-body">
            {lr && (
              <>
                <div className="panel-kv">
                  <span className="panel-label">运行时间</span>
                  <span>{lr.started_at ? String(lr.started_at).slice(11, 19) : "—"}</span>
                </div>
                <div className="panel-kv">
                  <span className="panel-label">耗时</span>
                  <span>{fmtElapsed(lr.elapsed_ms) || "—"}</span>
                </div>
                {lr.result_summary && (
                  <div className="panel-summary">{lr.result_summary}</div>
                )}
              </>
            )}
            {node.error_detail && (
              <div className="panel-error">{node.error_detail}</div>
            )}
            {(node.sync_source || node.sync_dataset) && (
              <div className="panel-kv">
                <span className="panel-label">数据源</span>
                <span className="muted-line">{[node.sync_source, node.sync_dataset].filter(Boolean).join(" / ")}</span>
              </div>
            )}
            <div className="panel-kv">
              <span className="panel-label">触发</span>
              <span className="muted-line">{node.source || "—"}</span>
            </div>
          </div>
          {dagId ? (
            <div className="pipeline-panel-actions">
              <button
                type="button"
                className="dag-node-quick-action"
                onClick={() => void runDagNode(dagId, "self")}
              >
                ▶ 执行
              </button>
              <button
                type="button"
                className="btn-config"
                onClick={() => {
                  setConfigPanelDagId(dagId);
                  setConfigPanelValue("{}");
                }}
              >
                ⚙ 配置
              </button>
              <button
                type="button"
                className="btn-backfill"
                onClick={() => {
                  setBackfillDagId(dagId);
                  setBackfillFrom("");
                  setBackfillTo("");
                }}
              >
                📅 回补
              </button>
            </div>
          ) : null}
          {configPanelDagId !== null && configPanelDagId === dagId && (
            <div className="config-panel" style={{ margin: "8px 0 0" }}>
              <textarea
                value={configPanelValue}
                onChange={(e) => setConfigPanelValue(e.target.value)}
                rows={5}
                className="config-textarea"
              />
              <div className="config-actions">
                <button type="button" onClick={() => void saveConfig(configPanelDagId)}>{t("saveConfig")}</button>
                <button type="button" onClick={() => setConfigPanelDagId(null)}>{t("cancel")}</button>
              </div>
            </div>
          )}
          {backfillDagId !== null && backfillDagId === dagId && (
            <div className="backfill-panel" style={{ margin: "8px 0 0" }}>
              <label>开始日期<input type="date" value={backfillFrom} onChange={(e) => setBackfillFrom(e.target.value)} /></label>
              <label>结束日期<input type="date" value={backfillTo} onChange={(e) => setBackfillTo(e.target.value)} /></label>
              <div className="config-actions">
                <button type="button" onClick={() => void runBackfill(backfillDagId)}>{t("confirmBackfill")}</button>
                <button type="button" onClick={() => setBackfillDagId(null)}>{t("cancel")}</button>
              </div>
            </div>
          )}
        </div>
      );
    }

    return (
      <div className="pipeline-v2">
        <div className="pipeline-v2-topbar">
          <span className={`pill ${streamState.status === "connected" ? "ok" : streamState.status === "connecting" ? "running" : "error"}`}>
            {streamState.status === "connected" ? "● 已连接" : streamState.status === "connecting" ? "○ 连接中" : "✕ 断开"}
          </span>
          {streamState.lastUpdate && (
            <span className="muted-line">{formatDateTime(streamState.lastUpdate)}</span>
          )}
        </div>

        <div className="pipeline-v2-body">
          {/* ── Fetch column ── */}
          <div className="pipeline-fetch-col">
            <div className="pipeline-col-title">获取层</div>
            <div className="fetch-list">
              {fetchNodes.map((node) => (
                <div
                  key={node.job_name}
                  className={`fetch-item ${statusClass(node.status)}${pipelineHover === node.job_name ? " hovered" : ""}`}
                  onMouseEnter={(e) => {
                    if (pipelineHoverTimerRef.current) clearTimeout(pipelineHoverTimerRef.current);
                    setPipelineHover(String(node.job_name || ""));
                    setPipelineHoverPos({ x: e.clientX, y: e.clientY });
                  }}
                  onMouseLeave={() => {
                    pipelineHoverTimerRef.current = window.setTimeout(() => setPipelineHover(null), 180);
                  }}
                >
                  <div className="fetch-item-row">
                    <span className={`node-dot ${statusClass(node.status)}`} />
                    <span className="fetch-item-name">{node.job_name}</span>
                    <span className="fetch-item-elapsed">{fmtElapsed(node.last_run?.elapsed_ms)}</span>
                  </div>
                  {node.last_run?.result_summary && (
                    <div className="fetch-item-summary">{shortText(node.last_run.result_summary, 58)}</div>
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* ── Compute column ── */}
          <div className="pipeline-compute-col">
            <div className="pipeline-col-title">计算链路</div>
            <div className="compute-chains">
              {chains.map((chain, ci) => (
                <div key={ci} className="compute-chain">
                  {chain.map((node, ni) => (
                    <div key={node.job_name} className="compute-chain-item">
                      {ni > 0 && <span className="chain-arrow">→</span>}
                      <div
                        className={`compute-node-box ${statusClass(node.status)}${pipelineHover === node.job_name ? " hovered" : ""}`}
                        onMouseEnter={(e) => {
                          if (pipelineHoverTimerRef.current) clearTimeout(pipelineHoverTimerRef.current);
                          setPipelineHover(String(node.job_name || ""));
                          setPipelineHoverPos({ x: e.clientX, y: e.clientY });
                        }}
                        onMouseLeave={() => {
                          pipelineHoverTimerRef.current = window.setTimeout(() => setPipelineHover(null), 180);
                        }}
                      >
                        <div className="compute-node-top">
                          <span className={`node-dot ${statusClass(node.status)}`} />
                          <span className="compute-node-name">{node.job_name}</span>
                          {node.stage === "train" && (
                            <span className="compute-node-badge train">train</span>
                          )}
                        </div>
                        {node.last_run?.elapsed_ms != null && (
                          <div className="compute-node-elapsed">{fmtElapsed(node.last_run.elapsed_ms)}</div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              ))}
            </div>
          </div>

          {/* ── Hover panel (tooltip near cursor) ── */}
          <div
            className={`pipeline-panel-col${hoveredNode ? " visible" : ""}`}
            style={{
              left: Math.min(pipelineHoverPos.x + 16, window.innerWidth - 320),
              top: Math.min(pipelineHoverPos.y + 8, window.innerHeight - 400),
            }}
            onMouseEnter={() => { if (pipelineHoverTimerRef.current) clearTimeout(pipelineHoverTimerRef.current); }}
            onMouseLeave={() => { setPipelineHover(null); }}
          >
            {hoveredNode ? renderPanel(hoveredNode) : null}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="shell">
      <header className="topbar">
        <div>
          <h1>{t("title")}</h1>
          <p>{t("subtitle")}</p>
        </div>
        <div className="topbar-actions">
          <label>
            {t("language")}
            <select value={locale} onChange={(event) => setLocale(event.target.value as Locale)}>
              <option value="zh-CN">简体中文</option>
              <option value="en">English</option>
            </select>
          </label>
          <button onClick={() => void refreshCurrent()}>{t("refresh")}</button>
        </div>
      </header>

      <nav className="tabs">
        {PAGES.map((item) => (
          <button
            key={item.key}
            className={`tab ${page === item.key ? "active" : ""}`}
            onClick={() => setPage(item.key)}
          >
            {t(item.label)}
          </button>
        ))}
      </nav>

      {page === "today" && renderToday()}
      {page === "candidates" && renderCandidates()}
      {page === "symbol" && renderSymbol()}
      {page === "ops" && renderOps()}

      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}

export default App;
