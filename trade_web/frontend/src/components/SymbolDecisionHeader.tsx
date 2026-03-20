import type { DecisionExplanation, KlineResponse, WorldState } from "../lib/api";
import { formatCompactNumber, formatConfidence, formatDate, formatPercent, formatScore } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { classNames } from "../lib/ui";
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

  // Derive price/return/volume from kline ohlcv
  const bars = kline?.ohlcv || [];
  const lastBar = bars[bars.length - 1];
  const prevBar = bars[bars.length - 2];
  const latestClose = typeof lastBar?.close === "number" ? lastBar.close : undefined;
  const dailyReturn =
    latestClose !== undefined && typeof prevBar?.close === "number" && prevBar.close > 0
      ? (latestClose - prevBar.close) / prevBar.close
      : undefined;
  const latestVolume = typeof lastBar?.volume === "number" ? lastBar.volume : undefined;
  const hasStats = latestClose !== undefined || dailyReturn !== undefined || latestVolume !== undefined;

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

      {hasStats && (
        <div className="symbol-header__stats">
          {latestClose !== undefined && (
            <div className="symbol-header__stat">
              <span className="symbol-header__stat-label">{t("symbol.latestClose")}</span>
              <span className="symbol-header__stat-value">{formatScore(latestClose, 2)}</span>
            </div>
          )}
          {dailyReturn !== undefined && (
            <div className="symbol-header__stat">
              <span className="symbol-header__stat-label">{t("symbol.dailyReturn")}</span>
              <span className={classNames("symbol-header__stat-value", dailyReturn >= 0 ? "symbol-header__stat-value--positive" : "symbol-header__stat-value--negative")}>
                {dailyReturn >= 0 ? "+" : ""}{formatPercent(dailyReturn, 2)}
              </span>
            </div>
          )}
          {latestVolume !== undefined && (
            <div className="symbol-header__stat">
              <span className="symbol-header__stat-label">{t("symbol.volume")}</span>
              <span className="symbol-header__stat-value">{formatCompactNumber(latestVolume)}</span>
            </div>
          )}
          {formatScore(explanation?.trust?.trust_score || state?.trust_score) !== "—" && (
            <div className="symbol-header__stat">
              <span className="symbol-header__stat-label">{t("ops.trust.scalar")}</span>
              <span className="symbol-header__stat-value">{formatPercent(explanation?.trust?.trust_score || state?.trust_score, 0)}</span>
            </div>
          )}
        </div>
      )}

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
