"""回款时效提成页 —— 按合同号为主体展示"""

import streamlit as st
import pandas as pd

from engine.calculator import calc_payment_timeliness, DEFAULT_PAYMENT_TIERS
from db.database import save_rules, load_rules


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


def _status_of(d_amt: float, p_amt: float) -> str:
    if d_amt == 0 and p_amt > 0:
        return "未发货（已收款）"
    if d_amt == 0:
        return "未发货"
    if p_amt <= 0:
        return "未回款"
    if p_amt + 1e-2 >= d_amt:
        return "已完成"
    return "部分回款"


def _build_contract_summary(
    timeliness_df: pd.DataFrame,
    delivery_df: pd.DataFrame,
    payment_df: pd.DataFrame,
) -> pd.DataFrame:
    """按合同号+销售员汇总发货/回款/时效提成。"""
    rows: dict[tuple[str, str], dict] = {}

    if delivery_df is not None and not delivery_df.empty:
        grp = delivery_df.groupby(["工程项目号", "销售员"])["发货金额"].sum()
        for (pid, sp), amt in grp.items():
            rows.setdefault((str(pid), str(sp)), {})["发货额"] = float(amt)

    if payment_df is not None and not payment_df.empty:
        grp = payment_df.groupby(["工程项目号", "销售员"])["回款金额"].sum()
        for (pid, sp), amt in grp.items():
            rows.setdefault((str(pid), str(sp)), {})["回款额"] = float(amt)

    tl_grp = {}
    if timeliness_df is not None and not timeliness_df.empty:
        for (pid, sp), grp in timeliness_df.groupby(["工程项目号", "销售员"]):
            tl_grp[(str(pid), str(sp))] = float(
                pd.to_numeric(grp["时效提成金额"], errors="coerce").fillna(0).sum()
            )

    dept_map: dict[str, str] = {}
    for src in (delivery_df, payment_df):
        if src is None or src.empty or "销售员" not in src.columns or "销售部门" not in src.columns:
            continue
        for _, r in src[["销售员", "销售部门"]].drop_duplicates().iterrows():
            sp = str(r["销售员"]).strip()
            dept = str(r["销售部门"]).strip() if pd.notna(r["销售部门"]) else ""
            if sp and dept:
                dept_map.setdefault(sp, dept)

    out = []
    for (pid, sp), v in rows.items():
        d_amt = round(v.get("发货额", 0.0), 2)
        p_amt = round(v.get("回款额", 0.0), 2)
        out.append({
            "工程项目号": pid,
            "销售员": sp,
            "销售部门": dept_map.get(sp, ""),
            "发货额": d_amt,
            "回款额": p_amt,
            "未回款额": round(max(d_amt - p_amt, 0), 2),
            "时效提成合计": round(tl_grp.get((pid, sp), 0.0), 2),
            "状态": _status_of(d_amt, p_amt),
        })

    df = pd.DataFrame(out)
    if df.empty:
        return df
    df["_sort"] = df["工程项目号"].apply(lambda x: (1 if x == "其他" else 0, x))
    return df.sort_values(["_sort", "销售员"]).drop(columns=["_sort"]).reset_index(drop=True)


def render_payment(username: str):
    st.header("回款时效提成")

    delivery_df = st.session_state.get("delivery_df")
    payment_df = st.session_state.get("payment_df")

    if delivery_df is None or payment_df is None:
        st.warning("请先在数据导入页上传交货和回款数据")
        return

    with st.container(border=True):
        st.subheader("规则设置")
        saved = load_rules(username, "payment_tiers")
        default_tiers = saved if saved else [list(t) for t in DEFAULT_PAYMENT_TIERS]

        tiers_df = pd.DataFrame(default_tiers, columns=["天数上限", "提成率(%)"])
        edited_tiers = st.data_editor(
            tiers_df, num_rows="dynamic", width="stretch",
            key="payment_tiers_editor",
        )

        c1, c2 = st.columns(2)
        with c1:
            if st.button("保存规则", key="save_payment_rules"):
                data = edited_tiers.values.tolist()
                save_rules(username, "payment_tiers", data)
                st.success("规则已保存")
        with c2:
            calc_clicked = st.button("计算回款时效提成", type="primary", use_container_width=True)

    if calc_clicked:
        tiers = [tuple(row) for row in edited_tiers.values.tolist()
                 if pd.notna(row[0]) and pd.notna(row[1])]
        try:
            timeliness_df, del_summary, pay_summary = calc_payment_timeliness(
                delivery_df, payment_df, tiers)
            st.session_state["timeliness_result"] = timeliness_df
            st.session_state["del_summary"] = del_summary
            st.session_state["pay_summary"] = pay_summary
            st.success(f"计算完成，时效记录 {len(timeliness_df)} 条")
        except Exception as e:
            st.error(f"计算出错: {e}")

    timeliness_df = st.session_state.get("timeliness_result")
    if timeliness_df is None:
        return

    st.markdown("")

    summary_df = _build_contract_summary(timeliness_df, delivery_df, payment_df)

    if summary_df.empty:
        st.info("暂无合同数据")
        return

    c1, c2, c3, c4 = st.columns(4, gap="medium")
    with c1:
        st.metric("合同数", f"{len(summary_df)} 个")
    with c2:
        st.metric("总发货额", _fmt_money(summary_df["发货额"].sum()))
    with c3:
        st.metric("总回款额", _fmt_money(summary_df["回款额"].sum()))
    with c4:
        st.metric("时效提成合计", _fmt_money(summary_df["时效提成合计"].sum()))

    st.markdown("")
    with st.container(border=True):
        st.subheader("合同汇总")
        st.dataframe(
            summary_df,
            width="stretch",
            height=min(400, 45 + len(summary_df) * 36),
            column_config={
                "发货额": st.column_config.NumberColumn(format="%.2f"),
                "回款额": st.column_config.NumberColumn(format="%.2f"),
                "未回款额": st.column_config.NumberColumn(format="%.2f"),
                "时效提成合计": st.column_config.NumberColumn(format="%.2f"),
            },
        )
        csv = summary_df.to_csv(index=False).encode("utf-8-sig")
        st.download_button("下载合同汇总", csv, "合同汇总.csv", "text/csv",
                           key="dl_contract_summary")

    st.markdown("")
    st.subheader("合同明细")
    st.caption("点击展开查看该合同的发货明细、回款明细与时效匹配结果。")

    filter_status = st.multiselect(
        "按状态筛选",
        options=["已完成", "部分回款", "未回款", "未发货", "未发货（已收款）"],
        default=[],
        key="payment_filter_status",
    )

    del_cols_pref = ["发货日期", "发货金额", "订货单位", "开票单位"]
    pay_cols_pref = ["回款日期", "回款金额", "开票单位", "订货单位", "核销金额"]
    tl_cols_pref = ["回款日期", "回款金额", "匹配发货日期", "回款周期(天)",
                    "时效提成比例", "时效提成金额"]

    for _, row in summary_df.iterrows():
        if filter_status and row["状态"] not in filter_status:
            continue

        pid = row["工程项目号"]
        sp = row["销售员"]
        color = _status_color(row["状态"])

        header = (
            f"{pid}　·　{sp}　·　"
            f"发货 {_fmt_money(row['发货额'])}　"
            f"/　回款 {_fmt_money(row['回款额'])}　"
            f"/　时效提成 {_fmt_money(row['时效提成合计'])}"
        )
        with st.expander(header, expanded=False):
            st.markdown(
                f"**状态：** <span style='color:{color};font-weight:600'>{row['状态']}</span>　",
                unsafe_allow_html=True,
            )
            if row["销售部门"]:
                st.caption("销售部门：" + row["销售部门"])

            d_sub = delivery_df[
                (delivery_df["工程项目号"].astype(str) == pid)
                & (delivery_df["销售员"].astype(str) == sp)
            ].copy()
            p_sub = payment_df[
                (payment_df["工程项目号"].astype(str) == pid)
                & (payment_df["销售员"].astype(str) == sp)
            ].copy()
            tl_sub = timeliness_df[
                (timeliness_df["工程项目号"].astype(str) == pid)
                & (timeliness_df["销售员"].astype(str) == sp)
            ].copy() if not timeliness_df.empty else pd.DataFrame()

            col_d, col_p = st.columns(2, gap="large")
            with col_d:
                st.markdown("**发货明细**")
                if d_sub.empty:
                    st.caption("（无发货记录）")
                else:
                    cols = [c for c in del_cols_pref if c in d_sub.columns]
                    show = d_sub[cols].sort_values("发货日期") if "发货日期" in cols else d_sub[cols]
                    st.dataframe(
                        show.reset_index(drop=True),
                        width="stretch",
                        height=min(260, 45 + len(show) * 36),
                        column_config={
                            "发货金额": st.column_config.NumberColumn(format="%.2f"),
                        },
                    )
            with col_p:
                st.markdown("**回款明细**")
                if p_sub.empty:
                    st.caption("（无回款记录）")
                else:
                    cols = [c for c in pay_cols_pref if c in p_sub.columns]
                    show = p_sub[cols].sort_values("回款日期") if "回款日期" in cols else p_sub[cols]
                    st.dataframe(
                        show.reset_index(drop=True),
                        width="stretch",
                        height=min(260, 45 + len(show) * 36),
                        column_config={
                            "回款金额": st.column_config.NumberColumn(format="%.2f"),
                            "核销金额": st.column_config.NumberColumn(format="%.2f"),
                        },
                    )

            st.markdown("**时效匹配明细**")
            if tl_sub.empty:
                st.caption("（无时效记录）")
            else:
                cols = [c for c in tl_cols_pref if c in tl_sub.columns]
                st.dataframe(
                    tl_sub[cols].reset_index(drop=True),
                    width="stretch",
                    height=min(260, 45 + len(tl_sub) * 36),
                    column_config={
                        "回款金额": st.column_config.NumberColumn(format="%.2f"),
                        "时效提成金额": st.column_config.NumberColumn(format="%.2f"),
                    },
                )

    with st.expander("原始时效提成明细（扁平表）", expanded=False):
        st.dataframe(timeliness_df, width="stretch", height=400)
        csv = timeliness_df.to_csv(index=False).encode("utf-8-sig")
        st.download_button("下载时效明细", csv, "回款时效提成.csv", "text/csv",
                           key="dl_timeliness_flat")
