import { useEffect, useMemo, useState } from "react";

import { ErrorState } from "./ErrorState";
import { LoadingSkeleton } from "./LoadingSkeleton";
import type { DataNewsPayload, NewsArticle } from "../lib/api";
import { getDataNews } from "../lib/api";
import { formatDateTime } from "../lib/format";

type NewsFeedProps = {
  // If provided, pre-filter to this source
  initialSource?: string;
};

function SentimentDot({ score }: { score: number | null }) {
  if (score === null || score === undefined) {
    return <span style={{ display: "inline-block", width: 8, height: 8, borderRadius: "50%", background: "#555", verticalAlign: "middle", marginRight: 6 }} title="No sentiment" />;
  }
  let color = "#888";
  let label = "neutral";
  if (score > 0.3) { color = "var(--ok)"; label = "positive"; }
  else if (score > 0.05) { color = "#6b8a3a"; label = "slightly positive"; }
  else if (score < -0.3) { color = "var(--err)"; label = "negative"; }
  else if (score < -0.05) { color = "#8a5a3a"; label = "slightly negative"; }
  return (
    <span
      style={{ display: "inline-block", width: 8, height: 8, borderRadius: "50%", background: color, verticalAlign: "middle", marginRight: 6 }}
      title={`${label} (${score.toFixed(2)})`}
    />
  );
}

export function NewsFeed({ initialSource = "" }: NewsFeedProps) {
  const [source, setSource] = useState(initialSource);
  const [days, setDays] = useState(3);
  const [limit, setLimit] = useState(30);
  const [payload, setPayload] = useState<DataNewsPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getDataNews(source, days, limit)
      .then((data) => { if (!cancelled) setPayload(data); })
      .catch((err) => { if (!cancelled) setError(err instanceof Error ? err.message : String(err)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [source, days, limit]);

  // Collect unique sources for filter
  const sources = useMemo(() => {
    const set = new Set<string>();
    for (const a of payload?.articles || []) {
      if (a.source) set.add(a.source);
    }
    return Array.from(set).sort();
  }, [payload]);

  const articles = payload?.articles || [];

  return (
    <div>
      <div className="filter-bar" style={{ marginBottom: 12, flexWrap: "wrap" }}>
        <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ fontSize: "0.8rem", color: "var(--muted)" }}>Source:</span>
          <select value={source} onChange={(e) => setSource(e.target.value)}>
            <option value="">All sources</option>
            {sources.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </label>
        <div style={{ display: "flex", gap: 4 }}>
          {[1, 3, 7, 14].map((d) => (
            <button key={d} type="button" className={days === d ? "is-active" : ""} onClick={() => setDays(d)}>{d}d</button>
          ))}
        </div>
        <div style={{ display: "flex", gap: 4 }}>
          {[10, 30, 50].map((l) => (
            <button key={l} type="button" className={limit === l ? "is-active" : ""} onClick={() => setLimit(l)}>{l}</button>
          ))}
        </div>
        <span style={{ color: "var(--muted)", fontSize: "0.8rem", marginLeft: "auto" }}>
          {articles.length} / {payload?.total ?? 0} articles
        </span>
      </div>

      {loading && !payload ? (
        <LoadingSkeleton variant="panel" />
      ) : error ? (
        <ErrorState title="Failed to load news" body={error} />
      ) : articles.length === 0 ? (
        <div style={{ padding: 32, textAlign: "center", color: "var(--muted)" }}>
          No news articles found for the current filters. News parquet files may not exist yet under <code>data/news/</code>.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {articles.map((a: NewsArticle, i: number) => (
            <article key={i} style={{ padding: 14, background: "rgba(255,255,255,0.03)", border: "1px solid var(--line)", borderRadius: 6 }}>
              <div style={{ display: "flex", alignItems: "flex-start", gap: 10, marginBottom: 6 }}>
                <SentimentDot score={a.sentiment_score} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  {a.url ? (
                    <a href={a.url} target="_blank" rel="noopener noreferrer" style={{ color: "var(--text)", textDecoration: "none", fontWeight: 600, fontSize: "0.95rem" }}>
                      {a.title || "(untitled)"}
                    </a>
                  ) : (
                    <div style={{ fontWeight: 600, fontSize: "0.95rem" }}>{a.title || "(untitled)"}</div>
                  )}
                </div>
              </div>
              {a.summary && (
                <div style={{ fontSize: "0.82rem", color: "var(--muted)", lineHeight: 1.5, marginBottom: 8 }}>
                  {a.summary}
                </div>
              )}
              <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: "0.72rem", color: "var(--muted)" }}>
                {a.source && <span className="pill" style={{ fontSize: "0.68rem", padding: "1px 7px" }}>{a.source}</span>}
                {a.published_at && <span>{formatDateTime(a.published_at, "en-US")}</span>}
                {a.sentiment_score !== null && a.sentiment_score !== undefined && (
                  <span style={{ color: a.sentiment_score > 0.1 ? "var(--ok)" : a.sentiment_score < -0.1 ? "var(--err)" : "var(--muted)" }}>
                    sentiment: {a.sentiment_score.toFixed(2)}
                  </span>
                )}
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
