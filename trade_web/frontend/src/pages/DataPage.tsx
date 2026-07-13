import { useEffect, useState } from "react";

import { AssetInventoryTable } from "../components/AssetInventoryTable";
import { CoverageMatrix } from "../components/CoverageMatrix";
import { ErrorState } from "../components/ErrorState";
import { GapTimeline } from "../components/GapTimeline";
import { KlineViewer } from "../components/KlineViewer";
import { LoadingSkeleton } from "../components/LoadingSkeleton";
import { NewsFeed } from "../components/NewsFeed";
import { PanelCard } from "../components/PanelCard";
import { StatusPill } from "../components/StatusPill";
import type { DataAsset, DataAssetsPayload } from "../lib/api";
import { getDataAssets } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { classNames, useLocalStorageState } from "../lib/ui";

type DataTab = "assets" | "kline" | "gaps" | "news" | "coverage";

type DataPageProps = {
  refreshToken: number;
};

const TAB_LIST: Array<{ key: DataTab; label: string }> = [
  { key: "assets", label: "Assets" },
  { key: "kline", label: "K-Line" },
  { key: "gaps", label: "Gaps" },
  { key: "news", label: "News" },
  { key: "coverage", label: "Coverage" },
];

export function DataPage({ refreshToken }: DataPageProps) {
  const { t } = useI18n();
  const [tab, setTab] = useLocalStorageState<DataTab>("trade-web:data-tab", "assets");
  const [selectedAsset, setSelectedAsset] = useState<DataAsset | null>(null);
  const [assetsPayload, setAssetsPayload] = useState<DataAssetsPayload | null>(null);
  const [assetsLoading, setAssetsLoading] = useState(false);
  const [assetsError, setAssetsError] = useState<string | null>(null);
  const [assetsVersion, setAssetsVersion] = useState(0);

  // Reload assets when tab becomes assets/kline/gaps (needs asset list) or refresh fires
  useEffect(() => {
    let cancelled = false;
    setAssetsLoading(true);
    setAssetsError(null);
    getDataAssets()
      .then((data) => { if (!cancelled) setAssetsPayload(data); })
      .catch((err) => { if (!cancelled) setAssetsError(err instanceof Error ? err.message : String(err)); })
      .finally(() => { if (!cancelled) setAssetsLoading(false); });
    return () => { cancelled = true; };
  }, [refreshToken, assetsVersion]);

  // Auto-select first non-missing asset when payload arrives and nothing is selected
  useEffect(() => {
    if (!assetsPayload || selectedAsset) return;
    const first = assetsPayload.assets.find((a) => a.health !== "missing") || assetsPayload.assets[0];
    if (first) setSelectedAsset(first);
  }, [assetsPayload, selectedAsset]);

  // Keep selectedAsset synced with payload (e.g. after refresh)
  useEffect(() => {
    if (!assetsPayload || !selectedAsset) return;
    const match = assetsPayload.assets.find((a) => a.asset_id === selectedAsset.asset_id);
    if (match && match !== selectedAsset) {
      setSelectedAsset(match);
    }
  }, [assetsPayload, selectedAsset]);

  const summary = assetsPayload?.summary;
  const assets = assetsPayload?.assets || [];

  return (
    <div className="data-page">
      {/* Summary strip */}
      <div style={{ display: "flex", gap: 12, marginBottom: 16, flexWrap: "wrap", alignItems: "center" }}>
        <PanelCard subdued className="data-summary-card">
          <div style={{ display: "flex", gap: 16, alignItems: "center", padding: "4px 0" }}>
            <SummaryMetric label="Total" value={summary?.total_assets ?? "—"} />
            <SummaryMetric label="OK" value={summary?.ok ?? "—"} tone="ok" />
            <SummaryMetric label="Stale" value={summary?.stale ?? "—"} tone="warn" />
            <SummaryMetric label="Missing" value={summary?.missing ?? "—"} tone="err" />
            {summary?.error !== undefined && summary.error > 0 && (
              <SummaryMetric label="Error" value={summary.error} tone="err" />
            )}
            <button type="button" className="button" onClick={() => setAssetsVersion((v) => v + 1)} style={{ marginLeft: "auto" }}>
              {t("common.refresh")}
            </button>
          </div>
        </PanelCard>
      </div>

      {/* Tabs */}
      <div className="tabs" role="tablist">
        {TAB_LIST.map((item) => (
          <button
            key={item.key}
            type="button"
            role="tab"
            aria-selected={tab === item.key}
            className={classNames("tab", tab === item.key && "active")}
            onClick={() => setTab(item.key)}
          >
            {item.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {tab === "assets" && (
        <PanelCard title="Asset Inventory" subdued>
          {assetsLoading && !assetsPayload ? (
            <LoadingSkeleton variant="panel" />
          ) : assetsError ? (
            <ErrorState title="Failed to load assets" body={assetsError} action={<button type="button" className="button button--primary" onClick={() => setAssetsVersion((v) => v + 1)}>{t("common.retry")}</button>} />
          ) : (
            <AssetInventoryTable
              assets={assets}
              selectedAssetId={selectedAsset?.asset_id}
              onSelectAsset={(a) => setSelectedAsset(a)}
            />
          )}
        </PanelCard>
      )}

      {tab === "kline" && (
        <PanelCard title="K-Line Viewer" subdued actions={
          <AssetQuickSelector assets={assets} selected={selectedAsset} onSelect={setSelectedAsset} />
        }>
          {assetsLoading && !assetsPayload ? (
            <LoadingSkeleton variant="panel" />
          ) : (
            <KlineViewer asset={selectedAsset} />
          )}
        </PanelCard>
      )}

      {tab === "gaps" && (
        <PanelCard title="Data Gap Detection" subdued actions={
          <AssetQuickSelector assets={assets} selected={selectedAsset} onSelect={setSelectedAsset} />
        }>
          {assetsLoading && !assetsPayload ? (
            <LoadingSkeleton variant="panel" />
          ) : (
            <GapTimeline asset={selectedAsset} />
          )}
        </PanelCard>
      )}

      {tab === "news" && (
        <PanelCard title="News Feed" subdued>
          <NewsFeed />
        </PanelCard>
      )}

      {tab === "coverage" && (
        <PanelCard title="Coverage Matrix" subdued>
          <CoverageMatrix />
        </PanelCard>
      )}
    </div>
  );
}

function SummaryMetric({ label, value, tone }: { label: string; value: number | string; tone?: "ok" | "warn" | "err" }) {
  return (
    <div>
      <div style={{ fontSize: "0.7rem", color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>{label}</div>
      <div style={{ fontSize: "1.1rem", fontWeight: 700, color: tone ? `var(--${tone})` : undefined }}>{value}</div>
    </div>
  );
}

function AssetQuickSelector({ assets, selected, onSelect }: { assets: DataAsset[]; selected: DataAsset | null; onSelect: (a: DataAsset) => void }) {
  return (
    <select
      value={selected?.asset_id || ""}
      onChange={(e) => {
        const a = assets.find((x) => x.asset_id === e.target.value);
        if (a) onSelect(a);
      }}
      style={{ maxWidth: 260 }}
    >
      {assets.map((a) => (
        <option key={a.asset_id} value={a.asset_id}>
          {a.symbol} ({a.asset_class})
        </option>
      ))}
    </select>
  );
}
