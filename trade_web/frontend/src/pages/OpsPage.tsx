import { useState } from "react";

import { ErrorState } from "../components/ErrorState";
import { LoadingSkeleton } from "../components/LoadingSkeleton";
import { PanelCard } from "../components/PanelCard";
import { SectionHeader } from "../components/SectionHeader";
import { StatusPill } from "../components/StatusPill";
import { useApiResource, type DagRuntime, type DataHealthPayload, type EventsPagePayload, type StatusPayload, type TrustOverview, type WorkflowSummary } from "../lib/api";
import { formatDateTime, formatPercent, labelizeDataset, shortText } from "../lib/format";
import { useLocalStorageState } from "../lib/ui";

type OpsPageProps = {
  refreshToken: number;
};

type OpsTab = "overview" | "pipeline" | "data" | "trust" | "workflows";

export function OpsPage({ refreshToken }: OpsPageProps) {
  const [tab, setTab] = useLocalStorageState<OpsTab>("trade-web:ops-tab", "overview");

  const status = useApiResource<StatusPayload>("/api/status", { deps: [refreshToken], cacheKey: "trade-web:status" });
  const runtime = useApiResource<DagRuntime>("/api/dag/runtime", { deps: [refreshToken], cacheKey: "trade-web:dag-runtime" });
  const dataHealth = useApiResource<DataHealthPayload>("/api/data-health", { deps: [refreshToken], cacheKey: "trade-web:data-health" });
  const trust = useApiResource<TrustOverview>("/api/trust/overview", { deps: [refreshToken], cacheKey: "trade-web:trust-overview" });
  const workflows = useApiResource<WorkflowSummary[]>("/api/workflows", { deps: [refreshToken], cacheKey: "trade-web:workflows" });
  const events = useApiResource<EventsPagePayload>("/api/events-page", { deps: [refreshToken], cacheKey: "trade-web:events-page" });

  if (status.loading && !status.data) {
    return <LoadingSkeleton variant="ops" />;
  }

  if (status.error && !status.data) {
    return <ErrorState title="Ops view unavailable" body="The backstage console could not load its status payload." detail={status.error.message} action={<button type="button" className="button button--primary" onClick={status.retry}>Retry</button>} />;
  }

  return (
    <div className="page-stack page-ops">
      <SectionHeader title="Backstage operations" subtitle="The decision workflow stays front-stage. This page is for verifying runtime health, data freshness, and replay paths." />

      <div className="filter-bar filter-bar--ops">
        {([
          ["overview", "Overview"],
          ["pipeline", "Pipeline"],
          ["data", "Data Health"],
          ["trust", "Trust"],
          ["workflows", "Workflows"],
        ] as const).map(([key, label]) => (
          <button key={key} type="button" className={tab === key ? "is-active" : ""} onClick={() => setTab(key)}>
            {label}
          </button>
        ))}
      </div>

      {tab === "overview" && (
        <div className="compact-grid">
          <PanelCard title="System summary" subdued>
            <div className="metric-grid">
              <div className="metric-card">
                <div className="metric-card__label">Status</div>
                <div className="metric-card__value">{status.data?.status || "unknown"}</div>
              </div>
              <div className="metric-card">
                <div className="metric-card__label">Models</div>
                <div className="metric-card__value">{(status.data?.inference_models || []).length}</div>
              </div>
              <div className="metric-card">
                <div className="metric-card__label">Trust</div>
                <div className="metric-card__value">{formatPercent(trust.data?.trust_scalar, 0)}</div>
              </div>
            </div>
          </PanelCard>

          <PanelCard title="Stage summary" subdued>
            <div className="list-stack">
              {Object.entries(runtime.data?.stage_summary || {}).map(([key, value]) => (
                <div className="compact-row" key={key}>
                  <div className="compact-row__title">{key}</div>
                  <div className="compact-row__meta">
                    <StatusPill label={`${value.ok || 0} ok`} tone="ok" subtle />
                    <StatusPill label={`${value.error || 0} err`} tone="err" subtle />
                    <StatusPill label={`${value.running || 0} running`} tone="info" subtle />
                  </div>
                </div>
              ))}
            </div>
          </PanelCard>

          <PanelCard title="Recent failures" subdued>
            <div className="list-stack">
              {(events.data?.failed_nodes || []).slice(0, 8).map((node, index) => (
                <div className="compact-row" key={`${node.job_name || node.id || index}`}>
                  <div>
                    <div className="compact-row__title">{String(node.job_name || node.id || "Node")}</div>
                    <div className="compact-row__subtitle">{shortText(String(node.error_detail || node.result_summary || ""), 80)}</div>
                  </div>
                  <StatusPill label={String(node.status || "error")} tone="err" subtle />
                </div>
              ))}
              {(!events.data?.failed_nodes || events.data.failed_nodes.length === 0) && <div className="note-card">No recent failed nodes.</div>}
            </div>
          </PanelCard>
        </div>
      )}

      {tab === "pipeline" && (
        <PanelCard title="Pipeline runtime" subdued>
          <div className="pipeline-list">
            {(runtime.data?.nodes || []).slice(0, 18).map((node, index) => (
              <div className="pipeline-list__row" key={`${node.job_name || node.id || index}`}>
                <div>
                  <div className="pipeline-list__title">{String(node.job_name || "Unknown node")}</div>
                  <div className="pipeline-list__subtitle">{String(node.stage || "unknown stage")}</div>
                </div>
                <div className="pipeline-list__meta">
                  <StatusPill label={String(node.status || "unknown")} tone={String(node.status) === "ok" ? "ok" : String(node.status) === "error" ? "err" : "info"} subtle />
                  <span>{shortText(String(node.error_detail || node.result_summary || ""), 70)}</span>
                </div>
              </div>
            ))}
          </div>
        </PanelCard>
      )}

      {tab === "data" && (
        <div className="compact-grid">
          <PanelCard title="Data freshness" subdued>
            <div className="list-stack">
              {(dataHealth.data?.datasets || []).map((dataset) => (
                <div className="compact-row" key={dataset.id}>
                  <div>
                    <div className="compact-row__title">{dataset.name}</div>
                    <div className="compact-row__subtitle">{dataset.lineage}</div>
                  </div>
                  <div className="compact-row__meta">
                    <span>{dataset.lag_days !== null && dataset.lag_days !== undefined ? `${dataset.lag_days}d` : "—"}</span>
                    <StatusPill label={dataset.status || "unknown"} tone={dataset.status === "ok" ? "ok" : dataset.status === "error" ? "err" : "warn"} subtle />
                  </div>
                </div>
              ))}
            </div>
          </PanelCard>

          <PanelCard title="Data highlights" subdued>
            <div className="tag-cluster">
              {(dataHealth.data?.highlights || []).map((item) => (
                <span className="tag-chip" key={item.title}>
                  {item.title}: {item.value}
                </span>
              ))}
            </div>
          </PanelCard>
        </div>
      )}

      {tab === "trust" && (
        <PanelCard title="Trust trend" subdued>
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
        <PanelCard title="Workflow traces" subdued>
          <div className="list-stack">
            {(workflows.data || []).slice(0, 12).map((workflow, index) => (
              <div className="compact-row" key={`${workflow.root_event_id || index}`}>
                <div>
                  <div className="compact-row__title">{String(workflow.topic || workflow.job_name || "Workflow")}</div>
                  <div className="compact-row__subtitle">{shortText(String(workflow.root_cause || workflow.reason_summary || ""), 90) || "No root cause summary"}</div>
                </div>
                <div className="compact-row__meta">
                  <StatusPill label={String(workflow.status || "unknown")} tone={String(workflow.status) === "ok" ? "ok" : String(workflow.status) === "error" ? "err" : "info"} subtle />
                  <span>{formatDateTime(String(workflow.created_at || workflow.started_at || ""))}</span>
                </div>
              </div>
            ))}
          </div>
        </PanelCard>
      )}
    </div>
  );
}
