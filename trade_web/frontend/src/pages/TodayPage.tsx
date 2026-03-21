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

  // Split by recommendation state — ALWAYS show both groups, never hide recommendations.
  // "Blocked" means constrained execution, not "no recommendations".
  const actionableCards = actions.filter(
    (item) => item.recommendation_state === "ACTIONABLE" || (
      !item.recommendation_state && isActionable(item.action) && String(item.action || "").toUpperCase() !== "WATCH"
    )
  );
  const constrainedCards = actions.filter(
    (item) => item.recommendation_state === "CONSTRAINED" || item.recommendation_state === "BROWSE_ONLY" || (
      !item.recommendation_state && (!isActionable(item.action) || String(item.action || "").toUpperCase() === "WATCH")
    )
  );

  // When globally blocked, all actionable cards should be in constrained group
  const isBlocked = Boolean(todayResource.data?.global_blocked);
  const displayActionable = isBlocked ? [] : actionableCards;
  const displayConstrained = isBlocked
    ? [...actionableCards, ...constrainedCards]
    : constrainedCards;

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
  const hasAnyRecommendations = actions.length > 0;

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

      {/* ── Recommended symbols — ALWAYS rendered ──────────────────────────────
          Blocked = constrained execution, NOT "no recommendations".
          Always show what the system recommends, labelled clearly.
      */}
      <section className="page-section">
        <SectionHeader
          title={t("today.topSetups")}
          subtitle={
            !hasAnyRecommendations
              ? t("today.topSetupsConstrained")
              : displayActionable.length > 0
                ? t("today.topSetupsActionable")
                : t("today.topSetupsConstrained")
          }
        />

        {!hasAnyRecommendations && (
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

        {/* Actionable group */}
        {displayActionable.length > 0 && (
          <div className="today-rec-group">
            <div className="today-rec-group__label today-rec-group__label--actionable">
              {t("today.recGroupActionable")}
            </div>
            <div className="card-grid card-grid--actions">
              {displayActionable.slice(0, 6).map((item) => (
                <ActionCard key={item.symbol || Math.random()} candidate={item} constrained={false} onOpenSymbol={onOpenSymbol} />
              ))}
            </div>
          </div>
        )}

        {/* Constrained group — always shown when there are items */}
        {displayConstrained.length > 0 && (
          <div className="today-rec-group">
            <div className="today-rec-group__label today-rec-group__label--constrained">
              {isBlocked ? t("today.recGroupBlockedAll") : t("today.recGroupConstrained")}
            </div>
            {isBlocked && (today.blocker_details || []).length > 0 && (
              <div className="today-constraint-hint">
                {(today.blocker_details || []).slice(0, 2).map((item) => (
                  <span key={`${item.dataset}-${item.status}`} className="today-constraint-hint__item">
                    {getDatasetText(locale, item.dataset)}
                    {item.lag_days != null ? ` · ${item.lag_days}d` : ""}
                  </span>
                ))}
                <button
                  type="button"
                  className="button button--ghost today-constraint-hint__action"
                  onClick={() => onOpenOpsFocus({ tab: "readiness", date: today.as_of, dataset: today.blocker_details?.[0]?.dataset || "signals" })}
                >
                  {t("common.openReadiness")}
                </button>
              </div>
            )}
            <div className="card-grid card-grid--actions">
              {displayConstrained.slice(0, 6).map((item) => (
                <ActionCard
                  key={item.symbol || Math.random()}
                  candidate={item}
                  constrained={true}
                  constraintReason={item.data_risk_flag || (isBlocked ? today.blockers?.[0] : undefined)}
                  onOpenSymbol={onOpenSymbol}
                />
              ))}
            </div>
          </div>
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

function ActionCard({
  candidate,
  constrained,
  constraintReason,
  onOpenSymbol,
}: {
  candidate: CandidateRow;
  constrained: boolean;
  constraintReason?: string;
  onOpenSymbol: (symbol: string) => void;
}) {
  const { t } = useI18n();
  const hasBeliefDelta = candidate.belief_delta_mu !== null && candidate.belief_delta_mu !== undefined;
  const beliefDelta = Number(candidate.belief_delta_mu);
  const recState = candidate.recommendation_state;

  // Badge label based on state
  const constraintLabel = (() => {
    if (!constrained) return null;
    if (recState === "BROWSE_ONLY") return t("today.cardBrowseOnly");
    if (recState === "CONSTRAINED") return t("today.cardConstrained");
    return t("today.cardWaitingRecovery");
  })();

  return (
    <PanelCard
      accent={
        constrained ? "amber" :
        String(candidate.action || "").toUpperCase() === "ADD" ? "green" :
        String(candidate.action || "").toUpperCase() === "PROBE" ? "cyan" : "amber"
      }
      className={classNames("action-card", constrained && "action-card--constrained")}
    >
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
          {/* Symbol-level trust */}
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
        {constraintLabel && (
          <span className="action-card__constraint-badge">{constraintLabel}</span>
        )}
      </div>
      <div className="action-card__footer">
        <div className="action-card__invalidator">
          {constraintReason
            ? <span className="action-card__constraint-reason">{constraintReason}</span>
            : shortText((candidate.top_invalidators || []).join(" · "), 80) || t("candidates.table.noInvalidator")
          }
        </div>
        <button type="button" className="button button--ghost" onClick={() => candidate.symbol && onOpenSymbol(candidate.symbol)}>
          {t("common.openWorkspace")}
        </button>
      </div>
    </PanelCard>
  );
}
