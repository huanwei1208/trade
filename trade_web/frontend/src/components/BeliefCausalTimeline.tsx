import type { BeliefGraphResponse, KlineResponse } from "../lib/api";
import { formatDate, formatPercent } from "../lib/format";
import { useI18n } from "../lib/i18n";

type Props = {
  beliefGraph?: BeliefGraphResponse | null;
  kline?: KlineResponse | null;
};

// Minimal SVG trend line for belief history
function BeliefTrendLine({ history }: { history: { date?: string; mu?: number }[] }) {
  const { t } = useI18n();
  if (history.length < 2) {
    return <div className="note-card">{t("symbol.timeline.noHistory")}</div>;
  }

  const W = 600;
  const H = 80;
  const pad = 8;

  const mus = history.map((h) => h.mu ?? 0);
  const minMu = Math.min(...mus);
  const maxMu = Math.max(...mus, minMu + 0.01);

  function x(i: number) {
    return pad + ((W - pad * 2) * i) / (history.length - 1);
  }
  function y(mu: number) {
    return H - pad - ((H - pad * 2) * (mu - minMu)) / (maxMu - minMu);
  }

  const d = history
    .map((h, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(h.mu ?? 0).toFixed(1)}`)
    .join(" ");

  return (
    <svg
      className="belief-trend-line"
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
    >
      <line x1={pad} y1={y(0.5)} x2={W - pad} y2={y(0.5)} className="belief-trend-line__midline" />
      <path d={d} className="belief-trend-line__path" fill="none" />
      {/* First + last labels */}
      <text x={pad} y={H - 2} className="belief-trend-line__date-label">
        {history[0]?.date?.slice(5) || ""}
      </text>
      <text x={W - pad} y={H - 2} textAnchor="end" className="belief-trend-line__date-label">
        {history[history.length - 1]?.date?.slice(5) || ""}
      </text>
    </svg>
  );
}

export function BeliefCausalTimeline({ beliefGraph, kline }: Props) {
  const { locale, t } = useI18n();

  // Prefer belief graph history; fall back to kline belief_overlay
  const history =
    (beliefGraph?.history || []).length > 0
      ? beliefGraph!.history!
      : (kline?.belief_overlay || []).map((b) => ({ date: b.date, mu: b.mu }));

  // Causal events: use kline event_markers as causal anchors
  const events = (kline?.event_markers || []).slice(-10).reverse();

  const hasHistory = history.length >= 2;
  const hasEvents = events.length > 0;

  if (!hasHistory && !hasEvents) {
    return (
      <div className="belief-causal-timeline belief-causal-timeline--empty">
        <div className="note-card">{t("symbol.timeline.unavailable")}</div>
      </div>
    );
  }

  return (
    <div className="belief-causal-timeline">
      {hasHistory && (
        <section className="belief-causal-timeline__section">
          <div className="belief-causal-timeline__section-title">{t("symbol.timeline.beliefTrend")}</div>
          <div className="belief-causal-timeline__trend">
            <BeliefTrendLine history={history} />
            <div className="belief-causal-timeline__trend-stats">
              {history.length >= 2 && (
                <>
                  <span className="belief-causal-timeline__stat">
                    <span className="belief-causal-timeline__stat-label">{t("symbol.timeline.latest")}</span>
                    <strong>{formatPercent(history[history.length - 1]?.mu ?? 0, 0)}</strong>
                  </span>
                  <span className="belief-causal-timeline__stat">
                    <span className="belief-causal-timeline__stat-label">{t("symbol.timeline.earliest")}</span>
                    <strong>{formatPercent(history[0]?.mu ?? 0, 0)}</strong>
                  </span>
                </>
              )}
            </div>
          </div>
        </section>
      )}

      {hasEvents && (
        <section className="belief-causal-timeline__section">
          <div className="belief-causal-timeline__section-title">{t("symbol.timeline.causalEvents")}</div>
          <div className="belief-causal-timeline__events">
            {events.map((ev, i) => (
              <div key={`${ev.date}-${i}`} className="belief-causal-event-card">
                <div className="belief-causal-event-card__head">
                  <span className="belief-causal-event-card__date">
                    {formatDate(ev.date || "", locale === "zh-CN" ? "zh-CN" : "en-US")}
                  </span>
                  <span className="belief-causal-event-card__type">{ev.event_type || t("common.event")}</span>
                  {typeof ev.kg_score === "number" && (
                    <span className="belief-causal-event-card__score">{formatPercent(ev.kg_score, 0)}</span>
                  )}
                </div>
                {ev.title && (
                  <div className="belief-causal-event-card__title">{ev.title}</div>
                )}
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
