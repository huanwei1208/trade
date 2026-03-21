import type { ReactNode } from "react";

import type { OpsComputeLayersPayload, OpsComputeNode } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { ComputeResultCard } from "./ComputeResultCard";
import { PanelCard } from "./PanelCard";

type ComputeLayersViewProps = {
  payload: OpsComputeLayersPayload;
  activeNodeId?: string | null;
  selectedNodeIds: string[];
  collapsedGroups: Record<string, boolean>;
  onToggleGroup: (key: string) => void;
  onActivateNode: (nodeId: string) => void;
  onToggleNode: (nodeId: string) => void;
  inspector: ReactNode;
};

export function ComputeLayersView({
  payload,
  activeNodeId,
  selectedNodeIds,
  collapsedGroups,
  onToggleGroup,
  onActivateNode,
  onToggleNode,
  inspector,
}: ComputeLayersViewProps) {
  const { t } = useI18n();

  return (
    <div className="readiness-shell">
      <PanelCard
        title={t("ops.tabs.compute")}
        eyebrow={payload.representative_symbol ? `${t("ops.sampleSymbol")} · ${payload.representative_symbol}` : undefined}
        subdued
      >
        <div className="compute-layer-groups">
          {payload.layers.map((group) => (
            <section className="compute-layer-group" key={group.key}>
              <button type="button" className="compute-layer-group__header" onClick={() => onToggleGroup(group.key)}>
                <div>
                  <strong>{group.label}</strong>
                  <span>{group.nodes.length} {t("ops.nodes")}</span>
                </div>
                <span>{collapsedGroups[group.key] ? "+" : "−"}</span>
              </button>
              {!collapsedGroups[group.key] && (
                <div className="compute-layer-group__grid">
                  {group.nodes.map((node) => (
                    <ComputeResultCard
                      key={node.id}
                      node={node}
                      active={activeNodeId === node.id}
                      selected={selectedNodeIds.includes(node.id)}
                      onActivate={() => onActivateNode(node.id)}
                      onToggleSelect={() => onToggleNode(node.id)}
                    />
                  ))}
                  {group.nodes.length === 0 && <div className="note-card">{t("ops.noNodesInGroup")}</div>}
                </div>
              )}
            </section>
          ))}
        </div>
      </PanelCard>
      {inspector}
    </div>
  );
}
