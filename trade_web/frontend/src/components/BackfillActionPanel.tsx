import type { ReplayPlanPayload } from "../lib/api";
import { formatDateTime } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { getDatasetText, getImpactText } from "../lib/statusText";

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
  changed?: boolean | null;
  onChangeRange: (next: { dateFrom: string; dateTo: string }) => void;
  onBackfillDay: () => void;
  onBackfillRange: () => void;
  onReplayDownstream: () => void;
  onReplayFullChain: () => void;
  onDryRun: () => void;
};

export function BackfillActionPanel({
  dataset,
  selectedDate,
  rangeFrom,
  rangeTo,
  plan,
  loading,
  error,
  successMessage,
  lastActionAt,
  changed,
  onChangeRange,
  onBackfillDay,
  onBackfillRange,
  onReplayDownstream,
  onReplayFullChain,
  onDryRun,
}: BackfillActionPanelProps) {
  const { locale, t } = useI18n();
  const downstreamNodes = plan?.downstream_nodes || [];
  const fullChainNodes = plan?.full_chain || [];
  const datasetLabel = getDatasetText(locale, dataset);
  const activeRangeLabel = rangeFrom === rangeTo || !rangeTo ? rangeFrom || selectedDate : `${rangeFrom} → ${rangeTo}`;

  return (
    <div className="readiness-inspector__section">
      <div className="readiness-inspector__label">{t("recovery.restoreLatestRecommendation")}</div>

      <div className="note-card">
        <strong>{t("recovery.restoreLatestRecommendation")}</strong>
        <div className="recovery-plan-copy">
          {t("recovery.restorePlanIntro", {
            dataset: datasetLabel,
            date: activeRangeLabel,
          })}
        </div>
      </div>

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

      {changed && <div className="note-card note-card--warning">{t("recovery.changedDetectedStrong")}</div>}

      <div className="recovery-action-stack">
        <button type="button" className="button button--primary" onClick={onBackfillDay} disabled={loading}>
          {t("recovery.repairDataDay")}
        </button>
        <button type="button" className="button button--ghost" onClick={onBackfillRange} disabled={loading}>
          {t("recovery.repairDataRange")}
        </button>
        <button type="button" className="button button--ghost" onClick={onReplayDownstream} disabled={loading}>
          {t("recovery.restoreLatestRecommendationAction")}
        </button>
        <button type="button" className="button button--ghost" onClick={onReplayFullChain} disabled={loading}>
          {t("recovery.replayFullChainAction")}
        </button>
        <button type="button" className="button button--ghost" onClick={onDryRun} disabled={loading}>
          {t("recovery.previewRecommendationImpact")}
        </button>
      </div>

      {error && <div className="note-card note-card--danger">{error}</div>}
      {successMessage && <div className="note-card note-card--warning">{successMessage}</div>}

      {plan !== null && plan !== undefined && (
        <div className="note-stack">
          <div className="note-card">
            <strong>{plan ? t("recovery.planReady") : t("recovery.planUnavailable")}</strong>
            {plan && (
              <div className="recovery-plan-copy">
                {t("recovery.planRecommendationCopy", {
                  count: downstreamNodes.length || fullChainNodes.length || 0,
                })}
              </div>
            )}
            {plan?.estimated_duration_ms && (
              <div className="recovery-plan-copy">{t("recovery.estimatedDuration")} {plan.estimated_duration_ms}ms</div>
            )}
            {(plan?.affected_outputs || []).length > 0 && (
              <div className="tag-cluster tag-cluster--compact">
                {(plan?.affected_outputs || []).map((output) => (
                  <span className="tag-chip" key={output}>
                    {getImpactText(locale, output)}
                  </span>
                ))}
              </div>
            )}
          </div>
          {downstreamNodes.length > 0 && (
            <div className="operator-chain">
              <div className="readiness-inspector__label">{t("recovery.restoreChain")}</div>
              <div className="operator-chain__steps">
                {downstreamNodes.map((node, i) => (
                  <div key={node.job_name || i} className="operator-chain__step">
                    {i > 0 && <span className="operator-chain__arrow">→</span>}
                    <span className="operator-chain__job">{node.job_name || "?"}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {fullChainNodes.length > 0 && (
            <div className="operator-chain">
              <div className="readiness-inspector__label">{t("recovery.fullChain")}</div>
              <div className="operator-chain__steps">
                {fullChainNodes.map((node, i) => (
                  <div key={node.job_name || i} className="operator-chain__step">
                    {i > 0 && <span className="operator-chain__arrow">→</span>}
                    <span className="operator-chain__job">{node.job_name || "?"}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {downstreamNodes.length === 0 && fullChainNodes.length === 0 && plan && (
            <div className="readiness-inspector__subtle">{t("recovery.noDownstreamNodes")}</div>
          )}
        </div>
      )}

      <div className="readiness-inspector__subtle">
        {t("recovery.lastAction")} {lastActionAt ? formatDateTime(lastActionAt, locale === "zh-CN" ? "zh-CN" : "en-US") : "—"}
      </div>
    </div>
  );
}
