/**
 * CandidateQuickPanel — quick review panel for a single candidate.
 *
 * Factor placement rule: this panel shows factor SUMMARY only (chips/short list).
 * Full factor decomposition belongs on the Symbol page workspace.
 */
import type { CandidateRow, DecisionExplanation } from "../lib/api";
import { formatConfidence, formatPercent, formatScore, humanizeEnum, shortText } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { getGateStatusText } from "../lib/statusText";
import { classNames } from "../lib/ui";
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
  onOpenReadiness: () => void;
  onOpenRecovery: () => void;
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
  onOpenReadiness,
  onOpenRecovery,
}: CandidateQuickPanelProps) {
  const { locale, t } = useI18n();
  const constrainedNoAction = String(candidate?.action || explanation?.action || "").toUpperCase() === "NO_ACTION";
  const readinessSemantic = getGateStatusText(locale, constrainedNoAction ? "partial" : "ok");
  // Trust components: prefer explanation, but note this is symbol-level trust
  const trustComponents = Object.entries(explanation?.trust?.components || {});
  const hasQualityIssues = (explanation?.data_quality_notes || []).length > 0 || (explanation?.input_warnings || []).length > 0;

  // Belief values: use explanation or candidate fallback
  const beliefMu = candidate?.belief_mu;
  const beliefDelta = candidate?.belief_delta_mu;
  const risk = candidate?.risk;
  const recState = candidate?.recommendation_state;
  const dataRisk = candidate?.data_risk_flag;

  // Factor summary: from candidate (signals-page) or explanation evidence (explain endpoint)
  const factorPos = candidate?.factor_summary?.positive?.filter(Boolean) || [];
  const factorNeg = candidate?.factor_summary?.negative?.filter(Boolean) || [];
  const hasFactorSummary = factorPos.length > 0 || factorNeg.length > 0;

  if (!candidate) {
    return (
      <PanelCard title={t("candidate.quickReview")} eyebrow={t("candidate.selection")}>
        <EmptyState title={t("candidate.pickOne")} body={t("candidate.pickOneCopy")} />
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
          {/* Symbol-level trust — distinct from system/portfolio trust in Today diagnostics */}
          <TrustBadge score={candidate.trust_score || explanation?.trust?.trust_score} level={candidate.trust_level || explanation?.trust?.trust_level} />
          <div className="candidate-quick-panel__confidence">{formatConfidence(explanation?.action_confidence || candidate.confidence)}</div>
        </div>
      </div>

      {stale && <div className="candidate-quick-panel__stale">{t("common.cachedExplanation")}</div>}

      {/* Recommendation state badge */}
      {recState && recState !== "ACTIONABLE" && (
        <div className={classNames(
          "candidate-quick-panel__rec-state",
          recState === "CONSTRAINED" ? "rec-state--constrained" : "rec-state--browse"
        )}>
          <span>{recState === "CONSTRAINED" ? t("candidates.constrained") : t("candidates.browseOnlyLabel")}</span>
          {dataRisk && <span className="candidate-quick-panel__data-risk"> · {dataRisk}</span>}
        </div>
      )}

      <div className="candidate-quick-panel__readiness">
        <StatusPill label={readinessSemantic.label} tone={readinessSemantic.tone} subtle />
        <span>{constrainedNoAction ? t("candidate.constrainedNoAction") : readinessSemantic.description}</span>
      </div>

      {/* Quantitative summary row */}
      <div className="candidate-quick-panel__quant-row">
        {beliefMu !== undefined && beliefMu !== null && (
          <div className="qp-metric">
            <div className="qp-metric__label">{t("candidates.table.belief")}</div>
            <div className={classNames("qp-metric__value", beliefMu > 0.1 ? "is-positive" : beliefMu < -0.1 ? "is-negative" : "")}>
              {beliefMu >= 0 ? "+" : ""}{formatScore(beliefMu, 3)}
            </div>
          </div>
        )}
        {beliefDelta !== undefined && beliefDelta !== null && (
          <div className="qp-metric">
            <div className="qp-metric__label">{t("candidates.table.delta")}</div>
            <div className={classNames("qp-metric__value belief-delta", Number(beliefDelta) >= 0 ? "is-positive" : "is-negative")}>
              {Number(beliefDelta) >= 0 ? "+" : ""}{formatScore(beliefDelta, 2)}μ
            </div>
          </div>
        )}
        {risk !== undefined && risk !== null && (
          <div className="qp-metric">
            <div className="qp-metric__label">{t("candidates.table.risk")}</div>
            <div className={classNames("qp-metric__value", risk > 0.6 ? "is-negative" : risk > 0.3 ? "" : "is-positive")}>
              {formatScore(risk, 2)}
            </div>
          </div>
        )}
      </div>

      {/* Data quality / risk — prominent when there are issues */}
      {(hasQualityIssues || dataRisk) && (
        <div className="candidate-quick-panel__section candidate-quick-panel__section--risk">
          <div className="candidate-quick-panel__label">{t("symbol.dataQualityTitle")}</div>
          <div className="quick-panel__quality-notes">
            {dataRisk && <div className="note-card note-card--warning">{dataRisk}</div>}
            {(explanation?.input_warnings || []).map((item) => (
              <div className="note-card note-card--danger" key={item}>{item}</div>
            ))}
            {(explanation?.data_quality_notes || []).map((item) => (
              <div className="note-card note-card--warning" key={item}>{item}</div>
            ))}
          </div>
        </div>
      )}

      {/* Factor summary — chips only, not full decomposition */}
      {hasFactorSummary && (
        <div className="candidate-quick-panel__section">
          <div className="candidate-quick-panel__label">{t("candidate.factorSummary")}</div>
          <div className="factor-summary-panel">
            {factorPos.length > 0 && (
              <div className="factor-summary-panel__group">
                <span className="factor-summary-panel__group-label">{t("candidate.factorPos")}</span>
                <div className="factor-chips">
                  {factorPos.map((f) => (
                    <span key={f} className="factor-chip factor-chip--positive" title={f}>{f}</span>
                  ))}
                </div>
              </div>
            )}
            {factorNeg.length > 0 && (
              <div className="factor-summary-panel__group">
                <span className="factor-summary-panel__group-label">{t("candidate.factorNeg")}</span>
                <div className="factor-chips">
                  {factorNeg.map((f) => (
                    <span key={f} className="factor-chip factor-chip--negative" title={f}>{f}</span>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

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

      {trustComponents.length > 0 && (
        <div className="candidate-quick-panel__section">
          {/* Label: "Symbol trust" to distinguish from portfolio/system trust shown in Today diagnostics */}
          <div className="candidate-quick-panel__label">{t("candidate.trustComponents")}</div>
          <div className="trust-breakdown">
            {trustComponents.map(([key, value]) => (
              <div className="trust-breakdown__row" key={key}>
                <span className="trust-breakdown__label">{humanizeEnum(key)}</span>
                <div className="trust-breakdown__bar-wrap">
                  <div className="trust-breakdown__bar">
                    <div className="trust-breakdown__fill" style={{ width: `${Math.max(4, Number(value) * 100)}%` }} />
                  </div>
                  <span className="trust-breakdown__pct">{formatPercent(value, 0)}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="candidate-quick-panel__footer">
        <button type="button" className="button button--primary" onClick={() => candidate.symbol && onOpenSymbol(candidate.symbol)}>
          {t("common.openWorkspace")}
        </button>
        <div className="candidate-quick-panel__footer-actions">
          <button type="button" className="button button--ghost" onClick={onOpenReadiness}>
            {t("common.openReadiness")}
          </button>
          <button type="button" className="button button--ghost" onClick={onOpenRecovery}>
            {t("common.openRecovery")}
          </button>
        </div>
      </div>
    </PanelCard>
  );
}
