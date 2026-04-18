"""数据导入页"""

import tempfile
from pathlib import Path

import streamlit as st
import pandas as pd

from engine.calculator import (
    load_delivery_excel,
    load_payment_excel,
    build_contract_overview,
    extract_project_list,
)
from db.database import save_import_snapshots


def _upload_and_load(
    label: str,
    key: str,
    loader,
    state_key: str,
    username: str,
    kind: str,
):
    uploaded = st.file_uploader(label, type=["xls", "xlsx", "csv"], key=key)
    if uploaded is not None:
        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(uploaded.name).suffix) as tmp:
            tmp.write(uploaded.read())
            tmp_path = tmp.name
        try:
            df = loader(tmp_path)
            st.session_state[state_key] = df
            if kind == "delivery":
                save_import_snapshots(username, delivery_df=df)
            else:
                save_import_snapshots(username, payment_df=df)
            st.success(f"已加载 {len(df)} 条记录，并已写入数据库")
        except Exception as e:
            st.error(f"加载失败: {e}")

    df = st.session_state.get(state_key)
    if df is not None:
        with st.expander(f"预览数据 ({len(df)} 条)", expanded=False):
            st.dataframe(df.head(100), width="stretch", height=300)


def render_import(username: str):
    st.header("数据导入")

    col1, col2 = st.columns(2, gap="large")

    with col1:
        with st.container(border=True):
            st.subheader("交货数据")
            _upload_and_load(
                "上传交货单 Excel",
                "delivery_uploader",
                load_delivery_excel,
                "delivery_df",
                username,
                "delivery",
            )

    with col2:
        with st.container(border=True):
            st.subheader("回款数据")
            _upload_and_load(
                "上传回款单 Excel",
                "payment_uploader",
                load_payment_excel,
                "payment_df",
                username,
                "payment",
            )

    st.markdown("")
    c1, c2, c3 = st.columns(3, gap="large")
    with c1:
        status = "已导入" if st.session_state.get("delivery_df") is not None else "未导入"
        st.metric("交货数据", status)
    with c2:
        status = "已导入" if st.session_state.get("payment_df") is not None else "未导入"
        st.metric("回款数据", status)
    dd = st.session_state.get("delivery_df")
    pd_df = st.session_state.get("payment_df")
    with c3:
        n_union = len(extract_project_list(dd, pd_df))
        st.metric("工程项目号（去重）", f"{n_union} 个")

    if dd is not None or pd_df is not None:
        overview = build_contract_overview(dd, pd_df)
        if not overview.empty:
            st.markdown("")
            with st.container(border=True):
                st.subheader("工程项目号汇总")
                st.dataframe(overview, width="stretch", height=min(400, 35 + len(overview) * 36))
