import * as dagre from "dagre";
import { useEffect, useMemo, useRef, useState } from "react";
import type { MouseEvent as ReactMouseEvent, ReactNode } from "react";

type Locale = "zh-CN" | "en";
type PageKey = "report" | "events" | "kg";
type GraphNodeKind = "task" | "topic";

type DagNode = {
  id?: number;
  dag_id?: number;
  job_name?: string;
  stage?: string;
  source?: string;
  emits?: string;
  status?: string;
  error_detail?: string;
  error?: string;
  result_summary?: string;
  recent_ok_count?: number;
  recent_error_count?: number;
  last_run?: { started_at?: string; completed_at?: string; result_summary?: string } | null;
  last_source_event?: { created_at?: string; status?: string } | null;
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
    subtitle: "报表 / 事件 / KG 运行台",
    language: "语言",
    refresh: "刷新",
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
    candidates: "候选边",
    topPropagation: "传播最多标的",
    relationTypes: "边类型分布",
    snapshot: "快照",
    generatedAt: "生成时间",
    nodeDetail: "节点详情",
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
  },
  en: {
    title: "TradeDB",
    subtitle: "Report / Events / KG console",
    language: "Language",
    refresh: "Refresh",
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
    candidates: "Candidate edges",
    topPropagation: "Top propagated symbols",
    relationTypes: "Relation types",
    snapshot: "Snapshot",
    generatedAt: "Generated at",
    nodeDetail: "Node detail",
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
  },
};

type TranslationKey = keyof (typeof I18N)["zh-CN"];

const PAGES: Array<{ key: PageKey; label: TranslationKey }> = [
  { key: "report", label: "report" },
  { key: "events", label: "events" },
  { key: "kg", label: "kg" },
];

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

function buildDagLayout(
  rows: DagNode[],
  rawEdges: DagEdge[],
  focusDagIds?: Set<number>,
  overrides?: PositionOverrideMap,
): DagLayout {
  const taskWidth = 232;
  const taskHeight = 108;
  const topicWidth = 208;
  const topicHeight = 72;
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
      width: taskWidth,
      height: taskHeight,
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
            width: topicWidth,
            height: topicHeight,
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
  const graph = new dagre.graphlib.Graph({ multigraph: false, compound: false });
  graph.setGraph({
    rankdir: "LR",
    ranksep: 108,
    nodesep: 34,
    edgesep: 28,
    marginx: padX,
    marginy: padY,
    ranker: "network-simplex",
    acyclicer: "greedy",
  });
  graph.setDefaultEdgeLabel(() => ({}));

  for (const node of allNodes) {
    graph.setNode(node.key, {
      width: node.width,
      height: node.height,
      kind: node.kind,
      stage: node.stage,
      label: node.label,
      focused: Boolean(node.dagId && focusDagIds?.has(node.dagId)),
    });
  }
  for (const edge of edges) {
    graph.setEdge(edge.from, edge.to, { key: `${edge.from}->${edge.to}` });
  }

  dagre.layout(graph);

  const levelsMap = new Map<number, GraphNode[]>();
  let maxRight = 0;
  let maxBottom = 0;
  for (const node of allNodes) {
    const layoutNode = graph.node(node.key) as { x: number; y: number; rank?: number } | undefined;
    const override = overrides?.[node.key];
    node.x = override?.x ?? ((layoutNode?.x ?? padX) - node.width / 2);
    node.y = override?.y ?? ((layoutNode?.y ?? padY) - node.height / 2);
    const rank = Number(layoutNode?.rank ?? 0);
    const bucket = levelsMap.get(rank) || [];
    bucket.push(node);
    levelsMap.set(rank, bucket);
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
      width: Math.max(taskWidth, right - left),
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
      return {
        key: `${edge.from}->${edge.to}`,
        from: edge.from,
        to: edge.to,
        x1: from.x + from.width,
        y1: from.y + from.height / 2,
        x2: to.x,
        y2: to.y + to.height / 2,
        status,
      };
    })
    .filter(Boolean) as GraphEdge[];

  return { width, height, levels, nodes: allNodes, edges: graphEdges };
}

function App() {
  const [locale, setLocale] = useState<Locale>((localStorage.getItem("trade_locale") as Locale) || "zh-CN");
  const [page, setPage] = useState<PageKey>((localStorage.getItem("trade_page") as PageKey) || "report");
  const [reportPage, setReportPage] = useState<any>(null);
  const [eventsPage, setEventsPage] = useState<any>(null);
  const [kgPage, setKgPage] = useState<any>(null);
  const [workflowDetail, setWorkflowDetail] = useState<any>(null);
  const [selectedDagKey, setSelectedDagKey] = useState<string>("");
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
  const [toast, setToast] = useState("");
  const [loading, setLoading] = useState<Record<string, boolean>>({});
  const refreshTimerRef = useRef<number | null>(null);
  const flyoutTimerRef = useRef<number | null>(null);
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
  const globalGraph = useMemo(
    () => buildDagLayout(
      (eventsPage?.dag?.nodes || []) as DagNode[],
      (eventsPage?.dag?.edges || []) as DagEdge[],
      focusDagIds,
      graphOverrides[globalGraphKey] || {},
    ),
    [eventsPage?.dag?.nodes, eventsPage?.dag?.edges, focusDagIds, graphOverrides, globalGraphKey],
  );
  const selectedGlobalGraphNode = globalGraph.nodes.find((node) => node.key === selectedDagKey) || null;

  useEffect(() => {
    localStorage.setItem("trade_locale", locale);
  }, [locale]);

  useEffect(() => {
    localStorage.setItem("trade_page", page);
  }, [page]);

  useEffect(() => {
    if (selectedWorkflowId != null) {
      localStorage.setItem("trade_events_selected_workflow", String(selectedWorkflowId));
    }
  }, [selectedWorkflowId]);

  useEffect(() => {
    localStorage.setItem("trade_graph_positions", JSON.stringify(graphOverrides));
  }, [graphOverrides]);

  useEffect(() => {
    void loadReport();
  }, []);

  useEffect(() => {
    if (page === "report" && !reportPage) void loadReport();
    if (page === "events" && !eventsPage) void loadEvents();
    if (page === "kg" && !kgPage) void loadKG();
  }, [page]);

  useEffect(() => {
    if (page !== "report" && page !== "events") return;
    const source = new EventSource(`/api/runtime/stream?scope=${page}`);
    source.onmessage = (event) => {
      try {
        JSON.parse(event.data);
        if (refreshTimerRef.current) window.clearTimeout(refreshTimerRef.current);
        refreshTimerRef.current = window.setTimeout(() => {
          if (page === "events") {
            void loadEvents();
          } else {
            void loadReport();
          }
        }, 350);
      } catch {
        // ignore malformed rows
      }
    };
    source.onerror = () => {
      source.close();
    };
    return () => {
      source.close();
      if (refreshTimerRef.current) {
        window.clearTimeout(refreshTimerRef.current);
        refreshTimerRef.current = null;
      }
    };
  }, [page]);

  useEffect(() => {
    if (page !== "events") return;
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

  async function loadReport() {
    setLoading((prev) => ({ ...prev, report: true }));
    try {
      setReportPage(await apiFetch("/api/report-page"));
    } finally {
      setLoading((prev) => ({ ...prev, report: false }));
    }
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

  async function loadKG() {
    setLoading((prev) => ({ ...prev, kg: true }));
    try {
      setKgPage(await apiFetch("/api/kg-page"));
    } finally {
      setLoading((prev) => ({ ...prev, kg: false }));
    }
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
    if (page === "events") void loadEvents();
    if (page === "report") void loadReport();
  }

  async function rerunNode(rootEventId: number, dagId: number, mode: "self" | "upstream" | "downstream" | "full" = "self") {
    await apiFetch(`/api/workflows/${rootEventId}/rerun-node`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dag_id: dagId, mode }),
    });
    pushToast(`${t("rerun")}: ${dagId} · ${mode}`);
    await loadEvents();
    await loadReport();
  }

  async function runDagNode(dagId: number, mode: "self" | "upstream" | "downstream" | "full" = "self") {
    await apiFetch(`/api/dag/${dagId}/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode, payload: {} }),
    });
    pushToast(`run: ${dagId} · ${mode}`);
    await loadEvents();
    await loadReport();
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

  async function refreshCurrent() {
    if (page === "report") return loadReport();
    if (page === "events") return loadEvents();
    return loadKG();
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

  function renderReport() {
    if (loading.report && !reportPage) return <div className="empty">{t("loading")}</div>;
    if (!reportPage) return <div className="empty">{t("noData")}</div>;
    const conclusion = reportPage.conclusion || {};
    const progress = reportPage.progress || {};
    const health = reportPage.data_health || {};
    return (
      <div className="page">
        <section className="panel wide">
          <div className="panel-title">{t("reason")}</div>
          <div className="summary">
            <div className="summary-card">
              <div className="stat-label">{t("overall")}</div>
              <div className="stat-value">{conclusion.headline || "-"}</div>
              <div className={`pill ${statusClass(conclusion.gate_status)}`}>{conclusion.gate_status || "-"}</div>
            </div>
            <div className="summary-card">
              <div className="stat-label">{t("reason")}</div>
              <div className="stat-value">{shortText(conclusion.reason_summary || "-")}</div>
              <div className="muted-line">{(conclusion.reasons || []).slice(0, 3).map((item: any) => item.reason || item).join(" / ") || "-"}</div>
            </div>
          </div>
          <div className="cards">
            <div className="stat-card">
              <div className="stat-label">{t("operational")}</div>
              <div className="stat-value">
                <span className={`pill ${statusClass(conclusion.operational_status)}`}>{conclusion.operational_status || "-"}</span>
              </div>
            </div>
            <div className="stat-card">
              <div className="stat-label">{t("research")}</div>
              <div className="stat-value">
                <span className={`pill ${statusClass(conclusion.research_status)}`}>{conclusion.research_status || "-"}</span>
              </div>
            </div>
            <div className="stat-card">
              <div className="stat-label">{t("workflowProgress")}</div>
              <div className="stat-value">{progress.workflow_ok ?? 0}/{progress.workflow_total ?? 0}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">{t("agenda")}</div>
              <div className="stat-value">{(reportPage.agenda || []).length}</div>
            </div>
          </div>
        </section>

        <section className="panel-grid">
          <div className="panel">
            <div className="panel-title">{t("runActions")}</div>
            <div className="flow-buttons">
              <button className="button-card" onClick={() => void runTarget("sync")}>{t("runSync")}</button>
              <button className="button-card" onClick={() => void runTarget("close")}>{t("runClose")}</button>
              <button className="button-card" onClick={() => void runTarget("evening")}>{t("runEvening")}</button>
              <button className="button-card" onClick={() => void runTarget("agenda")}>{t("runAgenda")}</button>
            </div>
          </div>
          <div className="panel">
            <div className="panel-title">{t("rootCauses")}</div>
            <div className="list-stack">
              {(reportPage.root_causes || []).length ? (reportPage.root_causes || []).map((row: any) => (
                <div key={row.root_event_id} className="list-card">
                  <div className={`pill ${statusClass(row.status)}`}>{row.status}</div>
                  <div>{row.title || row.topic}</div>
                  <div className="error-text">{shortText(row.root_cause?.message || "-", 200)}</div>
                </div>
              )) : <div className="list-card">{t("noRootCause")}</div>}
            </div>
          </div>
        </section>

        <section className="panel-grid">
          <div className="panel">
            <div className="panel-title">{t("modelSignals")}</div>
            {renderSignals(reportPage.top_signals?.model_score || [], "model_score")}
          </div>
          <div className="panel">
            <div className="panel-title">{t("kgSignals")}</div>
            {renderSignals(reportPage.top_signals?.event_kg_score || [], "event_kg_score")}
          </div>
        </section>

        <section className="panel-grid">
          <div className="panel">
            <div className="panel-title">{t("todayEvents")}</div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Type</th>
                    <th>Magnitude</th>
                    <th>Summary</th>
                  </tr>
                </thead>
                <tbody>
                  {(reportPage.today_events || []).slice(0, 12).map((row: any) => (
                    <tr key={row.event_id}>
                      <td>{row.event_date}</td>
                      <td>{row.event_type}</td>
                      <td>{row.magnitude}</td>
                      <td>{shortText(row.summary, 90)}</td>
                    </tr>
                  ))}
                  {!reportPage.today_events?.length && (
                    <tr><td colSpan={4} className="empty">{t("noData")}</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
          <div className="panel">
            <div className="panel-title">{t("plannedEvents")}</div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>When</th>
                    <th>Type</th>
                    <th>Importance</th>
                    <th>Title</th>
                  </tr>
                </thead>
                <tbody>
                  {(reportPage.planned_events || []).slice(0, 12).map((row: any) => (
                    <tr key={row.planned_event_id}>
                      <td>{formatDateTime(row.scheduled_at)}</td>
                      <td>{row.event_type}</td>
                      <td><span className={`pill ${statusClass(row.importance === "high" ? "running" : "partial")}`}>{row.importance}</span></td>
                      <td>{shortText(row.title, 90)}</td>
                    </tr>
                  ))}
                  {!reportPage.planned_events?.length && (
                    <tr><td colSpan={4} className="empty">{t("noData")}</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </section>

        <section className="panel wide">
          <div className="panel-title">{t("dataHealth")}</div>
          <div className="cards">
            <div className="stat-card">
              <div className="stat-label">OK</div>
              <div className="stat-value">{health.summary?.ok ?? 0}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Partial</div>
              <div className="stat-value">{health.summary?.partial ?? 0}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Error</div>
              <div className="stat-value">{health.summary?.error ?? 0}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">As Of</div>
              <div className="stat-value">{health.as_of || "-"}</div>
            </div>
          </div>
          <div className="split-grid">
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Dataset</th>
                    <th>Status</th>
                    <th>Freshness</th>
                    <th>Coverage</th>
                    <th>Lineage</th>
                  </tr>
                </thead>
                <tbody>
                  {(health.datasets || []).slice(0, 10).map((row: any) => (
                    <tr key={row.id}>
                      <td>{row.name}</td>
                      <td><span className={`pill ${statusClass(row.status)}`}>{row.status}</span></td>
                      <td>{row.freshness_date || "-"}</td>
                      <td>{row.coverage_pct == null ? "-" : `${Math.round(row.coverage_pct * 1000) / 10}%`}</td>
                      <td>{shortText(row.lineage, 70)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="list-stack">
              {(health.highlights || []).map((item: any, index: number) => (
                <div key={`highlight-${index}`} className="list-card">
                  <div className="stat-label">{item.kind}</div>
                  <div>{item.title}</div>
                  <div className="stat-value">{item.value}</div>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="panel wide">
          <div className="panel-title">{t("recentEvents")}</div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Topic</th>
                  <th>Status</th>
                  <th>Created</th>
                  <th>Error</th>
                </tr>
              </thead>
              <tbody>
                {(reportPage.recent_events || []).map((row: any) => (
                  <tr key={row.id}>
                    <td>{row.id}</td>
                    <td>{row.topic}</td>
                    <td><span className={`pill ${statusClass(row.status)}`}>{row.status}</span></td>
                    <td>{formatDateTime(row.created_at)}</td>
                    <td>{shortText(row.error, 90)}</td>
                  </tr>
                ))}
                {!reportPage.recent_events?.length && (
                  <tr><td colSpan={5} className="empty">{t("noData")}</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
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
              const midX = edge.x1 + Math.max(32, (edge.x2 - edge.x1) / 2);
              const path = `M ${edge.x1} ${edge.y1} C ${midX} ${edge.y1}, ${midX} ${edge.y2}, ${edge.x2} ${edge.y2}`;
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
    const upstream = rows.filter((item) => String(item.emits || "") && String(item.emits || "") === String(row.source || ""));
    const downstream = rows.filter((item) => String(item.source || "") && String(item.source || "") === String(row.emits || ""));
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
          <div className="list-card flyout-card">
            <div className="panel-title">{t("upstream")}</div>
            {(upstream.length ? upstream : [{ job_name: row.source || "-", stage: "topic", status: row.last_source_event?.status || "pending" }]).map((item: any, index: number) => (
              <div key={`up-${index}`} className="muted-line">{item.job_name || item.source || item}</div>
            ))}
          </div>
          <div className="list-card flyout-card">
            <div className="panel-title">{t("downstream")}</div>
            {(downstream.length ? downstream : [{ job_name: row.emits || "-", stage: "topic", status: "pending" }]).map((item: any, index: number) => (
              <div key={`down-${index}`} className="muted-line">{item.job_name || item.source || item}</div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  function renderEvents() {
    if (loading.events && !eventsPage) return <div className="empty">{t("loading")}</div>;
    if (!eventsPage) return <div className="empty">{t("noData")}</div>;
    const selectedWorkflow = workflowDetail || eventsPage.focus || null;
    const workflowFailedNodes = workflowRows.filter((row) => ["error", "partial"].includes(String(row.status || "")));
    const failureList = workflowFailedNodes.length ? workflowFailedNodes : (eventsPage.failed_nodes || []);
    const workflowNodeIds = new Set(
      workflowRows.map((row) => Number(row.dag_id ?? row.id ?? 0)).filter((value) => value > 0),
    );
    const focusTitle = selectedWorkflow
      ? `${selectedWorkflow.title || selectedWorkflow.topic || "workflow"} #${selectedWorkflow.root_event_id || "-"}`
      : t("focusWorkflow");
    const focusRootCause = shortText(
      selectedWorkflow?.root_cause?.message
      || selectedWorkflow?.root_cause?.error
      || failureList[0]?.error_detail
      || "-",
      220,
    );
    return (
      <div className="page">
        <section className="panel wide">
          <div className="panel-title">{t("finalResults")}</div>
          <div className="cards">
            <div className="stat-card">
              <div className="stat-label">{t("liveWorkflows")}</div>
              <div className="stat-value">{(eventsPage.workflows || []).filter((row: any) => row.status === "running").length}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">{t("failedCount")}</div>
              <div className="stat-value">{(eventsPage.failed_nodes || []).length}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">{t("agendaCount")}</div>
              <div className="stat-value">{(eventsPage.due_agenda || []).length}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">{t("eventCount")}</div>
              <div className="stat-value">{(eventsPage.today_events || []).length}</div>
            </div>
          </div>
          <div className="muted-line">{t("restoreState")} · {t("dragHint")}</div>
          <div className="split-grid">
            <div className="table-wrap workflow-history-table">
              <table>
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Type</th>
                    <th>{t("status")}</th>
                    <th>Magnitude</th>
                    <th>Summary</th>
                  </tr>
                </thead>
                <tbody>
                  {(eventsPage.recent_market_events || []).slice(0, 12).map((row: any) => (
                    <tr key={`recent-market-${row.event_id || row.id}`}>
                      <td>{row.event_date || formatDateTime(row.created_at)}</td>
                      <td>{row.event_type || row.title || "-"}</td>
                      <td><span className={`pill ${statusClass(row.status || "ok")}`}>{row.status || "ok"}</span></td>
                      <td>{row.magnitude ?? "-"}</td>
                      <td>{shortText(row.summary || row.title, 88)}</td>
                    </tr>
                  ))}
                  {!eventsPage.recent_market_events?.length && (
                    <tr><td colSpan={5} className="empty">{t("noData")}</td></tr>
                  )}
                </tbody>
              </table>
            </div>
            <div className="list-stack">
              <div className="list-card">
                <div className="stat-label">{t("focusWorkflow")}</div>
                <div className="panel-title">{focusTitle}</div>
                <div className="badge-line">
                  <span className={`pill ${statusClass(selectedWorkflow?.status)}`}>{selectedWorkflow?.status || "-"}</span>
                  <span className="muted-line">
                    {selectedWorkflow?.progress?.completed ?? 0}/{selectedWorkflow?.progress?.total ?? 0}
                  </span>
                </div>
                <div className="muted-line">
                  {formatDateTime(selectedWorkflow?.created_at)} → {formatDateTime(selectedWorkflow?.processed_at)}
                </div>
              </div>
              <div className="list-card">
                <div className="stat-label">{t("rootCauses")}</div>
                <div className={`muted-line ${focusRootCause !== "-" ? "error-text" : ""}`}>{focusRootCause}</div>
              </div>
              <div className="list-card">
                <div className="stat-label">{t("focusHint")}</div>
                <div className="muted-line">{t("dragHint")}</div>
              </div>
            </div>
          </div>
        </section>

        <section className="panel wide">
          <div className="panel-title">{t("globalDag")}</div>
          <div className="muted-line">{focusTitle}</div>
          {renderDagGraph(globalGraph, {
            graphKey: globalGraphKey,
            selectedKey: selectedDagKey,
            onSelect: setSelectedDagKey,
            onHoverStart: openDagFlyout,
            onHoverEnd: scheduleDagFlyoutClose,
            onPin: togglePinnedFlyout,
            onNodeMove: (nodeKey, x, y) => updateGraphNodePosition(globalGraphKey, nodeKey, x, y),
            focusDagIds,
            onExecute: (node) => {
              if (!node.dagId) return;
              if (selectedWorkflow?.root_event_id && workflowNodeIds.has(node.dagId)) {
                void rerunNode(selectedWorkflow.root_event_id, node.dagId, "self");
                return;
              }
              void runDagNode(node.dagId, "self");
            },
            flyout: renderNodeFlyout(
              globalGraph,
              selectedGlobalGraphNode,
              (eventsPage.dag?.nodes || []) as DagNode[],
              { rootEventId: selectedWorkflow?.root_event_id, readOnly: false, workflowNodeIds },
            ),
          })}
        </section>

        <section className="panel-grid history-grid">
          <div className="panel">
            <div className="panel-title">{t("workflowHistory")}</div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Topic</th>
                    <th>{t("status")}</th>
                    <th>{t("progress")}</th>
                    <th>Created</th>
                    <th>Finished</th>
                  </tr>
                </thead>
                <tbody>
                  {(eventsPage.workflows || []).map((row: any) => (
                    <tr
                      key={row.root_event_id}
                      className={`clickable-row ${selectedWorkflow?.root_event_id === row.root_event_id ? "active-row" : ""}`}
                      onClick={() => void loadWorkflowDetail(row.root_event_id)}
                    >
                      <td>{row.root_event_id}</td>
                      <td>{row.title || row.topic}</td>
                      <td><span className={`pill ${statusClass(row.status)}`}>{row.status}</span></td>
                      <td>{row.progress?.completed ?? 0}/{row.progress?.total ?? 0}</td>
                      <td>{formatDateTime(row.created_at)}</td>
                      <td>{formatDateTime(row.processed_at)}</td>
                    </tr>
                  ))}
                  {!eventsPage.workflows?.length && (
                    <tr><td colSpan={6} className="empty">{t("noData")}</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
          <div className="panel">
            <div className="panel-title">{t("failedNodes")}</div>
            <div className="list-stack">
              {failureList.length ? failureList.map((row: any) => (
                <div key={`failed-${row.id || row.dag_id || row.job_name}`} className="list-card">
                  <div className="node-header">
                    <div>
                      <div className="panel-title">{row.job_name}</div>
                      <div className="muted-line">{row.source || row.stage || "-"}</div>
                    </div>
                    <span className={`pill ${statusClass(row.status || "error")}`}>{row.status || "error"}</span>
                  </div>
                  <div className="error-text">{shortText(row.error_detail, 200)}</div>
                </div>
              )) : <div className="empty">{t("noData")}</div>}
            </div>
          </div>
        </section>

        <section className="panel-grid">
          <div className="panel">
            <div className="panel-title">{t("dailyEvents")}</div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Topic</th>
                    <th>{t("status")}</th>
                    <th>{t("error")}</th>
                  </tr>
                </thead>
                <tbody>
                  {(eventsPage.recent_market_events || []).slice(0, 16).map((row: any) => (
                    <tr key={`recent-market-${row.event_id || row.id}`}>
                      <td>{row.event_date || formatDateTime(row.created_at)}</td>
                      <td>{shortText(row.summary || row.event_type || row.title, 72)}</td>
                      <td><span className={`pill ${statusClass(row.status || "ok")}`}>{row.status || "ok"}</span></td>
                      <td>{shortText(row.error || "-", 90)}</td>
                    </tr>
                  ))}
                  {!eventsPage.recent_market_events?.length && (
                    <tr><td colSpan={4} className="empty">{t("noData")}</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
          <div className="panel">
            <div className="panel-title">{t("todayEvents")}</div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Type</th>
                    <th>Magnitude</th>
                    <th>Summary</th>
                  </tr>
                </thead>
                <tbody>
                  {(eventsPage.today_events || []).map((row: any) => (
                    <tr key={row.event_id}>
                      <td>{row.event_date}</td>
                      <td>{row.event_type}</td>
                      <td>{row.magnitude}</td>
                      <td>{shortText(row.summary, 90)}</td>
                    </tr>
                  ))}
                  {!eventsPage.today_events?.length && (
                    <tr><td colSpan={4} className="empty">{t("noData")}</td></tr>
                  )}
                </tbody>
              </table>
            </div>
            <div className="panel-title" style={{ marginTop: "14px" }}>{t("agenda")}</div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Run At</th>
                    <th>Phase</th>
                    <th>{t("status")}</th>
                    <th>Title</th>
                  </tr>
                </thead>
                <tbody>
                  {(eventsPage.due_agenda || []).map((row: any) => (
                    <tr key={row.agenda_id}>
                      <td>{formatDateTime(row.run_at)}</td>
                      <td>{row.phase}</td>
                      <td><span className={`pill ${statusClass(row.status)}`}>{row.status}</span></td>
                      <td>{shortText(row.title, 90)}</td>
                    </tr>
                  ))}
                  {!eventsPage.due_agenda?.length && (
                    <tr><td colSpan={4} className="empty">{t("noData")}</td></tr>
                  )}
                </tbody>
              </table>
            </div>
            <div className="panel-title" style={{ marginTop: "14px" }}>{t("plannedEvents")}</div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>When</th>
                    <th>Type</th>
                    <th>Importance</th>
                    <th>Title</th>
                  </tr>
                </thead>
                <tbody>
                  {(eventsPage.planned_events || []).slice(0, 12).map((row: any) => (
                    <tr key={`planned-${row.planned_event_id}`}>
                      <td>{formatDateTime(row.scheduled_at)}</td>
                      <td>{row.event_type}</td>
                      <td><span className={`pill ${statusClass(row.importance === "high" ? "running" : "partial")}`}>{row.importance}</span></td>
                      <td>{shortText(row.title, 88)}</td>
                    </tr>
                  ))}
                  {!eventsPage.planned_events?.length && (
                    <tr><td colSpan={4} className="empty">{t("noData")}</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </section>
      </div>
    );
  }

  function renderKG() {
    if (loading.kg && !kgPage) return <div className="empty">{t("loading")}</div>;
    if (!kgPage) return <div className="empty">{t("noData")}</div>;
    return (
      <div className="page">
        <section className="panel wide">
          <div className="panel-title">{t("activeGraph")}</div>
          <div className="cards">
            <div className="stat-card">
              <div className="stat-label">{t("snapshot")}</div>
              <div className="stat-value">{kgPage.snapshot?.version || "-"}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Nodes</div>
              <div className="stat-value">{kgPage.snapshot?.node_count ?? 0}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Edges</div>
              <div className="stat-value">{kgPage.snapshot?.edge_count ?? 0}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Event Map</div>
              <div className="stat-value">{kgPage.snapshot?.event_map_count ?? 0}</div>
            </div>
          </div>
          <div className="muted-line">{t("generatedAt")}: {formatDateTime(kgPage.snapshot?.generated_at)}</div>
        </section>

        <section className="panel-grid">
          <div className="panel">
            <div className="panel-title">{t("relationTypes")}</div>
            <div className="list-stack">
              {(kgPage.relation_types || []).map((row: any) => (
                <div key={row.rel_type} className="list-card">
                  <div className="stat-label">{row.rel_type}</div>
                  <div className="stat-value">{row.relation_count}</div>
                </div>
              ))}
              {!kgPage.relation_types?.length && <div className="empty">{t("noData")}</div>}
            </div>
          </div>
          <div className="panel">
            <div className="panel-title">{t("topPropagation")}</div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th>Count</th>
                    <th>Avg KG</th>
                    <th>Date</th>
                  </tr>
                </thead>
                <tbody>
                  {(kgPage.top_symbols || []).map((row: any) => (
                    <tr key={row.symbol}>
                      <td>{row.symbol}</td>
                      <td>{row.propagation_count}</td>
                      <td>{row.avg_kg_score}</td>
                      <td>{row.latest_event_date}</td>
                    </tr>
                  ))}
                  {!kgPage.top_symbols?.length && (
                    <tr><td colSpan={4} className="empty">{t("noData")}</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </section>

        <section className="panel wide">
          <div className="panel-title">{t("activeRelations")}</div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>From</th>
                  <th>To</th>
                  <th>Type</th>
                  <th>Weight</th>
                  <th>Confidence</th>
                  <th>Source</th>
                </tr>
              </thead>
              <tbody>
                {(kgPage.active_relations || []).map((row: any) => (
                  <tr key={`rel-${row.id}`}>
                    <td>{row.from_entity}</td>
                    <td>{row.to_entity}</td>
                    <td>{row.rel_type}</td>
                    <td>{row.weight}</td>
                    <td>{row.confidence}</td>
                    <td>{row.source || "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="panel wide">
          <div className="panel-title">{t("candidates")}</div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>From</th>
                  <th>To</th>
                  <th>Type</th>
                  <th>Weight</th>
                  <th>Confidence</th>
                  <th>Samples</th>
                  <th>Source</th>
                </tr>
              </thead>
              <tbody>
                {(kgPage.candidates || []).map((row: any) => (
                  <tr key={`cand-${row.id}`}>
                    <td>{row.from_entity}</td>
                    <td>{row.to_entity}</td>
                    <td>{row.rel_type}</td>
                    <td>{row.weight}</td>
                    <td>{row.confidence}</td>
                    <td>{row.sample_count}</td>
                    <td>{row.source || "-"}</td>
                  </tr>
                ))}
                {!kgPage.candidates?.length && (
                  <tr><td colSpan={7} className="empty">{t("noData")}</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
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

      {page === "report" && renderReport()}
      {page === "events" && renderEvents()}
      {page === "kg" && renderKG()}

      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}

export default App;
