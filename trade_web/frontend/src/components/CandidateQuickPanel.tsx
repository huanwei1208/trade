import type { CandidateRow, DecisionExplanation } from "../lib/api";
import { formatConfidence, shortText } from "../lib/format";
import { ActionChip } from "./ActionChip";
import { EmptyState } from "./EmptyState";
import { ErrorState } from "./ErrorState";
import { LoadingSkeleton } from "./LoadingSkeleton";
import { PanelCard } from "./PanelCard";
import { TrustBadge } from "./TrustBadge";

type CandidateQuickPanelProps = {
  candidate?: CandidateRow | null;
  explanation?: DecisionExplanation | null;
  loading: boolean;
  error?: string | null;
  stale?: boolean;
  onRetry: () => void;
  onOpenSymbol: (symbol: string) => void;
  onOpenOps: () => void;
};

export function CandidateQuickPanel({
  candidate,
  explanation,
  loading,
  error,
  stale,
  onRetry,
  onOpenSymbol,
  onOpenOps,
}: CandidateQuickPanelProps) {
  if (!candidate) {
    return (
      <PanelCard title="Quick review" eyebrow="Selection">
        <EmptyState
          title="Pick one candidate"
          body="Use this panel to stress-test the current thesis before opening the full symbol workspace."
        />
      </PanelCard>
    );
  }

  if (loading && !explanation) {
    return (
      <PanelCard title="Quick review" eyebrow={candidate.symbol}>
        <LoadingSkeleton variant="panel" />
      </PanelCard>
    );
  }

  if (error && !explanation) {
    return (
      <PanelCard title="Quick review" eyebrow={candidate.symbol}>
        <ErrorState
          title="Candidate review unavailable"
          body="The explanation service did not return a usable response. You can retry, or inspect Ops if the pipeline looks unhealthy."
          detail={error}
          action={
            <div className="state-card__button-row">
              <button type="button" className="button button--ghost" onClick={onRetry}>
                Retry
              </button>
              <button type="button" className="button button--ghost" onClick={onOpenOps}>
                Open Ops
              </button>
            </div>
          }
        />
      </PanelCard>
    );
  }

  return (
    <PanelCard title="Quick review" eyebrow={candidate.symbol} className="candidate-quick-panel">
      <div className="candidate-quick-panel__header">
        <div>
          <div className="candidate-quick-panel__symbol">
            {candidate.symbol}
            <span>{candidate.name || ""}</span>
          </div>
          <div className="candidate-quick-panel__copy">{shortText(explanation?.thesis || candidate.thesis || candidate.world_state_summary, 180)}</div>
        </div>
        <div className="candidate-quick-panel__meta">
          <ActionChip action={explanation?.action || candidate.action} />
          <TrustBadge score={candidate.trust_score || explanation?.trust?.trust_score} level={candidate.trust_level || explanation?.trust?.trust_level} />
          <div className="candidate-quick-panel__confidence">{formatConfidence(explanation?.action_confidence || candidate.confidence)}</div>
        </div>
      </div>

      {stale && <div className="candidate-quick-panel__stale">Showing cached explanation while retry is available.</div>}

      <div className="candidate-quick-panel__section">
        <div className="candidate-quick-panel__label">Evidence for</div>
        <ul className="clean-list">
          {(explanation?.evidence_for || []).slice(0, 3).map((item, index) => (
            <li key={`${item.description}-${index}`}>
              <strong>{item.source || "signal"}</strong> {item.description}
            </li>
          ))}
        </ul>
      </div>

      <div className="candidate-quick-panel__section">
        <div className="candidate-quick-panel__label">Evidence against</div>
        <ul className="clean-list clean-list--negative">
          {(explanation?.evidence_against || []).slice(0, 2).map((item, index) => (
            <li key={`${item.description}-${index}`}>
              <strong>{item.source || "signal"}</strong> {item.description}
            </li>
          ))}
        </ul>
      </div>

      <div className="candidate-quick-panel__section">
        <div className="candidate-quick-panel__label">Invalidators</div>
        <div className="tag-cluster">
          {(explanation?.invalidators || candidate.top_invalidators || []).slice(0, 4).map((item) => (
            <span className="tag-chip tag-chip--negative" key={item}>
              {item}
            </span>
          ))}
        </div>
      </div>

      <div className="candidate-quick-panel__footer">
        <button type="button" className="button button--primary" onClick={() => candidate.symbol && onOpenSymbol(candidate.symbol)}>
          Open full workspace
        </button>
      </div>
    </PanelCard>
  );
}
