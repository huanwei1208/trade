import { useEffect, useState } from "react";

import type { WorkspaceTab } from "../lib/api";
import { useI18n } from "../lib/i18n";

const STORAGE_KEY = "trade-web:symbol-workspace-tab";

const TABS: { id: WorkspaceTab; labelKey: string }[] = [
  { id: "decision", labelKey: "symbol.tab.decision" },
  { id: "belief", labelKey: "symbol.tab.belief" },
  { id: "timeline", labelKey: "symbol.tab.timeline" },
  { id: "data-trust", labelKey: "symbol.tab.dataTrust" },
];

function readPersistedTab(): WorkspaceTab {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw === "decision" || raw === "belief" || raw === "timeline" || raw === "data-trust") {
      return raw;
    }
  } catch {
    // ignore
  }
  return "decision";
}

type Props = {
  activeTab: WorkspaceTab;
  onChange: (tab: WorkspaceTab) => void;
};

export function SymbolWorkspaceTabs({ activeTab, onChange }: Props) {
  const { t } = useI18n();

  function handleClick(tab: WorkspaceTab) {
    try {
      window.localStorage.setItem(STORAGE_KEY, tab);
    } catch {
      // ignore
    }
    onChange(tab);
  }

  return (
    <nav className="symbol-workspace-tabs" aria-label={t("symbol.tab.ariaLabel")}>
      {TABS.map(({ id, labelKey }) => (
        <button
          key={id}
          type="button"
          className={`symbol-workspace-tabs__tab${activeTab === id ? " is-active" : ""}`}
          onClick={() => handleClick(id)}
          aria-selected={activeTab === id}
        >
          {t(labelKey)}
        </button>
      ))}
    </nav>
  );
}

export function useWorkspaceTab(): [WorkspaceTab, (tab: WorkspaceTab) => void] {
  const [tab, setTab] = useState<WorkspaceTab>(() => readPersistedTab());

  function setTabAndPersist(next: WorkspaceTab) {
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // ignore
    }
    setTab(next);
  }

  return [tab, setTabAndPersist];
}
