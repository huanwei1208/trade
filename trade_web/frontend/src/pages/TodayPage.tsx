import { CollapseSection } from "../components/CollapseSection";
import { DecisionHero } from "../components/DecisionHero";
import { ErrorState } from "../components/ErrorState";
import { LoadingSkeleton } from "../components/LoadingSkeleton";
import { MetricCard } from "../components/MetricCard";
import { PanelCard } from "../components/PanelCard";
import { RetryInline } from "../components/RetryInline";
import { SectionHeader } from "../components/SectionHeader";
import { ActionChip } from "../components/ActionChip";
import { StatusPill } from "../components/StatusPill";
import { TrustBadge } from "../components/TrustBadge";
import type { CandidateRow, EventsPagePayload, TodayPageData } from "../lib/api";
import { useApiResource } from "../lib/api";
import { formatDateTime, labelizeDataset, shortText } from "../lib/format";
import { getTodayCall, isActionable } from "../lib/ui";

type TodayPageProps = {
  refreshToken: number;
  onOpenSymbol: (symbol: string) => void;
};

export function TodayPage({ refreshToken, onOpenSymbol }: TodayPageProps) {
  const todayResource = useApiResource<TodayPageData>("/api/today-page", {
    deps: [refreshToken],
    cacheKey: "trade-web:today-page",
  });
  const eventsResource = useApiResource<EventsPagePayload>("/api/events-page", {
    deps: [refreshToken],
    cacheKey: "trade-web:events-page",
  });

  const todayCall = getTodayCall(todayResource.data);
  const actions = todayResource.data?.top_actions || [];
  const actionable = actions.filter((item) => isActionable(item.action) && String(item.action || "").toUpperCase() !== "WATCH");

  const canRenderCards = actionable.length > 0 && !todayResource.data?.global_blocked;

  if (todayResource.loading && !todayResource.data) {
    return <LoadingSkeleton variant="hero" />;
  }

  if (todayResource.error && !todayResource.data) {
    return (
      <ErrorState
        title="Today's workspace is unavailable"
        body="The decision snapshot could not be loaded. Retry the request or verify backend availability."
        detail={todayResource.error.message}
        action={
          <button type="button" className="button button--primary" onClick={todayResource.retry}>
            Retry
          </button>
        }
      />
    );
  }

  const today = todayResource.data;
  if (!today) {
    return null;
  }

  return (
    <div className="page-stack page-today">
      <DecisionHero today={today} todayCall={todayCall} />

      {todayResource.error && todayResource.data && (
        <RetryInline message="Showing the last successful Today snapshot while a fresh fetch failed." onRetry={todayResource.retry} />
      )}

      <section className="page-section">
        <SectionHeader
          title="Top setups"
          subtitle={canRenderCards ? "Small set of names worth immediate review." : "The system is constrained, so action cards are intentionally suppressed."}
        />

        {canRenderCards ? (
          <div className="card-grid card-grid--actions">
            {actions.slice(0, 6).map((item) => (
              <ActionCard key={item.symbol || Math.random()} candidate={item} onOpenSymbol={onOpenSymbol} />
            ))}
          </div>
        ) : (
          <PanelCard title="Decision blockers" accent="red" className="today-blocker-card">
            <div className="today-blocker-card__copy">
              The workspace is keeping action output conservative because trust or freshness blockers affect decision quality.
            </div>
            <div className="today-blocker-card__list">
              {(today.blocker_details || []).map((item) => (
                <div className="today-blocker-card__item" key={`${item.dataset}-${item.status}`}>
                  <div>{labelizeDataset(item.dataset)}</div>
                  <StatusPill label={`${item.status || "unknown"}${item.lag_days !== null && item.lag_days !== undefined ? ` · ${item.lag_days}d` : ""}`} tone="warn" subtle />
                </div>
              ))}
            </div>
            <div className="tag-cluster">
              {(today.safe_to_view || []).map((item) => (
                <span className="tag-chip" key={item}>
                  {item}
                </span>
              ))}
            </div>
          </PanelCard>
        )}
      </section>

      <section className="page-section">
        <SectionHeader title="Diagnostic context" subtitle="Important, but visually secondary to the decision path." />
        <div className="subtle-grid">
          <CollapseSection title="Trust and data freshness" initialOpen>
            <div className="metric-grid">
              <MetricCard label="Trust scalar" value={<TrustBadge score={today.trust_gate?.trust_scalar} />} hint={today.trust_gate?.eval_date || "No eval date"} />
              <MetricCard label="Operational gate" value={today.trust_gate?.operational_status || "unknown"} />
              <MetricCard label="Research gate" value={today.trust_gate?.research_status || "unknown"} />
              <MetricCard label="Pipeline health" value={today.pipeline_health?.status || "unknown"} hint={`${today.pipeline_health?.ok || 0} ok · ${today.pipeline_health?.error || 0} error`} />
            </div>
            <div className="diagnostic-list">
              {(today.trust_gate?.freshness || []).map((item) => (
                <div className="diagnostic-list__row" key={`${item.dataset}-${item.status}`}>
                  <span>{labelizeDataset(item.dataset)}</span>
                  <span>{item.lag_days !== undefined && item.lag_days !== null ? `${item.lag_days}d lag` : "No lag info"}</span>
                  <StatusPill label={item.status || "unknown"} tone={String(item.status) === "ok" ? "ok" : "warn"} subtle />
                </div>
              ))}
            </div>
          </CollapseSection>

          <CollapseSection title="Blockers and recovery path">
            <div className="diagnostic-callout">{(today.blockers || []).join(" · ") || "No explicit blockers surfaced."}</div>
            <div className="diagnostic-copy">{today.recovery_condition || "Wait for stronger confirmation."}</div>
          </CollapseSection>
        </div>
      </section>

      <section className="page-section">
        <SectionHeader title="Recent activity" subtitle="Runs, failures, and recent event context in compact form." />
        <div className="compact-grid">
          <PanelCard title="Recent runs" subdued>
            <div className="list-stack">
              {(today.recent_runs || []).length === 0 && <div className="note-card">No recent runs.</div>}
              {(today.recent_runs || []).slice(0, 5).map((run) => (
                <div className="compact-row" key={`${run.job_name}-${run.started_at}`}>
                  <div>
                    <div className="compact-row__title">{run.job_name || "Unknown run"}</div>
                    <div className="compact-row__subtitle">{shortText(run.result_summary, 80) || "No summary"}</div>
                  </div>
                  <div className="compact-row__meta">
                    <StatusPill label={run.status || "unknown"} tone={String(run.status) === "ok" ? "ok" : String(run.status) === "error" ? "err" : "info"} subtle />
                    <span>{formatDateTime(run.started_at)}</span>
                  </div>
                </div>
              ))}
            </div>
          </PanelCard>

          <PanelCard title="Failed nodes" subdued>
            <div className="list-stack">
              {(eventsResource.data?.failed_nodes || today.error_nodes || []).slice(0, 5).map((node) => {
                const nodeRecord = node as Record<string, unknown>;
                const key = String(nodeRecord.job_name || nodeRecord.id || "node");
                const detail = String(nodeRecord.error_detail || nodeRecord.result_summary || "No detail");
                const status = String(nodeRecord.status || "error");
                return (
                <div className="compact-row" key={key}>
                  <div>
                    <div className="compact-row__title">{String(nodeRecord.job_name || nodeRecord.id || "Unknown node")}</div>
                    <div className="compact-row__subtitle">{shortText(detail, 80)}</div>
                  </div>
                  <StatusPill label={status} tone="err" subtle />
                </div>
                );
              })}
              {(!eventsResource.data?.failed_nodes || eventsResource.data.failed_nodes.length === 0) && (!today.error_nodes || today.error_nodes.length === 0) && <div className="note-card">No active node failures.</div>}
            </div>
          </PanelCard>

          <PanelCard title="Noteworthy events" subdued>
            <div className="list-stack">
              {(eventsResource.data?.today_events || eventsResource.data?.recent_market_events || []).slice(0, 5).map((item, index) => (
                <div className="compact-row" key={`${item.title || item.event_type || index}`}>
                  <div>
                    <div className="compact-row__title">{String(item.title || item.event_type || item.symbol || "Market event")}</div>
                    <div className="compact-row__subtitle">{shortText(String(item.summary || item.description || item.symbol || ""), 80) || "No summary"}</div>
                  </div>
                  <span>{String(item.event_date || item.created_at || "—")}</span>
                </div>
              ))}
              {eventsResource.loading && !eventsResource.data && <LoadingSkeleton variant="panel" />}
            </div>
          </PanelCard>
        </div>
      </section>
    </div>
  );
}

function ActionCard({ candidate, onOpenSymbol }: { candidate: CandidateRow; onOpenSymbol: (symbol: string) => void }) {
  return (
    <PanelCard accent={String(candidate.action || "").toUpperCase() === "ADD" ? "green" : String(candidate.action || "").toUpperCase() === "PROBE" ? "cyan" : "amber"} className="action-card">
      <div className="action-card__head">
        <div>
          <div className="action-card__symbol">
            {candidate.symbol}
            <span>{candidate.name || ""}</span>
          </div>
          <div className="action-card__summary">{shortText(candidate.world_state_summary || candidate.thesis, 120)}</div>
        </div>
        <div className="action-card__meta">
          <ActionChip action={candidate.action} />
          <TrustBadge score={candidate.trust_score} level={candidate.trust_level} />
        </div>
      </div>
      <div className="action-card__footer">
        <div className="action-card__invalidator">{shortText((candidate.top_invalidators || []).join(" · "), 90) || "No invalidator surfaced."}</div>
        <button type="button" className="button button--ghost" onClick={() => candidate.symbol && onOpenSymbol(candidate.symbol)}>
          Open workspace
        </button>
      </div>
    </PanelCard>
  );
}
