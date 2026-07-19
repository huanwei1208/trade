import { useMemo } from "react";

import type { ObsCompositeSeries, ObsTrust } from "../../lib/api";
import { humanizeEnum } from "../../lib/format";
import { PanelCard } from "../PanelCard";
import { StatusPill } from "../StatusPill";
import { extractLayers } from "../../lib/observatory";

// Trust lens (docs/26 §13). Coverage Calendar (per market day state), Acquisition
// Calendar (pre-stage states shown as unsupported/unknown — NEVER failed), gate
// presentation with what-happened / affected-dates / blocked-purposes / evidence.
// Colors are always paired with a text label so status is not conveyed by hue.

type TrustLensProps = {
  trust: ObsTrust | null | undefined;
  composite: ObsCompositeSeries | null | undefined;
  loading?: boolean;
  error?: string | null;
  onSelectDate?: (date: string) => void;
};

type CoverageState = "complete" | "quarantined" | "missing" | "non_final" | "unobserved" | "unknown";

function coverageState(row: { availability_state?: string; quality_flags?: string[] }): CoverageState {
  const flags = row.quality_flags ?? [];
  if (flags.includes("quarantined")) {
    return "quarantined";
  }
  if (flags.includes("non_final")) {
    return "non_final";
  }
  switch (row.availability_state) {
    case "present":
      return "complete";
    case "missing":
      return "missing";
    case "unobserved":
      return "unobserved";
    default:
      return "unknown";
  }
}

const COVERAGE_GLYPH: Record<CoverageState, string> = {
  complete: "●",
  quarantined: "◇",
  missing: "×",
  non_final: "◐",
  unobserved: "·",
  unknown: "?",
};

export function TrustLens({ trust, composite, loading, error, onSelectDate }: TrustLensProps) {
  // Coverage calendar rows: prefer observed layer (widest), fall back to formal.
  const coverageRows = useMemo(() => {
    const layers = extractLayers(composite);
    const observed = layers.find((l) => l.key === "latest_observed");
    const formal = layers.find((l) => l.key === "formal");
    const source = observed?.rows?.length ? observed.rows : formal?.rows ?? [];
    return source.filter((r) => r.date);
  }, [composite]);

  return (
    <div className="obs-trust-lens" data-testid="trust-lens">
      <PanelCard title="Coverage calendar" subdued>
        <p className="obs-lens__hint">Per market day. Each cell pairs a shape glyph with a text state (non-color).</p>
        {coverageRows.length === 0 ? (
          <div className="obs-empty">No coverage rows resolved.</div>
        ) : (
          <div className="obs-calendar" data-testid="coverage-calendar">
            {coverageRows.map((r) => {
              const state = coverageState(r);
              return (
                <button
                  key={r.date}
                  type="button"
                  className={`obs-cal-cell obs-cal-cell--${state}`}
                  data-coverage-state={state}
                  title={`${r.date}: ${state}`}
                  onClick={() => r.date && onSelectDate?.(r.date)}
                >
                  <span className="obs-cal-cell__glyph" aria-hidden="true">{COVERAGE_GLYPH[state]}</span>
                  <span className="obs-cal-cell__date">{(r.date || "").slice(5)}</span>
                </button>
              );
            })}
          </div>
        )}
        <CoverageLegend />
      </PanelCard>

      <PanelCard title="Acquisition calendar" subdued>
        <p className="obs-lens__hint">
          Aggregated by real acquisition day. Pre-stage states show as <strong>unsupported/unknown</strong>, never as
          failed, when attempt receipts are absent.
        </p>
        <div className="obs-acq-note" data-testid="acquisition-calendar">
          <StatusPill
            label={`Acquisition state: ${humanizeEnum(trust?.acquisition_state)}`}
            tone={trust?.acquisition_state === "succeeded" ? "ok" : trust?.acquisition_state === "failed" ? "err" : "muted"}
            subtle
          />
          <StatusPill label={`Quality: ${humanizeEnum(trust?.quality_state)}`} tone="info" subtle />
          <p className="obs-lens__hint">
            Only completed facts from immutable manifests are shown. Missing attempt receipts are not painted as failures.
          </p>
        </div>
      </PanelCard>

      <PanelCard title="Quality gates" subdued>
        <p className="obs-lens__hint">
          User-level gates: contract, acquisition, structure, cross-source, revision, publish. Each shows what happened,
          affected dates, and evidence.
        </p>
        {loading && <div className="obs-empty">Loading gates…</div>}
        {error && <div className="obs-error">{error}</div>}
        {!loading && !error && (trust?.gates ?? []).length === 0 && <div className="obs-empty">No gates recorded.</div>}
        {(trust?.gates ?? []).length > 0 && (
          <div className="obs-gate-list" data-testid="gate-list">
            {(trust?.gates ?? []).map((g, i) => {
              const status = (g.status || "").toLowerCase();
              const tone = status === "pass" ? "ok" : status === "warn" ? "warn" : status === "block" || status === "fail" ? "err" : "muted";
              return (
                <div key={`${g.gate}-${i}`} className="obs-gate" data-gate={g.gate} data-gate-status={g.status}>
                  <div className="obs-gate__head">
                    <span className="obs-gate__name">{humanizeEnum(g.gate)}</span>
                    <StatusPill label={humanizeEnum(g.status) || "unknown"} tone={tone} subtle />
                  </div>
                  {g.detail && <div className="obs-gate__detail">{g.detail}</div>}
                  {g.reason_code && <div className="obs-gate__reason"><code>{g.reason_code}</code></div>}
                </div>
              );
            })}
          </div>
        )}
      </PanelCard>

      <PanelCard title="Findings" subdued>
        {(trust?.findings ?? []).length === 0 ? (
          <div className="obs-empty">No findings recorded for this snapshot.</div>
        ) : (
          <div className="obs-finding-list" data-testid="finding-list">
            {(trust?.findings ?? []).map((f) => (
              <div key={f.finding_id} className="obs-finding">
                <div className="obs-finding__head">
                  <span className="obs-finding__gate">{humanizeEnum(f.gate)}</span>
                  <StatusPill label={humanizeEnum(f.severity) || "info"} tone={f.severity === "block" ? "err" : "warn"} subtle />
                </div>
                {f.reason_code && <div className="obs-finding__reason"><code>{f.reason_code}</code></div>}
                {(f.affected_dates ?? []).length > 0 && (
                  <div className="obs-finding__dates">
                    Affected: {(f.affected_dates ?? []).slice(0, 8).join(", ")}
                    {(f.affected_dates ?? []).length > 8 ? " …" : ""}
                  </div>
                )}
                {(f.evidence_refs ?? []).length > 0 && (
                  <div className="obs-finding__evidence">evidence: {(f.evidence_refs ?? []).slice(0, 3).join(", ")}</div>
                )}
              </div>
            ))}
          </div>
        )}
      </PanelCard>
    </div>
  );
}

function CoverageLegend() {
  const states: CoverageState[] = ["complete", "quarantined", "missing", "non_final", "unobserved", "unknown"];
  return (
    <div className="obs-cal-legend" data-testid="coverage-legend">
      {states.map((s) => (
        <span key={s} className="obs-cal-legend__item">
          <span aria-hidden="true">{COVERAGE_GLYPH[s]}</span> {humanizeEnum(s)}
        </span>
      ))}
    </div>
  );
}
