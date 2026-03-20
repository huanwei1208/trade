import { useDeferredValue, useEffect } from "react";
import { useState } from "react";

import { CandidateQuickPanel } from "../components/CandidateQuickPanel";
import { CandidateTable } from "../components/CandidateTable";
import { ErrorState } from "../components/ErrorState";
import { LoadingSkeleton } from "../components/LoadingSkeleton";
import { RetryInline } from "../components/RetryInline";
import { SectionHeader } from "../components/SectionHeader";
import type { DecisionExplanation, SignalsPageData } from "../lib/api";
import { useApiResource } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { searchCandidate, sortCandidates, useLocalStorageState } from "../lib/ui";

type CandidatesPageProps = {
  refreshToken: number;
  onOpenSymbol: (symbol: string) => void;
  onOpenOps: () => void;
  onOpenOpsFocus: (focus: { tab: "readiness" | "recovery"; date?: string; dataset?: string }) => void;
};

type ActionFilter = "ALL" | "ADD" | "PROBE" | "WATCH" | "NO_ACTION";
type TrustFilter = "ALL" | "HIGH" | "MEDIUM" | "LOW";
type AvailabilityFilter = "ACTIONABLE_ONLY" | "INCLUDE_BLOCKED";

export function CandidatesPage({ refreshToken, onOpenSymbol, onOpenOps, onOpenOpsFocus }: CandidatesPageProps) {
  const { t } = useI18n();
  const resource = useApiResource<SignalsPageData>("/api/signals-page", {
    deps: [refreshToken],
    cacheKey: "trade-web:signals-page",
  });
  const [selectedSymbol, setSelectedSymbol] = useLocalStorageState<string>("trade-web:selected-candidate", "");
  const [actionFilter, setActionFilter] = useState<ActionFilter>("ALL");
  const [trustFilter, setTrustFilter] = useState<TrustFilter>("ALL");
  const [availabilityFilter, setAvailabilityFilter] = useState<AvailabilityFilter>("ACTIONABLE_ONLY");
  const [sortBy, setSortBy] = useState<"confidence" | "trust" | "action" | "latest">("action");
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search);

  const filtered = sortCandidates(
    (resource.data?.picks || []).filter((candidate) => {
      if (actionFilter !== "ALL" && String(candidate.action || "").toUpperCase() !== actionFilter) {
        return false;
      }
      if (trustFilter !== "ALL" && String(candidate.trust_level || "").toUpperCase() !== trustFilter) {
        return false;
      }
      if (availabilityFilter === "ACTIONABLE_ONLY" && String(candidate.action || "").toUpperCase() === "NO_ACTION") {
        return false;
      }
      if (deferredSearch && !searchCandidate(candidate, deferredSearch)) {
        return false;
      }
      return true;
    }),
    sortBy,
  );

  const selectedCandidate = filtered.find((candidate) => candidate.symbol === selectedSymbol) || filtered[0] || null;

  useEffect(() => {
    if (selectedCandidate?.symbol && selectedCandidate.symbol !== selectedSymbol) {
      setSelectedSymbol(selectedCandidate.symbol);
    }
  }, [selectedCandidate?.symbol, selectedSymbol, setSelectedSymbol]);

  const explainResource = useApiResource<DecisionExplanation>(selectedCandidate?.symbol ? `/api/explain/${selectedCandidate.symbol}` : null, {
    deps: [selectedCandidate?.symbol, refreshToken],
    cacheKey: selectedCandidate?.symbol ? `trade-web:explain:${selectedCandidate.symbol}` : undefined,
  });

  if (resource.loading && !resource.data) {
    return <LoadingSkeleton variant="table" />;
  }

  if (resource.error && !resource.data) {
    return (
        <ErrorState
        title={t("candidates.unavailable")}
        body={t("candidates.unavailableCopy")}
        detail={resource.error.message}
        action={
          <div className="state-card__button-row">
            <button type="button" className="button button--primary" onClick={resource.retry}>
              {t("common.retry")}
            </button>
            <button type="button" className="button button--ghost" onClick={onOpenOps}>
              {t("common.openOps")}
            </button>
          </div>
        }
      />
    );
  }

  return (
    <div className="page-stack page-candidates">
      <SectionHeader title={t("candidates.title")} subtitle={t("candidates.subtitle")} />

      {resource.error && resource.data && (
        <RetryInline message={t("candidates.showingStale")} onRetry={resource.retry} />
      )}

      {resource.data?.picks?.some((candidate) => String(candidate.action || "").toUpperCase() === "NO_ACTION") && (
        <div className="page-banner page-banner--muted">
          <strong>{t("candidates.browseOnly")}</strong>
          <span>{t("candidates.globalConstraint")}</span>
          <button
            type="button"
            className="button button--ghost"
            onClick={() => onOpenOpsFocus({ tab: "readiness", date: resource.data?.as_of, dataset: "signals" })}
          >
            {t("common.openReadiness")}
          </button>
        </div>
      )}

      <div className="filter-bar">
        <div className="segmented-group">
          {(["ALL", "ADD", "PROBE", "WATCH", "NO_ACTION"] as ActionFilter[]).map((value) => (
            <button key={value} type="button" className={actionFilter === value ? "is-active" : ""} onClick={() => setActionFilter(value)}>
              {value === "ALL" ? t("candidates.filters.all") : value === "ADD" ? t("candidates.filters.add") : value === "PROBE" ? t("candidates.filters.probe") : value === "WATCH" ? t("candidates.filters.watch") : t("candidates.filters.noAction")}
            </button>
          ))}
        </div>
        <div className="segmented-group">
          {(["ALL", "HIGH", "MEDIUM", "LOW"] as TrustFilter[]).map((value) => (
            <button key={value} type="button" className={trustFilter === value ? "is-active" : ""} onClick={() => setTrustFilter(value)}>
              {value}
            </button>
          ))}
        </div>
        <div className="segmented-group">
          <button type="button" className={availabilityFilter === "ACTIONABLE_ONLY" ? "is-active" : ""} onClick={() => setAvailabilityFilter("ACTIONABLE_ONLY")}>
            {t("candidates.actionableOnly")}
          </button>
          <button type="button" className={availabilityFilter === "INCLUDE_BLOCKED" ? "is-active" : ""} onClick={() => setAvailabilityFilter("INCLUDE_BLOCKED")}>
            {t("candidates.includeBlocked")}
          </button>
        </div>
        <label className="filter-bar__search">
          <span>{t("common.search")}</span>
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder={t("common.search")} />
        </label>
        <label className="filter-bar__search filter-bar__sort">
          <span>{t("common.sort")}</span>
          <select value={sortBy} onChange={(event) => setSortBy(event.target.value as "confidence" | "trust" | "action" | "latest")}>
            <option value="action">{t("candidates.sort.action")}</option>
            <option value="confidence">{t("candidates.sort.confidence")}</option>
            <option value="trust">{t("candidates.sort.trust")}</option>
            <option value="latest">{t("candidates.sort.latest")}</option>
          </select>
        </label>
      </div>

      <div className="candidates-layout">
        <div className="candidates-layout__table">
          {filtered.length === 0 ? (
            <ErrorState
              title={t("candidates.empty")}
              body={t("candidates.emptyCopy")}
              action={
                <button type="button" className="button button--ghost" onClick={() => {
                  setActionFilter("ALL");
                  setTrustFilter("ALL");
                  setAvailabilityFilter("INCLUDE_BLOCKED");
                  setSearch("");
                }}>
                  {t("candidates.resetFilters")}
                </button>
              }
            />
          ) : (
            <CandidateTable rows={filtered} selectedSymbol={selectedCandidate?.symbol} onSelect={(row) => row.symbol && setSelectedSymbol(row.symbol)} onOpenSymbol={onOpenSymbol} />
          )}
        </div>
        <div className="candidates-layout__panel">
          <CandidateQuickPanel
            candidate={selectedCandidate}
            explanation={explainResource.data}
            loading={explainResource.loading}
            error={explainResource.error?.message || null}
            stale={explainResource.stale}
            onRetry={explainResource.retry}
            onOpenSymbol={onOpenSymbol}
            onOpenOps={onOpenOps}
            onOpenReadiness={() => onOpenOpsFocus({ tab: "readiness", date: resource.data?.as_of, dataset: "signals" })}
            onOpenRecovery={() => onOpenOpsFocus({ tab: "recovery", date: resource.data?.as_of, dataset: "signals" })}
          />
        </div>
      </div>
    </div>
  );
}
