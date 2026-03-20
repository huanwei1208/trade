import { useState } from "react";

import { classNames } from "../lib/ui";

type CollapseSectionProps = {
  title: string;
  initialOpen?: boolean;
  children: React.ReactNode;
};

export function CollapseSection({ title, initialOpen = false, children }: CollapseSectionProps) {
  const [open, setOpen] = useState(initialOpen);

  return (
    <section className={classNames("collapse-section", open && "is-open")}>
      <button type="button" className="collapse-section__toggle" onClick={() => setOpen((current) => !current)}>
        <span>{title}</span>
        <span>{open ? "−" : "+"}</span>
      </button>
      {open && <div className="collapse-section__content">{children}</div>}
    </section>
  );
}
