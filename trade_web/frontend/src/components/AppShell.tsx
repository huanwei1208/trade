import type { ReactNode } from "react";

import type { Locale, PageKey, TrustOverview } from "../lib/api";
import { formatPercent } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { classNames } from "../lib/ui";
import { TopNav } from "./TopNav";
import { StatusPill } from "./StatusPill";

type AppShellProps = {
  activePage: PageKey;
  pageTitle: string;
  pageSubtitle: string;
  locale: Locale;
  asOf: string;
  selectedSymbol?: string;
  trustOverview?: TrustOverview | null;
  observatoryAuthorized?: boolean;
  onNavigate: (page: PageKey) => void;
  onLocaleChange: (locale: Locale) => void;
  onRefresh: () => void;
  children: ReactNode;
};

export function AppShell({
  activePage,
  pageTitle,
  pageSubtitle,
  locale,
  asOf,
  selectedSymbol,
  trustOverview,
  observatoryAuthorized,
  onNavigate,
  onLocaleChange,
  onRefresh,
  children,
}: AppShellProps) {
  const { t } = useI18n();
  // RA.1 (F14): the Observatory nav entry is shown only when the App has computed a
  // FRESH, successful capability authorization (see App.tsx `observatoryAuthorized`).
  // `catalog_stale` is allowed so operators can open Observatory and see explicit
  // stale states; cached/previous ready, loading, stale, revalidating, error,
  // unknown, disabled, missing and catalog_corrupt all leave it hidden.
  const observatoryReady = observatoryAuthorized === true;
  const navItems: Array<{ key: PageKey; label: string; symbolOnly?: boolean }> = [
    { key: "today", label: t("nav.today") },
    { key: "candidates", label: t("nav.candidates") },
    {
      key: "symbol",
      label: selectedSymbol ? t("nav.symbolWithCode", { symbol: selectedSymbol }) : t("nav.symbol"),
      symbolOnly: true,
    },
    ...(observatoryReady ? [{ key: "observatory" as PageKey, label: t("nav.observatory") }] : []),
    { key: "research", label: t("nav.research") },
    { key: "data", label: t("nav.data") },
    { key: "ops", label: t("nav.ops") },
  ];

  return (
    <div className="app-shell">
      <aside className="app-sidebar">
        <div className="app-sidebar__brand">
          <div className="app-sidebar__logo">T</div>
          <div>
            <div className="app-sidebar__title">TradeDB</div>
            <div className="app-sidebar__subtitle">{t("app.brandSubtitle")}</div>
          </div>
        </div>

        <nav className="app-sidebar__nav">
          {navItems.map((item) => {
            const disabled = item.symbolOnly && !selectedSymbol;
            return (
              <button
                key={item.key}
                type="button"
                data-testid={`nav-${item.key}`}
                className={classNames("app-sidebar__link", activePage === item.key && "is-active")}
                onClick={() => !disabled && onNavigate(item.key)}
                disabled={disabled}
              >
                <span className="app-sidebar__icon">
                  {item.key === "ops"
                    ? "⌘"
                    : item.key === "research"
                      ? "◇"
                      : item.key === "observatory"
                        ? "◉"
                        : item.key === "symbol"
                          ? "◎"
                          : item.key === "candidates"
                            ? "▤"
                            : item.key === "data"
                              ? "▣"
                              : "◢"}
                </span>
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>

        <div className="app-sidebar__footer">
          <div className="app-sidebar__footer-label">{t("shell.portfolioTrust")}</div>
          <div className="app-sidebar__footer-value">
            {formatPercent(trustOverview?.trust_scalar, 0)}
          </div>
          <div className="app-sidebar__footer-subtle">
            {t("shell.coverage")} {formatPercent(trustOverview?.coverage, 0)}
          </div>
          <div className="app-sidebar__footer-pills">
            <StatusPill
              label={selectedSymbol ? t("shell.symbolReady") : t("shell.pickSymbol")}
              tone={selectedSymbol ? "ok" : "muted"}
              subtle
            />
            <StatusPill
              label={t("shell.asOf", { date: trustOverview?.as_of || "—" })}
              tone="info"
              subtle
            />
          </div>
        </div>
      </aside>

      <main className="app-main">
        <TopNav
          title={pageTitle}
          subtitle={pageSubtitle}
          locale={locale}
          asOf={asOf}
          onLocaleChange={onLocaleChange}
          onRefresh={onRefresh}
        />
        <div className="app-content">{children}</div>
      </main>
    </div>
  );
}
