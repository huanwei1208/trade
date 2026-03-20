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
