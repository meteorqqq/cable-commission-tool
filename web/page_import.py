"""数据导入页"""

import os
import tempfile
from pathlib import Path

import streamlit as st
import pandas as pd

from engine.calculator import (
    load_delivery_excel,
    load_payment_excel,
    format_date_columns,
)
from db.database import save_import_snapshots
from web._cache import bump_data_version, get_project_list, get_contract_overview
from web.page_balance import render_opening_balance_import
from web._ui import page_intro, panel_intro


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
        suffix = Path(uploaded.name).suffix
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(uploaded.read())
            tmp_path = tmp.name
        try:
            df = loader(tmp_path)
            st.session_state[state_key] = df
            if kind == "delivery":
                save_import_snapshots(username, delivery_df=df)
            else:
                save_import_snapshots(username, payment_df=df)
            bump_data_version()
            st.success(f"已加载 {len(df)} 条记录，并已写入数据库")
        except Exception as e:
            st.error(f"加载失败: {e}")
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    df = st.session_state.get(state_key)
    if df is not None:
        with st.expander(f"预览数据 ({len(df)} 条)", expanded=False):
            st.dataframe(format_date_columns(df.head(100)), width="stretch", height=300)


def render_import(username: str):
    dd = st.session_state.get("delivery_df")
    pd_df = st.session_state.get("payment_df")
    n_union = len(get_project_list())

    st.html(page_intro(
        "数据导入",
        "上传交货、回款与期初结余数据，系统会自动刷新合同视图，并保留退货与退款的业务语义。",
        eyebrow="Data Intake",
        meta=[
            ("交货数据", "已导入" if dd is not None else "待上传"),
            ("回款数据", "已导入" if pd_df is not None else "待上传"),
            ("合同去重", f"{n_union} 个"),
        ],
    ))

    col1, col2 = st.columns(2, gap="large")

    with col1:
        with st.container(border=True):
            st.html(panel_intro("交货数据", "支持 Excel / CSV，导入后会自动识别负交货并标记为退货。"))
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
            st.html(panel_intro("回款数据", "支持 Excel / CSV，负回款会保留为退款记录并参与后续计算。"))
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
    with c3:
        st.metric("合同编号（去重）", f"{n_union} 个")

    if dd is not None or pd_df is not None:
        overview = get_contract_overview()
        if overview is not None and not overview.empty:
            st.markdown("")
            with st.container(border=True):
                st.html(panel_intro("合同编号汇总", "用于快速检查导入结果是否存在仅交货、仅回款、含退货或含退款的合同。"))
                st.dataframe(overview, width="stretch", height=min(400, 35 + len(overview) * 36))

        st.markdown("")
        with st.container(border=True):
            st.html(panel_intro("期初结余（可选）", "适合承接上期未结清合同，让历史余额继续参与本期的结余与提成计算。"))
            render_opening_balance_import()
