import type { ReadinessGridPayload } from "../lib/api";
import { formatPercent } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { getDatasetText, getImpactText } from "../lib/statusText";
import { PanelCard } from "./PanelCard";

type ReadinessSummaryCardsProps = {
  payload: ReadinessGridPayload;
};

export function ReadinessSummaryCards({ payload }: ReadinessSummaryCardsProps) {
  const { locale, t } = useI18n();
  const unstable = payload.summary.unstable_datasets || [];
  const todayImpact = payload.summary.today_impact;

  return (
    <div className="readiness-summary-grid">
      <PanelCard subdued className="readiness-summary-card">
        <div className="readiness-summary-card__label">{t("readiness.summary.overall")}</div>
        <div className="readiness-summary-card__value">{formatPercent(payload.summary.overall_readiness_pct, 0)}</div>
        <div className="readiness-summary-card__helper">{t("readiness.summary.overallCopy")}</div>
      </PanelCard>

      <PanelCard subdued className="readiness-summary-card">
        <div className="readiness-summary-card__label">{t("readiness.summary.blockedDays")}</div>
        <div className="readiness-summary-card__value">{payload.summary.blocked_days ?? 0}</div>
        <div className="readiness-summary-card__helper">{t("readiness.summary.blockedDaysCopy")}</div>
      </PanelCard>

      <PanelCard subdued className="readiness-summary-card">
        <div className="readiness-summary-card__label">{t("readiness.summary.unstable")}</div>
        <div className="readiness-summary-card__value">{unstable[0]?.issue_count ?? 0}</div>
        <div className="readiness-summary-card__helper">
          {unstable.slice(0, 2).map((item) => getDatasetText(locale, item.dataset, item.label)).join(" · ") || t("common.noData")}
        </div>
      </PanelCard>

      <PanelCard subdued className="readiness-summary-card">
        <div className="readiness-summary-card__label">{t("readiness.summary.todayImpact")}</div>
        <div className="readiness-summary-card__value">{todayImpact?.datasets?.length ?? 0}</div>
        <div className="readiness-summary-card__helper">
          {(todayImpact?.affected_outputs || []).slice(0, 3).map((item) => getImpactText(locale, item)).join(" · ") || t("readiness.noTodayImpact")}
        </div>
      </PanelCard>
    </div>
  );
}
