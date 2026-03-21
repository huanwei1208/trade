import type { KlineResponse, SymbolEvidenceResponse, SymbolSectorResponse } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { ArticleEvidenceList } from "./ArticleEvidenceList";
import { BeliefCausalTimeline } from "./BeliefCausalTimeline";
import type { BeliefGraphResponse } from "../lib/api";
import { SectorContextPanel } from "./SectorContextPanel";

type Props = {
  evidenceData?: SymbolEvidenceResponse | null;
  sectorData?: SymbolSectorResponse | null;
  beliefGraph?: BeliefGraphResponse | null;
  kline?: KlineResponse | null;
  evidenceLoading?: boolean;
  sectorLoading?: boolean;
};

export function SymbolEvidenceTab({
  evidenceData,
  sectorData,
  beliefGraph,
  kline,
  evidenceLoading,
  sectorLoading,
}: Props) {
  const { t } = useI18n();

  return (
    <div className="symbol-evidence-tab">
      {/* Article / event evidence */}
      <section className="symbol-evidence-tab__section">
        <div className="symbol-evidence-tab__section-title">{t("symbol.evidence.title")}</div>
        <ArticleEvidenceList
          marketEvents={evidenceData?.market_events}
          evidenceItems={evidenceData?.evidence_items}
          attentionItems={evidenceData?.attention_items}
          loading={evidenceLoading && !evidenceData}
        />
      </section>

      {/* Sector context + peer table */}
      <section className="symbol-evidence-tab__section">
        <div className="symbol-evidence-tab__section-title">{t("symbol.sector.title")}</div>
        <SectorContextPanel data={sectorData} loading={sectorLoading && !sectorData} />
      </section>

      {/* Belief causal timeline (moved from old Timeline tab) */}
      <section className="symbol-evidence-tab__section">
        <div className="symbol-evidence-tab__section-title">{t("symbol.timeline.title")}</div>
        <BeliefCausalTimeline beliefGraph={beliefGraph} kline={kline} />
      </section>
    </div>
  );
}
