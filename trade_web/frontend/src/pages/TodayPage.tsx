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
import type { CandidateRow, TodayPageData } from "../lib/api";
import { useApiResource } from "../lib/api";
import { formatConfidence, formatScore, shortText } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { classNames } from "../lib/ui";
import { getDatasetText, getGateStatusText } from "../lib/statusText";
import { getTodayCall, isActionable } from "../lib/ui";

type TodayPageProps = {
  refreshToken: number;
  onOpenSymbol: (symbol: string) => void;
  onOpenOpsFocus: (focus: { tab: "readiness" | "recovery"; date?: string; dataset?: string }) => void;
  onOpenCandidates?: () => void;
};

type OperatingMode = "actionable" | "review" | "blocked";

function getOperatingMode(today: TodayPageData): OperatingMode {
  if (today.global_blocked) return "blocked";
  const opStatus = String(today.trust_gate?.operational_status || "").toLowerCase();
  if (opStatus.includes("research") || opStatus.includes("browse")) return "review";
  const trust = today.trust_gate?.trust_scalar;
  if (typeof trust === "number" && trust < 0.4) return "review";
  return "actionable";
}

function OperatingModeBanner({
  today,
  mode,
  onOpenCandidates,
  onOpenRecovery,
}: {
  today: TodayPageData;
  mode: OperatingMode;
  onOpenCandidates?: () => void;
  onOpenRecovery?: () => void;
}) {
  const { locale, t } = useI18n();
  const modeLabel =
    mode === "actionable"
      ? t("today.operatingModeActionable")
      : mode === "review"
        ? t("today.operatingModeReviewOnly")
        : t("today.operatingModeBlocked");

  const mainBlocker =
    (today.blockers || [])[0] ||
    (today.blocker_details?.[0]?.dataset ? getDatasetText(locale, today.blocker_details[0].dataset) : undefined);

  return (
    <div className={`today-mode-banner today-mode-banner--${mode}`}>
      <div className="today-mode-banner__left">
        <div className="today-mode-banner__mode">{t("today.operatingMode")}</div>
        <div className={`today-mode-banner__value today-mode-banner__value--${mode}`}>{modeLabel}</div>
        {mainBlocker && (
          <div className="today-mode-banner__constraint">
            {t("today.mainConstraint")}: {mainBlocker}
          </div>
        )}
      </div>
      <div className="today-mode-banner__actions">
        {mode === "actionable" && onOpenCandidates && (
          <button type="button" className="button button--primary" onClick={onOpenCandidates}>
            {t("today.viewPriorityCandidates")}
          </button>
        )}
        {(mode === "review" || mode === "blocked") && onOpenRecovery && (
          <button type="button" className="button button--ghost" onClick={onOpenRecovery}>
            {t("today.openDataRecovery")}
          </button>
        )}
      </div>
    </div>
  );
}

export function TodayPage({ refreshToken, onOpenSymbol, onOpenOpsFocus, onOpenCandidates }: TodayPageProps) {
  const { locale, t } = useI18n();
  const todayResource = useApiResource<TodayPageData>("/api/today-page", {
    deps: [refreshToken],
    cacheKey: "trade-web:today-page",
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

  const mode = getOperatingMode(today);

  return (
    <div className="page-stack page-today">
      <OperatingModeBanner
        today={today}
        mode={mode}
        onOpenCandidates={onOpenCandidates}
        onOpenRecovery={() =>
          onOpenOpsFocus({
            tab: "recovery",
            date: today.as_of,
            dataset: today.blocker_details?.[0]?.dataset || "signals",
          })
        }
      />

      <DecisionHero
        today={today}
        todayCall={todayCall}
        onOpenReadiness={() =>
          onOpenOpsFocus({
            tab: "readiness",
            date: today.as_of,
            dataset: today.blocker_details?.[0]?.dataset || "signals",
          })
        }
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
              onClick={() =>
                onOpenOpsFocus({
                  tab: "readiness",
                  date: today.as_of,
                  dataset: today.blocker_details?.[0]?.dataset || "signals",
                })
              }
            >
              {t("common.openReadiness")}
            </button>
          </PanelCard>
        )}
      </section>

      <section className="page-section">
        <SectionHeader title={t("today.diagnostics")} subtitle={t("today.diagnosticsSubtitle")} />
        <div className="subtle-grid">
          <CollapseSection title={t("today.trustAndFreshness")} initialOpen={false}>
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
    </div>
  );
}

function ActionCard({ candidate, onOpenSymbol }: { candidate: CandidateRow; onOpenSymbol: (symbol: string) => void }) {
  const { t } = useI18n();
  const hasBeliefDelta = candidate.belief_delta_mu !== null && candidate.belief_delta_mu !== undefined;
  const beliefDelta = Number(candidate.belief_delta_mu);
  return (
    <PanelCard accent={String(candidate.action || "").toUpperCase() === "ADD" ? "green" : String(candidate.action || "").toUpperCase() === "PROBE" ? "cyan" : "amber"} className="action-card">
      <div className="action-card__head">
        <div>
          <div className="action-card__symbol">
            {candidate.symbol}
            <span>{candidate.name || ""}</span>
          </div>
          <div className="action-card__summary">{shortText(candidate.world_state_summary || candidate.thesis, 100) || t("today.stateSummaryFallback")}</div>
        </div>
        <div className="action-card__meta">
          <ActionChip action={candidate.action} />
          <TrustBadge score={candidate.trust_score} level={candidate.trust_level} />
        </div>
      </div>
      <div className="action-card__stats">
        {candidate.confidence !== undefined && candidate.confidence !== null && (
          <span className="action-card__stat">{formatConfidence(candidate.confidence)}</span>
        )}
        {hasBeliefDelta && (
          <span className={classNames("action-card__stat belief-delta", beliefDelta >= 0 ? "is-positive" : "is-negative")}>
            {beliefDelta >= 0 ? "+" : ""}{formatScore(beliefDelta, 2)}μ
          </span>
        )}
      </div>
      <div className="action-card__footer">
        <div className="action-card__invalidator">{shortText((candidate.top_invalidators || []).join(" · "), 80) || t("candidates.table.noInvalidator")}</div>
        <button type="button" className="button button--ghost" onClick={() => candidate.symbol && onOpenSymbol(candidate.symbol)}>
          {t("common.openWorkspace")}
        </button>
      </div>
    </PanelCard>
  );
}
