import type { CandidateRow, DecisionExplanation } from "../lib/api";
import { formatConfidence, shortText } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { getGateStatusText } from "../lib/statusText";
import { ActionChip } from "./ActionChip";
import { EmptyState } from "./EmptyState";
import { ErrorState } from "./ErrorState";
import { LoadingSkeleton } from "./LoadingSkeleton";
import { PanelCard } from "./PanelCard";
import { StatusPill } from "./StatusPill";
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
  const { locale, t } = useI18n();
  const constrainedNoAction = String(candidate?.action || explanation?.action || "").toUpperCase() === "NO_ACTION";
  const readinessSemantic = getGateStatusText(locale, constrainedNoAction ? "partial" : "ok");
  if (!candidate) {
    return (
      <PanelCard title={t("candidate.quickReview")} eyebrow={t("candidate.selection")}>
        <EmptyState
          title={t("candidate.pickOne")}
          body={t("candidate.pickOneCopy")}
        />
      </PanelCard>
    );
  }

  if (loading && !explanation) {
    return (
      <PanelCard title={t("candidate.quickReview")} eyebrow={candidate.symbol}>
        <LoadingSkeleton variant="panel" />
      </PanelCard>
    );
  }

  if (error && !explanation) {
    return (
      <PanelCard title={t("candidate.quickReview")} eyebrow={candidate.symbol}>
        <ErrorState
          title={t("candidate.reviewUnavailable")}
          body={t("candidate.reviewUnavailableCopy")}
          detail={error}
          action={
            <div className="state-card__button-row">
              <button type="button" className="button button--ghost" onClick={onRetry}>
                {t("common.retry")}
              </button>
              <button type="button" className="button button--ghost" onClick={onOpenOps}>
                {t("common.openOps")}
              </button>
            </div>
          }
        />
      </PanelCard>
    );
  }

  return (
    <PanelCard title={t("candidate.quickReview")} eyebrow={candidate.symbol} className="candidate-quick-panel">
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

      {stale && <div className="candidate-quick-panel__stale">{t("common.cachedExplanation")}</div>}

      <div className="candidate-quick-panel__readiness">
        <StatusPill label={readinessSemantic.label} tone={readinessSemantic.tone} subtle />
        <span>{constrainedNoAction ? t("candidate.constrainedNoAction") : readinessSemantic.description}</span>
      </div>

      <div className="candidate-quick-panel__section">
        <div className="candidate-quick-panel__label">{t("candidate.evidenceFor")}</div>
        <ul className="clean-list">
          {(explanation?.evidence_for || []).slice(0, 3).map((item, index) => (
            <li key={`${item.description}-${index}`}>
              <strong>{item.source || t("common.signal")}</strong> {item.description}
            </li>
          ))}
        </ul>
      </div>

      <div className="candidate-quick-panel__section">
        <div className="candidate-quick-panel__label">{t("candidate.evidenceAgainst")}</div>
        <ul className="clean-list clean-list--negative">
          {(explanation?.evidence_against || []).slice(0, 2).map((item, index) => (
            <li key={`${item.description}-${index}`}>
              <strong>{item.source || t("common.signal")}</strong> {item.description}
            </li>
          ))}
        </ul>
      </div>

      <div className="candidate-quick-panel__section">
        <div className="candidate-quick-panel__label">{t("candidate.invalidators")}</div>
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
          {t("common.openWorkspace")}
        </button>
        <button type="button" className="button button--ghost" onClick={onOpenOps}>
          {t("common.openOps")}
        </button>
      </div>
    </PanelCard>
  );
}
