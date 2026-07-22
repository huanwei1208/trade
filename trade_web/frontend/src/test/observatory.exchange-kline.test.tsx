import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ExchangeKlineChart } from "../components/observatory/ExchangeKlineChart";
import { ExchangeKlinePanel } from "../components/observatory/ExchangeKlinePanel";
import type { ObsChannel } from "../lib/api";
import { buildObservatoryKlineModel, type ObservatoryKlineModel } from "../lib/observatoryChart";
import { CONTEXT_FIXTURE, OBSERVED_SERIES_FIXTURE } from "./fixtures";

const chartMock = vi.hoisted(() => {
  const candlePriceScale = { applyOptions: vi.fn() };
  const volumePriceScale = { applyOptions: vi.fn() };
  const candleSeries = {
    setData: vi.fn(),
    priceScale: vi.fn(() => candlePriceScale),
  };
  const volumeSeries = {
    setData: vi.fn(),
    priceScale: vi.fn(() => volumePriceScale),
  };
  const timeScale = {
    fitContent: vi.fn(),
    scrollToRealTime: vi.fn(),
    timeToCoordinate: vi.fn(() => 120),
    subscribeVisibleLogicalRangeChange: vi.fn(),
    unsubscribeVisibleLogicalRangeChange: vi.fn(),
  };
  const markerApi = { detach: vi.fn() };
  const chart = {
    addSeries: vi.fn(),
    subscribeCrosshairMove: vi.fn(),
    unsubscribeCrosshairMove: vi.fn(),
    subscribeClick: vi.fn(),
    unsubscribeClick: vi.fn(),
    timeScale: vi.fn(() => timeScale),
    setCrosshairPosition: vi.fn(),
    clearCrosshairPosition: vi.fn(),
    remove: vi.fn(),
  };
  const createChart = vi.fn();
  const createSeriesMarkers = vi.fn(() => markerApi);
  return {
    candlePriceScale,
    volumePriceScale,
    candleSeries,
    volumeSeries,
    timeScale,
    markerApi,
    chart,
    createChart,
    createSeriesMarkers,
  };
});

vi.mock("lightweight-charts", () => ({
  CandlestickSeries: "CandlestickSeries",
  ColorType: { Solid: "solid" },
  HistogramSeries: "HistogramSeries",
  PriceScaleMode: { Normal: 0, Logarithmic: 1 },
  createChart: chartMock.createChart,
  createSeriesMarkers: chartMock.createSeriesMarkers,
}));

function resetChartMock() {
  for (const candidate of Object.values(chartMock)) {
    if (candidate && typeof candidate === "object") {
      for (const value of Object.values(candidate)) {
        if (typeof value === "function" && "mockClear" in value) value.mockClear();
      }
    }
    if (typeof candidate === "function" && "mockClear" in candidate) candidate.mockClear();
  }
  chartMock.chart.addSeries.mockImplementation((seriesType) =>
    seriesType === "CandlestickSeries" ? chartMock.candleSeries : chartMock.volumeSeries,
  );
  chartMock.createChart.mockReturnValue(chartMock.chart);
  chartMock.createSeriesMarkers.mockReturnValue(chartMock.markerApi);
}

function readyModel(channel: ObsChannel = "observed") {
  const activeContext = { ...CONTEXT_FIXTURE, resolved_channel: channel, excluded_dates: [] };
  const normalizedRows = (OBSERVED_SERIES_FIXTURE.rows ?? []).map((row) => ({
    ...row,
    quality_flags: [],
    revision_state: "unchanged" as const,
  }));
  const rowTemplate = normalizedRows.at(0);
  const contiguousRows =
    rowTemplate && !normalizedRows.some((row) => row.date === "2026-07-15")
      ? [...normalizedRows, { ...rowTemplate, date: "2026-07-15" }]
      : normalizedRows;
  return buildObservatoryKlineModel(
    {
      ...OBSERVED_SERIES_FIXTURE,
      view: channel,
      context: activeContext,
      rows: contiguousRows,
    },
    activeContext,
  );
}

beforeEach(() => {
  resetChartMock();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("ExchangeKlineChart", () => {
  it("creates one chart with candle and volume series using exchange-style interactions", () => {
    const model = readyModel();
    render(<ExchangeKlineChart model={model} />);

    expect(chartMock.createChart).toHaveBeenCalledTimes(1);
    expect(chartMock.createChart.mock.calls[0]?.[1]).toMatchObject({
      autoSize: true,
      layout: { attributionLogo: false },
      handleScroll: { horzTouchDrag: true, vertTouchDrag: false },
      handleScale: { mouseWheel: true, pinch: true },
    });
    expect(chartMock.chart.addSeries).toHaveBeenNthCalledWith(
      1,
      "CandlestickSeries",
      expect.objectContaining({ upColor: "#26a69a", downColor: "#ef5350" }),
    );
    expect(chartMock.chart.addSeries).toHaveBeenNthCalledWith(
      2,
      "HistogramSeries",
      expect.objectContaining({ priceScaleId: "volume" }),
    );
    expect(chartMock.candleSeries.setData).toHaveBeenCalledWith(model.candles);
    expect(chartMock.volumeSeries.setData).toHaveBeenCalledWith(model.volumes);
    expect(chartMock.timeScale.fitContent).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("exchange-kline-chart")).toHaveAttribute(
      "data-renderer-state",
      "ready",
    );
    expect(screen.getByText("Local daily Observatory snapshot · not live")).toBeTruthy();
    expect(screen.getByRole("link", { name: /TradingView Lightweight Charts/ })).toHaveAttribute(
      "href",
      "https://www.tradingview.com/",
    );
    expect(screen.getByText("Volume is shown as supplied; source unit unavailable.")).toBeTruthy();
  });

  it.each([
    ["formal", "Published baseline", "published"],
    ["evaluated_candidate", "Evaluated candidate · UNPUBLISHED", "unpublished"],
    ["observed", "Latest observed · UNPUBLISHED", "unpublished"],
  ] as const)("renders persistent %s publication framing", (channel, label, publication) => {
    render(<ExchangeKlineChart model={readyModel(channel)} selectedDate="2026-07-17" />);

    const chart = screen.getByTestId("exchange-kline-chart");
    expect(chart).toHaveAttribute("data-channel", channel);
    expect(chart).toHaveAttribute("data-publication", publication);
    expect(screen.getAllByText(label).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(new RegExp(`${publication}\\. 2026-07-17 pinned`, "i"))).toBeTruthy();
  });

  it("routes missing whitespace dates to one repository-owned Canvas marker", () => {
    const activeContext = {
      ...CONTEXT_FIXTURE,
      excluded_dates: [
        {
          date: "2026-07-15",
          exclusion_reason: "quarantined",
          quality_flags: ["basis_breach"],
          evidence_refs: ["run_candidate"],
          marker_position: "below",
        },
      ],
    };
    const model = buildObservatoryKlineModel(OBSERVED_SERIES_FIXTURE, activeContext);

    render(<ExchangeKlineChart model={model} />);

    expect(screen.getByTestId("exchange-kline-gap-markers")).toHaveAttribute(
      "data-marker-count",
      "1",
    );
  });

  it("clears repository-owned marker pixels when a replacement model has no gaps", async () => {
    const clearRect = vi.fn();
    const drawingContext = {
      setTransform: vi.fn(),
      clearRect,
      beginPath: vi.fn(),
      arc: vi.fn(),
      fill: vi.fn(),
      fillRect: vi.fn(),
      fillText: vi.fn(),
      font: "",
      textAlign: "center",
      textBaseline: "middle",
      fillStyle: "",
    } as unknown as CanvasRenderingContext2D;
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(drawingContext);
    vi.spyOn(HTMLCanvasElement.prototype, "getBoundingClientRect").mockReturnValue({
      width: 800,
      height: 400,
      top: 0,
      left: 0,
      right: 800,
      bottom: 400,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    });
    const gapModel = buildObservatoryKlineModel(OBSERVED_SERIES_FIXTURE, CONTEXT_FIXTURE);
    const page = render(<ExchangeKlineChart model={gapModel} />);
    await waitFor(() => expect(clearRect).toHaveBeenCalled());
    const drawCount = clearRect.mock.calls.length;

    page.rerender(<ExchangeKlineChart model={readyModel()} />);

    await waitFor(() => expect(clearRect.mock.calls.length).toBeGreaterThan(drawCount));
    expect(screen.getByTestId("exchange-kline-gap-markers")).toHaveAttribute(
      "data-marker-count",
      "0",
    );
  });

  it("coalesces hover updates and keeps ordinary clicks local until explicit inspection", () => {
    const frames: FrameRequestCallback[] = [];
    vi.stubGlobal(
      "requestAnimationFrame",
      vi.fn((callback: FrameRequestCallback) => {
        frames.push(callback);
        return frames.length;
      }),
    );
    vi.stubGlobal("cancelAnimationFrame", vi.fn());
    const onSelectDate = vi.fn();
    render(<ExchangeKlineChart model={readyModel()} onSelectDate={onSelectDate} />);
    const hover = chartMock.chart.subscribeCrosshairMove.mock.calls[0]?.[0];
    const click = chartMock.chart.subscribeClick.mock.calls[0]?.[0];

    act(() => {
      for (let index = 0; index < 100; index += 1) {
        hover({ time: index % 2 === 0 ? "2026-07-16" : "2026-07-17" });
      }
    });
    expect(frames).toHaveLength(1);
    expect(onSelectDate).not.toHaveBeenCalled();
    act(() => frames[0]?.(0));
    expect(screen.getByTestId("exchange-kline-readout")).toHaveTextContent("2026-07-17");
    expect(screen.getByTestId("exchange-kline-keyboard-announcement")).toBeEmptyDOMElement();
    expect(chartMock.createChart).toHaveBeenCalledOnce();
    expect(chartMock.chart.addSeries).toHaveBeenCalledTimes(2);

    act(() => click({ time: "2026-07-17" }));
    expect(onSelectDate).not.toHaveBeenCalled();
    expect(screen.getByTestId("exchange-kline-readout")).toHaveTextContent("2026-07-17");
    fireEvent.click(screen.getByTestId("exchange-kline-inspect-date"));
    expect(onSelectDate).toHaveBeenCalledOnce();
    expect(onSelectDate).toHaveBeenCalledWith("2026-07-17");
  });

  it("supports keyboard date navigation and explicit Enter pinning", () => {
    const onSelectDate = vi.fn();
    render(<ExchangeKlineChart model={readyModel()} onSelectDate={onSelectDate} />);
    const chartGroup = screen.getByRole("group", { name: /Interactive BTC daily candlestick/ });

    fireEvent.keyDown(chartGroup, { key: "ArrowLeft" });
    expect(screen.getByTestId("exchange-kline-readout")).toHaveTextContent("2026-07-17");
    expect(screen.getByTestId("exchange-kline-keyboard-announcement")).toHaveTextContent(
      /Latest observed, unpublished\. 2026-07-17 inspected\. Open .*, high .*, low .*, close .*, volume .*\./,
    );
    expect(onSelectDate).not.toHaveBeenCalled();
    fireEvent.keyDown(chartGroup, { key: "Enter" });
    expect(onSelectDate).toHaveBeenCalledWith("2026-07-17");
    expect(chartMock.chart.setCrosshairPosition).toHaveBeenCalled();
  });

  it("announces a declared exclusion during keyboard inspection without pinning it", () => {
    const activeContext = {
      ...CONTEXT_FIXTURE,
      excluded_dates: [
        {
          date: "2026-07-15",
          exclusion_reason: "quarantined",
          quality_flags: ["basis_breach"],
          evidence_refs: ["run_candidate"],
          marker_position: "below" as const,
        },
      ],
    };
    const onSelectDate = vi.fn();
    render(
      <ExchangeKlineChart
        model={buildObservatoryKlineModel(OBSERVED_SERIES_FIXTURE, activeContext)}
        onSelectDate={onSelectDate}
      />,
    );
    const chartGroup = screen.getByRole("group", {
      name: /Interactive BTC daily candlestick/,
    });

    fireEvent.keyDown(chartGroup, { key: "Home" });
    fireEvent.keyDown(chartGroup, { key: "ArrowRight" });

    expect(screen.getByTestId("exchange-kline-keyboard-announcement")).toHaveTextContent(
      /Latest observed, unpublished\. 2026-07-15 inspected\. No plotted candle\. Reasons: .*QUARANTINED/,
    );
    expect(onSelectDate).not.toHaveBeenCalled();
    expect(chartMock.chart.clearCrosshairPosition).toHaveBeenCalled();
  });

  it("wires scale, fit, newest, date input, and expanded fallback controls", () => {
    const onSelectDate = vi.fn();
    render(<ExchangeKlineChart model={readyModel()} onSelectDate={onSelectDate} />);

    fireEvent.click(screen.getByRole("button", { name: "Log" }));
    expect(chartMock.candlePriceScale.applyOptions).toHaveBeenCalledWith({ mode: 1 });
    fireEvent.click(screen.getByRole("button", { name: "Fit" }));
    fireEvent.click(screen.getByRole("button", { name: "Newest bar" }));
    expect(chartMock.timeScale.fitContent).toHaveBeenCalledTimes(2);
    expect(chartMock.timeScale.scrollToRealTime).toHaveBeenCalledOnce();

    fireEvent.change(screen.getByLabelText("Inspect a daily market date"), {
      target: { value: "2026-07-16" },
    });
    expect(onSelectDate).toHaveBeenCalledWith("2026-07-16");

    fireEvent.click(screen.getByRole("button", { name: "Fullscreen" }));
    expect(screen.getByTestId("exchange-kline-chart")).toHaveClass("obs-kline--expanded");
  });

  it("reapplies retained log mode when the chart model is recreated", () => {
    const page = render(<ExchangeKlineChart model={readyModel()} />);

    fireEvent.click(screen.getByRole("button", { name: "Log" }));
    page.rerender(<ExchangeKlineChart model={readyModel()} />);

    expect(chartMock.createChart).toHaveBeenCalledTimes(2);
    expect(chartMock.candlePriceScale.applyOptions).toHaveBeenLastCalledWith(
      expect.objectContaining({ mode: 1 }),
    );
    expect(screen.getByRole("button", { name: "Log" })).toHaveAttribute("aria-pressed", "true");
  });

  it("contains renderer creation failures and recovers through an explicit retry", async () => {
    chartMock.createChart.mockReset();
    chartMock.createChart.mockImplementationOnce(() => {
      throw new Error("raw canvas failure must not render");
    });
    chartMock.createChart.mockReturnValueOnce(chartMock.chart);
    render(<ExchangeKlineChart model={readyModel()} />);

    expect(await screen.findByText("Reason code: CHART_CREATE_FAILED")).toBeTruthy();
    expect(screen.getByTestId("exchange-kline-chart")).toHaveAttribute(
      "data-renderer-state",
      "failed",
    );
    expect(screen.queryByText(/raw canvas failure/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Retry chart" }));
    await waitFor(() => expect(chartMock.createChart).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByText("Reason code: CHART_CREATE_FAILED")).toBeNull());
  });

  it("classifies candle data rejection separately from chart creation failures", async () => {
    chartMock.candleSeries.setData.mockImplementationOnce(() => {
      throw new Error("raw rejected row detail must not render");
    });

    render(<ExchangeKlineChart model={readyModel()} />);

    expect(await screen.findByText("Reason code: CHART_DATA_REJECTED")).toBeTruthy();
    expect(screen.getByTestId("exchange-kline-chart")).toHaveAttribute(
      "data-renderer-state",
      "failed",
    );
    expect(screen.queryByText(/raw rejected row detail/)).toBeNull();
    expect(chartMock.chart.remove).toHaveBeenCalledOnce();
  });

  it("fully tears down overlay bindings after partial chart initialization fails", async () => {
    const frames: FrameRequestCallback[] = [];
    const cancelAnimationFrame = vi.fn();
    vi.stubGlobal(
      "requestAnimationFrame",
      vi.fn((callback: FrameRequestCallback) => {
        frames.push(callback);
        return frames.length;
      }),
    );
    vi.stubGlobal("cancelAnimationFrame", cancelAnimationFrame);
    const observe = vi.fn();
    const disconnect = vi.fn();
    class ResizeObserverMock {
      observe = observe;
      disconnect = disconnect;
      unobserve = vi.fn();
    }
    vi.stubGlobal("ResizeObserver", ResizeObserverMock);
    chartMock.timeScale.subscribeVisibleLogicalRangeChange.mockImplementationOnce((callback) => {
      callback();
    });
    chartMock.timeScale.fitContent.mockImplementationOnce(() => {
      throw new Error("fit failed after bindings");
    });

    render(
      <ExchangeKlineChart
        model={buildObservatoryKlineModel(OBSERVED_SERIES_FIXTURE, CONTEXT_FIXTURE)}
      />,
    );

    expect(await screen.findByText("Reason code: CHART_RUNTIME_FAILED")).toBeTruthy();
    expect(observe).toHaveBeenCalledOnce();
    expect(disconnect).toHaveBeenCalledOnce();
    expect(chartMock.chart.unsubscribeCrosshairMove).toHaveBeenCalledOnce();
    expect(chartMock.chart.unsubscribeClick).toHaveBeenCalledOnce();
    expect(chartMock.timeScale.unsubscribeVisibleLogicalRangeChange).toHaveBeenCalledOnce();
    expect(cancelAnimationFrame).toHaveBeenCalledOnce();
    expect(chartMock.chart.remove).toHaveBeenCalledOnce();
  });

  it("contains callback failures without exposing the thrown error", () => {
    const onSelectDate = vi.fn(() => {
      throw new Error("sensitive callback detail");
    });
    render(
      <ExchangeKlineChart
        model={readyModel()}
        onSelectDate={onSelectDate}
        onRequestCompare={vi.fn()}
      />,
    );
    const click = chartMock.chart.subscribeClick.mock.calls[0]?.[0];

    act(() => click({ time: "2026-07-17" }));
    expect(onSelectDate).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId("exchange-kline-inspect-date"));
    expect(screen.getByText("Reason code: CHART_RUNTIME_FAILED")).toBeTruthy();
    expect(screen.queryByText(/sensitive callback detail/)).toBeNull();
    expect(screen.getByRole("button", { name: "Retry chart" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Open Compare" })).toBeTruthy();
  });

  it("keeps partial diagnostics bounded and non-live", () => {
    const model = buildObservatoryKlineModel(
      {
        ...OBSERVED_SERIES_FIXTURE,
        rows: [
          { ...OBSERVED_SERIES_FIXTURE.rows?.[0], date: "2026-01-01", quality_flags: [] },
          { ...OBSERVED_SERIES_FIXTURE.rows?.[0], date: "2026-04-20", quality_flags: [] },
        ],
      },
      { ...CONTEXT_FIXTURE, excluded_dates: [] },
    );
    render(<ExchangeKlineChart model={model} />);
    const diagnostics = screen.getByTestId("exchange-kline-diagnostics");

    expect(within(diagnostics).getAllByText(/affected dates/)).toHaveLength(2);
    expect(within(diagnostics).getByLabelText("Affected date preview").children).toHaveLength(8);
    expect(within(diagnostics).getAllByRole("listitem")).toHaveLength(50);
    expect(diagnostics).not.toHaveAttribute("aria-live");
  });

  it("renders explicit per-diagnostic omitted reason and evidence counts", () => {
    const model = buildObservatoryKlineModel(OBSERVED_SERIES_FIXTURE, {
      ...CONTEXT_FIXTURE,
      excluded_dates: [
        {
          date: "2026-07-15",
          exclusion_reason: "quarantined",
          quality_flags: Array.from({ length: 20 }, (_, index) => `flag_${index}`),
          evidence_refs: Array.from({ length: 12 }, (_, index) => `evidence_${index}`),
          marker_position: "below",
        },
      ],
    });

    render(<ExchangeKlineChart model={model} />);

    const preview = within(screen.getByLabelText("Affected date preview"));
    expect(preview.getByText(/6 additional reason codes omitted/)).toBeTruthy();
    expect(preview.getByText(/4 additional evidence references omitted/)).toBeTruthy();
  });

  it("unsubscribes events, ignores late callbacks, and removes the chart exactly once", () => {
    const onSelectDate = vi.fn();
    const page = render(<ExchangeKlineChart model={readyModel()} onSelectDate={onSelectDate} />);
    const hover = chartMock.chart.subscribeCrosshairMove.mock.calls[0]?.[0];
    const click = chartMock.chart.subscribeClick.mock.calls[0]?.[0];

    page.unmount();
    expect(chartMock.chart.unsubscribeCrosshairMove).toHaveBeenCalledWith(hover);
    expect(chartMock.chart.unsubscribeClick).toHaveBeenCalledWith(click);
    expect(chartMock.markerApi.detach).toHaveBeenCalledOnce();
    expect(chartMock.chart.remove).toHaveBeenCalledOnce();
    act(() => click({ time: "2026-07-17" }));
    act(() => hover({ time: "2026-07-17" }));
    expect(onSelectDate).not.toHaveBeenCalled();
  });

  it("ignores a deferred fullscreen rejection after unmount", async () => {
    const originalRequest = Object.getOwnPropertyDescriptor(
      HTMLElement.prototype,
      "requestFullscreen",
    );
    let rejectRequest: ((reason?: unknown) => void) | undefined;
    Object.defineProperty(HTMLElement.prototype, "requestFullscreen", {
      configurable: true,
      value: vi.fn(
        () =>
          new Promise<void>((_resolve, reject) => {
            rejectRequest = reject;
          }),
      ),
    });
    try {
      const page = render(<ExchangeKlineChart model={readyModel()} />);
      fireEvent.click(screen.getByRole("button", { name: "Fullscreen" }));
      page.unmount();
      await act(async () => {
        rejectRequest?.(new Error("late fullscreen failure"));
        await Promise.resolve();
      });
      expect(screen.queryByText("Reason code: CHART_RUNTIME_FAILED")).toBeNull();
    } finally {
      if (originalRequest) {
        Object.defineProperty(HTMLElement.prototype, "requestFullscreen", originalRequest);
      } else {
        Reflect.deleteProperty(HTMLElement.prototype, "requestFullscreen");
      }
    }
  });

  it("classifies a current fullscreen rejection as a runtime failure", async () => {
    const originalRequest = Object.getOwnPropertyDescriptor(
      HTMLElement.prototype,
      "requestFullscreen",
    );
    Object.defineProperty(HTMLElement.prototype, "requestFullscreen", {
      configurable: true,
      value: vi.fn().mockRejectedValue(new Error("private fullscreen detail")),
    });
    try {
      render(<ExchangeKlineChart model={readyModel()} onRequestCompare={vi.fn()} />);
      fireEvent.click(screen.getByRole("button", { name: "Fullscreen" }));

      expect(await screen.findByText("Reason code: CHART_RUNTIME_FAILED")).toBeTruthy();
      expect(screen.queryByText(/private fullscreen detail/)).toBeNull();
      expect(screen.getByTestId("exchange-kline-chart")).toHaveClass("obs-kline--expanded");
      expect(screen.getByRole("button", { name: "Retry chart" })).toBeTruthy();
      expect(screen.getByRole("button", { name: "Open Compare" })).toBeTruthy();
    } finally {
      if (originalRequest) {
        Object.defineProperty(HTMLElement.prototype, "requestFullscreen", originalRequest);
      } else {
        Reflect.deleteProperty(HTMLElement.prototype, "requestFullscreen");
      }
    }
  });

  it("exits fullscreen when a deferred request succeeds after unmount", async () => {
    const originalRequest = Object.getOwnPropertyDescriptor(
      HTMLElement.prototype,
      "requestFullscreen",
    );
    const originalElement = Object.getOwnPropertyDescriptor(document, "fullscreenElement");
    const originalExit = Object.getOwnPropertyDescriptor(document, "exitFullscreen");
    let fullscreenElement: Element | null = null;
    let resolveRequest: (() => void) | undefined;
    const exitFullscreen = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(HTMLElement.prototype, "requestFullscreen", {
      configurable: true,
      value: vi.fn(
        () =>
          new Promise<void>((resolve) => {
            resolveRequest = resolve;
          }),
      ),
    });
    Object.defineProperty(document, "fullscreenElement", {
      configurable: true,
      get: () => fullscreenElement,
    });
    Object.defineProperty(document, "exitFullscreen", {
      configurable: true,
      value: exitFullscreen,
    });
    try {
      const page = render(<ExchangeKlineChart model={readyModel()} />);
      const host = screen.getByTestId("exchange-kline-chart");
      fireEvent.click(screen.getByRole("button", { name: "Fullscreen" }));
      page.unmount();
      fullscreenElement = host;
      await act(async () => {
        resolveRequest?.();
        await Promise.resolve();
      });
      expect(exitFullscreen).toHaveBeenCalledOnce();
    } finally {
      if (originalRequest) {
        Object.defineProperty(HTMLElement.prototype, "requestFullscreen", originalRequest);
      } else {
        Reflect.deleteProperty(HTMLElement.prototype, "requestFullscreen");
      }
      if (originalElement) Object.defineProperty(document, "fullscreenElement", originalElement);
      else Reflect.deleteProperty(document, "fullscreenElement");
      if (originalExit) Object.defineProperty(document, "exitFullscreen", originalExit);
      else Reflect.deleteProperty(document, "exitFullscreen");
    }
  });

  it("restores focus to the Fullscreen trigger only after its owned fullscreen exits", () => {
    const originalElement = Object.getOwnPropertyDescriptor(document, "fullscreenElement");
    let fullscreenElement: Element | null = null;
    const page = render(<ExchangeKlineChart model={readyModel()} />);
    const host = screen.getByTestId("exchange-kline-chart");
    const fullscreenButton = screen.getByRole("button", { name: "Fullscreen" });
    Object.defineProperty(document, "fullscreenElement", {
      configurable: true,
      get: () => fullscreenElement,
    });
    try {
      act(() => {
        fullscreenElement = host;
        document.dispatchEvent(new Event("fullscreenchange"));
        fullscreenElement = null;
        document.dispatchEvent(new Event("fullscreenchange"));
      });
      expect(fullscreenButton).toHaveFocus();
    } finally {
      page.unmount();
      if (originalElement) Object.defineProperty(document, "fullscreenElement", originalElement);
      else Reflect.deleteProperty(document, "fullscreenElement");
    }
  });

  it("exits only the fullscreen element owned by the unmounting chart", () => {
    const originalElement = Object.getOwnPropertyDescriptor(document, "fullscreenElement");
    const originalExit = Object.getOwnPropertyDescriptor(document, "exitFullscreen");
    const exitFullscreen = vi.fn().mockResolvedValue(undefined);
    const page = render(<ExchangeKlineChart model={readyModel()} />);
    const host = screen.getByTestId("exchange-kline-chart");
    Object.defineProperty(document, "fullscreenElement", {
      configurable: true,
      get: () => host,
    });
    Object.defineProperty(document, "exitFullscreen", {
      configurable: true,
      value: exitFullscreen,
    });
    try {
      page.unmount();
      expect(exitFullscreen).toHaveBeenCalledOnce();
    } finally {
      if (originalElement) Object.defineProperty(document, "fullscreenElement", originalElement);
      else Reflect.deleteProperty(document, "fullscreenElement");
      if (originalExit) Object.defineProperty(document, "exitFullscreen", originalExit);
      else Reflect.deleteProperty(document, "exitFullscreen");
    }
  });
});

describe("ExchangeKlinePanel", () => {
  it("fails safely on lazy-module load and retries without switching modes", async () => {
    const loader = vi
      .fn()
      .mockRejectedValueOnce(new Error("private import detail"))
      .mockResolvedValueOnce({ ExchangeKlineChart });
    render(
      <ExchangeKlinePanel
        series={{
          ...OBSERVED_SERIES_FIXTURE,
          rows: OBSERVED_SERIES_FIXTURE.rows?.map((row) => ({
            ...row,
            quality_flags: [],
            revision_state: "unchanged",
          })),
        }}
        context={{ ...CONTEXT_FIXTURE, excluded_dates: [] }}
        loadChart={loader}
      />,
    );

    expect(await screen.findByText("Reason code: CHART_MODULE_LOAD_FAILED")).toBeTruthy();
    expect(screen.queryByText(/private import detail/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Retry chart" }));
    expect(await screen.findByTestId("exchange-kline-chart")).toBeTruthy();
    expect(loader).toHaveBeenCalledTimes(2);
  });

  it("renders invalid selected data as unavailable with Retry and Compare recovery", () => {
    const onRetrySeries = vi.fn();
    const onRequestCompare = vi.fn();
    render(
      <ExchangeKlinePanel
        series={{
          ...OBSERVED_SERIES_FIXTURE,
          rows: [{ ...OBSERVED_SERIES_FIXTURE.rows?.[0], provider: "binance" }],
        }}
        context={{ ...CONTEXT_FIXTURE, excluded_dates: [] }}
        onRetrySeries={onRetrySeries}
        onRequestCompare={onRequestCompare}
      />,
    );

    expect(screen.getByTestId("exchange-kline-invalid")).toHaveTextContent("PROVENANCE_MISMATCH");
    fireEvent.click(screen.getByRole("button", { name: "Retry series" }));
    fireEvent.click(screen.getByRole("button", { name: "Open Compare" }));
    expect(onRetrySeries).toHaveBeenCalledOnce();
    expect(onRequestCompare).toHaveBeenCalledOnce();
  });

  it("reports fatal reason codes omitted by both display and adapter bounds", () => {
    const activeContext = {
      ...CONTEXT_FIXTURE,
      excluded_dates: [
        {
          date: "2026-07-15",
          exclusion_reason: "quarantined",
          quality_flags: Array.from({ length: 20 }, (_, index) => `flag_${index}`),
          evidence_refs: [],
          marker_position: "below" as const,
        },
      ],
    };
    const invalidSeries = {
      ...OBSERVED_SERIES_FIXTURE,
      rows: [{ ...OBSERVED_SERIES_FIXTURE.rows?.[0], provider: "binance" }],
    };
    const invalidModel = buildObservatoryKlineModel(invalidSeries, activeContext);
    const expectedOmittedCount =
      Math.max(0, invalidModel.fatalReasonCodes.length - 8) +
      invalidModel.omittedFatalReasonCodeCount;

    render(<ExchangeKlinePanel series={invalidSeries} context={activeContext} />);

    expect(expectedOmittedCount).toBeGreaterThan(0);
    expect(
      screen.getByText(`${expectedOmittedCount} additional reason codes omitted.`),
    ).toBeTruthy();
  });

  it("passes the inclusive request window into chart adaptation", async () => {
    const capturedModels: ObservatoryKlineModel[] = [];
    function CapturedChart({ model }: { model: ObservatoryKlineModel }) {
      capturedModels.push(model);
      return <div data-testid="captured-window-dates">{model.dates.join("|")}</div>;
    }
    const loader = vi.fn().mockResolvedValue({ ExchangeKlineChart: CapturedChart });
    const activeContext = {
      ...CONTEXT_FIXTURE,
      excluded_dates: [
        {
          date: "2020-01-01",
          exclusion_reason: "historical_gap",
          quality_flags: [],
          evidence_refs: [],
          marker_position: "above" as const,
        },
      ],
    };
    const boundedSeries = {
      ...OBSERVED_SERIES_FIXTURE,
      rows: OBSERVED_SERIES_FIXTURE.rows?.filter(
        (row) =>
          typeof row.date === "string" && row.date >= "2026-07-16" && row.date <= "2026-07-18",
      ),
    };

    const page = render(
      <ExchangeKlinePanel
        series={boundedSeries}
        context={activeContext}
        window={{ from: "2026-07-16", to: "2026-07-18" }}
        loadChart={loader}
      />,
    );

    expect(await screen.findByTestId("captured-window-dates")).toHaveTextContent(
      "2026-07-16|2026-07-17|2026-07-18",
    );
    const firstModel = capturedModels.at(-1);

    page.rerender(
      <ExchangeKlinePanel
        series={boundedSeries}
        context={activeContext}
        window={{ from: "2026-07-16", to: "2026-07-18" }}
        loadChart={loader}
        onRequestCompare={() => undefined}
      />,
    );

    expect(capturedModels.at(-1)).toBe(firstModel);
    expect(loader).toHaveBeenCalledOnce();
  });

  it("contains a lazy chart render failure and preserves Retry and Compare", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const onRequestCompare = vi.fn();
    let shouldThrow = true;
    function ThrowingChart() {
      if (shouldThrow) throw new Error("private render detail");
      return <div data-testid="recovered-kline">Recovered chart</div>;
    }
    const loader = vi.fn().mockResolvedValue({ ExchangeKlineChart: ThrowingChart });
    render(
      <ExchangeKlinePanel
        series={OBSERVED_SERIES_FIXTURE}
        context={CONTEXT_FIXTURE}
        loadChart={loader}
        onRequestCompare={onRequestCompare}
      />,
    );

    expect(await screen.findByText("Reason code: CHART_RUNTIME_FAILED")).toBeTruthy();
    expect(screen.queryByText(/private render detail/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Open Compare" }));
    expect(onRequestCompare).toHaveBeenCalledOnce();
    shouldThrow = false;
    fireEvent.click(screen.getByRole("button", { name: "Retry chart" }));
    expect(await screen.findByTestId("recovered-kline")).toBeTruthy();
    consoleError.mockRestore();
  });

  it("rejects a malformed lazy module without exposing a runtime exception", async () => {
    const loader = vi.fn().mockResolvedValue({});
    render(
      <ExchangeKlinePanel
        series={OBSERVED_SERIES_FIXTURE}
        context={CONTEXT_FIXTURE}
        loadChart={loader as never}
      />,
    );

    expect(await screen.findByText("Reason code: CHART_MODULE_LOAD_FAILED")).toBeTruthy();
  });
});
