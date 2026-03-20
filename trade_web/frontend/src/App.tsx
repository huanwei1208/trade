import { AppShell } from "./components/AppShell";
import { useApiResource, type Locale, type PageKey, type TrustOverview } from "./lib/api";
import { formatDateTime } from "./lib/format";
import { getPageMeta, useLocalStorageState } from "./lib/ui";
import { CandidatesPage } from "./pages/CandidatesPage";
import { OpsPage } from "./pages/OpsPage";
import { SymbolPage } from "./pages/SymbolPage";
import { TodayPage } from "./pages/TodayPage";

export default function App() {
  const [locale, setLocale] = useLocalStorageState<Locale>("trade-web:locale", "zh-CN");
  const [page, setPage] = useLocalStorageState<PageKey>("trade-web:page", "today");
  const [selectedSymbol, setSelectedSymbol] = useLocalStorageState<string>("trade-web:selected-symbol", "");
  const [symbolOrigin, setSymbolOrigin] = useLocalStorageState<PageKey>("trade-web:symbol-origin", "today");
  const [refreshToken, setRefreshToken] = useLocalStorageState<number>("trade-web:refresh-seq", 0);

  const trustOverview = useApiResource<TrustOverview>("/api/trust/overview", {
    deps: [refreshToken],
    cacheKey: "trade-web:trust-overview",
  });

  const resolvedPage: PageKey = page === "symbol" && !selectedSymbol ? "today" : page;
  const meta = getPageMeta(resolvedPage, locale, selectedSymbol);
  const asOf = formatDateTime(new Date().toISOString(), locale === "zh-CN" ? "zh-CN" : "en-US");

  function navigate(nextPage: PageKey) {
    if (nextPage === "symbol" && !selectedSymbol) {
      return;
    }
    if (nextPage !== "symbol") {
      setSymbolOrigin(nextPage);
    }
    setPage(nextPage);
  }

  function openSymbol(symbol: string) {
    setSelectedSymbol(symbol);
    if (resolvedPage !== "symbol") {
      setSymbolOrigin(resolvedPage);
    }
    setPage("symbol");
  }

  return (
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
      {resolvedPage === "today" && <TodayPage refreshToken={refreshToken} onOpenSymbol={openSymbol} />}
      {resolvedPage === "candidates" && <CandidatesPage refreshToken={refreshToken} onOpenSymbol={openSymbol} onOpenOps={() => navigate("ops")} />}
      {resolvedPage === "symbol" && <SymbolPage symbol={selectedSymbol} refreshToken={refreshToken} onBack={() => navigate(symbolOrigin || "today")} />}
      {resolvedPage === "ops" && <OpsPage refreshToken={refreshToken} />}
    </AppShell>
  );
}
