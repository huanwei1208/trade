import { useI18n } from "../lib/i18n";
import { getActionText } from "../lib/statusText";
import { classNames } from "../lib/ui";

type ActionChipProps = {
  action?: string | null;
};

export function ActionChip({ action }: ActionChipProps) {
  const { locale } = useI18n();
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
  return <span className={classNames("action-chip", `action-chip--${tone}`)}>{getActionText(locale, normalized)}</span>;
}
