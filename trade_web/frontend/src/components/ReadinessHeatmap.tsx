import { useRef, useState } from "react";

import type { ReadinessCell, ReadinessRow } from "../lib/api";
import { formatDate, formatPercent } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { classNames } from "../lib/ui";
import { getDatasetText, getReadinessStatusText } from "../lib/statusText";

type HoverState = {
  cell: ReadinessCell;
  row: ReadinessRow;
  top: number;
  left: number;
};

type ReadinessHeatmapProps = {
  rows: ReadinessRow[];
  dates: string[];
  selectedCellId?: string | null;
  onSelect: (row: ReadinessRow, cell: ReadinessCell) => void;
};

function cellClass(status?: string | null) {
  const normalized = String(status || "UNKNOWN").toLowerCase();
  if (normalized === "late_ready") {
    return "readiness-cell--late-ready";
  }
  return `readiness-cell--${normalized.replace(/_/g, "-")}`;
}

export function ReadinessHeatmap({ rows, dates, selectedCellId, onSelect }: ReadinessHeatmapProps) {
  const { locale, t } = useI18n();
  const shellRef = useRef<HTMLDivElement | null>(null);
  const [hovered, setHovered] = useState<HoverState | null>(null);

  return (
    <div className="readiness-heatmap-shell" ref={shellRef}>
      <div className="readiness-heatmap-range">
        {dates.map((day, index) => (
          <div className="readiness-heatmap-range__item" key={day}>
            {index % 7 === 0 ? formatDate(day, locale === "zh-CN" ? "zh-CN" : "en-US") : ""}
          </div>
        ))}
      </div>

      <div className="readiness-heatmap-grid">
        {rows.map((row) => (
          <div className="readiness-heatmap-row" key={row.dataset}>
            <div className="readiness-dataset-label">
              <strong>{getDatasetText(locale, row.dataset, row.label)}</strong>
              <span>{row.critical ? t("readiness.critical") : row.job_name || ""}</span>
            </div>
            <div className="readiness-heatmap-row__cells">
              {row.cells.map((cell) => (
                <button
                  key={cell.id}
                  type="button"
                  className={classNames("readiness-cell", cellClass(cell.status), selectedCellId === cell.id && "is-selected")}
                  onClick={() => onSelect(row, cell)}
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
