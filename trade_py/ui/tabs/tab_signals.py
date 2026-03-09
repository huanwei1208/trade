from __future__ import annotations

"""Tab 3 — 信号监控 (Signal Monitor)

Displays watchlist with latest signals, macro headlines, cross-asset prices.
Auto-refreshes every 5 minutes during market hours (09:30–15:00 CST).
"""

import datetime
from pathlib import Path

import streamlit as st

from trade_py.data.access import DataGateway


_MARKET_OPEN = datetime.time(9, 30)
_MARKET_CLOSE = datetime.time(15, 0)


def _is_market_hours() -> bool:
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).time()
    return _MARKET_OPEN <= now <= _MARKET_CLOSE


def _data_root() -> Path:
    return Path(__file__).parent.parent.parent.parent / "data"


def _get_watchlist() -> list[str]:
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent))
        from trade_py.db.settings_db import SettingsDB
        db = SettingsDB(str(_data_root()))
        return db.watchlist_get()
    except Exception:
        return []


def _get_signal_cache(date_str: str) -> list[dict]:
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent))
        from trade_py.db.settings_db import SettingsDB
        db = SettingsDB(str(_data_root()))
        return db.signal_cache_get(date_str)
    except Exception:
        return []


def render() -> None:
    st.header("⚡ 信号监控")

    in_market = _is_market_hours()
    if in_market:
        st.success("🟢 交易时段 — 每5分钟自动刷新")
        # Auto-refresh every 5 minutes during market hours
        if "signal_refresh_count" not in st.session_state:
            st.session_state["signal_refresh_count"] = 0
        st.caption(f"上次更新：{datetime.datetime.now().strftime('%H:%M:%S')}")
    else:
        st.info("🔴 非交易时段 — 显示最新快照")

    col_refresh, col_add = st.columns([1, 3])
    with col_refresh:
        if st.button("🔄 手动刷新"):
            st.rerun()

    # ── Watchlist table ────────────────────────────────────────
    st.subheader("自选池")
    symbols = _get_watchlist()

    if not symbols:
        st.info("自选池为空。在「标的分析」中搜索并加入股票。")
    else:
        today_str = datetime.date.today().isoformat()
        cache_by_symbol = {r["symbol"]: r for r in _get_signal_cache(today_str)}

        rows = []
        for sym in symbols:
            cache = cache_by_symbol.get(sym, {})
            rows.append({
                "股票": sym,
                "窗口分": cache.get("window_score", "—"),
                "信号": cache.get("large_order_trend", "—"),
                "智能资金": "✅" if cache.get("smart_money_signal") == 1 else ("❌" if cache.get("smart_money_signal") == 0 else "—"),
            })

        import pandas as pd
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)

        # Add / remove symbols
        with st.expander("管理自选池"):
            col_sym, col_add_btn = st.columns([3, 1])
            with col_sym:
                new_sym = st.text_input("添加股票", placeholder="600000.SH", label_visibility="collapsed")
            with col_add_btn:
                if st.button("添加", use_container_width=True) and new_sym:
                    _add_to_watchlist(new_sym.strip().upper())
                    st.rerun()

            remove_sym = st.selectbox("移除股票", [""] + symbols)
            if st.button("移除") and remove_sym:
                _remove_from_watchlist(remove_sym)
                st.rerun()

    st.divider()

    # ── Macro headlines ────────────────────────────────────────
    st.subheader("宏观快讯")
    _render_macro_headlines()

    st.divider()

    # ── Cross-asset prices ─────────────────────────────────────
    st.subheader("跨资产")
    _render_cross_asset()


def _add_to_watchlist(symbol: str) -> None:
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent))
        from trade_py.db.settings_db import SettingsDB
        db = SettingsDB(str(_data_root()))
        db.watchlist_add(symbol)
        st.toast(f"✅ {symbol} 已加入自选池")
    except Exception as e:
        st.error(f"操作失败: {e}")


def _remove_from_watchlist(symbol: str) -> None:
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent))
        from trade_py.db.settings_db import SettingsDB
        db = SettingsDB(str(_data_root()))
        db.watchlist_remove(symbol)
        st.toast(f"🗑 {symbol} 已移出自选池")
    except Exception as e:
        st.error(f"操作失败: {e}")


def _render_macro_headlines() -> None:
    """Show latest sentiment headlines from gold tier, if available."""
    gold_dir = _data_root() / "sentiment" / "gold"
    if not gold_dir.exists():
        st.caption("情感数据未就绪 — 请运行 `uv run python -m trade_py.cli.main data sentiment`")
        return

    import json
    files = sorted(gold_dir.glob("*.json"), reverse=True)[:1]
    if not files:
        st.caption("暂无情报")
        return

    try:
        data = json.loads(files[0].read_text(encoding="utf-8"))
        headlines = data.get("headlines", data.get("items", []))[:5]
        for h in headlines:
            title = h.get("title", str(h))
            st.markdown(f"- {title}")
    except Exception:
        st.caption("情报数据解析失败")


def _render_cross_asset() -> None:
    """Show cross-asset data from data/cross_asset/ parquets."""
    gateway = DataGateway(str(_data_root()))
    assets = {
        "黄金": "gold.parquet",
        "BTC": "btc.parquet",
        "美元/人民币": "fx_cnh.parquet",
    }

    cols = st.columns(len(assets))
    for (name, fname), col in zip(assets.items(), cols):
        dataset = fname.replace(".parquet", "")
        with col:
            try:
                import pandas as pd
                df, report = gateway.get_cross_asset(dataset)
                if report.action != "hit_local" or report.degraded:
                    st.caption(f"{name} 回补: {gateway.format_report(report)}")
                if not df.empty:
                    df = df.sort_values("date" if "date" in df.columns else df.columns[0])
                    last = df.iloc[-1]
                    close_col = next(
                        (c for c in ["close", "price", "收盘价"] if c in df.columns),
                        df.columns[-1],
                    )
                    val = last[close_col]
                    if len(df) >= 2:
                        prev = df.iloc[-2][close_col]
                        pct = (val - prev) / prev * 100 if prev else 0
                        st.metric(name, f"{val:.4g}", f"{pct:+.2f}%")
                    else:
                        st.metric(name, f"{val:.4g}")
                else:
                    st.metric(name, "—", "未采集")
            except Exception:
                st.metric(name, "读取失败")
