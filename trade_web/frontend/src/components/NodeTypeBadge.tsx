import type { OpsNodeType } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { getOpsNodeTypeText } from "../lib/statusText";
import { classNames } from "../lib/ui";

type NodeTypeBadgeProps = {
  type?: OpsNodeType | string | null;
  subtle?: boolean;
};

export function NodeTypeBadge({ type, subtle = false }: NodeTypeBadgeProps) {
  const { locale } = useI18n();
  const normalized = String(type || "unknown").trim().toLowerCase();
  return (
    <span className={classNames("node-type-badge", `node-type-badge--${normalized}`, subtle && "is-subtle")}>
      {getOpsNodeTypeText(locale, normalized)}
    </span>
  );
}
