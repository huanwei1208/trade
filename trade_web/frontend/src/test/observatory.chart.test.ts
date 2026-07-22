import { describe, expect, it } from "vitest";

import type { ObsContext, ObsSeriesRow, ObsSingleSeries } from "../lib/api";
import {
  buildObservatoryKlineModel,
  OBSERVATORY_DIAGNOSTIC_EVIDENCE_LIMIT,
  OBSERVATORY_DIAGNOSTIC_REASON_LIMIT,
  type ObservatoryKlineDiagnostic,
} from "../lib/observatoryChart";
import { CONTEXT_FIXTURE, OBSERVED_SERIES_FIXTURE } from "./fixtures";

function presentRow(date: string, overrides: Partial<ObsSeriesRow> = {}): ObsSeriesRow {
  return {
    date,
    open: "100.10",
    high: "105.20",
    low: "98.30",
    close: "102.40",
    volume: "1234.5000",
    provider: "okx",
    instrument: "BTC-USDT",
    quote: "USDT",
    availability_state: "present",
    quality_flags: [],
    revision_state: "unchanged",
    ...overrides,
  };
}

function selectedSeries(rows: ObsSeriesRow[] | undefined): ObsSingleSeries {
  return {
    view: "observed",
    context: CONTEXT_FIXTURE,
    rows,
    pit_valid: true,
    reason_codes: [],
  };
}

function context(overrides: Partial<ObsContext> = {}): ObsContext {
  return { ...CONTEXT_FIXTURE, excluded_dates: [], ...overrides };
}

function reasons(diagnostics: ObservatoryKlineDiagnostic[], date: string | null): string[] {
  return diagnostics.find((diagnostic) => diagnostic.date === date)?.reasonCodes ?? [];
}

describe("buildObservatoryKlineModel", () => {
  it("adapts an actual selected-series shape and keeps decimal strings authoritative", () => {
    const model = buildObservatoryKlineModel(OBSERVED_SERIES_FIXTURE, CONTEXT_FIXTURE);

    expect(model.state).toBe("partial-invalid");
    expect(model.identity).toEqual({
      assetId: "crypto.BTC",
      displaySymbol: "BTC",
      provider: "okx",
      instrument: "BTC-USDT",
      quote: "USDT",
      interval: "1Dutc",
    });
    expect(model.suppliedRowCount).toBe(4);
    expect(model.renderedCandleCount).toBe(4);
    expect(model.spanDays).toBe(5);
    expect(model.candles).toContainEqual({ time: "2026-07-15" });
    expect(model.volumes).toContainEqual({ time: "2026-07-15" });
    expect(model.readouts["2026-07-14"]).toMatchObject({
      open: "62010",
      high: "62010",
      low: "62010",
      close: "62010",
      volume: "1000",
    });
    expect(reasons(model.diagnostics, "2026-07-15")).toEqual(["EXCLUDED_DATE", "QUARANTINED"]);
    expect(reasons(model.diagnostics, "2026-07-17")).toEqual(["REVISION_CHANGED"]);
    expect(model.markers.filter((marker) => marker.time === "2026-07-15")).toHaveLength(1);
  });

  it.each([
    ["formal", "Published baseline", "published", "Published baseline"],
    ["evaluated_candidate", "Evaluated candidate", "unpublished", "UNPUBLISHED"],
    ["observed", "Latest observed", "unpublished", "UNPUBLISHED"],
  ] as const)(
    "keeps %s lifecycle and publication truth in the renderer-neutral model",
    (channel, channelLabel, publication, publicationLabel) => {
      const activeContext = context({ resolved_channel: channel });
      const series = selectedSeries([presentRow("2026-01-01")]);
      series.view = channel;
      series.context = { ...activeContext };

      const model = buildObservatoryKlineModel(series, activeContext);

      expect(model.lifecycle).toMatchObject({
        channel,
        channelLabel,
        publication,
        publicationLabel,
      });
    },
  );

  it("fails closed when selected-series and Context lifecycle identities differ", () => {
    const series = selectedSeries([presentRow("2026-01-01")]);
    series.view = "evaluated_candidate";

    const model = buildObservatoryKlineModel(series, context());

    expect(model.state).toBe("invalid");
    expect(model.fatalReasonCodes).toContain("LIFECYCLE_IDENTITY_MISMATCH");
  });

  it("sorts validated dates and emits explicit UTC whitespace for missing daily rows", () => {
    const model = buildObservatoryKlineModel(
      selectedSeries([presentRow("2026-01-03"), presentRow("2026-01-01")]),
      context(),
    );

    expect(model.state).toBe("partial-invalid");
    expect(model.dates).toEqual(["2026-01-01", "2026-01-02", "2026-01-03"]);
    expect(model.candles[1]).toEqual({ time: "2026-01-02" });
    expect(reasons(model.diagnostics, "2026-01-02")).toEqual(["MISSING_DAILY_ROW"]);
  });

  it("keeps a present candle when volume is absent and emits volume whitespace", () => {
    const model = buildObservatoryKlineModel(
      selectedSeries([presentRow("2026-01-01", { volume: null })]),
      context(),
    );

    expect(model.state).toBe("ready");
    expect(model.renderedCandleCount).toBe(1);
    expect(model.volumes).toEqual([{ time: "2026-01-01" }]);
    expect(model.readouts["2026-01-01"].volume).toBeNull();
  });

  it.each([
    ["whitespace", { open: " 100" }, "INVALID_OHLC_DECIMAL"],
    ["exponent", { close: "1e2" }, "INVALID_OHLC_DECIMAL"],
    ["hex", { high: "0x69" }, "INVALID_OHLC_DECIMAL"],
    ["zero price", { low: "0" }, "INVALID_OHLC_DECIMAL"],
    ["negative volume", { volume: "-1" }, "INVALID_VOLUME"],
    ["non-enclosing high", { high: "99" }, "INVALID_OHLC_ENVELOPE"],
    ["non-enclosing low", { low: "103" }, "INVALID_OHLC_ENVELOPE"],
  ])("rejects %s without rendering misleading geometry", (_name, overrides, code) => {
    const model = buildObservatoryKlineModel(
      selectedSeries([
        presentRow("2026-01-01"),
        presentRow("2026-01-02", overrides as Partial<ObsSeriesRow>),
      ]),
      context(),
    );

    expect(model.state).toBe("partial-invalid");
    expect(model.renderedCandleCount).toBe(1);
    expect(model.candles[1]).toEqual({ time: "2026-01-02" });
    expect(reasons(model.diagnostics, "2026-01-02")).toContain(code);
  });

  it.each([
    [
      "near-ULP decimals",
      {
        open: "1.00000000000000002",
        high: "1.00000000000000001",
        low: "1",
        close: "1.00000000000000002",
      },
    ],
    [
      "integers beyond safe-number precision",
      {
        open: "9007199254740993",
        high: "9007199254740992",
        low: "9007199254740991",
        close: "9007199254740993",
      },
    ],
  ])("validates the %s OHLC envelope before lossy geometry conversion", (_name, overrides) => {
    const model = buildObservatoryKlineModel(
      selectedSeries([
        presentRow("2026-01-01"),
        presentRow("2026-01-02", overrides as Partial<ObsSeriesRow>),
      ]),
      context(),
    );

    expect(model.state).toBe("partial-invalid");
    expect(model.renderedCandleCount).toBe(1);
    expect(reasons(model.diagnostics, "2026-01-02")).toContain("INVALID_OHLC_ENVELOPE");
  });

  it("marks every duplicate date invalid instead of selecting a first or last row", () => {
    const model = buildObservatoryKlineModel(
      selectedSeries([
        presentRow("2026-01-01", { close: "101" }),
        presentRow("2026-01-01", { close: "102" }),
        presentRow("2026-01-02"),
      ]),
      context(),
    );

    expect(model.state).toBe("partial-invalid");
    expect(model.candles[0]).toEqual({ time: "2026-01-01" });
    expect(model.readouts["2026-01-01"]).toBeUndefined();
    expect(model.invalidRowCount).toBe(2);
    expect(reasons(model.diagnostics, "2026-01-01")).toContain("DUPLICATE_DATE");
  });

  it("uses Context exclusions as the quarantine authority and aggregates one marker per date", () => {
    const activeContext = context({
      excluded_dates: [
        {
          date: "2026-01-02",
          exclusion_reason: "quarantined",
          quality_flags: ["basis_breach", "quarantined"],
          evidence_refs: ["run_candidate", "receipts/quarantine.json", "run_candidate"],
          marker_position: "below",
        },
        {
          date: "2026-01-02",
          exclusion_reason: "manual_review",
          quality_flags: ["basis_breach"],
          evidence_refs: ["manual_review"],
          marker_position: "below",
        },
      ],
    });
    const model = buildObservatoryKlineModel(
      selectedSeries([presentRow("2026-01-01"), presentRow("2026-01-02")]),
      activeContext,
    );

    expect(model.candles[1]).toEqual({ time: "2026-01-02" });
    expect(reasons(model.diagnostics, "2026-01-02")).toEqual([
      "BASIS_BREACH",
      "EXCLUDED_DATE",
      "MANUAL_REVIEW",
      "QUARANTINED",
    ]);
    const marker = model.markers.filter((candidate) => candidate.time === "2026-01-02");
    expect(marker).toHaveLength(1);
    expect(marker[0]).toMatchObject({
      evidenceRefs: ["manual_review", "receipts/quarantine.json", "run_candidate"],
      position: "below",
    });
  });

  it.each([
    ["30D", "2026-06-19"],
    ["90D", "2026-04-20"],
    ["1Y", "2025-07-19"],
  ])("keeps out-of-window exclusions out of the bounded %s lattice", (_range, from) => {
    const activeContext = context({
      excluded_dates: [
        {
          date: "1990-01-01",
          exclusion_reason: "historical_quarantine",
          quality_flags: "invalid-but-irrelevant" as unknown as string[],
        },
      ],
    });
    const model = buildObservatoryKlineModel(
      selectedSeries([presentRow("2026-07-17"), presentRow("2026-07-18")]),
      activeContext,
      365,
      { from, to: "2026-07-18" },
    );

    expect(model.state).toBe("ready");
    expect(model.spanDays).toBe(2);
    expect(model.markers).toEqual([]);
    expect(model.diagnostics).toEqual([]);
  });

  it("retains all-run exclusions when no bounded request window is supplied", () => {
    const activeContext = context({
      excluded_dates: [{ date: "2026-01-01", exclusion_reason: "historical_quarantine" }],
    });
    const model = buildObservatoryKlineModel(
      selectedSeries([presentRow("2026-07-17"), presentRow("2026-07-18")]),
      activeContext,
    );

    expect(model.state).toBe("partial-invalid");
    expect(model.spanDays).toBe(199);
    expect(model.markers).toContainEqual(
      expect.objectContaining({
        time: "2026-01-01",
        reasonCodes: ["EXCLUDED_DATE", "HISTORICAL_QUARANTINE"],
      }),
    );
  });

  it("fails closed when selected-series rows escape the inclusive request window", () => {
    const model = buildObservatoryKlineModel(
      selectedSeries([presentRow("2026-07-17"), presentRow("2026-07-19")]),
      context(),
      7_300,
      { from: "2026-07-17", to: "2026-07-18" },
    );

    expect(model.state).toBe("invalid");
    expect(model.fatalReasonCodes).toContain("SERIES_WINDOW_MISMATCH");
    expect(model.candles).toEqual([]);
  });

  it("bounds diagnostic reason and evidence detail with explicit omission counts", () => {
    const qualityFlags = Array.from({ length: 24 }, (_, index) => `quality_${index}`);
    const evidenceRefs = Array.from({ length: 12 }, (_, index) => `receipt_${index}`);
    const activeContext = context({
      excluded_dates: [
        {
          date: "2026-01-02",
          exclusion_reason: "quarantined",
          quality_flags: qualityFlags,
          evidence_refs: evidenceRefs,
        },
      ],
    });
    const model = buildObservatoryKlineModel(
      selectedSeries([presentRow("2026-01-01")]),
      activeContext,
    );
    const diagnostic = model.diagnostics.find((item) => item.date === "2026-01-02");

    expect(model.state).toBe("partial-invalid");
    expect(diagnostic?.reasonCodes).toHaveLength(OBSERVATORY_DIAGNOSTIC_REASON_LIMIT);
    expect(diagnostic?.omittedReasonCodeCount).toBe(10);
    expect(diagnostic?.evidenceRefs).toHaveLength(OBSERVATORY_DIAGNOSTIC_EVIDENCE_LIMIT);
    expect(diagnostic?.omittedEvidenceRefCount).toBe(4);
  });

  it("fails closed on malformed Gregorian dates in rows or exclusions", () => {
    const badRow = buildObservatoryKlineModel(
      selectedSeries([presentRow("2026-02-30"), presentRow("2026-03-01")]),
      context(),
    );
    const badExclusion = buildObservatoryKlineModel(
      selectedSeries([presentRow("2026-03-01")]),
      context({ excluded_dates: [{ date: "not-a-date", exclusion_reason: "quarantined" }] }),
    );

    expect(badRow.state).toBe("invalid");
    expect(badRow.candles).toEqual([]);
    expect(badRow.fatalReasonCodes).toContain("MALFORMED_DATE");
    expect(badExclusion.state).toBe("invalid");
    expect(badExclusion.fatalReasonCodes).toContain("MALFORMED_DATE");
  });

  it("fails closed when row provenance or selected-series contract differs from Context", () => {
    const mismatchedRow = buildObservatoryKlineModel(
      selectedSeries([presentRow("2026-01-01", { provider: "binance" })]),
      context(),
    );
    const mismatchedSeries = selectedSeries([presentRow("2026-01-01")]);
    mismatchedSeries.context = {
      ...CONTEXT_FIXTURE,
      contract: { ...CONTEXT_FIXTURE.contract, primary_instrument: "BTC-USD" },
    };
    const mismatchedContract = buildObservatoryKlineModel(mismatchedSeries, context());

    expect(mismatchedRow.state).toBe("invalid");
    expect(mismatchedRow.fatalReasonCodes).toContain("PROVENANCE_MISMATCH");
    expect(mismatchedContract.state).toBe("invalid");
    expect(mismatchedContract.fatalReasonCodes).toContain("SERIES_CONTRACT_MISMATCH");
  });

  it("rejects unsupported or incomplete daily contracts", () => {
    const unsupported = buildObservatoryKlineModel(
      selectedSeries([presentRow("2026-01-01")]),
      context({ contract: { ...CONTEXT_FIXTURE.contract, primary_interval: "1h" } }),
    );
    const incomplete = buildObservatoryKlineModel(
      selectedSeries([presentRow("2026-01-01")]),
      context({ contract: { ...CONTEXT_FIXTURE.contract, primary_provider: undefined } }),
    );

    expect(unsupported.state).toBe("invalid");
    expect(unsupported.fatalReasonCodes).toContain("UNSUPPORTED_INTERVAL");
    expect(incomplete.state).toBe("invalid");
    expect(incomplete.fatalReasonCodes).toContain("CONTRACT_UNAVAILABLE");
  });

  it("checks inclusive UTC span capacity before allocating lattice points", () => {
    const model = buildObservatoryKlineModel(
      selectedSeries([presentRow("2026-01-01"), presentRow("2026-01-03")]),
      context(),
      2,
    );

    expect(model.state).toBe("invalid");
    expect(model.spanDays).toBe(3);
    expect(model.dates).toEqual([]);
    expect(model.candles).toEqual([]);
    expect(model.fatalReasonCodes).toContain("CHART_CAPACITY_EXCEEDED");
  });

  it("rejects 7,301 daily inputs without spread-argument overflow or lattice allocation", () => {
    const start = Date.UTC(2000, 0, 1);
    const rows = Array.from({ length: 7_301 }, (_, index) =>
      presentRow(new Date(start + index * 86_400_000).toISOString().slice(0, 10)),
    );

    const model = buildObservatoryKlineModel(selectedSeries(rows), context());

    expect(model.state).toBe("invalid");
    expect(model.spanDays).toBe(7_301);
    expect(model.dates).toEqual([]);
    expect(model.candles).toEqual([]);
    expect(model.fatalReasonCodes).toContain("CHART_CAPACITY_EXCEEDED");
  });

  it("distinguishes confirmed empty input from supplied data with zero valid candles", () => {
    const empty = buildObservatoryKlineModel(selectedSeries([]), context());
    const unavailable = buildObservatoryKlineModel(
      selectedSeries([presentRow("2026-01-01", { availability_state: "missing" })]),
      context(),
    );

    expect(empty.state).toBe("empty");
    expect(empty.fatalReasonCodes).toEqual([]);
    expect(unavailable.state).toBe("invalid");
    expect(unavailable.fatalReasonCodes).toContain("NO_VALID_CANDLES");
    expect(reasons(unavailable.diagnostics, "2026-01-01")).toContain("AVAILABILITY_MISSING");
  });

  it("treats an omitted rows array as an invalid payload rather than an empty result", () => {
    const model = buildObservatoryKlineModel(selectedSeries(undefined), context());

    expect(model.state).toBe("invalid");
    expect(model.fatalReasonCodes).toContain("SERIES_ROWS_UNAVAILABLE");
  });

  it.each([
    ["null series", null as unknown as ObsSingleSeries, context()],
    ["null row", { ...selectedSeries([]), rows: [null] } as unknown as ObsSingleSeries, context()],
    [
      "non-array exclusions",
      selectedSeries([presentRow("2026-01-01")]),
      { ...context(), excluded_dates: "invalid" } as unknown as ObsContext,
    ],
    [
      "null exclusion",
      selectedSeries([presentRow("2026-01-01")]),
      { ...context(), excluded_dates: [null] } as unknown as ObsContext,
    ],
  ])("contains runtime payload-shape corruption for %s", (_name, series, activeContext) => {
    expect(() => buildObservatoryKlineModel(series, activeContext)).not.toThrow();
    const model = buildObservatoryKlineModel(series, activeContext);
    expect(model.state).toBe("invalid");
    expect(model.fatalReasonCodes).toEqual(
      expect.arrayContaining([
        expect.stringMatching(
          /CHART_DATA_REJECTED|ROW_SHAPE_INVALID|EXCLUDED_DATES_UNAVAILABLE|EXCLUSION_SHAPE_INVALID/,
        ),
      ]),
    );
  });
});
