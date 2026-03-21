import type { DecisionExplanation, KlineResponse, WorldState } from "../lib/api";
import { buildNextTriggerView, type NextTriggerActionId, type NextTriggerType } from "../lib/nextTriggers";
import { useI18n } from "../lib/i18n";
import { classNames } from "../lib/ui";
import { StatusPill } from "./StatusPill";

type NextTriggerPanelProps = {
  kline?: KlineResponse | null;
  explanation?: DecisionExplanation | null;
  state?: WorldState | null;
  onOpenReadiness?: () => void;
  onOpenRecovery?: () => void;
  onOpenEvidenceTab?: () => void;
  onOpenBeliefTab?: () => void;
  onOpenDataOpsTab?: () => void;
};

function getTypeTone(type: NextTriggerType) {
  switch (type) {
    case "auto_market":
      return "info" as const;
    case "auto_data":
      return "warn" as const;
    case "manual_recovery":
      return "err" as const;
    case "mixed":
      return "warn" as const;
    default:
      return "muted" as const;
  }
}

function getStatusTone(status: string) {
  switch (status) {
    case "met":
      return "ok" as const;
    case "near":
      return "warn" as const;
    case "blocked_by_data":
      return "err" as const;
    case "unmet":
      return "muted" as const;
    default:
      return "muted" as const;
  }
}

export function NextTriggerPanel({
  kline,
  explanation,
  state,
  onOpenReadiness,
  onOpenRecovery,
  onOpenEvidenceTab,
  onOpenBeliefTab,
  onOpenDataOpsTab,
}: NextTriggerPanelProps) {
  const { locale, t } = useI18n();
  const { waitingFor, availableActions } = buildNextTriggerView(locale, { kline, explanation, state });

  const handlers: Partial<Record<NextTriggerActionId, () => void>> = {
    openReadiness: onOpenReadiness,
    openRecovery: onOpenRecovery,
    openEvidenceTab: onOpenEvidenceTab,
    openBeliefTab: onOpenBeliefTab,
    openDataOpsTab: onOpenDataOpsTab,
  };

  const actionableItems = availableActions.filter((item) => handlers[item.id]);

  if (waitingFor.length === 0 && actionableItems.length === 0) {
    return null;
  }

  return (
    <>
      <section className="explanation-rail__section">
        <div className="explanation-rail__section-title">{t("explain.waitingFor")}</div>
        {waitingFor.length === 0 ? (
          <div className="note-card">{t("explain.noWaitingConditions")}</div>
        ) : (
          <div className="trigger-watch-list">
            {waitingFor.map((item) => (
              <div className="trigger-watch-card" key={item.key}>
                <div className="trigger-watch-card__head">
                  <div className="trigger-watch-card__title-wrap">
                    <div className="trigger-watch-card__title">{item.label}</div>
                    <div className="trigger-watch-card__badges">
                      <StatusPill label={item.typeLabel} tone={getTypeTone(item.type)} subtle />
                      <StatusPill label={item.statusLabel} tone={getStatusTone(item.status)} subtle />
                    </div>
                  </div>
                </div>
                <div className="trigger-watch-card__copy">{item.description}</div>
                {(item.currentLabel || item.targetLabel) && (
                  <div className="trigger-watch-card__metrics">
                    {item.currentLabel && (
                      <div className="trigger-watch-card__metric">
                        <span>{t("common.current")}</span>
                        <strong>{item.currentLabel}</strong>
                      </div>
                    )}
                    {item.targetLabel && (
                      <div className="trigger-watch-card__metric">
                        <span>{t("common.target")}</span>
                        <strong>{item.targetLabel}</strong>
                      </div>
                    )}
                  </div>
                )}
                {item.whyItMatters && <div className="trigger-watch-card__why">{item.whyItMatters}</div>}
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="explanation-rail__section">
        <div className="explanation-rail__section-title">{t("explain.whatYouCanDoNow")}</div>
        {actionableItems.length === 0 ? (
          <div className="note-card">{t("explain.noActionsAvailable")}</div>
        ) : (
          <div className="next-action-panel">
            {actionableItems.map((item) => (
              <button
                type="button"
                key={item.id}
                className={classNames("button", item.appearance === "primary" ? "button--primary" : "button--ghost", "next-action-panel__button")}
                onClick={handlers[item.id]}
              >
                <span className="next-action-panel__label">{item.label}</span>
                <span className="next-action-panel__desc">{item.description}</span>
              </button>
            ))}
          </div>
        )}
      </section>
    </>
  );
}
