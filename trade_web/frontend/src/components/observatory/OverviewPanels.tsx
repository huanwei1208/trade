import type {
  ObsCompositeSeries,
  ObsContext,
  ObsExcludedDate,
  ObsSeriesRow,
  ObsSingleSeries,
} from "../../lib/api";
import { humanizeEnum } from "../../lib/format";
import { PanelCard } from "../PanelCard";
import { StatusPill } from "../StatusPill";
import {
  buildWhatChanged,
  extractLayers,
  isPlottable,
  parseDecimal,
  readMetricString,
} from "../../lib/observatory";

// Overview panels (docs/26 §11.3, §11.4). Backend metrics remain authoritative.
// When a selected market series has no metrics, this panel can show explicitly
// labeled display estimates from the visible OHLCV rows. Missing windows remain
// unavailable with a reason instead of being coerced to zero.

// ── Market summary ───────────────────────────────────────────────────────────

type MarketSummaryProps = {
  series: ObsSingleSeries | null | undefined;
  context: ObsContext | null | undefined;
  loading?: boolean;
  unavailable?: boolean;
};

type SummaryMetricSource = "backend" | "display_estimate" | "unavailable";

type SummaryMetric = {
  value: string | null;
  unit?: string;
  note?: string;
  source: SummaryMetricSource;
};

type ReturnWindow = 1 | 7 | 30;

function metricValue(metrics: Record<string, unknown> | undefined, key: string): string | null {
  const value = readMetricString(metrics, key);
  if (value === null) {
    return null;
  }
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

function formatPercent(value: number): string {
  const rounded = Number(value.toFixed(2));
  return Object.is(rounded, -0) ? "0.00" : rounded.toFixed(2);
}

function utcDateOffset(date: string | null | undefined, offsetDays: number): string | null {
  if (!date || !/^\d{4}-\d{2}-\d{2}$/.test(date)) {
    return null;
  }
  const parsed = new Date(`${date}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== date) {
    return null;
  }
  parsed.setUTCDate(parsed.getUTCDate() + offsetDays);
  return parsed.toISOString().slice(0, 10);
}

function sortedPlottableRows(series: ObsSingleSeries | null | undefined): ObsSeriesRow[] {
  return (series?.rows ?? [])
    .filter(isPlottable)
    .slice()
    .sort((left, right) => String(left.date ?? "").localeCompare(String(right.date ?? "")));
}

function closeForRow(row: ObsSeriesRow | null | undefined): number | null {
  const close = parseDecimal(row?.close);
  return close !== null && close > 0 ? close : null;
}

function displayEstimateNote(rowCount: number): string {
  return `Display estimate · ${rowCount} visible bar${rowCount === 1 ? "" : "s"}`;
}

function returnMetric(
  latestMetrics: Record<string, unknown> | undefined,
  rows: ObsSeriesRow[],
  days: ReturnWindow,
): SummaryMetric {
  const backend = metricValue(latestMetrics, `return_${days}d`);
  if (backend !== null) {
    return { value: backend, unit: "%", source: "backend", note: "Backend metric" };
  }

  const latest = rows[rows.length - 1];
  const latestClose = closeForRow(latest);
  const targetDate = utcDateOffset(latest?.date, -days);
  const prior = targetDate ? rows.find((row) => row.date === targetDate) : null;
  const priorClose = closeForRow(prior);

  if (latestClose === null || priorClose === null) {
    return {
      value: "Unavailable",
      source: "unavailable",
      note: targetDate ? `Need ${targetDate} close` : "Need valid market dates",
    };
  }

  return {
    value: formatPercent((latestClose / priorClose - 1) * 100),
    unit: "%",
    source: "display_estimate",
    note: displayEstimateNote(rows.length),
  };
}

function drawdownMetric(
  latestMetrics: Record<string, unknown> | undefined,
  rows: ObsSeriesRow[],
): SummaryMetric {
  const backend = metricValue(latestMetrics, "drawdown");
  if (backend !== null) {
    return { value: backend, unit: "%", source: "backend", note: "Backend metric" };
  }

  const closes = rows.map(closeForRow).filter((close): close is number => close !== null);
  if (closes.length < 2) {
    return {
      value: "Unavailable",
      source: "unavailable",
      note: "Need at least 2 valid closes",
    };
  }

  let peak = closes[0];
  let worstDrawdown = 0;
  for (const close of closes) {
    if (close > peak) {
      peak = close;
    }
    worstDrawdown = Math.min(worstDrawdown, (close / peak - 1) * 100);
  }

  return {
    value: formatPercent(worstDrawdown),
    unit: "%",
    source: "display_estimate",
    note: displayEstimateNote(closes.length),
  };
}

function standardDeviation(values: number[]): number {
  const mean = values.reduce((sum, value) => sum + value, 0) / values.length;
  const variance =
    values.reduce((sum, value) => sum + (value - mean) ** 2, 0) / Math.max(1, values.length - 1);
  return Math.sqrt(variance);
}

function rv20PercentileMetric(
  latestMetrics: Record<string, unknown> | undefined,
  rows: ObsSeriesRow[],
): SummaryMetric {
  const backend = metricValue(latestMetrics, "rv20_percentile");
  if (backend !== null) {
    return { value: backend, unit: "pct", source: "backend", note: "Backend metric" };
  }

  const closes = rows.map(closeForRow).filter((close): close is number => close !== null);
  if (closes.length < 22) {
    return {
      value: "Unavailable",
      source: "unavailable",
      note: "Need at least 22 daily closes",
    };
  }

  const returns: number[] = [];
  for (let index = 1; index < closes.length; index += 1) {
    returns.push(closes[index] / closes[index - 1] - 1);
  }

  const realizedVols: number[] = [];
  for (let end = 20; end <= returns.length; end += 1) {
    realizedVols.push(standardDeviation(returns.slice(end - 20, end)) * Math.sqrt(365));
  }

  const latestVol = realizedVols[realizedVols.length - 1];
  if (latestVol === undefined || realizedVols.length < 2) {
    return {
      value: "Unavailable",
      source: "unavailable",
      note: "Need enough RV20 history",
    };
  }

  const percentile =
    (realizedVols.filter((volatility) => volatility <= latestVol).length / realizedVols.length) *
    100;
  return {
    value: formatPercent(percentile),
    unit: "pct",
    source: "display_estimate",
    note: displayEstimateNote(closes.length),
  };
}

function Metric({
  label,
  value,
  unit,
  window,
  note,
  source = "backend",
  testId,
}: {
  label: string;
  value: string | null;
  unit?: string;
  window?: string;
  note?: string;
  source?: SummaryMetricSource;
  testId?: string;
}) {
  return (
    <div className="obs-metric" data-metric-source={source} data-testid={testId}>
      <div className="obs-metric__label">{label}</div>
      <div className="obs-metric__value">
        {value ?? "—"}
        {value && unit ? <span className="obs-metric__unit"> {unit}</span> : null}
      </div>
      {window && <div className="obs-metric__window">{window}</div>}
      {note && <div className="obs-metric__note">{note}</div>}
    </div>
  );
}

export function MarketSummary({ series, context, loading, unavailable }: MarketSummaryProps) {
  const rows = sortedPlottableRows(series);
  const latest = rows.length ? rows[rows.length - 1] : null;
  const latestMetrics = latest?.metrics;
  const return1d = returnMetric(latestMetrics, rows, 1);
  const return7d = returnMetric(latestMetrics, rows, 7);
  const return30d = returnMetric(latestMetrics, rows, 30);
  const drawdown = drawdownMetric(latestMetrics, rows);
  const rv20Percentile = rv20PercentileMetric(latestMetrics, rows);

  const snapshotId = context?.snapshot_id;

  return (
    <PanelCard title="Market summary" subdued className="obs-market-summary">
      {loading ? (
        <div className="obs-empty" role="status">
          Loading selected-channel market summary…
        </div>
      ) : unavailable ? (
        <div className="obs-empty" role="status">
          Selected-channel market metrics are unavailable until its evidence is confirmed.
        </div>
      ) : (
        <div className="obs-metric-grid" data-testid="market-summary">
          <Metric
            label="Latest close"
            value={latest?.close ?? null}
            unit={latest?.quote ?? ""}
            note={latest?.date ? `bar ${latest.date}` : undefined}
            source={latest ? "backend" : "unavailable"}
            testId="metric-latest-close"
          />
          <Metric
            label="1D return"
            value={return1d.value}
            unit={return1d.unit}
            window="1 day"
            note={return1d.note}
            source={return1d.source}
            testId="metric-return-1d"
          />
          <Metric
            label="7D return"
            value={return7d.value}
            unit={return7d.unit}
            window="7 days"
            note={return7d.note}
            source={return7d.source}
            testId="metric-return-7d"
          />
          <Metric
            label="30D return"
            value={return30d.value}
            unit={return30d.unit}
            window="30 days"
            note={return30d.note}
            source={return30d.source}
            testId="metric-return-30d"
          />
          <Metric
            label="Peak drawdown"
            value={drawdown.value}
            unit={drawdown.unit}
            window="within window"
            note={drawdown.note}
            source={drawdown.source}
            testId="metric-drawdown"
          />
          <Metric
            label="RV20 percentile"
            value={rv20Percentile.value}
            unit={rv20Percentile.unit}
            window="trailing window"
            note={rv20Percentile.note}
            source={rv20Percentile.source}
            testId="metric-rv20-percentile"
          />
        </div>
      )}
      <div className="obs-market-summary__footer">
        <span className="obs-market-summary__snapshot" data-testid="market-summary-snapshot">
          snapshot {snapshotId ? snapshotId.slice(0, 12) : "—"} · backend metrics first; display
          estimates marked
        </span>
      </div>
    </PanelCard>
  );
}

// ── Published baseline status ────────────────────────────────────────────────

type WhyNotFormalProps = {
  context: ObsContext | null | undefined;
};

export function WhyNotFormal({ context }: WhyNotFormalProps) {
  // Read purpose fitness + findings to explain why a visible staged BTC run is
  // not the published baseline. Rule based, no LLM: we surface backend blockers.
  const formalPurpose = (context?.purpose_fitness ?? []).find(
    (p) => p.purpose === "formal_system_consumption",
  );
  const strictPurpose = (context?.purpose_fitness ?? []).find(
    (p) => p.purpose === "strict_research",
  );
  const reasonCodes = context?.reason_codes ?? [];
  const findings = context?.findings_summary || {};

  return (
    <PanelCard title="Published baseline status" subdued className="obs-why-not">
      <div className="obs-why-not__body" data-testid="why-not-formal">
        <div className="obs-why-not__explain" data-testid="published-baseline-explain">
          Published baseline means the run passed the stricter gates and can be used by the formal
          system. A staged candidate is still visible for manual observation, but it is not treated
          as canonical output.
        </div>
        <div className="obs-why-not__row">
          <span className="obs-why-not__label">Published baseline use</span>
          <StatusPill
            label={
              formalPurpose?.allowed ? "allowed" : `blocked: ${humanizeEnum(formalPurpose?.status)}`
            }
            tone={formalPurpose?.allowed ? "ok" : "warn"}
            subtle
          />
        </div>
        <div className="obs-why-not__row">
          <span className="obs-why-not__label">Strict research</span>
          <StatusPill
            label={
              strictPurpose?.allowed ? "allowed" : `blocked: ${humanizeEnum(strictPurpose?.status)}`
            }
            tone={strictPurpose?.allowed ? "ok" : "warn"}
            subtle
          />
        </div>
        {(formalPurpose?.reason_codes ?? []).length > 0 && (
          <div className="obs-why-not__reasons">
            <div className="obs-why-not__reasons-title">Reason codes</div>
            <ul className="obs-code-list">
              {(formalPurpose?.reason_codes ?? []).map((rc) => (
                <li key={rc}>
                  <code>{rc}</code>
                </li>
              ))}
            </ul>
          </div>
        )}
        {reasonCodes.length > 0 && (
          <div className="obs-why-not__reasons">
            <div className="obs-why-not__reasons-title">Context reason codes</div>
            <ul className="obs-code-list">
              {reasonCodes.map((rc) => (
                <li key={rc}>
                  <code>{rc}</code>
                </li>
              ))}
            </ul>
          </div>
        )}
        {Object.keys(findings).length > 0 && (
          <div className="obs-why-not__findings">
            <div className="obs-why-not__reasons-title">Findings summary</div>
            <ul className="obs-kv-list">
              {Object.entries(findings).map(([k, v]) => (
                <li key={k}>
                  <span className="obs-kv-key">{humanizeEnum(k)}</span>
                  <span className="obs-kv-val">
                    {typeof v === "object" ? JSON.stringify(v) : String(v)}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </PanelCard>
  );
}

// ── What changed (deterministic, rule-based) ─────────────────────────────────

type WhatChangedProps = {
  composite: ObsCompositeSeries | null | undefined;
  excludedDates?: ObsExcludedDate[];
};

export function WhatChanged({ composite, excludedDates }: WhatChangedProps) {
  const entries = buildWhatChanged(composite, excludedDates);
  const layers = extractLayers(composite);
  const anyLayer = layers.some((l) => l.present);

  return (
    <PanelCard title="What changed" subdued className="obs-what-changed">
      <div data-testid="what-changed">
        {!anyLayer && <div className="obs-empty">No composite layers resolved.</div>}
        {anyLayer && entries.length === 0 && (
          <div className="obs-empty">No structural change detected between layers.</div>
        )}
        {entries.length > 0 && (
          <ul className="obs-change-list">
            {entries.map((e, i) => (
              <li key={`${e.kind}-${i}`} className="obs-change-item" data-change-kind={e.kind}>
                <span className="obs-change-icon" aria-hidden="true">
                  {e.kind === "added_dates"
                    ? "+"
                    : e.kind === "removed_dates"
                      ? "−"
                      : e.kind === "revised_dates"
                        ? "◆"
                        : e.kind === "quarantined_dates"
                          ? "◇"
                          : "→"}
                </span>
                <div className="obs-change-body">
                  <div className="obs-change-label">{e.label}</div>
                  <div className="obs-change-detail">{e.detail}</div>
                  {e.evidenceRefs.length > 0 && (
                    <div className="obs-change-evidence">
                      evidence: {e.evidenceRefs.slice(0, 3).join(", ")}
                    </div>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
        <div className="obs-what-changed__footer">Rule-based summary · no model generation</div>
      </div>
    </PanelCard>
  );
}
