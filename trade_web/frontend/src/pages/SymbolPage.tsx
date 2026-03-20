import { useState } from "react";

import { EmptyState } from "../components/EmptyState";
import { ErrorState } from "../components/ErrorState";
import { ExplanationRail } from "../components/ExplanationRail";
import { LoadingSkeleton } from "../components/LoadingSkeleton";
import { PanelCard } from "../components/PanelCard";
import { SectionHeader } from "../components/SectionHeader";
import { SymbolChart } from "../components/SymbolChart";
import { SymbolDecisionHeader } from "../components/SymbolDecisionHeader";
import { SymbolFreshnessBanner } from "../components/SymbolFreshnessBanner";
import type { DecisionExplanation, KlineResponse, WorldState } from "../lib/api";
import { useApiResource } from "../lib/api";
import { formatDate, formatPercent } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { getDatasetText, getWorldStateLabel } from "../lib/statusText";

type SymbolPageProps = {
  symbol?: string;
  refreshToken: number;
  onBack: () => void;
  onOpenOpsFocus: (focus: { tab: "readiness" | "recovery"; date?: string; dataset?: string }) => void;
};

export function SymbolPage({ symbol, refreshToken, onBack, onOpenOpsFocus }: SymbolPageProps) {
  const { locale, t } = useI18n();
  const [activeEvidenceSource, setActiveEvidenceSource] = useState<string | null>(null);
  const [markerKey, setMarkerKey] = useState<string | null>(null);
  const [invalidationFocused, setInvalidationFocused] = useState(false);

  const klineResource = useApiResource<KlineResponse>(symbol ? `/api/kline/${symbol}` : null, {
    deps: [symbol, refreshToken],
    cacheKey: symbol ? `trade-web:kline:${symbol}` : undefined,
  });
  const explainResource = useApiResource<DecisionExplanation>(symbol ? `/api/explain/${symbol}` : null, {
    deps: [symbol, refreshToken],
    cacheKey: symbol ? `trade-web:explain:${symbol}` : undefined,
  });
  const stateResource = useApiResource<WorldState>(symbol ? `/api/state/${symbol}` : null, {
    deps: [symbol, refreshToken],
    cacheKey: symbol ? `trade-web:state:${symbol}` : undefined,
  });

  if (!symbol) {
    return <EmptyState title={t("symbol.none")} body={t("symbol.noneCopy")} />;
  }

  if (klineResource.loading && !klineResource.data) {
    return <LoadingSkeleton variant="chart" />;
  }

  if (klineResource.error && !klineResource.data) {
    return (
      <ErrorState
        title={t("symbol.unavailable")}
        body={t("symbol.unavailableCopy")}
        detail={klineResource.error.message}
        action={
          <button type="button" className="button button--primary" onClick={klineResource.retry}>
            {t("common.retry")}
          </button>
        }
      />
    );
  }

  const explanation: DecisionExplanation | null = explainResource.data || (klineResource.data?.explanation as DecisionExplanation) || null;
  const dqs = stateResource.data?.data_quality_state;
  const hasDqs = Boolean(dqs && (dqs.missing_datasets || dqs.stale_datasets || typeof dqs.freshness_score === "number" || typeof dqs.score === "number"));
  const focusDate = explanation?.as_of || klineResource.data?.as_of || stateResource.data?.as_of_date;
  const focusDataset = resolveSymbolOpsDataset(stateResource.data, klineResource.data);

  function openReadiness() {
    onOpenOpsFocus({
      tab: "readiness",
      date: focusDate,
      dataset: focusDataset,
    });
  }

  function openRecovery() {
    onOpenOpsFocus({
      tab: "recovery",
      date: focusDate,
      dataset: focusDataset,
    });
  }

  function retrySymbolResources() {
    klineResource.retry();
    explainResource.retry();
    stateResource.retry();
  }

  return (
    <div className="page-stack page-symbol">
      <SymbolDecisionHeader
        symbol={symbol}
        kline={klineResource.data}
        explanation={explanation}
        state={stateResource.data}
        onBack={onBack}
        onOpenReadiness={openReadiness}
        onOpenRecovery={openRecovery}
      />

      <SymbolFreshnessBanner
        kline={klineResource.data}
        explanation={explanation}
        state={stateResource.data}
        onOpenReadiness={openReadiness}
        onOpenRecovery={openRecovery}
        onRetry={retrySymbolResources}
      />

      <div className="symbol-layout">
        <div className="symbol-layout__chart">
          <PanelCard title={t("symbol.chartPanel")} eyebrow={t("symbol.chartWorkspace")}>
            <SymbolChart
              kline={klineResource.data}
              explanation={explanation}
              state={stateResource.data}
              activeEvidenceSource={activeEvidenceSource}
              invalidationFocused={invalidationFocused}
              onMarkerHover={(value) => setMarkerKey(value)}
              onOpenReadiness={openReadiness}
              onOpenRecovery={openRecovery}
            />
          </PanelCard>
        </div>

        <div className="symbol-layout__rail">
          {explainResource.loading && !explanation ? (
            <LoadingSkeleton variant="panel" />
          ) : explainResource.error && !explanation ? (
            <ErrorState title={t("symbol.explanationUnavailable")} body={t("symbol.explanationUnavailableCopy")} detail={explainResource.error.message} action={<button type="button" className="button button--ghost" onClick={explainResource.retry}>{t("common.retry")}</button>} />
          ) : (
            <ExplanationRail
              explanation={explanation}
              activeEvidenceSource={activeEvidenceSource}
              markerActive={Boolean(markerKey)}
              onEvidenceHover={setActiveEvidenceSource}
              onInvalidatorClick={() => {
                setInvalidationFocused(true);
                window.setTimeout(() => setInvalidationFocused(false), 1200);
              }}
            />
          )}
        </div>
      </div>

      <section className="page-section">
        <SectionHeader title={t("symbol.supportingContext")} subtitle={t("symbol.supportingContextSubtitle")} />
        <div className="compact-grid">
          <PanelCard title={t("symbol.dataQuality")} subdued>
            {hasDqs ? (
              <div className="data-quality-table">
                {typeof dqs!.score === "number" && (
                  <div className="data-quality-table__score-row">
                    <span className="data-quality-table__score-label">{t("symbol.dataQualityScore")}</span>
                    <strong className="data-quality-table__score-value">{formatPercent(dqs!.score, 0)}</strong>
                  </div>
                )}
                {typeof dqs!.freshness_score === "number" && (
                  <div className="data-quality-table__score-row">
                    <span className="data-quality-table__score-label">{t("symbol.freshnessScore")}</span>
                    <strong className="data-quality-table__score-value">{formatPercent(dqs!.freshness_score, 0)}</strong>
                  </div>
                )}
                {(dqs!.missing_datasets || []).length > 0 && (
                  <div className="data-quality-section">
                    <div className="data-quality-section__label">{t("symbol.missingDatasets")}</div>
                    <div className="tag-cluster">
                      {(dqs!.missing_datasets || []).map((ds) => (
                        <span className="tag-chip tag-chip--negative" key={ds}>
                          {getDatasetText(locale, ds)}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
                {(dqs!.stale_datasets || []).length > 0 && (
                  <div className="data-quality-section">
                    <div className="data-quality-section__label">{t("symbol.staleDatasets")}</div>
                    <div className="tag-cluster">
                      {(dqs!.stale_datasets || []).map((ds) => (
                        <span className="tag-chip tag-chip--warning" key={ds}>
                          {getDatasetText(locale, ds)}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
                {(dqs!.missing_datasets || []).length === 0 && (dqs!.stale_datasets || []).length === 0 && (
                  <div className="note-card">{t("symbol.noMissingDatasets")}</div>
                )}
                {dqs!.rationale && <div className="note-card note-card--warning">{dqs!.rationale}</div>}
              </div>
            ) : (
              <div className="note-stack">
                {(explanation?.data_quality_notes || []).map((item) => (
                  <div className="note-card note-card--warning" key={item}>{item}</div>
                ))}
                {(explanation?.warnings || []).map((item) => (
                  <div className="note-card note-card--danger" key={item}>{item}</div>
                ))}
                {!explanation?.data_quality_notes?.length && !explanation?.warnings?.length && (
                  <div className="note-card">{t("symbol.noQualityWarnings")}</div>
                )}
              </div>
            )}
          </PanelCard>

          <PanelCard title={t("symbol.timeline")} subdued>
            <div className="timeline-list">
              {(klineResource.data?.event_markers || []).slice(-8).reverse().map((item, index) => (
                <div className="timeline-list__row" key={`${item.date}-${item.event_type}-${index}`}>
                  <div className="timeline-list__date">{formatDate(item.date, locale === "zh-CN" ? "zh-CN" : "en-US")}</div>
                  <div className="timeline-list__body">
                    <div className="timeline-list__title">{item.event_type || t("common.event")}</div>
                    <div className="timeline-list__copy">{item.title || t("common.noSummary")}</div>
                  </div>
                  <div className="timeline-list__score">{formatPercent(item.kg_score, 0)}</div>
                </div>
              ))}
            </div>
          </PanelCard>

          <PanelCard title={t("symbol.worldState")} subdued>
            <div className="regime-grid">
              <div className="regime-grid__item">
                <span>{t("symbol.worldStateLabel.market")}</span>
                <strong>{getWorldStateLabel(locale, "market", stateResource.data?.market_regime)}</strong>
              </div>
              <div className="regime-grid__item">
                <span>{t("symbol.worldStateLabel.event")}</span>
                <strong>{getWorldStateLabel(locale, "event", stateResource.data?.event_regime)}</strong>
              </div>
              <div className="regime-grid__item">
                <span>{t("symbol.worldStateLabel.sentiment")}</span>
                <strong>{getWorldStateLabel(locale, "sentiment", stateResource.data?.sentiment_regime)}</strong>
              </div>
              <div className="regime-grid__item">
                <span>{t("symbol.worldStateLabel.technical")}</span>
                <strong>{getWorldStateLabel(locale, "technical", stateResource.data?.technical_regime)}</strong>
              </div>
              <div className="regime-grid__item">
                <span>{t("symbol.worldStateLabel.liquidity")}</span>
                <strong>{getWorldStateLabel(locale, "liquidity", stateResource.data?.liquidity_regime)}</strong>
              </div>
              <div className="regime-grid__item">
                <span>{t("symbol.worldStateLabel.uncertainty")}</span>
                <strong>{getWorldStateLabel(locale, "uncertainty", stateResource.data?.uncertainty_level)}</strong>
              </div>
            </div>
          </PanelCard>
        </div>
      </section>
    </div>
  );
}

function resolveSymbolOpsDataset(state?: WorldState | null, kline?: KlineResponse | null) {
  const missing = state?.data_quality_state?.missing_datasets || [];
  const stale = state?.data_quality_state?.stale_datasets || [];
  const candidate = missing[0] || stale[0] || (kline?.ohlcv?.length ? "recommendation" : "kline");
  return candidate.replace(/^tushare_/, "");
}
