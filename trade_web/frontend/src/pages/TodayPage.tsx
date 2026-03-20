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
import { formatDateTime, shortText } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { getDatasetText, getGateStatusText } from "../lib/statusText";
import { getTodayCall, isActionable } from "../lib/ui";

type TodayPageProps = {
  refreshToken: number;
  onOpenSymbol: (symbol: string) => void;
  onOpenOpsFocus: (focus: { tab: "readiness" | "recovery"; date?: string; dataset?: string }) => void;
};

export function TodayPage({ refreshToken, onOpenSymbol, onOpenOpsFocus }: TodayPageProps) {
  const { locale, t } = useI18n();
  const todayResource = useApiResource<TodayPageData>("/api/today-page", {
    deps: [refreshToken],
    cacheKey: "trade-web:today-page",
  });
  const eventsResource = useApiResource<EventsPagePayload>("/api/events-page", {
    deps: [refreshToken],
    cacheKey: "trade-web:events-page",
  });

  const todayCall = getTodayCall(todayResource.data, locale);
  const actions = todayResource.data?.top_actions || [];
  const actionable = actions.filter((item) => isActionable(item.action) && String(item.action || "").toUpperCase() !== "WATCH");

  const canRenderCards = actionable.length > 0 && !todayResource.data?.global_blocked;

  if (todayResource.loading && !todayResource.data) {
    return <LoadingSkeleton variant="hero" />;
  }

  if (todayResource.error && !todayResource.data) {
    return (
        <ErrorState
          title={t("today.unavailable")}
          body={t("today.unavailableCopy")}
          detail={todayResource.error.message}
          action={
            <button type="button" className="button button--primary" onClick={todayResource.retry}>
              {t("common.retry")}
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
      <DecisionHero
        today={today}
        todayCall={todayCall}
        onOpenReadiness={() => onOpenOpsFocus({
          tab: "readiness",
          date: today.as_of,
          dataset: today.blocker_details?.[0]?.dataset || "signals",
        })}
      />

      {todayResource.error && todayResource.data && (
        <RetryInline message={t("today.showingStale")} onRetry={todayResource.retry} />
      )}

      <section className="page-section">
        <SectionHeader
          title={t("today.topSetups")}
          subtitle={canRenderCards ? t("today.topSetupsActionable") : t("today.topSetupsConstrained")}
        />

        {canRenderCards ? (
          <div className="card-grid card-grid--actions">
            {actions.slice(0, 6).map((item) => (
              <ActionCard key={item.symbol || Math.random()} candidate={item} onOpenSymbol={onOpenSymbol} />
            ))}
          </div>
        ) : (
          <PanelCard title={t("today.blockers")} accent="red" className="today-blocker-card">
            <div className="today-blocker-card__copy">{t("today.blockersCopy")}</div>
            <div className="today-blocker-card__list">
              {(today.blocker_details || []).map((item) => (
                <div className="today-blocker-card__item" key={`${item.dataset}-${item.status}`}>
                  <div>{getDatasetText(locale, item.dataset)}</div>
                  <StatusPill
                    label={`${getGateStatusText(locale, item.status).label}${item.lag_days !== null && item.lag_days !== undefined ? ` · ${item.lag_days}d` : ""}`}
                    tone={getGateStatusText(locale, item.status).tone}
                    subtle
                  />
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
            <button
              type="button"
              className="button button--ghost"
              onClick={() => onOpenOpsFocus({
                tab: "readiness",
                date: today.as_of,
                dataset: today.blocker_details?.[0]?.dataset || "signals",
              })}
            >
              {t("common.openReadiness")}
            </button>
          </PanelCard>
        )}
      </section>

      <section className="page-section">
        <SectionHeader title={t("today.diagnostics")} subtitle={t("today.diagnosticsSubtitle")} />
        <div className="subtle-grid">
          <CollapseSection title={t("today.trustAndFreshness")} initialOpen>
            <div className="metric-grid">
              <MetricCard label={t("today.trustScalar")} value={<TrustBadge score={today.trust_gate?.trust_scalar} />} hint={today.trust_gate?.eval_date || t("common.notAvailable")} />
              <MetricCard label={t("today.conclusionMode")} value={getGateStatusText(locale, today.trust_gate?.operational_status).label} hint={getGateStatusText(locale, today.trust_gate?.operational_status).description} />
              <MetricCard label={t("today.whyConstrained")} value={getGateStatusText(locale, today.trust_gate?.research_status).label} hint={getGateStatusText(locale, today.trust_gate?.research_status).description} />
              <MetricCard label={t("ops.tabs.pipeline")} value={getGateStatusText(locale, today.pipeline_health?.status).label} hint={`${today.pipeline_health?.ok || 0} ${t("status.healthy")} · ${today.pipeline_health?.error || 0} ${t("status.error")}`} />
            </div>
            <div className="diagnostic-list">
              {(today.trust_gate?.freshness || []).map((item) => (
                <div className="diagnostic-list__row" key={`${item.dataset}-${item.status}`}>
                  <span>{getDatasetText(locale, item.dataset)}</span>
                  <span>{item.lag_days !== undefined && item.lag_days !== null ? `${item.lag_days}d lag` : t("today.noLagInfo")}</span>
                  <StatusPill label={getGateStatusText(locale, item.status).label} tone={getGateStatusText(locale, item.status).tone} subtle />
                </div>
              ))}
            </div>
          </CollapseSection>

          <CollapseSection title={t("today.blockersRecovery")}>
            <div className="diagnostic-callout">{(today.blockers || []).join(" · ") || t("today.noExplicitBlocker")}</div>
            <div className="diagnostic-copy">{today.recovery_condition || t("status.recoveryPathDefault")}</div>
          </CollapseSection>
        </div>
      </section>

      <section className="page-section">
        <SectionHeader title={t("today.recentActivity")} subtitle={t("today.recentActivitySubtitle")} />
        <div className="compact-grid">
          <PanelCard title={t("today.recentRuns")} subdued>
            <div className="list-stack">
              {(today.recent_runs || []).length === 0 && <div className="note-card">{t("today.noRecentRuns")}</div>}
              {(today.recent_runs || []).slice(0, 5).map((run) => (
                <div className="compact-row" key={`${run.job_name}-${run.started_at}`}>
                  <div>
                    <div className="compact-row__title">{run.job_name || t("common.unknown")}</div>
                    <div className="compact-row__subtitle">{shortText(run.result_summary, 80) || t("common.noSummary")}</div>
                  </div>
                  <div className="compact-row__meta">
                    <StatusPill label={getGateStatusText(locale, run.status).label} tone={getGateStatusText(locale, run.status).tone} subtle />
                    <span>{formatDateTime(run.started_at, locale === "zh-CN" ? "zh-CN" : "en-US")}</span>
                  </div>
                </div>
              ))}
            </div>
          </PanelCard>

          <PanelCard title={t("today.failedNodes")} subdued>
            <div className="list-stack">
              {(eventsResource.data?.failed_nodes || today.error_nodes || []).slice(0, 5).map((node) => {
                const nodeRecord = node as Record<string, unknown>;
                const key = String(nodeRecord.job_name || nodeRecord.id || "node");
                const detail = String(nodeRecord.error_detail || nodeRecord.result_summary || t("common.noDetail"));
                const status = String(nodeRecord.status || "error");
                return (
                <div className="compact-row" key={key}>
                  <div>
                    <div className="compact-row__title">{String(nodeRecord.job_name || nodeRecord.id || t("common.unknown"))}</div>
                    <div className="compact-row__subtitle">{shortText(detail, 80)}</div>
                  </div>
                  <StatusPill label={getGateStatusText(locale, status).label} tone="err" subtle />
                </div>
                );
              })}
              {(!eventsResource.data?.failed_nodes || eventsResource.data.failed_nodes.length === 0) && (!today.error_nodes || today.error_nodes.length === 0) && <div className="note-card">{t("today.noFailures")}</div>}
            </div>
          </PanelCard>

          <PanelCard title={t("today.noteworthyEvents")} subdued>
            <div className="list-stack">
              {(eventsResource.data?.today_events || eventsResource.data?.recent_market_events || []).slice(0, 5).map((item, index) => (
                <div className="compact-row" key={`${item.title || item.event_type || index}`}>
                  <div>
                    <div className="compact-row__title">{String(item.title || item.event_type || item.symbol || t("common.marketEvent"))}</div>
                    <div className="compact-row__subtitle">{shortText(String(item.summary || item.description || item.symbol || ""), 80) || t("common.noSummary")}</div>
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
  const { t } = useI18n();
  return (
    <PanelCard accent={String(candidate.action || "").toUpperCase() === "ADD" ? "green" : String(candidate.action || "").toUpperCase() === "PROBE" ? "cyan" : "amber"} className="action-card">
      <div className="action-card__head">
        <div>
          <div className="action-card__symbol">
            {candidate.symbol}
            <span>{candidate.name || ""}</span>
          </div>
          <div className="action-card__summary">{shortText(candidate.world_state_summary || candidate.thesis, 120) || t("today.stateSummaryFallback")}</div>
        </div>
        <div className="action-card__meta">
          <ActionChip action={candidate.action} />
          <TrustBadge score={candidate.trust_score} level={candidate.trust_level} />
        </div>
      </div>
      <div className="action-card__footer">
        <div className="action-card__invalidator">{shortText((candidate.top_invalidators || []).join(" · "), 90) || t("candidates.table.noInvalidator")}</div>
        <button type="button" className="button button--ghost" onClick={() => candidate.symbol && onOpenSymbol(candidate.symbol)}>
          {t("common.openWorkspace")}
        </button>
      </div>
    </PanelCard>
  );
}
