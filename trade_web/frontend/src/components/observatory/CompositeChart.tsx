import { useMemo, useState, type RefObject } from "react";

import type { ObsChannel, ObsCompositeSeries, ObsExcludedDate, ObsSeriesRow } from "../../lib/api";
import { makeIndexScale, makeValueScale, paddedDomain, type ScaleMode } from "../../lib/chart";
import {
  applyRangeWindow,
  downsampleSeriesRows,
  extractLayers,
  formalWatermarkDate,
  isPlottable,
  layerTreatment,
  markersForRow,
  OBSERVATORY_CHART_POINT_BUDGET,
  parseDecimal,
  type LayerKey,
  type NonColorMarkerKind,
} from "../../lib/observatory";

// Three-layer composite chart (docs/26 §7.8, §11.1, §12.1). The three lifecycle
// layers (formal / evaluated_candidate / latest_observed) are drawn as
// INDEPENDENT OHLC candlestick overlays on one shared axis:
//   - formal   : published baseline outline, no texture
//   - candidate: staged overlay with persistent hatch texture (never "published")
//   - observed : latest overlay with distinct outline texture (never "published")
// A vertical divider marks the published-baseline watermark; everything to its
// right is candidate/observed-only tail. Missing dates render no candle (no
// interpolation). Quarantine/revision markers use shape+icon (non-color) so
// status never relies on hue alone.

type CompositeChartProps = {
  composite: ObsCompositeSeries | null | undefined;
  range: string; // 30D / 90D / 1Y / All
  selectedDate?: string | null;
  onSelectDate?: (date: string) => void;
  dateInputRef?: RefObject<HTMLInputElement | null>;
  height?: number;
  visibleLayers?: Record<LayerKey, boolean>;
  excludedDates?: ObsExcludedDate[];
  quarantineBreakLayer?: LayerKey;
};

const WIDTH = 860;
const PAD_LEFT = 56;
const PAD_RIGHT = 18;
const PAD_TOP = 16;
const PAD_BOTTOM = 30;

const LAYER_COLOR: Record<LayerKey, string> = {
  formal: "var(--accent-blue)",
  evaluated_candidate: "var(--warn)",
  latest_observed: "var(--accent-cyan)",
};

type ChartMarkerNode = {
  x: number;
  y: number;
  row: ObsSeriesRow;
  layer: LayerKey;
  kind: NonColorMarkerKind;
  source: "layer" | "context";
};

type ChartMarkerSelection = {
  nodes: ChartMarkerNode[];
  sampled: boolean;
};

type CandleValue = {
  open: number;
  high: number;
  low: number;
  close: number;
};

const RETAINED_MARKER_KINDS: NonColorMarkerKind[] = [
  "quarantine",
  "missing",
  "unobserved",
  "revision",
];

function sortChartMarkers(markerNodes: ChartMarkerNode[]): ChartMarkerNode[] {
  return [...markerNodes].sort(
    (left, right) =>
      left.x - right.x ||
      (left.row.date ?? "").localeCompare(right.row.date ?? "") ||
      left.layer.localeCompare(right.layer) ||
      left.kind.localeCompare(right.kind),
  );
}

function evenlySampleChartMarkers(
  markerNodes: ChartMarkerNode[],
  budget: number,
): ChartMarkerNode[] {
  if (budget <= 0) {
    return [];
  }
  if (markerNodes.length <= budget) {
    return markerNodes;
  }

  return Array.from({ length: budget }, (_, index) => {
    const selectedIndex = Math.round((index * (markerNodes.length - 1)) / (budget - 1));
    return markerNodes[selectedIndex] as ChartMarkerNode;
  });
}

function downsampleChartMarkers(markerNodes: ChartMarkerNode[]): ChartMarkerSelection {
  if (markerNodes.length <= OBSERVATORY_CHART_POINT_BUDGET) {
    return { nodes: markerNodes, sampled: false };
  }

  const sorted = sortChartMarkers(markerNodes);
  const retained = RETAINED_MARKER_KINDS.flatMap((kind) => {
    const marker = sorted.find((node) => node.kind === kind);
    return marker ? [marker] : [];
  });
  const retainedNodes = new Set(retained);
  const evenlySampled = evenlySampleChartMarkers(
    sorted.filter((node) => !retainedNodes.has(node)),
    OBSERVATORY_CHART_POINT_BUDGET - retained.length,
  );

  return {
    nodes: sortChartMarkers([...retained, ...evenlySampled]),
    sampled: true,
  };
}

function markerSelectionNotice(selection: ChartMarkerSelection): string | null {
  if (!selection.sampled) {
    return null;
  }
  return "Status markers sampled to the chart display budget; each available status type is retained.";
}

function mergeExcludedDates(...groups: ObsExcludedDate[][]): ObsExcludedDate[] {
  const dates = new Map<string, ObsExcludedDate>();
  for (const excludedDate of groups.flat()) {
    if (!excludedDate.date) {
      continue;
    }
    const existing = dates.get(excludedDate.date);
    dates.set(excludedDate.date, {
      ...existing,
      ...excludedDate,
      date: excludedDate.date,
      quality_flags: [
        ...new Set([...(existing?.quality_flags ?? []), ...(excludedDate.quality_flags ?? [])]),
      ],
    });
  }
  return [...dates.values()];
}

function mergeQuarantineBreakRows(
  rows: ObsSeriesRow[],
  excludedDateByValue: Map<string, ObsExcludedDate>,
): ObsSeriesRow[] {
  const rowsByDate = new Map(
    rows
      .filter((row): row is ObsSeriesRow & { date: string } => Boolean(row.date))
      .map((row) => [row.date, row]),
  );
  const dates = new Set([...rowsByDate.keys(), ...excludedDateByValue.keys()]);

  return [...dates].sort().map((date) => {
    const existingRow = rowsByDate.get(date);
    const excludedDate = excludedDateByValue.get(date);
    if (!excludedDate) {
      return existingRow as ObsSeriesRow;
    }

    return {
      ...existingRow,
      date,
      close: null,
      availability_state: "unknown",
      quality_flags: [
        ...new Set([
          ...(existingRow?.quality_flags ?? []),
          ...(excludedDate.quality_flags ?? []),
          "quarantined",
        ]),
      ],
    };
  });
}

function candleValue(row: ObsSeriesRow): CandleValue | null {
  if (!isPlottable(row)) {
    return null;
  }
  const open = parseDecimal(row.open);
  const high = parseDecimal(row.high);
  const low = parseDecimal(row.low);
  const close = parseDecimal(row.close);
  if (open === null || high === null || low === null || close === null) {
    return null;
  }
  return { open, high, low, close };
}

function candleTone(value: CandleValue): "up" | "down" | "flat" {
  if (value.close > value.open) {
    return "up";
  }
  if (value.close < value.open) {
    return "down";
  }
  return "flat";
}

export function CompositeChart({
  composite,
  range,
  selectedDate,
  onSelectDate,
  dateInputRef,
  height = 300,
  visibleLayers,
  excludedDates = [],
  quarantineBreakLayer,
}: CompositeChartProps) {
  // Long-period price defaults to log scale (docs/26 §12.1). 30D/90D linear.
  const [scaleMode, setScaleMode] = useState<ScaleMode>(
    range === "1Y" || range === "All" ? "log" : "linear",
  );

  const layers = useMemo(() => extractLayers(composite), [composite]);
  const excludedDatesByLayer = useMemo(
    () =>
      new Map(
        layers.map((layer) => [
          layer.key,
          mergeExcludedDates(
            layer.excludedDates,
            layer.key === quarantineBreakLayer ? excludedDates : [],
          ),
        ]),
      ),
    [layers, excludedDates, quarantineBreakLayer],
  );
  const allExcludedDates = useMemo(
    () => mergeExcludedDates(excludedDates, ...[...excludedDatesByLayer.values()]),
    [excludedDates, excludedDatesByLayer],
  );
  const layersWithQuarantineGaps = useMemo(
    () =>
      layers.map((layer) => {
        const layerExcludedDates = excludedDatesByLayer.get(layer.key) ?? [];
        return {
          ...layer,
          rows: mergeQuarantineBreakRows(
            layer.rows,
            new Map(
              layerExcludedDates
                .filter(
                  (excludedDate): excludedDate is ObsExcludedDate & { date: string } =>
                    typeof excludedDate.date === "string",
                )
                .map((excludedDate) => [excludedDate.date, excludedDate]),
            ),
          ),
        };
      }),
    [layers, excludedDatesByLayer],
  );
  const allDates = useMemo(
    () =>
      Array.from(
        new Set([
          ...layersWithQuarantineGaps.flatMap((layer) => layer.rows.map((row) => row.date)),
          ...allExcludedDates.map((excludedDate) => excludedDate.date),
        ]),
      )
        .filter((date): date is string => Boolean(date))
        .sort(),
    [allExcludedDates, layersWithQuarantineGaps],
  );
  const windowDates = useMemo(() => applyRangeWindow(allDates, range), [allDates, range]);
  const dateIndex = useMemo(() => {
    const map = new Map<string, number>();
    windowDates.forEach((d, i) => map.set(d, i));
    return map;
  }, [windowDates]);

  const formalWatermark = useMemo(() => formalWatermarkDate(composite), [composite]);

  // Shared y-domain across ALL layers so no single layer redefines the scale.
  const domain = useMemo(() => {
    const values: number[] = [];
    for (const layer of layersWithQuarantineGaps) {
      for (const row of layer.rows) {
        if (row.date && dateIndex.has(row.date)) {
          const candle = candleValue(row);
          if (candle) {
            values.push(candle.open, candle.high, candle.low, candle.close);
          }
        }
      }
    }
    return paddedDomain(values);
  }, [layersWithQuarantineGaps, dateIndex]);

  const xScale = useMemo(
    () => makeIndexScale(windowDates.length, WIDTH, PAD_LEFT, PAD_RIGHT),
    [windowDates.length],
  );
  const yScale = useMemo(
    () => makeValueScale(domain.min, domain.max, height, scaleMode, PAD_TOP, PAD_BOTTOM),
    [domain.min, domain.max, height, scaleMode],
  );

  if (!composite || !windowDates.length) {
    return (
      <div className="obs-chart obs-chart--empty" data-testid="composite-chart-empty">
        No composite series to display for this range.
      </div>
    );
  }

  const enabled = (key: LayerKey) => (visibleLayers ? visibleLayers[key] : true);
  const activeLayerKeys = layersWithQuarantineGaps
    .map((layer) => layer.key)
    .filter((key) => enabled(key));
  const activeLayerCount = Math.max(1, activeLayerKeys.length);
  const xStep =
    windowDates.length > 1 ? Math.abs(xScale(1) - xScale(0)) : WIDTH - PAD_LEFT - PAD_RIGHT;
  const candleSlot = Math.max(1.6, Math.min(12, (xStep * 0.78) / activeLayerCount));
  const candleWidth = Math.max(1.2, Math.min(8, candleSlot * 0.72));
  const excludedDateByValue = new Map(
    allExcludedDates
      .filter(
        (excludedDate): excludedDate is ObsExcludedDate & { date: string } =>
          typeof excludedDate.date === "string" && dateIndex.has(excludedDate.date),
      )
      .map((excludedDate) => [excludedDate.date, excludedDate]),
  );

  // Marker rows across all layers (for non-color quarantine/revision glyphs).
  const markerNodes: ChartMarkerNode[] = [];
  const layerQuarantineMarkerDates = new Set<string>();

  return (
    <div className="obs-chart" data-testid="composite-chart">
      <div className="obs-chart__toolbar">
        <div className="obs-chart__scale" data-testid="scale-label">
          <span className="obs-chart__scale-label">Scale</span>
          <button
            type="button"
            className={scaleMode === "linear" ? "is-active" : ""}
            aria-pressed={scaleMode === "linear"}
            onClick={() => setScaleMode("linear")}
          >
            Linear
          </button>
          <button
            type="button"
            className={scaleMode === "log" ? "is-active" : ""}
            aria-pressed={scaleMode === "log"}
            onClick={() => setScaleMode("log")}
          >
            Log
          </button>
          <span className="obs-chart__scale-current" data-testid="scale-current">
            {scaleMode === "log" ? "Log scale" : "Linear scale"}
          </span>
        </div>
        <CompositeLegend />
      </div>
      {onSelectDate ? (
        <label className="obs-chart__date-inspector">
          <span>Inspect market date</span>
          <input
            ref={dateInputRef}
            type="date"
            value={selectedDate ?? ""}
            min={windowDates[0]}
            max={windowDates[windowDates.length - 1]}
            aria-label="Inspect a visible market date"
            onChange={(event) => {
              if (windowDates.includes(event.target.value)) {
                onSelectDate(event.target.value);
              }
            }}
            data-testid="chart-date-inspector"
          />
        </label>
      ) : null}

      <svg
        className="obs-chart__svg"
        viewBox={`0 0 ${WIDTH} ${height}`}
        role="img"
        aria-label="BTC three-layer composite price chart"
        data-testid="composite-svg"
      >
        <defs>
          {/* Persistent textures — candidate/observed never look "published". */}
          <pattern
            id="hatch-candidate"
            width="6"
            height="6"
            patternUnits="userSpaceOnUse"
            patternTransform="rotate(45)"
          >
            <line x1="0" y1="0" x2="0" y2="6" stroke="var(--warn)" strokeWidth="1.4" />
          </pattern>
          <pattern id="outline-observed" width="5" height="5" patternUnits="userSpaceOnUse">
            <circle cx="1" cy="1" r="1" fill="var(--accent-cyan)" />
          </pattern>
        </defs>

        {/* y grid + axis labels */}
        {[0, 0.25, 0.5, 0.75, 1].map((t) => {
          const value =
            scaleMode === "log"
              ? Math.pow(
                  10,
                  Math.log10(Math.max(domain.min, 1e-9)) +
                    t *
                      (Math.log10(Math.max(domain.max, 1e-9)) -
                        Math.log10(Math.max(domain.min, 1e-9))),
                )
              : domain.min + t * (domain.max - domain.min);
          const y = yScale(value);
          return (
            <g key={t}>
              <line
                x1={PAD_LEFT}
                y1={y}
                x2={WIDTH - PAD_RIGHT}
                y2={y}
                stroke="var(--line)"
                strokeWidth="1"
              />
              <text x={4} y={y + 3} fontSize="9" fill="var(--text-3)">
                {value.toLocaleString(undefined, { maximumFractionDigits: 0 })}
              </text>
            </g>
          );
        })}

        {/* Published-baseline watermark divider — right of it is candidate/observed-only. */}
        {formalWatermark && dateIndex.has(formalWatermark) && (
          <g data-testid="formal-watermark-divider">
            <line
              x1={xScale(dateIndex.get(formalWatermark) as number)}
              y1={PAD_TOP}
              x2={xScale(dateIndex.get(formalWatermark) as number)}
              y2={height - PAD_BOTTOM}
              stroke="var(--accent-blue)"
              strokeWidth="1.4"
              strokeDasharray="2 3"
            />
            <text
              x={xScale(dateIndex.get(formalWatermark) as number) + 4}
              y={PAD_TOP + 10}
              fontSize="9"
              fill="var(--accent-blue)"
            >
              published baseline watermark
            </text>
          </g>
        )}

        {/* Layers — draw published baseline first, then candidate, then observed. */}
        {layersWithQuarantineGaps.map((layer) => {
          if (!enabled(layer.key)) {
            return null;
          }
          const treatment = layerTreatment(layer.key);
          const rowsInWindow = layer.rows.filter((r) => r.date && dateIndex.has(r.date));
          const displayedRows = downsampleSeriesRows(rowsInWindow);
          const layerIndex = Math.max(0, activeLayerKeys.indexOf(layer.key));
          const layerOffset = (layerIndex - (activeLayerCount - 1) / 2) * candleSlot;

          // Collect markers for this layer.
          for (const row of rowsInWindow) {
            const markers = markersForRow(row);
            if (markers.length && row.date && dateIndex.has(row.date)) {
              if (markers.some((marker) => marker.kind === "quarantine")) {
                layerQuarantineMarkerDates.add(row.date);
              }
              const v = parseDecimal(row.close);
              for (const marker of markers) {
                markerNodes.push({
                  x: xScale(dateIndex.get(row.date) as number),
                  y: v !== null ? yScale(v) : height - PAD_BOTTOM - 6,
                  row,
                  layer: layer.key,
                  kind: marker.kind,
                  source: "layer",
                });
              }
            }
          }

          return (
            <g
              key={layer.key}
              data-testid={`layer-${layer.key}`}
              data-render-role={treatment.isBaseline ? "baseline" : "overlay"}
            >
              {displayedRows.map((row) => {
                if (!row.date) {
                  return null;
                }
                const candle = candleValue(row);
                if (!candle) {
                  return null;
                }
                const index = dateIndex.get(row.date);
                if (index === undefined) {
                  return null;
                }
                const centerX = xScale(index) + layerOffset;
                const openY = yScale(candle.open);
                const closeY = yScale(candle.close);
                const highY = yScale(candle.high);
                const lowY = yScale(candle.low);
                const bodyY = Math.min(openY, closeY);
                const bodyHeight = Math.max(2, Math.abs(closeY - openY));
                const tone = candleTone(candle);
                const fill =
                  tone === "up" ? "var(--ok)" : tone === "down" ? "var(--err)" : "var(--text-2)";

                return (
                  <g
                    key={`${layer.key}-${row.date}`}
                    data-testid={`candle-${layer.key}`}
                    data-date={row.date}
                    data-price-direction={tone}
                    data-texture={treatment.texture ?? "none"}
                    data-presented-as-published={treatment.presentedAsPublished ? "true" : "false"}
                  >
                    <line
                      x1={centerX}
                      y1={highY}
                      x2={centerX}
                      y2={lowY}
                      stroke={LAYER_COLOR[layer.key]}
                      strokeWidth={treatment.isBaseline ? 1.5 : 1.2}
                    />
                    <rect
                      x={centerX - candleWidth / 2}
                      y={bodyY}
                      width={candleWidth}
                      height={bodyHeight}
                      rx="1"
                      fill={fill}
                      fillOpacity={treatment.isBaseline ? 0.32 : 0.2}
                      stroke={LAYER_COLOR[layer.key]}
                      strokeWidth={treatment.isBaseline ? 1.4 : 1.1}
                    />
                    {treatment.texture ? (
                      <rect
                        x={centerX - candleWidth / 2}
                        y={bodyY}
                        width={candleWidth}
                        height={bodyHeight}
                        rx="1"
                        fill={`url(#${treatment.texture})`}
                        opacity="0.72"
                        pointerEvents="none"
                      />
                    ) : null}
                  </g>
                );
              })}
            </g>
          );
        })}

        {(() => {
          const fallbackMarkers: ChartMarkerNode[] = [...excludedDateByValue.values()]
            .filter((excludedDate) => !layerQuarantineMarkerDates.has(excludedDate.date))
            .map((excludedDate) => ({
              x: xScale(dateIndex.get(excludedDate.date) as number),
              y: height - PAD_BOTTOM - 6,
              row: {
                date: excludedDate.date,
                close: null,
                availability_state: "unknown" as const,
                quality_flags: ["quarantined"],
              },
              layer: "latest_observed" as const,
              kind: "quarantine" as const,
              source: "context" as const,
            }));

          const selection = downsampleChartMarkers([...markerNodes, ...fallbackMarkers]);
          return (
            <>
              {markerSelectionNotice(selection) ? (
                <text
                  x={WIDTH - PAD_RIGHT}
                  y={height - 4}
                  fontSize="9"
                  textAnchor="end"
                  fill="var(--text-3)"
                  data-testid="chart-marker-sampling-notice"
                >
                  {markerSelectionNotice(selection)}
                </text>
              ) : null}
              {selection.nodes.map((node, index) => {
                const marker = markersForRow(node.row).find(
                  (candidate) => candidate.kind === node.kind,
                );
                return (
                  <g
                    key={`${node.row.date}-${node.layer}-${node.kind}-${index}`}
                    data-testid={
                      node.source === "context" ? "chart-context-quarantine-marker" : "chart-marker"
                    }
                    data-marker-kind={node.kind}
                  >
                    <text
                      x={node.x}
                      y={node.y - 6}
                      fontSize="10"
                      textAnchor="middle"
                      fill="var(--text-1)"
                    >
                      {marker?.icon}
                    </text>
                  </g>
                );
              })}
            </>
          );
        })()}

        {/* Selected-date crosshair (locks the date across panels). */}
        {selectedDate && dateIndex.has(selectedDate) && (
          <line
            x1={xScale(dateIndex.get(selectedDate) as number)}
            y1={PAD_TOP}
            x2={xScale(dateIndex.get(selectedDate) as number)}
            y2={height - PAD_BOTTOM}
            stroke="var(--text-2)"
            strokeWidth="1"
            data-testid="crosshair"
          />
        )}

        {onSelectDate ? (
          <rect
            x={PAD_LEFT}
            y={PAD_TOP}
            width={WIDTH - PAD_LEFT - PAD_RIGHT}
            height={height - PAD_TOP - PAD_BOTTOM}
            fill="transparent"
            style={{ cursor: "pointer" }}
            onPointerUp={(event) => {
              const bounds = event.currentTarget.getBoundingClientRect();
              if (!bounds.width) {
                return;
              }
              const ratio = Math.min(1, Math.max(0, (event.clientX - bounds.left) / bounds.width));
              const index = Math.round(ratio * (windowDates.length - 1));
              const date = windowDates[index];
              if (date) {
                onSelectDate(date);
              }
            }}
            data-testid="chart-pointer-overlay"
          />
        ) : null}
      </svg>
    </div>
  );
}

export function CompositeLegend() {
  const items: Array<{ key: LayerKey; hint: string }> = [
    { key: "formal", hint: "solid" },
    { key: "evaluated_candidate", hint: "hatch texture" },
    { key: "latest_observed", hint: "dotted outline" },
  ];
  return (
    <div className="obs-chart__legend" data-testid="composite-legend">
      {items.map(({ key, hint }) => {
        const t = layerTreatment(key);
        return (
          <span key={key} className="obs-legend-item" data-testid={`legend-${key}`}>
            <span
              className={`obs-legend-swatch obs-legend-swatch--${key}`}
              aria-hidden="true"
              style={{ background: LAYER_COLOR[key] }}
            />
            <span className="obs-legend-label">{t.legendLabel}</span>
            <span className="obs-legend-hint">({hint})</span>
          </span>
        );
      })}
    </div>
  );
}

export const CHANNEL_LABEL: Record<ObsChannel, string> = {
  formal: "Published baseline",
  evaluated_candidate: "Evaluated candidate",
  observed: "Latest observed",
};
