"""历史记录页"""

import io

import streamlit as st
import pandas as pd

from db.database import list_sessions, load_session_results, delete_session
from engine.calculator import format_date_columns


def render_history(username: str):
    st.header("历史记录")

    sessions = list_sessions(username)

    if not sessions:
        st.info("暂无历史记录")
        return

    for s in sessions:
        with st.expander(
            f"**{s['name']}**  /  {s['created_at']}  /  "
            f"{', '.join(s['result_types'])}",
            expanded=False,
        ):
            col1, col2, col3 = st.columns([2, 2, 1])

            with col1:
                if st.button("查看详情", key=f"view_{s['id']}"):
                    st.session_state[f"history_detail_{s['id']}"] = True

            with col2:
                if st.button("导出 Excel", key=f"export_{s['id']}"):
                    results = load_session_results(s["id"])
                    buf = io.BytesIO()
                    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                        for name, df in results.items():
                            df.to_excel(writer, sheet_name=name[:31], index=False)
                    st.download_button(
                        "点击下载",
                        buf.getvalue(),
                        f"历史记录_{s['id']}.xlsx",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key=f"dl_{s['id']}",
                    )

            with col3:
                if st.button("删除", key=f"del_{s['id']}", type="secondary"):
                    delete_session(s["id"])
                    st.success("已删除")
                    st.rerun()

            if st.session_state.get(f"history_detail_{s['id']}"):
                results = load_session_results(s["id"])
                if results:
                    tabs = st.tabs(list(results.keys()))
                    for tab, (name, df) in zip(tabs, results.items()):
                        with tab:
                            st.dataframe(format_date_columns(df), width="stretch", height=350)
                else:
                    st.info("无数据")
