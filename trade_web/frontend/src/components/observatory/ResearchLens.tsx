import { useState } from "react";

import type { ObsHypothesis, ObsResearchRun } from "../../lib/api";
import { humanizeEnum } from "../../lib/format";
import { PanelCard } from "../PanelCard";
import { StatusPill } from "../StatusPill";
import { readMetricString } from "../../lib/observatory";

// Research lens (docs/26 §15, WP8). Shows H1 id/version/statement, dataset
// snapshot + knowledge_as_of, effect ratio, bootstrap CI, BH q-value, status,
// reason codes / evidence. The future-outcome region has a DISTINCT background
// and must NOT appear in Observe/Investigate (it only lives here). When data is
// insufficient we honestly render insufficient / blocked.
//
// "Open in Lab" is DISPLAY ONLY: it shows a deep link + params + a copyable
// command that fixes snapshot_id. It never starts a process, creates a notebook,
// or registers a run.

type ResearchLensProps = {
  hypothesis: ObsHypothesis | null | undefined;
  researchRun: ObsResearchRun | null | undefined;
  loading?: boolean;
  error?: string | null;
};

const RESEARCH_TONE: Record<string, "ok" | "warn" | "err" | "info" | "muted"> = {
  validated: "ok",
  candidate: "info",
  monitoring: "info",
  rejected: "err",
  blocked: "warn",
  exploratory: "muted",
  eligible: "info",
  unknown: "muted",
};

export function ResearchLens({ hypothesis, researchRun, loading, error }: ResearchLensProps) {
  const state = researchRun?.research_state?.trim() || "unknown";
  const insufficient = state === "blocked" || state === "unknown";
  const metrics = researchRun?.metrics;
  const researchRunVersion = researchRun?.hypothesis_version;
  const hypothesisVersion = hypothesis?.hypothesis_version;
  const provenanceComplete =
    Boolean(researchRun?.dataset_snapshot_id) &&
    Boolean(researchRun?.knowledge_as_of) &&
    Boolean(researchRunVersion?.trim()) &&
    Boolean(hypothesisVersion?.trim()) &&
    researchRunVersion === hypothesisVersion;

  return (
    <div className="obs-research-lens" data-testid="research-lens">
      <div className="obs-research__scope" data-testid="research-scope-notice">
        Separately scoped research evidence — not confirmation of the selected Market snapshot.
      </div>
      <PanelCard title="Hypothesis H1" subdued>
        {loading && <div className="obs-empty">Loading hypothesis…</div>}
        {error && <div className="obs-error">{error}</div>}
        {!loading && !error && (
          <div data-testid="research-hypothesis">
            <div className="obs-research__head">
              <span className="obs-research__id">
                {hypothesis?.hypothesis_id || "H1"} · {hypothesis?.hypothesis_version || "—"}
              </span>
              <StatusPill
                label={`State: ${humanizeEnum(state)}`}
                tone={RESEARCH_TONE[state] || "muted"}
                subtle
              />
              <StatusPill
                label={hypothesis?.directional ? "directional" : "non-directional"}
                tone="muted"
                subtle
              />
            </div>
            <p className="obs-research__statement">{hypothesis?.statement || "—"}</p>
            <div className="obs-detail-grid">
              <Detail label="Dataset snapshot" value={researchRun?.dataset_snapshot_id} />
              <Detail label="Knowledge as of" value={researchRun?.knowledge_as_of} />
              <Detail label="Validation run" value={researchRun?.validation_run_id} />
              <Detail label="Generation" value={researchRun?.generation_id} />
            </div>
          </div>
        )}
      </PanelCard>

      <PanelCard title="Effect & confidence" subdued>
        {insufficient ? (
          <div className="obs-research__insufficient" data-testid="research-insufficient">
            <StatusPill label={`Research ${humanizeEnum(state)}`} tone="warn" subtle />
            <p className="obs-lens__hint">
              Data is insufficient to present a validated effect. The system does not fabricate a
              result — this is an honest insufficient / blocked state.
            </p>
          </div>
        ) : (
          <div className="obs-metric-grid" data-testid="research-metrics">
            <Metric label="Effect ratio" value={readMetricString(metrics, "effect_ratio")} />
            <Metric label="CI low" value={readMetricString(metrics, "ci_low")} />
            <Metric label="CI high" value={readMetricString(metrics, "ci_high")} />
            <Metric label="BH q-value" value={readMetricString(metrics, "q_value")} />
            <Metric label="Sample size" value={readMetricString(metrics, "sample_size")} />
            <Metric
              label="Data readiness"
              value={humanizeEnum(readMetricString(metrics, "data_readiness") || undefined)}
            />
          </div>
        )}
      </PanelCard>

      {/* Future-outcome region: distinct background + label. NEVER in Observe. */}
      <PanelCard title="Future outcome region" subdued className="obs-future-region">
        <div className="obs-future" data-testid="future-outcome-region" data-future-region="true">
          <div className="obs-future__banner">
            <span aria-hidden="true">⧉</span> FUTURE OUTCOME · research-only view
          </div>
          <p className="obs-lens__hint">
            Future-outcome evidence appears here only when a separately scoped, provenance-bound
            research receipt supplies it. This region is intentionally distinct from Market views.
          </p>
          <div className="obs-empty" data-testid="research-distribution-unavailable">
            Fold and distribution evidence is unavailable because this research receipt does not
            provide immutable, provenance-bound distribution values.
          </div>
        </div>
      </PanelCard>

      <OpenInLab
        snapshotId={researchRun?.dataset_snapshot_id}
        knowledgeAsOf={researchRun?.knowledge_as_of}
        hypothesisVersion={researchRun?.hypothesis_version}
        provenanceComplete={provenanceComplete}
      />

      {(researchRun?.evidence_refs ?? []).length > 0 && (
        <PanelCard title="Evidence" subdued>
          <ul className="obs-code-list" data-testid="research-evidence">
            {(researchRun?.evidence_refs ?? []).map((ref) => (
              <li key={ref}>
                <code>{ref}</code>
              </li>
            ))}
          </ul>
        </PanelCard>
      )}
    </div>
  );
}

function OpenInLab({
  snapshotId,
  knowledgeAsOf,
  hypothesisVersion,
  provenanceComplete,
}: {
  snapshotId?: string | null;
  knowledgeAsOf?: string | null;
  hypothesisVersion?: string | null;
  provenanceComplete: boolean;
}) {
  const [open, setOpen] = useState(false);
  const canOpen = provenanceComplete;
  const params = {
    asset: "crypto.BTC",
    snapshot_id: snapshotId,
    knowledge_as_of: knowledgeAsOf,
    hypothesis_version: hypothesisVersion,
  };
  const command = `trade research btc run --hypothesis H1 --snapshot-id ${params.snapshot_id} --dry-run`;
  const deepLink = `research/notebooks/btc_h1_observatory.py --snapshot-id ${params.snapshot_id}`;

  return (
    <PanelCard
      title="Open in Lab"
      subdued
      className="obs-open-lab"
      actions={
        <button
          type="button"
          className="button button--primary"
          disabled={!canOpen}
          onClick={() => setOpen((v) => !v)}
          data-testid="open-in-lab-button"
        >
          {open ? "Hide deep link" : "Open in Lab"}
        </button>
      }
    >
      <p className="obs-lens__hint">
        Display only. This shows a deep link, param file, and a copyable command that fixes the
        snapshot_id. It does NOT start a process, create a notebook, or register a run.
      </p>
      {!canOpen && (
        <div className="obs-empty" data-testid="open-in-lab-unavailable">
          Complete matched provenance is unavailable — cannot produce a reproducible deep link.
        </div>
      )}
      {open && canOpen && (
        <div className="obs-open-lab__body" data-testid="open-in-lab-panel">
          <div className="obs-open-lab__block">
            <div className="obs-cert-split__title">Frozen parameters</div>
            <pre className="obs-code-block">{JSON.stringify(params, null, 2)}</pre>
          </div>
          <div className="obs-open-lab__block">
            <div className="obs-cert-split__title">Reproducible command</div>
            <pre className="obs-code-block" data-testid="open-in-lab-command">
              {command}
            </pre>
          </div>
          <div className="obs-open-lab__block">
            <div className="obs-cert-split__title">Notebook deep link</div>
            <pre className="obs-code-block">{deepLink}</pre>
          </div>
        </div>
      )}
    </PanelCard>
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

function Metric({ label, value }: { label: string; value?: string | null }) {
  return (
    <div className="obs-metric">
      <div className="obs-metric__label">{label}</div>
      <div className="obs-metric__value">{value || "—"}</div>
    </div>
  );
}
