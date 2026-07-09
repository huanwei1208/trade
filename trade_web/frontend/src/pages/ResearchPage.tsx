import { useMemo, useState } from "react";

import { EmptyState } from "../components/EmptyState";
import { ErrorState } from "../components/ErrorState";
import { LoadingSkeleton } from "../components/LoadingSkeleton";
import { MetricCard } from "../components/MetricCard";
import { PanelCard } from "../components/PanelCard";
import { SectionHeader } from "../components/SectionHeader";
import { StatusPill } from "../components/StatusPill";
import type { ResearchTablesPayload, ResearchTablePayload } from "../lib/api";
import { useApiResource } from "../lib/api";

type ResearchPageProps = {
  refreshToken: number;
};

function cellText(value: unknown) {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

export function ResearchPage({ refreshToken }: ResearchPageProps) {
  const [selected, setSelected] = useState({ layer: "ads", table: "ads_data_signal_report" });
  const tables = useApiResource<ResearchTablesPayload>("/api/research/warehouse/tables", {
    deps: [refreshToken],
    cacheKey: "trade-web:research-tables",
  });
  const tablePath = selected.layer && selected.table
    ? `/api/research/warehouse/${selected.layer}/${selected.table}?limit=30`
    : null;
  const table = useApiResource<ResearchTablePayload>(tablePath, {
    deps: [refreshToken, selected.layer, selected.table],
    cacheKey: `trade-web:research-table:${selected.layer}:${selected.table}`,
  });

  const flatTables = useMemo(
    () => (tables.data?.layers || []).flatMap((layer) => layer.tables || []),
    [tables.data?.layers],
  );
  const existingTables = flatTables.filter((item) => item.exists);
  const adsTables = existingTables.filter((item) => item.layer === "ads");
  const rows = table.data?.rows || [];
  const columns = (table.data?.columns || []).slice(0, 8);

  if (tables.loading && !tables.data) {
    return <LoadingSkeleton variant="hero" />;
  }

  if (tables.error && !tables.data) {
    return (
      <ErrorState
        title="Research warehouse unavailable"
        body="The read-only research warehouse index could not be loaded."
        detail={tables.error.message}
        action={<button className="button button--primary" onClick={tables.retry}>Retry</button>}
      />
    );
  }

  return (
    <div className="page-stack">
      <section className="metric-grid metric-grid--four">
        <MetricCard label="Warehouse tables" value={String(existingTables.length)} />
        <MetricCard label="ADS tables" value={String(adsTables.length)} />
        <MetricCard label="Selected rows" value={String(table.data?.row_count ?? 0)} />
        <MetricCard label="Mode" value="Read-only" />
      </section>

      <section className="page-section">
        <SectionHeader
          title="Research warehouse"
          subtitle={tables.data?.warehouse_root || "No warehouse root detected"}
        />
        <div className="ops-grid">
          <PanelCard title="Tables" accent="blue">
            <div className="ops-list">
              {flatTables.map((item) => (
                <button
                  key={`${item.layer}.${item.table}`}
                  type="button"
                  className={`ops-list__item ${selected.layer === item.layer && selected.table === item.table ? "is-active" : ""}`}
                  onClick={() => setSelected({ layer: item.layer, table: item.table })}
                >
                  <span>{item.layer}.{item.table}</span>
                  <StatusPill
                    label={item.exists ? `${item.row_count} rows` : "missing"}
                    tone={item.exists ? "ok" : "muted"}
                    subtle
                  />
                </button>
              ))}
            </div>
          </PanelCard>

          <PanelCard title={`${selected.layer}.${selected.table}`} accent="cyan">
            {table.loading && !table.data && <LoadingSkeleton variant="panel" />}
            {table.error && !table.data && (
              <ErrorState
                title="Table unavailable"
                body="This research table could not be loaded."
                detail={table.error.message}
                action={<button className="button button--primary" onClick={table.retry}>Retry</button>}
              />
            )}
            {!table.loading && !table.error && rows.length === 0 && (
              <EmptyState title="No rows" body="The selected research table exists but has no rows yet." />
            )}
            {rows.length > 0 && (
              <div className="table-scroll">
                <table className="data-table">
                  <thead>
                    <tr>
                      {columns.map((column) => <th key={column}>{column}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {rows.slice(0, 12).map((row, idx) => (
                      <tr key={idx}>
                        {columns.map((column) => <td key={column}>{cellText(row[column])}</td>)}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </PanelCard>
        </div>
      </section>
    </div>
  );
}
