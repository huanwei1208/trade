type EmptyStateProps = {
  title: string;
  body: string;
  action?: React.ReactNode;
};

export function EmptyState({ title, body, action }: EmptyStateProps) {
  return (
    <div className="state-card state-card--empty">
      <div className="state-card__icon">◌</div>
      <div className="state-card__title">{title}</div>
      <div className="state-card__body">{body}</div>
      {action && <div className="state-card__action">{action}</div>}
    </div>
  );
}
