import type { AdjustMode, IndicatorMode } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { classNames } from "../lib/ui";

type SymbolChartToolbarProps = {
  adjustMode: AdjustMode;
  indicatorMode: IndicatorMode;
  showEvents: boolean;
  onAdjustChange: (mode: AdjustMode) => void;
  onIndicatorChange: (mode: IndicatorMode) => void;
  onShowEventsChange: (show: boolean) => void;
};

const ADJUST_OPTIONS: Array<{ value: AdjustMode; labelKey: string }> = [
  { value: "qfq", labelKey: "symbol.priceBasisQfq" },
  { value: "none", labelKey: "symbol.priceBasisNone" },
];

const INDICATOR_OPTIONS: Array<{ value: IndicatorMode; labelKey: string }> = [
  { value: "rsi", labelKey: "symbol.toolbar.indicatorRsi" },
  { value: "macd", labelKey: "symbol.toolbar.indicatorMacd" },
  { value: "kdj", labelKey: "symbol.toolbar.indicatorKdj" },
  { value: "none", labelKey: "symbol.toolbar.indicatorNone" },
];

export function SymbolChartToolbar({
  adjustMode,
  indicatorMode,
  showEvents,
  onAdjustChange,
  onIndicatorChange,
  onShowEventsChange,
}: SymbolChartToolbarProps) {
  const { t } = useI18n();

  return (
    <div className="symbol-chart-toolbar">
      <div className="symbol-chart-toolbar__group">
        <span className="symbol-chart-toolbar__label">{t("symbol.toolbar.adjust")}</span>
        {ADJUST_OPTIONS.map(({ value, labelKey }) => (
          <button
            key={value}
            type="button"
            className={classNames("toggle-chip", adjustMode === value && "is-active")}
            onClick={() => onAdjustChange(value)}
          >
            {t(labelKey)}
          </button>
        ))}
      </div>

      <div className="symbol-chart-toolbar__group">
        <span className="symbol-chart-toolbar__label">{t("symbol.toolbar.indicator")}</span>
        {INDICATOR_OPTIONS.map(({ value, labelKey }) => (
          <button
            key={value}
            type="button"
            className={classNames("toggle-chip", indicatorMode === value && "is-active")}
            onClick={() => onIndicatorChange(value)}
          >
            {t(labelKey)}
          </button>
        ))}
      </div>

      <div className="symbol-chart-toolbar__group">
        <button
          type="button"
          className={classNames("toggle-chip", showEvents && "is-active")}
          onClick={() => onShowEventsChange(!showEvents)}
        >
          {t("symbol.toolbar.eventMarkers")}
        </button>
      </div>
    </div>
  );
}
