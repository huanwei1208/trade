import type { ReplayPlanPayload } from "../lib/api";
import { formatDateTime } from "../lib/format";
import { useI18n } from "../lib/i18n";

type BackfillActionPanelProps = {
  dataset: string;
  selectedDate: string;
  rangeFrom: string;
  rangeTo: string;
  plan?: ReplayPlanPayload | null;
  loading?: boolean;
  error?: string | null;
  successMessage?: string | null;
  lastActionAt?: string | null;
  onChangeRange: (next: { dateFrom: string; dateTo: string }) => void;
  onBackfillDay: () => void;
  onBackfillRange: () => void;
  onReplayDownstream: () => void;
  onReplayFullChain: () => void;
  onDryRun: () => void;
};

export function BackfillActionPanel({
  rangeFrom,
  rangeTo,
  plan,
  loading,
  error,
  successMessage,
  lastActionAt,
  onChangeRange,
  onBackfillDay,
  onBackfillRange,
  onReplayDownstream,
  onReplayFullChain,
  onDryRun,
}: BackfillActionPanelProps) {
  const { locale, t } = useI18n();

  return (
    <div className="readiness-inspector__section">
      <div className="readiness-inspector__label">{t("ops.tabs.recovery")}</div>

      <div className="recovery-range-grid">
        <label className="filter-bar__search">
          <span>{t("recovery.startDate")}</span>
          <input type="date" value={rangeFrom} onChange={(event) => onChangeRange({ dateFrom: event.target.value, dateTo: rangeTo })} />
        </label>
        <label className="filter-bar__search">
          <span>{t("recovery.endDate")}</span>
          <input type="date" value={rangeTo} onChange={(event) => onChangeRange({ dateFrom: rangeFrom, dateTo: event.target.value })} />
        </label>
      </div>

      <div className="recovery-action-stack">
        <button type="button" className="button button--primary" onClick={onBackfillDay} disabled={loading}>
          {t("recovery.backfillDay")}
        </button>
        <button type="button" className="button button--ghost" onClick={onBackfillRange} disabled={loading}>
          {t("recovery.backfillRange")}
        </button>
        <button type="button" className="button button--ghost" onClick={onReplayDownstream} disabled={loading}>
          {t("recovery.replayDownstream")}
        </button>
        <button type="button" className="button button--ghost" onClick={onReplayFullChain} disabled={loading}>
          {t("recovery.replayFullChain")}
        </button>
        <button type="button" className="button button--ghost" onClick={onDryRun} disabled={loading}>
          {t("recovery.dryRun")}
        </button>
      </div>

      {error && <div className="note-card note-card--danger">{error}</div>}
      {successMessage && <div className="note-card note-card--warning">{successMessage}</div>}

      <div className="readiness-inspector__subtle">
        {t("recovery.lastAction")} {lastActionAt ? formatDateTime(lastActionAt, locale === "zh-CN" ? "zh-CN" : "en-US") : "—"}
      </div>

      <div className="note-stack">
        <div className="note-card">
          <strong>{plan ? t("recovery.planReady") : t("recovery.planUnavailable")}</strong>
          <div className="recovery-plan-copy">
            {plan ? `${t("recovery.downstreamNodes")} ${(plan.downstream_nodes || []).map((item) => item.job_name).filter(Boolean).join(" → ") || "—"}` : t("common.noDetail")}
          </div>
          {plan?.estimated_duration_ms ? (
            <div className="recovery-plan-copy">{t("recovery.estimatedDuration")} {plan.estimated_duration_ms}ms</div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
