"""完成额度提成页"""

import streamlit as st
import pandas as pd

from engine.calculator import (
    calc_quota_commission_by_dept, DEFAULT_QUOTA_TIERS,
)
from db.database import save_rules, load_rules
from web._cache import bump_calc_version, get_salesperson_dept_map
from web._download import render_df_download_buttons
from web._ui import page_intro


def _get_dept_list() -> list[str]:
    depts: set[str] = set()
    for key in ("delivery_df", "payment_df"):
        df = st.session_state.get(key)
        if df is not None and "销售部门" in df.columns:
            depts.update(str(d).strip() for d in df["销售部门"].dropna().unique())
    return sorted(d for d in depts if d)


def _calc_dept_totals() -> dict[str, float]:
    delivery_df = st.session_state.get("delivery_df")
    payment_df = st.session_state.get("payment_df")
    if delivery_df is None or payment_df is None:
        return {}
    dept_map = get_salesperson_dept_map()
    pay = payment_df.copy()
    pay["_dept"] = pay["销售员"].map(dept_map)
    totals = {}
    for dept, grp in pay.groupby("_dept"):
        if pd.notna(dept):
            totals[dept] = round(grp["回款金额"].sum() / 10000, 2)
    return totals


def _calc_dept_delivery_totals() -> dict[str, float]:
    """按 销售员→销售部门 映射汇总各部门发货额（万元）。"""
    delivery_df = st.session_state.get("delivery_df")
    if delivery_df is None or "发货金额" not in delivery_df.columns:
        return {}
    dept_map = get_salesperson_dept_map()
    d = delivery_df.copy()
    d["_dept"] = d["销售员"].map(dept_map)
    totals: dict[str, float] = {}
    for dept, grp in d.groupby("_dept"):
        if pd.notna(dept):
            totals[str(dept).strip()] = round(grp["发货金额"].sum() / 10000, 2)
    return totals


def render_quota(username: str):
    st.html(page_intro(
        "完成额度提成",
        "按部门发货完成比确定档位，再用个人回款额乘以对应系数，适合看团队目标兑现情况。",
        eyebrow="Quota Commission",
    ))

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
            del_totals = _calc_dept_delivery_totals()

            saved_targets = load_rules(username, "dept_targets") or {}

            if not depts:
                st.info("未检测到部门信息")
                edited_dept = pd.DataFrame(columns=["部门", "部门发货额(万元)", "目标额(万元)"])
            else:
                dept_data = [{
                    "部门": d,
                    "部门发货额(万元)": del_totals.get(d, 0.0),
                    "目标额(万元)": float(saved_targets.get(d, defaults.get(d, 0.0))),
                } for d in depts]
                dept_df = pd.DataFrame(dept_data)
                edited_dept = st.data_editor(
                    dept_df,
                    width="stretch",
                    key="dept_targets_editor",
                    disabled=["部门", "部门发货额(万元)"],
                    column_config={
                        "部门发货额(万元)": st.column_config.NumberColumn(
                            "部门发货额(万元)", format="%.2f",
                            help="来自交货 Excel，只读参考；用于填写目标额时对照。",
                        ),
                        "目标额(万元)": st.column_config.NumberColumn(
                            "目标额(万元)", format="%.2f", min_value=0.0, step=0.01,
                        ),
                    },
                )

                if st.button("保存目标额", key="save_dept_targets"):
                    targets_to_save = {
                        str(row["部门"]): float(row["目标额(万元)"])
                        for _, row in edited_dept.iterrows()
                        if pd.notna(row.get("目标额(万元)"))
                    }
                    save_rules(username, "dept_targets", targets_to_save)
                    st.success("目标额已保存")

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
            bump_calc_version()
            st.success(f"计算完成，共 {len(result)} 位销售员")
        except Exception as e:
            st.error(f"计算出错: {e}")

    result = st.session_state.get("quota_result")
    if result is not None and not result.empty:
        with st.container(border=True):
            st.subheader("计算结果")

            m1, m2, m3, m4 = st.columns(4, gap="medium")
            total_sp = len(result)
            total_pay = float(pd.to_numeric(
                result.get("个人回款额(元)", 0), errors="coerce"
            ).fillna(0).sum())
            total_commission = float(pd.to_numeric(
                result.get("完成额度提成(元)", 0), errors="coerce"
            ).fillna(0).sum())
            commissioned_n = int((pd.to_numeric(
                result.get("完成额度提成(元)", 0), errors="coerce"
            ).fillna(0).abs() > 0.005).sum())
            with m1:
                st.metric("销售员数", f"{total_sp}")
            with m2:
                st.metric("回款合计", f"{total_pay:,.2f}")
            with m3:
                st.metric("提成合计", f"{total_commission:,.2f}")
            with m4:
                st.metric("有提成人数", f"{commissioned_n}")

            all_depts = sorted({
                str(d).strip() for d in result.get("销售部门", pd.Series(dtype=str)).dropna()
                if str(d).strip()
            })
            fc1, fc2 = st.columns([1, 1], gap="medium")
            with fc1:
                filter_dept = st.multiselect(
                    "按销售部门筛选", options=all_depts, default=[],
                    key="quota_filter_dept",
                )
            with fc2:
                search_sp = st.text_input(
                    "按销售员姓名搜索", value="", placeholder="输入姓名片段",
                    key="quota_filter_sp",
                )

            view = result
            if filter_dept:
                view = view[view["销售部门"].isin(filter_dept)]
            if search_sp and search_sp.strip():
                kw = search_sp.strip()
                view = view[view["销售员"].astype(str).str.contains(kw, case=False, na=False)]

            st.caption(f"筛选结果：{len(view)} / {len(result)} 人")
            st.dataframe(view, width="stretch", height=400)

            render_df_download_buttons(
                view,
                base_filename="完成额度提成",
                sheet_name="完成额度提成",
                key_prefix="quota_result",
            )
