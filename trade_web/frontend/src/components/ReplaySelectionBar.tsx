import type { OpsReplayAction, OpsReplayMode } from "../lib/api";
import { useI18n } from "../lib/i18n";

type ReplaySelectionBarProps = {
  selectionMode: "cell" | "node" | "subtree";
  replayMode: OpsReplayMode;
  actionMode: OpsReplayAction;
  selectionCount: number;
  onSelectionMode: (value: "cell" | "node" | "subtree") => void;
  onReplayMode: (value: OpsReplayMode) => void;
  onActionMode: (value: OpsReplayAction) => void;
  onPreview: () => void;
  onRepair: () => void;
  onRecompute: () => void;
  onFullChain: () => void;
  onCompare: () => void;
  onClear: () => void;
  loading?: boolean;
};

export function ReplaySelectionBar({
  selectionMode,
  replayMode,
  actionMode,
  selectionCount,
  onSelectionMode,
  onReplayMode,
  onActionMode,
  onPreview,
  onRepair,
  onRecompute,
  onFullChain,
  onCompare,
  onClear,
  loading,
}: ReplaySelectionBarProps) {
  const { t } = useI18n();

  return (
    <div className="replay-selection-bar">
      <div className="replay-selection-bar__meta">
        <strong>{t("ops.selectedCount", { count: selectionCount })}</strong>
      </div>

      <div className="replay-selection-bar__chips">
        {(["cell", "node", "subtree"] as const).map((value) => (
          <button key={value} type="button" className={selectionMode === value ? "is-active" : ""} onClick={() => onSelectionMode(value)}>
            {t(`ops.selectionMode.${value}`)}
          </button>
        ))}
      </div>

      <div className="replay-selection-bar__chips">
        {(["repair", "recompute"] as const).map((value) => (
          <button key={value} type="button" className={actionMode === value ? "is-active" : ""} onClick={() => onActionMode(value)}>
            {t(`ops.replayAction.${value}`)}
          </button>
        ))}
      </div>

      <div className="replay-selection-bar__chips">
        {(["selected_only", "selected_plus_downstream", "full_chain"] as const).map((value) => (
          <button key={value} type="button" className={replayMode === value ? "is-active" : ""} onClick={() => onReplayMode(value)}>
            {t(`ops.replayMode.${value}`)}
          </button>
        ))}
      </div>

      <div className="replay-selection-bar__actions">
        <button type="button" className="button button--ghost" onClick={onPreview} disabled={loading}>
          {t("ops.previewSelected")}
        </button>
        <button type="button" className="button button--ghost" onClick={onRepair} disabled={loading}>
          {t("ops.repairSelected")}
        </button>
        <button type="button" className="button button--primary" onClick={onRecompute} disabled={loading}>
          {t("ops.recomputeDownstream")}
        </button>
        <button type="button" className="button button--ghost" onClick={onFullChain} disabled={loading}>
          {t("ops.recomputeFullChain")}
        </button>
        <button type="button" className="button button--ghost" onClick={onCompare} disabled={loading}>
          {t("ops.compareOutputs")}
        </button>
        <button type="button" className="button button--ghost" onClick={onClear} disabled={loading}>
          {t("ops.clearSelection")}
        </button>
      </div>
    </div>
  );
}
