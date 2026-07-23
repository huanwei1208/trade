import type { KlineBar } from "./api";

type Point = { x: number; y: number };

export function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

export function linePath(points: Point[]) {
  if (!points.length) {
    return "";
  }
  return points.map((point, index) => `${index === 0 ? "M" : "L"} ${point.x.toFixed(2)} ${point.y.toFixed(2)}`).join(" ");
}

export function areaPath(points: Point[], baseline: number) {
  if (!points.length) {
    return "";
  }
  const start = `M ${points[0].x.toFixed(2)} ${baseline.toFixed(2)}`;
  const body = points.map((point) => `L ${point.x.toFixed(2)} ${point.y.toFixed(2)}`).join(" ");
  const end = `L ${points[points.length - 1].x.toFixed(2)} ${baseline.toFixed(2)} Z`;
  return [start, body, end].join(" ");
}

export function sparklinePath(values: number[], width: number, height: number, padding = 3) {
  if (!values.length) {
    return "";
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  return values
    .map((value, index) => {
      const x = padding + (index / Math.max(1, values.length - 1)) * (width - padding * 2);
      const y = height - padding - ((value - min) / range) * (height - padding * 2);
      return `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ");
}

export function normalizeSparkline(points?: Array<{ close?: number }>) {
  return (points || [])
    .map((point) => Number(point.close || 0))
    .filter((value) => Number.isFinite(value) && value > 0);
}

export function scaleSeries(values: number[], height: number, top = 0, bottom = 0) {
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  return (value: number) => top + (1 - (value - min) / range) * (height - top - bottom);
}

export function indexByDate(bars: KlineBar[]) {
  const result = new Map<string, number>();
  bars.forEach((bar, index) => {
    if (bar.date) {
      result.set(bar.date, index);
    }
  });
  return result;
}

export function closestBarIndex(bars: KlineBar[], targetDate?: string | null) {
  if (!targetDate || !bars.length) {
    return -1;
  }
  const direct = bars.findIndex((bar) => bar.date === targetDate);
  if (direct >= 0) {
    return direct;
  }
  const target = new Date(targetDate).getTime();
  if (Number.isNaN(target)) {
    return -1;
  }
  let bestIndex = -1;
  let bestDistance = Number.POSITIVE_INFINITY;
  bars.forEach((bar, index) => {
    const current = new Date(bar.date || "").getTime();
    const distance = Math.abs(current - target);
    if (!Number.isNaN(current) && distance < bestDistance) {
      bestDistance = distance;
      bestIndex = index;
    }
  });
  return bestIndex;
}

// ── Observatory chart helpers (WP4) ──────────────────────────────────────────
// Extends the existing SVG helpers (frozen decision #2: no charting library).

export type ScaleMode = "linear" | "log";

/**
 * Build a value->y mapping across a fixed [min,max] domain. Unlike scaleSeries
 * (which derives the domain from a single value array), this takes an explicit
 * domain so multiple independent composite layers share ONE y-axis without any
 * one layer redefining the scale. Supports log scale for long-period price.
 */
export function makeValueScale(
  min: number,
  max: number,
  height: number,
  mode: ScaleMode = "linear",
  top = 0,
  bottom = 0,
) {
  if (mode === "log") {
    const safeMin = Math.max(min, 1e-9);
    const safeMax = Math.max(max, safeMin * (1 + 1e-6));
    const logMin = Math.log10(safeMin);
    const logMax = Math.log10(safeMax);
    const logRange = logMax - logMin || 1;
    return (value: number) => {
      const v = Math.max(value, safeMin);
      return top + (1 - (Math.log10(v) - logMin) / logRange) * (height - top - bottom);
    };
  }
  const range = max - min || 1;
  return (value: number) => top + (1 - (value - min) / range) * (height - top - bottom);
}

/** Map an index in [0, count-1] to an x coordinate across [left, width-right]. */
export function makeIndexScale(count: number, width: number, left = 0, right = 0) {
  const usable = width - left - right;
  return (index: number) => left + (count <= 1 ? usable / 2 : (index / (count - 1)) * usable);
}

/**
 * Turn broken segments (arrays of {index, value}) into an array of SVG path
 * strings — one per segment — so a gap between segments produces a REAL break in
 * the line (no interpolation across missing dates).
 */
export function segmentedLinePaths(
  segments: Array<Array<{ index: number; value: number }>>,
  xScale: (index: number) => number,
  yScale: (value: number) => number,
): string[] {
  return segments
    .filter((seg) => seg.length > 0)
    .map((seg) =>
      seg
        .map((point, i) => `${i === 0 ? "M" : "L"} ${xScale(point.index).toFixed(2)} ${yScale(point.value).toFixed(2)}`)
        .join(" "),
    );
}

/** Nice-ish domain padding so lines don't touch the frame. */
export function paddedDomain(values: number[], pad = 0.04): { min: number; max: number } {
  if (!values.length) {
    return { min: 0, max: 1 };
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || Math.abs(max) || 1;
  return { min: min - span * pad, max: max + span * pad };
}
