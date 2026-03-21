import { useState } from "react";

import { fetchJson } from "../lib/api";
import type { DataOpsRepairResponse } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { classNames } from "../lib/ui";

type Props = {
  symbol: string;
  selectedIds: Set<string>;
  onOpenFullOps: () => void;
  onActionComplete?: (message: string) => void;
};

type ActionState = "idle" | "loading" | "done" | "error";

export function SymbolRepairActionBar({ symbol, selectedIds, onOpenFullOps, onActionComplete }: Props) {
  const { t } = useI18n();
  const [repullState, setRepullState] = useState<ActionState>("idle");
  const [replayState, setReplayState] = useState<ActionState>("idle");
  const [verifyState, setVerifyState] = useState<ActionState>("idle");
  const [statusMessage, setStatusMessage] = useState<string | null>(null);

  const hasSelection = selectedIds.size > 0;
  const domains = Array.from(selectedIds);

  async function doAction(
    endpoint: string,
    setState: (s: ActionState) => void,
    payload: object,
  ) {
    setState("loading");
    setStatusMessage(null);
    try {
      const res = await fetchJson<DataOpsRepairResponse>(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      setState("done");
      const msg = res.message || t("symbol.dataOps.actionAccepted");
      setStatusMessage(msg);
      onActionComplete?.(msg);
    } catch (err: unknown) {
      setState("error");
      setStatusMessage(err instanceof Error ? err.message : t("symbol.dataOps.actionFailed"));
    }
  }

  function handleRepull() {
    doAction("/api/symbol-data-ops/repull", setRepullState, { symbol, domains });
  }

  function handleReplay() {
    doAction("/api/symbol-data-ops/replay", setReplayState, { symbol, domains });
  }

  function handleMarkVerified() {
    doAction("/api/symbol-data-ops/mark-verified", setVerifyState, { symbol, domains });
  }

  return (
    <div className="symbol-repair-action-bar">
      <div className="symbol-repair-action-bar__buttons">
        <button
          type="button"
          className={classNames("button button--sm button--primary", !hasSelection && "is-disabled")}
          disabled={!hasSelection || repullState === "loading"}
          onClick={handleRepull}
          title={t("symbol.dataOps.repullHint")}
        >
          {repullState === "loading" ? t("common.loading") : t("symbol.dataOps.repull")}
        </button>

        <button
          type="button"
          className={classNames("button button--sm button--secondary", !hasSelection && "is-disabled")}
          disabled={!hasSelection || replayState === "loading"}
          onClick={handleReplay}
          title={t("symbol.dataOps.replayHint")}
        >
          {replayState === "loading" ? t("common.loading") : t("symbol.dataOps.replay")}
        </button>

        <button
          type="button"
          className={classNames("button button--sm button--ghost", !hasSelection && "is-disabled")}
          disabled={!hasSelection || verifyState === "loading"}
          onClick={handleMarkVerified}
          title={t("symbol.dataOps.markVerifiedHint")}
        >
          {verifyState === "loading" ? t("common.loading") : t("symbol.dataOps.markVerified")}
        </button>

        <button
          type="button"
          className="button button--sm button--ghost"
          onClick={onOpenFullOps}
          title={t("symbol.dataOps.openFullOpsHint")}
        >
          {t("symbol.dataOps.openFullOps")}
        </button>
      </div>

      {!hasSelection && (
        <div className="symbol-repair-action-bar__hint">{t("symbol.dataOps.selectHint")}</div>
      )}

      {statusMessage && (
        <div className={classNames(
          "symbol-repair-action-bar__status",
          (repullState === "error" || replayState === "error" || verifyState === "error") && "is-error"
        )}>
          {statusMessage}
        </div>
      )}
    </div>
  );
}
