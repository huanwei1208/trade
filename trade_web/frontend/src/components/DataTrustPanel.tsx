import type { BeliefGraphResponse, DecisionExplanation, KlineResponse, WorldState } from "../lib/api";
import { formatPercent } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { getDatasetText, getWorldStateLabel } from "../lib/statusText";
import { TrustBadge } from "./TrustBadge";

type Props = {
  explanation?: DecisionExplanation | null;
  state?: WorldState | null;
  kline?: KlineResponse | null;
  beliefGraph?: BeliefGraphResponse | null;
};

export function DataTrustPanel({ explanation, state, kline, beliefGraph }: Props) {
  const { locale, t } = useI18n();

  const dqs = state?.data_quality_state;
  const hasDqs = Boolean(
    dqs && (dqs.missing_datasets || dqs.stale_datasets || typeof dqs.freshness_score === "number" || typeof dqs.score === "number")
  );

  const trustComponents = Object.entries(explanation?.trust?.components || {});
  const hasTrust = Boolean(explanation?.trust);

  const subBeliefs = beliefGraph?.sub_beliefs || [];

  return (
    <div className="data-trust-panel">
      {/* ── Trust Summary ─────────────────────────────────────────────── */}
      {hasTrust && (
        <section className="data-trust-panel__section">
          <div className="data-trust-panel__section-title">{t("symbol.dataTrust.trustSummary")}</div>
          <div className="data-trust-panel__trust-row">
            <TrustBadge
              score={explanation?.trust?.trust_score}
              level={explanation?.trust?.trust_level}
              detailed
            />
          </div>
          {trustComponents.length > 0 && (
            <div className="trust-components">
              {trustComponents.map(([key, value]) => (
                <div className="trust-components__row" key={key}>
                  <span>{key.replace(/_/g, " ")}</span>
                  <div className="trust-components__bar">
                    <div
                      className="trust-components__fill"
                      style={{ width: `${Math.max(4, Number(value) * 100)}%` }}
                    />
                  </div>
                  <strong>{formatPercent(value, 0)}</strong>
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      {/* ── Sub-Belief Provenance ─────────────────────────────────────── */}
      {subBeliefs.length > 0 && (
        <section className="data-trust-panel__section">
          <div className="data-trust-panel__section-title">{t("symbol.dataTrust.beliefProvenance")}</div>
          <div className="data-trust-panel__sub-beliefs">
            {subBeliefs.map((sub) => {
              const name = locale === "zh-CN" ? sub.name_zh : sub.name_en;
              return (
                <div key={sub.id} className="data-trust-panel__provenance-row">
                  <span className="data-trust-panel__provenance-name">{name || sub.id}</span>
                  <div className="trust-components__bar">
                    <div
                      className="trust-components__fill"
                      style={{ width: `${Math.max(4, (sub.score ?? 0) * 100)}%` }}
                    />
                  </div>
                  <strong>{formatPercent(sub.score ?? 0, 0)}</strong>
                </div>
              );
            })}
          </div>
        </section>
      )}

      {/* ── Data Quality State ────────────────────────────────────────── */}
      <section className="data-trust-panel__section">
        <div className="data-trust-panel__section-title">{t("symbol.dataQuality")}</div>
        {hasDqs ? (
          <div className="data-quality-table">
            {typeof dqs!.score === "number" && (
              <div className="data-quality-table__score-row">
                <span className="data-quality-table__score-label">{t("symbol.dataQualityScore")}</span>
                <strong className="data-quality-table__score-value">{formatPercent(dqs!.score, 0)}</strong>
              </div>
            )}
            {typeof dqs!.freshness_score === "number" && (
              <div className="data-quality-table__score-row">
                <span className="data-quality-table__score-label">{t("symbol.freshnessScore")}</span>
                <strong className="data-quality-table__score-value">{formatPercent(dqs!.freshness_score, 0)}</strong>
              </div>
            )}
            {(dqs!.missing_datasets || []).length > 0 && (
              <div className="data-quality-section">
                <div className="data-quality-section__label">{t("symbol.missingDatasets")}</div>
                <div className="tag-cluster">
                  {(dqs!.missing_datasets || []).map((ds) => (
                    <span className="tag-chip tag-chip--negative" key={ds}>{getDatasetText(locale, ds)}</span>
                  ))}
                </div>
              </div>
            )}
            {(dqs!.stale_datasets || []).length > 0 && (
              <div className="data-quality-section">
                <div className="data-quality-section__label">{t("symbol.staleDatasets")}</div>
                <div className="tag-cluster">
                  {(dqs!.stale_datasets || []).map((ds) => (
                    <span className="tag-chip tag-chip--warning" key={ds}>{getDatasetText(locale, ds)}</span>
                  ))}
                </div>
              </div>
            )}
            {(dqs!.missing_datasets || []).length === 0 && (dqs!.stale_datasets || []).length === 0 && (
              <div className="note-card">{t("symbol.noMissingDatasets")}</div>
            )}
            {dqs!.rationale && <div className="note-card note-card--warning">{dqs!.rationale}</div>}
          </div>
        ) : (
          <div className="note-stack">
            {(explanation?.data_quality_notes || []).map((item) => (
              <div className="note-card note-card--warning" key={item}>{item}</div>
            ))}
            {(explanation?.warnings || []).map((item) => (
              <div className="note-card note-card--danger" key={item}>{item}</div>
            ))}
            {!explanation?.data_quality_notes?.length && !explanation?.warnings?.length && (
              <div className="note-card">{t("symbol.noQualityWarnings")}</div>
            )}
          </div>
        )}
      </section>

      {/* ── World State ───────────────────────────────────────────────── */}
      {state && (
        <section className="data-trust-panel__section">
          <div className="data-trust-panel__section-title">{t("symbol.worldState")}</div>
          <div className="regime-grid">
            {(["market", "event", "sentiment", "technical", "liquidity", "uncertainty"] as const).map((key) => {
              const value = key === "uncertainty"
                ? state.uncertainty_level
                : state[`${key}_regime` as keyof WorldState] as string;
              return (
                <div className="regime-grid__item" key={key}>
                  <span>{t(`symbol.worldStateLabel.${key}`)}</span>
                  <strong>{getWorldStateLabel(locale, key, value)}</strong>
                </div>
              );
            })}
          </div>
        </section>
      )}

      {/* ── Input Warnings ────────────────────────────────────────────── */}
      {(explanation?.input_warnings || []).length > 0 && (
        <section className="data-trust-panel__section">
          <div className="data-trust-panel__section-title">{t("symbol.dataTrust.inputWarnings")}</div>
          <div className="note-stack">
            {(explanation?.input_warnings || []).map((item) => (
              <div className="note-card note-card--danger" key={item}>{item}</div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
