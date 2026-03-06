from __future__ import annotations

"""Trade Decision Support System — Streamlit Web UI

Entry point:
    uv run streamlit run trade_py/ui/ui.py

Tabs:
    1. 📋 今日晨报  — daily morning brief
    2. 📊 标的分析  — stock analysis + prediction verdict
    3. ⚡ 信号监控  — watchlist signal monitor
    4. 📓 决策日志  — decision journal + bias analysis
    5. ⚙️ 设置     — user-tunable parameters
"""

import streamlit as st

from trade_py.ui.tabs import tab_brief, tab_analysis, tab_signals, tab_journal, tab_settings


def _setup_page() -> None:
    st.set_page_config(
        page_title="Trade · 决策支持系统",
        page_icon="📈",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    # Minimal custom CSS for a cleaner look
    st.markdown("""
        <style>
        /* Tighten up top padding */
        .block-container { padding-top: 1rem; }
        /* Hide Streamlit's default header & footer */
        #MainMenu, footer { visibility: hidden; }
        /* Make tab labels a bit larger */
        button[data-baseweb="tab"] { font-size: 1rem; }
        </style>
    """, unsafe_allow_html=True)


def main() -> None:
    _setup_page()

    st.title("📈 Trade · 决策支持系统")

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📋 今日晨报",
        "📊 标的分析",
        "⚡ 信号监控",
        "📓 决策日志",
        "⚙️ 设置",
    ])

    with tab1:

        tab_brief.render()

    with tab2:
        tab_analysis.render()

    with tab3:
        tab_signals.render()

    with tab4:
        tab_journal.render()

    with tab5:
        tab_settings.render()


main()
