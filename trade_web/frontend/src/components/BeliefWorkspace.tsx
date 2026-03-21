import { useState } from "react";

import type { BeliefGraphResponse, SubBeliefNode } from "../lib/api";
import { formatPercent } from "../lib/format";
import { useI18n } from "../lib/i18n";

type ViewMode = "funnel" | "waterfall" | "compare";

type Props = {
  data?: BeliefGraphResponse | null;
  loading?: boolean;
};

// ── Funnel view ─────────────────────────────────────────────────────────────

function BeliefFunnel({ data }: { data: BeliefGraphResponse }) {
  const { locale, t } = useI18n();
  const [selectedSub, setSelectedSub] = useState<SubBeliefNode | null>(null);

  const subBeliefs = (data.sub_beliefs || []).slice().sort((a, b) => (b.weight || 0) - (a.weight || 0));
  const finalScore = data.final_belief?.score ?? null;
  const finalTrust = data.final_belief?.trust ?? null;

  return (
    <div className="belief-funnel">
      {/* Layer 1: Final belief */}
      <div className="belief-funnel__layer belief-funnel__layer--final">
        <div className="belief-funnel__layer-label">{t("symbol.belief.finalBelief")}</div>
        <div className="belief-funnel__final-row">
          <div className="belief-funnel__score-block">
            <span className="belief-funnel__score-value">
              {finalScore !== null ? formatPercent(finalScore, 0) : "—"}
            </span>
            <span className="belief-funnel__score-label">{t("symbol.belief.beliefScore")}</span>
          </div>
          {finalTrust !== null && (
            <div className="belief-funnel__score-block">
              <span className="belief-funnel__score-value belief-funnel__score-value--trust">
                {formatPercent(finalTrust, 0)}
              </span>
              <span className="belief-funnel__score-label">{t("symbol.belief.trustScore")}</span>
            </div>
          )}
          {data.final_belief?.delta !== undefined && (
            <div className="belief-funnel__score-block">
              <span className={`belief-funnel__delta ${(data.final_belief.delta ?? 0) >= 0 ? "belief-funnel__delta--up" : "belief-funnel__delta--down"}`}>
                {(data.final_belief.delta ?? 0) >= 0 ? "▲" : "▼"} {formatPercent(Math.abs(data.final_belief.delta ?? 0), 2)}
              </span>
              <span className="belief-funnel__score-label">{t("symbol.belief.delta")}</span>
            </div>
          )}
        </div>
      </div>

      {/* Layer 2: Sub-beliefs */}
      {subBeliefs.length > 0 && (
        <div className="belief-funnel__layer belief-funnel__layer--sub">
          <div className="belief-funnel__layer-label">{t("symbol.belief.subBeliefs")}</div>
          <div className="belief-funnel__sub-grid">
            {subBeliefs.map((sub) => {
              const name = locale === "zh-CN" ? sub.name_zh : sub.name_en;
              const isSelected = selectedSub?.id === sub.id;
              return (
                <button
                  key={sub.id}
                  type="button"
                  className={`belief-sub-card${isSelected ? " is-selected" : ""}`}
                  onClick={() => setSelectedSub(isSelected ? null : sub)}
                >
                  <div className="belief-sub-card__name">{name || sub.id}</div>
                  <div className="belief-sub-card__score">
                    {sub.score !== undefined ? formatPercent(sub.score, 0) : "—"}
                  </div>
                  <div className="belief-sub-card__bar">
                    <div
                      className="belief-sub-card__bar-fill"
                      style={{ width: `${Math.max(2, (sub.score ?? 0) * 100)}%` }}
                    />
                  </div>
                  <div className="belief-sub-card__weight">
                    {t("symbol.belief.weight")} {formatPercent(sub.weight ?? 0, 0)}
                  </div>
                </button>
              );
            })}
          </div>

          {/* Node inspector */}
          {selectedSub && (
            <BeliefNodeInspector node={selectedSub} data={data} />
          )}
        </div>
      )}

      {subBeliefs.length === 0 && (
        <div className="note-card">{t("symbol.belief.noSubBeliefs")}</div>
      )}
    </div>
  );
}

// ── Waterfall view ───────────────────────────────────────────────────────────

function BeliefWaterfall({ data }: { data: BeliefGraphResponse }) {
  const { locale, t } = useI18n();
  const subBeliefs = (data.sub_beliefs || []).slice().sort((a, b) => (b.score || 0) - (a.score || 0));

  if (subBeliefs.length === 0) {
    return <div className="note-card">{t("symbol.belief.noSubBeliefs")}</div>;
  }

  const maxScore = Math.max(...subBeliefs.map((s) => s.score ?? 0), 0.01);

  return (
    <div className="belief-waterfall">
      <div className="belief-waterfall__label">{t("symbol.belief.contributionBreakdown")}</div>
      {subBeliefs.map((sub) => {
        const name = locale === "zh-CN" ? sub.name_zh : sub.name_en;
        const score = sub.score ?? 0;
        const contribution = score * (sub.weight ?? 0);
        const barWidth = (score / maxScore) * 100;
        return (
          <div key={sub.id} className="belief-waterfall__row">
            <div className="belief-waterfall__name">{name || sub.id}</div>
            <div className="belief-waterfall__bar-track">
              <div
                className={`belief-waterfall__bar-fill${score >= 0.5 ? " belief-waterfall__bar-fill--pos" : " belief-waterfall__bar-fill--neg"}`}
                style={{ width: `${barWidth}%` }}
              />
            </div>
            <div className="belief-waterfall__values">
              <span className="belief-waterfall__score">{formatPercent(score, 0)}</span>
              <span className="belief-waterfall__contribution">×{formatPercent(sub.weight ?? 0, 0)} = {formatPercent(contribution, 0)}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── Compare view (factors) ───────────────────────────────────────────────────

function BeliefCompare({ data }: { data: BeliefGraphResponse }) {
  const { t } = useI18n();
  const factors = (data.factors || []).slice().sort((a, b) => Math.abs(b.direction ?? 0) - Math.abs(a.direction ?? 0));

  if (factors.length === 0) {
    return <div className="note-card">{t("symbol.belief.noFactors")}</div>;
  }

  return (
    <div className="belief-compare">
      <div className="belief-compare__label">{t("symbol.belief.factorContributions")}</div>
      {factors.map((f, i) => {
        const dir = f.direction ?? 0;
        const isPos = dir >= 0;
        return (
          <div key={f.id || i} className="belief-compare__row">
            <div className="belief-compare__name">{f.name || f.id}</div>
            <div className="belief-compare__bar-track">
              <div className="belief-compare__bar-mid" />
              <div
                className={`belief-compare__bar-fill${isPos ? " belief-compare__bar-fill--pos" : " belief-compare__bar-fill--neg"}`}
                style={{
                  width: `${Math.abs(dir) * 50}%`,
                  [isPos ? "left" : "right"]: "50%",
                  position: "absolute",
                }}
              />
            </div>
            <div className={`belief-compare__dir${isPos ? " belief-compare__dir--pos" : " belief-compare__dir--neg"}`}>
              {dir >= 0 ? "+" : ""}{dir.toFixed(2)}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── Node inspector ───────────────────────────────────────────────────────────

function BeliefNodeInspector({ node, data }: { node: SubBeliefNode; data: BeliefGraphResponse }) {
  const { locale, t } = useI18n();
  const name = locale === "zh-CN" ? node.name_zh : node.name_en;

  // Find factors connected to this sub-belief
  const edges = (data.provenance_edges || []).filter((e) => e.to === node.id);
  const connectedFactorIds = new Set(edges.map((e) => e.from));
  const connectedFactors = (data.factors || []).filter((f) => connectedFactorIds.has(f.id));

  return (
    <div className="belief-node-inspector">
      <div className="belief-node-inspector__title">
        {name || node.id}
        <span className="belief-node-inspector__score">{formatPercent(node.score ?? 0, 0)}</span>
      </div>
      {connectedFactors.length > 0 ? (
        <div className="belief-node-inspector__factors">
          <div className="belief-node-inspector__factors-label">{t("symbol.belief.connectedFactors")}</div>
          {connectedFactors.map((f, i) => (
            <div key={f.id || i} className="belief-node-inspector__factor-row">
              <span className="belief-node-inspector__factor-name">{f.name || f.id}</span>
              <span className={`belief-node-inspector__factor-dir${(f.direction ?? 0) >= 0 ? " is-pos" : " is-neg"}`}>
                {(f.direction ?? 0) >= 0 ? "▲" : "▼"}
              </span>
              <span className="belief-node-inspector__factor-weight">{formatPercent(f.weight ?? 0, 1)}</span>
            </div>
          ))}
        </div>
      ) : (
        <div className="note-card">{t("symbol.belief.noConnectedFactors")}</div>
      )}
    </div>
  );
}

// ── Main export ──────────────────────────────────────────────────────────────

const VIEW_MODES: { id: ViewMode; labelKey: string }[] = [
  { id: "funnel", labelKey: "symbol.belief.viewFunnel" },
  { id: "waterfall", labelKey: "symbol.belief.viewWaterfall" },
  { id: "compare", labelKey: "symbol.belief.viewCompare" },
];

export function BeliefWorkspace({ data, loading }: Props) {
  const { t } = useI18n();
  const [viewMode, setViewMode] = useState<ViewMode>("funnel");

  if (loading && !data) {
    return <div className="belief-workspace belief-workspace--loading">{t("symbol.belief.loading")}</div>;
  }

  if (!data || (!data.final_belief && !data.sub_beliefs?.length && !data.history?.length)) {
    return (
      <div className="belief-workspace belief-workspace--empty">
        <div className="note-card">{t("symbol.belief.unavailable")}</div>
      </div>
    );
  }

  return (
    <div className="belief-workspace">
      <div className="belief-workspace__toolbar">
        {VIEW_MODES.map(({ id, labelKey }) => (
          <button
            key={id}
            type="button"
            className={`belief-workspace__view-btn${viewMode === id ? " is-active" : ""}`}
            onClick={() => setViewMode(id)}
          >
            {t(labelKey)}
          </button>
        ))}
      </div>

      <div className="belief-workspace__body">
        {viewMode === "funnel" && <BeliefFunnel data={data} />}
        {viewMode === "waterfall" && <BeliefWaterfall data={data} />}
        {viewMode === "compare" && <BeliefCompare data={data} />}
      </div>
    </div>
  );
}
