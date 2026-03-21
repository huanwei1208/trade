import type { SymbolSectorResponse } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { PeerMiniTable } from "./PeerMiniTable";

type Props = {
  data?: SymbolSectorResponse | null;
  loading?: boolean;
};

function heatTone(sentiment?: number): "positive" | "negative" | "neutral" {
  if (sentiment == null) return "neutral";
  if (sentiment > 0.1) return "positive";
  if (sentiment < -0.1) return "negative";
  return "neutral";
}

export function SectorContextPanel({ data, loading }: Props) {
  const { t } = useI18n();

  if (loading && !data) {
    return <div className="sector-context-panel sector-context-panel--loading">{t("common.loading")}</div>;
  }

  if (!data) {
    return null;
  }

  const tone = heatTone(data.sector_sentiment);
  const sentDisplay = data.sector_sentiment != null
    ? `${data.sector_sentiment > 0 ? "+" : ""}${data.sector_sentiment.toFixed(2)}`
    : "—";

  return (
    <div className="sector-context-panel">
      <div className="sector-context-panel__head">
        <div className="sector-context-panel__label">
          <span className="sector-context-panel__name">{data.sector_name || data.sector_code || "—"}</span>
          {data.sector_code && (
            <span className="sector-context-panel__code">{data.sector_code}</span>
          )}
        </div>
        <div className="sector-context-panel__heat">
          <span className="sector-context-panel__heat-label">{t("symbol.sector.sentiment")}</span>
          <span className={`sector-context-panel__heat-value sector-context-panel__heat-value--${tone}`}>
            {sentDisplay}
          </span>
          {data.sector_event_count != null && data.sector_event_count > 0 && (
            <span className="sector-context-panel__event-count">
              {t("symbol.sector.eventCount", { count: data.sector_event_count })}
            </span>
          )}
        </div>
      </div>

      <div className="sector-context-panel__peers-label">{t("symbol.sector.peers")}</div>
      <PeerMiniTable peers={data.peers} loading={loading && !data.peers} />
    </div>
  );
}
