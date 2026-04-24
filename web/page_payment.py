"""回款时效提成页 —— 按合同号为主体展示"""

import streamlit as st
import pandas as pd

from engine.calculator import (
    annotate_delivery_business_type,
    annotate_payment_business_type,
    calc_payment_timeliness, DEFAULT_PAYMENT_TIERS, format_date_columns,
    contract_status as _status_of,
)
from db.database import save_rules, load_rules
from web._ui import (
    fmt_money, split_units, truncate_units_text,
    status_badge, unit_pills, kpi_row, meta_row, section_title, page_intro,
)
from web._download import (
    render_df_download_buttons,
    dataframes_to_excel_bytes,
    EXCEL_MIME,
)
from web._table import dataframe_with_fulltext_panel
from web._cache import (
    get_invoice_units_by_contract, get_invoice_units_by_contract_sp,
    get_salesperson_dept_map, get_delivery_by_pid_sp, get_payment_by_pid_sp,
    get_timeliness_by_pid_sp, bump_calc_version, session_cache,
)


_fmt_money = fmt_money


@session_cache("payment_contract_summary", scope="calc")
def _build_contract_summary_cached() -> pd.DataFrame:
    return _build_contract_summary(
        st.session_state.get("timeliness_result"),
        st.session_state.get("delivery_df"),
        st.session_state.get("payment_df"),
    )


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
        grp_neg = delivery_df.groupby(["合同编号", "销售员"])["发货金额"].apply(
            lambda s: bool((pd.to_numeric(s, errors="coerce").fillna(0) < -0.01).any())
        )
        for key, has_neg in grp_neg.items():
            if has_neg:
                rows.setdefault((str(key[0]), str(key[1])), {})["含退货"] = True

    if payment_df is not None and not payment_df.empty:
        grp = payment_df.groupby(["合同编号", "销售员"])["回款金额"].sum()
        for (pid, sp), amt in grp.items():
            rows.setdefault((str(pid), str(sp)), {})["回款额"] = float(amt)
        grp_neg = payment_df.groupby(["合同编号", "销售员"])["回款金额"].apply(
            lambda s: bool((pd.to_numeric(s, errors="coerce").fillna(0) < -0.01).any())
        )
        for key, has_neg in grp_neg.items():
            if has_neg:
                rows.setdefault((str(key[0]), str(key[1])), {})["含退款"] = True

    tl_grp = {}
    if timeliness_df is not None and not timeliness_df.empty:
        for (pid, sp), grp in timeliness_df.groupby(["合同编号", "销售员"]):
            tl_grp[(str(pid), str(sp))] = float(
                pd.to_numeric(grp["时效提成金额"], errors="coerce").fillna(0).sum()
            )

    dept_map = get_salesperson_dept_map()

    inv_sp_map = get_invoice_units_by_contract_sp()
    inv_map = get_invoice_units_by_contract()

    out = []
    for (pid, sp), v in rows.items():
        d_amt = round(v.get("发货额", 0.0), 2)
        p_amt = round(v.get("回款额", 0.0), 2)
        business_flags = []
        if v.get("含退货"):
            business_flags.append("有退货")
        if v.get("含退款"):
            business_flags.append("有退款")
        out.append({
            "合同编号": pid,
            "开票单位": inv_sp_map.get((pid, sp)) or inv_map.get(pid, ""),
            "销售员": sp,
            "销售部门": dept_map.get(sp, ""),
            "发货额": d_amt,
            "回款额": p_amt,
            "未回款额": round(max(d_amt - p_amt, 0), 2),
            "业务标记": " / ".join(business_flags),
            "时效提成合计": round(tl_grp.get((pid, sp), 0.0), 2),
            "状态": _status_of(d_amt, p_amt),
        })

    df = pd.DataFrame(out)
    if df.empty:
        return df
    df["_sort"] = df["合同编号"].apply(lambda x: (1 if x == "其他" else 0, x))
    return df.sort_values(["_sort", "销售员"]).drop(columns=["_sort"]).reset_index(drop=True)


def _build_sp_export_sheets(
    sp: str,
    summary_df: pd.DataFrame,
    timeliness_df: pd.DataFrame | None,
    delivery_df: pd.DataFrame | None,
    payment_df: pd.DataFrame | None,
) -> dict[str, pd.DataFrame]:
    """为单个销售员装配多 sheet 导出数据。"""
    sheets: dict[str, pd.DataFrame] = {}

    sum_sub = summary_df[summary_df["销售员"].astype(str) == str(sp)].copy()
    sheets["合同汇总"] = sum_sub.reset_index(drop=True)

    pids = set(sum_sub["合同编号"].astype(str).tolist())

    def _filter(df: pd.DataFrame | None) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame()
        sub = df.copy()
        if "销售员" in sub.columns:
            sub = sub[sub["销售员"].astype(str) == str(sp)]
        elif "合同编号" in sub.columns:
            sub = sub[sub["合同编号"].astype(str).isin(pids)]
        if "发货金额" in sub.columns:
            sub = annotate_delivery_business_type(sub)
        if "回款金额" in sub.columns:
            sub = annotate_payment_business_type(sub)
        return sub.reset_index(drop=True)

    del_cols_pref = [
        "发货日期", "业务类型", "合同编号", "销售员", "销售部门",
        "发货金额", "订货单位", "开票单位",
    ]
    pay_cols_pref = [
        "回款日期", "业务类型", "合同编号", "销售员", "销售部门",
        "回款金额", "核销金额", "开票单位", "订货单位",
    ]
    tl_cols_pref = [
        "合同编号", "销售员", "销售部门", "客户单位", "回款日期", "业务类型", "回款金额",
        "匹配发货日期", "回款周期(天)", "时效提成比例", "时效提成金额",
    ]

    def _reorder(df: pd.DataFrame, pref: list[str]) -> pd.DataFrame:
        if df.empty:
            return df
        cols = [c for c in pref if c in df.columns] + \
               [c for c in df.columns if c not in pref]
        return df[cols]

    sheets["发货明细"] = _reorder(_filter(delivery_df), del_cols_pref)
    sheets["回款明细"] = _reorder(_filter(payment_df), pay_cols_pref)
    sheets["时效匹配明细"] = _reorder(_filter(timeliness_df), tl_cols_pref)
    return sheets


def _build_and_offer_per_sp_download(
    *,
    summary_df: pd.DataFrame,
    timeliness_df: pd.DataFrame | None,
    delivery_df: pd.DataFrame | None,
    payment_df: pd.DataFrame | None,
    picked_sps: list[str],
) -> None:
    """渲染"按销售员导出"的按钮：
    - 未选销售员：导出整张合并表（全部销售员）
    - 只选 1 位：导出该销售员的多 sheet 单文件
    - 选 ≥2 位：导出一个 ZIP，内含每位销售员一份 Excel
    """
    import io
    import zipfile

    if summary_df.empty:
        st.caption("暂无可导出数据。")
        return

    if not picked_sps:
        sp_options = sorted(
            v for v in summary_df["销售员"].dropna().astype(str).unique()
            if v and v.lower() not in ("nan", "none")
        )
        merged: dict[str, pd.DataFrame] = {}
        for sp in sp_options:
            sheets = _build_sp_export_sheets(
                sp, summary_df, timeliness_df, delivery_df, payment_df
            )
            for name, sub in sheets.items():
                prev = merged.get(name)
                if prev is None or prev.empty:
                    merged[name] = sub
                elif not sub.empty:
                    merged[name] = pd.concat([prev, sub], ignore_index=True)
        excel_bytes = dataframes_to_excel_bytes(merged)
        st.download_button(
            "下载 Excel（全部销售员）",
            excel_bytes,
            "回款时效提成_全部销售员.xlsx",
            EXCEL_MIME,
            key="payment_export_all_xlsx",
            use_container_width=True,
        )
        return

    if len(picked_sps) == 1:
        sp = picked_sps[0]
        sheets = _build_sp_export_sheets(
            sp, summary_df, timeliness_df, delivery_df, payment_df
        )
        excel_bytes = dataframes_to_excel_bytes(sheets)
        safe = str(sp).replace("/", "_").replace("\\", "_")
        st.download_button(
            f"下载 Excel（{sp}）",
            excel_bytes,
            f"回款时效提成_{safe}.xlsx",
            EXCEL_MIME,
            key="payment_export_single_xlsx",
            use_container_width=True,
        )
        return

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for sp in picked_sps:
            sheets = _build_sp_export_sheets(
                sp, summary_df, timeliness_df, delivery_df, payment_df
            )
            safe = str(sp).replace("/", "_").replace("\\", "_")
            zf.writestr(
                f"回款时效提成_{safe}.xlsx",
                dataframes_to_excel_bytes(sheets),
            )
    st.download_button(
        f"下载 Excel ZIP（{len(picked_sps)} 位销售员）",
        buf.getvalue(),
        "回款时效提成_按销售员.zip",
        "application/zip",
        key="payment_export_multi_zip",
        use_container_width=True,
    )


def render_payment(username: str):
    st.html(page_intro(
        "回款时效提成",
        "按回款和发货的匹配关系计算时效提成，退款会自动冲销，孤立退货会单独留痕。",
        eyebrow="Timeliness Commission",
    ))

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
            bump_calc_version()
            st.success(f"计算完成，时效记录 {len(timeliness_df)} 条")
        except Exception as e:
            st.error(f"计算出错: {e}")

    timeliness_df = st.session_state.get("timeliness_result")
    if timeliness_df is None:
        return

    st.markdown("")

    summary_df = _build_contract_summary_cached()

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
        dataframe_with_fulltext_panel(
            summary_df,
            key="payment_summary_selectable",
            fulltext_cols=["开票单位"],
            height=min(400, 45 + len(summary_df) * 36),
            column_config={
                "开票单位": st.column_config.TextColumn(
                    "开票单位", help="保留全称；显示区域不足时可点击单元格查看完整文本。"
                ),
                "发货额": st.column_config.NumberColumn(format="%.2f"),
                "回款额": st.column_config.NumberColumn(format="%.2f"),
                "未回款额": st.column_config.NumberColumn(format="%.2f"),
                "时效提成合计": st.column_config.NumberColumn(format="%.2f"),
            },
        )
        render_df_download_buttons(
            summary_df,
            base_filename="合同汇总",
            sheet_name="合同汇总",
            key_prefix="payment_contract_summary",
        )

    st.markdown("")
    with st.container(border=True):
        st.subheader("按销售员导出")
        st.caption(
            "选择一位或多位销售员，导出的 Excel 包含该销售员名下的："
            "合同汇总、发货明细、回款明细、时效匹配明细（多工作表）。"
        )
        sp_options = sorted(
            v for v in summary_df["销售员"].dropna().astype(str).unique()
            if v and v.lower() not in ("nan", "none")
        )
        picked_sps = st.multiselect(
            "销售员",
            options=sp_options,
            default=[],
            key="payment_export_by_sp",
            placeholder="留空表示导出全部销售员（单文件）",
        )
        _build_and_offer_per_sp_download(
            summary_df=summary_df,
            timeliness_df=timeliness_df,
            delivery_df=delivery_df,
            payment_df=payment_df,
            picked_sps=picked_sps,
        )

    st.markdown("")
    st.subheader("合同明细")
    st.caption("点击展开查看该合同的发货明细、回款明细与时效匹配结果。")

    def _sorted_unique(col: str) -> list[str]:
        if col not in summary_df.columns:
            return []
        vals = summary_df[col].dropna().astype(str).str.strip()
        vals = [v for v in vals.unique() if v and v.lower() not in ("nan", "none")]
        return sorted(vals)

    all_pids = _sorted_unique("合同编号")
    all_sps = _sorted_unique("销售员")
    all_depts = _sorted_unique("销售部门")

    inv_options: set[str] = set()
    for s in summary_df.get("开票单位", pd.Series(dtype=str)).dropna():
        for u in split_units(s):
            if u:
                inv_options.add(u)
    all_invs = sorted(inv_options)

    fc1, fc2 = st.columns(2, gap="medium")
    with fc1:
        filter_status = st.multiselect(
            "按状态筛选",
            options=[
                "已完成", "部分回款", "未回款", "未发货", "未发货（已收款）",
            ],
            default=[],
            key="payment_filter_status",
        )
        filter_pids = st.multiselect(
            "按合同号筛选", options=all_pids, default=[],
            key="payment_filter_pids",
        )
    with fc2:
        filter_sps = st.multiselect(
            "按销售员筛选", options=all_sps, default=[],
            key="payment_filter_sps",
        )
        filter_depts = st.multiselect(
            "按销售部门筛选", options=all_depts, default=[],
            key="payment_filter_depts",
        )

    filter_invs = st.multiselect(
        "按开票单位筛选", options=all_invs, default=[],
        key="payment_filter_invs",
        help="只要该合同的开票单位包含任一选中单位即保留。",
    )

    del_cols_pref = ["发货日期", "业务类型", "发货金额", "订货单位", "开票单位"]
    pay_cols_pref = ["回款日期", "业务类型", "回款金额", "核销金额", "开票单位", "订货单位"]
    tl_cols_pref = ["客户单位", "回款日期", "业务类型", "回款金额", "匹配发货日期", "回款周期(天)",
                    "时效提成比例", "时效提成金额"]

    def _row_passes(row) -> bool:
        if filter_status and row["状态"] not in filter_status:
            return False
        if filter_pids and str(row["合同编号"]) not in filter_pids:
            return False
        if filter_sps and str(row["销售员"]) not in filter_sps:
            return False
        if filter_depts and str(row.get("销售部门", "")) not in filter_depts:
            return False
        if filter_invs:
            row_units = set(split_units(row.get("开票单位", "")))
            if not row_units.intersection(filter_invs):
                return False
        return True

    filtered_rows = [r for _, r in summary_df.iterrows() if _row_passes(r)]
    st.caption(f"筛选结果：{len(filtered_rows)} / {len(summary_df)} 个合同")

    del_lookup = get_delivery_by_pid_sp()
    pay_lookup = get_payment_by_pid_sp()
    tl_lookup = get_timeliness_by_pid_sp()

    for row in filtered_rows:

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
            if row.get("业务标记"):
                metas.append(("业务标记", str(row["业务标记"])))
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

            key = (str(pid), str(sp))
            d_sub = annotate_delivery_business_type(del_lookup.get(key, pd.DataFrame()))
            p_sub = annotate_payment_business_type(pay_lookup.get(key, pd.DataFrame()))
            tl_sub = annotate_payment_business_type(tl_lookup.get(key, pd.DataFrame()))

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
        render_df_download_buttons(
            timeliness_df,
            base_filename="回款时效提成",
            sheet_name="回款时效提成",
            key_prefix="payment_timeliness_flat",
        )
