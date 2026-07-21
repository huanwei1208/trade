import type {
  ObsCompositeSeries,
  ObsContext,
  ObsExcludedDate,
  ObsSingleSeries,
} from "../../lib/api";
import { humanizeEnum } from "../../lib/format";
import { PanelCard } from "../PanelCard";
import { StatusPill } from "../StatusPill";
import {
  buildWhatChanged,
  extractLayers,
  isPlottable,
  readMetricString,
} from "../../lib/observatory";

// Overview panels (docs/26 §11.3, §11.4). The browser NEVER recomputes formal
// metrics — it only displays decimal strings the backend already produced. When
// a metric is absent we show "—" (honest unknown), not a fabricated 0.

// ── Market summary ───────────────────────────────────────────────────────────

type MarketSummaryProps = {
  series: ObsSingleSeries | null | undefined;
  context: ObsContext | null | undefined;
  loading?: boolean;
  unavailable?: boolean;
};

function Metric({
  label,
  value,
  unit,
  window,
  note,
}: {
  label: string;
  value: string | null;
  unit?: string;
  window?: string;
  note?: string;
}) {
  return (
    <div className="obs-metric">
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
  const rows = (series?.rows ?? []).filter(isPlottable);
  const latest = rows.length ? rows[rows.length - 1] : null;
  const latestMetrics = latest?.metrics;

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
          />
          <Metric
            label="1D return"
            value={readMetricString(latestMetrics, "return_1d")}
            unit="%"
            window="1 day"
          />
          <Metric
            label="7D return"
            value={readMetricString(latestMetrics, "return_7d")}
            unit="%"
            window="7 days"
          />
          <Metric
            label="30D return"
            value={readMetricString(latestMetrics, "return_30d")}
            unit="%"
            window="30 days"
          />
          <Metric
            label="Peak drawdown"
            value={readMetricString(latestMetrics, "drawdown")}
            unit="%"
            window="within window"
          />
          <Metric
            label="RV20 percentile"
            value={readMetricString(latestMetrics, "rv20_percentile")}
            unit="pct"
            window="trailing window"
          />
        </div>
      )}
      <div className="obs-market-summary__footer">
        <span className="obs-market-summary__snapshot" data-testid="market-summary-snapshot">
          snapshot {snapshotId ? snapshotId.slice(0, 12) : "—"} · metric contract v1 (display only)
        </span>
      </div>
    </PanelCard>
  );
}

// ── Why-not-formal ───────────────────────────────────────────────────────────

type WhyNotFormalProps = {
  context: ObsContext | null | undefined;
};

export function WhyNotFormal({ context }: WhyNotFormalProps) {
  // Read purpose fitness + findings to explain the current formal gap. Rule
  // based, no LLM: we surface the blockers the backend already returned.
  const formalPurpose = (context?.purpose_fitness ?? []).find(
    (p) => p.purpose === "formal_system_consumption",
  );
  const strictPurpose = (context?.purpose_fitness ?? []).find(
    (p) => p.purpose === "strict_research",
  );
  const reasonCodes = context?.reason_codes ?? [];
  const findings = context?.findings_summary || {};

  return (
    <PanelCard title="Why not formal" subdued className="obs-why-not">
      <div className="obs-why-not__body" data-testid="why-not-formal">
        <div className="obs-why-not__row">
          <span className="obs-why-not__label">Formal system consumption</span>
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
