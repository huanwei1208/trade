/**
 * CandidateTable — ranked triage table for the Candidates page.
 *
 * Factor placement rule: this table shows FACTOR SUMMARY only (positive/negative chips).
 * Full factor decomposition belongs on the Symbol page.
 */
import { sparklinePath, normalizeSparkline } from "../lib/chart";
import type { CandidateRow } from "../lib/api";
import type { CandidateSortKey } from "../lib/ui";
import { formatConfidence, formatScore, shortText } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { classNames } from "../lib/ui";
import { ActionChip } from "./ActionChip";
import { TrustBadge } from "./TrustBadge";

type CandidateTableProps = {
  rows: CandidateRow[];
  selectedSymbol?: string;
  sortBy: CandidateSortKey;
  sortDir: "desc" | "asc";
  onSort: (key: CandidateSortKey) => void;
  onSelect: (row: CandidateRow) => void;
  onOpenSymbol: (symbol: string) => void;
};

/** Compact factor summary: at most one positive chip + one negative chip. */
function FactorChips({ factor_summary }: { factor_summary?: CandidateRow["factor_summary"] }) {
  const pos = (factor_summary?.positive || []).filter(Boolean).slice(0, 1);
  const neg = (factor_summary?.negative || []).filter(Boolean).slice(0, 1);
  if (!pos.length && !neg.length) return null;
  return (
    <div className="factor-chips">
      {pos.map((f) => (
        <span key={f} className="factor-chip factor-chip--positive" title={f}>
          {formatFactorLabel(f)}
        </span>
      ))}
      {neg.map((f) => (
        <span key={f} className="factor-chip factor-chip--negative" title={f}>
          {formatFactorLabel(f)}
        </span>
      ))}
    </div>
  );
}

/** Format "market:TRENDING_UP" → "trend↑" etc. */
function formatFactorLabel(raw: string): string {
  const part = raw.includes(":") ? raw.split(":")[1] : raw;
  return part
    .toLowerCase()
    .replace(/_/g, " ")
    .replace("trending up", "trend↑")
    .replace("trending down", "trend↓")
    .replace("positive", "pos")
    .replace("negative", "neg")
    .replace("high", "hi")
    .replace("low", "lo");
}

function SortIndicator({ active, dir }: { active: boolean; dir: "desc" | "asc" }) {
  if (!active) return <span className="sort-indicator sort-indicator--idle">⇅</span>;
  return <span className="sort-indicator sort-indicator--active">{dir === "desc" ? "↓" : "↑"}</span>;
}

type ColDef = {
  key: CandidateSortKey;
  labelKey: string;
  sortable: boolean;
};

const COLUMNS: ColDef[] = [
  { key: "action",      labelKey: "candidates.table.decision",    sortable: true  },
  { key: "confidence",  labelKey: "candidates.table.confidence",  sortable: true  },
  { key: "trust",       labelKey: "candidates.table.trust",       sortable: true  },
  { key: "belief",      labelKey: "candidates.table.belief",      sortable: true  },
  { key: "belief_delta",labelKey: "candidates.table.delta",       sortable: true  },
  { key: "risk",        labelKey: "candidates.table.risk",        sortable: true  },
  { key: "risk_adjusted",labelKey: "candidates.table.factors",   sortable: false },
];

export function CandidateTable({ rows, selectedSymbol, sortBy, sortDir, onSort, onSelect, onOpenSymbol }: CandidateTableProps) {
  const { t } = useI18n();
  const selectedIndex = rows.findIndex((row) => row.symbol === selectedSymbol);

  function move(delta: number) {
    if (!rows.length) return;
    const base = selectedIndex >= 0 ? selectedIndex : 0;
    const next = Math.max(0, Math.min(rows.length - 1, base + delta));
    onSelect(rows[next]);
  }

  return (
    <div
      className="candidate-table"
      tabIndex={0}
      onKeyDown={(event) => {
        if (event.key === "ArrowDown") { event.preventDefault(); move(1); }
        if (event.key === "ArrowUp")   { event.preventDefault(); move(-1); }
        if (event.key === "Enter" && selectedSymbol) { event.preventDefault(); onOpenSymbol(selectedSymbol); }
      }}
    >
      {/* Table header */}
      <div className="candidate-table__head">
        <span className="candidate-table__th candidate-table__th--symbol">
          {t("candidates.table.symbol")}
        </span>
        {COLUMNS.map((col) => (
          <button
            key={col.key}
            type="button"
            className={classNames(
              "candidate-table__th candidate-table__th--sortable",
              sortBy === col.key && "is-sorted",
            )}
            onClick={() => col.sortable && onSort(col.key)}
            aria-sort={sortBy === col.key ? (sortDir === "desc" ? "descending" : "ascending") : undefined}
          >
            {t(col.labelKey)}
            {col.sortable && <SortIndicator active={sortBy === col.key} dir={sortDir} />}
          </button>
        ))}
        <span className="candidate-table__th candidate-table__th--pulse">{t("candidates.table.pulse")}</span>
      </div>

      {/* Table body */}
      <div className="candidate-table__body">
        {rows.map((row) => {
          const sparkline = normalizeSparkline(row.sparkline);
          const hasBeliefDelta = row.belief_delta_mu !== null && row.belief_delta_mu !== undefined;
          const beliefDelta = Number(row.belief_delta_mu);
          const recState = row.recommendation_state;

          return (
            <button
              key={row.symbol}
              type="button"
              className={classNames(
                "candidate-row",
                row.symbol === selectedSymbol && "is-selected",
                recState === "CONSTRAINED" && "candidate-row--constrained",
                recState === "BROWSE_ONLY" && "candidate-row--browse-only",
              )}
              onClick={() => onSelect(row)}
              onDoubleClick={() => row.symbol && onOpenSymbol(row.symbol)}
            >
              {/* Symbol + name + summary */}
              <div className="candidate-row__identity">
                <div className="candidate-row__symbol">
                  {row.symbol}
                  {recState === "CONSTRAINED" && (
                    <span className="rec-state-badge rec-state-badge--constrained" title={row.data_risk_flag || undefined}>⚠</span>
                  )}
                  {recState === "BROWSE_ONLY" && (
                    <span className="rec-state-badge rec-state-badge--browse" title="Browse only">○</span>
                  )}
                </div>
                <div className="candidate-row__name">{row.name || t("candidates.table.noName")}</div>
                <div className="candidate-row__summary">{shortText(row.world_state_summary || row.thesis, 60) || ""}</div>
              </div>

              {/* Decision */}
              <div className="candidate-row__cell">
                <ActionChip action={row.action} />
              </div>

              {/* Confidence */}
              <div className="candidate-row__cell candidate-row__cell--num">
                <span className="candidate-row__conf">{formatConfidence(row.confidence)}</span>
              </div>

              {/* Trust (symbol-level) */}
              <div className="candidate-row__cell">
                <TrustBadge score={row.trust_score} level={row.trust_level} />
              </div>

              {/* Belief μ */}
              <div className="candidate-row__cell candidate-row__cell--num">
                {row.belief_mu !== undefined && row.belief_mu !== null ? (
                  <span className={classNames(
                    "belief-mu",
                    row.belief_mu > 0.1 ? "is-positive" : row.belief_mu < -0.1 ? "is-negative" : ""
                  )}>
                    {row.belief_mu >= 0 ? "+" : ""}{formatScore(row.belief_mu, 3)}
                  </span>
                ) : <span className="candidate-row__empty">—</span>}
              </div>

              {/* ΔBelief */}
              <div className="candidate-row__cell candidate-row__cell--num">
                {hasBeliefDelta ? (
                  <span className={classNames("belief-delta", beliefDelta >= 0 ? "is-positive" : "is-negative")}>
                    {beliefDelta >= 0 ? "+" : ""}{formatScore(beliefDelta, 2)}μ
                  </span>
                ) : <span className="candidate-row__empty">—</span>}
              </div>

              {/* Risk */}
              <div className="candidate-row__cell candidate-row__cell--num">
                {row.risk !== undefined && row.risk !== null ? (
                  <span className={classNames(
                    "risk-badge",
                    row.risk > 0.6 ? "risk-badge--high" : row.risk > 0.3 ? "risk-badge--med" : "risk-badge--low"
                  )}>
                    {formatScore(row.risk, 2)}
                  </span>
                ) : <span className="candidate-row__empty">—</span>}
              </div>

              {/* Factor summary — chips only, no decomposition */}
              <div className="candidate-row__cell candidate-row__cell--factors">
                <FactorChips factor_summary={row.factor_summary} />
                {!row.factor_summary?.positive?.length && !row.factor_summary?.negative?.length && (
                  <div className="candidate-row__tags">
                    {(row.event_tags || []).slice(0, 2).map((tag) => (
                      <span className="tag-chip" key={`${row.symbol}-${tag}`}>{tag}</span>
                    ))}
                  </div>
                )}
              </div>

              {/* Sparkline */}
              <div className="candidate-row__spark">
                <svg viewBox="0 0 84 28" role="img" aria-label={`${row.symbol} sparkline`}>
                  <path d={sparklinePath(sparkline, 84, 28)} />
                </svg>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
