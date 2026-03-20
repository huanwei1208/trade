import { sparklinePath, normalizeSparkline } from "../lib/chart";
import type { CandidateRow } from "../lib/api";
import { formatConfidence, formatScore, shortText } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { classNames } from "../lib/ui";
import { ActionChip } from "./ActionChip";
import { TrustBadge } from "./TrustBadge";

type CandidateTableProps = {
  rows: CandidateRow[];
  selectedSymbol?: string;
  onSelect: (row: CandidateRow) => void;
  onOpenSymbol: (symbol: string) => void;
};

export function CandidateTable({ rows, selectedSymbol, onSelect, onOpenSymbol }: CandidateTableProps) {
  const { t } = useI18n();
  const selectedIndex = rows.findIndex((row) => row.symbol === selectedSymbol);

  function move(delta: number) {
    if (!rows.length) {
      return;
    }
    const base = selectedIndex >= 0 ? selectedIndex : 0;
    const next = Math.max(0, Math.min(rows.length - 1, base + delta));
    onSelect(rows[next]);
  }

  return (
    <div
      className="candidate-table"
      tabIndex={0}
      onKeyDown={(event) => {
        if (event.key === "ArrowDown") {
          event.preventDefault();
          move(1);
        }
        if (event.key === "ArrowUp") {
          event.preventDefault();
          move(-1);
        }
        if (event.key === "Enter" && selectedSymbol) {
          event.preventDefault();
          onOpenSymbol(selectedSymbol);
        }
      }}
    >
      <div className="candidate-table__head">
        <span>{t("candidates.table.symbol")}</span>
        <span>{t("candidates.table.decision")}</span>
        <span>{t("candidates.table.beliefChange")}</span>
        <span>{t("candidates.table.pulse")}</span>
      </div>
      <div className="candidate-table__body">
        {rows.map((row) => {
          const sparkline = normalizeSparkline(row.sparkline);
          const hasBeliefDelta = row.belief_delta_mu !== null && row.belief_delta_mu !== undefined;
          const beliefDelta = Number(row.belief_delta_mu);
          return (
            <button
              key={row.symbol}
              type="button"
              className={classNames("candidate-row", row.symbol === selectedSymbol && "is-selected")}
              onClick={() => onSelect(row)}
              onDoubleClick={() => row.symbol && onOpenSymbol(row.symbol)}
            >
              <div className="candidate-row__identity">
                <div className="candidate-row__symbol">{row.symbol}</div>
                <div className="candidate-row__name">{row.name || t("candidates.table.noName")}</div>
                <div className="candidate-row__summary">{shortText(row.world_state_summary || row.thesis, 72) || ""}</div>
              </div>
              <div className="candidate-row__decision">
                <ActionChip action={row.action} />
                <div className="candidate-row__meta">
                  <span>{formatConfidence(row.confidence)}</span>
                </div>
              </div>
              <div className="candidate-row__quant">
                <TrustBadge score={row.trust_score} level={row.trust_level} />
                {hasBeliefDelta && (
                  <span className={classNames("belief-delta", beliefDelta >= 0 ? "is-positive" : "is-negative")}>
                    {beliefDelta >= 0 ? "+" : ""}{formatScore(beliefDelta, 2)}μ
                  </span>
                )}
                <div className="candidate-row__tags">
                  {(row.event_tags || []).slice(0, 2).map((tag) => (
                    <span className="tag-chip" key={`${row.symbol}-${tag}`}>
                      {tag}
                    </span>
                  ))}
                </div>
              </div>
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
