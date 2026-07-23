import { useMemo, useState } from "react";

import type { DataAsset, DataAssetHealth, DataAssetObservability } from "../lib/api";
import { classNames } from "../lib/ui";

type SortKey = "symbol" | "asset_class" | "health" | "lag_days" | "total_rows" | "last_date";
type SortDir = "asc" | "desc";

type AssetInventoryTableProps = {
  assets: DataAsset[];
  onSelectAsset?: (asset: DataAsset) => void;
  selectedAssetId?: string;
  observabilityByAsset?: Record<string, DataAssetObservability | undefined>;
};

function HealthBadge({ health }: { health: DataAssetHealth }) {
  const toneMap: Record<DataAssetHealth, string> = {
    ok: "pill ok",
    stale: "pill partial",
    missing: "pill error",
    error: "pill error",
  };
  const label: Record<DataAssetHealth, string> = {
    ok: "OK",
    stale: "Stale",
    missing: "Missing",
    error: "Error",
  };
  return <span className={toneMap[health]}>{label[health]}</span>;
}

function observedHealth(asset: DataAsset, observed?: DataAssetObservability): DataAssetHealth {
  if (!observed || observed.status !== "confirmed") {
    return asset.health;
  }
  if (observed.quality_state === "degraded" || observed.lifecycle_state === "staged") {
    return "stale";
  }
  if (observed.lag_days !== null && observed.lag_days > 2) {
    return "stale";
  }
  return "ok";
}

function observedLastDate(asset: DataAsset, observed?: DataAssetObservability): string | null {
  return observed?.status === "confirmed" ? observed.last_date : asset.last_date;
}

function observedLagDays(asset: DataAsset, observed?: DataAssetObservability): number {
  if (observed?.status === "confirmed" && observed.lag_days !== null) {
    return observed.lag_days;
  }
  return asset.lag_days;
}

export function AssetInventoryTable({
  assets,
  onSelectAsset,
  selectedAssetId,
  observabilityByAsset = {},
}: AssetInventoryTableProps) {
  const [sortKey, setSortKey] = useState<SortKey>("health");
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const [classFilter, setClassFilter] = useState<string>("all");
  const [healthFilter, setHealthFilter] = useState<string>("all");

  const classes = useMemo(() => {
    const set = new Set<string>();
    for (const a of assets) {
      if (a.asset_class) set.add(a.asset_class);
    }
    return Array.from(set).sort();
  }, [assets]);

  const filtered = useMemo(() => {
    return assets.filter((a) => {
      if (classFilter !== "all" && a.asset_class !== classFilter) return false;
      if (healthFilter !== "all" && a.health !== healthFilter) return false;
      return true;
    });
  }, [assets, classFilter, healthFilter]);

  const sorted = useMemo(() => {
    const copy = [...filtered];
    const sign = sortDir === "asc" ? 1 : -1;
    copy.sort((a, b) => {
      let diff = 0;
      switch (sortKey) {
        case "symbol":
          diff = a.symbol.localeCompare(b.symbol);
          break;
        case "asset_class":
          diff = a.asset_class.localeCompare(b.asset_class);
          break;
        case "health": {
          const order: Record<DataAssetHealth, number> = { error: 0, missing: 1, stale: 2, ok: 3 };
          diff =
            (order[observedHealth(a, observabilityByAsset[a.asset_id])] ?? 9) -
            (order[observedHealth(b, observabilityByAsset[b.asset_id])] ?? 9);
          break;
        }
        case "lag_days":
          diff =
            observedLagDays(a, observabilityByAsset[a.asset_id]) -
            observedLagDays(b, observabilityByAsset[b.asset_id]);
          break;
        case "total_rows":
          diff = (a.total_rows ?? 0) - (b.total_rows ?? 0);
          break;
        case "last_date":
          diff = (observedLastDate(a, observabilityByAsset[a.asset_id]) || "").localeCompare(
            observedLastDate(b, observabilityByAsset[b.asset_id]) || "",
          );
          break;
      }
      return sign * diff;
    });
    return copy;
  }, [filtered, sortKey, sortDir, observabilityByAsset]);

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  }

  function SortHeader({ k, label }: { k: SortKey; label: string }) {
    return (
      <th onClick={() => toggleSort(k)} style={{ cursor: "pointer", userSelect: "none" }}>
        {label} {sortKey === k ? (sortDir === "asc" ? "▲" : "▼") : ""}
      </th>
    );
  }

  return (
    <div>
      <div className="filter-bar" style={{ marginBottom: 12 }}>
        <select value={classFilter} onChange={(e) => setClassFilter(e.target.value)}>
          <option value="all">All classes</option>
          {classes.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        <select value={healthFilter} onChange={(e) => setHealthFilter(e.target.value)}>
          <option value="all">All health</option>
          <option value="ok">OK</option>
          <option value="stale">Stale</option>
          <option value="missing">Missing</option>
          <option value="error">Error</option>
        </select>
        <span style={{ color: "var(--muted)", fontSize: "0.8rem", marginLeft: "auto" }}>
          {sorted.length} / {assets.length} assets
        </span>
      </div>
      <div className="table-wrap">
        <table className="picks-table">
          <thead>
            <tr>
              <SortHeader k="symbol" label="Symbol" />
              <SortHeader k="asset_class" label="Class" />
              <th>Venue</th>
              <th>Data types</th>
              <SortHeader k="total_rows" label="Rows" />
              <SortHeader k="last_date" label="Last date" />
              <SortHeader k="lag_days" label="Lag (d)" />
              <SortHeader k="health" label="Health" />
            </tr>
          </thead>
          <tbody>
            {sorted.map((a) => {
              const observed = observabilityByAsset[a.asset_id];
              const latestDate = observedLastDate(a, observed);
              const lagDays = observedLagDays(a, observed);
              const health = observedHealth(a, observed);
              return (
                <tr
                  key={a.asset_id}
                  className={classNames(selectedAssetId === a.asset_id && "selected")}
                  onClick={() => onSelectAsset?.(a)}
                  style={{ cursor: onSelectAsset ? "pointer" : "default" }}
                >
                  <td>
                    <strong>{a.symbol}</strong>
                    <div style={{ fontSize: "0.72rem", color: "var(--muted)" }}>{a.asset_id}</div>
                  </td>
                  <td>{a.asset_class}</td>
                  <td>{a.venue || "—"}</td>
                  <td>
                    <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                      {(a.data_types || []).map((dt) => (
                        <span
                          key={dt}
                          className="pill"
                          style={{ fontSize: "0.68rem", padding: "1px 6px" }}
                        >
                          {dt}
                        </span>
                      ))}
                      {observed?.status === "confirmed" ? (
                        <span
                          className="pill partial"
                          style={{ fontSize: "0.68rem", padding: "1px 6px" }}
                        >
                          observed
                        </span>
                      ) : null}
                      {(!a.data_types || a.data_types.length === 0) && (
                        <span style={{ color: "var(--muted)" }}>—</span>
                      )}
                    </div>
                  </td>
                  <td>{a.total_rows?.toLocaleString() ?? 0}</td>
                  <td>
                    {latestDate || "—"}
                    {observed?.status === "confirmed" &&
                    observed.published_last_date &&
                    observed.published_last_date !== latestDate ? (
                      <div style={{ fontSize: "0.72rem", color: "var(--muted)" }}>
                        published {observed.published_last_date}
                      </div>
                    ) : null}
                  </td>
                  <td
                    style={{
                      color: lagDays > 7 ? "var(--err)" : lagDays > 2 ? "var(--warn)" : undefined,
                    }}
                  >
                    {lagDays != null && lagDays >= 0 ? lagDays : "—"}
                  </td>
                  <td>
                    <HealthBadge health={health} />
                  </td>
                </tr>
              );
            })}
            {sorted.length === 0 && (
              <tr>
                <td colSpan={8} style={{ textAlign: "center", color: "var(--muted)", padding: 24 }}>
                  No assets match the current filter.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
