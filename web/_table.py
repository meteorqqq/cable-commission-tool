"""表格交互工具：点击行后展示完整文本。"""

from __future__ import annotations

import pandas as pd
import streamlit as st


def dataframe_with_fulltext_panel(
    df: pd.DataFrame,
    *,
    key: str,
    fulltext_cols: list[str],
    column_config: dict | None = None,
    height: int = 400,
) -> None:
    """渲染可选中行的 dataframe，并在下方显示所选行的完整文本字段。"""
    selected_idx: int | None = None

    try:
        event = st.dataframe(
            df,
            width="stretch",
            height=height,
            column_config=column_config or {},
            on_select="rerun",
            selection_mode="single-row",
            key=key,
        )
        rows = getattr(getattr(event, "selection", None), "rows", None) or []
        if rows:
            selected_idx = int(rows[0])
    except TypeError:
        # 兼容旧版 Streamlit（不支持 on_select）
        st.dataframe(
            df,
            width="stretch",
            height=height,
            column_config=column_config or {},
        )

    if selected_idx is None or selected_idx < 0 or selected_idx >= len(df):
        return

    row = df.iloc[selected_idx]
    with st.container(border=True):
        st.caption(f"已选中第 {selected_idx + 1} 行，完整名称如下：")
        shown = 0
        for col in fulltext_cols:
            if col not in df.columns:
                continue
            val = row.get(col, "")
            if pd.isna(val) or not str(val).strip():
                continue
            st.markdown(f"**{col}**：{val}")
            shown += 1
        if shown == 0:
            st.caption("（该行无可展示的完整文本字段）")

