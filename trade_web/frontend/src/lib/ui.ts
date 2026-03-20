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

export type CandidateSortKey = "confidence" | "trust" | "action" | "latest";

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

export function sortCandidates(rows: CandidateRow[], sortBy: CandidateSortKey) {
  const copy = [...rows];
  copy.sort((left, right) => {
    if (sortBy === "action") {
      return actionPriority(left.action) - actionPriority(right.action);
    }
    if (sortBy === "trust") {
      return (right.trust_score || 0) - (left.trust_score || 0);
    }
    if (sortBy === "confidence") {
      const leftValue = typeof left.confidence === "number" ? left.confidence : actionPriority(left.action) === 0 ? 1 : 0.5;
      const rightValue = typeof right.confidence === "number" ? right.confidence : actionPriority(right.action) === 0 ? 1 : 0.5;
      return rightValue - leftValue;
    }
    return actionPriority(left.action) - actionPriority(right.action);
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
