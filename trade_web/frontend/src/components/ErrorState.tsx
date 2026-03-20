import type { ReactNode } from "react";

type ErrorStateProps = {
  title: string;
  body: string;
  detail?: string;
  action?: ReactNode;
};

export function ErrorState({ title, body, detail, action }: ErrorStateProps) {
  return (
    <div className="state-card state-card--error">
      <div className="state-card__icon">!</div>
      <div className="state-card__title">{title}</div>
      <div className="state-card__body">{body}</div>
      {detail && (
        <details className="state-card__details">
          <summary>Technical detail</summary>
          <pre>{detail}</pre>
        </details>
      )}
      {action && <div className="state-card__action">{action}</div>}
    </div>
  );
}
