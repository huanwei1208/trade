import type { DecisionExplanation, WorldState } from "../lib/api";
import { formatDate, formatPercent } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { getActionText, getConclusionModeText } from "../lib/statusText";
import { classNames } from "../lib/ui";
import { ActionChip } from "./ActionChip";
import { StatusPill } from "./StatusPill";
import { TrustBadge } from "./TrustBadge";

type SymbolDecisionPanelProps = {
  explanation?: DecisionExplanation | null;
  state?: WorldState | null;
  onOpenReadiness: () => void;
  onOpenRecovery: () => void;
};

export function SymbolDecisionPanel({
  explanation,
  state,
  onOpenReadiness,
  onOpenRecovery,
}: SymbolDecisionPanelProps) {
  const { locale, t } = useI18n();

  const action = explanation?.action || state?.state_summary;
  const confidence = explanation?.action_confidence;
  const trustScore = explanation?.trust?.trust_score ?? state?.trust_score;
  const trustLevel = explanation?.trust?.trust_level;
  const asOf = explanation?.as_of || state?.as_of_date;
  const blockers = state?.blockers || explanation?.warnings || [];
  const visibleBlockers = blockers.filter((b) => !b.startsWith("resolve:missing_datasets:"));
  const nextTriggers = explanation?.next_triggers || [];
  const isDegraded = Boolean(
    (explanation?.input_warnings?.length ?? 0) > 0 ||
    (explanation?.data_quality_notes ?? []).some((n) => n.includes("missing") || n.includes("stale"))
  );

  const conclusionMode = getConclusionModeText(locale, {
    global_blocked: Boolean(visibleBlockers.length || (explanation?.warnings?.length ?? 0) > 0),
    blockers: visibleBlockers,
  });

  const actionabilityTone = conclusionMode.tone;
  const actionabilityLabel =
    actionabilityTone === "err"
      ? t("symbol.decision.blocked")
      : actionabilityTone === "warn"
        ? t("symbol.decision.reviewOnly")
        : t("symbol.decision.actionable");

  return (
    <div className="symbol-decision-panel">
      <div className="symbol-decision-panel__title">{t("symbol.decision.title")}</div>

      {/* Hero: recommendation */}
      <div className="symbol-decision-panel__hero">
        <ActionChip action={explanation?.action} />
        {explanation?.action && (
          <span className="symbol-decision-panel__action-label">
            {getActionText(locale, explanation.action)}
          </span>
        )}
        {isDegraded && (
          <span className="symbol-decision-panel__degraded-badge">{t("symbol.decision.degraded")}</span>
        )}
      </div>

      {/* Actionability state */}
      <div className="symbol-decision-panel__actionability">
        <StatusPill label={actionabilityLabel} tone={actionabilityTone} />
        {asOf && (
          <span className="symbol-decision-panel__asof">
            {t("symbol.decision.asOf")} {formatDate(asOf, locale === "zh-CN" ? "zh-CN" : "en-US")}
          </span>
        )}
      </div>

      {/* Meta row: confidence + trust */}
      <div className="symbol-decision-panel__meta">
        {confidence && (
          <div className="symbol-decision-panel__meta-item">
            <span className="symbol-decision-panel__meta-label">{t("symbol.decision.confidence")}</span>
            <strong className="symbol-decision-panel__meta-value">{confidence}</strong>
          </div>
        )}
        <div className="symbol-decision-panel__meta-item">
          <span className="symbol-decision-panel__meta-label">{t("symbol.decision.trust")}</span>
          <TrustBadge score={trustScore} level={trustLevel} />
        </div>
        {trustScore !== undefined && (
          <span className="symbol-decision-panel__trust-pct">{formatPercent(trustScore, 0)}</span>
        )}
      </div>

      {/* Blockers */}
      {visibleBlockers.length > 0 ? (
        <div className="symbol-decision-panel__blockers">
          <div className="symbol-decision-panel__blockers-label">{t("symbol.decision.blockers")}</div>
          <div className="tag-cluster">
            {visibleBlockers.slice(0, 4).map((b) => (
              <span key={b} className="tag-chip tag-chip--negative">{b}</span>
            ))}
          </div>
        </div>
      ) : (
        <div className="symbol-decision-panel__no-blockers">{t("symbol.decision.noBlockers")}</div>
      )}

      {/* Next triggers */}
      {nextTriggers.length > 0 && (
        <div className="symbol-decision-panel__triggers">
          <div className="symbol-decision-panel__triggers-label">{t("symbol.decision.nextTrigger")}</div>
          <div className="tag-cluster">
            {nextTriggers.slice(0, 3).map((trig) => (
              <span key={trig} className="tag-chip">{trig}</span>
            ))}
          </div>
        </div>
      )}

      {/* Actions */}
      <div className="symbol-decision-panel__actions">
        <button type="button" className="button button--ghost" onClick={onOpenReadiness}>
          {t("symbol.inspectDayReadiness")}
        </button>
        <button type="button" className="button button--ghost" onClick={onOpenRecovery}>
          {t("symbol.openRecovery")}
        </button>
      </div>
    </div>
  );
}
