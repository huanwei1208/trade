import type { ReadinessHistoryItem } from "../lib/api";
import { formatDateTime } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { StatusPill } from "./StatusPill";

type RecoveryTimelineProps = {
  items?: ReadinessHistoryItem[];
};

export function RecoveryTimeline({ items = [] }: RecoveryTimelineProps) {
  const { locale, t } = useI18n();

  if (!items.length) {
    return <div className="note-card">{t("recovery.timelineEmpty")}</div>;
  }

  return (
    <div className="recovery-timeline">
      {items.map((item, index) => (
        <div className="recovery-timeline__item" key={`${item.ts || "history"}-${index}`}>
          <div className="recovery-timeline__time">{formatDateTime(item.ts, locale === "zh-CN" ? "zh-CN" : "en-US")}</div>
          <div className="recovery-timeline__body">
            <div className="recovery-timeline__head">
              <strong>{item.action || t("common.noDetail")}</strong>
              <StatusPill
                label={item.error ? t("queue.error") : item.status === "running" ? t("queue.running") : item.status === "queued" ? t("queue.queued") : t("queue.ok")}
                tone={item.error ? "err" : item.status === "running" || item.status === "queued" ? "info" : "ok"}
                subtle
              />
            </div>
            <div className="recovery-timeline__copy">
              {[item.reason_code, item.api_calls_actual ? `api=${item.api_calls_actual}` : "", item.duration_ms ? `${item.duration_ms}ms` : ""]
                .filter(Boolean)
                .join(" · ") || t("common.noDetail")}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
