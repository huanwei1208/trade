import { useState } from "react";

import { BeliefCausalTimeline } from "../components/BeliefCausalTimeline";
import { BeliefWorkspace } from "../components/BeliefWorkspace";
import { DataTrustPanel } from "../components/DataTrustPanel";
import { DecisionChangeStrip } from "../components/DecisionChangeStrip";
import { EmptyState } from "../components/EmptyState";
import { ErrorState } from "../components/ErrorState";
import { ExplanationRail } from "../components/ExplanationRail";
import { LoadingSkeleton } from "../components/LoadingSkeleton";
import { SymbolChart } from "../components/SymbolChart";
import { SymbolChartToolbar } from "../components/SymbolChartToolbar";
import { SymbolDecisionPanel } from "../components/SymbolDecisionPanel";
import { SymbolFreshnessBanner } from "../components/SymbolFreshnessBanner";
import { SymbolQuoteStrip } from "../components/SymbolQuoteStrip";
import { SymbolReasonBoard } from "../components/SymbolReasonBoard";
import { SymbolWorkspaceTabs, useWorkspaceTab } from "../components/SymbolWorkspaceTabs";
import type { AdjustMode, BeliefGraphResponse, DecisionExplanation, IndicatorMode, KlineResponse, WorldState } from "../lib/api";
import { useApiResource } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { getDatasetText } from "../lib/statusText";

type SymbolPageProps = {
  symbol?: string;
  refreshToken: number;
  onBack: () => void;
  onOpenOpsFocus: (focus: { tab: "readiness" | "recovery"; date?: string; dataset?: string }) => void;
};

export function SymbolPage({ symbol, refreshToken, onBack, onOpenOpsFocus }: SymbolPageProps) {
  const { t } = useI18n();
  const [activeEvidenceSource, setActiveEvidenceSource] = useState<string | null>(null);
  const [markerKey, setMarkerKey] = useState<string | null>(null);
  const [invalidationFocused, setInvalidationFocused] = useState(false);
  const [adjustMode, setAdjustMode] = useState<AdjustMode>("qfq");
  const [indicatorMode, setIndicatorMode] = useState<IndicatorMode>("rsi");
  const [showEvents, setShowEvents] = useState(true);
  const [activeTab, setActiveTab] = useWorkspaceTab();

  const klineResource = useApiResource<KlineResponse>(
    symbol ? `/api/kline/${symbol}?adjust=${adjustMode}` : null,
    {
      deps: [symbol, refreshToken, adjustMode],
      cacheKey: symbol ? `trade-web:kline:${symbol}:${adjustMode}` : undefined,
    }
  );
  const explainResource = useApiResource<DecisionExplanation>(symbol ? `/api/explain/${symbol}` : null, {
    deps: [symbol, refreshToken],
    cacheKey: symbol ? `trade-web:explain:${symbol}` : undefined,
  });
  const stateResource = useApiResource<WorldState>(symbol ? `/api/state/${symbol}` : null, {
    deps: [symbol, refreshToken],
    cacheKey: symbol ? `trade-web:state:${symbol}` : undefined,
  });
  const beliefGraphResource = useApiResource<BeliefGraphResponse>(symbol ? `/api/belief-graph/${symbol}` : null, {
    deps: [symbol, refreshToken],
    cacheKey: symbol ? `trade-web:belief-graph:${symbol}` : undefined,
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

  const explanation: DecisionExplanation | null =
    explainResource.data || (klineResource.data?.explanation as DecisionExplanation) || null;
  const focusDate = explanation?.as_of || klineResource.data?.as_of || stateResource.data?.as_of_date;
  const focusDataset = resolveSymbolOpsDataset(stateResource.data, klineResource.data);

  function openReadiness() {
    onOpenOpsFocus({ tab: "readiness", date: focusDate, dataset: focusDataset });
  }
  function openRecovery() {
    onOpenOpsFocus({ tab: "recovery", date: focusDate, dataset: focusDataset });
  }
  function retrySymbolResources() {
    klineResource.retry();
    explainResource.retry();
    stateResource.retry();
  }

  // Merge reason_groups from kline response and from explanation
  const reasonGroups = klineResource.data?.reason_groups || explanation?.reason_groups || null;

  return (
    <div className="page-stack page-symbol">
      {/* Always visible: Quote Strip */}
      <SymbolQuoteStrip
        symbol={symbol}
        name={klineResource.data?.name}
        quote={klineResource.data?.quote}
        priceBasis={klineResource.data?.price_basis}
        onBack={onBack}
      />

      {/* Always visible: Freshness Banner */}
      <SymbolFreshnessBanner
        kline={klineResource.data}
        explanation={explanation}
        state={stateResource.data}
        onOpenReadiness={openReadiness}
        onOpenRecovery={openRecovery}
        onRetry={retrySymbolResources}
      />

      {/* Workspace tab bar */}
      <SymbolWorkspaceTabs activeTab={activeTab} onChange={setActiveTab} />

      {/* Tab body */}
      {activeTab === "decision" && (
        <div className="symbol-tab-body symbol-tab-body--decision">
          {/* Decision change strip */}
          <DecisionChangeStrip kline={klineResource.data} explanation={explanation} />

          {/* Chart workspace */}
          <div className="symbol-chart-workspace">
            <SymbolChartToolbar
              adjustMode={adjustMode}
              indicatorMode={indicatorMode}
              showEvents={showEvents}
              onAdjustChange={setAdjustMode}
              onIndicatorChange={setIndicatorMode}
              onShowEventsChange={setShowEvents}
            />
            <SymbolChart
              kline={klineResource.data}
              explanation={explanation}
              state={stateResource.data}
              activeEvidenceSource={activeEvidenceSource}
              invalidationFocused={invalidationFocused}
              indicatorMode={indicatorMode}
              showEvents={showEvents}
              showBeliefOverlay={false}
              onMarkerHover={(value) => setMarkerKey(value)}
              onOpenReadiness={openReadiness}
              onOpenRecovery={openRecovery}
            />
          </div>

          {/* Decision panel + Reason board */}
          <div className="symbol-workspace-row">
            <div className="symbol-workspace-row__decision">
              {explainResource.loading && !explanation ? (
                <LoadingSkeleton variant="panel" />
              ) : (
                <SymbolDecisionPanel
                  explanation={explanation}
                  state={stateResource.data}
                  onOpenReadiness={openReadiness}
                  onOpenRecovery={openRecovery}
                />
              )}
            </div>
            <div className="symbol-workspace-row__reasons">
              <SymbolReasonBoard
                reasonGroups={reasonGroups}
                explanation={explanation}
              />
            </div>
          </div>

          {/* Slim explanation rail */}
          {explanation && (
            <div className="symbol-decision-rail">
              <ExplanationRail
                explanation={explanation}
                activeEvidenceSource={activeEvidenceSource}
                markerActive={Boolean(markerKey)}
                onEvidenceHover={setActiveEvidenceSource}
                onInvalidatorClick={() => {
                  setInvalidationFocused(true);
                  window.setTimeout(() => setInvalidationFocused(false), 1200);
                }}
                slim
              />
            </div>
          )}
        </div>
      )}

      {activeTab === "belief" && (
        <div className="symbol-tab-body symbol-tab-body--belief">
          <BeliefWorkspace
            data={beliefGraphResource.data}
            loading={beliefGraphResource.loading}
          />
        </div>
      )}

      {activeTab === "timeline" && (
        <div className="symbol-tab-body symbol-tab-body--timeline">
          <BeliefCausalTimeline
            beliefGraph={beliefGraphResource.data}
            kline={klineResource.data}
          />
        </div>
      )}

      {activeTab === "data-trust" && (
        <div className="symbol-tab-body symbol-tab-body--data-trust">
          <DataTrustPanel
            explanation={explanation}
            state={stateResource.data}
            kline={klineResource.data}
            beliefGraph={beliefGraphResource.data}
          />
        </div>
      )}
    </div>
  );
}

function resolveSymbolOpsDataset(state?: WorldState | null, kline?: KlineResponse | null) {
  const missing = state?.data_quality_state?.missing_datasets || [];
  const stale = state?.data_quality_state?.stale_datasets || [];
  const candidate = missing[0] || stale[0] || (kline?.ohlcv?.length ? "recommendation" : "kline");
  return candidate.replace(/^tushare_/, "");
}
