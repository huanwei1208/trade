from __future__ import annotations

"""Tab 5 — 设置 (Settings)

Edit user-tunable parameters stored in data/.db/trade.db settings table.
Categories: risk, backtest, signal, scheduler.
"""

from pathlib import Path

import streamlit as st


_CATEGORY_LABELS: dict[str, str] = {
    "risk":      "风险参数",
    "backtest":  "回测参数",
    "signal":    "信号参数",
    "scheduler": "调度参数",
}

_CATEGORY_ICONS: dict[str, str] = {
    "risk":      "🛡",
    "backtest":  "📈",
    "signal":    "⚡",
    "scheduler": "⏰",
}


def _data_root() -> Path:
    return Path(__file__).parent.parent.parent.parent / "data"


def _get_db():
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from trade_py.db.settings_db import SettingsDB
    return SettingsDB(str(_data_root()))


def render() -> None:
    st.header("⚙️ 设置")
    st.caption("所有参数存储在 data/.db/trade.db，修改后立即生效。")

    try:
        db = _get_db()
        categories = db.all_categories()
    except Exception as e:
        st.error(f"无法连接设置数据库: {e}")
        return

    if not categories:
        st.warning("设置表为空，请检查数据库初始化。")
        return

    # Render each category in a separate expander
    for cat in categories:
        icon = _CATEGORY_ICONS.get(cat, "🔧")
        label = _CATEGORY_LABELS.get(cat, cat)
        with st.expander(f"{icon} {label}", expanded=True):
            _render_category(db, cat)

    st.divider()
    st.subheader("🔑 系统信息")
    _render_system_info()


def _render_category(db, category: str) -> None:
    items = db.get_category(category)
    if not items:
        st.caption("（无设置项）")
        return

    for key, meta in items.items():
        value = meta["value"]
        label = meta.get("label", key)
        vtype = meta.get("value_type", "string")
        col_label, col_input, col_save = st.columns([3, 3, 1])
        with col_label:
            st.markdown(f"**{label}**")
            st.caption(key)
        with col_input:
            widget_key = f"setting_{key}"
            if vtype == "float":
                new_val = st.number_input(
                    label,
                    value=float(value),
                    format="%.6f",
                    key=widget_key,
                    label_visibility="collapsed",
                )
            elif vtype == "int":
                new_val = st.number_input(
                    label,
                    value=int(value),
                    step=1,
                    key=widget_key,
                    label_visibility="collapsed",
                )
            elif vtype == "bool":
                new_val = st.checkbox(
                    label,
                    value=bool(value),
                    key=widget_key,
                    label_visibility="collapsed",
                )
            else:
                new_val = st.text_input(
                    label,
                    value=str(value),
                    key=widget_key,
                    label_visibility="collapsed",
                )
        with col_save:
            if st.button("保存", key=f"save_{key}"):
                try:
                    db.set(key, new_val)
                    st.toast(f"✅ {label} 已更新为 {new_val}")
                except Exception as e:
                    st.error(f"保存失败: {e}")


def _render_system_info() -> None:
    from trade_py.ui.services.cpp_bridge import cli_available, _TRADE_CLI
    data_root = _data_root()

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**trade_cli**")
        if cli_available():
            st.success(f"✅ {_TRADE_CLI}")
        else:
            st.error(f"❌ 未找到 {_TRADE_CLI}")

        st.markdown("**数据目录**")
        if data_root.exists():
            st.success(f"✅ {data_root}")
        else:
            st.warning(f"⚠ {data_root} 不存在")

    with col2:
        st.markdown("**数据库**")
        db_path = __import__("trade_py.db.trade_db", fromlist=["_find_db_path"])._find_db_path(data_root)
        if db_path.exists():
            size_kb = db_path.stat().st_size / 1024
            st.success(f"✅ trade.db ({size_kb:.1f} KB)")
        else:
            st.warning("⚠ trade.db 不存在")

        st.markdown("**模型目录**")
        model_dir = data_root / "models"
        if model_dir.exists():
            model_files = list(model_dir.glob("*.model")) + list(model_dir.glob("*.onnx"))
            st.success(f"✅ {len(model_files)} 个模型文件")
        else:
            st.warning("⚠ models/ 目录不存在")
