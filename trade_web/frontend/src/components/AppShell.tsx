import type { ReactNode } from "react";

import type { Locale, PageKey, TrustOverview } from "../lib/api";
import { formatPercent } from "../lib/format";
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
  onNavigate,
  onLocaleChange,
  onRefresh,
  children,
}: AppShellProps) {
  const navItems: Array<{ key: PageKey; label: string; symbolOnly?: boolean }> = [
    { key: "today", label: "Today" },
    { key: "candidates", label: "Candidates" },
    { key: "symbol", label: selectedSymbol ? `Symbol · ${selectedSymbol}` : "Symbol", symbolOnly: true },
    { key: "ops", label: "Ops" },
  ];

  return (
    <div className="app-shell">
      <aside className="app-sidebar">
        <div className="app-sidebar__brand">
          <div className="app-sidebar__logo">T</div>
          <div>
            <div className="app-sidebar__title">TradeDB</div>
            <div className="app-sidebar__subtitle">Premium decision workspace</div>
          </div>
        </div>

        <nav className="app-sidebar__nav">
          {navItems.map((item) => {
            const disabled = item.symbolOnly && !selectedSymbol;
            return (
              <button
                key={item.key}
                type="button"
                className={classNames("app-sidebar__link", activePage === item.key && "is-active")}
                onClick={() => !disabled && onNavigate(item.key)}
                disabled={disabled}
              >
                <span className="app-sidebar__icon">{item.key === "ops" ? "⌘" : item.key === "symbol" ? "◎" : item.key === "candidates" ? "▤" : "◢"}</span>
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>

        <div className="app-sidebar__footer">
          <div className="app-sidebar__footer-label">Portfolio trust</div>
          <div className="app-sidebar__footer-value">{formatPercent(trustOverview?.trust_scalar, 0)}</div>
          <div className="app-sidebar__footer-subtle">Coverage {formatPercent(trustOverview?.coverage, 0)}</div>
          <div className="app-sidebar__footer-pills">
            <StatusPill label={selectedSymbol ? "Symbol ready" : "Pick a symbol"} tone={selectedSymbol ? "ok" : "muted"} subtle />
            <StatusPill label={`As of ${trustOverview?.as_of || "—"}`} tone="info" subtle />
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
