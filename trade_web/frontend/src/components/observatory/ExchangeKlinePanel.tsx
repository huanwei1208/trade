import {
  Component,
  useEffect,
  useMemo,
  useState,
  type ComponentType,
  type ReactNode,
  type RefObject,
} from "react";

import type { ObsContext, ObsSingleSeries } from "../../lib/api";
import {
  aggregateObservatoryKlineModel,
  buildObservatoryKlineModel,
  type ObservatoryKlineModel,
  type ObservatoryKlineWindow,
} from "../../lib/observatoryChart";
import type { ObservatoryTimeframe } from "../../lib/observatory";

type LoadedChartProps = {
  model: ObservatoryKlineModel;
  selectedDate?: string | null;
  onSelectDate?: (date: string) => void;
  onRequestCompare?: () => void;
  dateInputRef?: RefObject<HTMLInputElement | null>;
  onTimeframeChange?: (timeframe: ObservatoryTimeframe) => void;
};

type ExchangeKlineModule = {
  ExchangeKlineChart: ComponentType<LoadedChartProps>;
};

type KlineRuntimeBoundaryProps = {
  children: ReactNode;
  resetKey: number;
  onRetry: () => void;
  onRequestCompare?: () => void;
};

class KlineRuntimeBoundary extends Component<KlineRuntimeBoundaryProps, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidUpdate(previous: KlineRuntimeBoundaryProps) {
    if (this.state.failed && previous.resetKey !== this.props.resetKey) {
      this.setState({ failed: false });
    }
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div
        className="obs-kline-state obs-kline-state--error"
        role="alert"
        data-testid="exchange-kline-runtime-error"
      >
        <strong>Daily chart runtime unavailable</strong>
        <span>Reason code: CHART_RUNTIME_FAILED</span>
        <div>
          <button type="button" onClick={this.props.onRetry}>
            Retry chart
          </button>
          {this.props.onRequestCompare ? (
            <button type="button" onClick={this.props.onRequestCompare}>
              Open Compare
            </button>
          ) : null}
        </div>
      </div>
    );
  }
}

export function loadExchangeKlineChart(): Promise<ExchangeKlineModule> {
  return import("./ExchangeKlineChart");
}

type ExchangeKlinePanelProps = {
  series: ObsSingleSeries;
  context: ObsContext;
  selectedDate?: string | null;
  onSelectDate?: (date: string) => void;
  onRequestCompare?: () => void;
  onRetrySeries?: () => void;
  dateInputRef?: RefObject<HTMLInputElement | null>;
  loadChart?: () => Promise<ExchangeKlineModule>;
  window?: ObservatoryKlineWindow | null;
  timeframe?: ObservatoryTimeframe;
  onTimeframeChange?: (timeframe: ObservatoryTimeframe) => void;
};

export function ExchangeKlinePanel({
  series,
  context,
  selectedDate,
  onSelectDate,
  onRequestCompare,
  onRetrySeries,
  dateInputRef,
  onTimeframeChange,
  loadChart = loadExchangeKlineChart,
  window,
  timeframe = "1D",
}: ExchangeKlinePanelProps) {
  const windowFrom = window?.from ?? null;
  const windowTo = window?.to ?? null;
  const adaptation = useMemo(() => {
    const startedAt = performance.now();
    const adapterWindow =
      windowFrom === null || windowTo === null ? null : { from: windowFrom, to: windowTo };
    const model = buildObservatoryKlineModel(series, context, undefined, adapterWindow);
    return { model, durationMs: performance.now() - startedAt };
  }, [context, series, windowFrom, windowTo]);
  const model = useMemo(
    () => aggregateObservatoryKlineModel(adaptation.model, timeframe),
    [adaptation.model, timeframe],
  );
  const [ChartComponent, setChartComponent] = useState<ComponentType<LoadedChartProps> | null>(
    null,
  );
  const [loadFailure, setLoadFailure] = useState(false);
  const [loadVersion, setLoadVersion] = useState(0);
  const [runtimeRecoveryVersion, setRuntimeRecoveryVersion] = useState(0);

  useEffect(() => {
    if (model.state === "invalid" || model.state === "empty") return;
    let disposed = false;
    setLoadFailure(false);
    setChartComponent(null);
    loadChart()
      .then((module) => {
        if (!disposed) {
          if (typeof module?.ExchangeKlineChart !== "function") {
            setLoadFailure(true);
            return;
          }
          setChartComponent(() => module.ExchangeKlineChart);
        }
      })
      .catch(() => {
        if (!disposed) setLoadFailure(true);
      });
    return () => {
      disposed = true;
    };
  }, [loadChart, loadVersion, model.state]);

  if (model.state === "empty") {
    return (
      <div className="obs-kline-state" role="status" data-testid="exchange-kline-empty">
        <strong>No confirmed daily bars</strong>
        <span>The selected snapshot returned no rows or declared daily exclusions.</span>
        {onRequestCompare ? (
          <button type="button" onClick={onRequestCompare}>
            Open Compare
          </button>
        ) : null}
      </div>
    );
  }

  if (model.state === "invalid") {
    const omittedFatalReasonCodeCount =
      Math.max(0, model.fatalReasonCodes.length - 8) + model.omittedFatalReasonCodeCount;
    return (
      <div
        className="obs-kline-state obs-kline-state--error"
        role="alert"
        data-testid="exchange-kline-invalid"
      >
        <strong>Selected-channel daily chart unavailable</strong>
        <span>The snapshot could not be rendered without inventing or mixing market evidence.</span>
        <span>Reason codes: {model.fatalReasonCodes.slice(0, 8).join(", ")}</span>
        {omittedFatalReasonCodeCount > 0 ? (
          <span>
            {omittedFatalReasonCodeCount} additional reason{" "}
            {omittedFatalReasonCodeCount === 1 ? "code" : "codes"} omitted.
          </span>
        ) : null}
        <div>
          {onRetrySeries ? (
            <button type="button" onClick={onRetrySeries}>
              Retry series
            </button>
          ) : null}
          {onRequestCompare ? (
            <button type="button" onClick={onRequestCompare}>
              Open Compare
            </button>
          ) : null}
        </div>
      </div>
    );
  }

  if (loadFailure) {
    return (
      <div
        className="obs-kline-state obs-kline-state--error"
        role="alert"
        data-testid="exchange-kline-load-error"
      >
        <strong>Daily chart module unavailable</strong>
        <span>Reason code: CHART_MODULE_LOAD_FAILED</span>
        <div>
          <button type="button" onClick={() => setLoadVersion((current) => current + 1)}>
            Retry chart
          </button>
          {onRequestCompare ? (
            <button type="button" onClick={onRequestCompare}>
              Open Compare
            </button>
          ) : null}
        </div>
      </div>
    );
  }

  if (!ChartComponent) {
    return (
      <div className="obs-kline-state" role="status" data-testid="exchange-kline-loading">
        Loading exchange-style daily chart…
      </div>
    );
  }

  return (
    <div
      className="obs-kline-panel"
      data-testid="exchange-kline-panel"
      data-adapter-duration-ms={adaptation.durationMs.toFixed(3)}
    >
      <KlineRuntimeBoundary
        resetKey={runtimeRecoveryVersion}
        onRetry={() => setRuntimeRecoveryVersion((current) => current + 1)}
        onRequestCompare={onRequestCompare}
      >
        <ChartComponent
          key={runtimeRecoveryVersion}
          model={model}
          selectedDate={selectedDate}
          onSelectDate={onSelectDate}
          onRequestCompare={onRequestCompare}
          dateInputRef={dateInputRef}
          onTimeframeChange={onTimeframeChange}
        />
      </KlineRuntimeBoundary>
    </div>
  );
}
