import type { DecisionExplanation, KlineResponse } from "../lib/api";
import { formatPercent } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { getActionText } from "../lib/statusText";

type Props = {
  kline?: KlineResponse | null;
  explanation?: DecisionExplanation | null;
};

type ChangeSignal = {
  id: string;
  label: string;
  value: string;
  tone: "positive" | "negative" | "neutral" | "warning";
};

export function DecisionChangeStrip({ kline, explanation }: Props) {
  const { locale, t } = useI18n();

  const signals: ChangeSignal[] = [];

  // Action + confidence
  if (explanation?.action) {
    const isBuy = ["ADD", "PROBE"].includes(String(explanation.action));
    const isReduce = explanation.action === "REDUCE";
    signals.push({
      id: "action",
      label: t("symbol.changeStrip.action"),
      value: getActionText(locale, explanation.action),
      tone: isBuy ? "positive" : isReduce ? "negative" : "neutral",
    });
  }

  // Trust score
  const trustScore = explanation?.trust?.trust_score;
  if (typeof trustScore === "number") {
    signals.push({
      id: "trust",
      label: t("symbol.changeStrip.trust"),
      value: formatPercent(trustScore, 0),
      tone: trustScore >= 0.7 ? "positive" : trustScore >= 0.5 ? "neutral" : "warning",
    });
  }

  // Latest bar 1d return
  const bars = kline?.ohlcv || [];
  const quote = kline?.quote;
  if (quote?.change_pct !== undefined && quote.change_pct !== null) {
    const pct = quote.change_pct;
    signals.push({
      id: "day_return",
      label: t("symbol.changeStrip.dayReturn"),
      value: (pct >= 0 ? "+" : "") + formatPercent(pct, 2),
      tone: pct > 0 ? "positive" : pct < 0 ? "negative" : "neutral",
    });
  } else if (bars.length >= 2) {
    const last = bars[bars.length - 1];
    const prev = bars[bars.length - 2];
    if (last.close && prev.close && prev.close !== 0) {
      const pct = (last.close - prev.close) / prev.close;
      signals.push({
        id: "day_return",
        label: t("symbol.changeStrip.dayReturn"),
        value: (pct >= 0 ? "+" : "") + formatPercent(pct, 2),
        tone: pct > 0 ? "positive" : pct < 0 ? "negative" : "neutral",
      });
    }
  }

  // Blocker count
  const blockers = explanation?.invalidators || [];
  if (blockers.length > 0) {
    signals.push({
      id: "blockers",
      label: t("symbol.changeStrip.blockers"),
      value: String(blockers.length),
      tone: "warning",
    });
  }

  // Latest event marker
  const events = kline?.event_markers || [];
  if (events.length > 0) {
    const last = events[events.length - 1];
    signals.push({
      id: "last_event",
      label: t("symbol.changeStrip.latestEvent"),
      value: last.event_type || last.date || "—",
      tone: "neutral",
    });
  }

  if (signals.length === 0) {
    return null;
  }

  return (
    <div className="decision-change-strip">
      {signals.map((s) => (
        <div key={s.id} className={`decision-change-strip__item decision-change-strip__item--${s.tone}`}>
          <span className="decision-change-strip__label">{s.label}</span>
          <span className="decision-change-strip__value">{s.value}</span>
        </div>
      ))}
    </div>
  );
}
