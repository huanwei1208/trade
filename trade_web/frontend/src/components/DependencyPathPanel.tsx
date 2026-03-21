import type { OpsDependencyPathPayload } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { getOpsLayerText } from "../lib/statusText";
import { NodeTypeBadge } from "./NodeTypeBadge";

type DependencyPathPanelProps = {
  dependency?: OpsDependencyPathPayload | null;
};

export function DependencyPathPanel({ dependency }: DependencyPathPanelProps) {
  const { locale, t } = useI18n();

  if (!dependency || !dependency.nodes?.length) {
    return <div className="note-card">{t("ops.noDependencyPath")}</div>;
  }

  const byId = new Map(dependency.nodes.map((node) => [node.id, node]));
  const selected = dependency.selected_node_ids.map((id) => byId.get(id)).filter(Boolean);
  const upstream = dependency.upstream_ids.map((id) => byId.get(id)).filter(Boolean);
  const downstream = dependency.downstream_ids.map((id) => byId.get(id)).filter(Boolean);

  return (
    <div className="dependency-path-panel">
      <DependencyColumn title={t("ops.dependency.upstream")} nodes={upstream} locale={locale} />
      <DependencyColumn title={t("ops.dependency.selected")} nodes={selected} locale={locale} />
      <DependencyColumn title={t("ops.dependency.downstream")} nodes={downstream} locale={locale} />
    </div>
  );
}

function DependencyColumn({
  title,
  nodes,
  locale,
}: {
  title: string;
  nodes: Array<OpsDependencyPathPayload["nodes"][number] | undefined>;
  locale: "zh-CN" | "en-US";
}) {
  return (
    <div className="dependency-path-panel__column">
      <div className="readiness-inspector__label">{title}</div>
      {nodes.length === 0 ? (
        <div className="readiness-inspector__subtle">—</div>
      ) : (
        <div className="dependency-path-panel__list">
          {nodes.map((node) =>
            node ? (
              <div className="dependency-path-panel__node" key={node.id}>
                <div className="dependency-path-panel__node-head">
                  <NodeTypeBadge type={node.type} subtle />
                  <span>{getOpsLayerText(locale, node.layer)}</span>
                </div>
                <strong>{node.name}</strong>
              </div>
            ) : null,
          )}
        </div>
      )}
    </div>
  );
}
