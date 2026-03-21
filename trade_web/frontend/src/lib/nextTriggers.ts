import type {
  DecisionExplanation,
  KlineBar,
  KlineResponse,
  Locale,
  NextTriggerDetail,
  WorldState,
} from "./api";
import { formatPercent, formatScore, humanizeEnum, shortText } from "./format";
import { translate } from "./i18n";
import { getDatasetText, getMarketRegimeText } from "./statusText";

export type NextTriggerType = "auto_market" | "auto_data" | "manual_recovery" | "mixed" | "unknown";
export type NextTriggerStatus = "met" | "near" | "unmet" | "blocked_by_data" | "unknown";
export type NextTriggerActionability = "not_direct" | "actionable" | "partly_actionable";
export type NextTriggerActionId = "openReadiness" | "openRecovery" | "openEvidenceTab" | "openBeliefTab" | "openDataOpsTab";

export type StructuredNextTrigger = {
  key: string;
  label: string;
  type: NextTriggerType;
  typeLabel: string;
  description: string;
  targetLabel?: string;
  currentLabel?: string;
  whyItMatters?: string;
  actionability: NextTriggerActionability;
  status: NextTriggerStatus;
  statusLabel: string;
  suggestedActions: NextTriggerActionId[];
};

export type NextActionItem = {
  id: NextTriggerActionId;
  label: string;
  description: string;
  appearance: "primary" | "ghost";
};

type TriggerContext = {
  kline?: KlineResponse | null;
  explanation?: DecisionExplanation | null;
  state?: WorldState | null;
};

type TriggerDefinition = {
  type: NextTriggerType;
  actionability: NextTriggerActionability;
  suggestedActions: NextTriggerActionId[];
};

const TRIGGER_DEFINITIONS: Record<string, TriggerDefinition> = {
  data_refreshed: {
    type: "manual_recovery",
    actionability: "actionable",
    suggestedActions: ["openReadiness", "openRecovery", "openDataOpsTab"],
  },
  trust_recovered: {
    type: "mixed",
    actionability: "partly_actionable",
    suggestedActions: ["openRecovery", "openDataOpsTab", "openBeliefTab"],
  },
  regime_signal_emerges: {
    type: "auto_market",
    actionability: "not_direct",
    suggestedActions: ["openEvidenceTab", "openBeliefTab"],
  },
  rsi_crosses_40: {
    type: "auto_market",
    actionability: "not_direct",
    suggestedActions: ["openEvidenceTab"],
  },
  event_kg_score_confirms: {
    type: "auto_market",
    actionability: "not_direct",
    suggestedActions: ["openEvidenceTab"],
  },
  "vol_ratio_drops_below_1.5": {
    type: "auto_market",
    actionability: "not_direct",
    suggestedActions: ["openEvidenceTab"],
  },
  negative_event_reverses: {
    type: "auto_market",
    actionability: "not_direct",
    suggestedActions: ["openEvidenceTab", "openBeliefTab"],
  },
  belief_mu_recovers_above_0: {
    type: "auto_market",
    actionability: "not_direct",
    suggestedActions: ["openBeliefTab", "openEvidenceTab"],
  },
  volatility_regime_resolves: {
    type: "auto_market",
    actionability: "not_direct",
    suggestedActions: ["openEvidenceTab"],
  },
  hold_until_regime_changes: {
    type: "auto_market",
    actionability: "not_direct",
    suggestedActions: ["openEvidenceTab", "openBeliefTab"],
  },
  add_if_confirms: {
    type: "mixed",
    actionability: "partly_actionable",
    suggestedActions: ["openEvidenceTab", "openBeliefTab"],
  },
  "probe_if_score_crosses_0.55": {
    type: "mixed",
    actionability: "partly_actionable",
    suggestedActions: ["openEvidenceTab", "openBeliefTab"],
  },
  volume_breakout: {
    type: "auto_market",
    actionability: "not_direct",
    suggestedActions: ["openEvidenceTab"],
  },
  positive_event_confirmed: {
    type: "auto_market",
    actionability: "not_direct",
    suggestedActions: ["openEvidenceTab"],
  },
  negative_event_confirmed: {
    type: "auto_market",
    actionability: "not_direct",
    suggestedActions: ["openEvidenceTab"],
  },
  significant_news_event: {
    type: "auto_market",
    actionability: "not_direct",
    suggestedActions: ["openEvidenceTab"],
  },
  heavy_selling_volume: {
    type: "auto_market",
    actionability: "not_direct",
    suggestedActions: ["openEvidenceTab"],
  },
  regime_change: {
    type: "auto_market",
    actionability: "not_direct",
    suggestedActions: ["openEvidenceTab", "openBeliefTab"],
  },
};

const ACTION_ORDER: NextTriggerActionId[] = [
  "openReadiness",
  "openRecovery",
  "openEvidenceTab",
  "openBeliefTab",
  "openDataOpsTab",
];

function getLatestBar(kline?: KlineResponse | null): KlineBar | null {
  const bars = kline?.ohlcv || [];
  return bars.length ? bars[bars.length - 1] || null : null;
}

function getPreviousBar(kline?: KlineResponse | null): KlineBar | null {
  const bars = kline?.ohlcv || [];
  return bars.length > 1 ? bars[bars.length - 2] || null : null;
}

function findTriggerDetail(explanation: DecisionExplanation | null | undefined, key: string): NextTriggerDetail | undefined {
  return (explanation?.next_trigger_details || []).find((item) => item.key === key);
}

function translateMaybe(locale: Locale, key: string) {
  const translated = translate(locale, key);
  return translated === key ? "" : translated;
}

function getTypeLabel(locale: Locale, type: NextTriggerType) {
  return translate(locale, `trigger.type.${type}`);
}

function getStatusLabel(locale: Locale, status: NextTriggerStatus) {
  return translate(locale, `trigger.status.${status}`);
}

function formatScalar(value?: number | null, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "";
  }
  return formatScore(value, digits);
}

function formatUnitValue(value?: number | null, unit?: string | null) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "";
  }
  if (unit === "pct") {
    return formatPercent(value, 0);
  }
  if (unit === "rsi") {
    return formatScore(value, 1);
  }
  return formatScore(value, 2);
}

function summarizeDatasets(locale: Locale, datasets: string[]) {
  if (!datasets.length) {
    return "";
  }
  return datasets.slice(0, 2).map((dataset) => getDatasetText(locale, dataset)).join(" · ");
}

function getMarketSignalStatus(locale: Locale, regime?: string | null) {
  const normalized = String(regime || "").trim().toUpperCase();
  if (!normalized || normalized === "UNKNOWN" || normalized === "SIDEWAYS" || normalized === "NEUTRAL") {
    return {
      status: "unmet" as NextTriggerStatus,
      currentLabel: getMarketRegimeText(locale, regime).label,
    };
  }
  if (normalized === "VOLATILE") {
    return {
      status: "near" as NextTriggerStatus,
      currentLabel: getMarketRegimeText(locale, regime).label,
    };
  }
  return {
    status: "met" as NextTriggerStatus,
    currentLabel: getMarketRegimeText(locale, regime).label,
  };
}

function inferTriggerStatus(
  locale: Locale,
  key: string,
  context: TriggerContext,
): { status: NextTriggerStatus; currentLabel?: string; targetLabel?: string } {
  const latestBar = getLatestBar(context.kline);
  const previousBar = getPreviousBar(context.kline);
  const detail = findTriggerDetail(context.explanation, key);
  const dqs = context.state?.data_quality_state;
  const missing = dqs?.missing_datasets || [];
  const stale = dqs?.stale_datasets || [];
  const hasDataIssue = missing.length > 0 || stale.length > 0;
  const hasChart = Boolean(context.kline?.ohlcv?.length);
  const trustScore = context.explanation?.trust?.trust_score ?? context.state?.trust_score;
  const beliefMu = context.state?.sentiment_state?.belief_mu;
  const eventRegime = context.state?.event_regime || context.state?.event_state?.regime;
  const kgScore = context.state?.event_state?.kg_score;
  const regime = context.state?.market_regime;
  const score = context.kline?.action?.score;
  const volRatio = context.state?.liquidity_state?.vol_ratio ?? context.state?.market_state?.vol_ratio;
  const latestReturn =
    typeof latestBar?.close === "number" && typeof previousBar?.close === "number" && previousBar.close > 0
      ? (latestBar.close - previousBar.close) / previousBar.close
      : undefined;
  const rsi = latestBar?.rsi14 ?? context.state?.technical_state?.rsi_14;

  switch (key) {
    case "data_refreshed": {
      if (missing.length > 0) {
        return {
          status: "blocked_by_data" as NextTriggerStatus,
          currentLabel: summarizeDatasets(locale, missing),
          targetLabel: translate(locale, "trigger.target.latestInputsReady"),
        };
      }
      if (stale.length > 0 || !hasChart) {
        return {
          status: "blocked_by_data" as NextTriggerStatus,
          currentLabel: stale.length > 0 ? summarizeDatasets(locale, stale) : translate(locale, "trigger.current.chartUnavailable"),
          targetLabel: translate(locale, "trigger.target.latestInputsReady"),
        };
      }
      return {
        status: "met" as NextTriggerStatus,
        currentLabel: translate(locale, "trigger.current.inputsHealthy"),
        targetLabel: translate(locale, "trigger.target.latestInputsReady"),
      };
    }
    case "trust_recovered": {
      if (hasDataIssue && typeof trustScore === "number" && trustScore < 0.75) {
        return {
          status: "blocked_by_data" as NextTriggerStatus,
          currentLabel: formatPercent(trustScore, 0),
          targetLabel: translate(locale, "trigger.target.trustRecovered"),
        };
      }
      if (typeof trustScore === "number") {
        if (trustScore >= 0.75) {
          return {
            status: "met" as NextTriggerStatus,
            currentLabel: formatPercent(trustScore, 0),
            targetLabel: translate(locale, "trigger.target.trustRecovered"),
          };
        }
        if (trustScore >= 0.55) {
          return {
            status: "near" as NextTriggerStatus,
            currentLabel: formatPercent(trustScore, 0),
            targetLabel: translate(locale, "trigger.target.trustRecovered"),
          };
        }
        return {
          status: "unmet" as NextTriggerStatus,
          currentLabel: formatPercent(trustScore, 0),
          targetLabel: translate(locale, "trigger.target.trustRecovered"),
        };
      }
      break;
    }
    case "regime_signal_emerges": {
      return {
        ...getMarketSignalStatus(locale, regime),
        targetLabel: translate(locale, "trigger.target.clearerRegimeSignal"),
      };
    }
    case "rsi_crosses_40": {
      const current = rsi ?? detail?.current_value;
      if (typeof current === "number") {
        return {
          status: (current >= 40 ? "met" : current >= 35 ? "near" : "unmet") as NextTriggerStatus,
          currentLabel: formatUnitValue(current, detail?.unit || "rsi"),
          targetLabel: formatUnitValue(detail?.target_value ?? 40, detail?.unit || "rsi"),
        };
      }
      break;
    }
    case "event_kg_score_confirms": {
      const current = kgScore ?? detail?.current_value;
      if (eventRegime === "POSITIVE_EVENT") {
        return {
          status: "met" as NextTriggerStatus,
          currentLabel: current !== null && current !== undefined ? formatScalar(current, 2) : translate(locale, "trigger.current.positiveEvent"),
          targetLabel: translate(locale, "trigger.target.eventConfirmation"),
        };
      }
      if (typeof current === "number") {
        return {
          status: (current > 0 ? "near" : "unmet") as NextTriggerStatus,
          currentLabel: formatScalar(current, 2),
          targetLabel: translate(locale, "trigger.target.eventConfirmation"),
        };
      }
      break;
    }
    case "vol_ratio_drops_below_1.5": {
      const current = volRatio ?? detail?.current_value;
      if (typeof current === "number") {
        return {
          status: (current <= 1.5 ? "met" : current <= 1.8 ? "near" : "unmet") as NextTriggerStatus,
          currentLabel: formatScalar(current, 2),
          targetLabel: formatScalar(detail?.target_value ?? 1.5, 2),
        };
      }
      break;
    }
    case "negative_event_reverses": {
      if (eventRegime === "NEGATIVE_EVENT") {
        return {
          status: "unmet" as NextTriggerStatus,
          currentLabel: translate(locale, "trigger.current.negativeEventStillActive"),
          targetLabel: translate(locale, "trigger.target.negativeEventClears"),
        };
      }
      if (eventRegime) {
        return {
          status: "met" as NextTriggerStatus,
          currentLabel: humanizeEnum(eventRegime),
          targetLabel: translate(locale, "trigger.target.negativeEventClears"),
        };
      }
      break;
    }
    case "belief_mu_recovers_above_0": {
      const current = beliefMu ?? detail?.current_value;
      if (typeof current === "number") {
        return {
          status: (current > 0 ? "met" : current > -0.05 ? "near" : "unmet") as NextTriggerStatus,
          currentLabel: formatScalar(current, 2),
          targetLabel: formatScalar(detail?.target_value ?? 0, 2),
        };
      }
      break;
    }
    case "volatility_regime_resolves": {
      if (regime === "VOLATILE") {
        return {
          status: "unmet" as NextTriggerStatus,
          currentLabel: getMarketRegimeText(locale, regime).label,
          targetLabel: translate(locale, "trigger.target.volatilityResolved"),
        };
      }
      if (regime) {
        return {
          status: "met" as NextTriggerStatus,
          currentLabel: getMarketRegimeText(locale, regime).label,
          targetLabel: translate(locale, "trigger.target.volatilityResolved"),
        };
      }
      break;
    }
    case "add_if_confirms": {
      const current = score ?? detail?.current_value;
      const action = String(context.explanation?.action || context.kline?.action?.action || "").toUpperCase();
      if (action === "ADD" || (typeof current === "number" && current >= 0.65)) {
        return {
          status: "met" as NextTriggerStatus,
          currentLabel: typeof current === "number" ? formatPercent(current, 0) : translate(locale, "trigger.current.alreadyConfirmed"),
          targetLabel: formatPercent(detail?.target_value ?? 0.65, 0),
        };
      }
      if (typeof current === "number") {
        return {
          status: (current >= 0.6 ? "near" : "unmet") as NextTriggerStatus,
          currentLabel: formatPercent(current, 0),
          targetLabel: formatPercent(detail?.target_value ?? 0.65, 0),
        };
      }
      break;
    }
    case "probe_if_score_crosses_0.55": {
      const current = score ?? detail?.current_value;
      const action = String(context.explanation?.action || context.kline?.action?.action || "").toUpperCase();
      if (action === "PROBE" || action === "ADD" || (typeof current === "number" && current >= 0.55)) {
        return {
          status: "met" as NextTriggerStatus,
          currentLabel: typeof current === "number" ? formatPercent(current, 0) : translate(locale, "trigger.current.alreadyConfirmed"),
          targetLabel: formatPercent(detail?.target_value ?? 0.55, 0),
        };
      }
      if (typeof current === "number") {
        return {
          status: (current >= 0.5 ? "near" : "unmet") as NextTriggerStatus,
          currentLabel: formatPercent(current, 0),
          targetLabel: formatPercent(detail?.target_value ?? 0.55, 0),
        };
      }
      break;
    }
    case "hold_until_regime_changes": {
      if (regime) {
        return {
          status: (regime === "TRENDING_UP" ? "unmet" : "met") as NextTriggerStatus,
          currentLabel: getMarketRegimeText(locale, regime).label,
          targetLabel: translate(locale, "trigger.target.regimeChange"),
        };
      }
      break;
    }
    case "volume_breakout": {
      const current = volRatio ?? detail?.current_value;
      if (typeof current === "number") {
        return {
          status: (current >= 1.4 ? "met" : current >= 1.15 ? "near" : "unmet") as NextTriggerStatus,
          currentLabel: formatScalar(current, 2),
          targetLabel: translate(locale, "trigger.target.volumeBreakout"),
        };
      }
      break;
    }
    case "positive_event_confirmed": {
      if (eventRegime === "POSITIVE_EVENT") {
        return {
          status: "met" as NextTriggerStatus,
          currentLabel: translate(locale, "trigger.current.positiveEvent"),
          targetLabel: translate(locale, "trigger.target.positiveEventConfirmed"),
        };
      }
      if (typeof kgScore === "number") {
        return {
          status: (kgScore > 0 ? "near" : "unmet") as NextTriggerStatus,
          currentLabel: formatScalar(kgScore, 2),
          targetLabel: translate(locale, "trigger.target.positiveEventConfirmed"),
        };
      }
      break;
    }
    case "negative_event_confirmed": {
      if (eventRegime === "NEGATIVE_EVENT") {
        return {
          status: "met" as NextTriggerStatus,
          currentLabel: translate(locale, "trigger.current.negativeEventStillActive"),
          targetLabel: translate(locale, "trigger.target.negativeEventConfirmed"),
        };
      }
      if (typeof kgScore === "number") {
        return {
          status: (kgScore < 0 ? "near" : "unmet") as NextTriggerStatus,
          currentLabel: formatScalar(kgScore, 2),
          targetLabel: translate(locale, "trigger.target.negativeEventConfirmed"),
        };
      }
      break;
    }
    case "significant_news_event": {
      const count = context.state?.event_state?.event_count_recent;
      if (typeof count === "number") {
        return {
          status: (count > 0 ? "near" : "unmet") as NextTriggerStatus,
          currentLabel: String(count),
          targetLabel: translate(locale, "trigger.target.significantNews"),
        };
      }
      break;
    }
    case "heavy_selling_volume": {
      const current = volRatio ?? detail?.current_value;
      if (typeof current === "number" && typeof latestReturn === "number") {
        const status = (
          current >= 1.5 && latestReturn < 0 ? "met" : current >= 1.2 && latestReturn < 0 ? "near" : "unmet"
        ) as NextTriggerStatus;
        return {
          status,
          currentLabel: `${formatScalar(current, 2)} · ${latestReturn >= 0 ? "+" : ""}${formatPercent(latestReturn, 1)}`,
          targetLabel: translate(locale, "trigger.target.heavySelling"),
        };
      }
      break;
    }
    case "regime_change": {
      if (regime) {
        return {
          status: "unknown" as NextTriggerStatus,
          currentLabel: getMarketRegimeText(locale, regime).label,
          targetLabel: translate(locale, "trigger.target.regimeChange"),
        };
      }
      break;
    }
    default: {
      if (detail?.current_value !== undefined || detail?.target_value !== undefined) {
        return {
          status: "unknown" as NextTriggerStatus,
          currentLabel: formatUnitValue(detail.current_value, detail.unit),
          targetLabel: formatUnitValue(detail.target_value, detail.unit),
        };
      }
    }
  }

  return {
    status: hasDataIssue && (key === "data_refreshed" || key === "trust_recovered") ? "blocked_by_data" : "unknown",
    currentLabel: "",
    targetLabel: "",
  };
}

export function buildNextTriggerView(locale: Locale, context: TriggerContext) {
  const rawList = context.explanation?.next_triggers || context.kline?.action?.next_triggers || [];
  const unique = Array.from(new Set(rawList.filter(Boolean)));

  const waitingFor = unique.map<StructuredNextTrigger>((key) => {
    const definition = TRIGGER_DEFINITIONS[key] || {
      type: "unknown" as NextTriggerType,
      actionability: "not_direct" as NextTriggerActionability,
      suggestedActions: ["openEvidenceTab"],
    };
    const status = inferTriggerStatus(locale, key, context);
    const label = translateMaybe(locale, `trigger.${key}.label`) || humanizeEnum(key);
    const description = translateMaybe(locale, `trigger.${key}.description`) || translate(locale, "trigger.default.description");
    const whyItMatters = translateMaybe(locale, `trigger.${key}.matters`) || "";

    return {
      key,
      label,
      type: definition.type,
      typeLabel: getTypeLabel(locale, definition.type),
      description,
      whyItMatters: whyItMatters || undefined,
      actionability: definition.actionability,
      status: status.status,
      statusLabel: getStatusLabel(locale, status.status),
      currentLabel: status.currentLabel || undefined,
      targetLabel: status.targetLabel || undefined,
      suggestedActions: definition.suggestedActions,
    };
  });

  const actions = new Set<NextTriggerActionId>();
  for (const item of waitingFor) {
    item.suggestedActions.forEach((action) => actions.add(action));
  }

  const dqs = context.state?.data_quality_state;
  if ((dqs?.missing_datasets || []).length > 0 || (dqs?.stale_datasets || []).length > 0) {
    actions.add("openReadiness");
    actions.add("openRecovery");
    actions.add("openDataOpsTab");
  }

  const availableActions = ACTION_ORDER.filter((action) => actions.has(action)).map<NextActionItem>((id) => {
    const label = translate(locale, `trigger.action.${id}.label`);
    const description = translate(locale, `trigger.action.${id}.description`);
    const dataBlocked = (dqs?.missing_datasets || []).length > 0 || (dqs?.stale_datasets || []).length > 0;
    const appearance =
      dataBlocked && (id === "openRecovery" || id === "openReadiness")
        ? "primary"
        : !dataBlocked && (id === "openEvidenceTab" || id === "openBeliefTab")
          ? "primary"
          : "ghost";
    return { id, label, description: shortText(description, 90), appearance };
  });

  return { waitingFor, availableActions };
}
