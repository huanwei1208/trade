"""ExplanationService — builds DecisionExplanation + kline context.

Orchestrates the full explain path for a symbol:
  1. StateService  → WorldState
  2. DecisionService → ScenarioSummary + ActionDecision
  3. Trust (from InferenceService) → TrustBreakdown
  4. build_explanation() → DecisionExplanation

Also provides `build_kline_context()` so that /api/kline/{symbol} can
call a service instead of embedding business logic in the route handler.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

logger = logging.getLogger(__name__)


class ExplanationService:
    """Build DecisionExplanation and kline context for a symbol.

    Parameters
    ----------
    state_svc : StateService
    decision_svc : DecisionService
    inference
        Optional InferenceService for trust enrichment.
    """

    def __init__(self, state_svc, decision_svc, inference=None) -> None:
        self._state_svc    = state_svc
        self._decision_svc = decision_svc
        self._inference    = inference

    # ── Public API ────────────────────────────────────────────────────────────

    def explain(
        self,
        symbol: str,
        *,
        as_of_date: str | None = None,
        has_position: bool = False,
        raw_reasons: list[dict] | None = None,
    ):
        """Return a DecisionExplanation for *symbol*.

        Returns the DecisionExplanation dataclass; call `.to_dict()` for JSON.
        """
        from trade_py.decision.explanation import build_explanation

        db = self._state_svc._db or self._state_svc._open_db()
        as_of = as_of_date
        if not as_of:
            try:
                as_of = db.get_latest_market_asof()
            except Exception:
                as_of = None
        as_of = as_of or date.today().isoformat()

        # 1. WorldState
        trust_score, trust_breakdown = self._get_trust(symbol)
        ws = self._state_svc.build(symbol, as_of_date=as_of, trust_score=trust_score)

        # 2. Scenario + Action
        scenario, action = self._decision_svc.decide(ws, has_position=has_position)

        # 3. Build explanation
        exp = build_explanation(
            ws,
            action,
            trust_breakdown=trust_breakdown,
            scenario=scenario,
            raw_reasons=raw_reasons,
        )
        return exp

    def build_kline_context(
        self,
        symbol: str,
        *,
        days: int = 60,
        as_of_date: str | None = None,
        db=None,
        data_root: str = "data",
        adjust: str = "qfq",
        timeframe: str = "daily",
    ) -> dict[str, Any]:
        """Return kline enrichment payload for /api/kline/{symbol}.

        Reads OHLCV from the kline parquet files, computes per-bar indicators,
        then appends:
        - quote block (latest_price, prev_close, change, change_pct, ...)
        - price_basis block (adjust mode, timeframe, latest_trade_date)
        - belief_overlay (from BeliefState history)
        - prediction block (from InferenceService)
        - recommendation context (from Recommendation table)
        - world_state summary
        - action_decision summary
        - reason_groups (factual grouped reasons from indicators)

        The format matches what the frontend expects.
        """
        _db = db or self._state_svc._open_db()
        as_of = as_of_date
        if not as_of:
            try:
                as_of = _db.get_latest_market_asof()
            except Exception:
                as_of = None
        as_of = as_of or date.today().isoformat()
        today = as_of

        # ── OHLCV + per-bar indicators + quote + price_basis ──────────────────
        ohlcv_rows, indicators_meta, quote, price_basis = self._read_ohlcv(
            data_root, symbol, days, end_date=as_of, adjust=adjust
        )

        # ── Event markers ─────────────────────────────────────────────────────
        event_markers = self._read_event_markers(_db, symbol, days, today)

        # ── Belief overlay ────────────────────────────────────────────────────
        belief_overlay = self._read_belief_overlay(_db, symbol, days, today)

        # ── Prediction from inference ─────────────────────────────────────────
        prediction: dict[str, Any] = {}
        try:
            if self._inference is not None:
                pred_map = self._inference.predict([symbol])
                prediction = pred_map.get(symbol) or {}
        except Exception:
            pass

        # ── World state + action summary ──────────────────────────────────────
        ws_obj = None
        action_decision_obj = None
        state_summary: dict[str, Any] = {}
        action_summary: dict[str, Any] = {}
        try:
            ws_obj = self._state_svc.build(symbol, as_of_date=as_of)
            _, action_decision_obj = self._decision_svc.decide(ws_obj)
            state_summary = ws_obj.to_dict()
            action_summary = action_decision_obj.to_dict()
        except Exception as exc:
            logger.debug("kline_context: state/decision failed for %s: %s", symbol, exc)

        # ── Recommendation context ─────────────────────────────────────────────
        rec_context = self._read_recommendation(_db, symbol, today)

        # ── Grouped factual reasons ───────────────────────────────────────────
        reason_groups = self._generate_reason_groups(
            symbol=symbol,
            ohlcv_rows=ohlcv_rows,
            ws=ws_obj,
            action_decision=action_decision_obj,
            prediction=prediction,
            as_of=as_of,
        )

        return {
            "symbol":         symbol,
            "as_of":          as_of,
            "ohlcv":          ohlcv_rows,
            "indicators":     indicators_meta,
            "quote":          quote,
            "price_basis":    price_basis,
            "event_markers":  event_markers,
            "belief_overlay": belief_overlay,
            "prediction":     prediction,
            "world_state":    state_summary,
            "action":         action_summary,
            "recommendation": rec_context,
            "reason_groups":  reason_groups,
        }

    # ── Private helpers ───────────────────────────────────────────────────────

    def _get_trust(self, symbol: str) -> tuple[float | None, Any]:
        """Return (trust_score, TrustBreakdown | None) from inference layer."""
        if self._inference is None:
            return None, None
        try:
            pred_map = self._inference.predict([symbol])
            p = pred_map.get(symbol) or {}
            trust_dict = p.get("trust") or {}
            score = trust_dict.get("trust_score")
            # Reconstruct a TrustBreakdown if possible
            try:
                from trade_py.trust.breakdown import TrustBreakdown
                tb = TrustBreakdown(
                    trust_score=float(trust_dict.get("trust_score", 0.5)),
                    trust_level=str(trust_dict.get("trust_level", "MEDIUM")),
                    feature_coverage=float(trust_dict.get("feature_coverage", 0.5)),
                    data_freshness_score=float(trust_dict.get("data_freshness_score", 1.0)),
                    warnings=list(trust_dict.get("warnings", [])),
                )
                return score, tb
            except Exception:
                return score, None
        except Exception:
            return None, None

    def _read_ohlcv(
        self, data_root: str, symbol: str, days: int, *,
        end_date: str | None = None,
        adjust: str = "qfq",
    ) -> tuple[list[dict], dict[str, Any], dict[str, Any], dict[str, Any]]:
        """Read OHLCV rows with per-bar indicators, quote block, and price_basis.

        Returns (rows, meta, quote, price_basis).
        Rows include: date, open, high, low, close, volume, amount,
                      turnover_rate, prev_close, vwap,
                      ma5, ma10, ma20, ma60,
                      rsi14, macd_hist, macd_dif, macd_dea, macd_cross,
                      kdj_k, kdj_d, kdj_j, kdj_cross
        """
        import math
        try:
            import numpy as np
            import pandas as pd
            from trade_py.data.access import DataGateway

            resolved_end = date.fromisoformat(end_date) if end_date else date.today()
            gateway = DataGateway(data_root)

            # Request extra bars for indicator warmup:
            # MA60 needs 60, MACD EMA26+9 needs ~35, RSI14 needs 14
            warmup = max(days, 60) + 80
            df, _report = gateway.get_kline(symbol, lookback_bars=warmup, end_date=resolved_end)

            if df.empty:
                return [], {}, {}, {}

            # Normalize date strings, deduplicate, sort ascending
            df["date"] = df["date"].astype(str).str.slice(0, 10)
            df = df.drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)

            # Numeric coercion
            for col in ("open", "high", "low", "close", "volume",
                        "amount", "turnover_rate", "prev_close", "vwap"):
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")

            close = df["close"].ffill()

            # Moving averages
            for n in [5, 10, 20, 60]:
                df[f"ma{n}"] = close.rolling(n, min_periods=n).mean()

            # RSI-14
            delta = close.diff()
            gain = delta.clip(lower=0.0)
            loss = (-delta.clip(upper=0.0))
            avg_gain = gain.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
            avg_loss = loss.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
            rs = avg_gain / avg_loss.replace(0, np.nan)
            df["rsi14"] = (100.0 - 100.0 / (1.0 + rs)).replace([np.inf, -np.inf], np.nan)

            # MACD (EMA12 − EMA26, signal EMA9, histogram)
            ema12 = close.ewm(span=12, adjust=False, min_periods=12).mean()
            ema26 = close.ewm(span=26, adjust=False, min_periods=26).mean()
            dif = ema12 - ema26
            dea = dif.ewm(span=9, adjust=False, min_periods=9).mean()
            hist = dif - dea
            df["macd_dif"] = dif
            df["macd_dea"] = dea
            df["macd_hist"] = hist
            df["macd_cross"] = np.where(
                (dif > dea) & (dif.shift(1) <= dea.shift(1)), 1.0,
                np.where((dif < dea) & (dif.shift(1) >= dea.shift(1)), -1.0, 0.0),
            )

            # KDJ (9-period)
            high = df["high"].fillna(close)
            low_s = df["low"].fillna(close)
            low9 = low_s.rolling(9, min_periods=9).min()
            high9 = high.rolling(9, min_periods=9).max()
            rsv = ((close - low9) / (high9 - low9).replace(0, np.nan) * 100.0).clip(0.0, 100.0)
            k = rsv.ewm(alpha=1 / 3, adjust=False).mean()
            d = k.ewm(alpha=1 / 3, adjust=False).mean()
            j = 3.0 * k - 2.0 * d
            df["kdj_k"] = k
            df["kdj_d"] = d
            df["kdj_j"] = j
            df["kdj_cross"] = np.where(
                (k > d) & (k.shift(1) <= d.shift(1)), 1.0,
                np.where((k < d) & (k.shift(1) >= d.shift(1)), -1.0, 0.0),
            )

            # Trim to requested days (after warmup computed)
            df = df.tail(days).reset_index(drop=True)

            # Serialise rows — include only finite floats
            _float_cols = [
                "open", "high", "low", "close", "volume",
                "amount", "turnover_rate", "prev_close", "vwap",
                "ma5", "ma10", "ma20", "ma60",
                "rsi14", "macd_dif", "macd_dea", "macd_hist", "macd_cross",
                "kdj_k", "kdj_d", "kdj_j", "kdj_cross",
            ]
            rows: list[dict] = []
            for _, row in df.iterrows():
                bar: dict[str, Any] = {"date": str(row["date"])}
                for col in _float_cols:
                    v = row.get(col)
                    if v is not None and not (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
                        bar[col] = round(float(v), 4)
                rows.append(bar)

            # Build quote block from last bar (prefer stored prev_close column)
            quote: dict[str, Any] = {}
            if rows:
                last = rows[-1]
                latest_price = last.get("close")
                prev_close = last.get("prev_close") or None
                # Fallback: use second-to-last close if prev_close absent or zero
                if not prev_close and len(rows) >= 2:
                    prev_close = rows[-2].get("close") or None
                if latest_price is not None and prev_close is not None and prev_close > 0:
                    chg = latest_price - prev_close
                    chg_pct = chg / prev_close
                else:
                    chg = chg_pct = None
                quote = {
                    "latest_price": latest_price,
                    "prev_close":   prev_close,
                    "change":       round(chg, 4) if chg is not None else None,
                    "change_pct":   round(chg_pct, 6) if chg_pct is not None else None,
                    "open":         last.get("open"),
                    "high":         last.get("high"),
                    "low":          last.get("low"),
                    "volume":       last.get("volume"),
                    "amount":       last.get("amount"),
                    # turnover_rate can be negative (akshare delta artifact) — treat as absent
                    "turnover":     last.get("turnover_rate") if (last.get("turnover_rate") or 0) > 0 else None,
                    "vwap":         last.get("vwap"),
                    "as_of":        last.get("date"),
                }

            price_basis: dict[str, Any] = {
                "adjust":            adjust,
                "timeframe":         "daily",
                "latest_trade_date": rows[-1].get("date") if rows else None,
                "quote_as_of":       end_date or resolved_end.isoformat(),
            }

            meta: dict[str, Any] = {
                "rows":  len(rows),
                "start": rows[0].get("date") if rows else None,
                "end":   rows[-1].get("date") if rows else None,
            }
            return rows, meta, quote, price_basis

        except Exception as exc:
            logger.debug("kline_context: ohlcv read failed for %s: %s", symbol, exc)
            return [], {}, {}, {}

    def _generate_reason_groups(
        self,
        *,
        symbol: str,
        ohlcv_rows: list[dict],
        ws: Any,
        action_decision: Any,
        prediction: dict[str, Any],
        as_of: str,
    ) -> dict[str, list[dict]]:
        """Generate factual grouped reasons from indicator data.

        Returns a dict mapping group name → list of ReasonItem dicts.
        Groups: price_trend, technical, volume_liquidity, event_sentiment,
                belief_uncertainty, counter_argument, invalidation
        """
        from trade_py.decision.explanation import ReasonItem

        groups: dict[str, list[ReasonItem]] = {
            "price_trend":       [],
            "technical":         [],
            "volume_liquidity":  [],
            "event_sentiment":   [],
            "belief_uncertainty":[],
            "counter_argument":  [],
            "invalidation":      [],
        }

        # ── Helper ────────────────────────────────────────────────────────────
        def _pct(v: float) -> str:
            sign = "+" if v >= 0 else ""
            return f"{sign}{v * 100:.2f}%"

        def _f(v: float | None, decimals: int = 2) -> str:
            if v is None:
                return "—"
            return f"{v:.{decimals}f}"

        # ── Price / trend reasons ─────────────────────────────────────────────
        closes = [r.get("close") for r in ohlcv_rows if r.get("close") is not None]
        n = len(closes)

        if n >= 2:
            ret1d = (closes[-1] - closes[-2]) / closes[-2]
            polarity = "support" if ret1d > 0.005 else "oppose" if ret1d < -0.005 else "neutral"
            groups["price_trend"].append(ReasonItem(
                id=f"{symbol}_1d_return",
                group="price_trend",
                polarity=polarity,
                title=f"1日收益: {_pct(ret1d)}",
                description=f"收盘价从 {_f(closes[-2])} 变为 {_f(closes[-1])}，1日涨跌 {_pct(ret1d)}",
                source="ohlcv",
                metric_name="return_1d",
                metric_value=round(ret1d, 6),
                metric_unit="%",
                lookback="1d",
                strength=min(1.0, abs(ret1d) / 0.05),
                sort_key=10,
            ))

        if n >= 6:
            ret5d = (closes[-1] - closes[-6]) / closes[-6]
            polarity = "support" if ret5d > 0.02 else "oppose" if ret5d < -0.02 else "neutral"
            groups["price_trend"].append(ReasonItem(
                id=f"{symbol}_5d_return",
                group="price_trend",
                polarity=polarity,
                title=f"5日收益: {_pct(ret5d)}",
                description=f"近5个交易日累计涨跌 {_pct(ret5d)}（从 {_f(closes[-6])} 到 {_f(closes[-1])}）",
                source="ohlcv",
                metric_name="return_5d",
                metric_value=round(ret5d, 6),
                metric_unit="%",
                lookback="5d",
                strength=min(1.0, abs(ret5d) / 0.10),
                sort_key=11,
            ))

        if n >= 21:
            ret20d = (closes[-1] - closes[-21]) / closes[-21]
            polarity = "support" if ret20d > 0.05 else "oppose" if ret20d < -0.05 else "neutral"
            groups["price_trend"].append(ReasonItem(
                id=f"{symbol}_20d_return",
                group="price_trend",
                polarity=polarity,
                title=f"20日收益: {_pct(ret20d)}",
                description=f"近20个交易日累计涨跌 {_pct(ret20d)}（从 {_f(closes[-21])} 到 {_f(closes[-1])}）",
                source="ohlcv",
                metric_name="return_20d",
                metric_value=round(ret20d, 6),
                metric_unit="%",
                lookback="20d",
                strength=min(1.0, abs(ret20d) / 0.20),
                sort_key=12,
            ))

        # MA20 relationship (use ma20 from last bar if available)
        if ohlcv_rows:
            last = ohlcv_rows[-1]
            ma20 = last.get("ma20")
            ma5 = last.get("ma5")
            close_now = last.get("close")
            if ma20 and close_now:
                gap = (close_now - ma20) / ma20
                polarity = "support" if gap > 0.01 else "oppose" if gap < -0.01 else "neutral"
                groups["price_trend"].append(ReasonItem(
                    id=f"{symbol}_price_vs_ma20",
                    group="price_trend",
                    polarity=polarity,
                    title=f"价格 vs MA20: {_pct(gap)}",
                    description=f"收盘价 {_f(close_now)} 位于MA20 ({_f(ma20)}) {'上方' if gap >= 0 else '下方'} {_pct(abs(gap))}",
                    source="technical",
                    metric_name="price_vs_ma20",
                    metric_value=round(gap, 6),
                    metric_unit="%",
                    strength=min(1.0, abs(gap) / 0.05),
                    sort_key=13,
                ))

            # MA5 vs MA20 golden/death cross — check last 3 bars
            if ma5 and ma20:
                # Detect recent cross in last 5 bars
                recent_bars = ohlcv_rows[-5:]
                cross_date = None
                cross_type = None
                for i in range(1, len(recent_bars)):
                    pm5 = recent_bars[i-1].get("ma5")
                    pm20 = recent_bars[i-1].get("ma20")
                    cm5 = recent_bars[i].get("ma5")
                    cm20 = recent_bars[i].get("ma20")
                    if pm5 and pm20 and cm5 and cm20:
                        if pm5 <= pm20 and cm5 > cm20:
                            cross_date = recent_bars[i].get("date")
                            cross_type = "golden"
                        elif pm5 >= pm20 and cm5 < cm20:
                            cross_date = recent_bars[i].get("date")
                            cross_type = "death"
                if cross_type:
                    polarity = "support" if cross_type == "golden" else "oppose"
                    label = "金叉" if cross_type == "golden" else "死叉"
                    groups["technical"].append(ReasonItem(
                        id=f"{symbol}_ma_cross",
                        group="technical",
                        polarity=polarity,
                        title=f"MA5/MA20 {label}（{cross_date}）",
                        description=f"MA5 ({_f(ma5)}) 于 {cross_date} {'上穿' if cross_type == 'golden' else '下穿'} MA20 ({_f(ma20)})",
                        source="technical",
                        metric_name="ma5_vs_ma20",
                        metric_value=round((ma5 - ma20) / ma20, 6) if ma20 else None,
                        strength=0.7,
                        sort_key=20,
                    ))

        # ── Technical reasons ─────────────────────────────────────────────────
        if ohlcv_rows:
            last = ohlcv_rows[-1]

            # RSI14
            rsi = last.get("rsi14")
            if rsi is not None:
                if rsi >= 70:
                    polarity, desc = "warning", f"RSI14 = {_f(rsi, 1)}，处于超买区域（>70），注意回调风险"
                    title = f"RSI14 超买 ({_f(rsi, 1)})"
                elif rsi <= 30:
                    polarity, desc = "support", f"RSI14 = {_f(rsi, 1)}，处于超卖区域（<30），可能存在反弹机会"
                    title = f"RSI14 超卖 ({_f(rsi, 1)})"
                elif 50 < rsi < 70:
                    polarity, desc = "support", f"RSI14 = {_f(rsi, 1)}，动能偏强"
                    title = f"RSI14 偏强 ({_f(rsi, 1)})"
                elif 30 < rsi < 50:
                    polarity, desc = "neutral", f"RSI14 = {_f(rsi, 1)}，动能偏弱"
                    title = f"RSI14 偏弱 ({_f(rsi, 1)})"
                else:
                    polarity, desc = "neutral", f"RSI14 = {_f(rsi, 1)}，处于中性区间"
                    title = f"RSI14 中性 ({_f(rsi, 1)})"

                # Check if RSI recently rebounded from oversold
                if len(ohlcv_rows) >= 5:
                    prev_rsis = [r.get("rsi14") for r in ohlcv_rows[-5:-1] if r.get("rsi14") is not None]
                    if prev_rsis and min(prev_rsis) < 30 and rsi > 35:
                        desc += f"（5日前RSI最低 {_f(min(prev_rsis), 1)}，已从超卖区反弹）"

                groups["technical"].append(ReasonItem(
                    id=f"{symbol}_rsi14",
                    group="technical",
                    polarity=polarity,
                    title=title,
                    description=desc,
                    source="technical",
                    metric_name="rsi14",
                    metric_value=round(rsi, 2),
                    lookback="14d",
                    strength=abs(rsi - 50) / 50,
                    sort_key=21,
                ))

            # MACD
            macd_hist = last.get("macd_hist")
            macd_dif = last.get("macd_dif")
            macd_dea = last.get("macd_dea")
            macd_cross = last.get("macd_cross")
            if macd_hist is not None:
                if macd_cross == 1.0:
                    polarity = "support"
                    title = "MACD 金叉（DIF上穿DEA）"
                    desc = f"DIF ({_f(macd_dif, 4)}) 今日上穿DEA ({_f(macd_dea, 4)})，柱状图转正"
                elif macd_cross == -1.0:
                    polarity = "oppose"
                    title = "MACD 死叉（DIF下穿DEA）"
                    desc = f"DIF ({_f(macd_dif, 4)}) 今日下穿DEA ({_f(macd_dea, 4)})，柱状图转负"
                elif macd_hist > 0:
                    polarity = "support"
                    title = f"MACD 柱状图为正 ({_f(macd_hist, 4)})"
                    desc = f"MACD柱状图 {_f(macd_hist, 4)} > 0，多头动能持续"
                else:
                    polarity = "oppose"
                    title = f"MACD 柱状图为负 ({_f(macd_hist, 4)})"
                    desc = f"MACD柱状图 {_f(macd_hist, 4)} < 0，空头动能持续"

                groups["technical"].append(ReasonItem(
                    id=f"{symbol}_macd",
                    group="technical",
                    polarity=polarity,
                    title=title,
                    description=desc,
                    source="technical",
                    metric_name="macd_hist",
                    metric_value=round(macd_hist, 6) if macd_hist else None,
                    strength=min(1.0, abs(macd_hist) / max(1e-6, abs(macd_dif or 1e-6))),
                    sort_key=22,
                ))

            # KDJ cross
            kdj_k = last.get("kdj_k")
            kdj_d = last.get("kdj_d")
            kdj_j = last.get("kdj_j")
            kdj_cross = last.get("kdj_cross")
            if kdj_k is not None:
                if kdj_cross == 1.0:
                    polarity = "support"
                    title = f"KDJ 金叉（K上穿D，K={_f(kdj_k, 1)}）"
                    desc = f"KDJ K线 ({_f(kdj_k, 1)}) 上穿D线 ({_f(kdj_d, 1)})，J线={_f(kdj_j, 1)}"
                elif kdj_cross == -1.0:
                    polarity = "oppose"
                    title = f"KDJ 死叉（K下穿D，K={_f(kdj_k, 1)}）"
                    desc = f"KDJ K线 ({_f(kdj_k, 1)}) 下穿D线 ({_f(kdj_d, 1)})，J线={_f(kdj_j, 1)}"
                elif kdj_k > 80:
                    polarity = "warning"
                    title = f"KDJ 超买区（K={_f(kdj_k, 1)}）"
                    desc = f"K值 {_f(kdj_k, 1)} > 80，处于超买区域"
                elif kdj_k < 20:
                    polarity = "support"
                    title = f"KDJ 超卖区（K={_f(kdj_k, 1)}）"
                    desc = f"K值 {_f(kdj_k, 1)} < 20，处于超卖区域"
                else:
                    polarity = "neutral"
                    title = f"KDJ 中性（K={_f(kdj_k, 1)}, D={_f(kdj_d, 1)}）"
                    desc = f"KDJ K={_f(kdj_k, 1)}, D={_f(kdj_d, 1)}, J={_f(kdj_j, 1)}，无明显信号"

                groups["technical"].append(ReasonItem(
                    id=f"{symbol}_kdj",
                    group="technical",
                    polarity=polarity,
                    title=title,
                    description=desc,
                    source="technical",
                    metric_name="kdj_k",
                    metric_value=round(kdj_k, 2) if kdj_k is not None else None,
                    strength=0.5,
                    sort_key=23,
                ))

        # ── Volume / liquidity reasons ─────────────────────────────────────────
        if n >= 2 and ohlcv_rows:
            last = ohlcv_rows[-1]
            volumes = [r.get("volume") for r in ohlcv_rows if r.get("volume") is not None]
            if len(volumes) >= 5:
                avg5 = sum(volumes[-5:]) / 5
                avg20 = sum(volumes[-min(20, len(volumes)):]) / min(20, len(volumes))
                vol_ratio = avg5 / avg20 if avg20 > 0 else 1.0
                if vol_ratio >= 1.5:
                    polarity = "support"
                    title = f"近5日成交量放大 ({_f(vol_ratio, 2)}x 20日均量)"
                    desc = f"近5日均量是20日均量的 {_f(vol_ratio, 2)} 倍，量能显著放大"
                elif vol_ratio <= 0.6:
                    polarity = "warning"
                    title = f"近5日成交量萎缩 ({_f(vol_ratio, 2)}x 20日均量)"
                    desc = f"近5日均量仅为20日均量的 {_f(vol_ratio, 2)} 倍，成交持续萎缩"
                else:
                    polarity = "neutral"
                    title = f"成交量正常 ({_f(vol_ratio, 2)}x 20日均量)"
                    desc = f"近5日均量为20日均量的 {_f(vol_ratio, 2)} 倍，成交活跃度正常"

                groups["volume_liquidity"].append(ReasonItem(
                    id=f"{symbol}_volume_ratio",
                    group="volume_liquidity",
                    polarity=polarity,
                    title=title,
                    description=desc,
                    source="ohlcv",
                    metric_name="volume_ratio_5_20",
                    metric_value=round(vol_ratio, 4),
                    lookback="5d/20d",
                    strength=min(1.0, abs(vol_ratio - 1.0) / 0.5),
                    sort_key=30,
                ))

        # ── Event / sentiment from WorldState signals ──────────────────────────
        if ws is not None:
            for sig in (getattr(ws, "supporting_signals", None) or []):
                src = str(sig.get("source", "signal"))
                if any(x in src.lower() for x in ("event", "sentiment", "news", "kg")):
                    groups["event_sentiment"].append(ReasonItem(
                        id=f"{symbol}_event_sup_{src}",
                        group="event_sentiment",
                        polarity="support",
                        title=str(sig.get("description", src))[:80],
                        description=str(sig.get("description", "")),
                        source=src,
                        strength=float(sig.get("strength", 0.5)),
                        sort_key=40,
                    ))
            for sig in (getattr(ws, "opposing_signals", None) or []):
                src = str(sig.get("source", "signal"))
                if any(x in src.lower() for x in ("event", "sentiment", "news", "kg")):
                    groups["event_sentiment"].append(ReasonItem(
                        id=f"{symbol}_event_opp_{src}",
                        group="event_sentiment",
                        polarity="oppose",
                        title=str(sig.get("description", src))[:80],
                        description=str(sig.get("description", "")),
                        source=src,
                        strength=float(sig.get("strength", 0.5)),
                        sort_key=41,
                    ))

        # ── Belief / uncertainty ──────────────────────────────────────────────
        trust_score: float | None = None
        trust_level = "MEDIUM"
        if prediction:
            trust_dict = prediction.get("trust") or {}
            trust_score = trust_dict.get("trust_score")
            trust_level = str(trust_dict.get("trust_level", "MEDIUM"))
        elif ws is not None:
            trust_score = getattr(ws, "trust_score", None)

        if trust_score is not None:
            if trust_score < 0.4:
                polarity = "warning"
                title = f"模型置信度低 ({int(trust_score * 100)}%)"
                desc = (f"当前置信分为 {int(trust_score * 100)}%，建议以审查模式参考决策，"
                        "部分输入特征可能缺失或过期")
            elif trust_score < 0.7:
                polarity = "neutral"
                title = f"模型置信度中等 ({int(trust_score * 100)}%)"
                desc = f"当前置信分为 {int(trust_score * 100)}%，决策可参考但需关注数据质量"
            else:
                polarity = "support"
                title = f"模型置信度高 ({int(trust_score * 100)}%)"
                desc = f"当前置信分为 {int(trust_score * 100)}%，数据完整度良好"

            groups["belief_uncertainty"].append(ReasonItem(
                id=f"{symbol}_trust",
                group="belief_uncertainty",
                polarity=polarity,
                title=title,
                description=desc,
                source="model",
                metric_name="trust_score",
                metric_value=round(trust_score, 4),
                metric_unit="%",
                strength=trust_score,
                sort_key=50,
            ))

        if ws is not None:
            unc = getattr(ws, "uncertainty_level", None)
            if unc == "HIGH":
                groups["belief_uncertainty"].append(ReasonItem(
                    id=f"{symbol}_high_uncertainty",
                    group="belief_uncertainty",
                    polarity="warning",
                    title="高不确定性",
                    description="当前市场不确定性评级为HIGH，信号置信度受影响，建议等待确认",
                    source="world_state",
                    strength=0.8,
                    sort_key=51,
                ))

        # ── Counter-arguments ─────────────────────────────────────────────────
        if ws is not None:
            for sig in (getattr(ws, "opposing_signals", None) or []):
                src = str(sig.get("source", "signal"))
                if not any(x in src.lower() for x in ("event", "sentiment", "news", "kg")):
                    groups["counter_argument"].append(ReasonItem(
                        id=f"{symbol}_counter_{src}",
                        group="counter_argument",
                        polarity="oppose",
                        title=str(sig.get("description", src))[:80],
                        description=str(sig.get("description", "")),
                        source=src,
                        strength=float(sig.get("strength", 0.5)),
                        sort_key=60,
                    ))

        # ── Invalidation conditions ───────────────────────────────────────────
        if action_decision is not None:
            for i, inv in enumerate(getattr(action_decision, "invalidators", []) or []):
                groups["invalidation"].append(ReasonItem(
                    id=f"{symbol}_inv_{i}",
                    group="invalidation",
                    polarity="warning",
                    title=str(inv)[:80],
                    description=str(inv),
                    source="decision",
                    strength=0.6,
                    sort_key=70 + i,
                ))

        # Remove empty groups and convert to dicts
        return {
            group: [item.to_dict() for item in items]
            for group, items in groups.items()
            if items
        }

    def _read_event_markers(
        self, db, symbol: str, days: int, as_of: str
    ) -> list[dict[str, Any]]:
        """Read recent market_events for event markers overlay."""
        markers: list[dict[str, Any]] = []
        try:
            cutoff = (date.fromisoformat(as_of) - timedelta(days=days)).isoformat()
            with db._conn_lock:
                rows = db._conn.execute(
                    """
                    SELECT me.event_date, me.event_type, ep.kg_score, me.summary
                    FROM event_propagations ep
                    JOIN market_events me ON me.event_id = ep.event_id
                    WHERE ep.symbol = ? AND me.event_date >= ? AND me.event_date <= ?
                    ORDER BY me.event_date, ep.kg_score DESC
                    LIMIT 24
                    """,
                    (symbol, cutoff, as_of),
                ).fetchall()
            for r in rows:
                markers.append({
                    "date":       r[0],
                    "event_type": r[1],
                    "kg_score":   round(float(r[2] or 0.0), 4),
                    "title":      r[3] or "",
                })
        except Exception as exc:
            logger.debug("kline_context: event markers read failed for %s: %s", symbol, exc)
        return markers

    def _read_belief_overlay(
        self, db, symbol: str, days: int, today: str
    ) -> list[dict[str, Any]]:
        """Read belief_state history for overlay chart."""
        overlay: list[dict[str, Any]] = []
        try:
            cur = date.fromisoformat(today)
            for _ in range(days):
                dstr = cur.isoformat()
                row = db.belief_state_get(dstr, symbol)
                if row:
                    bv = row.get("belief_vec") or {}
                    overlay.append({
                        "date":  dstr,
                        "mu":    round(float(bv.get("mu", 0.0)), 4),
                        "sigma": round(float(bv.get("sigma", 0.3)), 4),
                    })
                cur -= timedelta(days=1)
            overlay.sort(key=lambda x: x["date"])
        except Exception as exc:
            logger.debug("kline_context: belief overlay read failed for %s: %s", symbol, exc)
        return overlay

    def _read_recommendation(
        self, db, symbol: str, as_of: str
    ) -> dict[str, Any]:
        """Read latest Recommendation row for the symbol."""
        try:
            with db._conn_lock:
                row = db._conn.execute(
                    """
                    SELECT as_of_date, action, conviction, score, expected_return_5d,
                           confidence_interval_low, confidence_interval_high
                    FROM Recommendation
                    WHERE symbol = ? AND as_of_date <= ?
                    ORDER BY as_of_date DESC LIMIT 1
                    """,
                    (symbol, as_of),
                ).fetchone()
            if row:
                return {
                    "as_of_date":              row[0],
                    "action":                  row[1],
                    "conviction":              row[2],
                    "score":                   round(float(row[3] or 0.0), 4),
                    "expected_return_5d":       round(float(row[4] or 0.0), 4),
                    "confidence_interval_low":  row[5],
                    "confidence_interval_high": row[6],
                }
        except Exception as exc:
            logger.debug("kline_context: recommendation read failed for %s: %s", symbol, exc)
        return {}
