"""销售员详情页：按销售员展示其全部合同及发货/回款明细。"""

import streamlit as st
import pandas as pd

from engine.calculator import (
    list_salespersons, build_salesperson_detail, format_date_columns,
    contract_status,
)
from web._ui import (
    fmt_money, truncate_units_text,
    status_badge, unit_pills, kpi_row, meta_row, section_title,
)
from web._table import dataframe_with_fulltext_panel
from web._cache import session_cache


@session_cache("salesperson_names", scope="data")
def _cached_salesperson_names() -> list[str]:
    return list_salespersons(
        st.session_state.get("delivery_df"),
        st.session_state.get("payment_df"),
    )


@session_cache("salesperson_detail", scope="calc")
def _cached_salesperson_detail(sel: str) -> dict:
    """按 (calc_version, sel) 缓存单位销售员的 detail，避免切页回来重算。"""
    return build_salesperson_detail(
        sel,
        st.session_state.get("delivery_df"),
        st.session_state.get("payment_df"),
        profit_df=st.session_state.get("profit_result"),
        timeliness_df=st.session_state.get("timeliness_result"),
    )


_fmt_money = fmt_money


def render_salesperson():
    st.header("销售员详情")

    delivery_df = st.session_state.get("delivery_df")
    payment_df = st.session_state.get("payment_df")
    if delivery_df is None and payment_df is None:
        st.warning("请先在数据导入页上传交货或回款数据")
        return

    names = _cached_salesperson_names()
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

    detail = _cached_salesperson_detail(sel)

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

    normal_contracts = [c for c in detail["合同列表"] if c["合同编号"] != "其他"]
    other_contract = next(
        (c for c in detail["合同列表"] if c["合同编号"] == "其他"), None
    )

    summary_rows = []
    for c in detail["合同列表"]:
        units_str = " / ".join(c["订货单位"]) if c["订货单位"] else ""
        summary_rows.append({
            "合同编号": c["合同编号"],
            "订货单位": units_str,
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
        dataframe_with_fulltext_panel(
            summary_df,
            key="salesperson_summary_selectable",
            fulltext_cols=["订货单位"],
            height=min(400, 45 + len(summary_df) * 36),
            column_config={
                "订货单位": st.column_config.TextColumn(
                    "订货单位", help="保留全称；显示区域不足时可点击单元格查看完整文本。"
                ),
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
    inv_units = list(c.get("开票单位") or [])
    ord_units = list(c.get("订货单位") or [])
    inv_short = truncate_units_text(" / ".join(inv_units), max_n=1, max_chars=22)

    header_segs = [str(c["合同编号"])]
    if inv_short:
        header_segs.append(inv_short)
    header_segs.append(f"回款 {_fmt_money(c['回款额'])}")
    if c.get("时效提成", 0):
        header_segs.append(f"时效提成 {_fmt_money(c.get('时效提成', 0))}")
    if c.get("利润提成", 0):
        header_segs.append(f"利润提成 {_fmt_money(c.get('利润提成', 0))}")
    header = "　·　".join(header_segs)

    with st.expander(header, expanded=False):
        st.html(
            f'<div style="display:flex;flex-wrap:wrap;gap:.4rem;'
            f'align-items:center;margin:.1rem 0 .35rem;">'
            f'{status_badge(c["状态"])}</div>'
        )

        st.html(meta_row([
            ("合同编号", str(c["合同编号"])),
            ("利润提成率", str(c.get("利润提成率") or "")),
            ("利润分类", str(c.get("利润分类") or "")),
        ]))

        if ord_units:
            st.html(section_title(f"订货单位（{len(ord_units)}）"))
            st.html(unit_pills(ord_units))
        if inv_units:
            st.html(section_title(f"开票单位（{len(inv_units)}）"))
            st.html(unit_pills(inv_units))

        st.html(kpi_row([
            ("发货额", _fmt_money(c["发货额"]), False),
            ("回款额", _fmt_money(c["回款额"]), False),
            ("未回款额", _fmt_money(c["未回款额"]), False),
            ("利润提成", _fmt_money(c.get("利润提成", 0)), True),
            ("时效提成", _fmt_money(c.get("时效提成", 0)), True),
        ]))

        col_d, col_p = st.columns(2, gap="large")
        with col_d:
            st.html(section_title("发货明细"))
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
            st.html(section_title("回款明细"))
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
            st.html(section_title("时效提成明细"))
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
    with st.container(border=True):
        st.html(
            '<div style="display:flex;flex-wrap:wrap;align-items:center;gap:.6rem;'
            'margin:.1rem 0 .35rem;">'
            '<div style="font-size:1.05rem;font-weight:600;color:#0F172A;">其他（无合同号）</div>'
            f'{status_badge(other["状态"])}</div>'
        )
        st.html(kpi_row([
            ("发货额", _fmt_money(other["发货额"]), False),
            ("回款额", _fmt_money(other["回款额"]), False),
            ("未回款额", _fmt_money(other["未回款额"]), False),
            ("利润提成", _fmt_money(other.get("利润提成", 0)), True),
            ("时效提成", _fmt_money(other.get("时效提成", 0)), True),
        ]))

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

        st.html(section_title(f"按客户拆分（{len(units)} 家）"))
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
            unpaid = max(d_amt - p_amt, 0.0)
            sub_status = contract_status(d_amt, p_amt)

            unit_short = unit if len(unit) <= 28 else unit[:28] + "…"
            header_segs = [unit_short, f"回款 {_fmt_money(p_amt)}"]
            if d_amt:
                header_segs.insert(1, f"发货 {_fmt_money(d_amt)}")
            header = "　·　".join(header_segs)

            with st.expander(header, expanded=False):
                st.html(
                    f'<div style="display:flex;flex-wrap:wrap;gap:.4rem;'
                    f'align-items:center;margin:.1rem 0 .35rem;">'
                    f'{status_badge(sub_status)}</div>'
                )
                st.html(meta_row([("客户", unit)]))
                st.html(kpi_row([
                    ("发货额", _fmt_money(d_amt), False),
                    ("回款额", _fmt_money(p_amt), False),
                    ("未回款额", _fmt_money(unpaid), False),
                ]))
                _render_unit_tables(d_sub, p_sub, label=unit)


def _render_unit_tables(d_sub: pd.DataFrame, p_sub: pd.DataFrame, label: str):
    col_d, col_p = st.columns(2, gap="large")
    with col_d:
        st.html(section_title("发货明细"))
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
        st.html(section_title("回款明细"))
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
