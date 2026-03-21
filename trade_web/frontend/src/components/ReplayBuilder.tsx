import type { OpsComputeNode, OpsDependencyPathPayload, OpsReplayAction, OpsReplayMode, OpsReplayPreviewPayload, WorkflowDetailPayload } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { getOpsLayerText } from "../lib/statusText";
import { DependencyPathPanel } from "./DependencyPathPanel";
import { NodeTypeBadge } from "./NodeTypeBadge";
import { PanelCard } from "./PanelCard";
import { ReplayImpactPreview } from "./ReplayImpactPreview";
import { ReplaySelectionBar } from "./ReplaySelectionBar";

type ReplayBuilderProps = {
  selectionMode: "cell" | "node" | "subtree";
  replayMode: OpsReplayMode;
  actionMode: OpsReplayAction;
  selectedNodes: OpsComputeNode[];
  selectedCells: Array<{ id?: string; dataset?: string; date?: string }>;
  dependencyPath?: OpsDependencyPathPayload | null;
  preview?: OpsReplayPreviewPayload | null;
  workflow?: WorkflowDetailPayload | null;
  loading?: boolean;
  error?: string | null;
  onSelectionMode: (value: "cell" | "node" | "subtree") => void;
  onReplayMode: (value: OpsReplayMode) => void;
  onActionMode: (value: OpsReplayAction) => void;
  onPreview: () => void;
  onRepair: () => void;
  onRecompute: () => void;
  onFullChain: () => void;
  onCompare: () => void;
  onClear: () => void;
};

export function ReplayBuilder({
  selectionMode,
  replayMode,
  actionMode,
  selectedNodes,
  selectedCells,
  dependencyPath,
  preview,
  workflow,
  loading,
  error,
  onSelectionMode,
  onReplayMode,
  onActionMode,
  onPreview,
  onRepair,
  onRecompute,
  onFullChain,
  onCompare,
  onClear,
}: ReplayBuilderProps) {
  const { locale, t } = useI18n();
  const selectedCount = selectedNodes.length + selectedCells.length;

  return (
    <div className="page-stack">
      <ReplaySelectionBar
        selectionMode={selectionMode}
        replayMode={replayMode}
        actionMode={actionMode}
        selectionCount={selectedCount}
        onSelectionMode={onSelectionMode}
        onReplayMode={onReplayMode}
        onActionMode={onActionMode}
        onPreview={onPreview}
        onRepair={onRepair}
        onRecompute={onRecompute}
        onFullChain={onFullChain}
        onCompare={onCompare}
        onClear={onClear}
        loading={loading}
      />

      <div className="readiness-shell">
        <PanelCard title={t("ops.selectionSummary")} subdued>
          <div className="note-stack">
            <div className="readiness-inspector__label">{t("ops.selectedNodes")}</div>
            <div className="ops-selection-groups">
              {selectedNodes.length > 0 ? (
                groupByLayer(selectedNodes).map(([layer, nodes]) => (
                  <div className="ops-selection-group" key={layer}>
                    <strong>{getOpsLayerText(locale, layer)}</strong>
                    <div className="ops-selection-group__list">
                      {nodes.map((node) => (
                        <div className="ops-selection-group__item" key={node.id}>
                          <NodeTypeBadge type={node.type} subtle />
                          <span>{node.name}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                ))
              ) : (
                <div className="note-card">{t("ops.noNodeSelection")}</div>
              )}
            </div>

            <div className="readiness-inspector__label">{t("ops.selectedCells")}</div>
            <div className="tag-cluster tag-cluster--compact">
              {selectedCells.length > 0 ? (
                selectedCells.map((cell) => (
                  <span className="tag-chip" key={`${cell.dataset}:${cell.date}:${cell.id || ""}`}>
                    {cell.dataset} · {cell.date}
                  </span>
                ))
              ) : (
                <span className="readiness-inspector__subtle">—</span>
              )}
            </div>

            <div className="readiness-inspector__label">{t("ops.dependencyPath")}</div>
            <DependencyPathPanel dependency={dependencyPath} />
          </div>
        </PanelCard>

        <ReplayImpactPreview preview={preview} workflow={workflow} loading={loading} error={error} />
      </div>
    </div>
  );
}

function groupByLayer(nodes: OpsComputeNode[]) {
  const groups = new Map<string, OpsComputeNode[]>();
  for (const node of nodes) {
    const bucket = groups.get(node.layer) || [];
    bucket.push(node);
    groups.set(node.layer, bucket);
  }
  return Array.from(groups.entries());
}
