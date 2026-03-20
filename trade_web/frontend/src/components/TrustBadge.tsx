import { formatPercent } from "../lib/format";
import { classNames, getTrustLevel } from "../lib/ui";

type TrustBadgeProps = {
  score?: number | null;
  level?: string | null;
  detailed?: boolean;
};

export function TrustBadge({ score, level, detailed = false }: TrustBadgeProps) {
  const resolved = getTrustLevel(score, level).toLowerCase();

  return (
    <span className={classNames("trust-badge", `trust-badge--${resolved}`)}>
      <span className="trust-badge__label">{level || getTrustLevel(score, level)}</span>
      {detailed && <span className="trust-badge__score">{formatPercent(score, 0)}</span>}
    </span>
  );
}
