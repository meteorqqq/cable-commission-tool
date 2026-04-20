"""历史记录页"""

import io

import streamlit as st
import pandas as pd

from db.database import list_sessions, load_session_results, delete_session
from engine.calculator import format_date_columns


def _build_excel_bytes(results: dict[str, pd.DataFrame]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for name, df in results.items():
            out = df.copy()
            for col in out.columns:
                if pd.api.types.is_datetime64_any_dtype(out[col]):
                    out[col] = out[col].dt.strftime("%Y-%m-%d")
            out.to_excel(writer, sheet_name=name[:31], index=False)
    return buf.getvalue()


def render_history(username: str):
    st.header("历史记录")

    sessions = list_sessions(username)
    if not sessions:
        st.info("暂无历史记录")
        return

    kw = st.text_input(
        "按会话名称 / 结果类型搜索", value="",
        placeholder="输入关键字过滤", key="history_search",
    )

    def _row_passes(s: dict) -> bool:
        if kw and kw.strip():
            k = kw.strip()
            hit = (k in s["name"]) or any(k in t for t in s["result_types"])
            if not hit:
                return False
        return True

    visible = [s for s in sessions if _row_passes(s)]
    st.caption(f"筛选结果：{len(visible)} / {len(sessions)} 条")

    for s in visible:
        with st.expander(
            f"**{s['name']}**  /  {s['created_at']}  /  "
            f"{', '.join(s['result_types'])}",
            expanded=False,
        ):
            col_toggle, col_del = st.columns([4, 1])
            with col_toggle:
                show_key = f"history_detail_{s['id']}"
                show = st.toggle(
                    "显示详情与下载",
                    value=st.session_state.get(show_key, False),
                    key=f"tgl_{s['id']}",
                )
                st.session_state[show_key] = show
            with col_del:
                if st.button("删除", key=f"del_{s['id']}", type="secondary",
                             use_container_width=True):
                    delete_session(s["id"])
                    st.success("已删除")
                    st.rerun()

            if not st.session_state.get(show_key):
                continue

            results = load_session_results(s["id"])
            if not results:
                st.info("无数据")
                continue

            st.download_button(
                "下载 Excel",
                _build_excel_bytes(results),
                f"历史记录_{s['id']}.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key=f"dl_{s['id']}",
            )

            tabs = st.tabs(list(results.keys()))
            for tab, (name, df) in zip(tabs, results.items()):
                with tab:
                    st.dataframe(format_date_columns(df), width="stretch", height=350)
