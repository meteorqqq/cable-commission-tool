"""历史记录页"""

import streamlit as st
import pandas as pd

from db.database import list_sessions, load_session_results, delete_session
from engine.calculator import format_date_columns
from web._download import render_multi_download_buttons
from web._ui import page_intro, empty_state


def render_history(username: str):
    st.html(page_intro(
        "历史记录",
        "查看历史计算快照、重新核对结果，并按需下载或删除旧会话。",
        eyebrow="Archive",
    ))

    sessions = list_sessions(username)
    if not sessions:
        st.html(empty_state("暂无历史记录", "当你保存一次计算结果后，这里会出现可回看的会话快照。"))
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

            render_multi_download_buttons(
                results,
                base_filename=f"历史记录_{s['id']}",
                key_prefix=f"history_dl_{s['id']}",
            )

            tabs = st.tabs(list(results.keys()))
            for tab, (name, df) in zip(tabs, results.items()):
                with tab:
                    st.dataframe(format_date_columns(df), width="stretch", height=350)
