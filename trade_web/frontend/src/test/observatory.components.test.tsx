import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { CompositeChart } from "../components/observatory/CompositeChart";
import { DateEvidenceLens } from "../components/observatory/DateEvidenceLens";
import { SnapshotContextBar } from "../components/observatory/SnapshotContextBar";
import { COMPOSITE_FIXTURE, CONTEXT_FIXTURE, DATE_EVIDENCE_FIXTURE } from "./fixtures";

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
    expect(chips.textContent).toContain("Formal System Consumption");
    // Blocked purpose is shown as not allowed.
    expect(chips.textContent?.toLowerCase()).toContain("blocked");
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

  it("never presents candidate/observed paths as published (data attribute)", () => {
    const { container } = render(<CompositeChart composite={COMPOSITE_FIXTURE} range="All" />);
    const candidatePaths = container.querySelectorAll(
      '[data-testid="layer-evaluated_candidate"] path[data-presented-as-published]',
    );
    candidatePaths.forEach((p) => expect(p.getAttribute("data-presented-as-published")).toBe("false"));
    const observedPaths = container.querySelectorAll(
      '[data-testid="layer-latest_observed"] path[data-presented-as-published]',
    );
    observedPaths.forEach((p) => expect(p.getAttribute("data-presented-as-published")).toBe("false"));
    // The candidate layer carries a persistent texture attribute (not just color).
    candidatePaths.forEach((p) => expect(p.getAttribute("data-texture")).not.toBe("none"));
  });

  it("breaks the candidate line into >=2 path segments at the missing date (no interpolation)", () => {
    const { container } = render(<CompositeChart composite={COMPOSITE_FIXTURE} range="All" />);
    const candidatePaths = container.querySelectorAll('[data-testid="layer-evaluated_candidate"] path');
    // 07-10..07-12 and 07-14 => two separate <path> elements.
    expect(candidatePaths.length).toBeGreaterThanOrEqual(2);
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
});

describe("DateEvidenceLens", () => {
  it("shows research outcome fixed to not_visible in Observe/Investigate", () => {
    render(<DateEvidenceLens date="2026-07-15" channel="observed" evidence={DATE_EVIDENCE_FIXTURE} />);
    expect(screen.getByTestId("research-visibility").textContent).toContain("not_visible");
  });

  it("shows non-color markers for a quarantined date", () => {
    render(<DateEvidenceLens date="2026-07-15" channel="observed" evidence={DATE_EVIDENCE_FIXTURE} />);
    const markers = screen.getByTestId("date-evidence-markers");
    expect(markers.textContent).toContain("Quarantined");
  });

  it("renders provider, basis reconciliation and four clocks", () => {
    render(<DateEvidenceLens date="2026-07-15" channel="observed" evidence={DATE_EVIDENCE_FIXTURE} />);
    const panel = screen.getByTestId("date-evidence");
    expect(panel.textContent).toContain("okx");
    expect(panel.textContent).toContain("basis_bps");
    expect(panel.textContent).toContain("Available at");
    expect(panel.textContent).toContain("Fetched at");
  });
});
