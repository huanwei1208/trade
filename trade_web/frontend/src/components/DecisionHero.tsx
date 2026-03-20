import type { TodayPageData } from "../lib/api";
import { formatDate, formatPercent, labelizeDataset } from "../lib/format";
import type { TodayCall } from "../lib/ui";
import { ActionChip } from "./ActionChip";
import { PanelCard } from "./PanelCard";
import { StatusPill } from "./StatusPill";
import { TrustBadge } from "./TrustBadge";

type DecisionHeroProps = {
  today: TodayPageData;
  todayCall: TodayCall;
};

export function DecisionHero({ today, todayCall }: DecisionHeroProps) {
  const freshnessIssues = today.blocker_details || [];

  return (
    <PanelCard className="decision-hero" accent={todayCall.tone === "ok" ? "green" : todayCall.tone === "warn" ? "amber" : todayCall.tone === "err" ? "red" : "blue"}>
      <div className="decision-hero__grid">
        <div className="decision-hero__primary">
          <div className="decision-hero__chips">
            <StatusPill label={todayCall.key} tone={todayCall.tone} />
            <StatusPill label={today.market_regime || "UNKNOWN"} tone="info" subtle />
            <TrustBadge score={today.trust_gate?.trust_scalar ?? undefined} level={today.trust_gate?.operational_status?.toUpperCase()} detailed />
          </div>
          <div className="decision-hero__eyebrow">Today's call</div>
          <h2 className="decision-hero__headline">{todayCall.headline}</h2>
          <p className="decision-hero__thesis">{today.today_thesis || todayCall.summary}</p>
          <div className="decision-hero__microcopy">
            <span>As of {formatDate(today.as_of)}</span>
            <span>Gate {today.gate_status || "unknown"}</span>
            {today.kline_last_date && <span>Market data {formatDate(today.kline_last_date)}</span>}
          </div>
        </div>

        <div className="decision-hero__side">
          <div className="hero-stat">
            <div className="hero-stat__label">Trust scalar</div>
            <div className="hero-stat__value">{formatPercent(today.trust_gate?.trust_scalar, 0)}</div>
          </div>
          <div className="hero-stat">
            <div className="hero-stat__label">Actionable names</div>
            <div className="hero-stat__value">
              {(today.top_actions || []).filter((item) => ["ADD", "PROBE", "REDUCE"].includes(String(item.action || "").toUpperCase())).length}
            </div>
          </div>
          <div className="hero-stat">
            <div className="hero-stat__label">Recovery condition</div>
            <div className="hero-stat__text">{today.recovery_condition || "Wait for stronger confirmation."}</div>
          </div>
        </div>
      </div>

      {Boolean(today.global_blocked || freshnessIssues.length || (today.blockers || []).length) && (
        <div className="decision-hero__blocker">
          <div className="decision-hero__blocker-title">Global constraint</div>
          <div className="decision-hero__blocker-copy">
            {(today.blockers || []).join(" · ") || "Decision quality is constrained by trust or data freshness."}
          </div>
          <div className="decision-hero__blocker-list">
            {freshnessIssues.map((item) => (
              <div className="decision-hero__blocker-item" key={`${item.dataset}-${item.status}`}>
                <span>{labelizeDataset(item.dataset)}</span>
                <StatusPill label={`${item.status || "unknown"}${item.lag_days !== undefined && item.lag_days !== null ? ` · ${item.lag_days}d` : ""}`} tone="warn" subtle />
              </div>
            ))}
          </div>
          <div className="decision-hero__safe">
            {(today.safe_to_view || []).map((item) => (
              <StatusPill key={item} label={item} tone="info" subtle />
            ))}
          </div>
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
                <div className="decision-hero__mini-copy">{item.world_state_summary || item.thesis || "State summary unavailable."}</div>
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
