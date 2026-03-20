import { extractRecoverySteps, getRecoveryProgress, isTerminalRecoveryStatus, type ReadinessActionDetail } from "../lib/api";
import { formatDateTime, formatDurationMs } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { StatusPill } from "./StatusPill";

type ExecutionRunCardProps = {
  action?: ReadinessActionDetail | null;
  datasetLabel?: string;
};

function getStatusTone(status?: string | null) {
  const normalized = String(status || "").toLowerCase();
  if (normalized === "ok") {
    return "ok" as const;
  }
  if (normalized === "error") {
    return "err" as const;
  }
  return "info" as const;
}

function getStatusLabel(t: (key: string) => string, status?: string | null) {
  const normalized = String(status || "").toLowerCase();
  if (normalized === "queued") {
    return t("queue.queued");
  }
  if (normalized === "running") {
    return t("queue.running");
  }
  if (normalized === "error") {
    return t("queue.error");
  }
  return t("queue.ok");
}

export function ExecutionRunCard({ action, datasetLabel }: ExecutionRunCardProps) {
  const { locale, t } = useI18n();

  if (!action) {
    return null;
  }

  const progress = getRecoveryProgress(action);
  const actualSteps = extractRecoverySteps(action);
  const plannedSteps = (action.job_names || []).filter(Boolean);
  const displaySteps =
    plannedSteps.length > 0
      ? plannedSteps.map((jobName, index) => {
          const actualStep = actualSteps[index];
          if (actualStep && (actualStep.job_name === jobName || !actualStep.job_name)) {
            return {
              job_name: actualStep.job_name || jobName,
              status: actualStep.status,
              summary: actualStep.summary,
              duration_ms: actualStep.duration_ms,
            };
          }
          const pendingStatus =
            !isTerminalRecoveryStatus(action.status) && index === actualSteps.length
              ? String(action.status || "running").toLowerCase()
              : actualSteps.length > index
                ? "ok"
                : "queued";
          return {
            job_name: jobName,
            status: pendingStatus,
            summary: null,
            duration_ms: null,
          };
        })
      : actualSteps;

  return (
    <div className="execution-run-card">
      <div className="execution-run-card__head">
        <div>
          <div className="execution-run-card__eyebrow">{t("recovery.currentRun")}</div>
          <div className="execution-run-card__title">{t("recovery.restoreLatestRecommendation")}</div>
          <div className="execution-run-card__copy">
            {t("recovery.runTargetCopy", {
              dataset: datasetLabel || action.dataset,
              date: action.date_to,
            })}
          </div>
        </div>
        <StatusPill label={getStatusLabel(t, action.status)} tone={getStatusTone(action.status)} />
      </div>

      <div className="execution-run-card__meta">
        <span>
          {t("recovery.progressLabel")} {progress.completedSteps}/{progress.totalSteps || actualSteps.length || 0}
        </span>
        <span>
          {t("recovery.lastUpdated")} {formatDateTime(action.updated_at || action.requested_at, locale === "zh-CN" ? "zh-CN" : "en-US")}
        </span>
        <span>
          {t("recovery.totalDuration")} {formatDurationMs(action.result?.duration_ms)}
        </span>
      </div>

      {progress.totalSteps > 0 && (
        <div className="execution-run-card__progress">
          <div className="execution-run-card__progress-bar">
            <span
              className="execution-run-card__progress-fill"
              style={{ width: `${Math.max(6, Math.round((progress.progressRatio || 0) * 100))}%` }}
            />
          </div>
          {progress.activeStep?.job_name && (
            <div className="execution-run-card__active">
              {t("recovery.activeStep")} <strong>{progress.activeStep.job_name}</strong>
            </div>
          )}
        </div>
      )}

      <div className="execution-run-card__steps">
        {displaySteps.length > 0 ? (
          displaySteps.map((step, index) => (
            <div className="execution-run-card__step" key={`${step.job_name || "step"}-${index}`}>
              <div className="execution-run-card__step-main">
                <strong>{step.job_name || t("recovery.unknownStep")}</strong>
                <StatusPill label={getStatusLabel(t, step.status)} tone={getStatusTone(step.status)} subtle />
              </div>
              <div className="execution-run-card__step-copy">
                {step.summary || (String(step.status || "").toLowerCase() === "queued" ? t("recovery.waitingForExecution") : t("common.noDetail"))}
              </div>
              <div className="execution-run-card__step-meta">{formatDurationMs(step.duration_ms)}</div>
            </div>
          ))
        ) : (
          <div className="note-card">{action.summary || t("common.noDetail")}</div>
        )}
      </div>

      {action.error && <div className="note-card note-card--danger">{action.error}</div>}
    </div>
  );
}
