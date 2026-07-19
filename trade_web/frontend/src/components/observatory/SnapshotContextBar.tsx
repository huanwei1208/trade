import type { ReactNode } from "react";

import type { ObsContext } from "../../lib/api";
import { formatDateTime } from "../../lib/format";
import { humanizeEnum } from "../../lib/format";
import { StatusPill } from "../StatusPill";
import { purposeTone } from "../../lib/observatory";

// The Snapshot Context Bar (aka Truth Bar). Persistent across every lens.
// Requirement (docs/26 §11.2): it must show asset/instrument/quote/interval/
// timezone, expected latest bar, all three watermarks (Latest Observed /
// Evaluated Candidate / Formal), knowledge_as_of + rendered_at, freshness /
// compatibility / integrity, and purpose fitness chips. It must NOT be reduced
// to a single "updated time".

type SnapshotContextBarProps = {
  context: ObsContext | null | undefined;
  loading?: boolean;
  channelWatermarks?: {
    formal?: string | null;
    evaluated_candidate?: string | null;
    observed?: string | null;
  };
};

function toneForFreshness(state: string | undefined): "ok" | "warn" | "err" | "muted" {
  switch (state) {
    case "fresh":
      return "ok";
    case "stale":
      return "warn";
    case "unknown":
      return "muted";
    default:
      return "muted";
  }
}

function toneForCompatibility(state: string | undefined): "ok" | "warn" | "err" | "muted" {
  switch (state) {
    case "compatible":
      return "ok";
    case "contract_stale":
      return "warn";
    case "replay_mismatch":
      return "err";
    default:
      return "muted";
  }
}

function Field({ label, value, title }: { label: string; value: ReactNode; title?: string }) {
  return (
    <div className="obs-truthbar__field" title={title}>
      <div className="obs-truthbar__label">{label}</div>
      <div className="obs-truthbar__value">{value ?? "—"}</div>
    </div>
  );
}

export function SnapshotContextBar({ context, loading, channelWatermarks }: SnapshotContextBarProps) {
  const contract = context?.contract;
  const sem = context?.semantic_channels;
  const observedWm = channelWatermarks?.observed ?? sem?.observed?.watermark ?? null;
  const candidateWm = channelWatermarks?.evaluated_candidate ?? sem?.evaluated_candidate?.watermark ?? null;
  const formalWm = channelWatermarks?.formal ?? sem?.formal?.watermark ?? null;
  const knowledge = context?.effective_knowledge_cut || context?.requested_knowledge_as_of || "latest";

  return (
    <section className="obs-truthbar" aria-label="Snapshot context" data-testid="obs-truthbar">
      <div className="obs-truthbar__identity">
        <div className="obs-truthbar__symbol">{contract?.display_symbol || "BTC"}</div>
        <div className="obs-truthbar__contract">
          <span>{contract?.primary_instrument || "—"}</span>
          <span aria-hidden="true"> · </span>
          <span>{contract?.quote || "—"}</span>
          <span aria-hidden="true"> · </span>
          <span>{contract?.primary_interval || "—"}</span>
          <span aria-hidden="true"> · </span>
          <span>UTC</span>
        </div>
        <div className="obs-truthbar__providers">
          primary {contract?.primary_provider || "—"} · shadow {contract?.shadow_provider || "—"} (
          {contract?.shadow_instrument || "—"})
        </div>
      </div>

      <div className="obs-truthbar__grid">
        <Field label="Latest observed" value={<span data-testid="wm-observed">{observedWm || "—"}</span>} />
        <Field
          label="Evaluated candidate"
          value={<span data-testid="wm-candidate">{candidateWm || "—"}</span>}
        />
        <Field label="Formal baseline" value={<span data-testid="wm-formal">{formalWm || "—"}</span>} />
        <Field label="Knowledge as of" value={<span data-testid="knowledge-as-of">{knowledge}</span>} />
        <Field label="Rendered at" value={formatDateTime(context?.rendered_at)} />
        <Field label="Market watermark" value={context?.market_watermark || "—"} />
      </div>

      <div className="obs-truthbar__states" data-testid="obs-truthbar-states">
        <StatusPill
          label={`Freshness: ${humanizeEnum(context?.freshness_state)}`}
          tone={toneForFreshness(context?.freshness_state)}
          subtle
        />
        <StatusPill
          label={`Compatibility: ${humanizeEnum(context?.compatibility_state)}`}
          tone={toneForCompatibility(context?.compatibility_state)}
          subtle
        />
        <StatusPill label={`Quality: ${humanizeEnum(context?.quality_state)}`} tone="info" subtle />
        <StatusPill label={`Lifecycle: ${humanizeEnum(context?.lifecycle_state)}`} tone="info" subtle />
        <StatusPill label={`Acquisition: ${humanizeEnum(context?.acquisition_state)}`} tone="info" subtle />
      </div>

      <div className="obs-truthbar__purposes" aria-label="Purpose fitness" data-testid="obs-purpose-fitness">
        {(context?.purpose_fitness ?? []).map((pf) => (
          <span
            key={pf.purpose}
            className={`obs-purpose obs-purpose--${purposeTone(pf.status, pf.allowed)}`}
            title={(pf.reason_codes ?? []).join(", ")}
          >
            <span className="obs-purpose__icon" aria-hidden="true">
              {pf.allowed ? "✓" : "✕"}
            </span>
            <span className="obs-purpose__name">{humanizeEnum(pf.purpose)}</span>
            <span className="obs-purpose__status">{pf.allowed ? "allowed" : humanizeEnum(pf.status) || "blocked"}</span>
          </span>
        ))}
        {loading && !context && <span className="obs-truthbar__loading">Loading snapshot context…</span>}
      </div>
    </section>
  );
}
