import {
  Component,
  useCallback,
  useEffect,
  useMemo,
  useRef,
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
  view?: KlineViewportRange | null;
  recent?: KlineViewportRange | null;
  onRange?: (range: KlineViewportRange) => void;
};

type KlineViewportRange = {
  from: number;
  to: number;
};

type KlineDateRange = {
  from: string;
  to: string;
};
type KlineViewportCache = {
  version: 1;
  kind: "market.kline.viewport";
  id: string;
  from: string;
  to: string;
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

const KLINE_VIEWPORT_STORAGE_KEY = "trade-web:observatory:klineViewport:v1";
const KLINE_VIEWPORT_KIND = "market.kline.viewport";
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

function normalizeVisibleRange(range: { from: unknown; to: unknown }): KlineDateRange | null {
  const from = typeof range.from === "string" ? range.from.slice(0, 10) : "";
  const to = typeof range.to === "string" ? range.to.slice(0, 10) : "";
  return ISO_DATE.test(from) && ISO_DATE.test(to) && from < to ? { from, to } : null;
}

function recentVisibleRange(
  model: ObservatoryKlineModel,
  timeframe: ObservatoryTimeframe,
): KlineDateRange | null {
  const dates = model.dates.filter((date) => model.readouts[date]);
  if (dates.length < 2) return null;
  const visibleBars = timeframe === "1D" ? 31 : timeframe === "1W" ? 5 : 2;
  return {
    from: dates[Math.max(0, dates.length - visibleBars)],
    to: dates[dates.length - 1],
  };
}

function viewportStorageId(
  model: ObservatoryKlineModel,
  timeframe: ObservatoryTimeframe,
  context: ObsContext,
): string {
  const identity = model.identity;
  const lifecycle = model.lifecycle;
  return [
    KLINE_VIEWPORT_KIND,
    identity?.assetId ?? "unknown",
    identity?.displaySymbol ?? "unknown",
    identity?.provider ?? "unknown",
    identity?.instrument ?? "unknown",
    identity?.quote ?? "unknown",
    identity?.interval ?? "unknown",
    lifecycle?.channel ?? "unknown",
    lifecycle?.publication ?? "unknown",
    context.requested_knowledge_as_of ?? "unknown",
    context.knowledge_mode ?? "unknown",
    context.revision_policy ?? "unknown",
    timeframe,
  ].join("|");
}

function hasReadoutInRange(model: ObservatoryKlineModel, from: number, to: number): boolean {
  const start = Math.max(0, Math.floor(from));
  const end = Math.min(model.dates.length - 1, Math.ceil(to));
  for (let index = start; index <= end; index += 1) {
    if (model.readouts[model.dates[index]]) return true;
  }
  return false;
}

function loadVisibleRange(storageId: string, model: ObservatoryKlineModel): KlineDateRange | null {
  try {
    const raw = window.localStorage.getItem(KLINE_VIEWPORT_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<KlineViewportCache>;
    const range =
      parsed.version === 1 && parsed.kind === KLINE_VIEWPORT_KIND && parsed.id === storageId
        ? normalizeVisibleRange({ from: parsed.from, to: parsed.to })
        : null;
    if (!range) return null;
    const from = model.dates.indexOf(range.from);
    const to = model.dates.indexOf(range.to);
    return from >= 0 && to >= 0 && model.readouts[range.from] && model.readouts[range.to]
      ? range
      : null;
  } catch {
    return null;
  }
}

function logicalRangeForDates(
  model: ObservatoryKlineModel,
  range: KlineDateRange | null,
): KlineViewportRange | null {
  if (!range) return null;
  const from = model.dates.indexOf(range.from);
  const to = model.dates.indexOf(range.to);
  if (from < 0 || to < 0 || !hasReadoutInRange(model, from, to)) return null;
  return {
    from,
    to,
  };
}

function serializeVisibleRange(
  storageId: string,
  model: ObservatoryKlineModel,
  range: KlineViewportRange,
): string | null {
  const fromIndex = Math.max(0, Math.min(model.dates.length - 1, Math.floor(range.from)));
  const toIndex = Math.max(0, Math.min(model.dates.length - 1, Math.ceil(range.to)));
  if (!hasReadoutInRange(model, fromIndex, toIndex)) return null;
  const from = model.dates[fromIndex];
  const to = model.dates[toIndex];
  if (!from || !to) return null;
  if (!model.readouts[from] || !model.readouts[to]) return null;
  const normalized = normalizeVisibleRange({ from, to });
  if (!normalized) return null;
  return JSON.stringify({
    version: 1,
    kind: KLINE_VIEWPORT_KIND,
    id: storageId,
    from: normalized.from,
    to: normalized.to,
  } satisfies KlineViewportCache);
}

function saveVisibleRange(payload: string): boolean {
  try {
    window.localStorage.setItem(KLINE_VIEWPORT_STORAGE_KEY, payload);
    return true;
  } catch {
    // Viewport persistence is a convenience and must not block chart rendering.
    return false;
  }
}

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
  window: adapterWindow,
  timeframe = "1D",
}: ExchangeKlinePanelProps) {
  const windowFrom = adapterWindow?.from ?? null;
  const windowTo = adapterWindow?.to ?? null;
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
  const viewportId = useMemo(
    () => viewportStorageId(model, timeframe, context),
    [context, model, timeframe],
  );
  const recentLogicalRange = useMemo(
    () => logicalRangeForDates(model, recentVisibleRange(model, timeframe)),
    [model, timeframe],
  );
  const initialVisibleRange = useMemo(
    () =>
      logicalRangeForDates(
        model,
        loadVisibleRange(viewportId, model) ?? recentVisibleRange(model, timeframe),
      ),
    [model, timeframe, viewportId],
  );
  const pendingViewportPayloadRef = useRef<string | null>(null);
  const lastViewportPayloadRef = useRef<string | null>(null);
  const viewportStorageFailedRef = useRef(false);
  const initialViewportPayloadRef = useRef<string | null>(null);
  const viewportWriteFrameRef = useRef<number | null>(null);
  const flushVisibleRange = useCallback(() => {
    viewportWriteFrameRef.current = null;
    const payload = pendingViewportPayloadRef.current;
    pendingViewportPayloadRef.current = null;
    if (!payload || payload === lastViewportPayloadRef.current) return;
    if (saveVisibleRange(payload)) {
      lastViewportPayloadRef.current = payload;
    } else {
      viewportStorageFailedRef.current = true;
    }
  }, []);
  useEffect(
    () => () => {
      if (viewportWriteFrameRef.current !== null) {
        window.cancelAnimationFrame(viewportWriteFrameRef.current);
        viewportWriteFrameRef.current = null;
      }
      flushVisibleRange();
    },
    [flushVisibleRange],
  );
  const handleVisibleRangeChange = useCallback(
    (range: KlineViewportRange) => {
      if (viewportStorageFailedRef.current) return;
      const payload = serializeVisibleRange(viewportId, model, range);
      if (!payload || payload === lastViewportPayloadRef.current) return;
      if (payload === initialViewportPayloadRef.current) {
        initialViewportPayloadRef.current = null;
        return;
      }
      pendingViewportPayloadRef.current = payload;
      if (viewportWriteFrameRef.current === null) {
        viewportWriteFrameRef.current = window.requestAnimationFrame(flushVisibleRange);
      }
    },
    [flushVisibleRange, model, viewportId],
  );
  useEffect(() => {
    initialViewportPayloadRef.current = initialVisibleRange
      ? serializeVisibleRange(viewportId, model, initialVisibleRange)
      : null;
  }, [initialVisibleRange, model, viewportId]);
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
          view={initialVisibleRange}
          recent={recentLogicalRange}
          onRange={handleVisibleRangeChange}
        />
      </KlineRuntimeBoundary>
    </div>
  );
}
