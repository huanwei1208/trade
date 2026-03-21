import type { DecisionExplanation, KlineResponse, WorldState } from "../lib/api";
import { formatPercent, humanizeEnum } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { getActionText } from "../lib/statusText";
import { classNames } from "../lib/ui";
import { NextTriggerPanel } from "./NextTriggerPanel";
import { StatusPill } from "./StatusPill";
import { TrustBadge } from "./TrustBadge";

type ExplanationRailProps = {
  kline?: KlineResponse | null;
  explanation?: DecisionExplanation | null;
  state?: WorldState | null;
  activeEvidenceSource?: string | null;
  markerActive?: boolean;
  onEvidenceHover: (source: string | null) => void;
  onInvalidatorClick: () => void;
  onOpenReadiness?: () => void;
  onOpenRecovery?: () => void;
  onOpenEvidenceTab?: () => void;
  onOpenBeliefTab?: () => void;
  onOpenDataOpsTab?: () => void;
  /** Slim mode: hides scenario, trust components, and data quality sections */
  slim?: boolean;
};

type EvidenceSectionProps = {
  title: string;
  items: NonNullable<DecisionExplanation["evidence_for"]>;
  tone: "positive" | "negative";
  activeEvidenceSource?: string | null;
  markerActive?: boolean;
  onEvidenceHover: (source: string | null) => void;
};

function EvidenceSection({ title, items, tone, activeEvidenceSource, markerActive, onEvidenceHover }: EvidenceSectionProps) {
  const { locale, t } = useI18n();
  return (
    <section className="explanation-rail__section">
      <div className="explanation-rail__section-title">{title}</div>
      <div className="evidence-list">
        {items.map((item, index) => {
          const source = item.source || "signal";
          const eventLinked = markerActive && String(source).toLowerCase().includes("event");
          return (
            <button
              type="button"
              key={`${source}-${index}`}
              className={classNames("evidence-item", `evidence-item--${tone}`, (activeEvidenceSource === source || eventLinked) && "is-highlighted")}
              onMouseEnter={() => onEvidenceHover(source)}
              onMouseLeave={() => onEvidenceHover(null)}
            >
              <div className="evidence-item__head">
                <span className="evidence-item__source">{source}</span>
                <span className="evidence-item__weight">{formatPercent(item.weight, 0)}</span>
              </div>
              <div className="evidence-item__body">{item.description || t("common.noDetail")}</div>
            </button>
          );
        })}
      </div>
    </section>
  );
}

export function ExplanationRail({
  kline,
  explanation,
  state,
  activeEvidenceSource,
  markerActive,
  onEvidenceHover,
  onInvalidatorClick,
  onOpenReadiness,
  onOpenRecovery,
  onOpenEvidenceTab,
  onOpenBeliefTab,
  onOpenDataOpsTab,
  slim = false,
}: ExplanationRailProps) {
  const { locale, t } = useI18n();
  if (!explanation) {
    return null;
  }

  const scenario = explanation.scenario_summary;
  const trustComponents = Object.entries(explanation.trust?.components || {});

  return (
    <div className="explanation-rail">
      <div className="explanation-rail__sticky">
        <section className="explanation-rail__hero">
          <div className="explanation-rail__hero-top">
            <StatusPill label={getActionText(locale, explanation.action)} tone="info" />
            <TrustBadge score={explanation.trust?.trust_score} level={explanation.trust?.trust_level} detailed />
          </div>
          <div className="explanation-rail__hero-copy">{explanation.thesis || t("symbol.noThesis")}</div>
          <div className="tag-cluster">
            {(explanation.warnings || []).map((item) => (
              <span className="tag-chip tag-chip--warning" key={item}>
                {item}
              </span>
            ))}
          </div>
        </section>

        <EvidenceSection
          title={t("explain.evidenceFor")}
          items={explanation.evidence_for || []}
          tone="positive"
          activeEvidenceSource={activeEvidenceSource}
          markerActive={markerActive}
          onEvidenceHover={onEvidenceHover}
        />

        <EvidenceSection
          title={t("explain.evidenceAgainst")}
          items={explanation.evidence_against || []}
          tone="negative"
          activeEvidenceSource={activeEvidenceSource}
          markerActive={markerActive}
          onEvidenceHover={onEvidenceHover}
        />

        <section className="explanation-rail__section">
          <div className="explanation-rail__section-title">{t("explain.invalidators")}</div>
          <div className="tag-cluster">
            {(explanation.invalidators || []).map((item) => (
              <button type="button" className="tag-chip tag-chip--negative" key={item} onClick={onInvalidatorClick}>
                {item}
              </button>
            ))}
          </div>
        </section>

        <NextTriggerPanel
          kline={kline}
          explanation={explanation}
          state={state}
          onOpenReadiness={onOpenReadiness}
          onOpenRecovery={onOpenRecovery}
          onOpenEvidenceTab={onOpenEvidenceTab}
          onOpenBeliefTab={onOpenBeliefTab}
          onOpenDataOpsTab={onOpenDataOpsTab}
        />

        {!slim && scenario && (
          <section className="explanation-rail__section">
            <div className="explanation-rail__section-title">{t("explain.scenarioSummary")}</div>
            <div className="scenario-stack">
              {(["bull_case", "base_case", "bear_case"] as const).map((key) => {
                const item = scenario[key];
                if (!item) {
                  return null;
                }
                const dominant = scenario.dominant_scenario === item.label;
                const scenarioLabel = (() => {
                  const translated = t(`scenario.${key}`);
                  return translated !== `scenario.${key}` ? translated : humanizeEnum(item.label);
                })();
                return (
                  <div className={classNames("scenario-card", dominant && "is-dominant")} key={key}>
                    <div className="scenario-card__head">
                      <span>{scenarioLabel}</span>
                      <strong>{formatPercent(item.probability, 0)}</strong>
                    </div>
                    <div className="scenario-card__body">{item.thesis}</div>
                  </div>
                );
              })}
            </div>
          </section>
        )}

        {!slim && (
          <>
            <section className="explanation-rail__section">
              <div className="explanation-rail__section-title">{t("explain.dataTrustNotes")}</div>
              <div className="note-stack">
                {(explanation.data_quality_notes || []).map((item) => (
                  <div className="note-card note-card--warning" key={item}>
                    {item}
                  </div>
                ))}
                {(explanation.input_warnings || []).map((item) => (
                  <div className="note-card note-card--danger" key={item}>
                    {item}
                  </div>
                ))}
              </div>
            </section>

            <section className="explanation-rail__section">
              <div className="explanation-rail__section-title">{t("explain.trustComponents")}</div>
              <div className="trust-components">
                {trustComponents.length === 0 && <div className="note-card">{t("explain.noTrustVector")}</div>}
                {trustComponents.map(([key, value]) => (
                  <div className="trust-components__row" key={key}>
                    <span>{humanizeEnum(key)}</span>
                    <div className="trust-components__bar">
                      <div className="trust-components__fill" style={{ width: `${Math.max(4, Number(value) * 100)}%` }} />
                    </div>
                    <strong>{formatPercent(value, 0)}</strong>
                  </div>
                ))}
              </div>
            </section>
          </>
        )}
      </div>
    </div>
  );
}
