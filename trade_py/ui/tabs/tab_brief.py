from __future__ import annotations

"""Tab 1 — 今日晨报 (Morning Brief)

Reads the pre-generated daily brief from data/briefs/YYYY-MM-DD.md.
Falls back to a placeholder when the file doesn't exist yet.
"""

import datetime
from pathlib import Path

import streamlit as st


def _data_root() -> Path:
    return Path(__file__).parent.parent.parent.parent / "data"


def _load_brief(date: datetime.date) -> str | None:
    path = _data_root() / "briefs" / f"{date}.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


def render() -> None:
    st.header("📋 今日晨报")

    today = datetime.date.today()
    col_date, col_refresh = st.columns([3, 1])
    with col_date:
        selected_date = st.date_input("日期", value=today, max_value=today)
    with col_refresh:
        st.write("")  # vertical align
        refresh = st.button("🔄 刷新")

    if refresh:
        st.rerun()

    brief_md = _load_brief(selected_date)

    if brief_md:
        st.markdown(brief_md)
    else:
        # Placeholder structure until morning_brief.py is implemented
        st.info(f"📄 {selected_date} 的晨报尚未生成。请在 09:10 后刷新，或手动运行 `uv run python -m trade_py.cli.main report brief`。")

        with st.expander("示例晨报结构（占位）", expanded=True):
            st.markdown("""
### 宏观环境

| 指标 | 值 | 状态 |
|------|----|------|
| 大盘情绪 | — | 待采集 |
| 北向资金 | — | 待采集 |
| 美股夜盘 | — | 待采集 |

---

### 今日建议

> ⏳ 等待数据采集完成

---

### 重点关注

*自选池为空或数据未就绪*

---

### 昨日回溯

*决策日志为空*

---

### 今日情报（三句话）

*LLM 情报摘要未生成*
""")

    # Watchlist summary below brief
    st.divider()
    _render_watchlist_summary()


def _render_watchlist_summary() -> None:
    """Show a quick watchlist status pulled from the settings DB."""
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent))
        from trade_py.db.settings_db import SettingsDB
        db = SettingsDB(str(_data_root().parent / "data"))
        symbols = db.watchlist_get()
    except Exception:
        symbols = []

    st.subheader("自选池快览")
    if not symbols:
        st.caption("自选池为空 — 在「信号监控」或「标的分析」中添加股票")
    else:
        for sym in symbols:
            st.text(sym)
