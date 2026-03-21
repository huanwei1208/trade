import type { OpsNodeResultPayload } from "../lib/api";
import { formatDateTime } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { getImpactText, getOpsRuntimeStatusText } from "../lib/statusText";
import { DependencyPathPanel } from "./DependencyPathPanel";
import { EmptyState } from "./EmptyState";
import { NodeTypeBadge } from "./NodeTypeBadge";
import { PanelCard } from "./PanelCard";
import { StatusPill } from "./StatusPill";

type ComputeNodeInspectorProps = {
  node?: OpsNodeResultPayload | null;
  loading?: boolean;
  error?: string | null;
};

export function ComputeNodeInspector({ node, loading, error }: ComputeNodeInspectorProps) {
  const { locale, t } = useI18n();

  if (loading && !node) {
    return (
      <PanelCard className="readiness-inspector">
        <div className="note-card">{t("ops.loadingNode")}</div>
      </PanelCard>
    );
  }

  if (error && !node) {
    return (
      <PanelCard className="readiness-inspector">
        <div className="note-card note-card--danger">{error}</div>
      </PanelCard>
    );
  }

  if (!node) {
    return (
      <PanelCard className="readiness-inspector">
        <EmptyState title={t("ops.selectNode")} body={t("ops.selectNodeCopy")} />
      </PanelCard>
    );
  }

  const status = getOpsRuntimeStatusText(locale, node.latest_status);
  const details = (node.details || {}) as Record<string, unknown>;
  const kind = String(details.kind || node.type || "unknown");
  const detailItems = renderDetailItems(kind, details, locale, t);

  return (
    <PanelCard className="readiness-inspector">
      <div className="readiness-inspector__section">
        <div className="readiness-inspector__pill-row">
          <NodeTypeBadge type={node.type} />
          <StatusPill label={status.label} tone={status.tone} />
        </div>
        <div className="readiness-inspector__value">{node.name}</div>
        <div className="readiness-inspector__subtle">{node.description || t("ops.noDescription")}</div>
      </div>

      <div className="readiness-inspector__section">
        <div className="readiness-inspector__label">{t("ops.latestOutput")}</div>
        <div className="inspector-metric-grid">
          <div className="inspector-metric">
            <span>{t("ops.current")}</span>
            <strong>{node.latest_output_summary?.primary || "—"}</strong>
          </div>
          <div className="inspector-metric">
            <span>{t("ops.previous")}</span>
            <strong>{node.previous_output_summary?.primary || "—"}</strong>
          </div>
        </div>
        {node.latest_output_summary?.secondary && <div className="readiness-inspector__subtle">{node.latest_output_summary.secondary}</div>}
        <div className="readiness-inspector__kv">
          <span>{t("ops.delta")}</span>
          <strong>{node.delta_summary || "—"}</strong>
        </div>
        <div className="readiness-inspector__kv">
          <span>{t("ops.lastRun")}</span>
          <strong>{node.last_run_at ? formatDateTime(node.last_run_at, locale === "zh-CN" ? "zh-CN" : "en-US") : "—"}</strong>
        </div>
        {node.representative_symbol && (
          <div className="readiness-inspector__kv">
            <span>{t("ops.sampleSymbol")}</span>
            <strong>{node.representative_symbol}</strong>
          </div>
        )}
      </div>

      <div className="readiness-inspector__section">
        <div className="readiness-inspector__label">{t("ops.computeDetails")}</div>
        <div className="ops-detail-list">
          {detailItems.length > 0 ? detailItems : <div className="readiness-inspector__subtle">{t("ops.noStructuredDetails")}</div>}
        </div>
      </div>

      <div className="readiness-inspector__section">
        <div className="readiness-inspector__label">{t("ops.dependencyPath")}</div>
        <DependencyPathPanel dependency={node.dependency_path} />
      </div>
    </PanelCard>
  );
}

function renderDetailItems(
  kind: string,
  details: Record<string, unknown>,
  locale: "zh-CN" | "en-US",
  t: (key: string, values?: Record<string, string | number>) => string,
) {
  if (kind === "source") {
    const row = asRecord(details.readiness_row);
    const impacts = Array.isArray(row.impacts) ? row.impacts : [];
    return [
      <div className="ops-detail-item" key="source-summary">
        <strong>{t("ops.readinessHistoryWindow")}</strong>
        <span>{Array.isArray(row.cells) ? `${row.cells.length} ${t("ops.cells")}` : "—"}</span>
      </div>,
      <div className="tag-cluster tag-cluster--compact" key="source-impacts">
        {impacts.length > 0 ? impacts.map((item) => <span className="tag-chip" key={String(item)}>{getImpactText(locale, String(item))}</span>) : <span className="readiness-inspector__subtle">—</span>}
      </div>,
    ];
  }
  if (kind === "factor") {
    const factor = asRecord(details.latest_factor);
    return [
      <div className="ops-detail-item" key="factor-direction">
        <strong>{t("ops.factorDirection")}</strong>
        <span>{String(factor.direction || "—")}</span>
      </div>,
      <div className="ops-detail-item" key="factor-strength">
        <strong>{t("ops.factorStrength")}</strong>
        <span>{formatMetric(factor.strength)}</span>
      </div>,
      <div className="ops-detail-item ops-detail-item--stack" key="factor-rationale">
        <strong>{t("ops.rationale")}</strong>
        <span>{String(factor.rationale || "—")}</span>
      </div>,
    ];
  }
  if (kind === "decision") {
    const explain = asRecord(details.latest_explain);
    const invalidators = asStringArray(explain.invalidators);
    const nextTriggers = asStringArray(explain.next_triggers);
    return [
      <div className="ops-detail-item" key="decision-action">
        <strong>{t("ops.latestDecision")}</strong>
        <span>{String(explain.action || "—")}</span>
      </div>,
      <div className="ops-detail-item ops-detail-item--stack" key="decision-thesis">
        <strong>{t("ops.latestThesis")}</strong>
        <span>{String(explain.thesis || "—")}</span>
      </div>,
      <div className="tag-cluster tag-cluster--compact" key="decision-invalidators">
        {invalidators.map((item) => <span className="tag-chip" key={item}>{item}</span>)}
        {invalidators.length === 0 && <span className="readiness-inspector__subtle">—</span>}
      </div>,
      <div className="tag-cluster tag-cluster--compact" key="decision-next">
        {nextTriggers.map((item) => <span className="tag-chip" key={item}>{item}</span>)}
        {nextTriggers.length === 0 && <span className="readiness-inspector__subtle">—</span>}
      </div>,
    ];
  }
  if (kind === "workflow") {
    const runs = Array.isArray(details.recent_runs) ? details.recent_runs : [];
    return runs.slice(0, 6).map((run, index) => {
      const row = asRecord(run);
      return (
        <div className="ops-detail-item ops-detail-item--stack" key={`${String(row.id || index)}`}>
          <strong>{String(row.job_name || t("ops.run"))}</strong>
          <span>{String(row.status || "unknown")} · {String(row.result_summary || "—")}</span>
        </div>
      );
    });
  }

  if (kind === "model" || kind === "feature") {
    const state = asRecord(details.latest_state);
    const explain = asRecord(details.latest_explain);
    const causal = asRecord(details.latest_causal);
    const conviction = asRecord(causal.conviction_vector);
    return [
      <div className="ops-detail-item" key="model-summary">
        <strong>{t("ops.stateSummary")}</strong>
        <span>{String(state.state_summary || explain.world_state_summary || "—")}</span>
      </div>,
      <div className="ops-detail-item" key="model-trust">
        <strong>{t("ops.trust")}</strong>
        <span>{formatMetric(asRecord(explain.trust).trust_score)}</span>
      </div>,
      <div className="ops-detail-item" key="model-confidence">
        <strong>{t("ops.decisionConfidence")}</strong>
        <span>{formatMetric(conviction.final_decision_confidence)}</span>
      </div>,
    ];
  }

  return [];
}

function asRecord(value: unknown) {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

function asStringArray(value: unknown) {
  return Array.isArray(value) ? value.map((item) => String(item)) : [];
}

function formatMetric(value: unknown) {
  if (typeof value === "number") {
    return Number.isFinite(value) ? value.toFixed(3) : "—";
  }
  if (value === null || value === undefined || value === "") {
    return "—";
  }
  return String(value);
}
