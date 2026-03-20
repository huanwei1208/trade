import { formatAction } from "../lib/format";
import { classNames } from "../lib/ui";

type ActionChipProps = {
  action?: string | null;
};

export function ActionChip({ action }: ActionChipProps) {
  const normalized = String(action || "NO_ACTION").toUpperCase();
  const tone =
    normalized === "ADD"
      ? "add"
      : normalized === "PROBE"
        ? "probe"
        : normalized === "WATCH"
          ? "watch"
          : normalized === "REDUCE"
            ? "reduce"
            : "no-action";

  return <span className={classNames("action-chip", `action-chip--${tone}`)}>{formatAction(normalized)}</span>;
}
