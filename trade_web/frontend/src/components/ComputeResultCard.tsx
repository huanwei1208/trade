import type { OpsComputeNode } from "../lib/api";
import { formatDateTime } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { getOpsRuntimeStatusText } from "../lib/statusText";
import { classNames } from "../lib/ui";
import { NodeTypeBadge } from "./NodeTypeBadge";
import { StatusPill } from "./StatusPill";

type ComputeResultCardProps = {
  node: OpsComputeNode;
  active?: boolean;
  selected?: boolean;
  onActivate: () => void;
  onToggleSelect: () => void;
};

export function ComputeResultCard({
  node,
  active = false,
  selected = false,
  onActivate,
  onToggleSelect,
}: ComputeResultCardProps) {
  const { locale, t } = useI18n();
  const status = getOpsRuntimeStatusText(locale, node.latest_status);

  return (
    <section className={classNames("compute-result-card", active && "is-active", selected && "is-selected")}>
      <div className="compute-result-card__toolbar">
        <label className="selection-check">
          <input type="checkbox" checked={selected} onChange={onToggleSelect} />
          <span />
        </label>
        <NodeTypeBadge type={node.type} subtle />
        <StatusPill label={status.label} tone={status.tone} subtle />
      </div>
      <button type="button" className="compute-result-card__main" onClick={onActivate}>
        <div className="compute-result-card__title-row">
          <h4>{node.name}</h4>
          {node.delta_summary && <span className="compute-result-card__delta">{node.delta_summary}</span>}
        </div>
        <div className="compute-result-card__primary">{node.latest_output_summary?.primary || t("ops.outputUnavailable")}</div>
        {node.latest_output_summary?.secondary && (
          <div className="compute-result-card__secondary">{node.latest_output_summary.secondary}</div>
        )}
        <div className="compute-result-card__meta">
          <span>{t("ops.upstreamCount")} {node.upstream_ids?.length || 0}</span>
          <span>{t("ops.downstreamCount")} {node.downstream_ids?.length || 0}</span>
          <span>{t("ops.lastRun")} {node.last_run_at ? formatDateTime(node.last_run_at, locale === "zh-CN" ? "zh-CN" : "en-US") : "—"}</span>
        </div>
      </button>
    </section>
  );
}
