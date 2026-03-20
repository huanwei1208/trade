import { useEffect, useState } from "react";

import type { CandidateRow, Locale, PageKey, TodayPageData } from "./api";

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
  const copy =
    locale === "zh-CN"
      ? {
          today: ["今日决策", "先看是否能行动，再看为什么。"],
          candidates: ["候选工作台", "筛出值得深挖的少数标的。"],
          symbol: [symbol ? `${symbol} 工作区` : "Symbol 工作区", "图表、证据、失效条件放在同一个决策平面。"],
          ops: ["运营后台", "数据、DAG、工作流与失败恢复。"],
        }
      : {
          today: ["Today", "Start with posture, trust, and blockers."],
          candidates: ["Candidates", "Triage which setups deserve a deeper review."],
          symbol: [symbol ? `${symbol} Workspace` : "Symbol Workspace", "Keep chart, evidence, and invalidation in one place."],
          ops: ["Ops", "Pipeline, data health, workflows, and recovery paths."],
        };
  const [title, subtitle] = copy[page];
  return { title, subtitle };
}

export function getTodayCall(today?: TodayPageData | null): TodayCall {
  if (!today) {
    return {
      key: "DEGRADED",
      tone: "info",
      headline: "Loading today's posture",
      summary: "Waiting for the latest decision snapshot.",
    };
  }

  const posture = String(today.decision_posture || "").toUpperCase();
  if (posture === "ACTIONABLE") {
    return {
      key: "ACTIONABLE",
      tone: "ok",
      headline: "Actionable",
      summary: "At least one setup is strong enough to review for action today.",
    };
  }
  if (posture === "WATCHLIST") {
    return {
      key: "WATCHLIST",
      tone: "warn",
      headline: "Watchlist",
      summary: "Monitor candidates, but conviction is not broad enough for aggressive action.",
    };
  }
  if (posture === "NO_ACTION") {
    return {
      key: "NO_ACTION",
      tone: "info",
      headline: "No Action",
      summary: "The current state supports patience over forced trades.",
    };
  }
  return {
    key: "DEGRADED",
    tone: "err",
    headline: "Degraded",
    summary: "Data freshness or trust blockers are constraining decision quality.",
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
