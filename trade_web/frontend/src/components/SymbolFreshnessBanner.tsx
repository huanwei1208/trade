import type { DecisionExplanation, KlineResponse, WorldState } from "../lib/api";
import { formatPercent } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { getDatasetText } from "../lib/statusText";
import { StatusPill } from "./StatusPill";

type SymbolFreshnessBannerProps = {
  kline?: KlineResponse | null;
  explanation?: DecisionExplanation | null;
  state?: WorldState | null;
  onOpenReadiness: () => void;
  onOpenRecovery: () => void;
  onRetry: () => void;
};

function summarizeInputWarning(t: (key: string, vars?: Record<string, string | number | null | undefined>) => string, warning: string) {
  if (warning.startsWith("used_defaults:")) {
    const count = Number.parseInt(warning.split(":")[1] || "0", 10);
    return t("symbol.freshness.usedDefaults", { count: Number.isFinite(count) ? count : "?" });
  }
  return warning;
}

export function SymbolFreshnessBanner({ kline, explanation, state, onOpenReadiness, onOpenRecovery, onRetry }: SymbolFreshnessBannerProps) {
  const { locale, t } = useI18n();
  const dqs = state?.data_quality_state;
  const missing = dqs?.missing_datasets || [];
  const stale = dqs?.stale_datasets || [];
  const inputWarnings = explanation?.input_warnings || [];
  const hasChart = Boolean(kline?.ohlcv?.length);
  const missingBlockers = (state?.blockers || []).filter((item) => item.includes("missing_datasets"));
  const freshnessScore = dqs?.freshness_score;
  const qualityScore = dqs?.score;

  const isConstrained = missing.length > 0 || missingBlockers.length > 0 || (!hasChart && missing.length > 0);
  const isDegraded = !isConstrained && (stale.length > 0 || inputWarnings.length > 0 || !hasChart || (typeof freshnessScore === "number" && freshnessScore < 0.85));

  const tone = isConstrained ? "err" : isDegraded ? "warn" : "ok";
  const headline = isConstrained
    ? t("symbol.freshness.constrainedTitle")
    : isDegraded
      ? t("symbol.freshness.degradedTitle")
      : t("symbol.freshness.freshTitle");
  const summary = isConstrained
    ? t("symbol.freshness.constrainedCopy")
    : isDegraded
      ? t("symbol.freshness.degradedCopy")
      : t("symbol.freshness.freshCopy");

  return (
    <div className={`symbol-freshness symbol-freshness--${tone}`}>
      <div className="symbol-freshness__head">
        <div>
          <div className="symbol-freshness__eyebrow">{t("symbol.freshness.eyebrow")}</div>
          <div className="symbol-freshness__title">{headline}</div>
          <div className="symbol-freshness__copy">{summary}</div>
        </div>
        <div className="symbol-freshness__pills">
          <StatusPill label={isConstrained ? t("symbol.freshness.reviewOnly") : isDegraded ? t("symbol.freshness.useWithCare") : t("symbol.freshness.freshEnough")} tone={tone} />
          {typeof freshnessScore === "number" && <StatusPill label={`${t("symbol.freshness.score")} · ${formatPercent(freshnessScore, 0)}`} tone={tone} subtle />}
          {typeof qualityScore === "number" && <StatusPill label={`${t("symbol.dataQualityScore")} · ${formatPercent(qualityScore, 0)}`} tone={tone} subtle />}
        </div>
      </div>

      <div className="symbol-freshness__body">
        {missing.length > 0 && (
          <div className="symbol-freshness__section">
            <div className="symbol-freshness__label">{t("symbol.missingDatasets")}</div>
            <div className="tag-cluster">
              {missing.map((dataset) => (
                <span className="tag-chip tag-chip--negative" key={dataset}>
                  {getDatasetText(locale, dataset)}
                </span>
              ))}
            </div>
          </div>
        )}

        {stale.length > 0 && (
          <div className="symbol-freshness__section">
            <div className="symbol-freshness__label">{t("symbol.staleDatasets")}</div>
            <div className="tag-cluster">
              {stale.map((dataset) => (
                <span className="tag-chip tag-chip--warning" key={dataset}>
                  {getDatasetText(locale, dataset)}
                </span>
              ))}
            </div>
          </div>
        )}

        {!hasChart && (
          <div className="note-card note-card--warning">
            {missing.length > 0 ? t("symbol.chartMissingReadiness") : t("symbol.freshness.noChartCopy")}
          </div>
        )}

        {inputWarnings.length > 0 && (
          <div className="symbol-freshness__section">
            <div className="symbol-freshness__label">{t("symbol.freshness.modelInputWarnings")}</div>
            <div className="note-stack">
              {inputWarnings.slice(0, 2).map((warning) => (
                <div className="note-card note-card--warning" key={warning}>
                  {summarizeInputWarning(t, warning)}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="symbol-freshness__footer">
        <div className="symbol-freshness__next">
          <strong>{t("symbol.freshness.nextStep")}</strong>
          <span>{isConstrained ? t("symbol.freshness.nextStepConstrained") : isDegraded ? t("symbol.freshness.nextStepDegraded") : t("symbol.freshness.nextStepFresh")}</span>
        </div>
        <div className="symbol-freshness__actions">
          <button type="button" className="button button--ghost" onClick={onOpenReadiness}>
            {t("common.openReadiness")}
          </button>
          <button type="button" className="button button--ghost" onClick={onOpenRecovery}>
            {t("common.openRecovery")}
          </button>
          <button type="button" className="button button--primary" onClick={onRetry}>
            {t("common.retry")}
          </button>
        </div>
      </div>
    </div>
  );
}
