import { useMemo, useRef, useState } from "react";

import type { OpsLayerKey, OpsNodeType, ReadinessCell, ReadinessRow } from "../lib/api";
import { formatDate, formatPercent } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { getDatasetText, getOpsLayerText, getReadinessStatusText } from "../lib/statusText";
import { classNames } from "../lib/ui";
import { NodeTypeBadge } from "./NodeTypeBadge";

type HoverState = {
  cell: ReadinessCell;
  row: ReadinessRow;
  top: number;
  left: number;
};

export type ReadinessRowMeta = {
  nodeId?: string | null;
  nodeType?: OpsNodeType | string | null;
  layer?: OpsLayerKey | string | null;
  description?: string | null;
};

type ReadinessHeatmapProps = {
  rows: ReadinessRow[];
  dates: string[];
  activeCellId?: string | null;
  selectedCellIds?: string[];
  selectedNodeIds?: string[];
  rowMeta?: Record<string, ReadinessRowMeta>;
  collapsedGroups?: Record<string, boolean>;
  onToggleGroup?: (groupKey: string) => void;
  onSelect: (row: ReadinessRow, cell: ReadinessCell, options?: { append?: boolean }) => void;
  onToggleRow?: (row: ReadinessRow) => void;
};

function cellClass(status?: string | null) {
  const normalized = String(status || "UNKNOWN").toLowerCase();
  if (normalized === "late_ready") {
    return "readiness-cell--late-ready";
  }
  return `readiness-cell--${normalized.replace(/_/g, "-")}`;
}

export function ReadinessHeatmap({
  rows,
  dates,
  activeCellId,
  selectedCellIds = [],
  selectedNodeIds = [],
  rowMeta = {},
  collapsedGroups = {},
  onToggleGroup,
  onSelect,
  onToggleRow,
}: ReadinessHeatmapProps) {
  const { locale, t } = useI18n();
  const shellRef = useRef<HTMLDivElement | null>(null);
  const [hovered, setHovered] = useState<HoverState | null>(null);

  const groupedRows = useMemo(() => {
    const order: OpsLayerKey[] = ["source", "feature", "factor", "model", "decision", "workflow"];
    return order
      .map((layer) => ({
        key: layer,
        label: getOpsLayerText(locale, layer),
        rows: rows.filter((row) => String(rowMeta[row.dataset]?.layer || "source") === layer),
      }))
      .filter((group) => group.rows.length > 0);
  }, [locale, rowMeta, rows]);

  return (
    <div className="readiness-heatmap-shell" ref={shellRef}>
      <div className="readiness-heatmap-range">
        <div className="readiness-heatmap-range__anchor" />
        {dates.map((day, index) => (
          <div className="readiness-heatmap-range__item" key={day}>
            {index % 7 === 0 ? formatDate(day, locale === "zh-CN" ? "zh-CN" : "en-US") : ""}
          </div>
        ))}
      </div>

      <div className="readiness-heatmap-grid">
        {groupedRows.map((group) => (
          <section className="readiness-group" key={group.key}>
            <button type="button" className="readiness-group__header" onClick={() => onToggleGroup?.(group.key)}>
              <div>
                <strong>{group.label}</strong>
                <span>{group.rows.length} {t("ops.nodes")}</span>
              </div>
              <span>{collapsedGroups[group.key] ? "+" : "−"}</span>
            </button>

            {!collapsedGroups[group.key] && group.rows.map((row) => {
              const meta = rowMeta[row.dataset] || {};
              const nodeId = meta.nodeId || undefined;
              const rowSelected = Boolean(nodeId && selectedNodeIds.includes(nodeId));

              return (
                <div className="readiness-heatmap-row" key={row.dataset}>
                  <div className="readiness-dataset-label">
                    <div className="readiness-dataset-label__head">
                      <label className="selection-check">
                        <input
                          type="checkbox"
                          checked={rowSelected}
                          onChange={() => onToggleRow?.(row)}
                        />
                        <span />
                      </label>
                      <NodeTypeBadge type={meta.nodeType || "source"} subtle />
                    </div>
                    <strong>{getDatasetText(locale, row.dataset, row.label)}</strong>
                    <span>{row.critical ? t("readiness.critical") : row.job_name || meta.description || ""}</span>
                  </div>
                  <div className="readiness-heatmap-row__cells">
                    {row.cells.map((cell) => (
                      <button
                        key={cell.id}
                        type="button"
                        className={classNames(
                          "readiness-cell",
                          cellClass(cell.status),
                          activeCellId === cell.id && "is-active",
                          selectedCellIds.includes(cell.id) && "is-marked",
                        )}
                        onClick={(event) =>
                          onSelect(row, cell, {
                            append: event.metaKey || event.ctrlKey || event.shiftKey,
                          })
                        }
                        onMouseEnter={(event) => {
                          const container = shellRef.current?.getBoundingClientRect();
                          const target = event.currentTarget.getBoundingClientRect();
                          if (!container) {
                            return;
                          }
                          setHovered({
                            cell,
                            row,
                            top: target.top - container.top + target.height + 10,
                            left: Math.max(0, target.left - container.left - 120),
                          });
                        }}
                        onMouseLeave={() => setHovered((current) => (current?.cell.id === cell.id ? null : current))}
                        aria-label={`${row.label} ${cell.date} ${cell.status}`}
                      />
                    ))}
                  </div>
                </div>
              );
            })}
          </section>
        ))}
      </div>

      {hovered && (
        <div className="readiness-tooltip" style={{ top: hovered.top, left: hovered.left }}>
          <div className="readiness-tooltip__title">
            {getDatasetText(locale, hovered.row.dataset, hovered.row.label)}
            <span>{formatDate(hovered.cell.date, locale === "zh-CN" ? "zh-CN" : "en-US")}</span>
          </div>
          <div className="readiness-tooltip__body">
            <div>{getReadinessStatusText(locale, hovered.cell.status).label}</div>
            <div>{t("readiness.coverage")} {formatPercent(hovered.cell.coverage_pct, 0)}</div>
            <div>{t("readiness.lagDays")} {hovered.cell.lag_days ?? "—"}</div>
            <div>{t("readiness.rowCount")} {hovered.cell.row_count ?? "—"} / {hovered.cell.expected_count ?? "—"}</div>
            <div>{t("readiness.latestSourceDate")} {hovered.cell.source_last_date || "—"}</div>
          </div>
        </div>
      )}
    </div>
  );
}
