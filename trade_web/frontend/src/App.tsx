import { useEffect, useState } from "react";

type Locale = "zh-CN" | "en";
type TabKey = "overview" | "data-health" | "pipeline" | "workflows" | "calendar" | "agenda" | "models" | "trigger";

type Dict = Record<string, string>;

const I18N: Record<Locale, Dict> = {
  "zh-CN": {
    title: "TradeDB Console",
    subtitle: "独立 Web 项目，面向事件 / DAG / Agenda / KG 的交易运行台",
    language: "语言",
    overview: "总览",
    dataHealth: "数据健康",
    pipeline: "流程",
    workflows: "工作流",
    calendar: "日历",
    agenda: "议程",
    models: "模型",
    trigger: "触发",
    refresh: "刷新",
    run: "运行",
    publish: "发布",
    qualityGate: "质量门禁",
    operational: "运营态",
    research: "研究态",
    dueAgenda: "到期 Agenda",
    modelsLoaded: "已加载模型",
    rootCauses: "根因 / 错误节点",
    recentEvents: "最近事件流",
    topSignals: "重点信号",
    recentWorkflows: "最近工作流",
    dataHealthSummary: "数据健康摘要",
    dataHealthDatasets: "数据健康数据集",
    plannedEvents: "Planned Events",
    noData: "暂无数据",
    loading: "加载中...",
    triggerWorkflow: "运行工作流",
    manualTrigger: "手工 Topic 触发",
    modelScore: "模型分",
    kgScore: "事件 KG 分",
  },
  en: {
    title: "TradeDB Console",
    subtitle: "Standalone web project for event / DAG / agenda / KG operations",
    language: "Language",
    overview: "Overview",
    dataHealth: "Data Health",
    pipeline: "Pipeline",
    workflows: "Workflows",
    calendar: "Calendar",
    agenda: "Agenda",
    models: "Models",
    trigger: "Trigger",
    refresh: "Refresh",
    run: "Run",
    publish: "Publish",
    qualityGate: "Quality Gate",
    operational: "Operational",
    research: "Research",
    dueAgenda: "Due Agenda",
    modelsLoaded: "Models Loaded",
    rootCauses: "Root Causes / Failed Nodes",
    recentEvents: "Recent Event Stream",
    topSignals: "Top Signals",
    recentWorkflows: "Recent Workflows",
    dataHealthSummary: "Data Health Summary",
    dataHealthDatasets: "Data Health Datasets",
    plannedEvents: "Planned Events",
    noData: "No data",
    loading: "Loading...",
    triggerWorkflow: "Run Workflow",
    manualTrigger: "Manual Topic Trigger",
    modelScore: "Model Score",
    kgScore: "Event KG Score",
  },
};

const RUN_TARGETS = ["morning", "intraday", "evening", "close", "sync", "evaluate", "agenda"];

const TABS: Array<{ key: TabKey; label: keyof typeof I18N["zh-CN"] }> = [
  { key: "overview", label: "overview" },
  { key: "data-health", label: "dataHealth" },
  { key: "pipeline", label: "pipeline" },
  { key: "workflows", label: "workflows" },
  { key: "calendar", label: "calendar" },
  { key: "agenda", label: "agenda" },
  { key: "models", label: "models" },
  { key: "trigger", label: "trigger" },
];

function statusClass(status: string | undefined | null) {
  const value = String(status || "unknown").toLowerCase();
  if (["ok", "done", "active"].includes(value)) return "ok";
  if (["partial"].includes(value)) return "partial";
  if (["error", "failed", "degraded", "blocked_by_dependency"].includes(value)) return "error";
  if (["running", "live"].includes(value)) return "running";
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

function App() {
  const [locale, setLocale] = useState<Locale>((localStorage.getItem("trade_locale") as Locale) || "zh-CN");
  const [tab, setTab] = useState<TabKey>("overview");
  const [overview, setOverview] = useState<any>(null);
  const [dataHealth, setDataHealth] = useState<any>(null);
  const [pipeline, setPipeline] = useState<any>(null);
  const [workflowList, setWorkflowList] = useState<any[]>([]);
  const [workflowDetail, setWorkflowDetail] = useState<any>(null);
  const [calendar, setCalendar] = useState<any>(null);
  const [agenda, setAgenda] = useState<any[]>([]);
  const [models, setModels] = useState<any[]>([]);
  const [triggerTopic, setTriggerTopic] = useState("gate.morning");
  const [triggerPayload, setTriggerPayload] = useState("{}");
  const [toast, setToast] = useState<string>("");
  const [loading, setLoading] = useState<Record<string, boolean>>({});

  const t = (key: keyof typeof I18N["zh-CN"]) => I18N[locale][key];

  useEffect(() => {
    localStorage.setItem("trade_locale", locale);
  }, [locale]);

  useEffect(() => {
    const source = new EventSource("/api/events/stream");
    source.onmessage = (event) => {
      try {
        const row = JSON.parse(event.data);
        setOverview((prev: any) => {
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

  useEffect(() => {
    void loadOverview();
  }, []);

  useEffect(() => {
    if (tab === "overview" && !overview) void loadOverview();
    if (tab === "data-health" && !dataHealth) void loadDataHealth();
    if (tab === "pipeline" && !pipeline) void loadPipeline();
    if (tab === "workflows" && !workflowList.length) void loadWorkflows();
    if (tab === "calendar" && !calendar) void loadCalendar();
    if (tab === "agenda" && !agenda.length) void loadAgenda();
    if (tab === "models" && !models.length) void loadModels();
  }, [tab]);

  function pushToast(message: string) {
    setToast(message);
    window.setTimeout(() => setToast(""), 2400);
  }

  async function loadOverview() {
    setLoading((prev) => ({ ...prev, overview: true }));
    try {
      setOverview(await apiFetch("/api/overview"));
    } finally {
      setLoading((prev) => ({ ...prev, overview: false }));
    }
  }

  async function loadDataHealth() {
    setLoading((prev) => ({ ...prev, dataHealth: true }));
    try {
      setDataHealth(await apiFetch("/api/data-health"));
    } finally {
      setLoading((prev) => ({ ...prev, dataHealth: false }));
    }
  }

  async function loadPipeline() {
    setLoading((prev) => ({ ...prev, pipeline: true }));
    try {
      setPipeline(await apiFetch("/api/dag/runtime?limit=240"));
    } finally {
      setLoading((prev) => ({ ...prev, pipeline: false }));
    }
  }

  async function loadWorkflows() {
    setLoading((prev) => ({ ...prev, workflows: true }));
    try {
      const rows = await apiFetch<any[]>("/api/workflows?limit=15");
      setWorkflowList(rows);
      if (rows[0]) {
        setWorkflowDetail(await apiFetch(`/api/workflows/${rows[0].root_event_id}`));
      }
    } finally {
      setLoading((prev) => ({ ...prev, workflows: false }));
    }
  }

  async function loadWorkflowDetail(rootEventId: number) {
    setWorkflowDetail(await apiFetch(`/api/workflows/${rootEventId}`));
  }

  async function loadCalendar() {
    setLoading((prev) => ({ ...prev, calendar: true }));
    try {
      setCalendar(await apiFetch("/api/calendar?days=5"));
    } finally {
      setLoading((prev) => ({ ...prev, calendar: false }));
    }
  }

  async function loadAgenda() {
    setLoading((prev) => ({ ...prev, agenda: true }));
    try {
      setAgenda(await apiFetch<any[]>("/api/agenda?limit=50"));
    } finally {
      setLoading((prev) => ({ ...prev, agenda: false }));
    }
  }

  async function loadModels() {
    setLoading((prev) => ({ ...prev, models: true }));
    try {
      setModels(await apiFetch<any[]>("/api/models"));
    } finally {
      setLoading((prev) => ({ ...prev, models: false }));
    }
  }

  async function runTarget(target: string) {
    await apiFetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target, payload: {}, limit: 10 }),
    });
    pushToast(`${t("run")}: ${target}`);
  }

  async function publishTopic() {
    await apiFetch("/api/trigger", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ topic: triggerTopic, payload: JSON.parse(triggerPayload || "{}") }),
    });
    pushToast(`${t("publish")}: ${triggerTopic}`);
  }

  return (
    <div className="shell">
      <header className="topbar">
        <div>
          <h1>{t("title")}</h1>
          <p>{t("subtitle")}</p>
        </div>
        <div className="topbar-actions">
          <select value={locale} onChange={(event) => setLocale(event.target.value as Locale)}>
            <option value="zh-CN">简体中文</option>
            <option value="en">English</option>
          </select>
          <button onClick={() => void loadOverview()}>{t("refresh")}</button>
        </div>
      </header>

      <nav className="tabs">
        {TABS.map((item) => (
          <button key={item.key} className={tab === item.key ? "tab active" : "tab"} onClick={() => setTab(item.key)}>
            {t(item.label)}
          </button>
        ))}
      </nav>

      <main className="page">
        {tab === "overview" && (
          <section className="panel-grid">
            <div className="panel wide">
              <div className="panel-title">{t("overview")}</div>
              {loading.overview || !overview ? (
                <div className="empty">{t("loading")}</div>
              ) : (
                <>
                  <div className="cards">
                    <StatCard label={t("qualityGate")} value={overview.conclusion?.gate_status} />
                    <StatCard label={t("operational")} value={overview.conclusion?.operational_status} />
                    <StatCard label={t("research")} value={overview.conclusion?.research_status} />
                    <StatCard label={t("dueAgenda")} value={String((overview.agenda || []).length)} />
                    <StatCard label={t("modelsLoaded")} value={String((overview.system?.inference_models || []).length)} />
                  </div>
                  <div className="summary">
                    <div className="summary-card">
                      <strong>{overview.conclusion?.headline}</strong>
                      <div>{overview.conclusion?.reason_summary || "-"}</div>
                    </div>
                    <div className="summary-card">
                      <strong>{t("topSignals")}</strong>
                      <div className="signal-columns">
                        <SignalList title={t("modelScore")} rows={overview.top_signals?.model_score || []} />
                        <SignalList title={t("kgScore")} rows={overview.top_signals?.event_kg_score || []} />
                      </div>
                    </div>
                  </div>
                </>
              )}
            </div>
            <div className="panel">
              <div className="panel-title">{t("rootCauses")}</div>
              {(overview?.root_causes || []).length ? (
                overview.root_causes.map((row: any) => (
                  <div key={row.root_event_id} className="list-card">
                    <strong>{row.title || row.topic}</strong>
                    <span className={`pill ${statusClass(row.status)}`}>{row.status}</span>
                    <div>{row.root_cause?.message || "-"}</div>
                  </div>
                ))
              ) : (
                <div className="empty">{t("noData")}</div>
              )}
            </div>
            <div className="panel">
              <div className="panel-title">{t("recentEvents")}</div>
              <Table
                columns={["id", "status", "topic", "handler", "created_at"]}
                rows={overview?.recent_events || []}
                formatters={{ created_at: formatDateTime }}
              />
            </div>
            <div className="panel">
              <div className="panel-title">{t("recentWorkflows")}</div>
              {(overview?.workflows || []).map((row: any) => (
                <button key={row.root_event_id} className="list-card button-card" onClick={() => { setTab("workflows"); void loadWorkflowDetail(row.root_event_id); }}>
                  <strong>{row.title || row.topic}</strong>
                  <div>{row.progress?.completed || 0}/{row.progress?.total || 0}</div>
                  <span className={`pill ${statusClass(row.status)}`}>{row.status}</span>
                </button>
              ))}
            </div>
          </section>
        )}

        {tab === "data-health" && (
          <section className="panel-grid">
            <div className="panel wide">
              <div className="panel-title">{t("dataHealthSummary")}</div>
              {loading["data-health"] || !dataHealth ? (
                <div className="empty">{t("loading")}</div>
              ) : (
                <>
                  <div className="cards">
                    <StatCard label="total" value={String(dataHealth.summary?.total || 0)} />
                    <StatCard label="ok" value={String(dataHealth.summary?.ok || 0)} />
                    <StatCard label="partial" value={String(dataHealth.summary?.partial || 0)} />
                    <StatCard label="error" value={String(dataHealth.summary?.error || 0)} />
                  </div>
                  <Table
                    columns={["name", "domain", "status", "freshness_date", "lag_days", "coverage_pct", "rows", "count"]}
                    rows={dataHealth.datasets || []}
                    formatters={{
                      lag_days: (value) => (value == null ? "-" : `${value}d`),
                      coverage_pct: (value) => (value == null ? "-" : `${(Number(value) * 100).toFixed(1)}%`),
                    }}
                  />
                </>
              )}
            </div>
          </section>
        )}

        {tab === "pipeline" && (
          <section className="panel-grid">
            <div className="panel wide">
              <div className="panel-title">{t("pipeline")}</div>
              {loading.pipeline || !pipeline ? (
                <div className="empty">{t("loading")}</div>
              ) : (
                <div className="node-grid">
                  {(pipeline.nodes || []).map((row: any) => (
                    <div key={row.id} className={`node-card ${statusClass(row.status)}`}>
                      <strong>{row.job_name}</strong>
                      <div>{row.source}</div>
                      <div>{row.description}</div>
                      <div>{formatDateTime(row.last_run?.started_at)}</div>
                      {row.error_detail ? <div className="error-text">{String(row.error_detail).slice(0, 180)}</div> : null}
                      <button onClick={() => void runTarget(row.source?.replace("gate.", "") || "sync")}>{t("run")}</button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </section>
        )}

        {tab === "workflows" && (
          <section className="panel-grid">
            <div className="panel">
              <div className="panel-title">{t("recentWorkflows")}</div>
              {loading.workflows ? (
                <div className="empty">{t("loading")}</div>
              ) : (
                workflowList.map((row) => (
                  <button key={row.root_event_id} className="list-card button-card" onClick={() => void loadWorkflowDetail(row.root_event_id)}>
                    <strong>{row.title || row.topic}</strong>
                    <div>{row.progress?.completed || 0}/{row.progress?.total || 0}</div>
                    <span className={`pill ${statusClass(row.status)}`}>{row.status}</span>
                  </button>
                ))
              )}
            </div>
            <div className="panel wide">
              <div className="panel-title">{t("workflows")}</div>
              {workflowDetail ? (
                <>
                  <div className="summary-card">
                    <strong>{workflowDetail.title || workflowDetail.topic}</strong>
                    <div>{workflowDetail.root_cause?.message || "-"}</div>
                  </div>
                  <div className="node-grid">
                    {(workflowDetail.nodes || []).map((node: any) => (
                      <div key={`${node.job_name}-${node.dag_id}`} className={`node-card ${statusClass(node.status)}`}>
                        <strong>{node.job_name}</strong>
                        <div>{node.stage}</div>
                        <div>{node.source}</div>
                        {node.error ? <div className="error-text">{String(node.error).slice(0, 200)}</div> : null}
                      </div>
                    ))}
                  </div>
                </>
              ) : (
                <div className="empty">{t("noData")}</div>
              )}
            </div>
          </section>
        )}

        {tab === "calendar" && (
          <section className="panel-grid">
            <div className="panel wide">
              <div className="panel-title">{t("calendar")}</div>
              {loading.calendar || !calendar ? (
                <div className="empty">{t("loading")}</div>
              ) : (
                <div className="split-grid">
                  <Table columns={["trade_date", "is_open", "pretrade_date", "session_am_open", "session_pm_open"]} rows={calendar.calendar || []} />
                  <Table columns={["scheduled_at", "event_type", "importance", "title"]} rows={calendar.planned_events || []} formatters={{ scheduled_at: formatDateTime }} />
                </div>
              )}
            </div>
          </section>
        )}

        {tab === "agenda" && (
          <section className="panel-grid">
            <div className="panel wide">
              <div className="panel-title">{t("agenda")}</div>
              {loading.agenda ? <div className="empty">{t("loading")}</div> : <Table columns={["agenda_id", "run_at", "phase", "status", "job_name", "title"]} rows={agenda} formatters={{ run_at: formatDateTime }} />}
            </div>
          </section>
        )}

        {tab === "models" && (
          <section className="panel-grid">
            <div className="panel wide">
              <div className="panel-title">{t("models")}</div>
              {loading.models ? <div className="empty">{t("loading")}</div> : <Table columns={["id", "model_name", "target_name", "backend", "trained_at", "promotion_state"]} rows={models} formatters={{ trained_at: formatDateTime }} />}
            </div>
          </section>
        )}

        {tab === "trigger" && (
          <section className="panel-grid">
            <div className="panel">
              <div className="panel-title">{t("triggerWorkflow")}</div>
              <div className="flow-buttons">
                {RUN_TARGETS.map((item) => (
                  <button key={item} onClick={() => void runTarget(item)}>
                    {item}
                  </button>
                ))}
              </div>
            </div>
            <div className="panel">
              <div className="panel-title">{t("manualTrigger")}</div>
              <div className="form-grid">
                <input value={triggerTopic} onChange={(event) => setTriggerTopic(event.target.value)} />
                <textarea value={triggerPayload} onChange={(event) => setTriggerPayload(event.target.value)} />
                <button onClick={() => void publishTopic()}>{t("publish")}</button>
              </div>
            </div>
          </section>
        )}
      </main>

      {toast ? <div className="toast">{toast}</div> : null}
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string | undefined }) {
  return (
    <div className="stat-card">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value || "-"}</div>
    </div>
  );
}

function SignalList({ title, rows }: { title: string; rows: any[] }) {
  return (
    <div>
      <strong>{title}</strong>
      <div className="list-stack">
        {rows.length ? rows.map((row) => (
          <div key={`${row.symbol || row.ts_code || row.name}-${title}`} className="list-card">
            <strong>{row.symbol || row.ts_code || row.name || "-"}</strong>
            <div>{row.display_name || row.name || "-"}</div>
            <div>{row.model_score ?? row.event_kg_score ?? "-"}</div>
          </div>
        )) : <div className="empty">-</div>}
      </div>
    </div>
  );
}

function Table({
  columns,
  rows,
  formatters = {},
}: {
  columns: string[];
  rows: any[];
  formatters?: Record<string, (value: unknown) => string>;
}) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr>
        </thead>
        <tbody>
          {rows.length ? rows.map((row, idx) => (
            <tr key={row.id || row.agenda_id || row.root_event_id || idx}>
              {columns.map((column) => (
                <td key={column}>
                  {column === "status" || column === "promotion_state" ? (
                    <span className={`pill ${statusClass(row[column])}`}>{String(row[column] || "-")}</span>
                  ) : (
                    formatters[column]?.(row[column]) ?? String(row[column] ?? "-")
                  )}
                </td>
              ))}
            </tr>
          )) : (
            <tr>
              <td colSpan={columns.length}>-</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

export default App;
