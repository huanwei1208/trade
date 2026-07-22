import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CompositeChart } from "../components/observatory/CompositeChart";
import { DateEvidenceLens } from "../components/observatory/DateEvidenceLens";
import { WhyNotFormal } from "../components/observatory/OverviewPanels";
import { ResearchLens } from "../components/observatory/ResearchLens";
import { RunsLineageLens } from "../components/observatory/RunsLineageLens";
import { SnapshotContextBar } from "../components/observatory/SnapshotContextBar";
import { TrustLens } from "../components/observatory/TrustLens";
import { OBSERVATORY_CHART_POINT_BUDGET } from "../lib/observatory";
import {
  COMPOSITE_FIXTURE,
  CONTEXT_FIXTURE,
  DATE_EVIDENCE_FIXTURE,
  HYPOTHESES_FIXTURE,
  RESEARCH_RUN_FIXTURE,
  RUNS_FIXTURE,
} from "./fixtures";

afterEach(() => cleanup());

describe("SnapshotContextBar (Truth Bar)", () => {
  it("shows all three watermarks, knowledge_as_of and rendered_at (not just an updated time)", () => {
    render(<SnapshotContextBar context={CONTEXT_FIXTURE} />);
    expect(screen.getByTestId("wm-observed")).toHaveTextContent("2026-07-18");
    expect(screen.getByTestId("wm-candidate")).toHaveTextContent("2026-07-18");
    expect(screen.getByTestId("wm-formal")).toHaveTextContent("2026-07-11");
    expect(screen.getByTestId("knowledge-as-of")).toBeTruthy();
    // Contract identity is present (instrument/quote/interval/timezone).
    const bar = screen.getByTestId("obs-truthbar");
    expect(bar.textContent).toContain("BTC-USDT");
    expect(bar.textContent).toContain("USDT");
    expect(bar.textContent).toContain("UTC");
  });

  it("renders purpose-fitness chips with allowed/blocked state", () => {
    render(<SnapshotContextBar context={CONTEXT_FIXTURE} />);
    const chips = screen.getByTestId("obs-purpose-fitness");
    expect(chips.textContent).toContain("Manual Observation");
    expect(chips.textContent).toContain("Published Baseline Use");
    // Blocked purpose is shown as not allowed.
    expect(chips.textContent?.toLowerCase()).toContain("blocked");
  });

  it("does not render current cross-channel watermarks as historical as-of truth", () => {
    render(
      <SnapshotContextBar
        context={{
          ...CONTEXT_FIXTURE,
          resolved_channel: "formal",
          market_watermark: "2026-07-11",
          requested_knowledge_as_of: "2026-07-11T00:00:00Z",
          semantic_channels: {
            formal: { watermark: "2026-07-11" },
            evaluated_candidate: { watermark: "2026-07-18" },
            observed: { watermark: "2026-07-18" },
          },
        }}
      />,
    );

    expect(screen.getByTestId("wm-formal")).toHaveTextContent("2026-07-11");
    expect(screen.getByTestId("wm-candidate")).toHaveTextContent("unavailable");
    expect(screen.getByTestId("wm-observed")).toHaveTextContent("unavailable");
  });
});

describe("CompositeChart", () => {
  it("draws three independent layer groups with correct baseline vs overlay roles", () => {
    render(<CompositeChart composite={COMPOSITE_FIXTURE} range="All" />);
    const formal = screen.getByTestId("layer-formal");
    const candidate = screen.getByTestId("layer-evaluated_candidate");
    const observed = screen.getByTestId("layer-latest_observed");
    expect(formal.getAttribute("data-render-role")).toBe("baseline");
    expect(candidate.getAttribute("data-render-role")).toBe("overlay");
    expect(observed.getAttribute("data-render-role")).toBe("overlay");
  });

  it("marks the formal watermark divider and shows the scale label", () => {
    render(<CompositeChart composite={COMPOSITE_FIXTURE} range="All" />);
    expect(screen.getByTestId("formal-watermark-divider")).toBeTruthy();
    expect(screen.getByTestId("scale-current")).toBeTruthy();
  });

  it("renders OHLC candles and never presents candidate/observed candles as published", () => {
    const { container } = render(<CompositeChart composite={COMPOSITE_FIXTURE} range="All" />);
    const formalCandles = container.querySelectorAll('[data-testid="candle-formal"]');
    const candidateCandles = container.querySelectorAll(
      '[data-testid="candle-evaluated_candidate"]',
    );
    const observedCandles = container.querySelectorAll('[data-testid="candle-latest_observed"]');
    expect(formalCandles.length).toBeGreaterThan(0);
    expect(candidateCandles.length).toBeGreaterThan(0);
    expect(observedCandles.length).toBeGreaterThan(0);
    candidateCandles.forEach((candle) =>
      expect(candle.getAttribute("data-presented-as-published")).toBe("false"),
    );
    observedCandles.forEach((candle) =>
      expect(candle.getAttribute("data-presented-as-published")).toBe("false"),
    );
    candidateCandles.forEach((candle) =>
      expect(candle.getAttribute("data-texture")).not.toBe("none"),
    );
  });

  it("renders volume bars and date ticks as part of the K-line visualization", () => {
    const { container } = render(<CompositeChart composite={COMPOSITE_FIXTURE} range="All" />);

    expect(container.querySelectorAll('[data-testid="volume-formal"]').length).toBeGreaterThan(0);
    expect(
      container.querySelectorAll('[data-testid="volume-evaluated_candidate"]').length,
    ).toBeGreaterThan(0);
    expect(screen.getAllByTestId("chart-date-tick").length).toBeGreaterThanOrEqual(3);
  });

  it("shows selected-date OHLC and volume readout inside the chart", () => {
    render(
      <CompositeChart
        composite={COMPOSITE_FIXTURE}
        range="All"
        selectedDate="2026-07-14"
        onSelectDate={() => {}}
      />,
    );

    expect(screen.getByTestId("chart-selected-readout")).toHaveTextContent("2026-07-14");
    expect(screen.getByTestId("readout-evaluated_candidate")).toHaveTextContent("O 62,000");
    expect(screen.getByTestId("readout-latest_observed")).toHaveTextContent("C 62,010");
    expect(screen.getByTestId("readout-latest_observed")).toHaveTextContent("V 1,000");
  });

  it("does not draw a candidate candle for a missing date", () => {
    const { container } = render(<CompositeChart composite={COMPOSITE_FIXTURE} range="All" />);
    const missingDateCandle = container.querySelector(
      '[data-testid="candle-evaluated_candidate"][data-date="2026-07-13"]',
    );
    expect(missingDateCandle).toBeNull();
  });

  it("renders non-color markers with a shape glyph for quarantine/revision", () => {
    render(<CompositeChart composite={COMPOSITE_FIXTURE} range="All" />);
    const markers = screen.getAllByTestId("chart-marker");
    expect(markers.length).toBeGreaterThan(0);
    const kinds = markers.map((m) => m.getAttribute("data-marker-kind"));
    expect(kinds).toContain("quarantine");
    // Each marker has visible glyph text (non-color redundancy).
    markers.forEach((m) => expect((m.textContent || "").length).toBeGreaterThan(0));
  });

  it("shows the three-layer legend", () => {
    render(<CompositeChart composite={COMPOSITE_FIXTURE} range="All" />);
    const legend = screen.getByTestId("composite-legend");
    expect(within(legend).getByTestId("legend-formal")).toBeTruthy();
    expect(within(legend).getByTestId("legend-evaluated_candidate")).toBeTruthy();
    expect(within(legend).getByTestId("legend-latest_observed")).toBeTruthy();
  });

  it("uses one pointer overlay and a keyboard-operable date inspector instead of per-date hit targets", () => {
    const { container } = render(
      <CompositeChart composite={COMPOSITE_FIXTURE} range="All" onSelectDate={() => {}} />,
    );
    expect(screen.getByTestId("chart-pointer-overlay")).toBeTruthy();
    expect(screen.getByTestId("chart-date-inspector")).toHaveAttribute("type", "date");
    expect(container.querySelectorAll('[data-testid^="hit-"]')).toHaveLength(0);
  });

  it("renders a Context-only quarantine marker and breaks the selected layer without plotting an excluded close", () => {
    const compositeWithoutQuarantine = {
      ...COMPOSITE_FIXTURE,
      layers: {
        ...COMPOSITE_FIXTURE.layers,
        latest_observed: {
          ...COMPOSITE_FIXTURE.layers?.latest_observed,
          rows: (COMPOSITE_FIXTURE.layers?.latest_observed?.rows ?? []).filter(
            (row) => row.date !== "2026-07-15",
          ),
        },
      },
    };
    const { container } = render(
      <CompositeChart
        composite={compositeWithoutQuarantine}
        range="All"
        quarantineBreakLayer="latest_observed"
        excludedDates={[
          {
            date: "2026-07-15",
            exclusion_reason: "quarantined",
            quality_flags: ["quarantined"],
          },
        ]}
      />,
    );

    const quarantineMarker = screen
      .getAllByTestId("chart-marker")
      .find((marker) => marker.getAttribute("data-marker-kind") === "quarantine");
    expect(quarantineMarker).toHaveTextContent("◇");
    expect(
      container.querySelectorAll('[data-testid="candle-latest_observed"][data-date="2026-07-15"]'),
    ).toHaveLength(0);
    expect(container.querySelectorAll('[data-testid="candle-latest_observed"]')).toHaveLength(4);
  });

  it("breaks each composite layer at that layer's own Context quarantine date", () => {
    const { container } = render(
      <CompositeChart
        composite={{
          view: "composite",
          layers: {
            formal: null,
            evaluated_candidate: {
              channel: "evaluated_candidate",
              context: {
                ...CONTEXT_FIXTURE,
                resolved_channel: "evaluated_candidate",
                excluded_dates: [
                  {
                    date: "2026-01-02",
                    exclusion_reason: "quarantined",
                    quality_flags: ["quarantined"],
                  },
                ],
              },
              rows: [
                {
                  date: "2026-01-01",
                  open: "59900",
                  high: "60200",
                  low: "59800",
                  close: "60000",
                  availability_state: "present",
                },
                {
                  date: "2026-01-02",
                  open: "60000",
                  high: "61200",
                  low: "59900",
                  close: "61000",
                  availability_state: "present",
                },
                {
                  date: "2026-01-03",
                  open: "61000",
                  high: "62300",
                  low: "60900",
                  close: "62000",
                  availability_state: "present",
                },
              ],
            },
            latest_observed: null,
          },
        }}
        range="All"
      />,
    );

    expect(
      container.querySelectorAll(
        '[data-testid="candle-evaluated_candidate"][data-date="2026-01-02"]',
      ),
    ).toHaveLength(0);
    expect(container.querySelectorAll('[data-testid="candle-evaluated_candidate"]')).toHaveLength(
      2,
    );
    expect(
      screen
        .getAllByTestId("chart-marker")
        .some((marker) => marker.getAttribute("data-marker-kind") === "quarantine"),
    ).toBe(true);
  });

  it("caps rendered quarantine/revision marker DOM nodes at the chart point budget", () => {
    const rows = Array.from({ length: 2_000 }, (_, index) => ({
      date: `2020-01-${String((index % 28) + 1).padStart(2, "0")}-${index}`,
      close: String(30_000 + index),
      availability_state: "present" as const,
      revision_state: "changed" as const,
    }));
    render(
      <CompositeChart
        composite={{
          view: "composite",
          layers: {
            formal: {
              channel: "formal",
              context: CONTEXT_FIXTURE,
              rows,
            },
            evaluated_candidate: null,
            latest_observed: null,
          },
        }}
        range="All"
      />,
    );

    expect(screen.getAllByTestId("chart-marker")).toHaveLength(OBSERVATORY_CHART_POINT_BUDGET);
  });

  it("caps Context-only quarantine fallback markers within the chart point budget", () => {
    const excludedDates = Array.from({ length: 2_000 }, (_, index) => ({
      date: `2020-02-${String((index % 28) + 1).padStart(2, "0")}-${index}`,
      exclusion_reason: "quarantined",
      quality_flags: ["quarantined"],
    }));
    render(
      <CompositeChart
        composite={{
          view: "composite",
          layers: {
            formal: null,
            evaluated_candidate: null,
            latest_observed: null,
          },
        }}
        range="All"
        excludedDates={excludedDates}
      />,
    );

    const renderedMarkerCount =
      screen.queryAllByTestId("chart-marker").length +
      screen.queryAllByTestId("chart-context-quarantine-marker").length;
    expect(renderedMarkerCount).toBe(OBSERVATORY_CHART_POINT_BUDGET);
  });

  it("caps combined layer and Context fallback markers within the chart point budget", () => {
    const rows = Array.from({ length: 2_000 }, (_, index) => ({
      date: `2020-05-${String((index % 28) + 1).padStart(2, "0")}-${index}`,
      close: String(30_000 + index),
      availability_state: "present" as const,
      revision_state: "changed" as const,
    }));
    const excludedDates = rows.map((row) => ({
      date: row.date,
      exclusion_reason: "quarantined",
      quality_flags: ["quarantined"],
    }));
    render(
      <CompositeChart
        composite={{
          view: "composite",
          layers: {
            formal: {
              channel: "formal",
              context: CONTEXT_FIXTURE,
              rows,
            },
            evaluated_candidate: null,
            latest_observed: null,
          },
        }}
        range="All"
        excludedDates={excludedDates}
      />,
    );

    const renderedMarkerCount =
      screen.queryAllByTestId("chart-marker").length +
      screen.queryAllByTestId("chart-context-quarantine-marker").length;
    expect(renderedMarkerCount).toBe(OBSERVATORY_CHART_POINT_BUDGET);
    expect(
      screen
        .getAllByTestId("chart-context-quarantine-marker")
        .some((marker) => marker.textContent === "◇"),
    ).toBe(true);
  });

  it("retains a sparse Context quarantine marker while sampling revision-heavy markers", () => {
    const rows = Array.from({ length: 2_000 }, (_, index) => ({
      date: `2020-03-${String((index % 28) + 1).padStart(2, "0")}-${index}`,
      close: String(30_000 + index),
      availability_state: "present" as const,
      revision_state: "changed" as const,
    }));
    render(
      <CompositeChart
        composite={{
          view: "composite",
          layers: {
            formal: {
              channel: "formal",
              context: CONTEXT_FIXTURE,
              rows,
            },
            evaluated_candidate: null,
            latest_observed: null,
          },
        }}
        range="All"
        excludedDates={[
          {
            date: "2021-01-01",
            exclusion_reason: "quarantined",
            quality_flags: ["quarantined"],
          },
        ]}
      />,
    );

    const renderedMarkerCount =
      screen.queryAllByTestId("chart-marker").length +
      screen.queryAllByTestId("chart-context-quarantine-marker").length;
    expect(renderedMarkerCount).toBe(OBSERVATORY_CHART_POINT_BUDGET);
    expect(screen.getByTestId("chart-context-quarantine-marker")).toHaveTextContent("◇");
    expect(screen.getByTestId("chart-marker-sampling-notice")).toHaveTextContent(
      "each available status type is retained",
    );
  });

  it("retains a raw status marker even when its row is omitted from line geometry sampling", () => {
    const rows = Array.from({ length: 2_000 }, (_, index) => ({
      date: `2020-04-${String((index % 28) + 1).padStart(2, "0")}-${index}`,
      close: String(30_000 + index),
      availability_state: "present" as const,
      revision_state: index === 1 ? ("changed" as const) : undefined,
    }));
    render(
      <CompositeChart
        composite={{
          view: "composite",
          layers: {
            formal: {
              channel: "formal",
              context: CONTEXT_FIXTURE,
              rows,
            },
            evaluated_candidate: null,
            latest_observed: null,
          },
        }}
        range="All"
      />,
    );

    expect(
      screen
        .getAllByTestId("chart-marker")
        .some((marker) => marker.getAttribute("data-marker-kind") === "revision"),
    ).toBe(true);
  });
});

describe("WhyNotFormal", () => {
  it("explains published baseline versus staged candidate in user-facing terms", () => {
    render(<WhyNotFormal context={CONTEXT_FIXTURE} />);

    expect(screen.getByTestId("published-baseline-explain")).toHaveTextContent(
      "Published baseline means the run passed the stricter gates",
    );
    expect(screen.getByTestId("why-not-formal")).toHaveTextContent("staged candidate");
    expect(screen.getByTestId("why-not-formal")).toHaveTextContent("CHANNEL_UNAVAILABLE");
  });
});

describe("DateEvidenceLens", () => {
  it("shows research outcome fixed to not_visible in Observe/Investigate", () => {
    render(
      <DateEvidenceLens date="2026-07-15" channel="observed" evidence={DATE_EVIDENCE_FIXTURE} />,
    );
    expect(screen.getByTestId("research-visibility").textContent).toContain("not_visible");
  });

  it("keeps Observe research visibility fixed when a malformed response reports a future state", () => {
    render(
      <DateEvidenceLens
        date="2026-07-15"
        channel="observed"
        evidence={{ ...DATE_EVIDENCE_FIXTURE, research_visibility: "matured" }}
      />,
    );
    expect(screen.getByTestId("research-visibility")).toHaveTextContent("not_visible");
    expect(screen.getByTestId("research-visibility")).not.toHaveTextContent("matured");
  });

  it("shows non-color markers for a quarantined date", () => {
    render(
      <DateEvidenceLens date="2026-07-15" channel="observed" evidence={DATE_EVIDENCE_FIXTURE} />,
    );
    const markers = screen.getByTestId("date-evidence-markers");
    expect(markers.textContent).toContain("Quarantined");
  });

  it("renders provider, basis reconciliation and four clocks", () => {
    render(
      <DateEvidenceLens date="2026-07-15" channel="observed" evidence={DATE_EVIDENCE_FIXTURE} />,
    );
    const panel = screen.getByTestId("date-evidence");
    expect(panel.textContent).toContain("okx");
    expect(panel.textContent).toContain("basis_bps");
    expect(panel.textContent).toContain("Available at");
    expect(panel.textContent).toContain("Fetched at");
  });
});

describe("ResearchLens provenance", () => {
  it("does not treat a hypothesis state as receipt-backed when the receipt omits its state", () => {
    render(
      <ResearchLens
        hypothesis={{ ...HYPOTHESES_FIXTURE.hypotheses?.[0], research_state: "validated" }}
        researchRun={{ ...RESEARCH_RUN_FIXTURE, research_state: undefined }}
      />,
    );

    expect(screen.getByTestId("research-insufficient")).toHaveTextContent("Research Unknown");
    expect(screen.queryByTestId("research-metrics")).toBeNull();
  });

  it("does not render unprovided fold or distribution geometry as research evidence", () => {
    render(
      <ResearchLens
        hypothesis={HYPOTHESES_FIXTURE.hypotheses?.[0]}
        researchRun={RESEARCH_RUN_FIXTURE}
      />,
    );

    expect(screen.getByTestId("research-distribution-unavailable")).toHaveTextContent(
      "does not provide immutable, provenance-bound distribution values",
    );
    expect(screen.queryByLabelText("Fold effect forest plot (illustrative axis)")).toBeNull();
  });

  it("does not create a lab deep link from incomplete or mismatched provenance", () => {
    render(
      <ResearchLens
        hypothesis={HYPOTHESES_FIXTURE.hypotheses?.[0]}
        researchRun={{
          ...RESEARCH_RUN_FIXTURE,
          dataset_snapshot_id: null,
          knowledge_as_of: null,
          hypothesis_version: "other-version",
        }}
      />,
    );

    expect(screen.getByTestId("open-in-lab-button")).toBeDisabled();
    expect(screen.getByTestId("open-in-lab-unavailable")).toHaveTextContent(
      "Complete matched provenance is unavailable",
    );
  });
});

describe("TrustLens and RunsLineageLens failure budgets", () => {
  it("caps coverage DOM cells at the configured 90-day budget", () => {
    const rows = Array.from({ length: 1_000 }, (_, index) => ({
      date: new Date(Date.UTC(2024, 0, 1 + index)).toISOString().slice(0, 10),
      availability_state: "present" as const,
    }));
    render(<TrustLens series={{ view: "observed", rows, pit_valid: true }} trust={null} />);

    expect(screen.getByTestId("coverage-calendar").querySelectorAll(".obs-cal-cell")).toHaveLength(
      90,
    );
  });

  it("renders structured run detail and diff errors with their retry actions", () => {
    const retryDetail = vi.fn();
    const retryDiff = vi.fn();
    render(
      <RunsLineageLens
        runs={RUNS_FIXTURE}
        selectedRunId="run_observed"
        compareRunId="run_formal"
        detailError={{
          message: "Current run detail is unavailable.",
          reasonCodes: ["RUN_DETAIL_UNAVAILABLE"],
          evidenceRefs: ["run:run_observed"],
          retryable: true,
        }}
        diffError={{
          message: "Current run diff is unavailable.",
          reasonCodes: ["RUN_DIFF_UNAVAILABLE"],
          evidenceRefs: ["run:run_observed"],
          retryable: true,
        }}
        onDetailRetry={retryDetail}
        onDiffRetry={retryDiff}
        onSelectRun={() => {}}
        onCompareRun={() => {}}
      />,
    );

    const detailError = screen.getByText("Run detail unavailable").parentElement;
    const diffError = screen.getByText("Run diff unavailable").parentElement;
    expect(detailError).toHaveTextContent("RUN_DETAIL_UNAVAILABLE");
    expect(diffError).toHaveTextContent("RUN_DIFF_UNAVAILABLE");
    within(detailError as HTMLElement)
      .getByRole("button", { name: "Retry" })
      .click();
    within(diffError as HTMLElement)
      .getByRole("button", { name: "Retry" })
      .click();
    expect(retryDetail).toHaveBeenCalledTimes(1);
    expect(retryDiff).toHaveBeenCalledTimes(1);
  });
});
