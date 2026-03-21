import type { DecisionExplanation, ReasonItem, ReasonPolarity } from "../lib/api";
import { formatPercent } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { classNames } from "../lib/ui";

type SymbolReasonBoardProps = {
  reasonGroups?: Record<string, ReasonItem[]> | null;
  explanation?: DecisionExplanation | null;
};

const GROUP_ORDER = [
  "price_trend",
  "technical",
  "volume_liquidity",
  "event_sentiment",
  "counter_argument",
  "belief_uncertainty",
  "invalidation",
];

function PolarityIcon({ polarity }: { polarity: ReasonPolarity }) {
  if (polarity === "support") return <span className="reason-polarity reason-polarity--support">▲</span>;
  if (polarity === "oppose") return <span className="reason-polarity reason-polarity--oppose">▼</span>;
  if (polarity === "warning") return <span className="reason-polarity reason-polarity--warning">⚠</span>;
  return <span className="reason-polarity reason-polarity--neutral">—</span>;
}

function ReasonRow({ item }: { item: ReasonItem }) {
  const { t } = useI18n();
  return (
    <div className={classNames(
      "symbol-reason-row",
      `symbol-reason-row--${item.polarity}`
    )}>
      <div className="symbol-reason-row__head">
        <PolarityIcon polarity={item.polarity} />
        <span className="symbol-reason-row__title">{item.title}</span>
        {item.metric_value !== undefined && (
          <span className="symbol-reason-row__metric">
            {item.metric_name}: {item.metric_value}
            {item.metric_unit === "%" ? "" : item.metric_unit ? ` ${item.metric_unit}` : ""}
            {item.lookback && <span className="symbol-reason-row__lookback"> ({item.lookback})</span>}
          </span>
        )}
      </div>
      {item.description && item.description !== item.title && (
        <div className="symbol-reason-row__desc">{item.description}</div>
      )}
    </div>
  );
}

function ReasonGroup({ groupKey, items }: { groupKey: string; items: ReasonItem[] }) {
  const { t } = useI18n();
  if (!items.length) return null;

  const labelKey = `symbol.reasons.group.${groupKey}`;
  const supportCount = items.filter((i) => i.polarity === "support").length;
  const opposeCount = items.filter((i) => i.polarity === "oppose").length;
  const warnCount = items.filter((i) => i.polarity === "warning").length;

  return (
    <div className="symbol-reason-group">
      <div className="symbol-reason-group__title">
        <span>{t(labelKey)}</span>
        <div className="symbol-reason-group__counts">
          {supportCount > 0 && <span className="reason-count reason-count--support">▲{supportCount}</span>}
          {opposeCount > 0 && <span className="reason-count reason-count--oppose">▼{opposeCount}</span>}
          {warnCount > 0 && <span className="reason-count reason-count--warning">⚠{warnCount}</span>}
        </div>
      </div>
      <div className="symbol-reason-group__rows">
        {[...items].sort((a, b) => (a.sort_key ?? 0) - (b.sort_key ?? 0)).map((item) => (
          <ReasonRow key={item.id} item={item} />
        ))}
      </div>
    </div>
  );
}

export function SymbolReasonBoard({ reasonGroups, explanation }: SymbolReasonBoardProps) {
  const { t } = useI18n();

  // Merge reason_groups from kline response and from explanation (deduplicate by id)
  const mergedGroups: Record<string, ReasonItem[]> = {};

  const addItems = (groups: Record<string, ReasonItem[]> | null | undefined) => {
    if (!groups) return;
    for (const [key, items] of Object.entries(groups)) {
      if (!mergedGroups[key]) mergedGroups[key] = [];
      const existingIds = new Set(mergedGroups[key].map((i) => i.id));
      for (const item of items) {
        if (!existingIds.has(item.id)) {
          mergedGroups[key].push(item);
          existingIds.add(item.id);
        }
      }
    }
  };

  addItems(reasonGroups);
  addItems(explanation?.reason_groups);

  // Also add evidence items that are not already in reason groups
  if (explanation) {
    const hasEventSentiment = (mergedGroups["event_sentiment"] || []).length > 0;
    if (!hasEventSentiment) {
      const evItems: ReasonItem[] = [
        ...(explanation.evidence_for || []).map((e, i) => ({
          id: `ev_for_${i}`,
          group: "event_sentiment",
          polarity: "support" as ReasonPolarity,
          title: e.source || "支持信号",
          description: e.description || "",
          source: e.source || "signal",
          strength: e.strength ?? 0.5,
          sort_key: 40 + i,
        })),
      ].filter((e) => {
        const src = (e.source || "").toLowerCase();
        return src.includes("event") || src.includes("sentiment") || src.includes("news");
      });
      if (evItems.length > 0) {
        mergedGroups["event_sentiment"] = evItems;
      }
    }

    const hasCounter = (mergedGroups["counter_argument"] || []).length > 0;
    if (!hasCounter) {
      const counterItems: ReasonItem[] = (explanation.evidence_against || []).map((e, i) => ({
        id: `ev_against_${i}`,
        group: "counter_argument",
        polarity: "oppose" as ReasonPolarity,
        title: e.source || "反向信号",
        description: e.description || "",
        source: e.source || "signal",
        strength: e.strength ?? 0.5,
        sort_key: 60 + i,
      }));
      if (counterItems.length > 0) {
        mergedGroups["counter_argument"] = counterItems;
      }
    }

    const hasInvalidation = (mergedGroups["invalidation"] || []).length > 0;
    if (!hasInvalidation) {
      const invItems: ReasonItem[] = (explanation.invalidators || [])
        .filter((inv) => !inv.startsWith("resolve:"))
        .map((inv, i) => ({
          id: `inv_${i}`,
          group: "invalidation",
          polarity: "warning" as ReasonPolarity,
          title: inv,
          description: inv,
          source: "decision",
          strength: 0.6,
          sort_key: 70 + i,
        }));
      if (invItems.length > 0) {
        mergedGroups["invalidation"] = invItems;
      }
    }
  }

  const hasAnyReasons = GROUP_ORDER.some((key) => (mergedGroups[key] || []).length > 0);

  return (
    <div className="symbol-reason-board">
      <div className="symbol-reason-board__header">
        <div className="symbol-reason-board__title">{t("symbol.reasons.title")}</div>
        <div className="symbol-reason-board__subtitle">{t("symbol.reasons.subtitle")}</div>
      </div>
      {!hasAnyReasons ? (
        <div className="note-card">{t("symbol.reasons.noReasons")}</div>
      ) : (
        <div className="symbol-reason-board__groups">
          {GROUP_ORDER.map((key) => {
            const items = mergedGroups[key];
            if (!items?.length) return null;
            return <ReasonGroup key={key} groupKey={key} items={items} />;
          })}
        </div>
      )}
    </div>
  );
}
