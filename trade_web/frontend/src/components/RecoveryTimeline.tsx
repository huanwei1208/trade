import { extractRecoverySteps, type ReadinessActionDetail, type ReadinessHistoryItem } from "../lib/api";
import { formatDateTime, formatDurationMs } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { StatusPill } from "./StatusPill";

type RecoveryTimelineProps = {
  items?: Array<ReadinessHistoryItem | ReadinessActionDetail>;
};

function getActionLabel(t: (key: string) => string, item: ReadinessActionDetail) {
  if (item.mode === "data_only") {
    return t("recovery.repairDataRange");
  }
  if (item.mode === "full_replay") {
    return t("recovery.replayFullChainAction");
  }
  return t("recovery.restoreLatestRecommendationAction");
}

export function RecoveryTimeline({ items = [] }: RecoveryTimelineProps) {
  const { locale, t } = useI18n();

  if (!items.length) {
    return <div className="note-card">{t("recovery.timelineEmpty")}</div>;
  }

  return (
    <div className="recovery-timeline">
      {items.map((item, index) => (
        <div className="recovery-timeline__item" key={`${("requested_at" in item ? item.requested_at : item.ts) || "history"}-${index}`}>
          <div className="recovery-timeline__time">
            {formatDateTime("requested_at" in item ? item.requested_at : item.ts, locale === "zh-CN" ? "zh-CN" : "en-US")}
          </div>
          <div className="recovery-timeline__body">
            <div className="recovery-timeline__head">
              <strong>{"action_type" in item ? getActionLabel(t, item) : item.action || t("common.noDetail")}</strong>
              <StatusPill
                label={item.error ? t("queue.error") : item.status === "running" ? t("queue.running") : item.status === "queued" ? t("queue.queued") : t("queue.ok")}
                tone={item.error ? "err" : item.status === "running" || item.status === "queued" ? "info" : "ok"}
                subtle
              />
            </div>
            <div className="recovery-timeline__copy">
              {"action_type" in item
                ? [item.summary, item.date_from === item.date_to ? item.date_to : `${item.date_from} → ${item.date_to}`, formatDurationMs(item.result?.duration_ms)]
                    .filter(Boolean)
                    .join(" · ") || t("common.noDetail")
                : [item.reason_code, item.api_calls_actual ? `api=${item.api_calls_actual}` : "", formatDurationMs(item.duration_ms)]
                    .filter(Boolean)
                    .join(" · ") || t("common.noDetail")}
            </div>
            {"action_type" in item && extractRecoverySteps(item).length > 0 && (
              <div className="recovery-timeline__steps">
                {extractRecoverySteps(item).map((step, stepIndex) => (
                  <div className="recovery-timeline__step" key={`${step.job_name || "step"}-${stepIndex}`}>
                    <div className="recovery-timeline__step-head">
                      <strong>{step.job_name || t("recovery.unknownStep")}</strong>
                      <StatusPill
                        label={step.status === "running" ? t("queue.running") : step.status === "queued" ? t("queue.queued") : step.status === "error" ? t("queue.error") : t("queue.ok")}
                        tone={step.status === "running" || step.status === "queued" ? "info" : step.status === "error" ? "err" : "ok"}
                        subtle
                      />
                    </div>
                    <div className="recovery-timeline__step-copy">
                      {[step.summary, formatDurationMs(step.duration_ms)].filter(Boolean).join(" · ") || t("common.noDetail")}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
