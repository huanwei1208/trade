import { useState } from "react";

import type { DecisionExplanation, IndicatorMode, KlineBar, KlineResponse, WorldState } from "../lib/api";
import { clamp, closestBarIndex, linePath } from "../lib/chart";
import { formatCompactNumber, formatDate, formatScore } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { classNames } from "../lib/ui";
import { EmptyState } from "./EmptyState";

type SymbolChartProps = {
  kline?: KlineResponse | null;
  explanation?: DecisionExplanation | null;
  state?: WorldState | null;
  activeEvidenceSource?: string | null;
  invalidationFocused?: boolean;
  indicatorMode?: IndicatorMode;
  showEvents?: boolean;
  showBeliefOverlay?: boolean;
  onMarkerHover: (value: string | null) => void;
  onOpenReadiness?: () => void;
  onOpenRecovery?: () => void;
};

function latest(values: Array<number | undefined>) {
  return [...values].reverse().find((value) => value !== undefined && value !== null);
}

function ChartEmptyState({
  kline,
  explanation,
  onOpenReadiness,
  onOpenRecovery,
}: {
  kline?: KlineResponse | null;
  explanation?: DecisionExplanation | null;
  onOpenReadiness?: () => void;
  onOpenRecovery?: () => void;
}) {
  const { t } = useI18n();
  const hasExplanation = Boolean(explanation && (explanation.thesis || explanation.action));
  const isReadinessConstrained = Boolean(
    explanation?.input_warnings?.length ||
    explanation?.warnings?.some((w) => String(w).toLowerCase().includes("readiness") || String(w).toLowerCase().includes("missing"))
  );

  let body = t("symbol.chartEmptyCopy");
  if (hasExplanation && isReadinessConstrained) {
    body = t("symbol.chartEmptyReadinessCause");
  } else if (hasExplanation) {
    body = t("symbol.chartEmptyExplanationAvailable");
  }

  return (
    <div className="symbol-chart symbol-chart--empty">
      <EmptyState
        title={t("symbol.chartEmpty")}
        body={body}
        action={
          (onOpenReadiness || onOpenRecovery) ? (
            <div className="state-card__button-row">
              {onOpenReadiness && (
                <button type="button" className="button button--ghost" onClick={onOpenReadiness}>
                  {t("symbol.inspectDayReadiness")}
                </button>
              )}
              {onOpenRecovery && (
                <button type="button" className="button button--ghost" onClick={onOpenRecovery}>
                  {t("symbol.openRecovery")}
                </button>
              )}
            </div>
          ) : undefined
        }
      />
    </div>
  );
}

export function SymbolChart({
  kline,
  explanation,
  state,
  activeEvidenceSource,
  invalidationFocused,
  indicatorMode = "rsi",
  showEvents = true,
  showBeliefOverlay = false,
  onMarkerHover,
  onOpenReadiness,
  onOpenRecovery,
}: SymbolChartProps) {
  const { locale, t } = useI18n();

  const bars = (kline?.ohlcv || []).filter((bar): bar is Required<KlineBar> => Boolean(bar.date));
  const sortedBars = [...bars].sort((a, b) => String(a.date).localeCompare(String(b.date)));

  if (!sortedBars.length) {
    return <ChartEmptyState kline={kline} explanation={explanation} onOpenReadiness={onOpenReadiness} onOpenRecovery={onOpenRecovery} />;
  }

  // ── Chart dimensions ────────────────────────────────────────────────────────
  const width = 880;
  const hasIndicator = indicatorMode !== "none" && indicatorMode !== undefined;
  const indicatorHeight = hasIndicator ? 60 : 0;
  const volumeHeight = 64;
  const volumeGap = 6;
  const indicatorGap = hasIndicator ? 6 : 0;

  const left = 52;
  const right = width - 24;
  const priceTop = 30;
  const priceHeight = 260;
  const volumeTop = priceTop + priceHeight + volumeGap;
  const indicatorTop = volumeTop + volumeHeight + indicatorGap;
  const totalHeight = indicatorTop + indicatorHeight + (hasIndicator ? 10 : 0);
  const stripTop = hasIndicator ? indicatorTop + indicatorHeight + 4 : volumeTop + volumeHeight + 4;
  const height = stripTop + 20;

  const chartWidth = right - left;
  const candleStep = chartWidth / Math.max(1, sortedBars.length);
  const candleWidth = Math.max(3, candleStep * 0.6);

  // ── Price range ─────────────────────────────────────────────────────────────
  const lows = sortedBars.map((bar) => Number(bar.low || 0));
  const highs = sortedBars.map((bar) => Number(bar.high || 0));
  const closes = sortedBars.map((bar) => Number(bar.close || 0));
  const volumes = sortedBars.map((bar) => Number(bar.volume || 0));
  const minPrice = Math.min(...lows) * 0.998;
  const maxPrice = Math.max(...highs) * 1.002;
  const priceRange = maxPrice - minPrice || 1;
  const maxVolume = Math.max(...volumes, 1);

  const priceY = (value: number) => priceTop + (1 - (value - minPrice) / priceRange) * priceHeight;
  const volumeY = (value: number) => volumeTop + volumeHeight - (value / maxVolume) * volumeHeight;

  // ── MA paths ─────────────────────────────────────────────────────────────────
  function buildMaPath(maKey: keyof KlineBar): string {
    const points: Array<{ x: number; y: number }> = [];
    sortedBars.forEach((bar, index) => {
      const v = (bar as Record<string, unknown>)[maKey];
      if (typeof v === "number" && v > 0) {
        points.push({ x: left + index * candleStep + candleStep / 2, y: priceY(v) });
      }
    });
    return points.length > 1 ? linePath(points) : "";
  }

  const ma5Path = buildMaPath("ma5");
  const ma10Path = buildMaPath("ma10");
  const ma20Path = buildMaPath("ma20");
  const ma60Path = buildMaPath("ma60");

  // ── Indicator subpanel ───────────────────────────────────────────────────────
  // RSI
  const rsiValues = sortedBars.map((bar) => bar.rsi14);
  const rsiPath = (() => {
    const pts: Array<{ x: number; y: number }> = [];
    sortedBars.forEach((bar, i) => {
      const v = bar.rsi14;
      if (typeof v === "number") {
        pts.push({ x: left + i * candleStep + candleStep / 2, y: indicatorTop + (1 - v / 100) * indicatorHeight });
      }
    });
    return pts.length > 1 ? linePath(pts) : "";
  })();

  // MACD
  const macdHistBars = sortedBars.map((bar, i) => {
    const hist = bar.macd_hist;
    if (hist === undefined || hist === null) return null;
    const maxHist = Math.max(...sortedBars.map((b) => Math.abs(b.macd_hist ?? 0)), 0.001);
    const barH = Math.abs(hist) / maxHist * (indicatorHeight / 2 - 4);
    const midY = indicatorTop + indicatorHeight / 2;
    return {
      x: left + i * candleStep + candleStep / 2 - candleWidth / 2,
      y: hist >= 0 ? midY - barH : midY,
      h: Math.max(1, barH),
      positive: hist >= 0,
    };
  });

  // KDJ
  const kdjKPath = (() => {
    const pts = sortedBars
      .map((bar, i) => bar.kdj_k !== undefined ? { x: left + i * candleStep + candleStep / 2, y: indicatorTop + (1 - (bar.kdj_k ?? 50) / 100) * indicatorHeight } : null)
      .filter((p): p is { x: number; y: number } => p !== null);
    return pts.length > 1 ? linePath(pts) : "";
  })();
  const kdjDPath = (() => {
    const pts = sortedBars
      .map((bar, i) => bar.kdj_d !== undefined ? { x: left + i * candleStep + candleStep / 2, y: indicatorTop + (1 - (bar.kdj_d ?? 50) / 100) * indicatorHeight } : null)
      .filter((p): p is { x: number; y: number } => p !== null);
    return pts.length > 1 ? linePath(pts) : "";
  })();

  // ── Event markers ─────────────────────────────────────────────────────────────
  const eventHighlight = String(activeEvidenceSource || "").toLowerCase().includes("event");
  const markerRows = (kline?.event_markers || []).slice(-14);

  // ── Belief overlay ─────────────────────────────────────────────────────────────
  const beliefPoints = (kline?.belief_overlay || [])
    .filter((point) => point.date)
    .map((point) => ({
      date: point.date as string,
      mu: Number(point.mu || 0),
      sigma: Number(point.sigma || 0),
    }));
  const beliefValues = beliefPoints.flatMap((point) => [point.mu - point.sigma, point.mu + point.sigma]);
  const beliefMin = beliefValues.length ? Math.min(...beliefValues) : -0.5;
  const beliefMax = beliefValues.length ? Math.max(...beliefValues) : 0.5;
  const beliefRange = beliefMax - beliefMin || 1;
  const beliefY = (value: number) => priceTop + priceHeight - ((value - beliefMin) / beliefRange) * priceHeight;

  const beliefLine = beliefPoints
    .map((point) => {
      const index = closestBarIndex(sortedBars, point.date);
      if (index < 0) return null;
      return { x: left + index * candleStep + candleStep / 2, y: beliefY(point.mu) };
    })
    .filter((p): p is { x: number; y: number } => p !== null);
  const beliefUpper = beliefPoints
    .map((point) => {
      const index = closestBarIndex(sortedBars, point.date);
      if (index < 0) return null;
      return { x: left + index * candleStep + candleStep / 2, y: beliefY(point.mu + point.sigma) };
    })
    .filter((p): p is { x: number; y: number } => p !== null);
  const beliefLower = beliefPoints
    .map((point) => {
      const index = closestBarIndex(sortedBars, point.date);
      if (index < 0) return null;
      return { x: left + index * candleStep + candleStep / 2, y: beliefY(point.mu - point.sigma) };
    })
    .filter((p): p is { x: number; y: number } => p !== null);
  const beliefArea =
    beliefUpper.length && beliefLower.length
      ? `${linePath(beliefUpper)} ${linePath([...beliefLower].reverse()).replace(/^M/, "L")} Z`
      : "";

  const actionTone = String(explanation?.action || kline?.action?.action || "NO_ACTION").toUpperCase();
  const lastBar = sortedBars[sortedBars.length - 1];

  return (
    <div className="symbol-chart">
      <svg viewBox={`0 0 ${width} ${height}`} className="symbol-chart__svg" role="img" aria-label="Price chart">
        <rect x={0} y={0} width={width} height={height} rx={20} className="symbol-chart__background" />

        {/* Decision zone overlay */}
        <rect
          x={left} y={priceTop} width={chartWidth} height={priceHeight}
          fill={
            actionTone === "ADD" ? "rgba(40,200,100,0.07)" :
            actionTone === "PROBE" ? "rgba(57,192,255,0.07)" :
            actionTone === "WATCH" ? "rgba(255,180,50,0.07)" :
            "rgba(108,124,255,0.05)"
          }
          rx={8}
        />

        {/* Price grid lines */}
        {Array.from({ length: 5 }).map((_, index) => {
          const y = priceTop + (index / 4) * priceHeight;
          const price = maxPrice - (index / 4) * priceRange;
          return (
            <g key={index}>
              <line x1={left} x2={right} y1={y} y2={y} className="symbol-chart__grid" />
              <text x={left - 4} y={y + 4} className="symbol-chart__axis-label" textAnchor="end">{formatScore(price, 2)}</text>
            </g>
          );
        })}

        {/* Candles */}
        {sortedBars.map((bar, index) => {
          const x = left + index * candleStep + candleStep / 2;
          const openY = priceY(Number(bar.open || 0));
          const closeY = priceY(Number(bar.close || 0));
          const highY = priceY(Number(bar.high || 0));
          const lowY = priceY(Number(bar.low || 0));
          const up = Number(bar.close || 0) >= Number(bar.open || 0);
          return (
            <g key={bar.date}>
              <line x1={x} x2={x} y1={highY} y2={lowY} className={classNames("symbol-chart__wick", up ? "is-up" : "is-down")} />
              <rect
                x={x - candleWidth / 2}
                y={Math.min(openY, closeY)}
                width={candleWidth}
                height={Math.max(2, Math.abs(closeY - openY))}
                rx={2}
                className={classNames("symbol-chart__candle", up ? "is-up" : "is-down")}
              />
            </g>
          );
        })}

        {/* MA lines */}
        {ma60Path && <path d={ma60Path} className="symbol-chart__ma symbol-chart__ma--60" />}
        {ma20Path && <path d={ma20Path} className="symbol-chart__ma symbol-chart__ma--20" />}
        {ma10Path && <path d={ma10Path} className="symbol-chart__ma symbol-chart__ma--10" />}
        {ma5Path && <path d={ma5Path} className="symbol-chart__ma symbol-chart__ma--5" />}

        {/* Belief overlay (optional, advanced) */}
        {showBeliefOverlay && beliefArea && <path d={beliefArea} className="symbol-chart__belief-area" />}
        {showBeliefOverlay && beliefLine.length > 1 && <path d={linePath(beliefLine)} className="symbol-chart__belief-line" />}

        {/* Event markers */}
        {showEvents && markerRows.map((marker, index) => {
          const barIndex = closestBarIndex(sortedBars, marker.date);
          if (barIndex < 0) return null;
          const x = left + barIndex * candleStep + candleStep / 2;
          const y = clamp(priceY(Number(sortedBars[barIndex].high || sortedBars[barIndex].close || 0)) - 14 - (index % 3) * 10, priceTop + 16, priceTop + priceHeight - 40);
          const tone = Number(marker.kg_score || 0) >= 0 ? "positive" : "negative";
          const key = `${marker.date}-${marker.event_type}-${index}`;
          return (
            <g
              key={key}
              className={classNames("symbol-chart__marker", tone === "positive" ? "is-positive" : "is-negative", eventHighlight && "is-emphasized")}
              onMouseEnter={() => onMarkerHover(key)}
              onMouseLeave={() => onMarkerHover(null)}
            >
              <circle cx={x} cy={y} r={5} />
              <text x={x + 8} y={y + 4}>{marker.event_type}</text>
            </g>
          );
        })}

        {/* MA legend */}
        <g className="symbol-chart__legend">
          {ma5Path && <text x={left} y={20} className="symbol-chart__legend-ma5">MA5</text>}
          {ma10Path && <text x={left + 36} y={20} className="symbol-chart__legend-ma10">MA10</text>}
          {ma20Path && <text x={left + 80} y={20} className="symbol-chart__legend-ma20">MA20</text>}
          {ma60Path && <text x={left + 130} y={20} className="symbol-chart__legend-ma60">MA60</text>}
          <text x={right - 180} y={20}>
            {t("symbol.chartLegend.lastClose")} {formatScore(latest(closes), 2)}
          </text>
        </g>

        {/* Volume section divider */}
        <line x1={left} x2={right} y1={volumeTop} y2={volumeTop} className="symbol-chart__panel-divider" />

        {/* Volume bars */}
        {sortedBars.map((bar, index) => {
          const x = left + index * candleStep + candleStep / 2 - candleWidth / 2;
          const y = volumeY(Number(bar.volume || 0));
          const h = Math.max(2, volumeTop + volumeHeight - y);
          const up = Number(bar.close || 0) >= Number(bar.open || 0);
          return (
            <rect
              key={`${bar.date}-vol`}
              x={x} y={y} width={candleWidth} height={h}
              className={classNames("symbol-chart__volume", up ? "is-up" : "is-down")}
              rx={2}
            />
          );
        })}

        {/* Volume label */}
        <text x={left} y={volumeTop + 12} className="symbol-chart__panel-label">{t("symbol.chartLayer.volume")}</text>

        {/* Indicator subpanel */}
        {hasIndicator && (
          <>
            <line x1={left} x2={right} y1={indicatorTop} y2={indicatorTop} className="symbol-chart__panel-divider" />

            {/* RSI */}
            {indicatorMode === "rsi" && (
              <>
                {/* Overbought/oversold reference lines */}
                <line x1={left} x2={right}
                  y1={indicatorTop + (1 - 70 / 100) * indicatorHeight}
                  y2={indicatorTop + (1 - 70 / 100) * indicatorHeight}
                  className="symbol-chart__indicator-ref" />
                <line x1={left} x2={right}
                  y1={indicatorTop + (1 - 30 / 100) * indicatorHeight}
                  y2={indicatorTop + (1 - 30 / 100) * indicatorHeight}
                  className="symbol-chart__indicator-ref" />
                <text x={left - 4} y={indicatorTop + (1 - 70 / 100) * indicatorHeight + 4}
                  className="symbol-chart__axis-label" textAnchor="end">70</text>
                <text x={left - 4} y={indicatorTop + (1 - 30 / 100) * indicatorHeight + 4}
                  className="symbol-chart__axis-label" textAnchor="end">30</text>
                {rsiPath && <path d={rsiPath} className="symbol-chart__rsi-line" />}
                <text x={left} y={indicatorTop + 12} className="symbol-chart__panel-label">RSI14</text>
              </>
            )}

            {/* MACD */}
            {indicatorMode === "macd" && (
              <>
                <line x1={left} x2={right}
                  y1={indicatorTop + indicatorHeight / 2}
                  y2={indicatorTop + indicatorHeight / 2}
                  className="symbol-chart__indicator-ref" />
                {macdHistBars.map((bar, i) => {
                  if (!bar) return null;
                  return (
                    <rect
                      key={`macd-${i}`}
                      x={bar.x} y={bar.y} width={candleWidth} height={bar.h}
                      className={classNames("symbol-chart__macd-hist", bar.positive ? "is-positive" : "is-negative")}
                    />
                  );
                })}
                <text x={left} y={indicatorTop + 12} className="symbol-chart__panel-label">MACD</text>
              </>
            )}

            {/* KDJ */}
            {indicatorMode === "kdj" && (
              <>
                <line x1={left} x2={right}
                  y1={indicatorTop + (1 - 80 / 100) * indicatorHeight}
                  y2={indicatorTop + (1 - 80 / 100) * indicatorHeight}
                  className="symbol-chart__indicator-ref" />
                <line x1={left} x2={right}
                  y1={indicatorTop + (1 - 20 / 100) * indicatorHeight}
                  y2={indicatorTop + (1 - 20 / 100) * indicatorHeight}
                  className="symbol-chart__indicator-ref" />
                {kdjKPath && <path d={kdjKPath} className="symbol-chart__kdj-k" />}
                {kdjDPath && <path d={kdjDPath} className="symbol-chart__kdj-d" />}
                <text x={left} y={indicatorTop + 12} className="symbol-chart__panel-label">KDJ</text>
              </>
            )}
          </>
        )}

        {/* Bottom strip: market context */}
        <g className="symbol-chart__strip">
          <rect x={left} y={stripTop} width={chartWidth} height={16} rx={8} />
          {lastBar?.date && (
            <text x={left + 8} y={stripTop + 11}>
              {formatDate(lastBar.date, locale === "zh-CN" ? "zh-CN" : "en-US")}
              {" · "}{t("symbol.chartLegend.vol")} {formatCompactNumber(lastBar.volume)}
            </text>
          )}
        </g>
      </svg>
    </div>
  );
}
