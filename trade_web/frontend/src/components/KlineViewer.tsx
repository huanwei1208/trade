import { useEffect, useState } from "react";

import { ErrorState } from "./ErrorState";
import { LoadingSkeleton } from "./LoadingSkeleton";
import type { DataAsset, DataKlinePayload } from "../lib/api";
import { getDataKlineForAsset } from "../lib/api";
import { formatCompactNumber } from "../lib/format";

type KlineViewerProps = {
  asset: DataAsset | null;
};

function fmt(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return n.toLocaleString(undefined, { maximumFractionDigits: 4 });
}

function dayColor(open: number | null | undefined, close: number | null | undefined): string {
  if (open === null || open === undefined || close === null || close === undefined) return "";
  if (close > open) return "var(--ok)";
  if (close < open) return "var(--err)";
  return "";
}

function sourceStatus(
  payload: DataKlinePayload | null,
  asset: DataAsset,
): DataKlinePayload["source"] {
  return (
    payload?.source ?? {
      channel: "published",
      label: "Published data",
      last_date: asset.last_date,
      published_last_date: asset.last_date,
    }
  );
}

function sourceTone(source: DataKlinePayload["source"]): string {
  if (source?.channel === "observed") {
    return source.quality_state === "degraded" || source.lifecycle_state === "staged"
      ? "partial"
      : "ok";
  }
  return "ok";
}

function Sparkline({ rows }: { rows: Array<{ close: number | null }> }) {
  const valid = rows
    .map((r) => r.close)
    .filter((v): v is number => v !== null && v !== undefined && !Number.isNaN(v));
  if (valid.length < 2)
    return <span style={{ color: "var(--muted)", fontSize: "0.75rem" }}>No sparkline</span>;
  const min = Math.min(...valid);
  const max = Math.max(...valid);
  const range = max - min || 1;
  const w = 120;
  const h = 32;
  const points = valid
    .map((v, i) => {
      const x = (i / (valid.length - 1)) * w;
      const y = h - ((v - min) / range) * h;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const lastClose = valid[valid.length - 1];
  const firstClose = valid[0];
  const stroke = lastClose >= firstClose ? "var(--ok)" : "var(--err)";
  return (
    <svg width={w} height={h} style={{ display: "block" }}>
      <polyline fill="none" stroke={stroke} strokeWidth="1.5" points={points} />
    </svg>
  );
}

export function KlineViewer({ asset }: KlineViewerProps) {
  const [days, setDays] = useState(30);
  const [payload, setPayload] = useState<DataKlinePayload | null>(null);
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
    getDataKlineForAsset(asset.asset_id, days)
      .then((data) => {
        if (!cancelled) {
          setPayload(data);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [asset?.asset_id, days]);

  if (!asset) {
    return (
      <div style={{ color: "var(--muted)", padding: 24, textAlign: "center" }}>
        Select an asset from the Assets tab to view kline data.
      </div>
    );
  }

  const rows = payload?.rows || [];
  const reversed = [...rows].reverse();
  const source = sourceStatus(payload, asset);

  return (
    <div>
      <div className="filter-bar" style={{ marginBottom: 12 }}>
        <span style={{ fontWeight: 600 }}>{payload?.symbol || asset.symbol}</span>
        <span style={{ color: "var(--muted)", fontSize: "0.8rem" }}>
          {asset.asset_id} · {payload?.interval || "1d"}
        </span>
        <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
          {[14, 30, 60, 90, 180].map((d) => (
            <button
              key={d}
              type="button"
              className={days === d ? "is-active" : ""}
              onClick={() => setDays(d)}
            >
              {d}d
            </button>
          ))}
        </div>
      </div>

      {loading && !payload ? (
        <LoadingSkeleton variant="panel" />
      ) : error ? (
        <ErrorState
          title="Failed to load kline"
          body={error}
          action={
            <button
              type="button"
              className="button button--primary"
              onClick={() => setDays((d) => d)}
            >
              Retry
            </button>
          }
        />
      ) : (
        <>
          <div
            data-testid="data-kline-source"
            style={{
              alignItems: "center",
              background: "rgba(12, 24, 44, 0.55)",
              border: "1px solid var(--line)",
              borderRadius: 6,
              color: "var(--muted)",
              display: "flex",
              flexWrap: "wrap",
              fontSize: "0.78rem",
              gap: 8,
              marginBottom: 10,
              padding: "6px 10px",
            }}
          >
            <span className={`pill ${sourceTone(source)}`}>{source?.label}</span>
            <span>
              Latest {source?.last_date || "—"}
              {source?.published_last_date && source.published_last_date !== source.last_date
                ? ` · published ${source.published_last_date}`
                : ""}
            </span>
            {source?.lifecycle_state || source?.quality_state ? (
              <span>
                {source.lifecycle_state || "unknown"} / {source.quality_state || "unknown"}
              </span>
            ) : null}
            {source?.run_id ? (
              <code style={{ color: "var(--text-2)" }}>{source.run_id.slice(0, 12)}</code>
            ) : null}
          </div>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 16,
              marginBottom: 12,
              padding: "8px 12px",
              background: "rgba(42,157,255,0.05)",
              borderRadius: 6,
            }}
          >
            <div>
              <div
                style={{ fontSize: "0.72rem", color: "var(--muted)", textTransform: "uppercase" }}
              >
                Rows
              </div>
              <div style={{ fontWeight: 600 }}>{rows.length}</div>
            </div>
            <div>
              <div
                style={{ fontSize: "0.72rem", color: "var(--muted)", textTransform: "uppercase" }}
              >
                Range
              </div>
              <div style={{ fontWeight: 600 }}>
                {rows[0]?.date || "—"} → {rows[rows.length - 1]?.date || "—"}
              </div>
            </div>
            <div>
              <div
                style={{ fontSize: "0.72rem", color: "var(--muted)", textTransform: "uppercase" }}
              >
                Trend ({days}d)
              </div>
              <Sparkline rows={rows} />
            </div>
          </div>
          <div className="table-wrap">
            <table className="picks-table">
              <thead>
                <tr>
                  <th>Date</th>
                  <th style={{ textAlign: "right" }}>Open</th>
                  <th style={{ textAlign: "right" }}>High</th>
                  <th style={{ textAlign: "right" }}>Low</th>
                  <th style={{ textAlign: "right" }}>Close</th>
                  <th style={{ textAlign: "right" }}>Volume</th>
                  <th style={{ textAlign: "right" }}>Change</th>
                </tr>
              </thead>
              <tbody>
                {reversed.map((r, i) => {
                  const prev = reversed[i + 1];
                  const chg =
                    r.close !== null && r.close !== undefined && prev?.close
                      ? ((r.close - prev.close) / prev.close) * 100
                      : null;
                  const color = dayColor(r.open, r.close);
                  return (
                    <tr key={r.date}>
                      <td>{r.date}</td>
                      <td style={{ textAlign: "right" }}>{fmt(r.open)}</td>
                      <td style={{ textAlign: "right" }}>{fmt(r.high)}</td>
                      <td style={{ textAlign: "right" }}>{fmt(r.low)}</td>
                      <td
                        style={{ textAlign: "right", color: color || undefined, fontWeight: 600 }}
                      >
                        {fmt(r.close)}
                      </td>
                      <td style={{ textAlign: "right" }}>{formatCompactNumber(r.volume)}</td>
                      <td
                        style={{
                          textAlign: "right",
                          color: chg === null ? undefined : chg >= 0 ? "var(--ok)" : "var(--err)",
                        }}
                      >
                        {chg === null ? "—" : `${chg >= 0 ? "+" : ""}${chg.toFixed(2)}%`}
                      </td>
                    </tr>
                  );
                })}
                {rows.length === 0 && (
                  <tr>
                    <td
                      colSpan={7}
                      style={{ textAlign: "center", color: "var(--muted)", padding: 24 }}
                    >
                      No kline data for this asset. The parquet file may not exist yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
