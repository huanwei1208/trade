import type { RefObject } from "react";

import { CompositeChart } from "../../components/observatory/CompositeChart";
import { DateEvidenceLens } from "../../components/observatory/DateEvidenceLens";
import { ExchangeKlinePanel } from "../../components/observatory/ExchangeKlinePanel";
import { ObservatoryErrorState } from "../../components/observatory/ObservatoryErrorState";
import {
  MarketSummary,
  WhatChanged,
  WhyNotFormal,
} from "../../components/observatory/OverviewPanels";
import { SnapshotContextBar } from "../../components/observatory/SnapshotContextBar";
import type {
  ObsChannel,
  ObsCompositeSeries,
  ObsContext,
  ObsDateEvidence,
  ObsSingleSeries,
} from "../../lib/api";
import {
  compositeLayerForChannel,
  type ObservatoryChartMode,
  type ObservatorySafeError,
  type ObservatoryWindowBounds,
} from "../../lib/observatory";
import { parseObservatoryError, type ObservatoryResourceState } from "./observatoryResource";

type MarketResource<T> = ObservatoryResourceState<T> & {
  loading: boolean;
  retry: () => void;
};

type MarketWorkspaceProps = {
  chartMode: ObservatoryChartMode;
  contextResource: MarketResource<ObsContext>;
  selectedSeriesResource: MarketResource<ObsSingleSeries>;
  compositeResource: MarketResource<ObsCompositeSeries>;
  dateEvidenceResource: MarketResource<ObsDateEvidence>;
  range: string;
  selectedDate: string | null;
  channel: ObsChannel;
  windowBounds: ObservatoryWindowBounds;
  windowError: ObservatorySafeError | null;
  historicalCompositeUnavailable: boolean;
  dateInspectorRef: RefObject<HTMLInputElement | null>;
  onChartModeChange: (mode: ObservatoryChartMode) => void;
  onSelectDate: (date: string) => void;
  onCloseDate: () => void;
};

function confirmedData<T>(resource: ObservatoryResourceState<T>): T | null {
  return resource.status === "confirmed" ? resource.data : null;
}

export function MarketWorkspace({
  chartMode,
  contextResource,
  selectedSeriesResource,
  compositeResource,
  dateEvidenceResource,
  range,
  selectedDate,
  channel,
  windowBounds,
  windowError,
  historicalCompositeUnavailable,
  dateInspectorRef,
  onChartModeChange,
  onSelectDate,
  onCloseDate,
}: MarketWorkspaceProps) {
  const context = confirmedData(contextResource);
  const selectedSeries = confirmedData(selectedSeriesResource);
  const composite = confirmedData(compositeResource);
  const evidence = confirmedData(dateEvidenceResource);
  const contextError = parseObservatoryError(contextResource.error);
  const selectedSeriesError = parseObservatoryError(selectedSeriesResource.error);
  const compositeError = parseObservatoryError(compositeResource.error);
  const dateError = parseObservatoryError(dateEvidenceResource.error);
  const selectedSeriesUnavailable =
    Boolean(windowError) ||
    selectedSeriesResource.status === "failed" ||
    selectedSeriesResource.status === "unavailable";
  const selectedSeriesPending =
    selectedSeriesResource.status === "idle" || selectedSeriesResource.loading;
  const historicalCompositeError: ObservatorySafeError | null = historicalCompositeUnavailable
    ? {
        message:
          "Composite overlays are unavailable for this historical knowledge cut because the response does not provide per-layer point-in-time proof.",
        reasonCodes: ["COMPOSITE_PIT_NOT_PROVEN"],
        evidenceRefs: [],
        retryable: false,
      }
    : null;
  const compositeUnavailable =
    Boolean(windowError) ||
    historicalCompositeUnavailable ||
    compositeResource.status === "failed" ||
    compositeResource.status === "unavailable";

  if (contextResource.status !== "confirmed" || !context) {
    return (
      <div className="obs-overview">
        <SnapshotContextBar
          context={context}
          status={contextResource.status}
          error={contextError}
          onRetry={contextResource.retry}
        />
        <div className="obs-dependent-blocked" role="status">
          Market chart, comparison, and date evidence remain blocked until the selected snapshot is
          confirmed.
        </div>
      </div>
    );
  }

  return (
    <div className="obs-overview">
      <SnapshotContextBar
        context={context}
        status={contextResource.status}
        error={contextError}
        onRetry={contextResource.retry}
      />

      <div className="obs-chart-mode" role="group" aria-label="Market chart view">
        <button
          type="button"
          className={chartMode === "market" ? "is-active" : ""}
          aria-pressed={chartMode === "market"}
          onClick={() => onChartModeChange("market")}
        >
          Market
        </button>
        <button
          type="button"
          className={chartMode === "compare" ? "is-active" : ""}
          aria-pressed={chartMode === "compare"}
          onClick={() => onChartModeChange("compare")}
        >
          Compare
        </button>
        <span>
          {chartMode === "market"
            ? "One selected channel · exchange-style daily OHLCV"
            : "Formal, candidate, and observed lifecycle comparison"}
        </span>
      </div>

      <section className="obs-chart-section">
        {windowError ? (
          <ObservatoryErrorState
            title="Selected market window unavailable"
            error={windowError}
            unavailable
            onRetry={contextResource.retry}
          />
        ) : chartMode === "market" ? (
          selectedSeriesUnavailable ? (
            <ObservatoryErrorState
              title="Selected-channel market series unavailable"
              error={selectedSeriesError}
              unavailable={selectedSeriesResource.status === "unavailable"}
              onRetry={selectedSeriesResource.retry}
            />
          ) : selectedSeriesPending ? (
            <div className="obs-empty" role="status">
              Loading selected-channel daily chart…
            </div>
          ) : selectedSeries && context ? (
            <ExchangeKlinePanel
              series={selectedSeries}
              context={context}
              window={
                windowBounds.kind === "bounded"
                  ? { from: windowBounds.from, to: windowBounds.to }
                  : null
              }
              selectedDate={selectedDate}
              onSelectDate={onSelectDate}
              onRequestCompare={() => onChartModeChange("compare")}
              onRetrySeries={selectedSeriesResource.retry}
              dateInputRef={dateInspectorRef}
            />
          ) : (
            <div className="obs-empty" role="status">
              Waiting for selected-channel daily chart…
            </div>
          )
        ) : compositeUnavailable ? (
          <ObservatoryErrorState
            title="Composite comparison unavailable"
            error={historicalCompositeError ?? compositeError}
            unavailable={
              historicalCompositeUnavailable || compositeResource.status === "unavailable"
            }
            onRetry={
              historicalCompositeUnavailable ? contextResource.retry : compositeResource.retry
            }
          />
        ) : compositeResource.loading ? (
          <div className="obs-empty" role="status">
            Loading separate composite comparison…
          </div>
        ) : composite ? (
          <CompositeChart
            composite={composite}
            range={range}
            selectedDate={selectedDate}
            onSelectDate={onSelectDate}
            dateInputRef={dateInspectorRef}
            excludedDates={context.excluded_dates}
            quarantineBreakLayer={compositeLayerForChannel(channel)}
          />
        ) : (
          <div className="obs-empty" role="status">
            Waiting for separate composite comparison…
          </div>
        )}
      </section>

      <div className="obs-overview__panels">
        {chartMode === "market" ? (
          <MarketSummary
            series={selectedSeries}
            context={context}
            loading={selectedSeriesPending}
            unavailable={selectedSeriesUnavailable}
          />
        ) : null}
        <WhyNotFormal context={context} />
        {chartMode === "compare" && composite ? (
          <WhatChanged composite={composite} excludedDates={context.excluded_dates} />
        ) : null}
      </div>

      <DateEvidenceLens
        date={selectedDate}
        channel={channel}
        evidence={evidence}
        loading={dateEvidenceResource.loading}
        error={windowError ?? dateError}
        onRetry={windowError ? contextResource.retry : dateEvidenceResource.retry}
        onClose={onCloseDate}
      />
    </div>
  );
}
