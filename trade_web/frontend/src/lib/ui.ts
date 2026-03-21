import { useEffect, useState } from "react";

import type { CandidateRow, Locale, PageKey, TodayPageData } from "./api";
import { translate } from "./i18n";
import { getDecisionPostureText } from "./statusText";

export type TodayCall = {
  key: "ACTIONABLE" | "WATCHLIST" | "NO_ACTION" | "DEGRADED";
  tone: "ok" | "warn" | "err" | "info";
  headline: string;
  summary: string;
};

export type CandidateSortKey =
  | "action"
  | "confidence"
  | "trust"
  | "belief"
  | "belief_delta"
  | "risk"
  | "risk_adjusted"
  | "latest";

export function useLocalStorageState<T>(key: string, initialValue: T) {
  const [value, setValue] = useState<T>(() => {
    if (typeof window === "undefined") {
      return initialValue;
    }
    try {
      const stored = window.localStorage.getItem(key);
      return stored ? (JSON.parse(stored) as T) : initialValue;
    } catch {
      return initialValue;
    }
  });

  useEffect(() => {
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
    } catch {
      // ignore persistence failures
    }
  }, [key, value]);

  return [value, setValue] as const;
}

export function getPageMeta(page: PageKey, locale: Locale, symbol?: string) {
  const titleKey = page === "symbol" && symbol ? "page.symbol.titleWithCode" : `page.${page}.title`;
  const title = translate(locale, titleKey, { symbol });
  const subtitle = translate(locale, `page.${page}.subtitle`);
  return { title, subtitle };
}

export function getTodayCall(today: TodayPageData | null | undefined, locale: Locale): TodayCall {
  if (!today) {
    return {
      key: "DEGRADED",
      tone: "info",
      headline: locale === "zh-CN" ? "正在加载今日判断" : "Loading today's posture",
      summary: locale === "zh-CN" ? "等待最新决策快照返回。" : "Waiting for the latest decision snapshot.",
    };
  }

  const posture = getDecisionPostureText(locale, today.decision_posture);
  return {
    key: posture.key as TodayCall["key"],
    tone: posture.tone as TodayCall["tone"],
    headline: posture.label,
    summary: posture.description,
  };
}

export function actionPriority(action?: string | null) {
  const normalized = String(action || "").toUpperCase();
  return {
    ADD: 0,
    PROBE: 1,
    WATCH: 2,
    REDUCE: 3,
    NO_ACTION: 4,
  }[normalized] ?? 9;
}

export function isActionable(action?: string | null) {
  return ["ADD", "PROBE", "WATCH", "REDUCE"].includes(String(action || "").toUpperCase());
}

export function getTrustLevel(score?: number | null, existing?: string | null) {
  if (existing) {
    return existing;
  }
  if (score === null || score === undefined) {
    return "UNKNOWN";
  }
  if (score > 0.7) {
    return "HIGH";
  }
  if (score > 0.4) {
    return "MEDIUM";
  }
  return "LOW";
}

export function sortCandidates(rows: CandidateRow[], sortBy: CandidateSortKey, dir: "desc" | "asc" = "desc") {
  const copy = [...rows];
  const sign = dir === "asc" ? 1 : -1;

  copy.sort((left, right) => {
    let diff = 0;

    if (sortBy === "action") {
      // action priority is always ascending (ADD < PROBE < WATCH ...)
      diff = actionPriority(left.action) - actionPriority(right.action);
      return dir === "asc" ? -diff : diff;
    }
    if (sortBy === "trust") {
      diff = (left.trust_score || 0) - (right.trust_score || 0);
    } else if (sortBy === "confidence") {
      const lv = typeof left.confidence === "number" ? left.confidence : actionPriority(left.action) === 0 ? 1 : 0.5;
      const rv = typeof right.confidence === "number" ? right.confidence : actionPriority(right.action) === 0 ? 1 : 0.5;
      diff = lv - rv;
    } else if (sortBy === "belief") {
      diff = (left.belief_mu ?? -99) - (right.belief_mu ?? -99);
    } else if (sortBy === "belief_delta") {
      diff = (left.belief_delta_mu ?? 0) - (right.belief_delta_mu ?? 0);
    } else if (sortBy === "risk") {
      // For risk: lower is better, so ascending means "least risky first"
      diff = (left.risk ?? 0) - (right.risk ?? 0);
      return dir === "asc" ? diff : -diff;
    } else if (sortBy === "risk_adjusted") {
      // score / (1 + risk) — higher is better
      const ls = (left.score || 0) / (1 + (left.risk || 0));
      const rs = (right.score || 0) / (1 + (right.risk || 0));
      diff = ls - rs;
    } else {
      // fallback: action priority
      diff = actionPriority(left.action) - actionPriority(right.action);
    }

    return -sign * diff;
  });
  return copy;
}

export function searchCandidate(candidate: CandidateRow, query: string) {
  const text = `${candidate.symbol || ""} ${candidate.name || ""} ${candidate.thesis || ""}`.toLowerCase();
  return text.includes(query.trim().toLowerCase());
}

export function classNames(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}
