"""数据导入页"""

import tempfile
from pathlib import Path

import streamlit as st
import pandas as pd

from engine.calculator import load_delivery_excel, load_payment_excel


def _upload_and_load(label: str, key: str, loader, state_key: str):
    uploaded = st.file_uploader(label, type=["xls", "xlsx", "csv"], key=key)
    if uploaded is not None:
        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(uploaded.name).suffix) as tmp:
            tmp.write(uploaded.read())
            tmp_path = tmp.name
        try:
            df = loader(tmp_path)
            st.session_state[state_key] = df
            st.success(f"已加载 {len(df)} 条记录")
        except Exception as e:
            st.error(f"加载失败: {e}")

    df = st.session_state.get(state_key)
    if df is not None:
        with st.expander(f"预览数据 ({len(df)} 条)", expanded=False):
            st.dataframe(df.head(100), width="stretch", height=300)


def render_import():
    st.header("数据导入")

    col1, col2 = st.columns(2, gap="large")

    with col1:
        with st.container(border=True):
            st.subheader("交货数据")
            _upload_and_load("上传交货单 Excel", "delivery_uploader",
                             load_delivery_excel, "delivery_df")

    with col2:
        with st.container(border=True):
            st.subheader("回款数据")
            _upload_and_load("上传回款单 Excel", "payment_uploader",
                             load_payment_excel, "payment_df")

    st.markdown("")
    c1, c2 = st.columns(2, gap="large")
    with c1:
        status = "已导入" if st.session_state.get("delivery_df") is not None else "未导入"
        st.metric("交货数据", status)
    with c2:
        status = "已导入" if st.session_state.get("payment_df") is not None else "未导入"
        st.metric("回款数据", status)
