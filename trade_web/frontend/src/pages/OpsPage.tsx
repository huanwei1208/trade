import { useEffect, useState } from "react";

import { ErrorState } from "../components/ErrorState";
import { LoadingSkeleton } from "../components/LoadingSkeleton";
import { PanelCard } from "../components/PanelCard";
import { ReadinessHeatmap } from "../components/ReadinessHeatmap";
import { ReadinessInspector } from "../components/ReadinessInspector";
import { ReadinessSummaryCards } from "../components/ReadinessSummaryCards";
import { RecoveryTimeline } from "../components/RecoveryTimeline";
import { SectionHeader } from "../components/SectionHeader";
import { StatusPill } from "../components/StatusPill";
import { useApiResource, type DagRuntime, type DataHealthPayload, type EventsPagePayload, type ReadinessCell, type ReadinessGridPayload, type ReadinessRow, type StatusPayload, type TrustOverview, type WorkflowSummary } from "../lib/api";
import { formatDateTime, formatPercent, shortText } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { getDatasetText } from "../lib/statusText";
import { getGateStatusText } from "../lib/statusText";
import { useLocalStorageState } from "../lib/ui";

type OpsPageProps = {
  refreshToken: number;
};

type OpsTab = "overview" | "readiness" | "recovery" | "pipeline" | "trust" | "workflows";

export function OpsPage({ refreshToken }: OpsPageProps) {
  const { locale, t } = useI18n();
  const [tab, setTab] = useLocalStorageState<OpsTab>("trade-web:ops-tab", "overview");
  const [readinessDays, setReadinessDays] = useState<30 | 60 | 90>(30);
  const [selectedCellId, setSelectedCellId] = useState("");

  const status = useApiResource<StatusPayload>("/api/status", { deps: [refreshToken], cacheKey: "trade-web:status" });
  const runtime = useApiResource<DagRuntime>("/api/dag/runtime", { deps: [refreshToken], cacheKey: "trade-web:dag-runtime" });
  const dataHealth = useApiResource<DataHealthPayload>("/api/data-health", { deps: [refreshToken], cacheKey: "trade-web:data-health" });
  const trust = useApiResource<TrustOverview>("/api/trust/overview", { deps: [refreshToken], cacheKey: "trade-web:trust-overview" });
  const workflows = useApiResource<WorkflowSummary[]>("/api/workflows", { deps: [refreshToken], cacheKey: "trade-web:workflows" });
  const events = useApiResource<EventsPagePayload>("/api/events-page", { deps: [refreshToken], cacheKey: "trade-web:events-page" });
  const readiness = useApiResource<ReadinessGridPayload>(`/api/readiness-grid?days=${readinessDays}`, {
    deps: [refreshToken, readinessDays],
    cacheKey: `trade-web:readiness-grid:${readinessDays}`,
  });

  const selectedReadiness = findSelectedReadiness(readiness.data?.rows || [], selectedCellId);

  useEffect(() => {
    if (selectedReadiness.cell || !readiness.data?.rows?.length) {
      return;
    }
    const fallback = pickDefaultReadinessCell(readiness.data.rows);
    if (fallback) {
      setSelectedCellId(fallback.id);
    }
  }, [readiness.data, selectedReadiness.cell]);

  if (status.loading && !status.data) {
    return <LoadingSkeleton variant="ops" />;
  }

  if (status.error && !status.data) {
    return <ErrorState title={t("ops.viewUnavailable")} body={t("ops.viewUnavailableCopy")} detail={status.error.message} action={<button type="button" className="button button--primary" onClick={status.retry}>{t("common.retry")}</button>} />;
  }

  return (
    <div className="page-stack page-ops">
      <SectionHeader title={t("ops.title")} subtitle={t("ops.subtitle")} />

      <div className="filter-bar filter-bar--ops">
        {([
          ["overview", t("ops.tabs.overview")],
          ["readiness", t("ops.tabs.readiness")],
          ["recovery", t("ops.tabs.recovery")],
          ["pipeline", t("ops.tabs.pipeline")],
          ["trust", t("ops.tabs.trust")],
          ["workflows", t("ops.tabs.workflows")],
        ] as const).map(([key, label]) => (
          <button key={key} type="button" className={tab === key ? "is-active" : ""} onClick={() => setTab(key)}>
            {label}
          </button>
        ))}
      </div>

      {tab === "overview" && (
        <div className="compact-grid">
          <PanelCard title={t("ops.systemSummary")} subdued>
            <div className="metric-grid">
              <div className="metric-card">
                <div className="metric-card__label">{t("ops.status")}</div>
                <div className="metric-card__value">{getGateStatusText(locale, status.data?.status).label}</div>
              </div>
              <div className="metric-card">
                <div className="metric-card__label">{t("ops.models")}</div>
                <div className="metric-card__value">{(status.data?.inference_models || []).length}</div>
              </div>
              <div className="metric-card">
                <div className="metric-card__label">{t("ops.trust")}</div>
                <div className="metric-card__value">{formatPercent(trust.data?.trust_scalar, 0)}</div>
              </div>
            </div>
          </PanelCard>

          <PanelCard title={t("ops.stageSummary")} subdued>
            <div className="list-stack">
              {Object.entries(runtime.data?.stage_summary || {}).map(([key, value]) => (
                <div className="compact-row" key={key}>
                  <div className="compact-row__title">{key}</div>
                  <div className="compact-row__meta">
                    <StatusPill label={`${value.ok || 0} ${t("status.healthy")}`} tone="ok" subtle />
                    <StatusPill label={`${value.error || 0} err`} tone="err" subtle />
                    <StatusPill label={`${value.running || 0} running`} tone="info" subtle />
                  </div>
                </div>
              ))}
            </div>
          </PanelCard>

          <PanelCard title={t("ops.recentFailures")} subdued>
            <div className="list-stack">
              {(events.data?.failed_nodes || []).slice(0, 8).map((node, index) => (
                <div className="compact-row" key={`${node.job_name || node.id || index}`}>
                  <div>
                    <div className="compact-row__title">{String(node.job_name || node.id || "Node")}</div>
                    <div className="compact-row__subtitle">{shortText(String(node.error_detail || node.result_summary || ""), 80)}</div>
                  </div>
                  <StatusPill label={getGateStatusText(locale, String(node.status || "error")).label} tone="err" subtle />
                </div>
              ))}
              {(!events.data?.failed_nodes || events.data.failed_nodes.length === 0) && <div className="note-card">{t("ops.noFailures")}</div>}
            </div>
          </PanelCard>
        </div>
      )}

      {tab === "readiness" && (
        <div className="readiness-page">
          <div className="filter-bar filter-bar--ops">
            {([
              [30, t("readiness.range30")],
              [60, t("readiness.range60")],
              [90, t("readiness.range90")],
            ] as const).map(([value, label]) => (
              <button key={value} type="button" className={readinessDays === value ? "is-active" : ""} onClick={() => setReadinessDays(value)}>
                {label}
              </button>
            ))}
          </div>

          {readiness.loading && !readiness.data ? (
            <LoadingSkeleton variant="ops" />
          ) : readiness.data ? (
            <>
              <ReadinessSummaryCards payload={readiness.data} />

              {readiness.data.summary.today_impact?.constrained && (
                <div className="page-banner page-banner--muted">
                  <strong>{t("readiness.todayConstrained")}</strong>
                  <span>
                    {(readiness.data.summary.today_impact?.datasets || [])
                      .slice(0, 3)
                      .map((item) => getDatasetText(locale, item.dataset, item.label))
                      .join(" · ")}
                  </span>
                </div>
              )}

              <div className="readiness-shell">
                <PanelCard title={t("ops.tabs.readiness")} subdued>
                  <ReadinessHeatmap
                    rows={readiness.data.rows}
                    dates={readiness.data.range.dates}
                    selectedCellId={selectedReadiness.cell?.id}
                    onSelect={(row, cell) => setSelectedCellId(cell.id)}
                  />
                </PanelCard>
                <ReadinessInspector row={selectedReadiness.row} cell={selectedReadiness.cell} />
              </div>
            </>
          ) : (
            <ErrorState title={t("ops.viewUnavailable")} body={t("ops.viewUnavailableCopy")} action={<button type="button" className="button button--primary" onClick={readiness.retry}>{t("common.retry")}</button>} />
          )}
        </div>
      )}

      {tab === "pipeline" && (
        <PanelCard title={t("ops.pipelineRuntime")} subdued>
          <div className="pipeline-list">
            {(runtime.data?.nodes || []).slice(0, 18).map((node, index) => (
              <div className="pipeline-list__row" key={`${node.job_name || node.id || index}`}>
                <div>
                  <div className="pipeline-list__title">{String(node.job_name || "Unknown node")}</div>
                  <div className="pipeline-list__subtitle">{String(node.stage || "unknown stage")}</div>
                </div>
                <div className="pipeline-list__meta">
                  <StatusPill label={getGateStatusText(locale, String(node.status || "unknown")).label} tone={String(node.status) === "ok" ? "ok" : String(node.status) === "error" ? "err" : "info"} subtle />
                  <span>{shortText(String(node.error_detail || node.result_summary || ""), 70)}</span>
                </div>
              </div>
            ))}
          </div>
        </PanelCard>
      )}

      {tab === "recovery" && (
        <div className="readiness-shell">
          <PanelCard title={t("ops.tabs.recovery")} subdued>
            <div className="note-stack">
              <div className="note-card note-card--warning">
                {selectedReadiness.row && selectedReadiness.cell
                  ? `${getDatasetText(locale, selectedReadiness.row.dataset, selectedReadiness.row.label)} · ${selectedReadiness.cell.date}`
                  : t("readiness.selectCellCopy")}
              </div>
              <PanelCard title={t("readiness.auditHistory")} subdued>
                <RecoveryTimeline
                  items={
                    selectedReadiness.row
                      ? readiness.data?.recovery_history?.[selectedReadiness.row.dataset] || selectedReadiness.cell?.history || []
                      : []
                  }
                />
              </PanelCard>
            </div>
          </PanelCard>
          <ReadinessInspector row={selectedReadiness.row} cell={selectedReadiness.cell} />
        </div>
      )}

      {tab === "trust" && (
        <PanelCard title={t("ops.trustTrend")} subdued>
          <div className="list-stack">
            {(trust.data?.trend || []).map((item) => (
              <div className="compact-row" key={item.eval_date}>
                <div className="compact-row__title">{item.eval_date}</div>
                <div className="compact-row__meta">
                  <span>Trust {formatPercent(item.trust_scalar, 0)}</span>
                  <span>Coverage {formatPercent(item.coverage, 0)}</span>
                </div>
              </div>
            ))}
          </div>
        </PanelCard>
      )}

      {tab === "workflows" && (
        <PanelCard title={t("ops.workflowTraces")} subdued>
          <div className="list-stack">
            {(workflows.data || []).slice(0, 12).map((workflow, index) => (
              <div className="compact-row" key={`${workflow.root_event_id || index}`}>
                <div>
                  <div className="compact-row__title">{String(workflow.topic || workflow.job_name || "Workflow")}</div>
                  <div className="compact-row__subtitle">{shortText(String(workflow.root_cause || workflow.reason_summary || ""), 90) || "No root cause summary"}</div>
                </div>
                <div className="compact-row__meta">
                  <StatusPill label={getGateStatusText(locale, String(workflow.status || "unknown")).label} tone={String(workflow.status) === "ok" ? "ok" : String(workflow.status) === "error" ? "err" : "info"} subtle />
                  <span>{formatDateTime(String(workflow.created_at || workflow.started_at || ""), locale === "zh-CN" ? "zh-CN" : "en-US")}</span>
                </div>
              </div>
            ))}
          </div>
        </PanelCard>
      )}
    </div>
  );
}

function pickDefaultReadinessCell(rows: ReadinessRow[]) {
  for (const row of rows) {
    const problematic = row.cells.find((cell) => !["READY", "LATE_READY"].includes(cell.status));
    if (problematic) {
      return problematic;
    }
  }
  return rows[0]?.cells[0] || null;
}

function findSelectedReadiness(rows: ReadinessRow[], selectedCellId: string): { row: ReadinessRow | null; cell: ReadinessCell | null } {
  for (const row of rows) {
    const cell = row.cells.find((item) => item.id === selectedCellId);
    if (cell) {
      return { row, cell };
    }
  }
  return { row: null, cell: null };
}
