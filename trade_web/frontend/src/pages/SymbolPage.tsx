import { useState } from "react";

import { EmptyState } from "../components/EmptyState";
import { ErrorState } from "../components/ErrorState";
import { ExplanationRail } from "../components/ExplanationRail";
import { LoadingSkeleton } from "../components/LoadingSkeleton";
import { PanelCard } from "../components/PanelCard";
import { SectionHeader } from "../components/SectionHeader";
import { SymbolChart } from "../components/SymbolChart";
import { SymbolDecisionHeader } from "../components/SymbolDecisionHeader";
import type { DecisionExplanation, KlineResponse, WorldState } from "../lib/api";
import { useApiResource } from "../lib/api";
import { formatDate, formatPercent, humanizeEnum } from "../lib/format";

type SymbolPageProps = {
  symbol?: string;
  refreshToken: number;
  onBack: () => void;
};

export function SymbolPage({ symbol, refreshToken, onBack }: SymbolPageProps) {
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
    return <EmptyState title="No symbol selected" body="Open a symbol from Today or Candidates to enter the deep review workspace." />;
  }

  if (klineResource.loading && !klineResource.data) {
    return <LoadingSkeleton variant="chart" />;
  }

  if (klineResource.error && !klineResource.data) {
    return (
      <ErrorState
        title="Symbol workspace unavailable"
        body="The chart payload could not be loaded. Retry the symbol request or inspect backend availability."
        detail={klineResource.error.message}
        action={
          <button type="button" className="button button--primary" onClick={klineResource.retry}>
            Retry
          </button>
        }
      />
    );
  }

  const explanation: DecisionExplanation | null = explainResource.data || (klineResource.data?.explanation as DecisionExplanation) || null;

  return (
    <div className="page-stack page-symbol">
      <SymbolDecisionHeader symbol={symbol} kline={klineResource.data} explanation={explanation} state={stateResource.data} onBack={onBack} />

      <div className="symbol-layout">
        <div className="symbol-layout__chart">
          <PanelCard title="Price, events, and decision context" eyebrow="Chart workspace">
            <SymbolChart
              kline={klineResource.data}
              explanation={explanation}
              state={stateResource.data}
              activeEvidenceSource={activeEvidenceSource}
              invalidationFocused={invalidationFocused}
              onMarkerHover={(value) => setMarkerKey(value)}
            />
          </PanelCard>
        </div>

        <div className="symbol-layout__rail">
          {explainResource.loading && !explanation ? (
            <LoadingSkeleton variant="panel" />
          ) : explainResource.error && !explanation ? (
            <ErrorState title="Explanation unavailable" body="The chart loaded, but the structured explanation did not." detail={explainResource.error.message} action={<button type="button" className="button button--ghost" onClick={explainResource.retry}>Retry explanation</button>} />
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
        <SectionHeader title="Supporting context" subtitle="Secondary detail: historical events, data quality, and regime labels." />
        <div className="compact-grid">
          <PanelCard title="Recent event timeline" subdued>
            <div className="timeline-list">
              {(klineResource.data?.event_markers || []).slice(-8).reverse().map((item, index) => (
                <div className="timeline-list__row" key={`${item.date}-${item.event_type}-${index}`}>
                  <div className="timeline-list__date">{formatDate(item.date)}</div>
                  <div className="timeline-list__body">
                    <div className="timeline-list__title">{item.event_type || "Event"}</div>
                    <div className="timeline-list__copy">{item.title || "No title returned."}</div>
                  </div>
                  <div className="timeline-list__score">{formatPercent(item.kg_score, 0)}</div>
                </div>
              ))}
            </div>
          </PanelCard>

          <PanelCard title="Data quality" subdued>
            <div className="note-stack">
              {(explanation?.data_quality_notes || []).map((item) => (
                <div className="note-card note-card--warning" key={item}>
                  {item}
                </div>
              ))}
              {(explanation?.warnings || []).map((item) => (
                <div className="note-card note-card--danger" key={item}>
                  {item}
                </div>
              ))}
              {!explanation?.data_quality_notes?.length && !explanation?.warnings?.length && <div className="note-card">No extra quality warnings were returned.</div>}
            </div>
          </PanelCard>

          <PanelCard title="World state" subdued>
            <div className="regime-grid">
              <div className="regime-grid__item">
                <span>Market</span>
                <strong>{humanizeEnum(stateResource.data?.market_regime)}</strong>
              </div>
              <div className="regime-grid__item">
                <span>Event</span>
                <strong>{humanizeEnum(stateResource.data?.event_regime)}</strong>
              </div>
              <div className="regime-grid__item">
                <span>Sentiment</span>
                <strong>{humanizeEnum(stateResource.data?.sentiment_regime)}</strong>
              </div>
              <div className="regime-grid__item">
                <span>Technical</span>
                <strong>{humanizeEnum(stateResource.data?.technical_regime)}</strong>
              </div>
              <div className="regime-grid__item">
                <span>Liquidity</span>
                <strong>{humanizeEnum(stateResource.data?.liquidity_regime)}</strong>
              </div>
              <div className="regime-grid__item">
                <span>Uncertainty</span>
                <strong>{humanizeEnum(stateResource.data?.uncertainty_level)}</strong>
              </div>
            </div>
          </PanelCard>
        </div>
      </section>
    </div>
  );
}
