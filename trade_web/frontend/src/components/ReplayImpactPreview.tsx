import type { OpsReplayPreviewPayload, WorkflowDetailPayload } from "../lib/api";
import { formatDateTime } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { getOpsLayerText, getOpsRuntimeStatusText } from "../lib/statusText";
import { NodeTypeBadge } from "./NodeTypeBadge";
import { PanelCard } from "./PanelCard";
import { StatusPill } from "./StatusPill";

type ReplayImpactPreviewProps = {
  preview?: OpsReplayPreviewPayload | null;
  workflow?: WorkflowDetailPayload | null;
  loading?: boolean;
  error?: string | null;
};

export function ReplayImpactPreview({ preview, workflow, loading, error }: ReplayImpactPreviewProps) {
  const { locale, t } = useI18n();
  const workflowStatus = getOpsRuntimeStatusText(locale, String(workflow?.status || "unknown"));

  return (
    <PanelCard title={t("ops.previewImpact")} subdued>
      <div className="note-stack">
        {loading && <div className="note-card">{t("ops.previewLoading")}</div>}
        {error && <div className="note-card note-card--danger">{error}</div>}

        {workflow && (
          <div className="note-card">
            <div className="compact-row">
              <div>
                <div className="compact-row__title">{String(workflow.title || t("ops.currentWorkflow"))}</div>
                <div className="compact-row__subtitle">
                  {t("ops.workflowProgress", {
                    completed: Number(workflow.progress?.completed || 0),
                    total: Number(workflow.progress?.total || 0),
                  })}
                </div>
              </div>
              <StatusPill label={workflowStatus.label} tone={workflowStatus.tone} subtle />
            </div>
            <div className="readiness-inspector__subtle">
              {workflow.completed_at
                ? `${t("recovery.lastUpdated")} ${formatDateTime(workflow.completed_at, locale === "zh-CN" ? "zh-CN" : "en-US")}`
                : workflow.started_at
                  ? `${t("recovery.startedAt")} ${formatDateTime(workflow.started_at, locale === "zh-CN" ? "zh-CN" : "en-US")}`
                  : "—"}
            </div>
          </div>
        )}

        {!preview && !loading && !error && <div className="note-card">{t("ops.previewEmpty")}</div>}

        {preview && (
          <>
            <div className="ops-preview-grid">
              <div className="inspector-metric">
                <span>{t("ops.selectedNodes")}</span>
                <strong>{preview.estimated_scope?.selected_count || 0}</strong>
              </div>
              <div className="inspector-metric">
                <span>{t("ops.jobsToRun")}</span>
                <strong>{preview.estimated_scope?.job_count || 0}</strong>
              </div>
              <div className="inspector-metric">
                <span>{t("ops.affectedLayers")}</span>
                <strong>{preview.estimated_scope?.layers?.length || 0}</strong>
              </div>
              <div className="inspector-metric">
                <span>{t("recovery.estimatedDuration")}</span>
                <strong>{preview.estimated_scope?.estimated_duration_ms || 0}ms</strong>
              </div>
            </div>

            {preview.warnings.length > 0 && (
              <div className="note-card note-card--warning">
                {preview.warnings.map((warning) => (
                  <div key={warning}>{warning}</div>
                ))}
              </div>
            )}

            <div className="ops-preview-section">
              <div className="readiness-inspector__label">{t("ops.jobsPlanned")}</div>
              <div className="ops-preview-list">
                {preview.nodes_to_run.map((job, index) => (
                  <div className="ops-preview-item" key={`${job.job_name || index}`}>
                    <div className="ops-preview-item__head">
                      <strong>{job.job_name || "?"}</strong>
                      <span>{getOpsLayerText(locale, job.layer)}</span>
                    </div>
                    <div className="ops-preview-item__meta">
                      <NodeTypeBadge type={job.node_type} subtle />
                      <span>{job.avg_duration_ms ? `${job.avg_duration_ms}ms` : "—"}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="ops-preview-section">
              <div className="readiness-inspector__label">{t("ops.downstreamImpact")}</div>
              <div className="tag-cluster tag-cluster--compact">
                {preview.downstream_affected.map((item) => (
                  <span className="tag-chip" key={item.id}>
                    {item.name}
                  </span>
                ))}
              </div>
            </div>
          </>
        )}
      </div>
    </PanelCard>
  );
}
