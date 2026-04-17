"""完成额度提成页"""

import streamlit as st
import pandas as pd

from engine.calculator import (
    calc_quota_commission_by_dept, DEFAULT_QUOTA_TIERS,
    _build_salesperson_dept_map,
)
from db.database import save_rules, load_rules


def _get_dept_list() -> list[str]:
    df = st.session_state.get("delivery_df")
    if df is not None and "销售部门" in df.columns:
        return sorted(df["销售部门"].dropna().unique().tolist())
    return []


def _calc_dept_totals() -> dict[str, float]:
    delivery_df = st.session_state.get("delivery_df")
    payment_df = st.session_state.get("payment_df")
    if delivery_df is None or payment_df is None:
        return {}
    dept_map = _build_salesperson_dept_map(delivery_df)
    pay = payment_df.copy()
    pay["_dept"] = pay["销售员"].map(dept_map)
    totals = {}
    for dept, grp in pay.groupby("_dept"):
        if pd.notna(dept):
            totals[dept] = round(grp["回款金额"].sum() / 10000, 2)
    return totals


def render_quota(username: str):
    st.header("完成额度提成")

    delivery_df = st.session_state.get("delivery_df")
    payment_df = st.session_state.get("payment_df")

    if delivery_df is None or payment_df is None:
        st.warning("请先在数据导入页上传交货和回款数据")
        return

    col_rule, col_dept = st.columns([1, 2], gap="large")

    with col_rule:
        with st.container(border=True):
            st.subheader("规则设置")
            saved = load_rules(username, "quota_tiers")
            default_tiers = saved if saved else [list(t) for t in DEFAULT_QUOTA_TIERS]

            tiers_df = pd.DataFrame(default_tiers, columns=["完成比阈值(%)", "提成率(%)"])
            edited_tiers = st.data_editor(
                tiers_df, num_rows="dynamic", width="stretch", key="quota_tiers_editor"
            )

            if st.button("保存规则", key="save_quota_rules"):
                data = edited_tiers.values.tolist()
                save_rules(username, "quota_tiers", data)
                st.success("规则已保存")

    with col_dept:
        with st.container(border=True):
            st.subheader("部门目标额 (万元)")
            depts = _get_dept_list()
            defaults = _calc_dept_totals()

            if not depts:
                st.info("未检测到部门信息")
            else:
                dept_data = [{"部门": d, "目标额(万元)": defaults.get(d, 0.0)} for d in depts]
                dept_df = pd.DataFrame(dept_data)
                edited_dept = st.data_editor(
                    dept_df, width="stretch", key="dept_targets_editor",
                    disabled=["部门"],
                )

    st.markdown("")
    if st.button("计算完成额度提成", type="primary", use_container_width=True):
        tiers = [tuple(row) for row in edited_tiers.values.tolist()
                 if pd.notna(row[0]) and pd.notna(row[1])]
        dept_targets = {}
        for _, row in edited_dept.iterrows():
            dept_targets[row["部门"]] = float(row["目标额(万元)"])

        try:
            result = calc_quota_commission_by_dept(delivery_df, payment_df, dept_targets, tiers)
            st.session_state["quota_result"] = result
            st.success(f"计算完成，共 {len(result)} 位销售员")
        except Exception as e:
            st.error(f"计算出错: {e}")

    result = st.session_state.get("quota_result")
    if result is not None and not result.empty:
        with st.container(border=True):
            st.subheader("计算结果")
            st.dataframe(result, width="stretch", height=400)
            csv = result.to_csv(index=False).encode("utf-8-sig")
            st.download_button("下载结果 CSV", csv, "完成额度提成.csv", "text/csv")
