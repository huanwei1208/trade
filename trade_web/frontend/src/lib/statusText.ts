import type { Locale, TodayPageData } from "./api";
import { translate } from "./i18n";

export type SemanticTone = "ok" | "warn" | "err" | "info" | "muted";

type SemanticText = {
  key: string;
  label: string;
  description: string;
  tone: SemanticTone;
};

function normalize(raw?: string | null) {
  const value = String(raw || "").trim();
  return value ? value.toUpperCase() : "UNKNOWN";
}

function normalizeLower(raw?: string | null) {
  const value = String(raw || "").trim().toLowerCase();
  return value || "unknown";
}

export function getActionText(locale: Locale, action?: string | null) {
  const key = normalize(action);
  return translate(locale, `action.${key}`);
}

export function getDecisionPostureText(locale: Locale, posture?: string | null): SemanticText {
  switch (normalize(posture)) {
    case "ACTIONABLE":
      return {
        key: "ACTIONABLE",
        label: translate(locale, "status.actionable"),
        description: locale === "zh-CN"
          ? "今天至少存在一组值得进入个股工作区复核的机会。"
          : "At least one setup is strong enough to justify a full symbol review today.",
        tone: "ok",
      };
    case "WATCHLIST":
      return {
        key: "WATCHLIST",
        label: translate(locale, "status.watchlist"),
        description: locale === "zh-CN"
          ? "可以继续观察，但当前不宜把结果理解为直接执行信号。"
          : "The setup set is worth monitoring, but not strong enough for direct execution.",
        tone: "warn",
      };
    case "NO_ACTION":
      return {
        key: "NO_ACTION",
        label: translate(locale, "status.noActionRecommended"),
        description: locale === "zh-CN"
          ? "当前更适合等待，而不是强行交易。"
          : "Patience is preferred over forcing a trade right now.",
        tone: "info",
      };
    default:
      return {
        key: "DEGRADED",
        label: translate(locale, "status.decisionConstrained"),
        description: translate(locale, "status.readinessConstraint"),
        tone: "err",
      };
  }
}

export function getGateStatusText(locale: Locale, raw?: string | null): SemanticText {
  switch (normalizeLower(raw)) {
    case "ok":
      return { key: "ok", label: translate(locale, "status.healthy"), description: locale === "zh-CN" ? "关键数据和流程当前处于健康状态。" : "Critical data and pipeline steps are currently healthy.", tone: "ok" };
    case "partial":
      return { key: "partial", label: translate(locale, "status.partiallyReady"), description: locale === "zh-CN" ? "已有部分结果，但仍有缺口或延迟。" : "Some results are present, but important gaps or delays remain.", tone: "warn" };
    case "blocked":
      return { key: "blocked", label: translate(locale, "status.blocked"), description: locale === "zh-CN" ? "关键链路被阻断，不能把结论当成可执行信号。" : "A critical path is blocked, so conclusions should not be used as execution signals.", tone: "err" };
    case "degraded":
      return { key: "degraded", label: translate(locale, "status.constrained"), description: locale === "zh-CN" ? "系统仍可浏览，但关键输入不完整。" : "The system is still browsable, but critical inputs are incomplete.", tone: "warn" };
    case "missing":
      return { key: "missing", label: translate(locale, "status.missing"), description: locale === "zh-CN" ? "需要的数据当前不存在。" : "Required data is currently missing.", tone: "err" };
    default:
      return { key: "unknown", label: translate(locale, "status.unknown"), description: locale === "zh-CN" ? "当前无法判断该状态。" : "The current state cannot be determined.", tone: "muted" };
  }
}

export function getReadinessStatusText(locale: Locale, raw?: string | null): SemanticText {
  switch (normalize(raw)) {
    case "READY":
      return { key: "READY", label: translate(locale, "status.ready"), description: locale === "zh-CN" ? "该数据集在这个日期点具备可用结果。" : "This dataset is usable for the selected day.", tone: "ok" };
    case "LATE_READY":
      return { key: "LATE_READY", label: translate(locale, "status.lateReady"), description: locale === "zh-CN" ? "结果可用，但它是在更晚的快照或补齐后才达到可用状态。" : "Usable, but only after a later snapshot or delayed repair path caught up.", tone: "warn" };
    case "PARTIAL":
      return { key: "PARTIAL", label: translate(locale, "status.partiallyReady"), description: locale === "zh-CN" ? "已经有部分结果，但覆盖和稳定性还不完整。" : "Some usable results exist, but coverage or stability is still incomplete.", tone: "warn" };
    case "MISSING":
      return { key: "MISSING", label: translate(locale, "status.missing"), description: locale === "zh-CN" ? "该日期点缺少可用数据，前台结论可能受影响。" : "Usable data is missing for this day, so front-stage outputs may be constrained.", tone: "err" };
    case "CHANGED":
      return { key: "CHANGED", label: translate(locale, "status.changed"), description: locale === "zh-CN" ? "底层数据发生变化，等待或需要下游重算。" : "Underlying data changed and downstream recompute is pending or required.", tone: "info" };
    case "REPLAYING":
      return { key: "REPLAYING", label: translate(locale, "status.replaying"), description: locale === "zh-CN" ? "下游恢复或重算正在进行中。" : "Downstream recovery or replay is currently running.", tone: "info" };
    case "REPLAYED":
      return { key: "REPLAYED", label: translate(locale, "status.replayed"), description: locale === "zh-CN" ? "恢复链路已经跑完，结果已刷新。" : "Recovery replay completed and outputs were refreshed.", tone: "ok" };
    default:
      return { key: "UNKNOWN", label: translate(locale, "status.unknown"), description: locale === "zh-CN" ? "当前无法判定该日期点的就绪状态。" : "The readiness state for this day cannot be determined.", tone: "muted" };
  }
}

export function getTrustLevelText(locale: Locale, score?: number | null, rawLevel?: string | null): SemanticText {
  const level = normalize(rawLevel || (score === null || score === undefined ? "UNKNOWN" : score > 0.7 ? "HIGH" : score > 0.4 ? "MEDIUM" : "LOW"));
  if (level === "HIGH") {
    return { key: "HIGH", label: translate(locale, "status.highTrust"), description: translate(locale, "status.highTrustNarrative"), tone: "ok" };
  }
  if (level === "MEDIUM") {
    return { key: "MEDIUM", label: translate(locale, "status.mediumTrust"), description: translate(locale, "status.mediumTrustNarrative"), tone: "warn" };
  }
  if (level === "LOW") {
    return { key: "LOW", label: translate(locale, "status.lowTrust"), description: translate(locale, "status.lowTrustNarrative"), tone: "err" };
  }
  return { key: "UNKNOWN", label: translate(locale, "status.unknown"), description: locale === "zh-CN" ? "当前未返回可信的信任分层。" : "No reliable trust layer was returned.", tone: "muted" };
}

export function getTrustNarrative(locale: Locale, score?: number | null, rawLevel?: string | null, constrained?: boolean) {
  const base = getTrustLevelText(locale, score, rawLevel);
  if (constrained && base.key === "HIGH") {
    return {
      ...base,
      description: translate(locale, "status.highTrustConstrained"),
      tone: "warn" as SemanticTone,
    };
  }
  if (constrained && base.key === "MEDIUM") {
    return {
      ...base,
      description: translate(locale, "status.mediumTrustConstrained"),
    };
  }
  return base;
}

export function getConclusionModeText(locale: Locale, today?: TodayPageData | null): SemanticText {
  const constrained = Boolean(today?.global_blocked || (today?.blockers || []).length);
  if (constrained) {
    return {
      key: "BROWSE_ONLY",
      label: translate(locale, "status.browseOnly"),
      description: translate(locale, "today.restrictedMode"),
      tone: "warn",
    };
  }
  return {
    key: "DIRECT_REVIEW",
    label: translate(locale, "status.directReview"),
    description: translate(locale, "today.directUse"),
    tone: "ok",
  };
}

export function getMarketRegimeText(locale: Locale, raw?: string | null): SemanticText {
  const regime = normalize(raw);
  if (!raw || regime === "UNKNOWN") {
    return {
      key: "UNKNOWN",
      label: translate(locale, "status.marketUnavailable"),
      description: locale === "zh-CN" ? "当前没有足够输入来判断市场状态。" : "There is not enough signal to classify the current market state.",
      tone: "muted",
    };
  }
  return {
    key: regime,
    label: translate(locale, `regime.market.${regime}`),
    description: translate(locale, `regime.market.${regime}`),
    tone: regime === "TRENDING_UP" ? "ok" : regime === "TRENDING_DOWN" ? "err" : regime === "VOLATILE" ? "warn" : "info",
  };
}

export function getWorldStateLabel(locale: Locale, kind: "market" | "event" | "sentiment" | "technical" | "liquidity" | "uncertainty", raw?: string | null) {
  const value = normalize(raw);
  return translate(locale, `regime.${kind}.${value}`);
}

export function getDatasetText(locale: Locale, dataset?: string | null, fallback?: string | null) {
  const key = `dataset.${String(dataset || "").trim()}`;
  const translated = translate(locale, key);
  if (translated !== key) {
    return translated;
  }
  return fallback || String(dataset || translate(locale, "common.unknown"));
}

export function getImpactText(locale: Locale, key?: string | null) {
  return translate(locale, `impact.${String(key || "").trim()}`);
}

export function getTodayUsageCopy(locale: Locale, today?: TodayPageData | null) {
  const posture = getDecisionPostureText(locale, today?.decision_posture);
  const conclusionMode = getConclusionModeText(locale, today);
  const trust = getTrustNarrative(locale, today?.trust_gate?.trust_scalar ?? undefined, undefined, conclusionMode.key === "BROWSE_ONLY");
  return {
    posture,
    conclusionMode,
    trust,
    whyConstrained: (today?.blockers || []).join(" · ") || translate(locale, "status.readinessConstraint"),
    recoveryPath: today?.recovery_condition || translate(locale, "status.recoveryPathDefault"),
  };
}

export function getReadinessWarning(locale: Locale, constrained: boolean) {
  return constrained ? translate(locale, "status.readinessConstraint") : "";
}
