import { useEffect, useState } from "react";

import type { ObsRunDetail, ObsRunDiff, ObsRunsPayload } from "../../lib/api";
import { fetchJson, observatoryRunDetailPath, observatoryRunDiffPath } from "../../lib/api";
import { formatDateTime, humanizeEnum } from "../../lib/format";
import { PanelCard } from "../PanelCard";
import { StatusPill } from "../StatusPill";

// Runs & Lineage lens (docs/26 §14). Run list -> run detail -> run diff. Diff
// reports added / removed / changed dates plus code/config/schema changes — not
// just a watermark comparison. Historical certification and current
// compatibility are shown separately (a replay mismatch never erases the fact
// that a run was certified & published at the time).

type RunsLineageLensProps = {
  runs: ObsRunsPayload | null | undefined;
  loading?: boolean;
  error?: string | null;
  selectedRunId?: string | null;
  compareRunId?: string | null;
  onSelectRun: (runId: string | null) => void;
  onCompareRun: (runId: string | null) => void;
};

export function RunsLineageLens({
  runs,
  loading,
  error,
  selectedRunId,
  compareRunId,
  onSelectRun,
  onCompareRun,
}: RunsLineageLensProps) {
  const [detail, setDetail] = useState<ObsRunDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [diff, setDiff] = useState<ObsRunDiff | null>(null);
  const [diffError, setDiffError] = useState<string | null>(null);

  useEffect(() => {
    if (!selectedRunId) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    setDetailError(null);
    fetchJson<ObsRunDetail>(observatoryRunDetailPath(selectedRunId))
      .then((d) => !cancelled && setDetail(d))
      .catch((e) => !cancelled && setDetailError(e instanceof Error ? e.message : String(e)));
    return () => {
      cancelled = true;
    };
  }, [selectedRunId]);

  useEffect(() => {
    if (!selectedRunId || !compareRunId) {
      setDiff(null);
      return;
    }
    let cancelled = false;
    setDiffError(null);
    fetchJson<ObsRunDiff>(observatoryRunDiffPath(selectedRunId, compareRunId))
      .then((d) => !cancelled && setDiff(d))
      .catch((e) => !cancelled && setDiffError(e instanceof Error ? e.message : String(e)));
    return () => {
      cancelled = true;
    };
  }, [selectedRunId, compareRunId]);

  return (
    <div className="obs-runs-lens" data-testid="runs-lens">
      <PanelCard title="Runs" subdued>
        {loading && <div className="obs-empty">Loading runs…</div>}
        {error && <div className="obs-error">{error}</div>}
        {!loading && !error && (
          <div className="table-wrap">
            <table className="picks-table" data-testid="runs-table">
              <thead>
                <tr>
                  <th>Run</th>
                  <th>Created</th>
                  <th>Watermark</th>
                  <th>Quality</th>
                  <th>Lifecycle</th>
                  <th style={{ textAlign: "right" }}>Rows</th>
                  <th>Select</th>
                </tr>
              </thead>
              <tbody>
                {(runs?.runs ?? []).map((r) => (
                  <tr key={r.run_id} className={r.run_id === selectedRunId ? "is-active" : ""}>
                    <td><code>{r.run_id}</code></td>
                    <td>{formatDateTime(r.created_at)}</td>
                    <td>{r.market_watermark || "—"}</td>
                    <td>{humanizeEnum(r.quality_state)}</td>
                    <td>{humanizeEnum(r.lifecycle_state)}</td>
                    <td style={{ textAlign: "right" }}>{r.canonical_rows ?? "—"}</td>
                    <td>
                      <div className="obs-run-actions">
                        <button type="button" className="button button--ghost" onClick={() => onSelectRun(r.run_id || null)}>
                          Base
                        </button>
                        <button type="button" className="button button--ghost" onClick={() => onCompareRun(r.run_id || null)}>
                          Compare
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
                {(runs?.runs ?? []).length === 0 && (
                  <tr><td colSpan={7} className="obs-empty">No runs in catalog.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}
        {runs?.catalog_fingerprint && (
          <div className="obs-runs__fingerprint">catalog fingerprint {runs.catalog_fingerprint.slice(0, 16)}</div>
        )}
      </PanelCard>

      {selectedRunId && (
        <PanelCard title={`Run detail · ${selectedRunId}`} subdued>
          {detailError && <div className="obs-error">{detailError}</div>}
          {detail && (
            <div data-testid="run-detail">
              <div className="obs-detail-grid">
                <Detail label="Watermark" value={detail.market_watermark} />
                <Detail label="Rows" value={detail.canonical_rows != null ? String(detail.canonical_rows) : null} />
                <Detail label="Data readiness" value={humanizeEnum(detail.data_readiness)} />
                <Detail label="Quality" value={humanizeEnum(detail.quality_state)} />
                <Detail label="Lifecycle" value={humanizeEnum(detail.lifecycle_state)} />
                <Detail label="Acquisition" value={humanizeEnum(detail.acquisition_state)} />
                <Detail label="Code revision" value={detail.code_revision} />
              </div>
              {/* Historical certification vs current compatibility are separate. */}
              <div className="obs-cert-split" data-testid="cert-split">
                <div className="obs-cert-split__col">
                  <div className="obs-cert-split__title">Historical certification</div>
                  <StatusPill label={`published lifecycle: ${humanizeEnum(detail.lifecycle_state)}`} tone="info" subtle />
                  <p className="obs-lens__hint">Recorded at publish time. Not overwritten by later code changes.</p>
                </div>
                <div className="obs-cert-split__col">
                  <div className="obs-cert-split__title">Current compatibility</div>
                  <StatusPill label="re-evaluated separately" tone="muted" subtle />
                  <p className="obs-lens__hint">A replay mismatch changes compatibility only, never the historical fact.</p>
                </div>
              </div>
              {(detail.artifact_refs ?? []).length > 0 && (
                <div className="obs-artifact-list">
                  <div className="obs-cert-split__title">Artifacts</div>
                  <ul className="obs-code-list">
                    {(detail.artifact_refs ?? []).map((a) => (
                      <li key={a.name}><code>{a.name}</code> · {a.sha256?.slice(0, 12)}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </PanelCard>
      )}

      {selectedRunId && compareRunId && (
        <PanelCard title={`Run diff · ${selectedRunId} → ${compareRunId}`} subdued>
          {diffError && <div className="obs-error">{diffError}</div>}
          {diff && (
            <div data-testid="run-diff">
              <div className="obs-diff-flags">
                <StatusPill label={`code ${diff.code_changed ? "changed" : "same"}`} tone={diff.code_changed ? "warn" : "muted"} subtle />
                <StatusPill label={`config ${diff.config_changed ? "changed" : "same"}`} tone={diff.config_changed ? "warn" : "muted"} subtle />
                <StatusPill label={`schema ${diff.schema_changed ? "changed" : "same"}`} tone={diff.schema_changed ? "warn" : "muted"} subtle />
              </div>
              <div className="obs-diff-grid">
                <DiffCol title="Added dates" items={diff.added_dates ?? []} icon="+" />
                <DiffCol title="Removed dates" items={diff.removed_dates ?? []} icon="−" />
                <DiffCol
                  title="Changed dates"
                  items={(diff.changed_dates ?? []).map((c) => `${c.date} (${c.base_close}→${c.compare_close})`)}
                  icon="◆"
                />
              </div>
              {Object.keys(diff.gate_changes ?? {}).length > 0 && (
                <div className="obs-gate-changes">
                  <div className="obs-cert-split__title">Gate changes</div>
                  <ul className="obs-kv-list">
                    {Object.entries(diff.gate_changes ?? {}).map(([gate, change]) => (
                      <li key={gate}>
                        <span className="obs-kv-key">{humanizeEnum(gate)}</span>
                        <span className="obs-kv-val">
                          {JSON.stringify(change.base)} → {JSON.stringify(change.compare)}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </PanelCard>
      )}
    </div>
  );
}

function Detail({ label, value }: { label: string; value?: string | null }) {
  return (
    <div className="obs-detail">
      <div className="obs-detail__label">{label}</div>
      <div className="obs-detail__value">{value || "—"}</div>
    </div>
  );
}

function DiffCol({ title, items, icon }: { title: string; items: string[]; icon: string }) {
  return (
    <div className="obs-diff-col">
      <div className="obs-diff-col__title">
        {title} <span className="obs-diff-col__count">({items.length})</span>
      </div>
      {items.length === 0 ? (
        <div className="obs-empty">none</div>
      ) : (
        <ul className="obs-diff-col__list">
          {items.slice(0, 30).map((it) => (
            <li key={it}>
              <span aria-hidden="true">{icon}</span> {it}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
