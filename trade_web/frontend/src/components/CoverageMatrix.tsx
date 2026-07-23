import { useEffect, useState } from "react";

import { ErrorState } from "./ErrorState";
import { LoadingSkeleton } from "./LoadingSkeleton";
import type { CoverageAssetClass, CoverageCell, DataCoveragePayload } from "../lib/api";
import { getDataCoverage } from "../lib/api";

function cellBg(pct: number): string {
  if (pct >= 100) return "rgba(25,84,48,0.85)";
  if (pct >= 90) return "rgba(25,84,48,0.55)";
  if (pct >= 75) return "rgba(103,79,20,0.7)";
  if (pct >= 50) return "rgba(103,79,20,0.5)";
  if (pct > 0) return "rgba(95,21,37,0.6)";
  return "rgba(95,21,37,0.9)";
}

function cellTone(pct: number): string {
  if (pct >= 90) return "var(--ok)";
  if (pct >= 50) return "var(--warn)";
  return "var(--err)";
}

const DATA_TYPE_LABELS: Record<string, string> = {
  kline: "Kline",
  sentiment: "Sentiment",
  news: "News",
};

export function CoverageMatrix() {
  const [payload, setPayload] = useState<DataCoveragePayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getDataCoverage()
      .then((data) => { if (!cancelled) setPayload(data); })
      .catch((err) => { if (!cancelled) setError(err instanceof Error ? err.message : String(err)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  if (loading && !payload) return <LoadingSkeleton variant="panel" />;
  if (error) return <ErrorState title="Failed to load coverage matrix" body={error} />;

  const classes = payload?.asset_classes || [];
  const dataTypes = ["kline", "sentiment", "news"];

  return (
    <div>
      <div style={{ marginBottom: 12, fontSize: "0.8rem", color: "var(--muted)" }}>
        Coverage shows the fraction of assets within each class that have usable data for each data type.
      </div>

      {/* Summary cards */}
      <div style={{ display: "flex", gap: 12, marginBottom: 16, flexWrap: "wrap" }}>
        {classes.map((cls: CoverageAssetClass) => {
          const avg = Object.values(cls.data_types || {}).reduce((s: number, c: CoverageCell) => s + (c.pct || 0), 0) / Math.max(1, Object.keys(cls.data_types || {}).length);
          return (
            <div key={cls.name} style={{ padding: 12, background: "rgba(255,255,255,0.03)", borderRadius: 6, border: "1px solid var(--line)", minWidth: 140 }}>
              <div style={{ fontSize: "0.7rem", color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>{cls.name}</div>
              <div style={{ fontSize: "1.1rem", fontWeight: 700, color: cellTone(avg), marginTop: 4 }}>{avg.toFixed(0)}%</div>
              <div style={{ fontSize: "0.72rem", color: "var(--muted)" }}>{cls.total_assets} asset{cls.total_assets !== 1 ? "s" : ""}</div>
            </div>
          );
        })}
      </div>

      {/* Matrix grid */}
      <div className="table-wrap">
        <table className="picks-table" style={{ borderCollapse: "separate", borderSpacing: "3px" }}>
          <thead>
            <tr>
              <th style={{ background: "transparent", border: "none", padding: "6px 8px" }}>Asset class</th>
              <th style={{ background: "transparent", border: "none", padding: "6px 8px", textAlign: "center" }}>Assets</th>
              {dataTypes.map((dt) => (
                <th key={dt} style={{ background: "transparent", border: "none", padding: "6px 8px", textAlign: "center" }}>{DATA_TYPE_LABELS[dt] || dt}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {classes.map((cls: CoverageAssetClass) => (
              <tr key={cls.name}>
                <td style={{ background: "rgba(255,255,255,0.03)", border: "none", borderRadius: 4, fontWeight: 600 }}>{cls.name}</td>
                <td style={{ background: "rgba(255,255,255,0.03)", border: "none", borderRadius: 4, textAlign: "center" }}>{cls.total_assets}</td>
                {dataTypes.map((dt) => {
                  const cell = (cls.data_types || {})[dt];
                  const pct = cell?.pct ?? 0;
                  const present = cell?.present ?? 0;
                  const total = cell?.total ?? 0;
                  return (
                    <td key={dt} style={{ background: cellBg(pct), border: "none", borderRadius: 4, textAlign: "center", padding: "10px 8px", color: pct >= 50 ? "#fff" : "rgba(255,255,255,0.85)" }}>
                      <div style={{ fontWeight: 700, fontSize: "1rem" }}>{pct.toFixed(0)}%</div>
                      <div style={{ fontSize: "0.7rem", opacity: 0.85 }}>{present}/{total}</div>
                    </td>
                  );
                })}
              </tr>
            ))}
            {classes.length === 0 && (
              <tr><td colSpan={5} style={{ textAlign: "center", color: "var(--muted)", padding: 24 }}>No asset coverage data available.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Legend */}
      <div style={{ display: "flex", gap: 12, marginTop: 12, fontSize: "0.72rem", color: "var(--muted)", flexWrap: "wrap" }}>
        <span><span style={{ display: "inline-block", width: 12, height: 12, background: cellBg(100), borderRadius: 2, verticalAlign: "middle", marginRight: 4 }} />≥90%</span>
        <span><span style={{ display: "inline-block", width: 12, height: 12, background: cellBg(80), borderRadius: 2, verticalAlign: "middle", marginRight: 4 }} />75–89%</span>
        <span><span style={{ display: "inline-block", width: 12, height: 12, background: cellBg(60), borderRadius: 2, verticalAlign: "middle", marginRight: 4 }} />50–74%</span>
        <span><span style={{ display: "inline-block", width: 12, height: 12, background: cellBg(25), borderRadius: 2, verticalAlign: "middle", marginRight: 4 }} />&lt;50%</span>
        <span><span style={{ display: "inline-block", width: 12, height: 12, background: cellBg(0), borderRadius: 2, verticalAlign: "middle", marginRight: 4 }} />0%</span>
      </div>
    </div>
  );
}
