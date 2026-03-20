import type { TodayPageData } from "../lib/api";
import { formatDate, formatPercent, labelizeDataset } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { getGateStatusText, getMarketRegimeText, getTodayUsageCopy } from "../lib/statusText";
import type { TodayCall } from "../lib/ui";
import { ActionChip } from "./ActionChip";
import { PanelCard } from "./PanelCard";
import { StatusPill } from "./StatusPill";
import { TrustBadge } from "./TrustBadge";

type DecisionHeroProps = {
  today: TodayPageData;
  todayCall: TodayCall;
  onOpenReadiness?: () => void;
};

export function DecisionHero({ today, todayCall, onOpenReadiness }: DecisionHeroProps) {
  const { locale, t } = useI18n();
  const freshnessIssues = today.blocker_details || [];
  const marketRegime = getMarketRegimeText(locale, today.market_regime);
  const gateStatus = getGateStatusText(locale, today.gate_status || today.trust_gate?.operational_status);
  const usage = getTodayUsageCopy(locale, today);

  return (
    <PanelCard className="decision-hero" accent={todayCall.tone === "ok" ? "green" : todayCall.tone === "warn" ? "amber" : todayCall.tone === "err" ? "red" : "blue"}>
      <div className="decision-hero__grid">
        <div className="decision-hero__primary">
          <div className="decision-hero__chips">
            <StatusPill label={todayCall.headline} tone={todayCall.tone} />
            <StatusPill label={marketRegime.label} tone={marketRegime.tone} subtle />
            <StatusPill label={gateStatus.label} tone={gateStatus.tone} subtle />
            <TrustBadge score={today.trust_gate?.trust_scalar ?? undefined} />
          </div>
          <div className="decision-hero__eyebrow">{t("page.today.title")}</div>
          <h2 className="decision-hero__headline">{todayCall.headline}</h2>
          <p className="decision-hero__thesis">{today.today_thesis || todayCall.summary}</p>
          <div className="decision-hero__microcopy">
            <span>{t("shell.asOf", { date: formatDate(today.as_of, locale === "zh-CN" ? "zh-CN" : "en-US") })}</span>
            <span>{gateStatus.description}</span>
            {today.kline_last_date && <span>{t("today.marketData")} {formatDate(today.kline_last_date, locale === "zh-CN" ? "zh-CN" : "en-US")}</span>}
          </div>
        </div>

        <div className="decision-hero__side">
          <div className="hero-stat">
            <div className="hero-stat__label">{t("today.canITrust")}</div>
            <div className="hero-stat__value">{usage.conclusionMode.label}</div>
            <div className="hero-stat__text">{usage.trust.description}</div>
          </div>
          <div className="hero-stat">
            <div className="hero-stat__label">{t("today.trustScalar")}</div>
            <div className="hero-stat__value">{formatPercent(today.trust_gate?.trust_scalar, 0)}</div>
            <div className="hero-stat__text">{usage.trust.label}</div>
          </div>
          <div className="hero-stat">
            <div className="hero-stat__label">{t("today.actionableNames")}</div>
            <div className="hero-stat__value">
              {(today.top_actions || []).filter((item) => ["ADD", "PROBE", "REDUCE"].includes(String(item.action || "").toUpperCase())).length}
            </div>
          </div>
          <div className="hero-stat">
            <div className="hero-stat__label">{t("today.recoveryCondition")}</div>
            <div className="hero-stat__text">{usage.recoveryPath}</div>
          </div>
        </div>
      </div>

      <div className="decision-hero__summary">
        <div className="decision-hero__summary-item">
          <span>{t("today.canITrust")}</span>
          <strong>{usage.trust.label}</strong>
          <p>{usage.trust.description}</p>
        </div>
        <div className="decision-hero__summary-item">
          <span>{t("today.conclusionMode")}</span>
          <strong>{usage.conclusionMode.label}</strong>
          <p>{usage.conclusionMode.description}</p>
        </div>
        <div className="decision-hero__summary-item">
          <span>{t("today.whyConstrained")}</span>
          <strong>{today.global_blocked ? t("status.constrained") : gateStatus.label}</strong>
          <p>{usage.whyConstrained}</p>
        </div>
      </div>

      {Boolean(today.global_blocked || freshnessIssues.length || (today.blockers || []).length) && (
        <div className="decision-hero__blocker">
          <div className="decision-hero__blocker-title">{t("today.globalConstraint")}</div>
          <div className="decision-hero__blocker-copy">{(today.blockers || []).join(" · ") || t("today.blockersCopy")}</div>
          <div className="decision-hero__blocker-list">
            {freshnessIssues.map((item) => (
              <div className="decision-hero__blocker-item" key={`${item.dataset}-${item.status}`}>
                <span>{labelizeDataset(item.dataset)}</span>
                <StatusPill
                  label={`${getGateStatusText(locale, item.status).label}${item.lag_days !== undefined && item.lag_days !== null ? ` · ${item.lag_days}d` : ""}`}
                  tone={getGateStatusText(locale, item.status).tone}
                  subtle
                />
              </div>
            ))}
          </div>
          <div className="decision-hero__safe">
            {(today.safe_to_view || []).map((item) => (
              <StatusPill key={item} label={item} tone="info" subtle />
            ))}
          </div>
          {onOpenReadiness && (
            <div className="decision-hero__actions">
              <button type="button" className="button button--ghost" onClick={onOpenReadiness}>
                {t("common.openReadiness")}
              </button>
            </div>
          )}
        </div>
      )}

      {(today.top_actions || []).length > 0 && (
        <div className="decision-hero__strip">
          {(today.top_actions || []).slice(0, 3).map((item) => (
            <div className="decision-hero__mini" key={item.symbol}>
              <div>
                <div className="decision-hero__mini-symbol">
                  {item.symbol}
                  <span>{item.name || ""}</span>
                </div>
                <div className="decision-hero__mini-copy">{item.world_state_summary || item.thesis || t("today.stateSummaryFallback")}</div>
              </div>
              <div className="decision-hero__mini-aside">
                <ActionChip action={item.action} />
                <TrustBadge score={item.trust_score} level={item.trust_level} />
              </div>
            </div>
          ))}
        </div>
      )}
    </PanelCard>
  );
}
