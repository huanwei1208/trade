import type { ReactNode } from "react";

import type { ObsChannel, ObsDateEvidence } from "../../lib/api";
import { formatDateTime } from "../../lib/format";
import { PanelCard } from "../PanelCard";
import { StatusPill } from "../StatusPill";
import { markersForRow } from "../../lib/observatory";

// Date Evidence Lens (docs/26 §12.2). Click a date -> primary/shadow OHLCV,
// basis, the four clocks (bar_close/available/fetched), findings, revision, run
// lineage. Research outcome is FIXED to "not_visible" in Observe/Investigate —
// future outcomes only appear inside the Research lens.

type DateEvidenceLensProps = {
  date: string | null;
  channel: ObsChannel;
  evidence: ObsDateEvidence | null | undefined;
  loading?: boolean;
  error?: string | null;
  onClose?: () => void;
};

function Row({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="obs-evidence__row">
      <span className="obs-evidence__label">{label}</span>
      <span className="obs-evidence__value">{value ?? "—"}</span>
    </div>
  );
}

export function DateEvidenceLens({ date, channel, evidence, loading, error, onClose }: DateEvidenceLensProps) {
  if (!date) {
    return (
      <PanelCard title="Date evidence" subdued className="obs-date-evidence">
        <div className="obs-empty" data-testid="date-evidence-empty">
          Select a date on the chart to inspect its provider evidence, basis, revision, and lineage.
        </div>
      </PanelCard>
    );
  }

  const ohlcv = evidence?.ohlcv ?? null;
  const markers = ohlcv ? markersForRow(ohlcv) : [];
  const visibility = evidence?.research_visibility ?? "not_visible";

  return (
    <PanelCard
      title={`Date evidence · ${date}`}
      subdued
      className="obs-date-evidence"
      actions={onClose ? <button type="button" className="button button--ghost" onClick={onClose}>Close</button> : undefined}
    >
      <div data-testid="date-evidence">
        {loading && <div className="obs-empty">Loading evidence…</div>}
        {error && <div className="obs-error" data-testid="date-evidence-error">{error}</div>}
        {!loading && !error && (
          <>
            <div className="obs-evidence__section">
              <div className="obs-evidence__section-title">Channel &amp; lineage</div>
              <Row label="Channel" value={<code>{channel}</code>} />
              <Row label="Snapshot" value={<code>{evidence?.snapshot_id?.slice(0, 16) || "—"}</code>} />
              <Row label="Run" value={<code>{evidence?.run_id || "—"}</code>} />
              <Row
                label="Run lineage"
                value={(evidence?.run_lineage ?? []).length ? (evidence?.run_lineage ?? []).join(" → ") : "—"}
              />
            </div>

            <div className="obs-evidence__section">
              <div className="obs-evidence__section-title">OHLCV (view value)</div>
              {ohlcv ? (
                <>
                  <Row label="Open" value={ohlcv.open} />
                  <Row label="High" value={ohlcv.high} />
                  <Row label="Low" value={ohlcv.low} />
                  <Row label="Close" value={ohlcv.close} />
                  <Row label="Volume" value={ohlcv.volume} />
                  <Row label="Provider / instrument" value={`${ohlcv.provider || "—"} · ${ohlcv.instrument || "—"}`} />
                  <Row label="Availability" value={<code>{ohlcv.availability_state}</code>} />
                  <Row label="Revision" value={<code>{ohlcv.revision_state}</code>} />
                </>
              ) : (
                <div className="obs-empty">No OHLCV for this date in the selected channel.</div>
              )}
            </div>

            <div className="obs-evidence__section">
              <div className="obs-evidence__section-title">Four clocks</div>
              <Row label="Available at" value={formatDateTime(ohlcv?.available_at)} />
              <Row label="Fetched at" value={formatDateTime(ohlcv?.fetched_at)} />
            </div>

            {markers.length > 0 && (
              <div className="obs-evidence__section" data-testid="date-evidence-markers">
                <div className="obs-evidence__section-title">Non-color markers</div>
                <div className="obs-marker-chips">
                  {markers.map((m) => (
                    <span key={m.kind} className="obs-marker-chip" data-marker-kind={m.kind}>
                      <span aria-hidden="true">{m.icon}</span> {m.label}
                    </span>
                  ))}
                </div>
              </div>
            )}

            <div className="obs-evidence__section">
              <div className="obs-evidence__section-title">Reconciliation (basis)</div>
              {evidence?.reconciliation ? (
                <ul className="obs-kv-list">
                  {Object.entries(evidence.reconciliation).map(([k, v]) => (
                    <li key={k}>
                      <span className="obs-kv-key">{k}</span>
                      <span className="obs-kv-val">{v ?? "—"}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="obs-empty">No reconciliation record for this date.</div>
              )}
            </div>

            <div className="obs-evidence__section">
              <div className="obs-evidence__section-title">Revision</div>
              {evidence?.revision ? (
                <ul className="obs-kv-list">
                  {Object.entries(evidence.revision).map(([k, v]) => (
                    <li key={k}>
                      <span className="obs-kv-key">{k}</span>
                      <span className="obs-kv-val">{v ?? "—"}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="obs-empty">No revision recorded for this date.</div>
              )}
            </div>

            <div className="obs-evidence__section">
              <div className="obs-evidence__section-title">Research outcome</div>
              <div className="obs-evidence__research" data-testid="research-visibility">
                <StatusPill label={`Outcome: ${visibility}`} tone={visibility === "not_visible" ? "muted" : "info"} subtle />
                <p className="obs-evidence__note">
                  Forward-looking research labels are never shown in Observe / Investigate. Open the Research lens for
                  matured / pending labels.
                </p>
              </div>
            </div>

            {(evidence?.reason_codes ?? []).length > 0 && (
              <div className="obs-evidence__section">
                <div className="obs-evidence__section-title">Reason codes</div>
                <ul className="obs-code-list">
                  {(evidence?.reason_codes ?? []).map((rc) => (
                    <li key={rc}><code>{rc}</code></li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
      </div>
    </PanelCard>
  );
}
