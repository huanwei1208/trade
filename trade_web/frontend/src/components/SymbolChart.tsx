import { useState } from "react";

import type { DecisionExplanation, KlineBar, KlineResponse, WorldState } from "../lib/api";
import { areaPath, clamp, closestBarIndex, linePath } from "../lib/chart";
import { formatCompactNumber, formatDate, formatScore } from "../lib/format";
import { classNames } from "../lib/ui";
import { EmptyState } from "./EmptyState";

type SymbolChartProps = {
  kline?: KlineResponse | null;
  explanation?: DecisionExplanation | null;
  state?: WorldState | null;
  activeEvidenceSource?: string | null;
  invalidationFocused?: boolean;
  onMarkerHover: (value: string | null) => void;
};

type LayerState = {
  volume: boolean;
  events: boolean;
  belief: boolean;
  zones: boolean;
};

function latest(values: Array<number | undefined>) {
  return [...values].reverse().find((value) => value !== undefined && value !== null);
}

export function SymbolChart({ kline, explanation, state, activeEvidenceSource, invalidationFocused, onMarkerHover }: SymbolChartProps) {
  const [layers, setLayers] = useState<LayerState>({
    volume: true,
    events: true,
    belief: true,
    zones: true,
  });

  const bars = (kline?.ohlcv || []).filter((bar): bar is Required<KlineBar> => Boolean(bar.date));

  if (!bars.length) {
    return (
      <div className="symbol-chart symbol-chart--empty">
        <EmptyState title="No chart context" body="Historical OHLCV is not available for this symbol yet." />
      </div>
    );
  }

  const width = 880;
  const height = 520;
  const left = 48;
  const right = width - 24;
  const priceTop = 36;
  const priceHeight = 280;
  const volumeTop = 340;
  const volumeHeight = 76;
  const beliefTop = 432;
  const beliefHeight = 48;
  const stripTop = 492;
  const chartWidth = right - left;
  const candleStep = chartWidth / Math.max(1, bars.length);
  const candleWidth = Math.max(4, candleStep * 0.62);

  const lows = bars.map((bar) => Number(bar.low || 0));
  const highs = bars.map((bar) => Number(bar.high || 0));
  const closes = bars.map((bar) => Number(bar.close || 0));
  const volumes = bars.map((bar) => Number(bar.volume || 0));
  const minPrice = Math.min(...lows);
  const maxPrice = Math.max(...highs);
  const priceRange = maxPrice - minPrice || 1;
  const maxVolume = Math.max(...volumes, 1);

  const priceY = (value: number) => priceTop + (1 - (value - minPrice) / priceRange) * priceHeight;
  const volumeY = (value: number) => volumeTop + volumeHeight - (value / maxVolume) * volumeHeight;

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
  const beliefY = (value: number) => beliefTop + beliefHeight - ((value - beliefMin) / beliefRange) * beliefHeight;

  const beliefLine = beliefPoints
    .map((point) => {
      const index = closestBarIndex(bars, point.date);
      if (index < 0) {
        return null;
      }
      return { x: left + index * candleStep + candleStep / 2, y: beliefY(point.mu) };
    })
    .filter((point): point is { x: number; y: number } => Boolean(point));
  const beliefUpper = beliefPoints
    .map((point) => {
      const index = closestBarIndex(bars, point.date);
      if (index < 0) {
        return null;
      }
      return { x: left + index * candleStep + candleStep / 2, y: beliefY(point.mu + point.sigma) };
    })
    .filter((point): point is { x: number; y: number } => Boolean(point));
  const beliefLower = beliefPoints
    .map((point) => {
      const index = closestBarIndex(bars, point.date);
      if (index < 0) {
        return null;
      }
      return { x: left + index * candleStep + candleStep / 2, y: beliefY(point.mu - point.sigma) };
    })
    .filter((point): point is { x: number; y: number } => Boolean(point));
  const beliefArea = beliefUpper.length && beliefLower.length ? `${linePath(beliefUpper)} ${linePath([...beliefLower].reverse()).replace(/^M/, "L")} Z` : "";

  const actionTone = String(explanation?.action || kline?.action?.action || "NO_ACTION").toUpperCase();
  const eventHighlight = String(activeEvidenceSource || "").toLowerCase().includes("event");
  const markerRows = (kline?.event_markers || []).slice(-14);

  return (
    <div className="symbol-chart">
      <div className="symbol-chart__toolbar">
        {(["volume", "events", "belief", "zones"] as Array<keyof LayerState>).map((key) => (
          <button
            type="button"
            key={key}
            className={classNames("toggle-chip", layers[key] && "is-active")}
            onClick={() => setLayers((current) => ({ ...current, [key]: !current[key] }))}
          >
            {key}
          </button>
        ))}
      </div>

      <svg viewBox={`0 0 ${width} ${height}`} className="symbol-chart__svg" role="img" aria-label="Price and evidence chart">
        <defs>
          <linearGradient id="decisionOverlay" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor={actionTone === "ADD" ? "rgba(40, 200, 100, 0.18)" : actionTone === "PROBE" ? "rgba(57, 192, 255, 0.18)" : actionTone === "WATCH" ? "rgba(255, 180, 50, 0.16)" : "rgba(108, 124, 255, 0.12)"} />
            <stop offset="100%" stopColor="rgba(0, 0, 0, 0)" />
          </linearGradient>
        </defs>

        <rect x={0} y={0} width={width} height={height} rx={20} className="symbol-chart__background" />
        {layers.zones && <rect x={left} y={priceTop} width={chartWidth} height={priceHeight} fill="url(#decisionOverlay)" rx={16} />}
        {layers.zones && (
          <rect
            x={left}
            y={priceTop + priceHeight - 56}
            width={chartWidth}
            height={56}
            rx={12}
            className={classNames("symbol-chart__invalidation-zone", invalidationFocused && "is-focused")}
          />
        )}

        {Array.from({ length: 5 }).map((_, index) => {
          const y = priceTop + (index / 4) * priceHeight;
          return <line key={index} x1={left} x2={right} y1={y} y2={y} className="symbol-chart__grid" />;
        })}

        {bars.map((bar, index) => {
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
                rx={4}
                className={classNames("symbol-chart__candle", up ? "is-up" : "is-down")}
              />
            </g>
          );
        })}

        {layers.volume &&
          bars.map((bar, index) => {
            const x = left + index * candleStep + candleStep / 2 - candleWidth / 2;
            const y = volumeY(Number(bar.volume || 0));
            const heightValue = Math.max(3, volumeTop + volumeHeight - y);
            return <rect key={`${bar.date}-volume`} x={x} y={y} width={candleWidth} height={heightValue} className="symbol-chart__volume" rx={4} />;
          })}

        {layers.belief && beliefArea && <path d={beliefArea} className="symbol-chart__belief-area" />}
        {layers.belief && beliefLine.length > 1 && <path d={linePath(beliefLine)} className="symbol-chart__belief-line" />}

        {layers.events &&
          markerRows.map((marker, index) => {
            const barIndex = closestBarIndex(bars, marker.date);
            if (barIndex < 0) {
              return null;
            }
            const x = left + barIndex * candleStep + candleStep / 2;
            const y = clamp(priceY(Number(bars[barIndex].high || bars[barIndex].close || 0)) - 14 - (index % 3) * 10, priceTop + 16, priceTop + priceHeight - 72);
            const tone = Number(marker.kg_score || 0) >= 0 ? "positive" : "negative";
            const key = `${marker.date}-${marker.event_type}-${index}`;
            return (
              <g
                key={key}
                className={classNames("symbol-chart__marker", tone === "positive" ? "is-positive" : "is-negative", eventHighlight && "is-emphasized")}
                onMouseEnter={() => onMarkerHover(key)}
                onMouseLeave={() => onMarkerHover(null)}
              >
                <circle cx={x} cy={y} r={6} />
                <text x={x + 10} y={y + 4}>
                  {marker.event_type}
                </text>
              </g>
            );
          })}

        <g className="symbol-chart__legend">
          <text x={left} y={20}>
            Decision overlay {String(explanation?.action || kline?.action?.action || "NO_ACTION")}
          </text>
          <text x={right - 180} y={20}>
            Last close {formatScore(latest(closes), 2)}
          </text>
        </g>

        <g className="symbol-chart__strip">
          <rect x={left} y={stripTop} width={chartWidth} height={18} rx={9} />
          <text x={left + 8} y={stripTop + 12}>
            {state?.market_regime || "UNKNOWN"}
          </text>
          <text x={left + chartWidth / 2 - 40} y={stripTop + 12}>
            {state?.technical_regime || "UNKNOWN"}
          </text>
          <text x={right - 130} y={stripTop + 12}>
            Trust {formatScore(explanation?.trust?.trust_score || state?.trust_score)}
          </text>
        </g>
      </svg>

      <div className="symbol-chart__footer">
        <div>
          <div className="symbol-chart__footer-label">Market context</div>
          <div>{state?.state_summary || explanation?.world_state_summary || "Unavailable."}</div>
        </div>
        <div>
          <div className="symbol-chart__footer-label">Latest bar</div>
          <div>{formatDate(bars[bars.length - 1]?.date)} · Vol {formatCompactNumber(bars[bars.length - 1]?.volume)}</div>
        </div>
      </div>
    </div>
  );
}
