import { useMemo, useState } from "react";

import type { ObsChannel, ObsCompositeSeries, ObsSeriesRow } from "../../lib/api";
import {
  makeIndexScale,
  makeValueScale,
  paddedDomain,
  segmentedLinePaths,
  type ScaleMode,
} from "../../lib/chart";
import {
  applyRangeWindow,
  buildSegments,
  extractLayers,
  formalWatermarkDate,
  isPlottable,
  layerTreatment,
  markersForRow,
  parseDecimal,
  unionDates,
  type LayerKey,
} from "../../lib/observatory";

// Three-layer composite chart (docs/26 §7.8, §11.1, §12.1). The three lifecycle
// layers (formal / evaluated_candidate / latest_observed) are drawn as
// INDEPENDENT overlays on one shared axis:
//   - formal   : solid baseline stroke, no texture, IS the published baseline
//   - candidate: dashed stroke + persistent hatch texture (never "published")
//   - observed : dashed stroke + distinct outline texture (never "published")
// A vertical divider marks the formal watermark; everything to its right is
// candidate/observed-only tail. Missing dates BREAK the line (no interpolation).
// Quarantine/revision markers use shape+icon (non-color) so status never relies
// on hue alone.

type CompositeChartProps = {
  composite: ObsCompositeSeries | null | undefined;
  range: string; // 30D / 90D / 1Y / All
  selectedDate?: string | null;
  onSelectDate?: (date: string) => void;
  height?: number;
  visibleLayers?: Record<LayerKey, boolean>;
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

export function CompositeChart({
  composite,
  range,
  selectedDate,
  onSelectDate,
  height = 300,
  visibleLayers,
}: CompositeChartProps) {
  // Long-period price defaults to log scale (docs/26 §12.1). 30D/90D linear.
  const [scaleMode, setScaleMode] = useState<ScaleMode>(range === "1Y" || range === "All" ? "log" : "linear");

  const layers = useMemo(() => extractLayers(composite), [composite]);
  const allDates = useMemo(() => unionDates(composite), [composite]);
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
    for (const layer of layers) {
      for (const row of layer.rows) {
        if (row.date && dateIndex.has(row.date) && isPlottable(row)) {
          const v = parseDecimal(row.close);
          if (v !== null) {
            values.push(v);
          }
        }
      }
    }
    return paddedDomain(values);
  }, [layers, dateIndex]);

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

  // Marker rows across all layers (for non-color quarantine/revision glyphs).
  const markerNodes: Array<{ x: number; y: number; row: ObsSeriesRow; layer: LayerKey }> = [];

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

      <svg
        className="obs-chart__svg"
        viewBox={`0 0 ${WIDTH} ${height}`}
        role="img"
        aria-label="BTC three-layer composite price chart"
        data-testid="composite-svg"
      >
        <defs>
          {/* Persistent textures — candidate/observed never look "published". */}
          <pattern id="hatch-candidate" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="6" stroke="var(--warn)" strokeWidth="1.4" />
          </pattern>
          <pattern id="outline-observed" width="5" height="5" patternUnits="userSpaceOnUse">
            <circle cx="1" cy="1" r="1" fill="var(--accent-cyan)" />
          </pattern>
        </defs>

        {/* y grid + axis labels */}
        {[0, 0.25, 0.5, 0.75, 1].map((t) => {
          const value = scaleMode === "log"
            ? Math.pow(10, Math.log10(Math.max(domain.min, 1e-9)) + t * (Math.log10(Math.max(domain.max, 1e-9)) - Math.log10(Math.max(domain.min, 1e-9))))
            : domain.min + t * (domain.max - domain.min);
          const y = yScale(value);
          return (
            <g key={t}>
              <line x1={PAD_LEFT} y1={y} x2={WIDTH - PAD_RIGHT} y2={y} stroke="var(--line)" strokeWidth="1" />
              <text x={4} y={y + 3} fontSize="9" fill="var(--text-3)">
                {value.toLocaleString(undefined, { maximumFractionDigits: 0 })}
              </text>
            </g>
          );
        })}

        {/* Formal watermark divider — right of it is candidate/observed-only. */}
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
              formal watermark
            </text>
          </g>
        )}

        {/* Layers — draw formal first (baseline), then candidate, then observed. */}
        {layers.map((layer) => {
          if (!enabled(layer.key)) {
            return null;
          }
          const treatment = layerTreatment(layer.key);
          const rowsInWindow = layer.rows.filter((r) => r.date && dateIndex.has(r.date));
          const segments = buildSegments(rowsInWindow).map((seg) =>
            seg.map((p) => ({ index: dateIndex.get(rowsInWindow[p.index].date as string) as number, value: p.value })),
          );
          const paths = segmentedLinePaths(segments, xScale, yScale);

          // Collect markers for this layer.
          for (const row of rowsInWindow) {
            const markers = markersForRow(row);
            if (markers.length && row.date && dateIndex.has(row.date)) {
              const v = parseDecimal(row.close);
              markerNodes.push({
                x: xScale(dateIndex.get(row.date) as number),
                y: v !== null ? yScale(v) : height - PAD_BOTTOM - 6,
                row,
                layer: layer.key,
              });
            }
          }

          return (
            <g key={layer.key} data-testid={`layer-${layer.key}`} data-render-role={treatment.isBaseline ? "baseline" : "overlay"}>
              {paths.map((d, i) => (
                <path
                  key={i}
                  d={d}
                  fill="none"
                  stroke={LAYER_COLOR[layer.key]}
                  strokeWidth={treatment.isBaseline ? 2 : 1.6}
                  strokeDasharray={treatment.stroke === "dashed" ? "5 3" : undefined}
                  data-texture={treatment.texture ?? "none"}
                  data-presented-as-published={treatment.presentedAsPublished ? "true" : "false"}
                />
              ))}
            </g>
          );
        })}

        {/* Non-color markers: icon + shape (color is redundant, not required). */}
        {markerNodes.map((node, i) => {
          const markers = markersForRow(node.row);
          const primary = markers[0];
          return (
            <g key={`${node.row.date}-${node.layer}-${i}`} data-testid="chart-marker" data-marker-kind={primary?.kind}>
              <text x={node.x} y={node.y - 6} fontSize="10" textAnchor="middle" fill="var(--text-1)">
                {primary?.icon}
              </text>
            </g>
          );
        })}

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

        {/* Invisible hit targets for date selection. */}
        {onSelectDate &&
          windowDates.map((d, i) => (
            <rect
              key={d}
              x={xScale(i) - 3}
              y={PAD_TOP}
              width={6}
              height={height - PAD_TOP - PAD_BOTTOM}
              fill="transparent"
              style={{ cursor: "pointer" }}
              onClick={() => onSelectDate(d)}
              data-testid={`hit-${d}`}
            >
              <title>{d}</title>
            </rect>
          ))}
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
  formal: "Formal",
  evaluated_candidate: "Evaluated candidate",
  observed: "Latest observed",
};
