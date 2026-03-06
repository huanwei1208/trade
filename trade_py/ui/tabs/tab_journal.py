from __future__ import annotations

"""Tab 4 — 决策日志 (Decision Journal)

View past decisions, track outcomes, analyze personal biases.
"""

import datetime
from pathlib import Path

import streamlit as st


def _data_root() -> Path:
    return Path(__file__).parent.parent.parent.parent / "data"


def _load_journal() -> "pd.DataFrame | None":
    path = _data_root() / "journal" / "decisions.parquet"
    if not path.exists():
        return None
    try:
        import pandas as pd
        df = pd.read_parquet(path)
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
        return df.sort_values("date", ascending=False) if "date" in df.columns else df
    except Exception:
        return None


def render() -> None:
    st.header("📓 决策日志")

    col_new, _ = st.columns([1, 3])
    with col_new:
        if st.button("➕ 新增决策记录", type="primary"):
            st.session_state["show_new_decision_form"] = True

    if st.session_state.get("show_new_decision_form"):
        _render_new_decision_form()
        st.divider()

    df = _load_journal()

    if df is None or df.empty:
        st.info("决策日志为空。在「标的分析」中点击「记录决策」，或手动新增。")
        _render_empty_stats()
        return

    # ── Recent decisions table ─────────────────────────────────
    st.subheader("近期决策")

    display_cols = [c for c in ["date", "symbol", "direction", "probability", "actual_return", "outcome"]
                    if c in df.columns]
    col_rename = {
        "date": "日期", "symbol": "股票", "direction": "方向",
        "probability": "概率", "actual_return": "实际收益", "outcome": "结果",
    }
    show_df = df[display_cols].rename(columns=col_rename).head(50)
    st.dataframe(show_df, use_container_width=True, hide_index=True)

    st.divider()

    # ── Bias analysis ──────────────────────────────────────────
    st.subheader("偏差分析")
    _render_bias_analysis(df)

    st.divider()

    # ── Monthly performance ────────────────────────────────────
    st.subheader("月度绩效")
    _render_monthly_perf(df)

    col_export, _ = st.columns([1, 3])
    with col_export:
        if st.button("📤 导出报告"):
            _export_report(df)


def _render_new_decision_form() -> None:
    st.subheader("新增决策记录")
    with st.form("new_decision"):
        col1, col2, col3 = st.columns(3)
        with col1:
            symbol = st.text_input("股票代码", placeholder="600000.SH")
        with col2:
            direction = st.selectbox("方向", ["买入", "卖出", "观望"])
        with col3:
            emotion = st.selectbox("情绪", ["neutral", "confident", "fearful_but_confident", "fearful", "greedy", "contrarian"])
        reason = st.text_area("决策理由（叙事）", placeholder="为什么做这个决定？")
        submitted = st.form_submit_button("保存")

        if submitted and symbol:
            _save_decision(symbol.strip().upper(), direction, reason, emotion)
            st.session_state["show_new_decision_form"] = False
            st.rerun()


def _save_decision(symbol: str, direction: str, narrative: str, emotion: str) -> None:
    action_map = {"买入": "buy", "卖出": "sell", "观望": "hold"}
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent))
        from trade_py.journal.decision_journal import DecisionJournal
        journal = DecisionJournal(str(_data_root()))
        journal.log(
            symbol=symbol,
            action=action_map.get(direction, direction),
            narrative=narrative or direction,
            emotion=emotion,
            indicators=[],
            amount=0.0,
        )
        st.toast(f"✅ 决策已记录: {symbol} {direction}")
    except Exception as e:
        st.error(f"保存失败: {e}")


def _render_bias_analysis(df: "pd.DataFrame") -> None:
    try:
        import numpy as np

        total = len(df)
        if total == 0:
            st.caption("数据不足")
            return

        outcome_col = next((c for c in ["outcome", "result"] if c in df.columns), None)
        if outcome_col:
            correct = (df[outcome_col].astype(str).str.startswith("✅") |
                       (df[outcome_col] == 1) |
                       (df[outcome_col].astype(str).str.lower() == "true")).sum()
            win_rate = correct / total if total > 0 else 0
        else:
            win_rate = None

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("总信号数", total)
        with col2:
            st.metric("胜率", f"{win_rate * 100:.1f}%" if win_rate is not None else "—")
        with col3:
            hold_col = next((c for c in ["direction", "action"] if c in df.columns), None)
            if hold_col:
                watch_count = (df[hold_col].astype(str).str.contains("观望")).sum()
                st.metric("观望次数", watch_count)
            else:
                st.metric("观望次数", "—")

        # Per-industry breakdown if available
        if "industry" in df.columns and outcome_col:
            st.markdown("**板块胜率**")
            by_industry = df.groupby("industry")[outcome_col].apply(
                lambda s: ((s == 1) | s.astype(str).str.startswith("✅")).mean()
            ).sort_values()
            worst = by_industry.head(3)
            for ind, rate in worst.items():
                st.warning(f"⚠ {ind} 胜率 {rate * 100:.0f}%（偏低）")

    except Exception as e:
        st.caption(f"偏差分析计算失败: {e}")


def _render_monthly_perf(df: "pd.DataFrame") -> None:
    try:
        if "date" not in df.columns:
            st.caption("无日期数据")
            return

        df = df.copy()
        df["month"] = df["date"].dt.to_period("M")
        outcome_col = next((c for c in ["outcome", "result"] if c in df.columns), None)

        monthly = df.groupby("month").agg(
            总信号=("symbol", "count"),
        )
        if outcome_col:
            correct = df.groupby("month")[outcome_col].apply(
                lambda s: ((s == 1) | s.astype(str).str.startswith("✅")).sum()
            )
            monthly["胜出"] = correct

        monthly = monthly.tail(6)
        st.dataframe(monthly, use_container_width=True)

    except Exception as e:
        st.caption(f"月度统计失败: {e}")


def _render_empty_stats() -> None:
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("总信号数", "0")
    with col2:
        st.metric("胜率", "—")
    with col3:
        st.metric("观望次数", "0")


def _export_report(df: "pd.DataFrame") -> None:
    try:
        csv = df.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "下载 CSV",
            data=csv,
            file_name=f"decisions_{datetime.date.today()}.csv",
            mime="text/csv",
        )
    except Exception as e:
        st.error(f"导出失败: {e}")
