// Pure, DOM-free helpers for the BTC Observatory surfaces.
//
// These functions carry the load-bearing invariants that the plan and frozen
// contracts require (docs/26 §7.8, §11, §12; frozen_contracts.md):
//   - three independent composite layers (never merged into one truth),
//   - missing dates break the line (no interpolation / forward-fill),
//   - Candidate is NEVER presented as Published (persistent texture, not a badge),
//   - quarantine / revision use NON-COLOR semantics (icon + text + texture),
//   - decimal STRING prices parsed only for geometry (display keeps the string),
//   - fixed URL round-trips (page/lens/run/date/knowledge_as_of/range).
// They are unit-tested directly (Vitest) because the SVG chart cannot assert
// numerical invariants on its own.

import type {
  ObsChannel,
  ObsCompositeSeries,
  ObsExcludedDate,
  ObsLayer,
  ObsLens,
  ObsSeriesRow,
} from "./api";

export type ObservatoryResourceStatus = "idle" | "loading" | "confirmed" | "unavailable" | "failed";

export type ObservatorySafeError = {
  message: string;
  reasonCodes: string[];
  evidenceRefs: string[];
  retryable: boolean;
};

// ── Decimal handling ─────────────────────────────────────────────────────────
// Prices/volumes arrive as decimal-preserving strings. We ONLY convert to a
// number to compute chart geometry; display code should keep the original
// string to avoid float rounding divergence.

export function parseDecimal(value: string | null | undefined): number | null {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

// ── Layer extraction ─────────────────────────────────────────────────────────

export type LayerKey = "formal" | "evaluated_candidate" | "latest_observed";

export const LAYER_KEYS: LayerKey[] = ["formal", "evaluated_candidate", "latest_observed"];

export type ExtractedLayer = {
  key: LayerKey;
  present: boolean;
  channel?: string;
  rows: ObsSeriesRow[];
  excludedDates: ObsExcludedDate[];
  reasonCodes: string[];
};

/**
 * Split a composite payload into three independent layers. Each layer keeps its
 * own rows and is NEVER merged with another — overlapping dates are not averaged
 * or overwritten (invariant docs/26 §7.8).
 */
export function extractLayers(composite: ObsCompositeSeries | null | undefined): ExtractedLayer[] {
  const layers = composite?.layers;
  return LAYER_KEYS.map((key) => {
    const layer: ObsLayer = layers ? (layers as Record<string, ObsLayer>)[key] : null;
    return {
      key,
      present: Boolean(layer),
      channel: layer?.channel,
      rows: layer?.rows ?? [],
      excludedDates: layer?.context?.excluded_dates ?? [],
      reasonCodes: layer?.context?.reason_codes ?? [],
    };
  });
}

// ── Missing-break segments (no interpolation) ────────────────────────────────

export type SegmentPoint = { index: number; date: string; value: number };

/**
 * Determine whether a row is a plottable point. A row is only plottable when it
 * is explicitly `present` AND has a finite close. `missing`, `unobserved`,
 * `unknown`, or null close all break the line — we never bridge the gap.
 */
export function isPlottable(row: ObsSeriesRow): boolean {
  if (row.availability_state && row.availability_state !== "present") {
    return false;
  }
  return parseDecimal(row.close) !== null;
}

/**
 * Convert a layer's rows into contiguous segments broken at every non-plottable
 * row. Each returned segment is a run of adjacent plottable points; a gap
 * produces a new segment so the SVG line has a real break (no forward-fill).
 */
export function buildSegments(
  rows: ObsSeriesRow[],
  accessor: (row: ObsSeriesRow) => number | null = (row) => parseDecimal(row.close),
): SegmentPoint[][] {
  const segments: SegmentPoint[][] = [];
  let current: SegmentPoint[] = [];
  rows.forEach((row, index) => {
    const plottable = isPlottable(row) && accessor(row) !== null;
    if (!plottable) {
      if (current.length) {
        segments.push(current);
        current = [];
      }
      return;
    }
    current.push({ index, date: row.date ?? "", value: accessor(row) as number });
  });
  if (current.length) {
    segments.push(current);
  }
  return segments;
}

// ── Non-color semantics ──────────────────────────────────────────────────────
// Status must be conveyed by more than color (frozen a11y requirement). Each
// marker carries an icon glyph AND a text label AND a texture id.

export type NonColorMarkerKind = "quarantine" | "revision" | "missing" | "unobserved";

export type NonColorMarker = {
  kind: NonColorMarkerKind;
  icon: string; // shape glyph, distinct per kind
  label: string; // human text label
  texture: string; // SVG pattern id / css texture key
};

const MARKER_TABLE: Record<NonColorMarkerKind, Omit<NonColorMarker, "kind">> = {
  quarantine: { icon: "◇", label: "Quarantined", texture: "hatch-quarantine" },
  revision: { icon: "◆", label: "Revised", texture: "hatch-revision" },
  missing: { icon: "×", label: "Missing", texture: "hatch-missing" },
  unobserved: { icon: "·", label: "Unobserved", texture: "hatch-unobserved" },
};

/** Marker descriptors for a row. Returns every applicable non-color semantic. */
export function markersForRow(row: ObsSeriesRow): NonColorMarker[] {
  const out: NonColorMarker[] = [];
  if ((row.quality_flags ?? []).includes("quarantined")) {
    out.push({ kind: "quarantine", ...MARKER_TABLE.quarantine });
  }
  if (
    row.revision_state &&
    row.revision_state !== "unchanged" &&
    row.revision_state !== "unknown"
  ) {
    out.push({ kind: "revision", ...MARKER_TABLE.revision });
  }
  if (row.availability_state === "missing") {
    out.push({ kind: "missing", ...MARKER_TABLE.missing });
  }
  if (row.availability_state === "unobserved") {
    out.push({ kind: "unobserved", ...MARKER_TABLE.unobserved });
  }
  return out;
}

// ── Render-role visual treatment ─────────────────────────────────────────────
// The visual treatment per layer/render_role. The critical invariant is that a
// Candidate layer must never be styled as "published/solid baseline"; it always
// carries a persistent texture + watermark.

export type LayerTreatment = {
  key: LayerKey;
  stroke: "solid" | "dashed";
  texture: string | null; // non-null => persistent texture overlay
  isBaseline: boolean; // only Formal is the solid baseline
  presentedAsPublished: boolean; // MUST be false for candidate/observed
  legendLabel: string;
};

export function layerTreatment(key: LayerKey): LayerTreatment {
  switch (key) {
    case "formal":
      return {
        key,
        stroke: "solid",
        texture: null,
        isBaseline: true,
        presentedAsPublished: true,
        legendLabel: "Formal baseline",
      };
    case "evaluated_candidate":
      return {
        key,
        stroke: "dashed",
        texture: "hatch-candidate",
        isBaseline: false,
        presentedAsPublished: false,
        legendLabel: "Evaluated candidate (unpublished)",
      };
    case "latest_observed":
      return {
        key,
        stroke: "dashed",
        texture: "outline-observed",
        isBaseline: false,
        presentedAsPublished: false,
        legendLabel: "Latest observed (unpublished)",
      };
  }
}

/**
 * The formal watermark date = last plottable formal date. Everything to the
 * right is candidate/observed-only territory and must render with texture.
 */
export function formalWatermarkDate(
  composite: ObsCompositeSeries | null | undefined,
): string | null {
  const formal = extractLayers(composite).find((l) => l.key === "formal");
  if (!formal || !formal.rows.length) {
    return null;
  }
  const plottable = formal.rows.filter(isPlottable);
  if (!plottable.length) {
    return null;
  }
  return plottable[plottable.length - 1].date ?? null;
}

/**
 * Dates that appear only in the observed layer (beyond formal & candidate). Used
 * to prove the "observed-only tail" is rendered distinctly when
 * observed_watermark > formal_watermark.
 */
export function observedOnlyDates(composite: ObsCompositeSeries | null | undefined): string[] {
  const layers = extractLayers(composite);
  const formalDates = new Set(
    (layers.find((l) => l.key === "formal")?.rows ?? []).map((r) => r.date),
  );
  const candidateDates = new Set(
    (layers.find((l) => l.key === "evaluated_candidate")?.rows ?? []).map((r) => r.date),
  );
  const observed = layers.find((l) => l.key === "latest_observed")?.rows ?? [];
  return observed
    .filter((r) => r.date && !formalDates.has(r.date) && !candidateDates.has(r.date))
    .map((r) => r.date as string);
}

/** Sorted union of every date present across the three layers (shared x-axis). */
export function unionDates(composite: ObsCompositeSeries | null | undefined): string[] {
  const seen = new Set<string>();
  for (const layer of extractLayers(composite)) {
    for (const row of layer.rows) {
      if (row.date) {
        seen.add(row.date);
      }
    }
  }
  return Array.from(seen).sort();
}

const RANGE_DAYS: Record<string, number | null> = {
  "30D": 30,
  "90D": 90,
  "1Y": 365,
  All: null,
};

export const OBSERVATORY_CHART_POINT_BUDGET = 720;
export const OBSERVATORY_COVERAGE_DAY_BUDGET = 90;

export type ObservatoryWindowBounds =
  | { kind: "all" }
  | { kind: "bounded"; from: string; to: string }
  | { kind: "unavailable"; reasonCodes: string[] };

function utcDateOffset(date: string, offsetDays: number): string | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) {
    return null;
  }
  const parsed = new Date(`${date}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== date) {
    return null;
  }
  parsed.setUTCDate(parsed.getUTCDate() + offsetDays);
  return parsed.toISOString().slice(0, 10);
}

/**
 * The server owns the market watermark; the browser only derives the requested
 * display window around that supplied date. All intentionally sends no bounds.
 */
export function observatoryWindowBounds(
  marketWatermark: string | null | undefined,
  range: string,
): ObservatoryWindowBounds {
  const days = RANGE_DAYS[range];
  if (days === null) {
    return { kind: "all" };
  }
  if (days === undefined) {
    return { kind: "unavailable", reasonCodes: ["REQUESTED_RANGE_INVALID"] };
  }
  if (!marketWatermark) {
    return { kind: "unavailable", reasonCodes: ["MARKET_WATERMARK_UNAVAILABLE"] };
  }
  const from = utcDateOffset(marketWatermark, -(days - 1));
  return from
    ? { kind: "bounded", from, to: marketWatermark }
    : { kind: "unavailable", reasonCodes: ["MARKET_WATERMARK_INVALID"] };
}

/** Selects evenly distributed display dates while preserving both endpoints. */
export function downsampleDisplayDates(
  sortedDates: string[],
  budget = OBSERVATORY_CHART_POINT_BUDGET,
): string[] {
  if (budget < 2 || sortedDates.length <= budget) {
    return sortedDates;
  }
  const selected: string[] = [];
  for (let index = 0; index < budget; index += 1) {
    const sourceIndex = Math.round((index * (sortedDates.length - 1)) / (budget - 1));
    const date = sortedDates[sourceIndex];
    if (date && selected[selected.length - 1] !== date) {
      selected.push(date);
    }
  }
  return selected;
}

/**
 * Bounds one layer's SVG geometry without inventing a bridge across a missing
 * row. For long data with gaps, each sampled run gets a representative gap row
 * so `buildSegments` continues to emit separate paths.
 */
export function downsampleSeriesRows(
  rows: ObsSeriesRow[],
  budget = OBSERVATORY_CHART_POINT_BUDGET,
): ObsSeriesRow[] {
  if (rows.length <= budget || budget < 3) {
    return rows.slice(0, Math.max(0, budget));
  }

  const hasGap = rows.some((row) => !isPlottable(row));
  const pointBudget = hasGap ? Math.floor((budget + 1) / 2) : budget;
  const selectedIndexes = new Set<number>();
  for (let position = 0; position < pointBudget; position += 1) {
    selectedIndexes.add(Math.round((position * (rows.length - 1)) / (pointBudget - 1)));
  }

  const displayed: ObsSeriesRow[] = [];
  let previousIndex: number | null = null;
  for (const index of [...selectedIndexes].sort((left, right) => left - right)) {
    if (previousIndex !== null) {
      const gap = rows.slice(previousIndex + 1, index).find((row) => !isPlottable(row));
      if (gap) {
        displayed.push(gap);
      }
    }
    displayed.push(rows[index]);
    previousIndex = index;
  }
  return displayed.slice(0, budget);
}

/**
 * Window a sorted date axis to the trailing N calendar days for a range. "All"
 * returns the axis unchanged. Uses the last date as the anchor so the window is
 * deterministic regardless of wall-clock time.
 */
export function applyRangeWindow(sortedDates: string[], range: string): string[] {
  const days = RANGE_DAYS[range];
  if (!days || !sortedDates.length) {
    return sortedDates;
  }
  const anchor = new Date(`${sortedDates[sortedDates.length - 1]}T00:00:00Z`).getTime();
  if (Number.isNaN(anchor)) {
    return sortedDates;
  }
  const cutoff = anchor - days * 24 * 60 * 60 * 1000;
  return sortedDates.filter((d) => {
    const t = new Date(`${d}T00:00:00Z`).getTime();
    return Number.isNaN(t) ? true : t >= cutoff;
  });
}

/**
 * Candidate rows that would be mis-presented as Published. This MUST always be
 * empty: a candidate row is only "published-looking" if its render_role claims a
 * formal baseline treatment, which the resolver must never emit. The chart uses
 * this as a defensive assertion surface for tests.
 */
export function candidateRowsRenderedAsPublished(
  composite: ObsCompositeSeries | null | undefined,
): ObsSeriesRow[] {
  const candidate = extractLayers(composite).find((l) => l.key === "evaluated_candidate");
  if (!candidate) {
    return [];
  }
  return candidate.rows.filter((r) => r.render_role === "formal_baseline");
}

// ── Return / drawdown display (read from metrics, do NOT recompute formal) ────
// The plan forbids recomputing formal metrics in the browser. These helpers only
// read decimal strings already present on the series metrics/context. When the
// backend has not supplied a metric we return null (honest "unknown"), never 0.

export function readMetricString(
  metrics: Record<string, unknown> | undefined,
  key: string,
): string | null {
  if (!metrics) {
    return null;
  }
  const value = metrics[key];
  if (value === null || value === undefined) {
    return null;
  }
  return String(value);
}

// ── Fixed URL serialization ──────────────────────────────────────────────────
// The observatory context (page/lens/run/date/knowledge_as_of/range/channel)
// must serialize into query params and restore on refresh (docs/26 §14.2).

export type ObservatoryUrlState = {
  lens: ObsLens;
  channel: ObsChannel;
  knowledgeAsOf: string; // "latest" or an RFC3339 / date string
  range: string; // "30D" | "90D" | "1Y" | "All"
  runId?: string | null;
  compareRunId?: string | null;
  date?: string | null;
};

export const DEFAULT_OBS_URL_STATE: ObservatoryUrlState = {
  lens: "overview",
  channel: "observed",
  knowledgeAsOf: "latest",
  range: "90D",
  runId: null,
  compareRunId: null,
  date: null,
};

const OBS_LENSES: ObsLens[] = ["overview", "trust", "runs", "research"];
const OBS_CHANNELS: ObsChannel[] = ["formal", "evaluated_candidate", "observed"];
const OBS_RANGES = ["30D", "90D", "1Y", "All"];

export function serializeObservatoryState(state: ObservatoryUrlState): URLSearchParams {
  const params = new URLSearchParams();
  params.set("obsLens", state.lens);
  params.set("obsChannel", state.channel);
  if (state.knowledgeAsOf && state.knowledgeAsOf !== "latest") {
    params.set("knowledgeAsOf", state.knowledgeAsOf);
  }
  if (state.range && state.range !== DEFAULT_OBS_URL_STATE.range) {
    params.set("obsRange", state.range);
  }
  if (state.runId) {
    params.set("obsRun", state.runId);
  }
  if (state.compareRunId) {
    params.set("obsCompare", state.compareRunId);
  }
  if (state.date) {
    params.set("obsDate", state.date);
  }
  return params;
}

export function deserializeObservatoryState(params: URLSearchParams): ObservatoryUrlState {
  const lens = params.get("obsLens");
  const channel = params.get("obsChannel");
  const range = params.get("obsRange");
  return {
    lens:
      lens && OBS_LENSES.includes(lens as ObsLens) ? (lens as ObsLens) : DEFAULT_OBS_URL_STATE.lens,
    channel:
      channel && OBS_CHANNELS.includes(channel as ObsChannel)
        ? (channel as ObsChannel)
        : DEFAULT_OBS_URL_STATE.channel,
    knowledgeAsOf: params.get("knowledgeAsOf") || "latest",
    range: range && OBS_RANGES.includes(range) ? range : DEFAULT_OBS_URL_STATE.range,
    runId: params.get("obsRun"),
    compareRunId: params.get("obsCompare"),
    date: params.get("obsDate"),
  };
}

/** True when the observatory owns the current URL (an obsLens param is present). */
export function urlHasObservatory(params: URLSearchParams): boolean {
  return params.has("obsLens");
}

// ── Purpose fitness helpers ──────────────────────────────────────────────────

export function purposeTone(
  status: string | undefined,
  allowed: boolean | undefined,
): "ok" | "warn" | "err" | "muted" {
  if (allowed) {
    return "ok";
  }
  const s = (status || "").toLowerCase();
  if (s.includes("block") || s.includes("invalid")) {
    return "err";
  }
  if (s.includes("warn") || s.includes("degrad") || s.includes("constrain")) {
    return "warn";
  }
  return "muted";
}

// ── Deterministic "what changed" (rule-based, no LLM) ────────────────────────
// Builds a structured change summary from context findings/watermarks. Every
// entry links to evidence; nothing is generated by a model (docs/26 §11.4).

export type WhatChangedEntry = {
  kind:
    | "added_dates"
    | "removed_dates"
    | "revised_dates"
    | "quarantined_dates"
    | "watermark"
    | "formal_move";
  label: string;
  detail: string;
  evidenceRefs: string[];
};

export function buildWhatChanged(
  composite: ObsCompositeSeries | null | undefined,
  excludedDates: ObsExcludedDate[] = [],
): WhatChangedEntry[] {
  const entries: WhatChangedEntry[] = [];
  const layers = extractLayers(composite);
  const observed = layers.find((l) => l.key === "latest_observed");

  const observedOnly = observedOnlyDates(composite);
  if (observedOnly.length) {
    entries.push({
      kind: "added_dates",
      label: `${observedOnly.length} newly observed date(s)`,
      detail: `${observedOnly[0]} … ${observedOnly[observedOnly.length - 1]} present in observed but not in formal baseline`,
      evidenceRefs: observed?.channel ? [`channel:${observed.channel}`] : [],
    });
  }

  const revised = (observed?.rows ?? []).filter(
    (r) => r.revision_state && r.revision_state !== "unchanged" && r.revision_state !== "unknown",
  );
  if (revised.length) {
    entries.push({
      kind: "revised_dates",
      label: `${revised.length} revised date(s)`,
      detail: revised
        .slice(0, 5)
        .map((r) => `${r.date} (${r.revision_state})`)
        .join(", "),
      evidenceRefs: revised.map((r) => r.source_run_id || "").filter(Boolean),
    });
  }

  const quarantined = new Map<string, string[]>();
  for (const row of observed?.rows ?? []) {
    if ((row.quality_flags ?? []).includes("quarantined") && row.date) {
      quarantined.set(row.date, row.source_run_id ? [row.source_run_id] : []);
    }
  }
  for (const excludedDate of excludedDates) {
    if (excludedDate.date) {
      quarantined.set(excludedDate.date, excludedDate.evidence_refs ?? []);
    }
  }
  if (quarantined.size) {
    const dates = Array.from(quarantined.keys()).sort();
    entries.push({
      kind: "quarantined_dates",
      label: `${dates.length} quarantined date(s)`,
      detail: dates.slice(0, 5).join(", "),
      evidenceRefs: dates.flatMap((date) => quarantined.get(date) ?? []).filter(Boolean),
    });
  }

  const formalWatermark = formalWatermarkDate(composite);
  const observedWatermark = observed?.rows?.length
    ? (observed.rows.filter(isPlottable).slice(-1)[0]?.date ?? null)
    : null;
  if (formalWatermark && observedWatermark && observedWatermark > formalWatermark) {
    entries.push({
      kind: "watermark",
      label: "Observed ahead of formal",
      detail: `observed watermark ${observedWatermark} > formal watermark ${formalWatermark}`,
      evidenceRefs: [],
    });
  }

  return entries;
}
