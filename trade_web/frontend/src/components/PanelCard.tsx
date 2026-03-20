import type { ReactNode } from "react";

import { classNames } from "../lib/ui";

type PanelCardProps = {
  title?: string;
  eyebrow?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  accent?: "blue" | "cyan" | "green" | "amber" | "red" | "violet";
  selected?: boolean;
  interactive?: boolean;
  subdued?: boolean;
  onClick?: () => void;
};

export function PanelCard({
  title,
  eyebrow,
  actions,
  children,
  className,
  accent,
  selected,
  interactive,
  subdued,
  onClick,
}: PanelCardProps) {
  const content = (
    <>
      {(title || eyebrow || actions) && (
        <div className="panel-card__header">
          <div>
            {eyebrow && <div className="panel-card__eyebrow">{eyebrow}</div>}
            {title && <h3 className="panel-card__title">{title}</h3>}
          </div>
          {actions && <div className="panel-card__actions">{actions}</div>}
        </div>
      )}
      <div className="panel-card__body">{children}</div>
    </>
  );

  const classes = classNames(
    "panel-card",
    accent && `panel-card--${accent}`,
    selected && "is-selected",
    interactive && "is-interactive",
    subdued && "is-subdued",
    className,
  );

  if (interactive || onClick) {
    return (
      <button className={classes} onClick={onClick} type="button">
        {content}
      </button>
    );
  }

  return <section className={classes}>{content}</section>;
}
