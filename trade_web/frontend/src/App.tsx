import { useEffect } from "react";

import { AppShell } from "./components/AppShell";
import { useApiResource, type Locale, type ObsCapability, type PageKey, type TrustOverview } from "./lib/api";
import { observatoryCapabilityPath } from "./lib/api";
import { formatDateTime } from "./lib/format";
import { I18nProvider } from "./lib/i18n";
import {
  DEFAULT_OBS_URL_STATE,
  deserializeObservatoryState,
  serializeObservatoryState,
  urlHasObservatory,
  type ObservatoryUrlState,
} from "./lib/observatory";
import { getPageMeta, useLocalStorageState } from "./lib/ui";
import { CandidatesPage } from "./pages/CandidatesPage";
import { DataPage } from "./pages/DataPage";
import { ObservatoryPage } from "./pages/observatory/ObservatoryPage";
import { OpsPage } from "./pages/OpsPage";
import { ResearchPage } from "./pages/ResearchPage";
import { SymbolPage } from "./pages/SymbolPage";
import { TodayPage } from "./pages/TodayPage";

type OpsFocus = {
  tab?: "overview" | "automation" | "readiness" | "compute" | "replay" | "trust" | "audit" | "recovery" | "pipeline" | "workflows";
  date?: string;
  dataset?: string;
};

function readInitialQuery() {
  if (typeof window === "undefined") {
    return {
      page: undefined as PageKey | undefined,
      opsFocus: {} as OpsFocus,
      obsState: undefined as ObservatoryUrlState | undefined,
    };
  }
  const params = new URLSearchParams(window.location.search);
  // Observatory URL state wins when its params are present (fixed-URL restore).
  if (urlHasObservatory(params)) {
    const obsState = deserializeObservatoryState(params);
    try {
      window.localStorage.setItem("trade-web:page", JSON.stringify("observatory"));
      window.localStorage.setItem("trade-web:obs-state", JSON.stringify(obsState));
    } catch {
      // ignore — storage quota or private mode
    }
    return { page: "observatory" as PageKey, opsFocus: {} as OpsFocus, obsState };
  }
  const opsTab = params.get("opsTab");
  if (!opsTab) {
    return { page: undefined as PageKey | undefined, opsFocus: {} as OpsFocus, obsState: undefined };
  }
  const date = params.get("date") || undefined;
  const dataset = params.get("dataset") || undefined;
  const opsFocus: OpsFocus = {
    tab: opsTab as OpsFocus["tab"],
    date,
    dataset,
  };
  // URL params must win over stale localStorage. Write synchronously here so
  // useLocalStorageState's lazy initializer (called after this function)
  // reads the correct values on first render.
  try {
    window.localStorage.setItem("trade-web:page", JSON.stringify("ops"));
    window.localStorage.setItem("trade-web:ops-focus", JSON.stringify(opsFocus));
  } catch {
    // ignore — storage quota or private mode
  }
  return { page: "ops" as PageKey, opsFocus, obsState: undefined };
}

export default function App() {
  const initialQuery = readInitialQuery();
  const [locale, setLocale] = useLocalStorageState<Locale>("trade-web:locale", "zh-CN");
  const [page, setPage] = useLocalStorageState<PageKey>("trade-web:page", initialQuery.page || "today");
  const [selectedSymbol, setSelectedSymbol] = useLocalStorageState<string>("trade-web:selected-symbol", "");
  const [symbolOrigin, setSymbolOrigin] = useLocalStorageState<PageKey>("trade-web:symbol-origin", "today");
  const [refreshToken, setRefreshToken] = useLocalStorageState<number>("trade-web:refresh-seq", 0);
  const [opsFocus, setOpsFocus] = useLocalStorageState<OpsFocus>("trade-web:ops-focus", initialQuery.opsFocus);
  const [obsState, setObsState] = useLocalStorageState<ObservatoryUrlState>(
    "trade-web:obs-state",
    initialQuery.obsState || DEFAULT_OBS_URL_STATE,
  );

  const trustOverview = useApiResource<TrustOverview>("/api/trust/overview", {
    deps: [refreshToken],
    cacheKey: "trade-web:trust-overview",
  });

  // RA.1 (F14): read-only Observatory rollout capability. Nav visibility and the
  // Observatory page render are gated on a FRESH, successful capability response so
  // an unprepared/disabled installation never advertises or opens a broken page.
  //
  // Fail closed on freshness (docs/27 Phase A): the capability is deliberately NOT
  // given a localStorage cacheKey — it must never be persisted as an authorization
  // cache. Only a fresh success (not loading, not revalidating, not stale, not
  // served from cache, no error) with show_nav===true authorizes. Every other state
  // — cached/previous ready, loading, stale, revalidating, error, unknown, disabled,
  // missing, catalog_stale, catalog_corrupt — denies nav and never mounts Observatory.
  const observatoryCapability = useApiResource<ObsCapability>(observatoryCapabilityPath(), {
    deps: [refreshToken],
  });
  const observatoryAuthorized =
    observatoryCapability.data?.show_nav === true &&
    observatoryCapability.loading === false &&
    observatoryCapability.revalidating === false &&
    observatoryCapability.stale === false &&
    observatoryCapability.fromCache === false &&
    observatoryCapability.error === null;

  const requestedPage: PageKey = page === "symbol" && !selectedSymbol ? "today" : page;
  // If Observatory is not freshly authorized, fall back to Today even when
  // localStorage or the URL (e.g. a direct ?obsLens link) requested it. This also
  // covers a rollback or an unbuilt/corrupt catalog.
  const resolvedPage: PageKey = requestedPage === "observatory" && !observatoryAuthorized ? "today" : requestedPage;
  const meta = getPageMeta(resolvedPage, locale, selectedSymbol);
  const asOf = formatDateTime(new Date().toISOString(), locale === "zh-CN" ? "zh-CN" : "en-US");

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const params = new URLSearchParams(window.location.search);
    // Reset scoped params first so lenses don't leak across pages.
    for (const key of ["opsTab", "date", "dataset", "obsLens", "obsChannel", "knowledgeAsOf", "obsRange", "obsRun", "obsCompare", "obsDate"]) {
      params.delete(key);
    }
    if (resolvedPage === "observatory") {
      const obsParams = serializeObservatoryState(obsState);
      obsParams.forEach((value, key) => params.set(key, value));
    } else if (resolvedPage === "ops" && opsFocus.tab) {
      params.set("opsTab", opsFocus.tab);
      if (opsFocus.date) {
        params.set("date", opsFocus.date);
      }
      if (opsFocus.dataset) {
        params.set("dataset", opsFocus.dataset);
      }
    }
    const query = params.toString();
    window.history.replaceState({}, "", `${window.location.pathname}${query ? `?${query}` : ""}`);
  }, [resolvedPage, opsFocus, obsState]);

  function navigate(nextPage: PageKey) {
    if (nextPage === "symbol" && !selectedSymbol) {
      return;
    }
    if (nextPage !== "symbol") {
      setSymbolOrigin(nextPage);
    }
    setPage(nextPage);
  }

  function openOpsFocus(nextFocus: OpsFocus) {
    setOpsFocus((current) => ({
      ...current,
      ...nextFocus,
    }));
    setPage("ops");
  }

  function openSymbol(symbol: string) {
    setSelectedSymbol(symbol);
    if (resolvedPage !== "symbol") {
      setSymbolOrigin(resolvedPage);
    }
    setPage("symbol");
  }

  function updateObsState(next: Partial<ObservatoryUrlState>) {
    setObsState((current) => ({ ...current, ...next }));
  }

  return (
    <I18nProvider locale={locale}>
      <AppShell
        activePage={resolvedPage}
        pageTitle={meta.title}
        pageSubtitle={meta.subtitle}
        locale={locale}
        asOf={asOf}
        selectedSymbol={selectedSymbol}
        trustOverview={trustOverview.data}
        observatoryAuthorized={observatoryAuthorized}
        onNavigate={navigate}
        onLocaleChange={setLocale}
        onRefresh={() => setRefreshToken((current) => current + 1)}
      >
        {resolvedPage === "today" && <TodayPage refreshToken={refreshToken} onOpenSymbol={openSymbol} onOpenOpsFocus={openOpsFocus} onOpenCandidates={() => navigate("candidates")} />}
        {resolvedPage === "candidates" && <CandidatesPage refreshToken={refreshToken} onOpenSymbol={openSymbol} onOpenOps={() => navigate("ops")} onOpenOpsFocus={openOpsFocus} />}
        {resolvedPage === "symbol" && <SymbolPage symbol={selectedSymbol} refreshToken={refreshToken} onBack={() => navigate(symbolOrigin || "today")} onOpenOpsFocus={openOpsFocus} />}
        {resolvedPage === "observatory" && <ObservatoryPage refreshToken={refreshToken} urlState={obsState} onUrlStateChange={updateObsState} />}
        {resolvedPage === "research" && <ResearchPage refreshToken={refreshToken} />}
        {resolvedPage === "ops" && <OpsPage refreshToken={refreshToken} focus={opsFocus} onFocusChange={setOpsFocus} />}
        {resolvedPage === "data" && <DataPage refreshToken={refreshToken} />}
      </AppShell>
    </I18nProvider>
  );
}
