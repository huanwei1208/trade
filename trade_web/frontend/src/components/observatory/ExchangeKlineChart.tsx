import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type RefObject,
} from "react";
import {
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  PriceScaleMode,
  createChart,
  createSeriesMarkers,
  type CandlestickData,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type MouseEventParams,
  type SeriesMarker,
  type Time,
  type WhitespaceData,
} from "lightweight-charts";

import type {
  ObservatoryKlineMarker,
  ObservatoryKlineModel,
  ObservatoryKlineLifecycle,
  ObservatoryKlineReadout,
} from "../../lib/observatoryChart";
import type { ObservatoryTimeframe } from "../../lib/observatory";

type ExchangeKlineChartProps = {
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

type ScaleMode = "linear" | "log";
type RendererState = "initializing" | "ready" | "failed";
type RendererFailure = {
  code: "CHART_CREATE_FAILED" | "CHART_DATA_REJECTED" | "CHART_RUNTIME_FAILED";
  retryable: boolean;
};
type CursorPlacement = "left" | "right";
type CursorReadoutState = {
  date: string;
  x: number;
  y: number;
  placement: CursorPlacement;
};
type KlineViewportRange = {
  from: number;
  to: number;
};

type ChartRuntime = {
  chart: IChartApi;
  candles: ISeriesApi<"Candlestick">;
  markers: ISeriesMarkersPluginApi<Time> | null;
};

const DIAGNOSTIC_PREVIEW_LIMIT = 8;
const DIAGNOSTIC_DETAILS_LIMIT = 50;

function normalizeEventDate(time: Time | undefined): string | null {
  if (typeof time === "string") {
    return time.slice(0, 10);
  }
  if (typeof time === "number") {
    return new Date(time * 1_000).toISOString().slice(0, 10);
  }
  if (time && typeof time === "object") {
    const month = String(time.month).padStart(2, "0");
    const day = String(time.day).padStart(2, "0");
    return `${String(time.year).padStart(4, "0")}-${month}-${day}`;
  }
  return null;
}

function cursorReadoutState(
  params: MouseEventParams<Time>,
  model: ObservatoryKlineModel,
  container: HTMLElement,
): CursorReadoutState | null {
  const date = normalizeEventDate(params.time);
  if (!date || !model.dates.includes(date) || !params.point) return null;
  const bounds = container.getBoundingClientRect();
  const width = bounds.width > 0 ? bounds.width : 800;
  const height = bounds.height > 0 ? bounds.height : 440;
  const x = Math.min(Math.max(params.point.x, 12), Math.max(12, width - 12));
  const y = Math.min(Math.max(params.point.y, 42), Math.max(42, height - 42));
  return {
    date,
    x,
    y,
    placement: x > width - 260 ? "left" : "right",
  };
}

function markerColor(marker: ObservatoryKlineMarker): string {
  if (marker.tone === "error") return "#ff5b6e";
  if (marker.tone === "warning") return "#ffb432";
  return "#4aa3ff";
}

function markerText(marker: ObservatoryKlineMarker): string {
  if (marker.reasonCodes.some((reason) => reason.startsWith("REVISION_"))) return "R";
  return "!";
}

function chartMarkers(model: ObservatoryKlineModel): SeriesMarker<Time>[] {
  return model.markers
    .filter((marker) => model.readouts[marker.time])
    .map(
      (marker) =>
        ({
          time: marker.time,
          position: marker.position === "below" ? "belowBar" : "aboveBar",
          shape: marker.tone === "info" ? "circle" : "square",
          color: markerColor(marker),
          text: markerText(marker),
          size: 0.8,
        }) satisfies SeriesMarker<Time>,
    );
}

function gapMarkers(model: ObservatoryKlineModel): ObservatoryKlineMarker[] {
  return model.markers.filter((marker) => !model.readouts[marker.time]);
}

function drawGapMarkerCanvas(
  chart: IChartApi,
  canvas: HTMLCanvasElement,
  markers: ObservatoryKlineMarker[],
): void {
  const bounds = canvas.getBoundingClientRect();
  if (bounds.width <= 0 || bounds.height <= 0) return;
  const ratio = Math.max(1, window.devicePixelRatio || 1);
  const width = Math.round(bounds.width * ratio);
  const height = Math.round(bounds.height * ratio);
  if (canvas.width !== width) canvas.width = width;
  if (canvas.height !== height) canvas.height = height;
  const context = canvas.getContext("2d");
  if (!context) return;
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  context.clearRect(0, 0, bounds.width, bounds.height);
  context.font = "700 10px sans-serif";
  context.textAlign = "center";
  context.textBaseline = "middle";

  for (const marker of markers) {
    const x = chart.timeScale().timeToCoordinate(marker.time as Time);
    if (x === null || x < 0 || x > bounds.width) continue;
    const y = marker.position === "below" ? bounds.height - 14 : 14;
    context.fillStyle = markerColor(marker);
    if (marker.tone === "info") {
      context.beginPath();
      context.arc(x, y, 7, 0, Math.PI * 2);
      context.fill();
    } else {
      context.fillRect(x - 7, y - 7, 14, 14);
    }
    context.fillStyle = "#071321";
    context.fillText(markerText(marker), x, y + 0.5);
  }
}

function safeCleanup(runtime: Partial<ChartRuntime>): void {
  try {
    runtime.markers?.detach();
  } catch {
    // Cleanup must remain idempotent even after a partial vendor failure.
  }
  try {
    runtime.chart?.remove();
  } catch {
    // No raw vendor exception may escape an Observatory teardown.
  }
}

function formatPinnedSummary(
  date: string | null | undefined,
  readout: ObservatoryKlineReadout | undefined,
  lifecycle: ObservatoryKlineLifecycle | null,
): string {
  if (!date) return "";
  const lifecyclePrefix = lifecycle ? `${lifecycle.channelLabel}, ${lifecycle.publication}. ` : "";
  if (!readout) {
    return `${lifecyclePrefix}${date} pinned. Daily OHLCV is unavailable for this date.`;
  }
  return `${lifecyclePrefix}${date} pinned. Open ${readout.open}, high ${readout.high}, low ${readout.low}, close ${readout.close}, volume ${readout.volume ?? "unavailable"}.`;
}

function formatKeyboardInspectionSummary(
  date: string,
  readout: ObservatoryKlineReadout | undefined,
  reasons: string[],
  lifecycle: ObservatoryKlineLifecycle | null,
): string {
  const lifecyclePrefix = lifecycle ? `${lifecycle.channelLabel}, ${lifecycle.publication}. ` : "";
  if (!readout) {
    const reasonSummary = reasons.length ? ` Reasons: ${reasons.join(", ")}.` : "";
    return `${lifecyclePrefix}${date} inspected. No plotted candle.${reasonSummary}`;
  }
  return `${lifecyclePrefix}${date} inspected. Open ${readout.open}, high ${readout.high}, low ${readout.low}, close ${readout.close}, volume ${readout.volume ?? "unavailable"}.`;
}

function diagnosticSummary(diagnostic: ObservatoryKlineModel["diagnostics"][number]): string {
  const parts = [diagnostic.reasonCodes.join(", ")];
  if (diagnostic.omittedReasonCodeCount > 0) {
    parts.push(
      `${diagnostic.omittedReasonCodeCount} additional reason ${diagnostic.omittedReasonCodeCount === 1 ? "code" : "codes"} omitted`,
    );
  }
  if (diagnostic.evidenceRefs.length > 0) {
    parts.push(`evidence ${diagnostic.evidenceRefs.join(", ")}`);
  }
  if (diagnostic.omittedEvidenceRefCount > 0) {
    parts.push(
      `${diagnostic.omittedEvidenceRefCount} additional evidence ${diagnostic.omittedEvidenceRefCount === 1 ? "reference" : "references"} omitted`,
    );
  }
  return parts.filter(Boolean).join(" · ");
}

function KlineReadout({
  date,
  readout,
  reasons,
  lifecycle,
}: {
  date: string | null;
  readout: ObservatoryKlineReadout | undefined;
  reasons: string[];
  lifecycle: ObservatoryKlineLifecycle | null;
}) {
  return (
    <div className="obs-kline__readout" data-testid="exchange-kline-readout">
      <span className="obs-kline__readout-date">{readout?.date ?? date ?? "No date"}</span>
      {lifecycle ? (
        <span className="obs-kline__readout-lifecycle">
          {lifecycle.channelLabel}
          {lifecycle.publication === "unpublished" ? " · UNPUBLISHED" : ""}
        </span>
      ) : null}
      {readout ? (
        <>
          <span>O&nbsp;{readout.open}</span>
          <span>H&nbsp;{readout.high}</span>
          <span>L&nbsp;{readout.low}</span>
          <span>C&nbsp;{readout.close}</span>
          <span>Vol&nbsp;{readout.volume ?? "—"}</span>
        </>
      ) : (
        <span className="obs-kline__readout-gap">
          No plotted candle{reasons.length ? ` · ${reasons.join(", ")}` : ""}
        </span>
      )}
    </div>
  );
}

function KlineCursorReadout({
  cursor,
  readout,
}: {
  cursor: CursorReadoutState | null;
  readout: ObservatoryKlineReadout | undefined;
}) {
  if (!cursor) return null;
  return (
    <div
      className={`obs-kline__cursor obs-kline__cursor--${cursor.placement}`}
      style={{ left: `${cursor.x}px`, top: `${cursor.y}px` }}
      data-testid="exchange-kline-cursor-readout"
      aria-hidden="true"
    >
      <div>
        <strong>{readout?.date ?? cursor.date}</strong>
      </div>
      {readout ? (
        <>
          <dl>
            <dt>O</dt>
            <dd>{readout.open}</dd>
            <dt>H</dt>
            <dd>{readout.high}</dd>
            <dt>L</dt>
            <dd>{readout.low}</dd>
            <dt>C</dt>
            <dd>{readout.close}</dd>
          </dl>
          <small>Vol {readout.volume ?? "—"}</small>
        </>
      ) : (
        <small>No plotted candle</small>
      )}
    </div>
  );
}

function KlineDiagnostics({ model }: { model: ObservatoryKlineModel }) {
  if (model.state !== "partial-invalid") {
    return null;
  }
  const dated = model.diagnostics.filter(
    (diagnostic): diagnostic is typeof diagnostic & { date: string } => diagnostic.date !== null,
  );
  const preview = dated.slice(0, DIAGNOSTIC_PREVIEW_LIMIT);
  const details = dated.slice(0, DIAGNOSTIC_DETAILS_LIMIT);

  return (
    <aside className="obs-kline__diagnostics" data-testid="exchange-kline-diagnostics">
      <div className="obs-kline__diagnostics-summary">
        <strong>Partial daily coverage</strong>
        <span>
          {model.renderedCandleCount} of {model.suppliedRowCount} supplied rows plotted;{" "}
          {model.affectedDateCount} affected dates.
        </span>
      </div>
      <div className="obs-kline__diagnostics-preview" aria-label="Affected date preview">
        {preview.map((diagnostic) => (
          <span key={diagnostic.date}>
            {diagnostic.date}: {diagnosticSummary(diagnostic)}
          </span>
        ))}
      </div>
      {dated.length > DIAGNOSTIC_PREVIEW_LIMIT ? (
        <details>
          <summary>Show bounded diagnostic details</summary>
          <ul>
            {details.map((diagnostic) => (
              <li key={diagnostic.date}>
                {diagnostic.date}: {diagnosticSummary(diagnostic)}
              </li>
            ))}
          </ul>
          {dated.length > DIAGNOSTIC_DETAILS_LIMIT ? (
            <p>{dated.length - DIAGNOSTIC_DETAILS_LIMIT} additional affected dates omitted.</p>
          ) : null}
        </details>
      ) : null}
    </aside>
  );
}

export function ExchangeKlineChart({
  model,
  selectedDate,
  onSelectDate,
  onRequestCompare,
  dateInputRef,
  onTimeframeChange,
  view,
  recent,
  onRange,
}: ExchangeKlineChartProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const gapMarkerCanvasRef = useRef<HTMLCanvasElement>(null);
  const fullscreenButtonRef = useRef<HTMLButtonElement>(null);
  const runtimeRef = useRef<ChartRuntime | null>(null);
  const onSelectDateRef = useRef(onSelectDate);
  const modelRef = useRef(model);
  const mountedRef = useRef(false);
  const scaleModeRef = useRef<ScaleMode>("linear");
  const fullscreenRequestGenerationRef = useRef(0);
  const ownedFullscreenRef = useRef(false);
  const hoverFrameRef = useRef<number | null>(null);
  const pendingHoverDateRef = useRef<string | null>(null);
  const pendingCursorRef = useRef<CursorReadoutState | null>(null);
  const lastHoverDateRef = useRef<string | null>(null);
  const [hoveredDate, setHoveredDate] = useState<string | null>(null);
  const [inspectedDate, setInspectedDate] = useState<string | null>(null);
  const [cursorReadout, setCursorReadout] = useState<CursorReadoutState | null>(null);
  const [scaleMode, setScaleMode] = useState<ScaleMode>("linear");
  const [rendererState, setRendererState] = useState<RendererState>("initializing");
  const [rendererFailure, setRendererFailure] = useState<RendererFailure | null>(null);
  const [retryVersion, setRetryVersion] = useState(0);
  const [expandedFallback, setExpandedFallback] = useState(false);
  const [fullscreenActive, setFullscreenActive] = useState(false);
  const [keyboardAnnouncement, setKeyboardAnnouncement] = useState("");

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      fullscreenRequestGenerationRef.current += 1;
    };
  }, []);

  useEffect(() => {
    onSelectDateRef.current = onSelectDate;
  }, [onSelectDate]);

  useEffect(() => {
    modelRef.current = model;
  }, [model]);

  const latestDate = useMemo(() => {
    for (let index = model.dates.length - 1; index >= 0; index -= 1) {
      const date = model.dates[index];
      if (model.readouts[date]) return date;
    }
    return null;
  }, [model]);
  const selectedDisplayDate = selectedDate
    ? (model.dates.find(
        (date) => date === selectedDate || model.canonicalDates?.[date] === selectedDate,
      ) ?? null)
    : null;
  const activeDate = inspectedDate ?? hoveredDate ?? selectedDisplayDate ?? latestDate;
  const activeReadout = activeDate ? model.readouts[activeDate] : undefined;
  const activeReasons = activeDate
    ? (model.diagnostics.find((diagnostic) => diagnostic.date === activeDate)?.reasonCodes ?? [])
    : [];
  const sourceDates = model.dates
    .map((date) => model.canonicalDates?.[date] ?? date)
    .filter((date): date is string => date !== null);
  const inspectDate = inspectedDate ?? hoveredDate ?? selectedDisplayDate;
  const timeframe = model.timeframe ?? "1D";
  const cursorReadoutData = cursorReadout ? model.readouts[cursorReadout.date] : undefined;

  const canonicalSourceDate = useCallback((date: string | null): string | null => {
    if (!date) return null;
    const model = modelRef.current;
    if (model.dates.includes(date)) return model.canonicalDates?.[date] ?? date;
    const displayDate = model.dates.find((candidate) => model.canonicalDates?.[candidate] === date);
    return displayDate ? (model.canonicalDates?.[displayDate] ?? displayDate) : null;
  }, []);

  const pinDate = useCallback(
    (date: string | null) => {
      const sourceDate = canonicalSourceDate(date);
      if (!sourceDate || !onSelectDateRef.current) {
        return;
      }
      try {
        onSelectDateRef.current(sourceDate);
      } catch {
        setRendererFailure({ code: "CHART_RUNTIME_FAILED", retryable: true });
      }
    },
    [canonicalSourceDate],
  );

  const moveProgrammaticCrosshair = useCallback((date: string | null) => {
    const runtime = runtimeRef.current;
    const readout = date ? modelRef.current.readouts[date] : undefined;
    try {
      if (runtime && date && readout) {
        runtime.chart.setCrosshairPosition(Number(readout.close), date, runtime.candles);
      } else {
        runtime?.chart.clearCrosshairPosition();
      }
    } catch {
      setRendererFailure({ code: "CHART_RUNTIME_FAILED", retryable: true });
    }
  }, []);

  useEffect(() => {
    const container = canvasRef.current;
    if (!container) return;

    let disposed = false;
    const runtime: Partial<ChartRuntime> = {};
    let gapMarkerFrame: number | null = null;
    let resizeObserver: ResizeObserver | null = null;
    let initializationFailureCode: RendererFailure["code"] = "CHART_CREATE_FAILED";
    setRendererFailure(null);
    setRendererState("initializing");
    setKeyboardAnnouncement("");
    pendingCursorRef.current = null;
    setCursorReadout(null);

    const scheduleHover = (params: MouseEventParams<Time>) => {
      if (disposed) return;
      const eventDate = normalizeEventDate(params.time);
      pendingHoverDateRef.current =
        eventDate && modelRef.current.dates.includes(eventDate) ? eventDate : null;
      pendingCursorRef.current = cursorReadoutState(params, modelRef.current, container);
      if (hoverFrameRef.current !== null) return;
      hoverFrameRef.current = window.requestAnimationFrame(() => {
        hoverFrameRef.current = null;
        if (disposed) return;
        const nextDate = pendingHoverDateRef.current;
        if (nextDate !== lastHoverDateRef.current) {
          lastHoverDateRef.current = nextDate;
          setHoveredDate(nextDate);
        }
        setCursorReadout(pendingCursorRef.current);
      });
    };
    const handleClick = (params: MouseEventParams<Time>) => {
      if (disposed) return;
      const eventDate = normalizeEventDate(params.time);
      if (eventDate && modelRef.current.dates.includes(eventDate)) {
        setInspectedDate(eventDate);
        setHoveredDate(eventDate);
        const lockedCursor = cursorReadoutState(params, modelRef.current, container);
        pendingCursorRef.current = lockedCursor;
        setCursorReadout(lockedCursor);
        setKeyboardAnnouncement(
          formatKeyboardInspectionSummary(
            eventDate,
            modelRef.current.readouts[eventDate],
            modelRef.current.diagnostics.find((diagnostic) => diagnostic.date === eventDate)
              ?.reasonCodes ?? [],
            modelRef.current.lifecycle,
          ),
        );
      }
    };
    const modelGapMarkers = gapMarkers(model);
    const scheduleGapMarkerDraw = () => {
      if (disposed || modelGapMarkers.length === 0 || gapMarkerFrame !== null) return;
      gapMarkerFrame = window.requestAnimationFrame(() => {
        gapMarkerFrame = null;
        if (disposed || !runtime.chart || !gapMarkerCanvasRef.current) return;
        try {
          drawGapMarkerCanvas(runtime.chart, gapMarkerCanvasRef.current, modelGapMarkers);
        } catch {
          if (mountedRef.current) {
            setRendererFailure({ code: "CHART_RUNTIME_FAILED", retryable: true });
          }
        }
      });
    };
    const handleVisibleLogicalRangeChange = (range: { from: number; to: number } | null) => {
      if (modelGapMarkers.length > 0) scheduleGapMarkerDraw();
      if (!disposed && range) onRange?.(range);
    };
    const teardownBindings = () => {
      disposed = true;
      if (hoverFrameRef.current !== null) {
        window.cancelAnimationFrame(hoverFrameRef.current);
        hoverFrameRef.current = null;
      }
      if (gapMarkerFrame !== null) {
        window.cancelAnimationFrame(gapMarkerFrame);
        gapMarkerFrame = null;
      }
      resizeObserver?.disconnect();
      if (!runtime.chart) return;
      try {
        runtime.chart.unsubscribeCrosshairMove(scheduleHover);
      } catch {
        // Each vendor subscription is independently best-effort during teardown.
      }
      try {
        runtime.chart.unsubscribeClick(handleClick);
      } catch {
        // Each vendor subscription is independently best-effort during teardown.
      }
      try {
        runtime.chart
          .timeScale()
          .unsubscribeVisibleLogicalRangeChange(handleVisibleLogicalRangeChange);
      } catch {
        // Each vendor subscription is independently best-effort during teardown.
      }
    };

    try {
      const chart = createChart(container, {
        autoSize: true,
        height: 440,
        layout: {
          background: { type: ColorType.Solid, color: "#071321" },
          textColor: "#9eb0c8",
          attributionLogo: false,
        },
        grid: {
          vertLines: { color: "rgba(89, 112, 143, 0.16)" },
          horzLines: { color: "rgba(89, 112, 143, 0.16)" },
        },
        rightPriceScale: {
          borderColor: "rgba(111, 138, 172, 0.36)",
          minimumWidth: 76,
        },
        timeScale: {
          borderColor: "rgba(111, 138, 172, 0.36)",
          rightOffset: 4,
          barSpacing: 8,
          minBarSpacing: 2,
          timeVisible: false,
          secondsVisible: false,
        },
        handleScroll: {
          mouseWheel: true,
          pressedMouseMove: true,
          horzTouchDrag: true,
          vertTouchDrag: false,
        },
        handleScale: {
          mouseWheel: true,
          pinch: true,
          axisPressedMouseMove: { time: true, price: true },
          axisDoubleClickReset: { time: true, price: true },
        },
        kineticScroll: { touch: true, mouse: false },
      });
      runtime.chart = chart;
      const candles = chart.addSeries(CandlestickSeries, {
        upColor: "#26a69a",
        downColor: "#ef5350",
        borderUpColor: "#26a69a",
        borderDownColor: "#ef5350",
        wickUpColor: "#60c9bc",
        wickDownColor: "#ff7471",
        priceLineVisible: true,
        lastValueVisible: true,
        title: `${model.identity?.displaySymbol ?? "BTC"} · ${model.identity?.quote ?? "quote"} · ${model.lifecycle?.channelLabel ?? "Channel"}${model.lifecycle?.publication === "unpublished" ? " · UNPUBLISHED" : ""}`,
      });
      runtime.candles = candles;
      const volume = chart.addSeries(HistogramSeries, {
        priceScaleId: "volume",
        priceFormat: { type: "volume" },
        priceLineVisible: false,
        lastValueVisible: false,
      });
      candles.priceScale().applyOptions({
        scaleMargins: { top: 0.08, bottom: 0.25 },
        mode: scaleModeRef.current === "log" ? PriceScaleMode.Logarithmic : PriceScaleMode.Normal,
      });
      volume.priceScale().applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
      initializationFailureCode = "CHART_DATA_REJECTED";
      candles.setData(model.candles as Array<CandlestickData<Time> | WhitespaceData<Time>>);
      volume.setData(model.volumes);
      runtime.markers = createSeriesMarkers(candles, chartMarkers(model), {
        autoScale: true,
        zOrder: "aboveSeries",
      });
      initializationFailureCode = "CHART_RUNTIME_FAILED";
      chart.subscribeCrosshairMove(scheduleHover);
      chart.subscribeClick(handleClick);
      const timeScale = chart.timeScale();
      timeScale.subscribeVisibleLogicalRangeChange(handleVisibleLogicalRangeChange);
      if (modelGapMarkers.length > 0 && typeof ResizeObserver !== "undefined") {
        resizeObserver = new ResizeObserver(scheduleGapMarkerDraw);
        resizeObserver.observe(container);
      }
      if (view) {
        timeScale.setVisibleLogicalRange(view);
      } else {
        timeScale.fitContent();
      }
      runtimeRef.current = runtime as ChartRuntime;

      if (selectedDate && model.readouts[selectedDate]) {
        chart.setCrosshairPosition(
          Number(model.readouts[selectedDate].close),
          selectedDate,
          candles,
        );
      }
      if (modelGapMarkers.length > 0) {
        scheduleGapMarkerDraw();
      } else if (gapMarkerCanvasRef.current) {
        drawGapMarkerCanvas(chart, gapMarkerCanvasRef.current, []);
      }
      setRendererState("ready");

      return () => {
        teardownBindings();
        runtimeRef.current = null;
        safeCleanup(runtime);
      };
    } catch {
      teardownBindings();
      runtimeRef.current = null;
      safeCleanup(runtime);
      if (mountedRef.current) {
        setRendererState("failed");
        setRendererFailure({ code: initializationFailureCode, retryable: true });
      }
    }
  }, [model, onRange, pinDate, retryVersion, view]);

  useEffect(() => {
    if (selectedDisplayDate) {
      moveProgrammaticCrosshair(selectedDisplayDate);
    }
  }, [moveProgrammaticCrosshair, selectedDisplayDate]);

  useEffect(() => {
    const host = hostRef.current;
    const handleFullscreenChange = () => {
      if (!mountedRef.current) return;
      const active = document.fullscreenElement === host;
      const wasOwned = ownedFullscreenRef.current;
      ownedFullscreenRef.current = active;
      setFullscreenActive(active);
      if (wasOwned && !active) {
        setExpandedFallback(false);
        fullscreenButtonRef.current?.focus();
      }
    };
    document.addEventListener("fullscreenchange", handleFullscreenChange);
    return () => {
      fullscreenRequestGenerationRef.current += 1;
      ownedFullscreenRef.current = false;
      document.removeEventListener("fullscreenchange", handleFullscreenChange);
      if (host && document.fullscreenElement === host && document.exitFullscreen) {
        void document.exitFullscreen().catch(() => undefined);
      }
    };
  }, []);

  function setPriceScale(nextMode: ScaleMode) {
    try {
      runtimeRef.current?.candles.priceScale().applyOptions({
        mode: nextMode === "log" ? PriceScaleMode.Logarithmic : PriceScaleMode.Normal,
      });
      scaleModeRef.current = nextMode;
      setScaleMode(nextMode);
    } catch {
      setRendererFailure({ code: "CHART_RUNTIME_FAILED", retryable: true });
    }
  }

  function runChartAction(action: (runtime: ChartRuntime) => void) {
    const runtime = runtimeRef.current;
    if (!runtime) return;
    try {
      action(runtime);
    } catch {
      setRendererFailure({ code: "CHART_RUNTIME_FAILED", retryable: true });
    }
  }

  function navigateByKeyboard(event: KeyboardEvent<HTMLDivElement>) {
    if (!["ArrowLeft", "ArrowRight", "Home", "End", "Enter", " "].includes(event.key)) {
      return;
    }
    event.preventDefault();
    const current =
      hoveredDate ?? inspectedDate ?? selectedDisplayDate ?? latestDate ?? model.dates[0];
    let next = current;
    if (event.key === "Home") next = model.dates[0];
    if (event.key === "End") next = model.dates[model.dates.length - 1];
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      const currentIndex = Math.max(0, model.dates.indexOf(current));
      const delta = event.key === "ArrowLeft" ? -1 : 1;
      next = model.dates[Math.min(model.dates.length - 1, Math.max(0, currentIndex + delta))];
    }
    if (event.key === "Enter" || event.key === " ") {
      pinDate(current);
      return;
    }
    if (next) {
      setHoveredDate(next);
      moveProgrammaticCrosshair(next);
      setKeyboardAnnouncement(
        formatKeyboardInspectionSummary(
          next,
          model.readouts[next],
          model.diagnostics.find((diagnostic) => diagnostic.date === next)?.reasonCodes ?? [],
          model.lifecycle,
        ),
      );
    }
  }

  async function toggleFullscreen() {
    const host = hostRef.current;
    if (!host) return;
    const generation = fullscreenRequestGenerationRef.current + 1;
    fullscreenRequestGenerationRef.current = generation;
    const isCurrent = () =>
      mountedRef.current && fullscreenRequestGenerationRef.current === generation;
    try {
      if (document.fullscreenElement === host) {
        await document.exitFullscreen();
        return;
      }
      if (host.requestFullscreen) {
        await host.requestFullscreen();
        if (!isCurrent() && document.fullscreenElement === host && document.exitFullscreen) {
          await document.exitFullscreen().catch(() => undefined);
        }
        return;
      }
      if (isCurrent()) setExpandedFallback((current) => !current);
    } catch {
      if (isCurrent()) {
        setExpandedFallback(true);
        setRendererFailure({ code: "CHART_RUNTIME_FAILED", retryable: true });
      }
    }
  }

  const lifecycleClass = model.lifecycle
    ? ` obs-kline--${model.lifecycle.publication} obs-kline--${model.lifecycle.channel.replaceAll("_", "-")}`
    : "";
  const lifecycleTitle = model.lifecycle
    ? `${model.lifecycle.channelLabel}${model.lifecycle.publication === "unpublished" ? " · UNPUBLISHED" : ""}`
    : "Selected channel";

  return (
    <div
      ref={hostRef}
      className={`obs-kline${lifecycleClass}${expandedFallback ? " obs-kline--expanded" : ""}`}
      data-testid="exchange-kline-chart"
      data-renderer-state={rendererState}
      data-channel={model.lifecycle?.channel}
      data-publication={model.lifecycle?.publication}
    >
      <header className="obs-kline__header">
        <div>
          <div className="obs-kline__symbol">
            {model.identity?.displaySymbol}/{model.identity?.quote}
          </div>
          <div className="obs-kline__provenance">
            {model.identity?.provider} · {model.identity?.instrument} · {timeframe} display · UTC
            daily source
          </div>
          <div className="obs-kline__lifecycle" data-testid="exchange-kline-lifecycle">
            {lifecycleTitle}
          </div>
        </div>
        <div className="obs-kline__scope">Local daily Observatory snapshot · not live</div>
      </header>

      <div className="obs-kline__toolbar" role="toolbar" aria-label="Market chart controls">
        <div className="obs-kline__toolbar-group" aria-label="Chart timeframe">
          {(["1D", "1W", "1M", "1Y"] as const).map((option) => (
            <button
              key={option}
              type="button"
              className={timeframe === option ? "is-active" : ""}
              aria-pressed={timeframe === option}
              onClick={() => onTimeframeChange?.(option)}
              data-testid={`exchange-kline-timeframe-${option}`}
            >
              {option}
            </button>
          ))}
        </div>
        <div className="obs-kline__toolbar-group" aria-label="Price scale">
          <button
            type="button"
            className={scaleMode === "linear" ? "is-active" : ""}
            aria-pressed={scaleMode === "linear"}
            onClick={() => setPriceScale("linear")}
          >
            Linear
          </button>
          <button
            type="button"
            className={scaleMode === "log" ? "is-active" : ""}
            aria-pressed={scaleMode === "log"}
            onClick={() => setPriceScale("log")}
          >
            Log
          </button>
        </div>
        <button
          type="button"
          onClick={() => runChartAction((runtime) => runtime.chart.timeScale().fitContent())}
        >
          Fit
        </button>
        <button
          type="button"
          onClick={() =>
            runChartAction(
              (runtime) => recent && runtime.chart.timeScale().setVisibleLogicalRange(recent),
            )
          }
        >
          Newest bar
        </button>
        <button
          ref={fullscreenButtonRef}
          type="button"
          onClick={toggleFullscreen}
          aria-pressed={fullscreenActive || expandedFallback}
        >
          {fullscreenActive || expandedFallback ? "Exit expanded" : "Fullscreen"}
        </button>
        <button
          type="button"
          onClick={() => pinDate(inspectDate)}
          disabled={!inspectDate}
          data-testid="exchange-kline-inspect-date"
        >
          Inspect this date
        </button>
        <label className="obs-chart__date-inspector">
          <span>Inspect date</span>
          <input
            ref={dateInputRef}
            type="date"
            value={selectedDate ?? ""}
            min={sourceDates[0]}
            max={sourceDates[sourceDates.length - 1]}
            aria-label="Inspect a daily market date"
            onChange={(event) => pinDate(event.target.value)}
            data-testid="chart-date-inspector"
          />
        </label>
      </div>

      <KlineReadout
        date={activeDate}
        readout={activeReadout}
        reasons={activeReasons}
        lifecycle={model.lifecycle}
      />
      <div
        className="obs-kline__canvas-shell"
        data-testid="exchange-kline-canvas-shell"
        tabIndex={0}
        role="group"
        aria-label="Interactive BTC daily candlestick chart. Use left and right arrows to inspect dates; press Enter or Space to pin a date."
        onKeyDown={navigateByKeyboard}
      >
        <div ref={canvasRef} className="obs-kline__canvas" />
        <canvas
          ref={gapMarkerCanvasRef}
          className="obs-kline__gap-markers"
          data-testid="exchange-kline-gap-markers"
          data-marker-count={gapMarkers(model).length}
          aria-hidden="true"
        />
        <KlineCursorReadout cursor={cursorReadout} readout={cursorReadoutData} />
      </div>

      <div className="obs-kline__pinned" aria-live="polite" aria-atomic="true">
        {formatPinnedSummary(
          selectedDate,
          selectedDisplayDate ? model.readouts[selectedDisplayDate] : undefined,
          model.lifecycle,
        )}
      </div>
      <div
        className="obs-kline__pinned obs-kline__keyboard-announcement"
        aria-live="polite"
        aria-atomic="true"
        data-testid="exchange-kline-keyboard-announcement"
      >
        {keyboardAnnouncement}
      </div>

      {rendererFailure ? (
        <div className="obs-kline__renderer-warning" role="alert">
          <strong>Daily chart interaction degraded.</strong>
          <span>Reason code: {rendererFailure.code}</span>
          <div>
            {rendererFailure.retryable ? (
              <button type="button" onClick={() => setRetryVersion((current) => current + 1)}>
                Retry chart
              </button>
            ) : null}
            {onRequestCompare ? (
              <button type="button" onClick={onRequestCompare}>
                Open Compare
              </button>
            ) : null}
          </div>
        </div>
      ) : null}

      <KlineDiagnostics model={model} />
      <footer className="obs-kline__footer">
        <span>Volume is shown as supplied; source unit unavailable.</span>
        <a href="https://www.tradingview.com/" target="_blank" rel="noreferrer">
          Charting library: TradingView Lightweight Charts™
        </a>
      </footer>
    </div>
  );
}

export default ExchangeKlineChart;
