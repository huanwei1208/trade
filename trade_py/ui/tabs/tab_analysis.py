from __future__ import annotations

"""Tab 2 — 标的分析 (Stock Analysis)

Enter a symbol to get: K-line chart, prediction verdict, pro/con evidence,
devil's advocate, risk metrics.
"""

from pathlib import Path

import pandas as pd
import streamlit as st


def _data_root() -> Path:
    return Path(__file__).parent.parent.parent.parent / "data"


def _load_kline(symbol: str) -> pd.DataFrame | None:
    """Load all kline parquet files for the given symbol."""
    kline_dir = _data_root() / "kline"
    if not kline_dir.exists():
        return None
    frames = []
    sym_file = symbol.replace(".", "_") + ".parquet"
    for month_dir in sorted(kline_dir.iterdir()):
        p = month_dir / sym_file
        if p.exists():
            frames.append(pd.read_parquet(p))
    if not frames:
        return None
    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date")


def _add_to_watchlist(symbol: str) -> None:
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent))
        from trade_py.db.settings_db import SettingsDB
        db = SettingsDB(str(_data_root()))
        db.watchlist_add(symbol)
        st.toast(f"✅ {symbol} 已加入自选池")
    except Exception as e:
        st.error(f"加入自选池失败: {e}")


def render() -> None:
    st.header("📊 标的分析")

    col_input, col_btn, col_watch = st.columns([3, 1, 1])
    with col_input:
        symbol = st.text_input(
            "股票代码",
            placeholder="如 600000.SH 或 000858.SZ",
            label_visibility="collapsed",
        ).strip().upper()
    with col_btn:
        analyze = st.button("分析", type="primary", use_container_width=True)
    with col_watch:
        watch = st.button("⭐ 加自选", use_container_width=True)

    if watch and symbol:
        _add_to_watchlist(symbol)

    if not symbol:
        st.info("请输入股票代码后点击「分析」")
        return

    if not analyze and "last_analyzed_symbol" not in st.session_state:
        st.info("点击「分析」开始分析")
        return

    if analyze:
        st.session_state["last_analyzed_symbol"] = symbol

    symbol = st.session_state.get("last_analyzed_symbol", symbol)

    # ── K-line chart ──────────────────────────────────────────
    st.subheader(f"{symbol} — K线图")

    period = st.radio(
        "周期",
        ["1M", "3M", "6M", "1Y", "全部"],
        horizontal=True,
        label_visibility="collapsed",
    )
    period_days = {"1M": 30, "3M": 90, "6M": 180, "1Y": 365, "全部": 99999}

    df = _load_kline(symbol)
    if df is not None and not df.empty:
        import datetime
        cutoff = pd.Timestamp.today() - pd.Timedelta(days=period_days[period])
        df_view = df[df["date"] >= cutoff]

        import plotly.graph_objects as go
        fig = go.Figure()
        fig.add_trace(go.Candlestick(
            x=df_view["date"],
            open=df_view["open"],
            high=df_view["high"],
            low=df_view["low"],
            close=df_view["close"],
            name="K线",
        ))
        if "volume" in df_view.columns:
            fig.add_trace(go.Bar(
                x=df_view["date"],
                y=df_view["volume"],
                name="成交量",
                yaxis="y2",
                opacity=0.4,
                marker_color="gray",
            ))
        fig.update_layout(
            xaxis_rangeslider_visible=False,
            yaxis2=dict(overlaying="y", side="right", showgrid=False),
            height=400,
            margin=dict(l=0, r=0, t=20, b=0),
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning(f"未找到 {symbol} 的K线数据。请先运行数据采集。")

    # ── Prediction verdict ─────────────────────────────────────
    st.subheader("判决书")

    from trade_py.ui.services.cpp_bridge import cli_available, get_predict, get_risk
    if not cli_available():
        st.warning("trade_cli 未找到，无法生成预测。请先编译项目。")
        _render_verdict_placeholder()
        return

    with st.spinner("正在调用 trade_cli 生成预测…"):
        pred = get_predict(symbol)
        risk = get_risk(symbol)

    if "error" in pred:
        st.error(f"预测失败: {pred['error']}")
        _render_verdict_placeholder()
    else:
        _render_verdict(pred, risk)


def _render_verdict(pred: dict, risk: dict) -> None:
    prob = pred.get("probability", pred.get("bull_prob", None))
    window_score = pred.get("window_score", "—")
    action = pred.get("action_condition", "—")

    col1, col2, col3 = st.columns(3)
    with col1:
        if prob is not None:
            label = "看涨" if prob >= 0.5 else "看跌"
            delta = f"{abs(prob - 0.5) * 200:.0f}% 偏离中性"
            st.metric("预测概率", f"{label} {prob * 100:.1f}%", delta)
        else:
            st.metric("预测概率", "—")
    with col2:
        st.metric("窗口质量", f"{window_score}/100" if isinstance(window_score, (int, float)) else str(window_score))
    with col3:
        vol = risk.get("annual_vol", risk.get("annualized_vol", None))
        st.metric("年化波动率", f"{vol * 100:.1f}%" if vol else "—")

    st.markdown(f"**行动条件：** {action}")

    pro = pred.get("supporting_evidence", [])
    con = pred.get("opposing_evidence", [])
    col_pro, col_con = st.columns(2)
    with col_pro:
        st.markdown("**支持证据 ✅**")
        for e in pro:
            st.markdown(f"- {e}")
        if not pro:
            st.caption("暂无")
    with col_con:
        st.markdown("**反驳证据 ❌**")
        for e in con:
            st.markdown(f"- {e}")
        if not con:
            st.caption("暂无")

    devil = pred.get("devils_advocate", "")
    if devil:
        with st.expander("👹 魔鬼代理人"):
            st.markdown(devil)

    # Risk metrics
    if risk and "error" not in risk:
        with st.expander("风险指标"):
            st.json(risk)


def _render_verdict_placeholder() -> None:
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("预测概率", "—", "需编译 trade_cli")
    with col2:
        st.metric("窗口质量", "—")
    with col3:
        st.metric("年化波动率", "—")
