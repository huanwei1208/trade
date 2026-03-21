import { useEffect, useMemo, useRef, useState } from "react";

import { BackfillActionPanel } from "../components/BackfillActionPanel";
import { ComputeLayersView } from "../components/ComputeLayersView";
import { ComputeNodeInspector } from "../components/ComputeNodeInspector";
import { ErrorState } from "../components/ErrorState";
import { ExecutionRunCard } from "../components/ExecutionRunCard";
import { LoadingSkeleton } from "../components/LoadingSkeleton";
import { OpsLayerFilterBar } from "../components/OpsLayerFilterBar";
import { PanelCard } from "../components/PanelCard";
import { ReadinessHeatmap, type ReadinessRowMeta } from "../components/ReadinessHeatmap";
import { ReadinessInspector } from "../components/ReadinessInspector";
import { ReadinessSummaryCards } from "../components/ReadinessSummaryCards";
import { RecoveryTimeline } from "../components/RecoveryTimeline";
import { ReplayBuilder } from "../components/ReplayBuilder";
import { SectionHeader } from "../components/SectionHeader";
import { StatusPill } from "../components/StatusPill";
import {
  fetchJson,
  getOpsDependencyPath,
  getOpsNodeResult,
  getReadinessHistory,
  getReadinessReplayPlan,
  getWorkflowDetail,
  isTerminalRecoveryStatus,
  isTerminalWorkflowStatus,
  postOpsReplayExecute,
  postOpsReplayPreview,
  postReadinessBackfill,
  postReadinessDetectChanges,
  postReadinessReplay,
  type DagRuntime,
  type EventsPagePayload,
  type OpsComputeLayersPayload,
  type OpsDependencyPathPayload,
  type OpsNodeResultPayload,
  type OpsReplayAction,
  type OpsReplayMode,
  type ReadinessActionDetail,
  type ReadinessCell,
  type ReadinessGridPayload,
  type ReadinessHistoryPayload,
  type ReadinessRow,
  type ReplayPlanPayload,
  type StatusPayload,
  type TrustOverview,
  type WorkflowDetailPayload,
  type WorkflowSummary,
  useApiResource,
} from "../lib/api";
import { formatDateTime, formatPercent, shortText } from "../lib/format";
import { useI18n } from "../lib/i18n";
import {
  getDatasetText,
  getGateStatusText,
  getOpsNodeTypeText,
} from "../lib/statusText";
import { useLocalStorageState } from "../lib/ui";

type OpsTab = "overview" | "readiness" | "compute" | "replay" | "trust" | "audit";
type OpsTabLike = OpsTab | "recovery" | "pipeline" | "workflows";

type OpsPageProps = {
  refreshToken: number;
  focus?: {
    tab?: OpsTabLike;
    date?: string;
    dataset?: string;
  };
  onFocusChange?: (focus: { tab?: OpsTab; date?: string; dataset?: string }) => void;
};

type SelectionMode = "cell" | "node" | "subtree";
type OpsStatusFilter = "all" | "healthy" | "degraded" | "broken" | "stale" | "partial";

export function OpsPage({ refreshToken, focus, onFocusChange }: OpsPageProps) {
  const { locale, t } = useI18n();
  const [storedTab, setStoredTab] = useLocalStorageState<OpsTabLike>("trade-web:ops-tab", "readiness");
  const tab = normalizeOpsTab(storedTab);

  const [readinessDays, setReadinessDays] = useState<30 | 60 | 90>(30);
  const [activeCellId, setActiveCellId] = useState("");
  const [selectedCellIds, setSelectedCellIds] = useState<string[]>([]);
  const [activeNodeId, setActiveNodeId] = useState("");
  const [selectedNodeIds, setSelectedNodeIds] = useState<string[]>([]);
  const [selectionMode, setSelectionMode] = useState<SelectionMode>("cell");
  const [replayMode, setReplayMode] = useState<OpsReplayMode>("selected_plus_downstream");
  const [actionMode, setActionMode] = useState<OpsReplayAction>("recompute");
  const [typeFilter, setTypeFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState<OpsStatusFilter>("all");
  const [collapsedReadinessGroups, setCollapsedReadinessGroups] = useState<Record<string, boolean>>({});
  const [collapsedComputeGroups, setCollapsedComputeGroups] = useState<Record<string, boolean>>({});
  const [range, setRange] = useState({ dateFrom: "", dateTo: "" });
  const [recoveryPlan, setRecoveryPlan] = useState<ReplayPlanPayload | null>(null);
  const [recoveryBusy, setRecoveryBusy] = useState(false);
  const [recoveryError, setRecoveryError] = useState<string | null>(null);
  const [recoverySuccess, setRecoverySuccess] = useState<string | null>(null);
  const [changeDetected, setChangeDetected] = useState<boolean | null>(null);
  const [historyPayload, setHistoryPayload] = useState<ReadinessHistoryPayload | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [historyVersion, setHistoryVersion] = useState(0);
  const [nodeResult, setNodeResult] = useState<OpsNodeResultPayload | null>(null);
  const [nodeLoading, setNodeLoading] = useState(false);
  const [nodeError, setNodeError] = useState<string | null>(null);
  const [dependencyPath, setDependencyPath] = useState<OpsDependencyPathPayload | null>(null);
  const [workflowDetail, setWorkflowDetail] = useState<WorkflowDetailPayload | null>(null);
  const [workflowLoading, setWorkflowLoading] = useState(false);
  const [workflowError, setWorkflowError] = useState<string | null>(null);
  const [currentWorkflowId, setCurrentWorkflowId] = useState<number | null>(null);
  const [replayPreview, setReplayPreview] = useState<Awaited<ReturnType<typeof postOpsReplayPreview>> | null>(null);
  const terminalRefreshKeyRef = useRef("");

  const status = useApiResource<StatusPayload>("/api/status", { deps: [refreshToken], cacheKey: "trade-web:status" });
  const runtime = useApiResource<DagRuntime>("/api/dag/runtime", { deps: [refreshToken], cacheKey: "trade-web:dag-runtime" });
  const trust = useApiResource<TrustOverview>("/api/trust/overview", { deps: [refreshToken], cacheKey: "trade-web:trust-overview" });
  const workflows = useApiResource<WorkflowSummary[]>("/api/workflows", { deps: [refreshToken], cacheKey: "trade-web:workflows" });
  const events = useApiResource<EventsPagePayload>("/api/events-page", { deps: [refreshToken], cacheKey: "trade-web:events-page" });
  const readiness = useApiResource<ReadinessGridPayload>(`/api/readiness-grid?days=${readinessDays}`, {
    deps: [refreshToken, readinessDays],
    cacheKey: `trade-web:readiness-grid:${readinessDays}`,
  });
  const computeDate = focus?.date || "";
  const compute = useApiResource<OpsComputeLayersPayload>(computeDate ? `/api/ops/compute-layers?date=${computeDate}` : "/api/ops/compute-layers", {
    deps: [refreshToken, computeDate],
    cacheKey: `trade-web:ops-compute:${computeDate || "latest"}`,
  });

  const rowMetaByDataset = useMemo(() => buildReadinessRowMeta(compute.data?.nodes || []), [compute.data?.nodes]);
  const computeNodes = compute.data?.nodes || [];
  const filteredReadinessRows = useMemo(
    () => filterReadinessRows(readiness.data?.rows || [], rowMetaByDataset, typeFilter, statusFilter),
    [readiness.data?.rows, rowMetaByDataset, statusFilter, typeFilter],
  );
  const filteredComputePayload = useMemo(
    () => filterComputePayload(compute.data, typeFilter, statusFilter),
    [compute.data, statusFilter, typeFilter],
  );

  const selectedReadiness = findSelectedReadiness(readiness.data?.rows || [], activeCellId);
  const selectedDataset = selectedReadiness.row?.dataset || "";
  const selectedDate = selectedReadiness.cell?.date || "";
  const selectedCellChanged = selectedReadiness.cell?.changed_since_last_ready;
  const selectedNodeMeta = rowMetaByDataset[selectedDataset] || null;
  const selectedCellPayloads = useMemo(
    () => collectSelectedCells(readiness.data?.rows || [], selectedCellIds),
    [readiness.data?.rows, selectedCellIds],
  );
  const selectedComputeNodes = useMemo(
    () => computeNodes.filter((node) => selectedNodeIds.includes(node.id)),
    [computeNodes, selectedNodeIds],
  );
  const latestHistoryItems = historyPayload?.items || [];
  const latestRecovery = latestHistoryItems.find((item) => !isTerminalRecoveryStatus(item.status)) || latestHistoryItems[0] || null;
  const latestRecoveryAt = latestRecovery?.updated_at || latestRecovery?.requested_at || selectedReadiness.cell?.history?.[0]?.ts || readiness.data?.recovery_history?.[selectedReadiness.row?.dataset || ""]?.[0]?.ts || null;
  const richHistoryItems =
    latestHistoryItems.length > 0
      ? latestHistoryItems
      : selectedReadiness.row
        ? readiness.data?.recovery_history?.[selectedReadiness.row.dataset] || selectedReadiness.cell?.history || []
        : [];

  const effectiveNodeIds = useMemo(() => {
    if (selectedNodeIds.length > 0) {
      return selectedNodeIds;
    }
    if (activeNodeId) {
      return [activeNodeId];
    }
    if (selectedNodeMeta?.nodeId) {
      return [selectedNodeMeta.nodeId];
    }
    return [];
  }, [activeNodeId, selectedNodeIds, selectedNodeMeta?.nodeId]);

  useEffect(() => {
    if (selectedReadiness.cell || !readiness.data?.rows?.length) {
      return;
    }
    const fallback = pickDefaultReadinessCell(readiness.data.rows);
    if (fallback) {
      setActiveCellId(fallback.id);
      setSelectedCellIds([fallback.id]);
    }
  }, [readiness.data, selectedReadiness.cell]);

  useEffect(() => {
    if (!compute.data?.nodes?.length) {
      return;
    }
    if (activeNodeId && compute.data.nodes.some((node) => node.id === activeNodeId)) {
      return;
    }
    const suggested = selectedNodeMeta?.nodeId || compute.data.nodes[0]?.id;
    if (suggested) {
      setActiveNodeId(suggested);
    }
  }, [activeNodeId, compute.data?.nodes, selectedNodeMeta?.nodeId]);

  useEffect(() => {
    if (!focus?.tab) {
      return;
    }
    setStoredTab(normalizeOpsTab(focus.tab));
  }, [focus?.tab, setStoredTab]);

  useEffect(() => {
    if (!focus?.dataset || !focus?.date || !readiness.data?.rows?.length) {
      return;
    }
    const targetRow = readiness.data.rows.find((row) => row.dataset === focus.dataset);
    const targetCell = targetRow?.cells.find((cell) => cell.date === focus.date);
    if (targetCell) {
      setActiveCellId(targetCell.id);
      setSelectedCellIds([targetCell.id]);
    }
  }, [focus?.dataset, focus?.date, readiness.data]);

  useEffect(() => {
    if (!selectedReadiness.cell) {
      return;
    }
    const nextDate = selectedReadiness.cell.date;
    setRange((current) =>
      current.dateFrom === nextDate && current.dateTo === nextDate
        ? current
        : { dateFrom: nextDate, dateTo: nextDate },
    );
    setRecoveryPlan(null);
    setRecoveryError(null);
    setRecoverySuccess(null);
    setChangeDetected(typeof selectedCellChanged === "boolean" ? selectedCellChanged : null);
    setHistoryPayload(null);
    setHistoryError(null);
  }, [selectedReadiness.cell?.id, selectedCellChanged]);

  useEffect(() => {
    if (!selectedDataset || !selectedDate) {
      return;
    }
    let cancelled = false;
    setHistoryLoading(true);
    getReadinessHistory(selectedDataset, selectedDate)
      .then((payload) => {
        if (!cancelled) {
          setHistoryPayload(payload);
          setHistoryError(null);
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setHistoryError(error instanceof Error ? error.message : t("recovery.historyUnavailable"));
        }
      })
      .finally(() => {
        if (!cancelled) {
          setHistoryLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [historyVersion, refreshToken, selectedDataset, selectedDate, t]);

  useEffect(() => {
    if (!latestRecovery || isTerminalRecoveryStatus(latestRecovery.status)) {
      return;
    }
    const timer = window.setTimeout(() => {
      readiness.retry();
      setHistoryVersion((current) => current + 1);
    }, 1800);
    return () => window.clearTimeout(timer);
  }, [latestRecovery?.id, latestRecovery?.status, readiness]);

  useEffect(() => {
    if (!latestRecovery || !isTerminalRecoveryStatus(latestRecovery.status)) {
      terminalRefreshKeyRef.current = "";
      return;
    }
    const refreshKey = `${latestRecovery.id}:${latestRecovery.status}:${latestRecovery.updated_at}`;
    if (terminalRefreshKeyRef.current === refreshKey) {
      return;
    }
    terminalRefreshKeyRef.current = refreshKey;
    readiness.retry();
    compute.retry();
  }, [compute, latestRecovery?.id, latestRecovery?.status, latestRecovery?.updated_at, readiness]);

  useEffect(() => {
    const isDefaultSingleDayRange = Boolean(selectedDate && range.dateFrom === selectedDate && range.dateTo === selectedDate);
    if (!selectedDataset || !range.dateFrom || !range.dateTo || isDefaultSingleDayRange) {
      return;
    }
    const timer = window.setTimeout(() => {
      postReadinessDetectChanges({
        dataset: selectedDataset,
        date_from: range.dateFrom,
        date_to: range.dateTo,
      })
        .then((payload) => setChangeDetected(Boolean(payload.items?.some((item) => item.changed))))
        .catch(() => setChangeDetected(null));
    }, 400);
    return () => window.clearTimeout(timer);
  }, [range.dateFrom, range.dateTo, selectedDataset, selectedDate]);

  useEffect(() => {
    if (!selectedDate || !onFocusChange) {
      return;
    }
    if (focus?.tab === tab && focus?.date === selectedDate && focus?.dataset === selectedDataset) {
      return;
    }
    onFocusChange({
      tab,
      date: selectedDate,
      dataset: selectedDataset,
    });
  }, [focus?.dataset, focus?.date, focus?.tab, onFocusChange, selectedDataset, selectedDate, tab]);

  useEffect(() => {
    if (!activeNodeId) {
      setNodeResult(null);
      setNodeError(null);
      return;
    }
    let cancelled = false;
    setNodeLoading(true);
    getOpsNodeResult(activeNodeId, selectedDate || compute.data?.as_of)
      .then((payload) => {
        if (!cancelled) {
          setNodeResult(payload);
          setNodeError(null);
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setNodeError(error instanceof Error ? error.message : t("ops.nodeUnavailable"));
        }
      })
      .finally(() => {
        if (!cancelled) {
          setNodeLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [activeNodeId, compute.data?.as_of, selectedDate, t]);

  useEffect(() => {
    const nodeIds = Array.from(new Set([
      ...effectiveNodeIds,
      ...selectedCellPayloads
        .map((cell) => rowMetaByDataset[String(cell.dataset || "")]?.nodeId || "")
        .filter(Boolean),
    ]));
    if (nodeIds.length === 0) {
      setDependencyPath(null);
      return;
    }
    let cancelled = false;
    getOpsDependencyPath(nodeIds)
      .then((payload) => {
        if (!cancelled) {
          setDependencyPath(payload);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setDependencyPath(null);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [effectiveNodeIds, rowMetaByDataset, selectedCellPayloads]);

  useEffect(() => {
    if (!currentWorkflowId) {
      setWorkflowDetail(null);
      setWorkflowError(null);
      return;
    }
    let cancelled = false;
    setWorkflowLoading(true);
    getWorkflowDetail(currentWorkflowId)
      .then((payload) => {
        if (!cancelled) {
          setWorkflowDetail(payload);
          setWorkflowError(null);
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setWorkflowError(error instanceof Error ? error.message : t("ops.workflowUnavailable"));
        }
      })
      .finally(() => {
        if (!cancelled) {
          setWorkflowLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [currentWorkflowId, t]);

  useEffect(() => {
    if (!workflowDetail || isTerminalWorkflowStatus(String(workflowDetail.status || ""))) {
      return;
    }
    const timer = window.setTimeout(() => {
      if (currentWorkflowId) {
        getWorkflowDetail(currentWorkflowId)
          .then((payload) => {
            setWorkflowDetail(payload);
            if (isTerminalWorkflowStatus(String(payload.status || ""))) {
              readiness.retry();
              compute.retry();
              runtime.retry();
              workflows.retry();
              events.retry();
            }
          })
          .catch((error) => {
            setWorkflowError(error instanceof Error ? error.message : t("ops.workflowUnavailable"));
          });
      }
    }, 1800);
    return () => window.clearTimeout(timer);
  }, [compute, currentWorkflowId, events, readiness, runtime, t, workflowDetail, workflows]);

  async function loadReplayPlan() {
    if (!selectedReadiness.row) {
      return;
    }
    setRecoveryBusy(true);
    setRecoveryError(null);
    try {
      const plan = await getReadinessReplayPlan(
        selectedReadiness.row.dataset,
        range.dateFrom || selectedReadiness.cell?.date || "",
        range.dateTo || range.dateFrom || selectedReadiness.cell?.date || "",
      );
      setRecoveryPlan(plan);
    } catch (error) {
      setRecoveryError(error instanceof Error ? error.message : t("recovery.submitFailed"));
    } finally {
      setRecoveryBusy(false);
    }
  }

  async function submitRecovery(kind: "backfill" | "replay", mode: "data_only" | "data_plus_downstream" | "full_replay", dateFrom: string, dateTo: string) {
    if (!selectedReadiness.row) {
      return;
    }
    setRecoveryBusy(true);
    setRecoveryError(null);
    setRecoverySuccess(null);
    try {
      const payload = {
        dataset: selectedReadiness.row.dataset,
        date_from: dateFrom,
        date_to: dateTo,
        mode,
      };
      const response = kind === "backfill" ? await postReadinessBackfill(payload) : await postReadinessReplay(payload);
      setRecoveryPlan(response.plan);
      setRecoverySuccess(t("recovery.requestAccepted"));
      readiness.retry();
      compute.retry();
      setHistoryVersion((current) => current + 1);
    } catch (error) {
      setRecoveryError(error instanceof Error ? error.message : t("recovery.submitFailed"));
    } finally {
      setRecoveryBusy(false);
    }
  }

  async function previewSelection(nextAction = actionMode, nextMode = replayMode) {
    const payload = buildReplayRequest({
      effectiveNodeIds,
      selectedCells: selectedCellPayloads,
      selectedReadiness,
      range,
      action: nextAction,
      mode: nextMode,
    });
    if (!payload) {
      setRecoveryError(t("ops.noSelection"));
      return;
    }
    setRecoveryBusy(true);
    setRecoveryError(null);
    try {
      const preview = await postOpsReplayPreview(payload);
      setReplayPreview(preview);
    } catch (error) {
      setRecoveryError(error instanceof Error ? error.message : t("ops.previewFailed"));
    } finally {
      setRecoveryBusy(false);
    }
  }

  async function executeSelection(nextAction: OpsReplayAction, nextMode: OpsReplayMode) {
    const payload = buildReplayRequest({
      effectiveNodeIds,
      selectedCells: selectedCellPayloads,
      selectedReadiness,
      range,
      action: nextAction,
      mode: nextMode,
    });
    if (!payload) {
      setRecoveryError(t("ops.noSelection"));
      return;
    }
    setRecoveryBusy(true);
    setRecoveryError(null);
    setRecoverySuccess(null);
    try {
      const response = await postOpsReplayExecute(payload);
      setReplayPreview(response.preview);
      setCurrentWorkflowId(response.workflow_event_id);
      setWorkflowDetail(null);
      setRecoverySuccess(t("ops.replayAccepted"));
      setTabAndStore(setStoredTab, "audit");
    } catch (error) {
      setRecoveryError(error instanceof Error ? error.message : t("ops.executeFailed"));
    } finally {
      setRecoveryBusy(false);
    }
  }

  function setTabAndStore(setter: (value: OpsTabLike) => void, nextTab: OpsTab) {
    setter(nextTab);
  }

  const recoveryActionBlock =
    selectedReadiness.row && selectedReadiness.cell ? (
      <>
        {latestRecovery && (
          <ExecutionRunCard
            action={latestRecovery}
            datasetLabel={getDatasetText(locale, selectedReadiness.row.dataset, selectedReadiness.row.label)}
          />
        )}
        <BackfillActionPanel
          dataset={selectedReadiness.row.dataset}
          selectedDate={selectedReadiness.cell.date}
          rangeFrom={range.dateFrom}
          rangeTo={range.dateTo}
          plan={recoveryPlan}
          loading={recoveryBusy}
          error={recoveryError}
          successMessage={recoverySuccess}
          lastActionAt={latestRecoveryAt}
          changed={changeDetected}
          onChangeRange={setRange}
          onBackfillDay={() => submitRecovery("backfill", "data_only", selectedReadiness.cell?.date || "", selectedReadiness.cell?.date || "")}
          onBackfillRange={() => submitRecovery("backfill", "data_only", range.dateFrom, range.dateTo)}
          onReplayDownstream={() => submitRecovery("replay", "data_plus_downstream", range.dateFrom, range.dateTo)}
          onReplayFullChain={() => submitRecovery("replay", "full_replay", range.dateFrom, range.dateTo)}
          onDryRun={loadReplayPlan}
        />
      </>
    ) : null;

  if (status.loading && !status.data) {
    return <LoadingSkeleton variant="ops" />;
  }

  if (status.error && !status.data) {
    return (
      <ErrorState
        title={t("ops.viewUnavailable")}
        body={t("ops.viewUnavailableCopy")}
        detail={status.error.message}
        action={<button type="button" className="button button--primary" onClick={status.retry}>{t("common.retry")}</button>}
      />
    );
  }

  return (
    <div className="page-stack page-ops">
      <SectionHeader title={t("ops.title")} subtitle={t("ops.subtitle")} />

      <div className="filter-bar filter-bar--ops">
        {([
          ["overview", t("ops.tabs.overview")],
          ["readiness", t("ops.tabs.readiness")],
          ["compute", t("ops.tabs.compute")],
          ["replay", t("ops.tabs.replayBuilder")],
          ["trust", t("ops.tabs.trust")],
          ["audit", t("ops.tabs.audit")],
        ] as const).map(([key, label]) => (
          <button key={key} type="button" className={tab === key ? "is-active" : ""} onClick={() => setTabAndStore(setStoredTab, key)}>
            {label}
          </button>
        ))}
      </div>

      {(tab === "readiness" || tab === "compute") && (
        <OpsLayerFilterBar
          typeFilter={typeFilter}
          statusFilter={statusFilter}
          onTypeFilter={setTypeFilter}
          onStatusFilter={(value) => setStatusFilter(value as OpsStatusFilter)}
          typeOptions={[
            { value: "all", label: t("ops.filter.all") },
            { value: "source", label: t("ops.filter.source") },
            { value: "feature", label: t("ops.filter.feature") },
            { value: "factor", label: t("ops.filter.factor") },
            { value: "model", label: t("ops.filter.model") },
            { value: "decision", label: t("ops.filter.decision") },
            { value: "workflow", label: t("ops.filter.workflow") },
          ]}
          statusOptions={[
            { value: "all", label: t("ops.statusFilter.all") },
            { value: "healthy", label: t("ops.statusFilter.healthy") },
            { value: "degraded", label: t("ops.statusFilter.degraded") },
            { value: "broken", label: t("ops.statusFilter.broken") },
            { value: "stale", label: t("ops.statusFilter.stale") },
            { value: "partial", label: t("ops.statusFilter.partial") },
          ]}
        />
      )}

      {tab === "overview" && (
        <div className="compact-grid">
          <PanelCard title={t("ops.systemSummary")} subdued>
            <div className="metric-grid">
              <div className="metric-card">
                <div className="metric-card__label">{t("ops.status")}</div>
                <div className="metric-card__value">{getGateStatusText(locale, status.data?.status).label}</div>
              </div>
              <div className="metric-card">
                <div className="metric-card__label">{t("ops.models")}</div>
                <div className="metric-card__value">{(status.data?.inference_models || []).length}</div>
              </div>
              <div className="metric-card">
                <div className="metric-card__label">{t("ops.trust")}</div>
                <div className="metric-card__value">{formatPercent(trust.data?.trust_scalar, 0)}</div>
              </div>
            </div>
          </PanelCard>

          <PanelCard title={t("ops.stageSummary")} subdued>
            <div className="list-stack">
              {Object.entries(runtime.data?.stage_summary || {}).map(([key, value]) => (
                <div className="compact-row" key={key}>
                  <div className="compact-row__title">{key}</div>
                  <div className="compact-row__meta">
                    <StatusPill label={`${value.ok || 0} ${t("status.healthy")}`} tone="ok" subtle />
                    <StatusPill label={`${value.error || 0} ${t("ops.stage.error")}`} tone="err" subtle />
                    <StatusPill label={`${value.running || 0} ${t("ops.stage.running")}`} tone="info" subtle />
                  </div>
                </div>
              ))}
            </div>
          </PanelCard>

          <PanelCard title={t("ops.recentFailures")} subdued>
            <div className="list-stack">
              {(events.data?.failed_nodes || []).slice(0, 8).map((node, index) => (
                <div className="compact-row" key={`${node.job_name || node.id || index}`}>
                  <div>
                    <div className="compact-row__title">{String(node.job_name || node.id || "Node")}</div>
                    <div className="compact-row__subtitle">{shortText(String(node.error_detail || node.result_summary || ""), 80)}</div>
                  </div>
                  <StatusPill label={getGateStatusText(locale, String(node.status || "error")).label} tone="err" subtle />
                </div>
              ))}
              {(!events.data?.failed_nodes || events.data.failed_nodes.length === 0) && <div className="note-card">{t("ops.noFailures")}</div>}
            </div>
          </PanelCard>
        </div>
      )}

      {tab === "readiness" && (
        <div className="readiness-page">
          <div className="filter-bar filter-bar--ops">
            {([
              [30, t("readiness.range30")],
              [60, t("readiness.range60")],
              [90, t("readiness.range90")],
            ] as const).map(([value, label]) => (
              <button key={value} type="button" className={readinessDays === value ? "is-active" : ""} onClick={() => setReadinessDays(value)}>
                {label}
              </button>
            ))}
          </div>

          {readiness.loading && !readiness.data ? (
            <LoadingSkeleton variant="ops" />
          ) : readiness.data ? (
            <>
              <ReadinessSummaryCards payload={readiness.data} />

              {readiness.data.summary.today_impact?.constrained && (
                <div className="page-banner page-banner--muted">
                  <strong>{t("readiness.todayConstrained")}</strong>
                  <span>
                    {(readiness.data.summary.today_impact?.datasets || [])
                      .slice(0, 3)
                      .map((item) => `${getDatasetText(locale, item.dataset, item.label)} · ${getOpsNodeTypeText(locale, rowMetaByDataset[item.dataset || ""]?.nodeType || "source")}`)
                      .join(" · ")}
                  </span>
                </div>
              )}

              <div className="readiness-shell">
                <PanelCard title={t("ops.tabs.readiness")} subdued>
                  <ReadinessHeatmap
                    rows={filteredReadinessRows}
                    dates={readiness.data.range.dates}
                    activeCellId={activeCellId}
                    selectedCellIds={selectedCellIds}
                    selectedNodeIds={selectedNodeIds}
                    rowMeta={rowMetaByDataset}
                    collapsedGroups={collapsedReadinessGroups}
                    onToggleGroup={(groupKey) =>
                      setCollapsedReadinessGroups((current) => ({
                        ...current,
                        [groupKey]: !current[groupKey],
                      }))
                    }
                    onSelect={(row, cell, options) => {
                      setActiveCellId(cell.id);
                      setSelectedCellIds((current) => {
                        if (options?.append) {
                          return toggleId(current, cell.id);
                        }
                        return [cell.id];
                      });
                    }}
                    onToggleRow={(row) => {
                      const nodeId = rowMetaByDataset[row.dataset]?.nodeId;
                      if (!nodeId) {
                        return;
                      }
                      setActiveNodeId(nodeId);
                      setSelectedNodeIds((current) => toggleId(current, nodeId));
                    }}
                  />
                </PanelCard>
                <ReadinessInspector
                  row={selectedReadiness.row}
                  cell={selectedReadiness.cell}
                  nodeMeta={selectedNodeMeta}
                  historyItems={richHistoryItems}
                  actions={recoveryActionBlock}
                />
              </div>
            </>
          ) : (
            <ErrorState
              title={t("ops.viewUnavailable")}
              body={t("ops.viewUnavailableCopy")}
              action={<button type="button" className="button button--primary" onClick={readiness.retry}>{t("common.retry")}</button>}
            />
          )}
        </div>
      )}

      {tab === "compute" && compute.data && (
        <ComputeLayersView
          payload={filteredComputePayload}
          activeNodeId={activeNodeId}
          selectedNodeIds={selectedNodeIds}
          collapsedGroups={collapsedComputeGroups}
          onToggleGroup={(groupKey) =>
            setCollapsedComputeGroups((current) => ({
              ...current,
              [groupKey]: !current[groupKey],
            }))
          }
          onActivateNode={(nodeId) => {
            setActiveNodeId(nodeId);
            if (selectionMode !== "cell" && selectedNodeIds.length === 0) {
              setSelectedNodeIds([nodeId]);
            }
          }}
          onToggleNode={(nodeId) => {
            if (selectionMode === "subtree") {
              const expanded = expandSubtree(nodeId, computeNodes);
              setSelectedNodeIds((current) => toggleManyIds(current, expanded));
              return;
            }
            setSelectedNodeIds((current) => toggleId(current, nodeId));
          }}
          inspector={<ComputeNodeInspector node={nodeResult} loading={nodeLoading} error={nodeError} />}
        />
      )}

      {tab === "replay" && (
        <ReplayBuilder
          selectionMode={selectionMode}
          replayMode={replayMode}
          actionMode={actionMode}
          selectedNodes={selectedComputeNodes}
          selectedCells={selectedCellPayloads}
          dependencyPath={dependencyPath}
          preview={replayPreview}
          workflow={workflowDetail}
          loading={recoveryBusy || workflowLoading}
          error={recoveryError || workflowError}
          onSelectionMode={setSelectionMode}
          onReplayMode={setReplayMode}
          onActionMode={setActionMode}
          onPreview={() => previewSelection(actionMode, replayMode)}
          onRepair={() => executeSelection("repair", replayMode)}
          onRecompute={() => executeSelection("recompute", "selected_plus_downstream")}
          onFullChain={() => executeSelection("recompute", "full_chain")}
          onCompare={() => setTabAndStore(setStoredTab, "compute")}
          onClear={() => {
            setSelectedCellIds([]);
            setSelectedNodeIds([]);
            setReplayPreview(null);
          }}
        />
      )}

      {tab === "trust" && (
        <PanelCard title={t("ops.trustTrend")} subdued>
          <div className="list-stack">
            {(trust.data?.trend || []).map((item) => (
              <div className="compact-row" key={item.eval_date}>
                <div className="compact-row__title">{item.eval_date}</div>
                <div className="compact-row__meta">
                  <span>{t("ops.trust.scalar")} {formatPercent(item.trust_scalar, 0)}</span>
                  <span>{t("ops.trust.coverageLabel")} {formatPercent(item.coverage, 0)}</span>
                </div>
              </div>
            ))}
          </div>
        </PanelCard>
      )}

      {tab === "audit" && (
        <div className="compact-grid">
          <PanelCard title={t("ops.workflowTraces")} subdued>
            <div className="list-stack">
              {workflowDetail && (
                <div className="note-card">
                  <strong>{String(workflowDetail.title || t("ops.currentWorkflow"))}</strong>
                  <div className="readiness-inspector__subtle">
                    {t("ops.workflowProgress", {
                      completed: Number(workflowDetail.progress?.completed || 0),
                      total: Number(workflowDetail.progress?.total || 0),
                    })}
                  </div>
                </div>
              )}
              {(workflows.data || []).slice(0, 12).map((workflow, index) => (
                <div className="compact-row" key={`${workflow.root_event_id || index}`}>
                  <div>
                    <div className="compact-row__title">{getWorkflowTitle(workflow)}</div>
                    <div className="compact-row__subtitle">{shortText(getWorkflowSummary(workflow) || "", 90) || t("ops.noRootCause")}</div>
                  </div>
                  <div className="compact-row__meta">
                    <StatusPill label={getGateStatusText(locale, String(workflow.status || "unknown")).label} tone={String(workflow.status) === "ok" ? "ok" : String(workflow.status) === "error" ? "err" : "info"} subtle />
                    <span>{formatDateTime(String(workflow.created_at || workflow.started_at || ""), locale === "zh-CN" ? "zh-CN" : "en-US")}</span>
                  </div>
                </div>
              ))}
            </div>
          </PanelCard>

          <PanelCard title={t("readiness.auditHistory")} subdued>
            {historyLoading && richHistoryItems.length === 0 ? <LoadingSkeleton variant="panel" /> : <RecoveryTimeline items={richHistoryItems} />}
          </PanelCard>
        </div>
      )}
    </div>
  );
}

function normalizeOpsTab(tab?: string | null): OpsTab {
  if (tab === "recovery") {
    return "replay";
  }
  if (tab === "pipeline") {
    return "overview";
  }
  if (tab === "workflows") {
    return "audit";
  }
  if (tab === "overview" || tab === "readiness" || tab === "compute" || tab === "replay" || tab === "trust" || tab === "audit") {
    return tab;
  }
  return "readiness";
}

function pickDefaultReadinessCell(rows: ReadinessRow[]) {
  for (const row of rows) {
    const problematic = row.cells.find((cell) => !["READY", "LATE_READY"].includes(cell.status));
    if (problematic) {
      return problematic;
    }
  }
  return rows[0]?.cells[0] || null;
}

function findSelectedReadiness(rows: ReadinessRow[], selectedCellId: string): { row: ReadinessRow | null; cell: ReadinessCell | null } {
  for (const row of rows) {
    const cell = row.cells.find((item) => item.id === selectedCellId);
    if (cell) {
      return { row, cell };
    }
  }
  return { row: null, cell: null };
}

function getWorkflowTitle(workflow: WorkflowSummary) {
  return String(workflow.title || workflow.topic || workflow.job_name || "Workflow");
}

function getWorkflowSummary(workflow: WorkflowSummary) {
  const rootCause = workflow.root_cause;
  if (rootCause && typeof rootCause === "object") {
    const payload = rootCause as Record<string, unknown>;
    return String(payload.message || payload.node || workflow.reason_summary || "");
  }
  return String(workflow.reason_summary || "");
}

function buildReadinessRowMeta(nodes: OpsComputeLayersPayload["nodes"]): Record<string, ReadinessRowMeta> {
  const map: Record<string, ReadinessRowMeta> = {};
  for (const node of nodes) {
    if (!node.mapped_dataset) {
      continue;
    }
    if (!map[node.mapped_dataset]) {
      map[node.mapped_dataset] = {
        nodeId: node.id,
        nodeType: node.type,
        layer: node.layer,
        description: node.description,
      };
    }
  }
  return map;
}

function filterReadinessRows(rows: ReadinessRow[], rowMetaByDataset: Record<string, ReadinessRowMeta>, typeFilter: string, statusFilter: OpsStatusFilter) {
  return rows.filter((row) => {
    const meta = rowMetaByDataset[row.dataset];
    const nodeType = String(meta?.nodeType || "source");
    if (typeFilter !== "all" && nodeType !== typeFilter) {
      return false;
    }
    if (statusFilter === "all") {
      return true;
    }
    return row.cells.some((cell) => matchesReadinessStatus(cell.status, statusFilter));
  });
}

function filterComputePayload(payload: OpsComputeLayersPayload | null, typeFilter: string, statusFilter: OpsStatusFilter): OpsComputeLayersPayload {
  if (!payload) {
    return { as_of: "", previous_as_of: null, representative_symbol: null, layers: [], nodes: [] };
  }
  const layers = payload.layers
    .map((group) => ({
      ...group,
      nodes: group.nodes.filter((node) => {
        if (typeFilter !== "all" && node.type !== typeFilter) {
          return false;
        }
        return statusFilter === "all" ? true : matchesNodeStatus(String(node.latest_status || "unknown"), statusFilter);
      }),
    }))
    .filter((group) => group.nodes.length > 0);
  return {
    ...payload,
    layers,
    nodes: layers.flatMap((group) => group.nodes),
  };
}

function matchesReadinessStatus(status: string, filter: OpsStatusFilter) {
  const normalized = status.toUpperCase();
  if (filter === "healthy") {
    return normalized === "READY" || normalized === "REPLAYED";
  }
  if (filter === "degraded") {
    return normalized === "CHANGED" || normalized === "REPLAYING" || normalized === "UNKNOWN";
  }
  if (filter === "broken") {
    return normalized === "MISSING";
  }
  if (filter === "stale") {
    return normalized === "LATE_READY" || normalized === "CHANGED";
  }
  if (filter === "partial") {
    return normalized === "PARTIAL";
  }
  return true;
}

function matchesNodeStatus(status: string, filter: OpsStatusFilter) {
  const normalized = status.toLowerCase();
  if (filter === "healthy") {
    return normalized === "ok";
  }
  if (filter === "degraded") {
    return normalized === "running" || normalized === "unknown";
  }
  if (filter === "broken") {
    return normalized === "error";
  }
  if (filter === "stale" || filter === "partial") {
    return normalized === "partial";
  }
  return true;
}

function collectSelectedCells(rows: ReadinessRow[], selectedIds: string[]) {
  const items: Array<{ id: string; dataset: string; date: string }> = [];
  for (const row of rows) {
    for (const cell of row.cells) {
      if (selectedIds.includes(cell.id)) {
        items.push({ id: cell.id, dataset: row.dataset, date: cell.date });
      }
    }
  }
  return items;
}

function toggleId(current: string[], value: string) {
  return current.includes(value) ? current.filter((item) => item !== value) : [...current, value];
}

function toggleManyIds(current: string[], values: string[]) {
  const allSelected = values.every((value) => current.includes(value));
  if (allSelected) {
    return current.filter((item) => !values.includes(item));
  }
  return Array.from(new Set([...current, ...values]));
}

function expandSubtree(nodeId: string, nodes: OpsComputeLayersPayload["nodes"]) {
  const queue = [nodeId];
  const seen = new Set(queue);
  while (queue.length > 0) {
    const current = queue.shift() || "";
    const node = nodes.find((item) => item.id === current);
    for (const child of node?.downstream_ids || []) {
      if (!seen.has(child)) {
        seen.add(child);
        queue.push(child);
      }
    }
  }
  return Array.from(seen);
}

function buildReplayRequest({
  effectiveNodeIds,
  selectedCells,
  selectedReadiness,
  range,
  action,
  mode,
}: {
  effectiveNodeIds: string[];
  selectedCells: Array<{ id: string; dataset: string; date: string }>;
  selectedReadiness: { row: ReadinessRow | null; cell: ReadinessCell | null };
  range: { dateFrom: string; dateTo: string };
  action: OpsReplayAction;
  mode: OpsReplayMode;
}) {
  const fallbackDate = selectedReadiness.cell?.date || "";
  const dateFrom = range.dateFrom || fallbackDate;
  const dateTo = range.dateTo || dateFrom;
  if (!dateFrom) {
    return null;
  }
  const cells = selectedCells.length > 0
    ? selectedCells
    : selectedReadiness.row && selectedReadiness.cell
      ? [{ id: selectedReadiness.cell.id, dataset: selectedReadiness.row.dataset, date: selectedReadiness.cell.date }]
      : [];
  return {
    selected_node_ids: effectiveNodeIds,
    selected_cells: cells,
    date_from: dateFrom,
    date_to: dateTo,
    action,
    mode,
  };
}
