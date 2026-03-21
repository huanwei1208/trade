import type { AdjustMode, PriceBasis, SymbolQuote } from "../lib/api";
import { formatCompactNumber, formatDate, formatPercent, formatScore } from "../lib/format";
import { useI18n } from "../lib/i18n";
import { classNames } from "../lib/ui";

type SymbolQuoteStripProps = {
  symbol: string;
  name?: string | null;
  quote?: SymbolQuote | null;
  priceBasis?: PriceBasis | null;
  onBack: () => void;
};

function AdjustLabel({ adjust }: { adjust?: AdjustMode }) {
  const { t } = useI18n();
  if (!adjust || adjust === "none") return <span className="quote-strip__basis-tag">{t("symbol.priceBasisNone")}</span>;
  if (adjust === "hfq") return <span className="quote-strip__basis-tag">{t("symbol.priceBasisHfq")}</span>;
  return <span className="quote-strip__basis-tag">{t("symbol.priceBasisQfq")}</span>;
}

export function SymbolQuoteStrip({ symbol, name, quote, priceBasis, onBack }: SymbolQuoteStripProps) {
  const { locale, t } = useI18n();

  const latestPrice = quote?.latest_price;
  const change = quote?.change;
  const changePct = quote?.change_pct;
  const isPositive = (changePct ?? 0) >= 0;
  const isNegative = (changePct ?? 0) < 0;
  const asOf = quote?.as_of || priceBasis?.latest_trade_date;

  return (
    <div className="quote-strip">
      <div className="quote-strip__identity">
        <button type="button" className="button button--ghost quote-strip__back" onClick={onBack}>
          {t("common.back")}
        </button>
        <div className="quote-strip__symbol-block">
          <span className="quote-strip__symbol">{symbol}</span>
          {name && <span className="quote-strip__name">{name}</span>}
          {priceBasis?.adjust && <AdjustLabel adjust={priceBasis.adjust} />}
        </div>
      </div>

      <div className="quote-strip__price-block">
        {latestPrice !== undefined ? (
          <span className={classNames(
            "quote-strip__price",
            isPositive && "quote-strip__price--positive",
            isNegative && "quote-strip__price--negative"
          )}>
            {formatScore(latestPrice, 2)}
          </span>
        ) : (
          <span className="quote-strip__price quote-strip__price--na">—</span>
        )}
        {change !== undefined && changePct !== undefined && (
          <div className="quote-strip__change-block">
            <span className={classNames(
              "quote-strip__change",
              isPositive && "quote-strip__change--positive",
              isNegative && "quote-strip__change--negative"
            )}>
              {isPositive ? "+" : ""}{formatScore(change, 2)}
            </span>
            <span className={classNames(
              "quote-strip__change-pct",
              isPositive && "quote-strip__change--positive",
              isNegative && "quote-strip__change--negative"
            )}>
              ({isPositive ? "+" : ""}{formatPercent(changePct, 2)})
            </span>
          </div>
        )}
      </div>

      <div className="quote-strip__stats">
        {quote?.open !== undefined && (
          <div className="quote-strip__stat">
            <span className="quote-strip__stat-label">{t("symbol.quoteOpen")}</span>
            <span className="quote-strip__stat-value">{formatScore(quote.open, 2)}</span>
          </div>
        )}
        {quote?.high !== undefined && (
          <div className="quote-strip__stat">
            <span className="quote-strip__stat-label">{t("symbol.quoteHigh")}</span>
            <span className="quote-strip__stat-value quote-strip__stat-value--positive">{formatScore(quote.high, 2)}</span>
          </div>
        )}
        {quote?.low !== undefined && (
          <div className="quote-strip__stat">
            <span className="quote-strip__stat-label">{t("symbol.quoteLow")}</span>
            <span className="quote-strip__stat-value quote-strip__stat-value--negative">{formatScore(quote.low, 2)}</span>
          </div>
        )}
        {quote?.prev_close !== undefined && (
          <div className="quote-strip__stat">
            <span className="quote-strip__stat-label">{t("symbol.quotePrevClose")}</span>
            <span className="quote-strip__stat-value">{formatScore(quote.prev_close, 2)}</span>
          </div>
        )}
        {quote?.volume !== undefined && (
          <div className="quote-strip__stat">
            <span className="quote-strip__stat-label">{t("symbol.quoteVolume")}</span>
            <span className="quote-strip__stat-value">{formatCompactNumber(quote.volume)}</span>
          </div>
        )}
        {quote?.amount !== undefined && (
          <div className="quote-strip__stat">
            <span className="quote-strip__stat-label">{t("symbol.quoteAmount")}</span>
            <span className="quote-strip__stat-value">{formatCompactNumber(quote.amount)}</span>
          </div>
        )}
        {quote?.turnover !== undefined && (
          <div className="quote-strip__stat">
            <span className="quote-strip__stat-label">{t("symbol.quoteTurnover")}</span>
            <span className="quote-strip__stat-value">{formatPercent(quote.turnover, 2)}</span>
          </div>
        )}
        {quote?.vwap !== undefined && (
          <div className="quote-strip__stat">
            <span className="quote-strip__stat-label">{t("symbol.quoteVwap")}</span>
            <span className="quote-strip__stat-value">{formatScore(quote.vwap, 2)}</span>
          </div>
        )}
        {asOf && (
          <div className="quote-strip__stat quote-strip__stat--timestamp">
            <span className="quote-strip__stat-label">{t("symbol.quoteAsOf")}</span>
            <span className="quote-strip__stat-value">{formatDate(asOf, locale === "zh-CN" ? "zh-CN" : "en-US")}</span>
          </div>
        )}
      </div>
    </div>
  );
}
