import { useEffect, useState } from "react";

type Locale = "zh-CN" | "en";
type PageKey = "report" | "events" | "kg";

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
    failedNodes: "失败节点",
    rerun: "重跑节点",
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
    failedNodes: "Failed nodes",
    rerun: "Rerun node",
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

function App() {
  const [locale, setLocale] = useState<Locale>((localStorage.getItem("trade_locale") as Locale) || "zh-CN");
  const [page, setPage] = useState<PageKey>("report");
  const [reportPage, setReportPage] = useState<any>(null);
  const [eventsPage, setEventsPage] = useState<any>(null);
  const [kgPage, setKgPage] = useState<any>(null);
  const [workflowDetail, setWorkflowDetail] = useState<any>(null);
  const [toast, setToast] = useState("");
  const [loading, setLoading] = useState<Record<string, boolean>>({});

  const t = (key: TranslationKey) => I18N[locale][key];

  useEffect(() => {
    localStorage.setItem("trade_locale", locale);
  }, [locale]);

  useEffect(() => {
    void loadReport();
  }, []);

  useEffect(() => {
    if (page === "report" && !reportPage) void loadReport();
    if (page === "events" && !eventsPage) void loadEvents();
    if (page === "kg" && !kgPage) void loadKG();
  }, [page]);

  useEffect(() => {
    const source = new EventSource("/api/events/stream");
    source.onmessage = (event) => {
      try {
        const row = JSON.parse(event.data);
        setReportPage((prev: any) => {
          if (!prev) return prev;
          const recent = [row, ...(prev.recent_events || []).filter((item: any) => item.id !== row.id)].slice(0, 18);
          return { ...prev, recent_events: recent };
        });
      } catch {
        // ignore malformed rows
      }
    };
    return () => source.close();
  }, []);

  function pushToast(message: string) {
    setToast(message);
    window.setTimeout(() => setToast(""), 2400);
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
      setWorkflowDetail(payload?.focus || null);
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

  async function loadWorkflowDetail(rootEventId: number) {
    setLoading((prev) => ({ ...prev, workflow: true }));
    try {
      setWorkflowDetail(await apiFetch(`/api/workflows/${rootEventId}`));
    } finally {
      setLoading((prev) => ({ ...prev, workflow: false }));
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

  async function rerunNode(rootEventId: number, dagId: number) {
    await apiFetch(`/api/workflows/${rootEventId}/rerun-node`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dag_id: dagId }),
    });
    pushToast(`${t("rerun")}: ${dagId}`);
    await loadEvents();
    await loadReport();
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
              )) : <div className="empty">{t("noData")}</div>}
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

  function renderWorkflowNodes() {
    if (!workflowDetail?.nodes?.length) return <div className="empty">{t("noData")}</div>;
    return (
      <div className="node-grid">
        {workflowDetail.nodes.map((node: any) => (
          <div key={`${workflowDetail.root_event_id}-${node.dag_id}`} className={`node-card ${statusClass(node.status)}`}>
            <div className="node-header">
              <div>
                <div className="panel-title">{node.job_name}</div>
                <div className="muted-line">{node.stage} · {node.source}</div>
              </div>
              <span className={`pill ${statusClass(node.status)}`}>{node.status}</span>
            </div>
            <div className="muted-line">emits: {node.emits || "-"}</div>
            <div className="muted-line">run: {formatDateTime(node.job_run?.started_at || node.source_event?.created_at)}</div>
            <div className={node.error ? "error-text" : "muted-line"}>{shortText(node.error || node.job_run?.result_summary, 180)}</div>
            <div className="node-actions">
              <button onClick={() => void rerunNode(workflowDetail.root_event_id, node.dag_id)}>{t("rerun")}</button>
            </div>
          </div>
        ))}
      </div>
    );
  }

  function renderEvents() {
    if (loading.events && !eventsPage) return <div className="empty">{t("loading")}</div>;
    if (!eventsPage) return <div className="empty">{t("noData")}</div>;
    return (
      <div className="page">
        <section className="panel wide">
          <div className="panel-title">{t("runActions")}</div>
          <div className="flow-buttons inline-actions">
            <button onClick={() => void runTarget("sync")}>{t("runSync")}</button>
            <button onClick={() => void runTarget("close")}>{t("runClose")}</button>
            <button onClick={() => void runTarget("evening")}>{t("runEvening")}</button>
            <button onClick={() => void runTarget("agenda")}>{t("runAgenda")}</button>
          </div>
        </section>

        <section className="panel-grid">
          <div className="panel">
            <div className="panel-title">{t("workflows")}</div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Topic</th>
                    <th>{t("status")}</th>
                    <th>{t("progress")}</th>
                  </tr>
                </thead>
                <tbody>
                  {(eventsPage.workflows || []).map((row: any) => (
                    <tr key={row.root_event_id} className="clickable-row" onClick={() => void loadWorkflowDetail(row.root_event_id)}>
                      <td>{row.root_event_id}</td>
                      <td>{row.title || row.topic}</td>
                      <td><span className={`pill ${statusClass(row.status)}`}>{row.status}</span></td>
                      <td>{row.progress?.completed ?? 0}/{row.progress?.total ?? 0}</td>
                    </tr>
                  ))}
                  {!eventsPage.workflows?.length && (
                    <tr><td colSpan={4} className="empty">{t("noData")}</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
          <div className="panel">
            <div className="panel-title">{t("failedNodes")}</div>
            <div className="list-stack">
              {(eventsPage.failed_nodes || []).length ? (eventsPage.failed_nodes || []).map((row: any) => (
                <div key={`failed-${row.id}`} className="list-card">
                  <div className="panel-title">{row.job_name}</div>
                  <div className="muted-line">{row.source}</div>
                  <div className="error-text">{shortText(row.error_detail, 180)}</div>
                </div>
              )) : <div className="empty">{t("noData")}</div>}
            </div>
          </div>
        </section>

        <section className="panel wide">
          <div className="panel-title">{t("focusWorkflow")}</div>
          {loading.workflow ? <div className="empty">{t("loading")}</div> : renderWorkflowNodes()}
        </section>

        <section className="panel wide">
          <div className="panel-title">{t("dagRuntime")}</div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Job</th>
                  <th>{t("stage")}</th>
                  <th>{t("source")}</th>
                  <th>{t("status")}</th>
                  <th>Recent</th>
                  <th>{t("error")}</th>
                </tr>
              </thead>
              <tbody>
                {(eventsPage.dag?.nodes || []).map((row: any) => (
                  <tr key={`dag-${row.id}`}>
                    <td>{row.job_name}</td>
                    <td>{row.stage}</td>
                    <td>{row.source}</td>
                    <td><span className={`pill ${statusClass(row.status)}`}>{row.status}</span></td>
                    <td>{row.recent_ok_count ?? 0}/{(row.recent_ok_count ?? 0) + (row.recent_error_count ?? 0)}</td>
                    <td>{shortText(row.error_detail, 120)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
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
          </div>
          <div className="panel">
            <div className="panel-title">{t("agenda")}</div>
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
