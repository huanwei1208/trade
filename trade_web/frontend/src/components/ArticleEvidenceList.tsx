import type { SymbolAttentionItem, SymbolEvidenceItem, SymbolMarketEvent } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { classNames } from "../lib/ui";

type Props = {
  marketEvents?: SymbolMarketEvent[];
  evidenceItems?: SymbolEvidenceItem[];
  attentionItems?: SymbolAttentionItem[];
  loading?: boolean;
};

function sentimentTone(score?: number | null): "positive" | "negative" | "neutral" {
  if (score == null) return "neutral";
  if (score > 0.1) return "positive";
  if (score < -0.1) return "negative";
  return "neutral";
}

function directionTone(direction?: number | null): "positive" | "negative" | "neutral" {
  if (direction == null) return "neutral";
  if (direction > 0.05) return "positive";
  if (direction < -0.05) return "negative";
  return "neutral";
}

export function ArticleEvidenceList({ marketEvents = [], evidenceItems = [], attentionItems = [], loading }: Props) {
  const { t } = useI18n();

  if (loading) {
    return <div className="evidence-list-skeleton">{t("common.loading")}</div>;
  }

  const hasAny = marketEvents.length > 0 || evidenceItems.length > 0 || attentionItems.length > 0;

  if (!hasAny) {
    return (
      <div className="evidence-list-empty">
        <div className="evidence-list-empty__icon">—</div>
        <div className="evidence-list-empty__text">{t("symbol.evidence.noEvents")}</div>
      </div>
    );
  }

  return (
    <div className="article-evidence-list">
      {/* Market events section */}
      {marketEvents.length > 0 && (
        <section className="article-evidence-list__section">
          <div className="article-evidence-list__section-title">{t("symbol.evidence.marketEvents")}</div>
          <div className="article-evidence-list__cards">
            {marketEvents.map((ev) => {
              const tone = sentimentTone(ev.sentiment_score);
              return (
                <div key={ev.id} className={classNames("event-card", `event-card--${tone}`)}>
                  <div className="event-card__head">
                    <span className="event-card__type">{ev.event_type || "event"}</span>
                    <span className="event-card__entity">{ev.entity_id || ""}</span>
                    <span className="event-card__date">{ev.date || ""}</span>
                  </div>
                  {ev.summary && <div className="event-card__body">{ev.summary}</div>}
                  <div className="event-card__meta">
                    {ev.sentiment_score != null && (
                      <span className={`event-card__sentiment event-card__sentiment--${tone}`}>
                        {ev.sentiment_score > 0 ? "+" : ""}{ev.sentiment_score.toFixed(2)}
                      </span>
                    )}
                    {ev.magnitude != null && ev.magnitude > 0 && (
                      <span className="event-card__magnitude">{t("symbol.evidence.magnitude")}: {ev.magnitude.toFixed(2)}</span>
                    )}
                    {ev.news_volume != null && ev.news_volume > 0 && (
                      <span className="event-card__volume">{t("symbol.evidence.articles")}: {ev.news_volume}</span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      )}

      {/* Evidence rows section */}
      {evidenceItems.length > 0 && (
        <section className="article-evidence-list__section">
          <div className="article-evidence-list__section-title">{t("symbol.evidence.signalEvidence")}</div>
          <div className="article-evidence-list__cards">
            {evidenceItems.map((ev) => {
              const tone = directionTone(ev.direction);
              return (
                <div key={ev.id} className={classNames("event-card event-card--compact", `event-card--${tone}`)}>
                  <div className="event-card__head">
                    <span className="event-card__type">{ev.evidence_type || "signal"}</span>
                    <span className="event-card__date">{ev.date || ""}</span>
                    <span className={`event-card__sentiment event-card__sentiment--${tone}`}>
                      {(ev.direction ?? 0) > 0 ? "▲" : (ev.direction ?? 0) < 0 ? "▼" : "—"}
                      {ev.direction != null ? ` ${Math.abs(ev.direction).toFixed(2)}` : ""}
                    </span>
                  </div>
                  <div className="event-card__body event-card__body--meta">
                    <span>{t("symbol.evidence.strength")}: {(ev.strength ?? 0).toFixed(2)}</span>
                    <span>{t("symbol.evidence.reliability")}: {(ev.reliability ?? 0).toFixed(2)}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      )}

      {/* Attention / factor signals */}
      {attentionItems.length > 0 && (
        <section className="article-evidence-list__section">
          <div className="article-evidence-list__section-title">{t("symbol.evidence.attentionFactors")}</div>
          <div className="article-evidence-list__attention-rows">
            {attentionItems.map((a) => {
              const tone = directionTone(a.direction);
              return (
                <div key={a.id} className="attention-row">
                  <span className="attention-row__type">{a.evidence_type || "factor"}</span>
                  <div className="attention-row__bar-wrap">
                    <div
                      className="attention-row__bar"
                      style={{ width: `${Math.min(100, (a.weight ?? 0) * 500)}%` }}
                    />
                  </div>
                  <span className="attention-row__weight">{((a.weight ?? 0) * 100).toFixed(1)}%</span>
                  <span className={`attention-row__dir attention-row__dir--${tone}`}>
                    {(a.direction ?? 0) > 0 ? "▲" : (a.direction ?? 0) < 0 ? "▼" : "—"}
                  </span>
                </div>
              );
            })}
          </div>
        </section>
      )}
    </div>
  );
}
