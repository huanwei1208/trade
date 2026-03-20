import { useEffect } from "react";

import { AppShell } from "./components/AppShell";
import { useApiResource, type Locale, type PageKey, type TrustOverview } from "./lib/api";
import { formatDateTime } from "./lib/format";
import { I18nProvider } from "./lib/i18n";
import { getPageMeta, useLocalStorageState } from "./lib/ui";
import { CandidatesPage } from "./pages/CandidatesPage";
import { OpsPage } from "./pages/OpsPage";
import { SymbolPage } from "./pages/SymbolPage";
import { TodayPage } from "./pages/TodayPage";

type OpsFocus = {
  tab?: "overview" | "readiness" | "recovery" | "pipeline" | "trust" | "workflows";
  date?: string;
  dataset?: string;
};

function readInitialQuery() {
  if (typeof window === "undefined") {
    return { page: undefined as PageKey | undefined, opsFocus: {} as OpsFocus };
  }
  const params = new URLSearchParams(window.location.search);
  const opsTab = params.get("opsTab");
  if (!opsTab) {
    return { page: undefined as PageKey | undefined, opsFocus: {} as OpsFocus };
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
  return { page: "ops" as PageKey, opsFocus };
}

export default function App() {
  const initialQuery = readInitialQuery();
  const [locale, setLocale] = useLocalStorageState<Locale>("trade-web:locale", "zh-CN");
  const [page, setPage] = useLocalStorageState<PageKey>("trade-web:page", initialQuery.page || "today");
  const [selectedSymbol, setSelectedSymbol] = useLocalStorageState<string>("trade-web:selected-symbol", "");
  const [symbolOrigin, setSymbolOrigin] = useLocalStorageState<PageKey>("trade-web:symbol-origin", "today");
  const [refreshToken, setRefreshToken] = useLocalStorageState<number>("trade-web:refresh-seq", 0);
  const [opsFocus, setOpsFocus] = useLocalStorageState<OpsFocus>("trade-web:ops-focus", initialQuery.opsFocus);

  const trustOverview = useApiResource<TrustOverview>("/api/trust/overview", {
    deps: [refreshToken],
    cacheKey: "trade-web:trust-overview",
  });

  const resolvedPage: PageKey = page === "symbol" && !selectedSymbol ? "today" : page;
  const meta = getPageMeta(resolvedPage, locale, selectedSymbol);
  const asOf = formatDateTime(new Date().toISOString(), locale === "zh-CN" ? "zh-CN" : "en-US");

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const params = new URLSearchParams(window.location.search);
    if (resolvedPage === "ops" && opsFocus.tab) {
      params.set("opsTab", opsFocus.tab);
      if (opsFocus.date) {
        params.set("date", opsFocus.date);
      } else {
        params.delete("date");
      }
      if (opsFocus.dataset) {
        params.set("dataset", opsFocus.dataset);
      } else {
        params.delete("dataset");
      }
    } else {
      params.delete("opsTab");
      params.delete("date");
      params.delete("dataset");
    }
    const query = params.toString();
    window.history.replaceState({}, "", `${window.location.pathname}${query ? `?${query}` : ""}`);
  }, [resolvedPage, opsFocus]);

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
        onNavigate={navigate}
        onLocaleChange={setLocale}
        onRefresh={() => setRefreshToken((current) => current + 1)}
      >
        {resolvedPage === "today" && <TodayPage refreshToken={refreshToken} onOpenSymbol={openSymbol} onOpenOpsFocus={openOpsFocus} />}
        {resolvedPage === "candidates" && <CandidatesPage refreshToken={refreshToken} onOpenSymbol={openSymbol} onOpenOps={() => navigate("ops")} onOpenOpsFocus={openOpsFocus} />}
        {resolvedPage === "symbol" && <SymbolPage symbol={selectedSymbol} refreshToken={refreshToken} onBack={() => navigate(symbolOrigin || "today")} onOpenOpsFocus={openOpsFocus} />}
        {resolvedPage === "ops" && <OpsPage refreshToken={refreshToken} focus={opsFocus} onFocusChange={setOpsFocus} />}
      </AppShell>
    </I18nProvider>
  );
}
