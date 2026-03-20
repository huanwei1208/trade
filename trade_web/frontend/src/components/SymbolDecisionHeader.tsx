import type { DecisionExplanation, KlineResponse, WorldState } from "../lib/api";
import { formatConfidence, formatDate } from "../lib/format";
import { ActionChip } from "./ActionChip";
import { TrustBadge } from "./TrustBadge";

type SymbolDecisionHeaderProps = {
  symbol: string;
  kline?: KlineResponse | null;
  explanation?: DecisionExplanation | null;
  state?: WorldState | null;
  onBack: () => void;
};

export function SymbolDecisionHeader({ symbol, kline, explanation, state, onBack }: SymbolDecisionHeaderProps) {
  return (
    <div className="symbol-header">
      <div className="symbol-header__identity">
        <button type="button" className="button button--ghost" onClick={onBack}>
          Back
        </button>
        <div>
          <div className="symbol-header__symbol">
            {symbol}
            <span>{kline?.name || ""}</span>
          </div>
          <div className="symbol-header__copy">{explanation?.thesis || state?.state_summary || "No thesis available."}</div>
        </div>
      </div>
      <div className="symbol-header__meta">
        <ActionChip action={explanation?.action || kline?.action?.action} />
        <div className="symbol-header__metric">
          <span>Confidence</span>
          <strong>{formatConfidence(explanation?.action_confidence || kline?.action?.confidence)}</strong>
        </div>
        <TrustBadge score={explanation?.trust?.trust_score || state?.trust_score} level={explanation?.trust?.trust_level} detailed />
        <div className="symbol-header__metric">
          <span>As of</span>
          <strong>{formatDate(explanation?.as_of || kline?.as_of || state?.as_of_date)}</strong>
        </div>
      </div>
      <div className="symbol-header__footer">
        <div className="symbol-header__invalidators">
          {(explanation?.invalidators || []).slice(0, 3).map((item) => (
            <span className="tag-chip tag-chip--negative" key={item}>
              {item}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
