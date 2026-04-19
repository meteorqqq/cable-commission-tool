"""回款时效提成页 —— 按合同号为主体展示"""

import streamlit as st
import pandas as pd

from engine.calculator import (
    calc_payment_timeliness, DEFAULT_PAYMENT_TIERS, format_date_columns,
    invoice_units_by_contract, invoice_units_by_contract_sp,
)
from db.database import save_rules, load_rules
from web._ui import (
    fmt_money, split_units, truncate_units_text,
    status_badge, unit_pills, kpi_row, meta_row, section_title,
)


_fmt_money = fmt_money


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
        grp = delivery_df.groupby(["合同编号", "销售员"])["发货金额"].sum()
        for (pid, sp), amt in grp.items():
            rows.setdefault((str(pid), str(sp)), {})["发货额"] = float(amt)

    if payment_df is not None and not payment_df.empty:
        grp = payment_df.groupby(["合同编号", "销售员"])["回款金额"].sum()
        for (pid, sp), amt in grp.items():
            rows.setdefault((str(pid), str(sp)), {})["回款额"] = float(amt)

    tl_grp = {}
    if timeliness_df is not None and not timeliness_df.empty:
        for (pid, sp), grp in timeliness_df.groupby(["合同编号", "销售员"]):
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

    inv_sp_map = invoice_units_by_contract_sp(delivery_df, payment_df)
    inv_map = invoice_units_by_contract(delivery_df, payment_df)

    out = []
    for (pid, sp), v in rows.items():
        d_amt = round(v.get("发货额", 0.0), 2)
        p_amt = round(v.get("回款额", 0.0), 2)
        out.append({
            "合同编号": pid,
            "开票单位": inv_sp_map.get((pid, sp)) or inv_map.get(pid, ""),
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
    df["_sort"] = df["合同编号"].apply(lambda x: (1 if x == "其他" else 0, x))
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
        view_df = summary_df.copy()
        if "开票单位" in view_df.columns:
            view_df["开票单位"] = view_df["开票单位"].apply(
                lambda s: truncate_units_text(s, max_n=2, max_chars=18)
            )
        st.dataframe(
            view_df,
            width="stretch",
            height=min(400, 45 + len(view_df) * 36),
            column_config={
                "开票单位": st.column_config.TextColumn(
                    "开票单位", help="多家时仅显示前几家，完整列表见下方明细。"
                ),
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
    pay_cols_pref = ["回款日期", "回款金额", "核销金额", "开票单位", "订货单位"]
    tl_cols_pref = ["回款日期", "回款金额", "匹配发货日期", "回款周期(天)",
                    "时效提成比例", "时效提成金额"]

    for _, row in summary_df.iterrows():
        if filter_status and row["状态"] not in filter_status:
            continue

        pid = row["合同编号"]
        sp = row["销售员"]
        inv = row.get("开票单位", "")
        units = split_units(inv)
        inv_short = truncate_units_text(inv)

        d_amt = float(row["发货额"])
        p_amt = float(row["回款额"])
        tl_amt = float(row["时效提成合计"])
        unpaid = max(d_amt - p_amt, 0.0)

        # 简洁标题：合同号 · 销售员 · 截断的客户 · 回款/时效
        title_segs = [str(pid), str(sp)]
        if inv_short:
            title_segs.append(inv_short)
        title_segs.append(f"回款 {_fmt_money(p_amt)}")
        if tl_amt:
            title_segs.append(f"时效提成 {_fmt_money(tl_amt)}")
        header = "　·　".join(title_segs)

        with st.expander(header, expanded=False):
            badge_html = (
                f'<div style="display:flex;flex-wrap:wrap;gap:.4rem;align-items:center;'
                f'margin:.1rem 0 .35rem;">{status_badge(row["状态"])}</div>'
            )
            st.html(badge_html)

            metas: list[tuple[str, str]] = []
            if row["销售部门"]:
                metas.append(("销售部门", row["销售部门"]))
            metas.append(("销售员", str(sp)))
            metas.append(("合同编号", str(pid)))
            st.html(meta_row(metas))

            if units:
                st.html(section_title(f"开票单位（{len(units)}）"))
                st.html(unit_pills(units))

            st.html(kpi_row([
                ("发货额", _fmt_money(d_amt), False),
                ("回款额", _fmt_money(p_amt), False),
                ("未回款额", _fmt_money(unpaid), False),
                ("时效提成", _fmt_money(tl_amt), True),
            ]))

            d_sub = delivery_df[
                (delivery_df["合同编号"].astype(str) == pid)
                & (delivery_df["销售员"].astype(str) == sp)
            ].copy()
            p_sub = payment_df[
                (payment_df["合同编号"].astype(str) == pid)
                & (payment_df["销售员"].astype(str) == sp)
            ].copy()
            tl_sub = timeliness_df[
                (timeliness_df["合同编号"].astype(str) == pid)
                & (timeliness_df["销售员"].astype(str) == sp)
            ].copy() if not timeliness_df.empty else pd.DataFrame()

            col_d, col_p = st.columns(2, gap="large")
            with col_d:
                st.html(section_title("发货明细"))
                if d_sub.empty:
                    st.caption("（无发货记录）")
                else:
                    cols = [c for c in del_cols_pref if c in d_sub.columns]
                    show = d_sub[cols].sort_values("发货日期") if "发货日期" in cols else d_sub[cols]
                    st.dataframe(
                        format_date_columns(show.reset_index(drop=True)),
                        width="stretch",
                        height=min(260, 45 + len(show) * 36),
                        column_config={
                            "发货金额": st.column_config.NumberColumn(format="%.2f"),
                        },
                    )
            with col_p:
                st.html(section_title("回款明细"))
                if p_sub.empty:
                    st.caption("（无回款记录）")
                else:
                    cols = [c for c in pay_cols_pref if c in p_sub.columns]
                    show = p_sub[cols].sort_values("回款日期") if "回款日期" in cols else p_sub[cols]
                    st.dataframe(
                        format_date_columns(show.reset_index(drop=True)),
                        width="stretch",
                        height=min(260, 45 + len(show) * 36),
                        column_config={
                            "回款金额": st.column_config.NumberColumn(format="%.2f"),
                        },
                    )

            st.html(section_title("时效匹配明细"))
            if tl_sub.empty:
                st.caption("（无时效记录）")
            else:
                cols = [c for c in tl_cols_pref if c in tl_sub.columns]
                st.dataframe(
                    format_date_columns(tl_sub[cols].reset_index(drop=True)),
                    width="stretch",
                    height=min(260, 45 + len(tl_sub) * 36),
                    column_config={
                        "回款金额": st.column_config.NumberColumn(format="%.2f"),
                        "时效提成金额": st.column_config.NumberColumn(format="%.2f"),
                    },
                )

    with st.expander("原始时效提成明细（扁平表）", expanded=False):
        st.dataframe(format_date_columns(timeliness_df), width="stretch", height=400)
        csv = timeliness_df.to_csv(index=False).encode("utf-8-sig")
        st.download_button("下载时效明细", csv, "回款时效提成.csv", "text/csv",
                           key="dl_timeliness_flat")
