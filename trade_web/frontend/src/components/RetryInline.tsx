type RetryInlineProps = {
  message: string;
  onRetry: () => void;
};

export function RetryInline({ message, onRetry }: RetryInlineProps) {
  return (
    <div className="retry-inline">
      <span>{message}</span>
      <button type="button" className="button button--ghost" onClick={onRetry}>
        Retry
      </button>
    </div>
  );
}
