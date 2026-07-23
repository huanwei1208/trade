import { useEffect, useMemo, useState } from "react";

import { ErrorState } from "./ErrorState";
import { LoadingSkeleton } from "./LoadingSkeleton";
import type { DataAsset, DataGapsPayload } from "../lib/api";
import { getDataGaps } from "../lib/api";

type GapTimelineProps = {
  asset: DataAsset | null;
};

function parseDate(s: string): Date {
  return new Date(s + "T00:00:00Z");
}

export function GapTimeline({ asset }: GapTimelineProps) {
  const [payload, setPayload] = useState<DataGapsPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!asset) {
      setPayload(null);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    getDataGaps(asset.asset_id)
      .then((data) => { if (!cancelled) setPayload(data); })
      .catch((err) => { if (!cancelled) setError(err instanceof Error ? err.message : String(err)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [asset?.asset_id]);

  const segments = useMemo(() => {
    if (!payload || payload.gaps.length === 0 || !asset?.first_date || !asset?.last_date) {
      return [];
    }
    const start = parseDate(asset.first_date);
    const end = parseDate(asset.last_date);
    const total = Math.max(1, (end.getTime() - start.getTime()) / 86_400_000);
    const segs: Array<{ kind: "data" | "gap"; start_pct: number; width_pct: number; label: string; days: number }> = [];
    let cursor = new Date(start);
    // Sort gaps by start date
    const sortedGaps = [...payload.gaps].sort((a, b) => a.start.localeCompare(b.start));
    for (const gap of sortedGaps) {
      const gapStart = parseDate(gap.start);
      const gapEnd = parseDate(gap.end);
      // data segment before this gap
      if (gapStart > cursor) {
        const dataDays = (gapStart.getTime() - cursor.getTime()) / 86_400_000;
        segs.push({
          kind: "data",
          start_pct: ((cursor.getTime() - start.getTime()) / 86_400_000 / total) * 100,
          width_pct: (dataDays / total) * 100,
          label: cursor.toISOString().slice(0, 10) + " → " + gap.start,
          days: dataDays,
        });
      }
      segs.push({
        kind: "gap",
        start_pct: ((gapStart.getTime() - start.getTime()) / 86_400_000 / total) * 100,
        width_pct: Math.max(0.5, (gap.days / total) * 100),
        label: gap.start + " → " + gap.end,
        days: gap.days,
      });
      cursor = new Date(gapEnd.getTime() + 86_400_000);
    }
    // trailing data
    if (cursor <= end) {
      const dataDays = ((end.getTime() - cursor.getTime()) / 86_400_000) + 1;
      segs.push({
        kind: "data",
        start_pct: ((cursor.getTime() - start.getTime()) / 86_400_000 / total) * 100,
        width_pct: (dataDays / total) * 100,
        label: cursor.toISOString().slice(0, 10) + " → " + asset.last_date,
        days: dataDays,
      });
    }
    return segs;
  }, [payload, asset?.first_date, asset?.last_date]);

  if (!asset) {
    return <div style={{ color: "var(--muted)", padding: 24, textAlign: "center" }}>Select an asset to analyze gaps.</div>;
  }

  if (loading && !payload) return <LoadingSkeleton variant="panel" />;
  if (error) return <ErrorState title="Failed to load gap analysis" body={error} />;

  const covPct = payload?.coverage_pct ?? 0;
  const longest = payload?.longest_gap_days ?? 0;
  const gapCount = payload?.gaps.length ?? 0;

  return (
    <div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginBottom: 16 }}>
        <MetricCard label="Asset" value={asset.symbol} sub={asset.asset_id} />
        <MetricCard label="Coverage" value={`${covPct.toFixed(1)}%`} sub={`${payload?.present_dates ?? 0} / ${payload?.expected_dates ?? 0} days`} tone={covPct >= 99 ? "ok" : covPct >= 90 ? "warn" : "err"} />
        <MetricCard label="Gaps" value={String(gapCount)} sub={gapCount === 0 ? "No gaps detected" : `${gapCount} gap(s)`} tone={gapCount === 0 ? "ok" : gapCount <= 3 ? "warn" : "err"} />
        <MetricCard label="Longest gap" value={`${longest}d`} sub={longest === 0 ? "Continuous" : "Consecutive missing days"} tone={longest === 0 ? "ok" : longest <= 3 ? "warn" : "err"} />
      </div>

      {payload && asset.first_date && asset.last_date && (
        <div style={{ marginBottom: 16 }}>
          <div style={{ fontSize: "0.75rem", color: "var(--muted)", marginBottom: 6 }}>
            {asset.first_date} → {asset.last_date}
          </div>
          <div style={{ position: "relative", height: 28, background: "rgba(255,255,255,0.04)", borderRadius: 4, overflow: "hidden", display: "flex" }}>
            {segments.length === 0 && covPct >= 100 && (
              <div style={{ width: "100%", background: "rgba(25,84,48,0.6)" }} title="Complete coverage" />
            )}
            {segments.map((seg, i) => (
              <div
                key={i}
                title={`${seg.kind === "gap" ? "Gap" : "Data"}: ${seg.label} (${seg.days}d)`}
                style={{
                  position: "absolute",
                  left: `${seg.start_pct}%`,
                  width: `${seg.width_pct}%`,
                  top: 0,
                  bottom: 0,
                  background: seg.kind === "gap" ? "rgba(95,21,37,0.85)" : "rgba(25,84,48,0.6)",
                  borderRight: seg.kind === "gap" ? "1px solid rgba(95,21,37,1)" : "none",
                }}
              />
            ))}
          </div>
          <div style={{ display: "flex", gap: 12, marginTop: 6, fontSize: "0.72rem", color: "var(--muted)" }}>
            <span><span style={{ display: "inline-block", width: 10, height: 10, background: "rgba(25,84,48,0.6)", borderRadius: 2, verticalAlign: "middle", marginRight: 4 }} />Data present</span>
            <span><span style={{ display: "inline-block", width: 10, height: 10, background: "rgba(95,21,37,0.85)", borderRadius: 2, verticalAlign: "middle", marginRight: 4 }} />Gap</span>
          </div>
        </div>
      )}

      {(payload?.gaps?.length ?? 0) > 0 && (
        <div className="table-wrap">
          <table className="picks-table">
            <thead>
              <tr>
                <th>#</th>
                <th>Gap start</th>
                <th>Gap end</th>
                <th style={{ textAlign: "right" }}>Days missing</th>
              </tr>
            </thead>
            <tbody>
              {[...(payload?.gaps || [])].sort((a, b) => b.days - a.days).map((g, i) => (
                <tr key={i}>
                  <td>{i + 1}</td>
                  <td>{g.start}</td>
                  <td>{g.end}</td>
                  <td style={{ textAlign: "right", color: g.days > 7 ? "var(--err)" : g.days > 2 ? "var(--warn)" : undefined, fontWeight: 600 }}>{g.days}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {payload && gapCount === 0 && (
        <div style={{ padding: 16, textAlign: "center", color: "var(--ok)", background: "rgba(25,84,48,0.1)", borderRadius: 6 }}>
          No gaps detected — coverage is continuous across the date range.
        </div>
      )}
    </div>
  );
}

function MetricCard({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: "ok" | "warn" | "err" }) {
  const colors: Record<string, string> = {
    ok: "var(--ok)",
    warn: "var(--warn)",
    err: "var(--err)",
  };
  return (
    <div style={{ padding: 12, background: "rgba(255,255,255,0.03)", borderRadius: 6, border: "1px solid var(--line)" }}>
      <div style={{ fontSize: "0.7rem", color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>{label}</div>
      <div style={{ fontSize: "1.3rem", fontWeight: 700, color: tone ? colors[tone] : undefined, marginTop: 4 }}>{value}</div>
      {sub && <div style={{ fontSize: "0.72rem", color: "var(--muted)", marginTop: 2 }}>{sub}</div>}
    </div>
  );
}
