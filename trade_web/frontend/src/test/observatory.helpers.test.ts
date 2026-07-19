import { describe, expect, it } from "vitest";

import {
  applyRangeWindow,
  buildSegments,
  buildWhatChanged,
  candidateRowsRenderedAsPublished,
  deserializeObservatoryState,
  extractLayers,
  formalWatermarkDate,
  isPlottable,
  layerTreatment,
  markersForRow,
  observedOnlyDates,
  parseDecimal,
  purposeTone,
  serializeObservatoryState,
  unionDates,
  DEFAULT_OBS_URL_STATE,
  type ObservatoryUrlState,
} from "../lib/observatory";
import { COMPOSITE_FIXTURE } from "./fixtures";
import type { ObsSeriesRow } from "../lib/api";

describe("parseDecimal", () => {
  it("parses decimal strings and rejects null / empty / NaN", () => {
    expect(parseDecimal("60000")).toBe(60000);
    expect(parseDecimal("60000.25")).toBeCloseTo(60000.25);
    expect(parseDecimal(null)).toBeNull();
    expect(parseDecimal(undefined)).toBeNull();
    expect(parseDecimal("")).toBeNull();
    expect(parseDecimal("not-a-number")).toBeNull();
  });
});

describe("composite layering", () => {
  it("returns three independent layers that are never merged", () => {
    const layers = extractLayers(COMPOSITE_FIXTURE);
    expect(layers.map((l) => l.key)).toEqual(["formal", "evaluated_candidate", "latest_observed"]);
    // Each layer keeps its own rows — overlap dates exist in more than one layer
    // but are NOT collapsed into a single series.
    const formal = layers.find((l) => l.key === "formal")!;
    const candidate = layers.find((l) => l.key === "evaluated_candidate")!;
    const observed = layers.find((l) => l.key === "latest_observed")!;
    expect(formal.rows.length).toBeGreaterThan(0);
    expect(candidate.rows.length).toBeGreaterThan(0);
    expect(observed.rows.length).toBeGreaterThan(0);
    // 2026-07-10 appears in both formal and candidate with DIFFERENT closes,
    // proving no overwrite/average happened.
    const formal10 = formal.rows.find((r) => r.date === "2026-07-10");
    const cand10 = candidate.rows.find((r) => r.date === "2026-07-10");
    expect(formal10?.close).toBe("59000");
    expect(cand10?.close).toBe("59050");
  });

  it("renders the observed-only tail distinctly (observed_watermark > formal_watermark)", () => {
    const tail = observedOnlyDates(COMPOSITE_FIXTURE);
    // 07-15..07-18 are observed-only (beyond formal 07-11 and candidate 07-14).
    expect(tail).toContain("2026-07-15");
    expect(tail).toContain("2026-07-18");
    expect(tail).not.toContain("2026-07-14"); // overlaps candidate
    const formalWm = formalWatermarkDate(COMPOSITE_FIXTURE);
    expect(formalWm).toBe("2026-07-11");
    expect(tail[tail.length - 1] > (formalWm as string)).toBe(true);
  });
});

describe("candidate never rendered as published", () => {
  it("no candidate row carries a formal_baseline render treatment", () => {
    expect(candidateRowsRenderedAsPublished(COMPOSITE_FIXTURE)).toEqual([]);
  });

  it("candidate + observed treatments are never presentedAsPublished and carry a persistent texture", () => {
    const candidate = layerTreatment("evaluated_candidate");
    const observed = layerTreatment("latest_observed");
    const formal = layerTreatment("formal");
    expect(candidate.presentedAsPublished).toBe(false);
    expect(observed.presentedAsPublished).toBe(false);
    expect(candidate.texture).toBeTruthy();
    expect(observed.texture).toBeTruthy();
    // Only formal is the solid baseline.
    expect(formal.isBaseline).toBe(true);
    expect(candidate.isBaseline).toBe(false);
    expect(observed.isBaseline).toBe(false);
    expect(formal.stroke).toBe("solid");
    expect(candidate.stroke).toBe("dashed");
  });
});

describe("missing dates are not interpolated", () => {
  it("breaks the line into separate segments at a missing date", () => {
    const rows: ObsSeriesRow[] = [
      { date: "2026-07-12", close: "61000", availability_state: "present" },
      { date: "2026-07-13", close: null, availability_state: "missing" },
      { date: "2026-07-14", close: "62000", availability_state: "present" },
    ];
    const segments = buildSegments(rows);
    // Two segments (12) and (14) — never a single bridged line across 13.
    expect(segments.length).toBe(2);
    expect(segments[0].map((p) => p.date)).toEqual(["2026-07-12"]);
    expect(segments[1].map((p) => p.date)).toEqual(["2026-07-14"]);
  });

  it("isPlottable rejects non-present availability states and null close", () => {
    expect(isPlottable({ close: "1", availability_state: "present" })).toBe(true);
    expect(isPlottable({ close: null, availability_state: "present" })).toBe(false);
    expect(isPlottable({ close: "1", availability_state: "missing" })).toBe(false);
    expect(isPlottable({ close: "1", availability_state: "unobserved" })).toBe(false);
    expect(isPlottable({ close: "1", availability_state: "unknown" })).toBe(false);
  });

  it("the candidate layer's missing 07-13 splits it into two segments", () => {
    const candidate = extractLayers(COMPOSITE_FIXTURE).find((l) => l.key === "evaluated_candidate")!;
    const segments = buildSegments(candidate.rows);
    const dates = segments.map((seg) => seg.map((p) => p.date));
    // 07-10,07-11,07-12 | (07-13 missing) | 07-14
    expect(segments.length).toBe(2);
    expect(dates[0]).toContain("2026-07-12");
    expect(dates[1]).toEqual(["2026-07-14"]);
  });
});

describe("non-color semantics", () => {
  it("quarantine + revision carry icon + text + texture (not color alone)", () => {
    const quarantined = markersForRow({ quality_flags: ["quarantined"], availability_state: "present" });
    expect(quarantined).toHaveLength(1);
    expect(quarantined[0].kind).toBe("quarantine");
    expect(quarantined[0].icon).toBeTruthy();
    expect(quarantined[0].label).toBe("Quarantined");
    expect(quarantined[0].texture).toBeTruthy();

    const revised = markersForRow({ revision_state: "changed", availability_state: "present" });
    expect(revised[0].kind).toBe("revision");
    expect(revised[0].icon).toBeTruthy();
    expect(revised[0].label).toBe("Revised");
  });

  it("missing / unobserved produce distinct non-color markers", () => {
    expect(markersForRow({ availability_state: "missing" })[0].kind).toBe("missing");
    expect(markersForRow({ availability_state: "unobserved" })[0].kind).toBe("unobserved");
    // unchanged/present has no marker.
    expect(markersForRow({ availability_state: "present", revision_state: "unchanged" })).toEqual([]);
  });
});

describe("what changed (deterministic, rule-based)", () => {
  it("summarizes observed-only additions, revisions and quarantines from evidence", () => {
    const entries = buildWhatChanged(COMPOSITE_FIXTURE);
    const kinds = entries.map((e) => e.kind);
    expect(kinds).toContain("added_dates");
    expect(kinds).toContain("revised_dates");
    expect(kinds).toContain("quarantined_dates");
    expect(kinds).toContain("watermark");
    // Every entry is evidence-linked or has a concrete detail (no LLM prose).
    for (const e of entries) {
      expect(e.detail.length).toBeGreaterThan(0);
    }
  });
});

describe("range windowing and union dates", () => {
  it("union dates cover every date across all layers, sorted", () => {
    const dates = unionDates(COMPOSITE_FIXTURE);
    expect(dates[0]).toBe("2026-07-09");
    expect(dates[dates.length - 1]).toBe("2026-07-18");
    expect([...dates]).toEqual([...dates].sort());
  });

  it("applyRangeWindow trims to trailing window and keeps All intact", () => {
    const dates = unionDates(COMPOSITE_FIXTURE);
    expect(applyRangeWindow(dates, "All")).toEqual(dates);
    const win = applyRangeWindow(dates, "30D");
    expect(win.length).toBeLessThanOrEqual(dates.length);
    expect(win[win.length - 1]).toBe("2026-07-18");
  });
});

describe("purpose tone", () => {
  it("maps allowed/blocked/warn states to tones", () => {
    expect(purposeTone("allowed", true)).toBe("ok");
    expect(purposeTone("blocked", false)).toBe("err");
    expect(purposeTone("degraded", false)).toBe("warn");
    expect(purposeTone(undefined, false)).toBe("muted");
  });
});

describe("URL state round-trips (fixed URL restore)", () => {
  it("serializes and deserializes back to the same state", () => {
    const state: ObservatoryUrlState = {
      lens: "runs",
      channel: "evaluated_candidate",
      knowledgeAsOf: "2026-07-11",
      range: "1Y",
      runId: "run_observed",
      compareRunId: "run_formal",
      date: "2026-07-15",
    };
    const params = serializeObservatoryState(state);
    const restored = deserializeObservatoryState(params);
    expect(restored).toEqual(state);
  });

  it("defaults are omitted from the query but restore to defaults", () => {
    const params = serializeObservatoryState(DEFAULT_OBS_URL_STATE);
    // knowledge=latest and default range are not serialized.
    expect(params.get("knowledgeAsOf")).toBeNull();
    expect(params.get("obsRange")).toBeNull();
    expect(params.get("obsLens")).toBe("overview");
    const restored = deserializeObservatoryState(params);
    expect(restored.knowledgeAsOf).toBe("latest");
    expect(restored.range).toBe(DEFAULT_OBS_URL_STATE.range);
  });

  it("rejects unknown lens / channel and falls back to defaults", () => {
    const params = new URLSearchParams("obsLens=bogus&obsChannel=bogus");
    const restored = deserializeObservatoryState(params);
    expect(restored.lens).toBe("overview");
    expect(restored.channel).toBe("observed");
  });
});
