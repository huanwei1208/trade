import type { PeerEntry } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { classNames } from "../lib/ui";

type Props = {
  peers?: PeerEntry[];
  loading?: boolean;
};

function actionTone(action?: string): string {
  if (!action) return "neutral";
  const a = action.toUpperCase();
  if (a === "ADD" || a === "PROBE") return "positive";
  if (a === "REDUCE") return "negative";
  return "neutral";
}

function muColor(mu?: number | null): string {
  if (mu == null) return "";
  if (mu > 0.1) return "positive";
  if (mu < -0.1) return "negative";
  return "neutral";
}

export function PeerMiniTable({ peers = [], loading }: Props) {
  const { t } = useI18n();

  if (loading) {
    return <div className="peer-mini-table-skeleton">{t("common.loading")}</div>;
  }

  if (peers.length === 0) {
    return (
      <div className="peer-mini-table-empty">{t("symbol.sector.noPeers")}</div>
    );
  }

  return (
    <div className="peer-mini-table">
      <table className="peer-mini-table__table">
        <thead>
          <tr>
            <th className="peer-mini-table__th">{t("symbol.sector.peerSymbol")}</th>
            <th className="peer-mini-table__th">{t("symbol.sector.peerName")}</th>
            <th className="peer-mini-table__th peer-mini-table__th--num">{t("symbol.sector.peerAction")}</th>
            <th className="peer-mini-table__th peer-mini-table__th--num">{t("symbol.sector.peerBelief")}</th>
            <th className="peer-mini-table__th peer-mini-table__th--num">{t("symbol.sector.peerScore")}</th>
          </tr>
        </thead>
        <tbody>
          {peers.map((p) => (
            <tr key={p.symbol} className="peer-mini-table__row">
              <td className="peer-mini-table__td peer-mini-table__td--symbol">{p.symbol}</td>
              <td className="peer-mini-table__td peer-mini-table__td--name">{p.name}</td>
              <td className={classNames("peer-mini-table__td peer-mini-table__td--num", `peer-mini-table__td--${actionTone(p.action)}`)}>
                {p.action || "—"}
              </td>
              <td className={classNames("peer-mini-table__td peer-mini-table__td--num", `peer-mini-table__td--${muColor(p.belief_mu)}`)}>
                {p.belief_mu != null ? p.belief_mu.toFixed(3) : "—"}
              </td>
              <td className="peer-mini-table__td peer-mini-table__td--num">
                {p.score != null ? p.score.toFixed(2) : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
