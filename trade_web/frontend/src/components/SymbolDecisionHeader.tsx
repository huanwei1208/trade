import type { DecisionExplanation, KlineResponse, WorldState } from "../lib/api";
import { formatConfidence, formatDate } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { getConclusionModeText, getGateStatusText } from "../lib/statusText";
import { ActionChip } from "./ActionChip";
import { StatusPill } from "./StatusPill";
import { TrustBadge } from "./TrustBadge";

type SymbolDecisionHeaderProps = {
  symbol: string;
  kline?: KlineResponse | null;
  explanation?: DecisionExplanation | null;
  state?: WorldState | null;
  onBack: () => void;
  onOpenReadiness: () => void;
  onOpenRecovery: () => void;
};

export function SymbolDecisionHeader({ symbol, kline, explanation, state, onBack, onOpenReadiness, onOpenRecovery }: SymbolDecisionHeaderProps) {
  const { locale, t } = useI18n();
  const conclusionMode = getConclusionModeText(locale, {
    global_blocked: Boolean(state?.blockers?.length || explanation?.warnings?.length || explanation?.input_warnings?.length),
    blockers: state?.blockers || explanation?.warnings || [],
  });
  const chartReadiness = getGateStatusText(locale, kline?.ohlcv?.length ? "ok" : "missing");
  const modelInputReadiness = getGateStatusText(locale, explanation?.input_warnings?.length ? "partial" : "ok");

  return (
    <div className="symbol-header">
      <div className="symbol-header__identity">
        <button type="button" className="button button--ghost" onClick={onBack}>
          {t("common.back")}
        </button>
        <div>
          <div className="symbol-header__symbol">
            {symbol}
            <span>{kline?.name || ""}</span>
          </div>
          <div className="symbol-header__copy">{explanation?.thesis || state?.state_summary || t("symbol.noThesis")}</div>
        </div>
      </div>
      <div className="symbol-header__meta">
        <ActionChip action={explanation?.action || kline?.action?.action} />
        <div className="symbol-header__metric">
          <span>{t("symbol.confidence")}</span>
          <strong>{formatConfidence(explanation?.action_confidence || kline?.action?.confidence)}</strong>
        </div>
        <TrustBadge score={explanation?.trust?.trust_score || state?.trust_score} level={explanation?.trust?.trust_level} detailed />
        <div className="symbol-header__metric">
          <span>{t("symbol.asOf")}</span>
          <strong>{formatDate(explanation?.as_of || kline?.as_of || state?.as_of_date, locale === "zh-CN" ? "zh-CN" : "en-US")}</strong>
        </div>
      </div>
      <div className="symbol-header__footer">
        <div className="symbol-header__readiness">
          <StatusPill label={`${t("symbol.chartReadiness")} · ${chartReadiness.label}`} tone={chartReadiness.tone} subtle />
          <StatusPill label={`${t("symbol.modelInputs")} · ${modelInputReadiness.label}`} tone={modelInputReadiness.tone} subtle />
          <StatusPill label={`${t("symbol.conclusionMode")} · ${conclusionMode.label}`} tone={conclusionMode.tone} subtle />
        </div>
        <div className="symbol-header__actions">
          <button type="button" className="button button--ghost" onClick={onOpenReadiness}>
            {t("symbol.inspectDayReadiness")}
          </button>
          <button type="button" className="button button--ghost" onClick={onOpenRecovery}>
            {t("symbol.openRecovery")}
          </button>
        </div>
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
