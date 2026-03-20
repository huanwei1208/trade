import { classNames } from "../lib/ui";

type StatusPillProps = {
  label: string;
  tone?: "ok" | "warn" | "err" | "info" | "muted";
  subtle?: boolean;
};

export function StatusPill({ label, tone = "muted", subtle = false }: StatusPillProps) {
  return <span className={classNames("status-pill", `status-pill--${tone}`, subtle && "is-subtle")}>{label}</span>;
}
