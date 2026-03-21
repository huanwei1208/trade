import { useState } from "react";

import type { DataOpsDomain } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { classNames } from "../lib/ui";

type Props = {
  domains?: DataOpsDomain[];
  loading?: boolean;
  selectedIds: Set<string>;
  onSelectionChange: (ids: Set<string>) => void;
};

function statusTone(status?: string): string {
  const s = (status || "").toLowerCase();
  if (s === "ok") return "ok";
  if (s === "partial") return "partial";
  if (s === "error" || s === "missing") return "error";
  if (s === "stale") return "stale";
  return "unknown";
}

function lagLabel(lag?: number | null): string {
  if (lag == null) return "—";
  if (lag === 0) return "今日";
  if (lag === 1) return "昨日";
  return `${lag}天前`;
}

export function SymbolDataCoverageMatrix({ domains = [], loading, selectedIds, onSelectionChange }: Props) {
  const { t, locale } = useI18n();

  function toggleAll() {
    if (selectedIds.size === domains.length) {
      onSelectionChange(new Set());
    } else {
      onSelectionChange(new Set(domains.map((d) => d.id!).filter(Boolean)));
    }
  }

  function toggleOne(id: string) {
    const next = new Set(selectedIds);
    if (next.has(id)) {
      next.delete(id);
    } else {
      next.add(id);
    }
    onSelectionChange(next);
  }

  if (loading && domains.length === 0) {
    return <div className="data-coverage-skeleton">{t("common.loading")}</div>;
  }

  if (domains.length === 0) {
    return <div className="data-coverage-empty">{t("symbol.dataOps.noDomains")}</div>;
  }

  const allSelected = domains.length > 0 && selectedIds.size === domains.length;

  return (
    <div className="data-coverage-matrix">
      <table className="data-coverage-matrix__table">
        <thead>
          <tr>
            <th className="data-coverage-matrix__th data-coverage-matrix__th--check">
              <input
                type="checkbox"
                checked={allSelected}
                onChange={toggleAll}
                aria-label={t("symbol.dataOps.selectAll")}
              />
            </th>
            <th className="data-coverage-matrix__th">{t("symbol.dataOps.domain")}</th>
            <th className="data-coverage-matrix__th">{t("symbol.dataOps.source")}</th>
            <th className="data-coverage-matrix__th">{t("symbol.dataOps.lastDate")}</th>
            <th className="data-coverage-matrix__th">{t("symbol.dataOps.lag")}</th>
            <th className="data-coverage-matrix__th">{t("symbol.dataOps.rows")}</th>
            <th className="data-coverage-matrix__th">{t("symbol.dataOps.status")}</th>
          </tr>
        </thead>
        <tbody>
          {domains.map((d) => {
            const id = d.id || "";
            const tone = statusTone(d.status);
            const checked = selectedIds.has(id);
            return (
              <tr
                key={id}
                className={classNames("data-coverage-matrix__row", checked && "is-selected")}
                onClick={() => toggleOne(id)}
              >
                <td className="data-coverage-matrix__td data-coverage-matrix__td--check">
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => toggleOne(id)}
                    onClick={(e) => e.stopPropagation()}
                    aria-label={`${t("symbol.dataOps.select")} ${id}`}
                  />
                </td>
                <td className="data-coverage-matrix__td data-coverage-matrix__td--name">
                  {locale === "zh-CN" ? d.name_zh : d.name_en}
                </td>
                <td className="data-coverage-matrix__td data-coverage-matrix__td--source">
                  {d.source || "—"}
                </td>
                <td className="data-coverage-matrix__td data-coverage-matrix__td--date">
                  {d.last_date || "—"}
                </td>
                <td className="data-coverage-matrix__td data-coverage-matrix__td--lag">
                  {lagLabel(d.lag_days)}
                </td>
                <td className="data-coverage-matrix__td data-coverage-matrix__td--rows">
                  {d.row_count != null ? d.row_count.toLocaleString() : "—"}
                </td>
                <td className="data-coverage-matrix__td data-coverage-matrix__td--status">
                  <span className={`data-status-badge data-status-badge--${tone}`}>{d.status || "?"}</span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
