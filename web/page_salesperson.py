"""销售员详情页：按销售员展示其全部合同及发货/回款明细。"""

import streamlit as st
import pandas as pd

from engine.calculator import list_salespersons, build_salesperson_detail, format_date_columns


def _fmt_money(v: float) -> str:
    try:
        return f"{float(v):,.2f}"
    except Exception:
        return str(v)


def _status_color(status: str) -> str:
    return {
        "已完成": "#16a34a",
        "部分回款": "#f59e0b",
        "未回款": "#ef4444",
        "未发货": "#64748b",
        "未发货（已收款）": "#0ea5e9",
    }.get(status, "#64748b")


def render_salesperson():
    st.header("销售员详情")

    delivery_df = st.session_state.get("delivery_df")
    payment_df = st.session_state.get("payment_df")
    if delivery_df is None and payment_df is None:
        st.warning("请先在数据导入页上传交货或回款数据")
        return

    names = list_salespersons(delivery_df, payment_df)
    if not names:
        st.info("未检测到销售员信息")
        return

    default_idx = 0
    prev = st.session_state.get("_selected_salesperson")
    if prev in names:
        default_idx = names.index(prev)

    sel = st.selectbox("选择销售员", names, index=default_idx, key="_selected_salesperson")

    profit_df = st.session_state.get("profit_result")
    timeliness_df = st.session_state.get("timeliness_result")

    detail = build_salesperson_detail(
        sel, delivery_df, payment_df,
        profit_df=profit_df, timeliness_df=timeliness_df,
    )

    if profit_df is None or timeliness_df is None:
        missing = []
        if profit_df is None:
            missing.append("利润提成")
        if timeliness_df is None:
            missing.append("回款时效提成")
        st.caption(
            "未检测到 " + " / ".join(missing) + " 的计算结果，"
            "请先到对应页面点击「计算」以在此处显示提成明细。"
        )

    c1, c2, c3, c4, c5, c6 = st.columns(6, gap="medium")
    with c1:
        st.metric("销售部门", detail["销售部门"] or "—")
    with c2:
        st.metric("合同数", f"{detail['合同数']} 个")
    with c3:
        st.metric("总发货额", _fmt_money(detail["总发货额"]))
    with c4:
        st.metric("总回款额", _fmt_money(detail["总回款额"]))
    with c5:
        st.metric("利润提成", _fmt_money(detail.get("总利润提成", 0)))
    with c6:
        st.metric("时效提成", _fmt_money(detail.get("总时效提成", 0)))

    if not detail["合同列表"]:
        st.info("该销售员名下暂无合同")
        return

    st.markdown("")

    normal_contracts = [c for c in detail["合同列表"] if c["工程项目号"] != "其他"]
    other_contract = next(
        (c for c in detail["合同列表"] if c["工程项目号"] == "其他"), None
    )

    summary_rows = []
    for c in detail["合同列表"]:
        summary_rows.append({
            "工程项目号": c["工程项目号"],
            "订货单位": " / ".join(c["订货单位"]) if c["订货单位"] else "",
            "发货额": c["发货额"],
            "回款额": c["回款额"],
            "未回款额": c["未回款额"],
            "利润提成": c.get("利润提成", 0.0),
            "时效提成": c.get("时效提成", 0.0),
            "状态": c["状态"],
        })
    summary_df = pd.DataFrame(summary_rows)

    with st.container(border=True):
        st.subheader("合同汇总")
        if other_contract is None:
            st.caption(
                "未检测到「其他（无合同号）」条目。若源数据中确有无合同号明细，"
                "请到「数据导入」页重新上传 Excel 以刷新。"
            )
        st.dataframe(
            summary_df,
            width="stretch",
            height=min(400, 45 + len(summary_df) * 36),
            column_config={
                "发货额": st.column_config.NumberColumn(format="%.2f"),
                "回款额": st.column_config.NumberColumn(format="%.2f"),
                "未回款额": st.column_config.NumberColumn(format="%.2f"),
                "利润提成": st.column_config.NumberColumn(format="%.2f"),
                "时效提成": st.column_config.NumberColumn(format="%.2f"),
            },
        )

    st.markdown("")
    st.subheader("合同明细")

    for c in normal_contracts:
        _render_contract_expander(c)

    if other_contract is not None:
        st.markdown("")
        _render_other_section(other_contract)


def _render_contract_expander(c: dict):
    color = _status_color(c["状态"])
    header = (
        f"{c['工程项目号']}　·　{c['状态']}　·　"
        f"发货 {_fmt_money(c['发货额'])}　/　回款 {_fmt_money(c['回款额'])}　"
        f"/　未回款 {_fmt_money(c['未回款额'])}　·　"
        f"利润提成 {_fmt_money(c.get('利润提成', 0))}　/　"
        f"时效提成 {_fmt_money(c.get('时效提成', 0))}"
    )
    with st.expander(header, expanded=False):
        st.markdown(
            f"**状态：** <span style='color:{color};font-weight:600'>{c['状态']}</span>",
            unsafe_allow_html=True,
        )
        if c["订货单位"]:
            st.caption("订货单位：" + "　/　".join(c["订货单位"]))
        if c["开票单位"]:
            st.caption("开票单位：" + "　/　".join(c["开票单位"]))

        m1, m2, m3, m4 = st.columns(4, gap="medium")
        with m1:
            st.metric("发货额", _fmt_money(c["发货额"]))
        with m2:
            st.metric("回款额", _fmt_money(c["回款额"]))
        with m3:
            st.metric(
                "利润提成",
                _fmt_money(c.get("利润提成", 0)),
                help=(
                    f"利润提成率：{c.get('利润提成率', '')}　·　"
                    f"分类：{c.get('利润分类', '')}"
                ) if c.get("利润提成率") else None,
            )
        with m4:
            st.metric("回款时效提成", _fmt_money(c.get("时效提成", 0)))

        col_d, col_p = st.columns(2, gap="large")
        with col_d:
            st.markdown("**发货明细**")
            if c["发货明细"].empty:
                st.caption("（无发货记录）")
            else:
                st.dataframe(
                    format_date_columns(c["发货明细"]),
                    width="stretch",
                    height=min(280, 45 + len(c["发货明细"]) * 36),
                    column_config={
                        "发货金额": st.column_config.NumberColumn(format="%.2f"),
                    },
                )
        with col_p:
            st.markdown("**回款明细**")
            if c["回款明细"].empty:
                st.caption("（无回款记录）")
            else:
                st.dataframe(
                    format_date_columns(c["回款明细"]),
                    width="stretch",
                    height=min(280, 45 + len(c["回款明细"]) * 36),
                    column_config={
                        "回款金额": st.column_config.NumberColumn(format="%.2f"),
                    },
                )

        tl_df = c.get("时效提成明细")
        if tl_df is not None and not tl_df.empty:
            st.markdown("**时效提成明细**")
            st.dataframe(
                format_date_columns(tl_df),
                width="stretch",
                height=min(260, 45 + len(tl_df) * 36),
                column_config={
                    "回款金额": st.column_config.NumberColumn(format="%.2f"),
                    "时效提成金额": st.column_config.NumberColumn(format="%.2f"),
                },
            )
        elif c.get("时效提成", 0) == 0 and c["回款明细"].empty is False:
            st.caption("（暂无时效提成记录，请到「回款时效提成」页计算后查看）")


def _render_other_section(other: dict):
    """其他（无合同号）：按订货/开票单位再分组。"""
    color = _status_color(other["状态"])
    with st.container(border=True):
        st.markdown(
            f"### 其他（无合同号）　"
            f"<span style='color:{color};font-weight:600'>{other['状态']}</span>",
            unsafe_allow_html=True,
        )
        c1, c2, c3, c4, c5 = st.columns(5, gap="medium")
        with c1:
            st.metric("发货额", _fmt_money(other["发货额"]))
        with c2:
            st.metric("回款额", _fmt_money(other["回款额"]))
        with c3:
            st.metric("未回款额", _fmt_money(other["未回款额"]))
        with c4:
            st.metric("利润提成", _fmt_money(other.get("利润提成", 0)))
        with c5:
            st.metric("时效提成", _fmt_money(other.get("时效提成", 0)))

        tl_df = other.get("时效提成明细")
        if tl_df is not None and not tl_df.empty:
            with st.expander("时效提成明细", expanded=False):
                st.dataframe(
                    format_date_columns(tl_df),
                    width="stretch",
                    height=min(260, 45 + len(tl_df) * 36),
                    column_config={
                        "回款金额": st.column_config.NumberColumn(format="%.2f"),
                        "时效提成金额": st.column_config.NumberColumn(format="%.2f"),
                    },
                )

        d_df = other["发货明细"]
        p_df = other["回款明细"]

        units: list[str] = []
        seen = set()
        for src, col in ((d_df, "订货单位"), (p_df, "订货单位"),
                         (d_df, "开票单位"), (p_df, "开票单位")):
            if src is None or src.empty or col not in src.columns:
                continue
            for u in src[col].dropna().astype(str).str.strip().unique():
                if u and u not in seen:
                    seen.add(u)
                    units.append(u)

        if not units:
            st.caption("（无订货/开票单位信息）")
            _render_unit_tables(d_df, p_df, label="全部")
            return

        for unit in units:
            d_sub = d_df.copy()
            if not d_sub.empty:
                mask = pd.Series(False, index=d_sub.index)
                for col in ("订货单位", "开票单位"):
                    if col in d_sub.columns:
                        mask = mask | (d_sub[col].astype(str).str.strip() == unit)
                d_sub = d_sub[mask]

            p_sub = p_df.copy()
            if not p_sub.empty:
                mask = pd.Series(False, index=p_sub.index)
                for col in ("订货单位", "开票单位"):
                    if col in p_sub.columns:
                        mask = mask | (p_sub[col].astype(str).str.strip() == unit)
                p_sub = p_sub[mask]

            d_amt = float(d_sub["发货金额"].sum()) if "发货金额" in d_sub.columns else 0.0
            p_amt = float(p_sub["回款金额"].sum()) if "回款金额" in p_sub.columns else 0.0

            header = (
                f"{unit}　·　发货 {_fmt_money(d_amt)}　/　回款 {_fmt_money(p_amt)}"
            )
            with st.expander(header, expanded=False):
                _render_unit_tables(d_sub, p_sub, label=unit)


def _render_unit_tables(d_sub: pd.DataFrame, p_sub: pd.DataFrame, label: str):
    col_d, col_p = st.columns(2, gap="large")
    with col_d:
        st.markdown("**发货明细**")
        if d_sub is None or d_sub.empty:
            st.caption("（无发货记录）")
        else:
            st.dataframe(
                format_date_columns(d_sub.reset_index(drop=True)),
                width="stretch",
                height=min(260, 45 + len(d_sub) * 36),
                column_config={
                    "发货金额": st.column_config.NumberColumn(format="%.2f"),
                },
                key=f"other_del_{label}",
            )
    with col_p:
        st.markdown("**回款明细**")
        if p_sub is None or p_sub.empty:
            st.caption("（无回款记录）")
        else:
            st.dataframe(
                format_date_columns(p_sub.reset_index(drop=True)),
                width="stretch",
                height=min(260, 45 + len(p_sub) * 36),
                column_config={
                    "回款金额": st.column_config.NumberColumn(format="%.2f"),
                },
                key=f"other_pay_{label}",
            )
