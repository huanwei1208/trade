import { formatPercent } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { getTrustLevelText } from "../lib/statusText";
import { classNames, getTrustLevel } from "../lib/ui";

type TrustBadgeProps = {
  score?: number | null;
  level?: string | null;
  detailed?: boolean;
};

export function TrustBadge({ score, level, detailed = false }: TrustBadgeProps) {
  const { locale } = useI18n();
  const resolvedKey = getTrustLevel(score, level);
  const resolved = resolvedKey.toLowerCase();
  const semantic = getTrustLevelText(locale, score, level);

  return (
    <span className={classNames("trust-badge", `trust-badge--${resolved}`)}>
      <span className="trust-badge__label">{semantic.label}</span>
      {detailed && <span className="trust-badge__score">{formatPercent(score, 0)}</span>}
    </span>
  );
}
