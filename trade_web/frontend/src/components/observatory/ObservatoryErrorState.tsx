import type { ObservatorySafeError } from "../../lib/observatory";

type ObservatoryErrorStateProps = {
  title: string;
  error: ObservatorySafeError | null;
  unavailable?: boolean;
  onRetry?: () => void;
};

/** Presentation-only safe failure state for an Observatory resource. */
export function ObservatoryErrorState({
  title,
  error,
  unavailable = false,
  onRetry,
}: ObservatoryErrorStateProps) {
  const message =
    error?.message ??
    (unavailable ? "This evidence is unavailable." : "Unable to load current evidence.");

  return (
    <div className="obs-resource-error" role="alert" data-testid="observatory-error-state">
      <div className="obs-resource-error__title">{title}</div>
      <p>{message}</p>
      {error?.reasonCodes.length ? <div>Reason codes: {error.reasonCodes.join(", ")}</div> : null}
      {error?.evidenceRefs.length ? <div>Evidence: {error.evidenceRefs.join(", ")}</div> : null}
      {onRetry && error?.retryable ? (
        <button type="button" className="button button--ghost" onClick={onRetry}>
          Retry
        </button>
      ) : null}
    </div>
  );
}
