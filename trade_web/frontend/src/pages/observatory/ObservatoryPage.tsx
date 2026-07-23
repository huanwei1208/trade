import { useEffect, useRef, useState } from "react";

import { ObservatoryErrorState } from "../../components/observatory/ObservatoryErrorState";
import { ResearchLens } from "../../components/observatory/ResearchLens";
import { RunsLineageLens } from "../../components/observatory/RunsLineageLens";
import { SnapshotContextBar } from "../../components/observatory/SnapshotContextBar";
import { TrustLens } from "../../components/observatory/TrustLens";
import type {
  ObsChannel,
  ObsCompositeSeries,
  ObsContext,
  ObsDateEvidence,
  ObsHypothesis,
  ObsHypothesesPayload,
  ObsResearchRun,
  ObsRunDetail,
  ObsRunDiff,
  ObsRunsPayload,
  ObsSingleSeries,
  ObsTrust,
} from "../../lib/api";
import {
  observatoryDatePath,
  observatoryHypothesesPath,
  observatoryResearchRunPath,
  observatoryRunDetailPath,
  observatoryRunDiffPath,
  observatoryRunsPath,
  observatoryTrustPath,
  type ObsLens,
} from "../../lib/api";
import { observatoryContextPath, observatorySeriesPath } from "../../lib/api";
import { classNames } from "../../lib/ui";
import {
  compositeLayerForChannel,
  observatoryWindowBounds,
  type ObservatorySafeError,
  type ObservatoryUrlState,
  type ObservatoryWindowBounds,
} from "../../lib/observatory";
import { MarketWorkspace } from "./MarketWorkspace";
import {
  parseObservatoryError,
  useObservatoryResource,
  type ObservatoryValidationFailure,
  type ObservatoryResourceState,
} from "./observatoryResource";

type ObservatoryPageProps = {
  refreshToken: number;
  urlState: ObservatoryUrlState;
  onUrlStateChange: (next: Partial<ObservatoryUrlState>) => void;
};

type ObservatoryPageResource<T> = ObservatoryResourceState<T> & {
  loading: boolean;
  retry: () => void;
};

const LENS_TABS: Array<{ key: ObsLens; label: string }> = [
  { key: "overview", label: "Market" },
  { key: "trust", label: "Assurance / Gates" },
  { key: "runs", label: "Assurance / Run lineage" },
  { key: "research", label: "Research" },
];

const OBSERVATORY_FULL_RANGE = "All";

const RESEARCH_STATES = new Set([
  "exploratory",
  "eligible",
  "candidate",
  "monitoring",
  "validated",
  "rejected",
  "blocked",
  "unknown",
]);

function identityMismatch(
  message = "The response did not match the active Observatory selection.",
): ObservatoryValidationFailure {
  return {
    message,
    reasonCodes: ["RESPONSE_IDENTITY_MISMATCH"],
    retryable: true,
  };
}

function hasNonEmptyText(value: string | null | undefined): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function hasEvidenceReferences(value: string[] | null | undefined): boolean {
  return Array.isArray(value) && value.some((reference) => hasNonEmptyText(reference));
}

function validateContext(
  context: ObsContext,
  channel: ObsChannel,
  knowledgeAsOf: string,
): true | ObservatoryValidationFailure {
  const contextKnowledgeAsOf =
    context.requested_knowledge_as_of === null ? "latest" : context.requested_knowledge_as_of;
  if (
    context.resolved_channel !== channel ||
    !context.snapshot_id ||
    contextKnowledgeAsOf !== knowledgeAsOf
  ) {
    return identityMismatch(
      "The resolved market Context did not match the committed knowledge selector.",
    );
  }
  return true;
}

function validateResearchRun(
  researchRun: ObsResearchRun,
  hypothesis: ObsHypothesis | null,
): true | ObservatoryValidationFailure {
  if (!hasNonEmptyText(hypothesis?.hypothesis_version)) {
    return {
      message: "The selected H1 hypothesis does not provide an immutable version identity.",
      reasonCodes: ["H1_RESEARCH_VERSION_UNAVAILABLE"],
      retryable: false,
    };
  }
  if (!hasNonEmptyText(researchRun.hypothesis_version)) {
    return {
      message: "The current H1 research receipt does not provide a version identity.",
      reasonCodes: ["H1_RESEARCH_VERSION_UNAVAILABLE"],
      retryable: false,
    };
  }
  if (
    researchRun.hypothesis_id !== "H1" ||
    researchRun.research_run_id !== hypothesis?.current_research_run_id ||
    researchRun.is_current !== true ||
    researchRun.hypothesis_version !== hypothesis.hypothesis_version
  ) {
    return identityMismatch();
  }
  if (!hasNonEmptyText(researchRun.research_state)) {
    return {
      message: "The current H1 research receipt does not provide a research state.",
      reasonCodes: ["H1_RESEARCH_STATE_UNAVAILABLE"],
      retryable: false,
    };
  }
  if (!RESEARCH_STATES.has(researchRun.research_state.trim())) {
    return {
      message: "The current H1 research receipt has an unrecognized research state.",
      reasonCodes: ["H1_RESEARCH_STATE_UNAVAILABLE"],
      retryable: false,
    };
  }
  if (!hasNonEmptyText(researchRun.dataset_snapshot_id)) {
    return {
      message: "The current H1 research receipt does not provide a dataset snapshot identity.",
      reasonCodes: ["H1_RESEARCH_SNAPSHOT_UNAVAILABLE"],
      retryable: false,
    };
  }
  if (!hasNonEmptyText(researchRun.knowledge_as_of)) {
    return {
      message: "The current H1 research receipt does not provide a knowledge cutoff.",
      reasonCodes: ["H1_RESEARCH_KNOWLEDGE_UNAVAILABLE"],
      retryable: false,
    };
  }
  if (!hasEvidenceReferences(researchRun.evidence_refs)) {
    return {
      message: "The current H1 research receipt does not provide evidence references.",
      reasonCodes: ["H1_RESEARCH_EVIDENCE_UNAVAILABLE"],
      retryable: false,
    };
  }
  return true;
}

function validateSelectedSeries(
  series: ObsSingleSeries,
  channel: ObsChannel,
  snapshotId: string,
): true | ObservatoryValidationFailure {
  if (series.view !== channel || series.context?.snapshot_id !== snapshotId) {
    return identityMismatch();
  }
  if (series.pit_valid !== true) {
    return {
      message: "The selected market series is not point-in-time valid for this evidence selection.",
      reasonCodes: series.reason_codes?.length ? series.reason_codes : ["PIT_NOT_VALID"],
      retryable: false,
    };
  }
  return true;
}

function validateComposite(
  series: ObsCompositeSeries,
  channel: ObsChannel,
  snapshotId: string,
): true | ObservatoryValidationFailure {
  if (series.view !== "composite") {
    return identityMismatch();
  }
  const layer = series.layers?.[compositeLayerForChannel(channel)];
  if (layer?.context?.snapshot_id !== snapshotId) {
    return identityMismatch(
      "The selected composite layer did not match the resolved market snapshot.",
    );
  }
  return true;
}

function windowUnavailableError(
  windowBounds: ObservatoryWindowBounds,
): ObservatorySafeError | null {
  if (windowBounds.kind !== "unavailable") {
    return null;
  }
  return {
    message:
      "The selected market range cannot be loaded because its resolved market watermark is unavailable.",
    reasonCodes: windowBounds.reasonCodes,
    evidenceRefs: [],
    retryable: true,
  };
}

export function ObservatoryPage({
  refreshToken,
  urlState,
  onUrlStateChange,
}: ObservatoryPageProps) {
  const committedKnowledgeAsOf = urlState.knowledgeAsOf.trim() || "latest";
  const knowledgeParam = committedKnowledgeAsOf === "latest" ? undefined : committedKnowledgeAsOf;
  const historicalCompositeUnavailable = committedKnowledgeAsOf !== "latest";
  const marketOverview = urlState.lens === "overview" && urlState.chartMode === "market";
  const compareOverview = urlState.lens === "overview" && urlState.chartMode === "compare";
  const needsSelectedSeries = marketOverview || urlState.lens === "trust";
  const needsSnapshotContext = urlState.lens === "overview" || urlState.lens === "trust";
  const contextResource = useObservatoryResource<ObsContext>(
    needsSnapshotContext
      ? observatoryContextPath({ channel: urlState.channel, knowledgeAsOf: knowledgeParam })
      : null,
    {
      reloadKey: refreshToken,
      validateResponse: (context) =>
        validateContext(context, urlState.channel, committedKnowledgeAsOf),
    },
  );
  const context = confirmedData(contextResource);
  const snapshotId = context?.snapshot_id ?? null;
  const windowBounds = observatoryWindowBounds(context?.market_watermark, OBSERVATORY_FULL_RANGE);
  const windowError = windowUnavailableError(windowBounds);

  const selectedSeriesResource = useObservatoryResource<ObsSingleSeries>(
    needsSelectedSeries && snapshotId && !windowError
      ? observatorySeriesPath({
          view: urlState.channel,
          snapshotId,
        })
      : null,
    {
      reloadKey: refreshToken,
      validationKey: snapshotId ? `${urlState.channel}:${snapshotId}` : null,
      validateResponse: (series) =>
        snapshotId
          ? validateSelectedSeries(series, urlState.channel, snapshotId)
          : identityMismatch(),
    },
  );
  const selectedSeriesConfirmed = selectedSeriesResource.status === "confirmed";
  const compositeResource = useObservatoryResource<ObsCompositeSeries>(
    compareOverview && context && !windowError && !historicalCompositeUnavailable
      ? observatorySeriesPath({
          view: "composite",
          knowledgeAsOf: knowledgeParam,
        })
      : null,
    {
      reloadKey: refreshToken,
      validationKey: snapshotId ? `${urlState.channel}:${snapshotId}` : null,
      validateResponse: (series) =>
        snapshotId ? validateComposite(series, urlState.channel, snapshotId) : identityMismatch(),
    },
  );
  const trustResource = useObservatoryResource<ObsTrust>(
    urlState.lens === "trust" && snapshotId && !windowError && selectedSeriesConfirmed
      ? observatoryTrustPath({ channel: urlState.channel, snapshotId })
      : null,
    {
      reloadKey: refreshToken,
      validateResponse: (trust) => trust.snapshot_id === snapshotId,
    },
  );
  const dateEvidenceResource = useObservatoryResource<ObsDateEvidence>(
    urlState.lens === "overview" && snapshotId && urlState.date && !windowError
      ? observatoryDatePath(urlState.date, { channel: urlState.channel, snapshotId })
      : null,
    {
      reloadKey: refreshToken,
      validateResponse: (evidence) =>
        evidence.snapshot_id === snapshotId && evidence.date === urlState.date,
    },
  );
  const runsResource = useObservatoryResource<ObsRunsPayload>(
    urlState.lens === "runs" ? observatoryRunsPath({ limit: 50 }) : null,
    { reloadKey: refreshToken },
  );
  const detailResource = useObservatoryResource<ObsRunDetail>(
    urlState.lens === "runs" && urlState.runId ? observatoryRunDetailPath(urlState.runId) : null,
    {
      reloadKey: refreshToken,
      validateResponse: (detail) => detail.run_id === urlState.runId,
    },
  );
  const diffResource = useObservatoryResource<ObsRunDiff>(
    urlState.lens === "runs" && urlState.runId && urlState.compareRunId
      ? observatoryRunDiffPath(urlState.runId, urlState.compareRunId)
      : null,
    {
      reloadKey: refreshToken,
      validateResponse: (diff) =>
        diff.base?.run_id === urlState.runId && diff.compare?.run_id === urlState.compareRunId,
    },
  );
  const hypothesesResource = useObservatoryResource<ObsHypothesesPayload>(
    urlState.lens === "research" ? observatoryHypothesesPath() : null,
    { reloadKey: refreshToken },
  );
  const h1 =
    confirmedData(hypothesesResource)?.hypotheses?.find(
      (hypothesis) => hypothesis.hypothesis_id === "H1",
    ) ?? null;
  const h1RunId = h1?.current_research_run_id;
  const h1Version = h1?.hypothesis_version;
  const hypothesesRefreshConfirmed = hypothesesResource.confirmedReloadKey === refreshToken;
  const researchRunReloadKey = `${hypothesesResource.confirmedReloadKey ?? ""}:${h1RunId ?? ""}:${h1Version ?? ""}`;
  const researchRunResource = useObservatoryResource<ObsResearchRun>(
    urlState.lens === "research" &&
      hypothesesRefreshConfirmed &&
      hasNonEmptyText(h1RunId) &&
      hasNonEmptyText(h1Version)
      ? observatoryResearchRunPath(h1RunId)
      : null,
    {
      reloadKey: researchRunReloadKey,
      validateResponse: (researchRun) => validateResearchRun(researchRun, h1),
    },
  );
  const researchRunRefreshConfirmed =
    researchRunResource.confirmedReloadKey === researchRunReloadKey;
  const [knowledgeDraft, setKnowledgeDraft] = useState(urlState.knowledgeAsOf);
  const dateInspectorRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setKnowledgeDraft(urlState.knowledgeAsOf);
  }, [urlState.knowledgeAsOf]);

  function commitKnowledge() {
    const nextKnowledge = knowledgeDraft.trim() || "latest";
    if (nextKnowledge !== urlState.knowledgeAsOf) {
      onUrlStateChange({ knowledgeAsOf: nextKnowledge, date: null });
    }
  }

  function closeDateEvidence() {
    onUrlStateChange({ date: null });
    window.requestAnimationFrame(() => dateInspectorRef.current?.focus());
  }

  return (
    <div className="obs-page" data-testid="observatory-page">
      <div className="obs-controls">
        <div className="tabs" role="group" aria-label="Observatory lens">
          {LENS_TABS.map((tab) => (
            <button
              key={tab.key}
              type="button"
              aria-pressed={urlState.lens === tab.key}
              className={classNames("tab", urlState.lens === tab.key && "active")}
              data-testid={`lens-tab-${tab.key}`}
              onClick={() => onUrlStateChange({ lens: tab.key })}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {(urlState.lens === "overview" || urlState.lens === "trust") && (
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
                <option value="formal">Published baseline</option>
              </select>
            </label>
            {urlState.lens === "overview" ? (
              <label className="obs-select">
                <span>Knowledge</span>
                <input
                  type="text"
                  value={knowledgeDraft}
                  onChange={(event) => setKnowledgeDraft(event.target.value)}
                  onBlur={commitKnowledge}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.currentTarget.blur();
                    }
                  }}
                  placeholder="latest or YYYY-MM-DD"
                  data-testid="knowledge-input"
                  style={{ width: 150 }}
                />
              </label>
            ) : null}
          </div>
        )}
      </div>

      {urlState.lens === "overview" && (
        <MarketWorkspace
          contextResource={contextResource}
          chartMode={urlState.chartMode}
          selectedSeriesResource={selectedSeriesResource}
          compositeResource={compositeResource}
          dateEvidenceResource={dateEvidenceResource}
          timeframe={urlState.timeframe}
          selectedDate={urlState.date ?? null}
          channel={urlState.channel}
          windowBounds={windowBounds}
          windowError={windowError}
          historicalCompositeUnavailable={historicalCompositeUnavailable}
          dateInspectorRef={dateInspectorRef}
          onChartModeChange={(chartMode) => onUrlStateChange({ chartMode })}
          onTimeframeChange={(timeframe) => onUrlStateChange({ timeframe })}
          onSelectDate={(date) => onUrlStateChange({ date })}
          onCloseDate={closeDateEvidence}
        />
      )}

      {urlState.lens === "trust" && (
        <AssuranceGatesWorkspace
          contextResource={contextResource}
          selectedSeriesResource={selectedSeriesResource}
          trustResource={trustResource}
          windowError={windowError}
          onSelectDate={(date) => onUrlStateChange({ date, lens: "overview" })}
        />
      )}

      {urlState.lens === "runs" && (
        <RunLineageWorkspace
          runsResource={runsResource}
          detailResource={detailResource}
          diffResource={diffResource}
          selectedRunId={urlState.runId ?? null}
          compareRunId={urlState.compareRunId ?? null}
          onSelectRun={(runId) => onUrlStateChange({ runId })}
          onCompareRun={(compareRunId) => onUrlStateChange({ compareRunId })}
        />
      )}

      {urlState.lens === "research" && (
        <ResearchWorkspace
          hypothesesResource={hypothesesResource}
          researchRunResource={researchRunResource}
          hypothesis={h1}
          hypothesesRefreshConfirmed={hypothesesRefreshConfirmed}
          researchRunRefreshConfirmed={researchRunRefreshConfirmed}
        />
      )}
    </div>
  );
}

function confirmedData<T>(resource: ObservatoryResourceState<T>): T | null {
  return resource.status === "confirmed" ? resource.data : null;
}

function AssuranceGatesWorkspace({
  contextResource,
  selectedSeriesResource,
  trustResource,
  windowError,
  onSelectDate,
}: {
  contextResource: ObservatoryPageResource<ObsContext>;
  selectedSeriesResource: ObservatoryPageResource<ObsSingleSeries>;
  trustResource: ObservatoryPageResource<ObsTrust>;
  windowError: ObservatorySafeError | null;
  onSelectDate: (date: string) => void;
}) {
  const context = confirmedData(contextResource);
  const selectedSeries = confirmedData(selectedSeriesResource);
  const trust = confirmedData(trustResource);
  const contextError = parseObservatoryError(contextResource.error);
  const selectedSeriesError = parseObservatoryError(selectedSeriesResource.error);
  const trustError = parseObservatoryError(trustResource.error);
  const selectedSeriesUnavailable =
    Boolean(windowError) ||
    selectedSeriesResource.status === "failed" ||
    selectedSeriesResource.status === "unavailable";
  const selectedSeriesPending =
    selectedSeriesResource.status === "idle" || selectedSeriesResource.loading;

  if (contextResource.status !== "confirmed") {
    return (
      <div className="obs-assurance-workspace">
        <SnapshotContextBar
          context={context}
          status={contextResource.status}
          error={contextError}
          onRetry={contextResource.retry}
        />
        <div className="obs-dependent-blocked" role="status">
          Coverage and gate evidence remain blocked until the selected snapshot is confirmed.
        </div>
      </div>
    );
  }

  return (
    <div className="obs-assurance-workspace">
      <SnapshotContextBar
        context={context}
        status={contextResource.status}
        error={contextError}
        onRetry={contextResource.retry}
      />
      {selectedSeriesUnavailable ? (
        <ObservatoryErrorState
          title="Coverage evidence unavailable"
          error={windowError ?? selectedSeriesError}
          unavailable={Boolean(windowError) || selectedSeriesResource.status === "unavailable"}
          onRetry={windowError ? contextResource.retry : selectedSeriesResource.retry}
        />
      ) : null}
      {trustResource.status === "failed" || trustResource.status === "unavailable" ? (
        <ObservatoryErrorState
          title="Snapshot gate evidence unavailable"
          error={trustError}
          unavailable={trustResource.status === "unavailable"}
          onRetry={trustResource.retry}
        />
      ) : null}
      <TrustLens
        trust={trust}
        series={selectedSeries}
        coverageLoading={selectedSeriesPending}
        loading={trustResource.loading || selectedSeriesPending}
        error={windowError ?? (selectedSeriesUnavailable ? selectedSeriesError : trustError)}
        coverageUnavailable={selectedSeriesUnavailable}
        excludedDates={context?.excluded_dates}
        onRetry={
          windowError
            ? contextResource.retry
            : selectedSeriesUnavailable
              ? selectedSeriesResource.retry
              : trustResource.retry
        }
        onSelectDate={onSelectDate}
      />
    </div>
  );
}

function RunLineageWorkspace({
  runsResource,
  detailResource,
  diffResource,
  selectedRunId,
  compareRunId,
  onSelectRun,
  onCompareRun,
}: {
  runsResource: ObservatoryPageResource<ObsRunsPayload>;
  detailResource: ObservatoryPageResource<ObsRunDetail>;
  diffResource: ObservatoryPageResource<ObsRunDiff>;
  selectedRunId: string | null;
  compareRunId: string | null;
  onSelectRun: (runId: string | null) => void;
  onCompareRun: (runId: string | null) => void;
}) {
  return (
    <div className="obs-runs-workspace">
      <WorkspaceScope
        title="Assurance / Run lineage"
        detail="Catalog-wide immutable run evidence. It is separately scoped and does not confirm the selected Market snapshot."
      />
      <RunsLineageLens
        runs={confirmedData(runsResource)}
        loading={runsResource.loading}
        error={parseObservatoryError(runsResource.error)}
        onRetry={runsResource.retry}
        detail={confirmedData(detailResource)}
        detailLoading={detailResource.loading}
        detailError={parseObservatoryError(detailResource.error)}
        onDetailRetry={detailResource.retry}
        diff={confirmedData(diffResource)}
        diffLoading={diffResource.loading}
        diffError={parseObservatoryError(diffResource.error)}
        onDiffRetry={diffResource.retry}
        selectedRunId={selectedRunId}
        compareRunId={compareRunId}
        onSelectRun={onSelectRun}
        onCompareRun={onCompareRun}
      />
    </div>
  );
}

function ResearchWorkspace({
  hypothesesResource,
  researchRunResource,
  hypothesis,
  hypothesesRefreshConfirmed,
  researchRunRefreshConfirmed,
}: {
  hypothesesResource: ObservatoryPageResource<ObsHypothesesPayload>;
  researchRunResource: ObservatoryPageResource<ObsResearchRun>;
  hypothesis: ObsHypothesis | null;
  hypothesesRefreshConfirmed: boolean;
  researchRunRefreshConfirmed: boolean;
}) {
  const noH1 = hypothesesResource.status === "confirmed" && !hypothesis;
  const hypothesesError = parseObservatoryError(hypothesesResource.error);
  const researchRunError = parseObservatoryError(researchRunResource.error);
  const missingH1Run = hypothesis !== null && !hasNonEmptyText(hypothesis.current_research_run_id);
  const missingH1Version = hypothesis !== null && !hasNonEmptyText(hypothesis.hypothesis_version);
  const confirmedResearchRun = confirmedData(researchRunResource);
  const researchRunConfirmed =
    hypothesesRefreshConfirmed &&
    researchRunRefreshConfirmed &&
    confirmedResearchRun !== null &&
    validateResearchRun(confirmedResearchRun, hypothesis) === true;
  const unavailable =
    noH1 ||
    missingH1Run ||
    missingH1Version ||
    hypothesesResource.status === "failed" ||
    hypothesesResource.status === "unavailable" ||
    researchRunResource.status === "failed" ||
    researchRunResource.status === "unavailable";
  return (
    <div className="obs-research-workspace">
      <WorkspaceScope
        title="Research"
        detail="H1 is rendered as separately scoped descriptive evidence. This workspace does not provide investment recommendations."
      />
      {unavailable ? (
        <ObservatoryErrorState
          title="H1 research evidence unavailable"
          error={
            hypothesesError ??
            researchRunError ??
            (noH1
              ? {
                  message:
                    "The available research hypotheses do not include the required H1 evidence.",
                  reasonCodes: ["H1_RESEARCH_HYPOTHESIS_UNAVAILABLE"],
                  evidenceRefs: [],
                  retryable: false,
                }
              : missingH1Run
                ? {
                    message:
                      "The selected H1 hypothesis has no current immutable research run to display.",
                    reasonCodes: ["H1_RESEARCH_RUN_UNAVAILABLE"],
                    evidenceRefs: [],
                    retryable: false,
                  }
                : missingH1Version
                  ? {
                      message:
                        "The selected H1 hypothesis has no immutable version identity to match with a research receipt.",
                      reasonCodes: ["H1_RESEARCH_VERSION_UNAVAILABLE"],
                      evidenceRefs: [],
                      retryable: false,
                    }
                  : null)
          }
          unavailable
          onRetry={
            noH1 ||
            hypothesesResource.status === "failed" ||
            hypothesesResource.status === "unavailable"
              ? hypothesesResource.retry
              : researchRunResource.retry
          }
        />
      ) : hypothesis && researchRunConfirmed ? (
        <ResearchLens
          hypothesis={hypothesis}
          researchRun={confirmedResearchRun}
          loading={hypothesesResource.loading || researchRunResource.loading}
          error={null}
        />
      ) : (
        <div className="obs-empty" role="status">
          Loading H1 research evidence…
        </div>
      )}
    </div>
  );
}

function WorkspaceScope({ title, detail }: { title: string; detail: string }) {
  return (
    <section className="obs-workspace-scope" aria-label={title}>
      <h2>{title}</h2>
      <p>{detail}</p>
    </section>
  );
}
