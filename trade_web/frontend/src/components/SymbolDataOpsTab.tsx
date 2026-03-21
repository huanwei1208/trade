import { useState } from "react";

import type { SymbolDataOpsResponse } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { SymbolDataCoverageMatrix } from "./SymbolDataCoverageMatrix";
import { SymbolRepairActionBar } from "./SymbolRepairActionBar";

type Props = {
  symbol: string;
  data?: SymbolDataOpsResponse | null;
  loading?: boolean;
  onOpenFullOps: () => void;
  onRetry?: () => void;
};

export function SymbolDataOpsTab({ symbol, data, loading, onOpenFullOps, onRetry }: Props) {
  const { t } = useI18n();
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [actionStatus, setActionStatus] = useState<string | null>(null);

  return (
    <div className="symbol-data-ops-tab">
      <div className="symbol-data-ops-tab__head">
        <div className="symbol-data-ops-tab__title">{t("symbol.dataOps.title")}</div>
        {onRetry && (
          <button type="button" className="button button--sm button--ghost" onClick={onRetry}>
            {t("common.retry")}
          </button>
        )}
      </div>

      <SymbolDataCoverageMatrix
        domains={data?.domains}
        loading={loading}
        selectedIds={selectedIds}
        onSelectionChange={setSelectedIds}
      />

      <SymbolRepairActionBar
        symbol={symbol}
        selectedIds={selectedIds}
        onOpenFullOps={onOpenFullOps}
        onActionComplete={(msg) => {
          setActionStatus(msg);
          setSelectedIds(new Set());
        }}
      />

      {actionStatus && (
        <div className="symbol-data-ops-tab__action-status">{actionStatus}</div>
      )}
    </div>
  );
}
