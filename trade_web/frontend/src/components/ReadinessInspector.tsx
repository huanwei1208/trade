import type { ReactNode } from "react";

import type { ReadinessCell, ReadinessRow } from "../lib/api";
import { formatDate, formatDateTime, formatPercent } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { getDatasetText, getImpactText, getReadinessStatusText } from "../lib/statusText";
import { EmptyState } from "./EmptyState";
import { PanelCard } from "./PanelCard";
import { RecoveryTimeline } from "./RecoveryTimeline";
import { StatusPill } from "./StatusPill";

type ReadinessInspectorProps = {
  row?: ReadinessRow | null;
  cell?: ReadinessCell | null;
  actions?: ReactNode;
};

export function ReadinessInspector({ row, cell, actions }: ReadinessInspectorProps) {
  const { locale, t } = useI18n();

  if (!row || !cell) {
    return (
      <PanelCard className="readiness-inspector">
        <EmptyState title={t("readiness.selectCell")} body={t("readiness.selectCellCopy")} />
      </PanelCard>
    );
  }

  const status = getReadinessStatusText(locale, cell.status);

  return (
    <PanelCard className="readiness-inspector">
      <div className="readiness-inspector__section">
        <div className="readiness-inspector__label">{t("readiness.dataset")}</div>
        <div className="readiness-inspector__value">{getDatasetText(locale, row.dataset, row.label)}</div>
        <div className="readiness-inspector__subtle">{formatDate(cell.date, locale === "zh-CN" ? "zh-CN" : "en-US")}</div>
      </div>

      <div className="readiness-inspector__section">
        <div className="readiness-inspector__label">{t("readiness.state")}</div>
        <div className="readiness-inspector__pill-row">
          <StatusPill label={status.label} tone={status.tone} />
          {row.critical && <StatusPill label={t("readiness.critical")} tone="warn" subtle />}
        </div>
        <div className="readiness-inspector__subtle">{status.description}</div>
      </div>

      <div className="readiness-inspector__section">
        <div className="readiness-inspector__label">{t("readiness.whyState")}</div>
        <div className="inspector-metric-grid">
          <div className="inspector-metric">
            <span>{t("readiness.coverage")}</span>
            <strong>{formatPercent(cell.coverage_pct, 0)}</strong>
          </div>
          <div className="inspector-metric">
            <span>{t("readiness.lagDays")}</span>
            <strong>{cell.lag_days ?? "—"}</strong>
          </div>
          <div className="inspector-metric">
            <span>{t("readiness.rowCount")}</span>
            <strong>{cell.row_count ?? "—"}</strong>
          </div>
          <div className="inspector-metric">
            <span>{t("readiness.expectedCount")}</span>
            <strong>{cell.expected_count ?? "—"}</strong>
          </div>
        </div>
        <div className="readiness-inspector__kv">
          <span>{t("readiness.latestSourceDate")}</span>
          <strong>{cell.source_last_date ? formatDate(cell.source_last_date, locale === "zh-CN" ? "zh-CN" : "en-US") : "—"}</strong>
        </div>
        <div className="readiness-inspector__kv">
          <span>{t("readiness.lastBackfillAt")}</span>
          <strong>{cell.last_backfill_at ? formatDateTime(cell.last_backfill_at, locale === "zh-CN" ? "zh-CN" : "en-US") : "—"}</strong>
        </div>
        <div className="readiness-inspector__kv">
          <span>{t("readiness.jobName")}</span>
          <strong>{row.job_name || "—"}</strong>
        </div>
      </div>

      <div className="readiness-inspector__section">
        <div className="readiness-inspector__label">{t("readiness.affectedOutputs")}</div>
        <div className="tag-cluster">
          {(cell.affected_outputs || []).map((item) => (
            <span className="tag-chip" key={item}>
              {getImpactText(locale, item)}
            </span>
          ))}
        </div>
      </div>

      {actions}

      <div className="readiness-inspector__section">
        <div className="readiness-inspector__label">{t("readiness.auditHistory")}</div>
        <RecoveryTimeline items={cell.history} />
      </div>
    </PanelCard>
  );
}
