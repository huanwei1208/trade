import { useEffect, useState } from "react";

import { CompositeChart } from "../../components/observatory/CompositeChart";
import { DateEvidenceLens } from "../../components/observatory/DateEvidenceLens";
import { MarketSummary, WhatChanged, WhyNotFormal } from "../../components/observatory/OverviewPanels";
import { ResearchLens } from "../../components/observatory/ResearchLens";
import { RunsLineageLens } from "../../components/observatory/RunsLineageLens";
import { SnapshotContextBar } from "../../components/observatory/SnapshotContextBar";
import { TrustLens } from "../../components/observatory/TrustLens";
import type {
  ObsChannel,
  ObsCompositeSeries,
  ObsContext,
  ObsDateEvidence,
  ObsHypothesesPayload,
  ObsResearchRun,
  ObsRunsPayload,
  ObsSingleSeries,
  ObsTrust,
} from "../../lib/api";
import {
  fetchJson,
  observatoryDatePath,
  observatoryHypothesesPath,
  observatoryResearchRunPath,
  observatoryRunsPath,
  observatoryTrustPath,
  useApiResource,
  type ObsLens,
} from "../../lib/api";
import {
  observatoryContextPath,
  observatorySeriesPath,
} from "../../lib/api";
import { classNames } from "../../lib/ui";
import type { ObservatoryUrlState } from "../../lib/observatory";

type ObservatoryPageProps = {
  refreshToken: number;
  urlState: ObservatoryUrlState;
  onUrlStateChange: (next: Partial<ObservatoryUrlState>) => void;
};

const LENS_TABS: Array<{ key: ObsLens; label: string }> = [
  { key: "overview", label: "Overview" },
  { key: "trust", label: "Trust" },
  { key: "runs", label: "Runs & Lineage" },
  { key: "research", label: "Research" },
];

const RANGE_OPTIONS = ["30D", "90D", "1Y", "All"];

export function ObservatoryPage({ refreshToken, urlState, onUrlStateChange }: ObservatoryPageProps) {
  const knowledgeParam = urlState.knowledgeAsOf === "latest" ? undefined : urlState.knowledgeAsOf;

  // Context (Truth Bar). Channel-driven; always fetched.
  const contextResource = useApiResource<ObsContext>(
    observatoryContextPath({ channel: urlState.channel, knowledgeAsOf: knowledgeParam }),
    { deps: [refreshToken, urlState.channel, urlState.knowledgeAsOf], cacheKey: "obs:context" },
  );

  // Composite series for the main chart.
  const compositeResource = useApiResource<ObsCompositeSeries>(
    observatorySeriesPath({ view: "composite", knowledgeAsOf: knowledgeParam }),
    { deps: [refreshToken, urlState.knowledgeAsOf], cacheKey: "obs:composite" },
  );

  // Formal single-snapshot series feeds the market summary metrics.
  const formalSeriesResource = useApiResource<ObsSingleSeries>(
    observatorySeriesPath({ view: "formal", knowledgeAsOf: knowledgeParam }),
    { deps: [refreshToken, urlState.knowledgeAsOf], cacheKey: "obs:formal-series" },
  );

  const context = contextResource.data;
  const composite = compositeResource.data;

  return (
    <div className="obs-page" data-testid="observatory-page">
      <SnapshotContextBar context={context} loading={contextResource.loading} />

      <div className="obs-controls">
        <div className="tabs" role="tablist" aria-label="Observatory lens">
          {LENS_TABS.map((tab) => (
            <button
              key={tab.key}
              type="button"
              role="tab"
              aria-selected={urlState.lens === tab.key}
              className={classNames("tab", urlState.lens === tab.key && "active")}
              data-testid={`lens-tab-${tab.key}`}
              onClick={() => onUrlStateChange({ lens: tab.key })}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <div className="obs-controls__right">
          <label className="obs-select">
            <span>Channel</span>
            <select
              value={urlState.channel}
              onChange={(e) => onUrlStateChange({ channel: e.target.value as ObsChannel })}
              data-testid="channel-select"
            >
              <option value="observed">Latest observed</option>
              <option value="evaluated_candidate">Evaluated candidate</option>
              <option value="formal">Formal</option>
            </select>
          </label>
          <label className="obs-select">
            <span>Range</span>
            <select value={urlState.range} onChange={(e) => onUrlStateChange({ range: e.target.value })} data-testid="range-select">
              {RANGE_OPTIONS.map((r) => (
                <option key={r} value={r}>{r}</option>
              ))}
            </select>
          </label>
          <label className="obs-select">
            <span>Knowledge</span>
            <input
              type="text"
              value={urlState.knowledgeAsOf}
              onChange={(e) => onUrlStateChange({ knowledgeAsOf: e.target.value || "latest" })}
              placeholder="latest or YYYY-MM-DD"
              data-testid="knowledge-input"
              style={{ width: 150 }}
            />
          </label>
        </div>
      </div>

      {urlState.lens === "overview" && (
        <OverviewLens
          composite={composite}
          compositeLoading={compositeResource.loading}
          compositeError={compositeResource.error?.message ?? null}
          context={context}
          formalSeries={formalSeriesResource.data}
          range={urlState.range}
          selectedDate={urlState.date ?? null}
          channel={urlState.channel}
          refreshToken={refreshToken}
          onSelectDate={(date) => onUrlStateChange({ date })}
          onCloseDate={() => onUrlStateChange({ date: null })}
        />
      )}

      {urlState.lens === "trust" && (
        <TrustLensContainer
          channel={urlState.channel}
          composite={composite}
          refreshToken={refreshToken}
          onSelectDate={(date) => onUrlStateChange({ date, lens: "overview" })}
        />
      )}

      {urlState.lens === "runs" && (
        <RunsLensContainer
          refreshToken={refreshToken}
          selectedRunId={urlState.runId ?? null}
          compareRunId={urlState.compareRunId ?? null}
          onSelectRun={(runId) => onUrlStateChange({ runId })}
          onCompareRun={(compareRunId) => onUrlStateChange({ compareRunId })}
        />
      )}

      {urlState.lens === "research" && <ResearchLensContainer refreshToken={refreshToken} />}
    </div>
  );
}

// ── Overview lens (composite chart + panels + date evidence) ─────────────────

function OverviewLens({
  composite,
  compositeLoading,
  compositeError,
  context,
  formalSeries,
  range,
  selectedDate,
  channel,
  refreshToken,
  onSelectDate,
  onCloseDate,
}: {
  composite: ObsCompositeSeries | null | undefined;
  compositeLoading: boolean;
  compositeError: string | null;
  context: ObsContext | null | undefined;
  formalSeries: ObsSingleSeries | null | undefined;
  range: string;
  selectedDate: string | null;
  channel: ObsChannel;
  refreshToken: number;
  onSelectDate: (date: string) => void;
  onCloseDate: () => void;
}) {
  const [evidence, setEvidence] = useState<ObsDateEvidence | null>(null);
  const [evidenceLoading, setEvidenceLoading] = useState(false);
  const [evidenceError, setEvidenceError] = useState<string | null>(null);

  useEffect(() => {
    if (!selectedDate) {
      setEvidence(null);
      return;
    }
    let cancelled = false;
    setEvidenceLoading(true);
    setEvidenceError(null);
    fetchJson<ObsDateEvidence>(observatoryDatePath(selectedDate, { channel }))
      .then((d) => !cancelled && setEvidence(d))
      .catch((e) => !cancelled && setEvidenceError(e instanceof Error ? e.message : String(e)))
      .finally(() => !cancelled && setEvidenceLoading(false));
    return () => {
      cancelled = true;
    };
  }, [selectedDate, channel, refreshToken]);

  return (
    <div className="obs-overview">
      <section className="obs-chart-section">
        {compositeError ? (
          <div className="obs-error" data-testid="composite-error">{compositeError}</div>
        ) : compositeLoading && !composite ? (
          <div className="obs-empty">Loading composite series…</div>
        ) : (
          <CompositeChart composite={composite} range={range} selectedDate={selectedDate} onSelectDate={onSelectDate} />
        )}
      </section>

      <div className="obs-overview__panels">
        <MarketSummary formalSeries={formalSeries} context={context} />
        <WhyNotFormal context={context} />
        <WhatChanged composite={composite} />
      </div>

      <DateEvidenceLens
        date={selectedDate}
        channel={channel}
        evidence={evidence}
        loading={evidenceLoading}
        error={evidenceError}
        onClose={onCloseDate}
      />
    </div>
  );
}

// ── Trust lens container ─────────────────────────────────────────────────────

function TrustLensContainer({
  channel,
  composite,
  refreshToken,
  onSelectDate,
}: {
  channel: ObsChannel;
  composite: ObsCompositeSeries | null | undefined;
  refreshToken: number;
  onSelectDate: (date: string) => void;
}) {
  const trustResource = useApiResource<ObsTrust>(observatoryTrustPath({ channel }), {
    deps: [refreshToken, channel],
    cacheKey: "obs:trust",
  });
  return (
    <TrustLens
      trust={trustResource.data}
      composite={composite}
      loading={trustResource.loading}
      error={trustResource.error?.message ?? null}
      onSelectDate={onSelectDate}
    />
  );
}

// ── Runs lens container ──────────────────────────────────────────────────────

function RunsLensContainer({
  refreshToken,
  selectedRunId,
  compareRunId,
  onSelectRun,
  onCompareRun,
}: {
  refreshToken: number;
  selectedRunId: string | null;
  compareRunId: string | null;
  onSelectRun: (runId: string | null) => void;
  onCompareRun: (runId: string | null) => void;
}) {
  const runsResource = useApiResource<ObsRunsPayload>(observatoryRunsPath({ limit: 100 }), {
    deps: [refreshToken],
    cacheKey: "obs:runs",
  });
  return (
    <RunsLineageLens
      runs={runsResource.data}
      loading={runsResource.loading}
      error={runsResource.error?.message ?? null}
      selectedRunId={selectedRunId}
      compareRunId={compareRunId}
      onSelectRun={onSelectRun}
      onCompareRun={onCompareRun}
    />
  );
}

// ── Research lens container ──────────────────────────────────────────────────

function ResearchLensContainer({ refreshToken }: { refreshToken: number }) {
  const hypothesesResource = useApiResource<ObsHypothesesPayload>(observatoryHypothesesPath(), {
    deps: [refreshToken],
    cacheKey: "obs:hypotheses",
  });
  const hypothesis = hypothesesResource.data?.hypotheses?.[0];
  const researchRunId = hypothesis?.current_research_run_id ?? null;

  const [researchRun, setResearchRun] = useState<ObsResearchRun | null>(null);
  const [runError, setRunError] = useState<string | null>(null);

  useEffect(() => {
    if (!researchRunId) {
      setResearchRun(null);
      return;
    }
    let cancelled = false;
    setRunError(null);
    fetchJson<ObsResearchRun>(observatoryResearchRunPath(researchRunId))
      .then((d) => !cancelled && setResearchRun(d))
      .catch((e) => !cancelled && setRunError(e instanceof Error ? e.message : String(e)));
    return () => {
      cancelled = true;
    };
  }, [researchRunId, refreshToken]);

  return (
    <ResearchLens
      hypothesis={hypothesis}
      researchRun={researchRun}
      loading={hypothesesResource.loading}
      error={hypothesesResource.error?.message ?? runError}
    />
  );
}
