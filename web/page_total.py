"""总提成汇总页"""

import streamlit as st
import pandas as pd

from db.database import save_calc_session
from engine.calculator import contract_status as _status_of
from web._ui import fmt_money, meta_row, kpi_row
from web._download import render_df_download_buttons, render_multi_download_buttons
from web._table import dataframe_with_fulltext_panel
from web._cache import (
    get_invoice_units_by_contract_sp, get_contract_overview,
    get_main_contract_map, session_cache,
)


def _parse_pct_to_ratio(v) -> float:
    """把 '1.25%' / 1.25 / 0.0125 等形式统一转成比例(0~1)。"""
    if v is None:
        return 0.0
    s = str(v).strip()
    if not s or s.lower() in ("nan", "none"):
        return 0.0
    try:
        if s.endswith("%"):
            return float(s[:-1]) / 100.0
        x = float(s)
        return x / 100.0 if x > 1 else x
    except Exception:
        return 0.0


@session_cache("total_summary_df", scope="calc")
def _build_total_df() -> pd.DataFrame | None:
    quota_df = st.session_state.get("quota_result")
    profit_df = st.session_state.get("profit_result")
    timeliness_df = st.session_state.get("timeliness_result")

    if quota_df is None and profit_df is None and timeliness_df is None:
        return None

    all_persons: dict[str, dict] = {}

    if quota_df is not None and not quota_df.empty:
        for _, r in quota_df.iterrows():
            name = r.get("销售员", "")
            if not name:
                continue
            if name not in all_persons:
                all_persons[name] = {"销售员": name, "销售部门": r.get("销售部门", "")}
            all_persons[name]["完成额度提成(元)"] = \
                all_persons[name].get("完成额度提成(元)", 0) + (r.get("完成额度提成(元)", 0) or 0)

    if profit_df is not None and not profit_df.empty:
        for _, r in profit_df.iterrows():
            name = r.get("销售员", "")
            if not name:
                continue
            if name not in all_persons:
                all_persons[name] = {"销售员": name, "销售部门": r.get("销售部门", "")}
            all_persons[name]["利润提成(元)"] = \
                all_persons[name].get("利润提成(元)", 0) + (r.get("利润提成金额", 0) or 0)

    if timeliness_df is not None and not timeliness_df.empty:
        for _, r in timeliness_df.iterrows():
            name = r.get("销售员", "")
            if not name:
                continue
            if name not in all_persons:
                all_persons[name] = {"销售员": name, "销售部门": r.get("销售部门", "")}
            all_persons[name]["回款时效提成(元)"] = \
                all_persons[name].get("回款时效提成(元)", 0) + (r.get("时效提成金额", 0) or 0)

    if not all_persons:
        return None

    rows = []
    for p in all_persons.values():
        q = round(p.get("完成额度提成(元)", 0), 2)
        pr = round(p.get("利润提成(元)", 0), 2)
        t = round(p.get("回款时效提成(元)", 0), 2)
        rows.append({
            "销售员": p["销售员"],
            "销售部门": p.get("销售部门", ""),
            "完成额度提成(元)": q,
            "利润提成(元)": pr,
            "回款时效提成(元)": t,
            "总提成(元)": round(q + pr + t, 2),
        })

    df = pd.DataFrame(rows)
    return df.sort_values("总提成(元)", ascending=False).reset_index(drop=True)


@session_cache("total_contract_breakdown", scope="calc")
def _build_contract_breakdown_by_salesperson() -> dict[str, pd.DataFrame]:
    """为每位销售员构建"按合同"明细表，合并利润 / 回款时效 / 发货 / 回款 等信息。"""
    delivery_df = st.session_state.get("delivery_df")
    payment_df = st.session_state.get("payment_df")
    quota_df = st.session_state.get("quota_result")
    profit_df = st.session_state.get("profit_result")
    timeliness_df = st.session_state.get("timeliness_result")

    inv_sp_map = get_invoice_units_by_contract_sp()
    main_map = get_main_contract_map()

    # 先构建 (销售员, 合同号) 的基础集合
    rows: dict[tuple[str, str], dict] = {}

    def _key(sp, pid):
        return str(sp), str(pid)

    if delivery_df is not None and not delivery_df.empty \
            and "销售员" in delivery_df.columns and "合同编号" in delivery_df.columns:
        grp = delivery_df.groupby(["销售员", "合同编号"])["发货金额"].sum()
        for (sp, pid), amt in grp.items():
            rows.setdefault(_key(sp, pid), {})["合同发货额"] = float(amt)

    if payment_df is not None and not payment_df.empty \
            and "销售员" in payment_df.columns and "合同编号" in payment_df.columns:
        grp = payment_df.groupby(["销售员", "合同编号"])["回款金额"].sum()
        for (sp, pid), amt in grp.items():
            rows.setdefault(_key(sp, pid), {})["合同回款额"] = float(amt)

    quota_rate_map: dict[str, float] = {}
    if quota_df is not None and not quota_df.empty and "销售员" in quota_df.columns:
        for _, r in quota_df.iterrows():
            sp = str(r.get("销售员", "")).strip()
            if not sp:
                continue
            quota_rate_map[sp] = _parse_pct_to_ratio(r.get("提成比例", 0))

    profit_lookup: dict[tuple[str, str], dict] = {}
    if profit_df is not None and not profit_df.empty:
        for _, r in profit_df.iterrows():
            k = _key(r.get("销售员", ""), r.get("合同编号", ""))
            profit_lookup[k] = {
                "利润提成金额": float(r.get("利润提成金额", 0) or 0),
                "利润提成率": r.get("利润提成率", ""),
                "利润系数": float(r.get("K系数", 0) or 0) if pd.notna(r.get("K系数", None)) else 0.0,
                "利润分类": r.get("利润分类", ""),
                "系数来源": str(r.get("系数来源", "") or ""),
                "主合同编号": str(r.get("主合同编号", "") or ""),
                "状态": r.get("状态", ""),
            }

    tl_lookup: dict[tuple[str, str], dict] = {}
    if timeliness_df is not None and not timeliness_df.empty:
        for (sp, pid), grp in timeliness_df.groupby(["销售员", "合同编号"]):
            pay_all = pd.to_numeric(grp.get("回款金额", 0), errors="coerce").fillna(0)
            tl_amt_all = pd.to_numeric(grp.get("时效提成金额", 0), errors="coerce").fillna(0)
            days_raw = pd.to_numeric(grp.get("回款周期(天)", 0), errors="coerce")
            tl_sum = float(tl_amt_all.sum())

            # 仅取匹配到发货的回款（回款周期非空）参与加权
            # 超出发货额 / 无匹配发货 的行不应稀释该合同的时效系数与平均天数
            matched_mask = days_raw.notna()
            pay_matched = pay_all[matched_mask]
            days_matched = days_raw[matched_mask].fillna(0)
            matched_pay_sum = float(pay_matched.sum())
            if matched_pay_sum > 1e-9:
                ratio = tl_sum / matched_pay_sum
                day_avg = float((days_matched * pay_matched).sum() / matched_pay_sum)
            else:
                ratio = 0.0
                day_avg = 0.0

            tl_lookup[_key(sp, pid)] = {
                "时效提成金额": tl_sum,
                "时效系数": ratio,
                "时效天数": day_avg,
            }

    # 合并所有 (sp, pid)
    all_keys = set(rows) | set(profit_lookup) | set(tl_lookup)

    by_sp: dict[str, list[dict]] = {}
    for (sp, pid) in all_keys:
        base = rows.get((sp, pid), {})
        prof = profit_lookup.get((sp, pid), {})
        d_amt = round(base.get("合同发货额", 0.0), 2)
        p_amt = round(base.get("合同回款额", 0.0), 2)
        quota_ratio = quota_rate_map.get(sp, 0.0)
        quota_amt = round(p_amt * quota_ratio, 2)
        profit_amt = round(prof.get("利润提成金额", 0.0), 2)
        profit_ratio = _parse_pct_to_ratio(prof.get("利润提成率", ""))
        tl_info = tl_lookup.get((sp, pid), {})
        tl_amt = round(float(tl_info.get("时效提成金额", 0.0)), 2)
        tl_ratio = float(tl_info.get("时效系数", 0.0))
        tl_days = float(tl_info.get("时效天数", 0.0))
        status = prof.get("状态") or _status_of(d_amt, p_amt)

        main_pid = prof.get("主合同编号") or main_map.get(pid, pid)
        by_sp.setdefault(sp, []).append({
            "主合同编号": main_pid,
            "合同编号": pid,
            "开票单位": inv_sp_map.get((pid, sp), ""),
            "合同发货额": d_amt,
            "合同回款额": p_amt,
            "完成额度系数": f"{quota_ratio * 100:.2f}%",
            "完成额度提成": quota_amt,
            "利润系数": round(float(prof.get("利润系数", 0.0)), 4),
            "利润提成率": prof.get("利润提成率", "") or "",
            "利润系数(提成率)": f"{profit_ratio * 100:.2f}%",
            "系数来源": prof.get("系数来源", "") or "",
            "利润提成": profit_amt,
            "时效天数": round(tl_days, 1),
            "时效系数": f"{tl_ratio * 100:.2f}%",
            "回款时效提成": tl_amt,
            "合同小计": round(quota_amt + profit_amt + tl_amt, 2),
            "状态": status,
        })

    out: dict[str, pd.DataFrame] = {}
    for sp, items in by_sp.items():
        df = pd.DataFrame(items)
        df["_main_sort"] = df["主合同编号"].apply(
            lambda x: (1 if str(x) == "其他" else 0, str(x))
        )
        df["_sub_sort"] = df["合同编号"].apply(
            lambda x: (1 if str(x) == "其他" else 0, str(x))
        )
        # 主合同自身排最前；同主合同内部再按分项合同号升序
        df["_is_main"] = (df["主合同编号"] == df["合同编号"]).astype(int)
        df = (
            df.sort_values(
                ["_main_sort", "_is_main", "_sub_sort"],
                ascending=[True, False, True],
            )
            .drop(columns=["_main_sort", "_sub_sort", "_is_main"])
            .reset_index(drop=True)
        )
        out[sp] = df
    return out


def _build_contract_breakdown_flat(total_df: pd.DataFrame) -> pd.DataFrame:
    """扁平化：每位销售员 × 每笔合同一行，供 Excel 导出用。"""
    breakdown = _build_contract_breakdown_by_salesperson()
    if not breakdown:
        return pd.DataFrame()
    dept_map = {
        str(r["销售员"]): str(r.get("销售部门", "") or "")
        for _, r in total_df.iterrows()
    }
    rows = []
    for sp, df in breakdown.items():
        for _, r in df.iterrows():
            rows.append({
                "销售员": sp,
                "销售部门": dept_map.get(sp, ""),
                "主合同编号": r.get("主合同编号", r["合同编号"]),
                "合同编号": r["合同编号"],
                "开票单位": r["开票单位"],
                "合同发货额": r["合同发货额"],
                "合同回款额": r["合同回款额"],
                "完成额度系数": r.get("完成额度系数", ""),
                "完成额度提成": r.get("完成额度提成", 0.0),
                "利润系数": r.get("利润系数", 0.0),
                "利润提成率": r.get("利润提成率", ""),
                "利润系数(提成率)": r.get("利润系数(提成率)", ""),
                "系数来源": r.get("系数来源", ""),
                "利润提成": r["利润提成"],
                "时效天数": r.get("时效天数", 0.0),
                "时效系数": r.get("时效系数", ""),
                "回款时效提成": r["回款时效提成"],
                "合同小计": r["合同小计"],
                "状态": r["状态"],
            })
    if not rows:
        return pd.DataFrame()
    flat = pd.DataFrame(rows)
    flat["_main_sort"] = flat["主合同编号"].apply(
        lambda x: (1 if str(x) == "其他" else 0, str(x))
    )
    flat["_sub_sort"] = flat["合同编号"].apply(
        lambda x: (1 if str(x) == "其他" else 0, str(x))
    )
    flat["_is_main"] = (flat["主合同编号"] == flat["合同编号"]).astype(int)
    flat = (
        flat.sort_values(
            ["销售员", "_main_sort", "_is_main", "_sub_sort"],
            ascending=[True, True, False, True],
        )
        .drop(columns=["_main_sort", "_sub_sort", "_is_main"])
        .reset_index(drop=True)
    )
    return flat


def _build_export_template_df(total_df: pd.DataFrame) -> pd.DataFrame:
    """按用户给定模板导出（列名/顺序固定）。"""
    flat = _build_contract_breakdown_flat(total_df)
    if flat.empty:
        # 即便空数据也返回固定表头，保证导出格式稳定
        return pd.DataFrame(columns=[
            "销售员", "销售部门", "总销售金额", "回款金额",
            "完成额度提成(元)", "完成比系数",
            "利润提成(元)", "利润系数", "系数来源",
            "回款时效提成(元)", "时效（天数）", "时效系数",
            "总提成（元）", "主合同号", "合同号", "客户名",
        ])

    # 销售员 -> 部门/完成额度系数（来自 quota_result）
    quota_df = st.session_state.get("quota_result")
    dept_map: dict[str, str] = {}
    quota_ratio_map: dict[str, float] = {}
    if quota_df is not None and not quota_df.empty:
        for _, r in quota_df.iterrows():
            sp = str(r.get("销售员", "")).strip()
            if not sp:
                continue
            dept_map[sp] = str(r.get("销售部门", "") or "")
            quota_ratio_map[sp] = _parse_pct_to_ratio(r.get("提成比例", 0))

    # 时效天数来自 timeliness_result 的合同级加权平均
    # 仅统计匹配到发货的回款（回款周期(天) 非空）；超发/未匹配不参与加权
    tl_df = st.session_state.get("timeliness_result")
    tl_days_map: dict[tuple[str, str], float] = {}
    if tl_df is not None and not tl_df.empty:
        for (sp, pid), grp in tl_df.groupby(["销售员", "合同编号"]):
            pay = pd.to_numeric(grp.get("回款金额", 0), errors="coerce").fillna(0)
            days_raw = pd.to_numeric(grp.get("回款周期(天)", 0), errors="coerce")
            mask = days_raw.notna()
            pay_m = pay[mask]
            days_m = days_raw[mask].fillna(0)
            pay_sum = float(pay_m.sum())
            day_avg = float((days_m * pay_m).sum() / pay_sum) if pay_sum > 1e-9 else 0.0
            tl_days_map[(str(sp), str(pid))] = day_avg

    rows = []
    for _, r in flat.iterrows():
        sp = str(r.get("销售员", "") or "")
        pid = str(r.get("合同编号", "") or "")
        pay_amt = float(r.get("合同回款额", 0) or 0)
        sale_amt = float(r.get("合同发货额", 0) or 0)
        quota_ratio = float(quota_ratio_map.get(sp, 0.0))
        quota_amt = float(r.get("完成额度提成", 0) or 0)
        profit_amt = float(r.get("利润提成", 0) or 0)
        tl_amt = float(r.get("回款时效提成", 0) or 0)
        tl_days = float(tl_days_map.get((sp, pid), r.get("时效天数", 0) or 0))

        # 优先用合同小计，兜底时三项相加
        total_amt = float(r.get("合同小计", quota_amt + profit_amt + tl_amt) or 0)

        rows.append({
            "销售员": sp,
            "销售部门": dept_map.get(sp, str(r.get("销售部门", "") or "")),
            "总销售金额": round(sale_amt, 2),
            "回款金额": round(pay_amt, 2),
            "完成额度提成(元)": round(quota_amt, 2),
            "完成比系数": f"{quota_ratio * 100:.2f}%",
            "利润提成(元)": round(profit_amt, 2),
            "利润系数": r.get("利润系数", 0),
            "系数来源": r.get("系数来源", "") or "",
            "回款时效提成(元)": round(tl_amt, 2),
            "时效（天数）": round(tl_days, 1),
            "时效系数": r.get("时效系数", ""),
            "总提成（元）": round(total_amt, 2),
            "主合同号": str(r.get("主合同编号", pid) or pid),
            "合同号": pid,
            "客户名": str(r.get("开票单位", "") or ""),
        })

    out = pd.DataFrame(rows)
    # 严格固定列顺序
    cols = [
        "销售员", "销售部门", "总销售金额", "回款金额",
        "完成额度提成(元)", "完成比系数",
        "利润提成(元)", "利润系数", "系数来源",
        "回款时效提成(元)", "时效（天数）", "时效系数",
        "总提成（元）", "主合同号", "合同号", "客户名",
    ]
    out = out[cols]
    return out


def _collect_export_sheets(total_df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """汇总所有用于导出 / 保存历史的 sheet，保证两处口径一致。

    「总提成汇总」为界面「销售员提成汇总」表；「销售员合同明细」为原先 Excel
    第一页（按合同模板、列名固定）的导出结果。
    """
    sheets: dict[str, pd.DataFrame] = {
        "总提成汇总": total_df.copy(),
        "销售员合同明细": _build_export_template_df(total_df),
    }

    ov = get_contract_overview()
    if ov is not None and not ov.empty:
        sheets["合同编号汇总"] = ov

    for key, state_key in [
        ("交货明细", "delivery_df"),
        ("回款明细", "payment_df"),
        ("完成额度提成", "quota_result"),
        ("利润提成", "profit_result"),
        ("回款时效提成", "timeliness_result"),
    ]:
        df = st.session_state.get(state_key)
        if df is not None and not df.empty:
            sheets[key] = df
    return sheets


def render_total(username: str):
    st.header("总提成汇总")

    if st.button("汇总计算", type="primary", use_container_width=True):
        total_df = _build_total_df()
        if total_df is None or total_df.empty:
            st.warning("请先在各提成页面完成计算")
        else:
            st.session_state["total_result"] = total_df
            st.success(f"汇总完成，共 {len(total_df)} 位销售员")

    total_df = st.session_state.get("total_result")
    if total_df is not None and not total_df.empty:
        st.markdown("")
        c1, c2, c3, c4 = st.columns(4, gap="medium")
        with c1:
            st.metric("总人数", f"{len(total_df)} 人")
        with c2:
            st.metric("总提成合计", f"{total_df['总提成(元)'].sum():,.2f} 元")
        with c3:
            st.metric("人均提成", f"{total_df['总提成(元)'].mean():,.2f} 元")
        with c4:
            st.metric("最高提成", f"{total_df['总提成(元)'].max():,.2f} 元")

        st.markdown("")
        with st.container(border=True):
            st.subheader("销售员提成汇总")
            st.dataframe(total_df, width="stretch", height=400)

        # ── 按销售员展示合同明细 ──
        st.markdown("")
        with st.container(border=True):
            st.subheader("按销售员展开合同明细")
            st.caption("点击任一销售员查看其名下所有合同的发货、回款、利润提成与时效提成。")

            all_depts = sorted(
                {str(d).strip() for d in total_df.get("销售部门", pd.Series(dtype=str)).dropna()
                 if str(d).strip()}
            )
            fc1, fc2 = st.columns([1, 1], gap="medium")
            with fc1:
                filter_dept = st.multiselect(
                    "按销售部门筛选", options=all_depts, default=[],
                    key="total_filter_dept",
                )
            with fc2:
                search_sp = st.text_input(
                    "按销售员姓名搜索", value="", placeholder="输入姓名片段",
                    key="total_filter_sp_search",
                )

            breakdown = _build_contract_breakdown_by_salesperson()

            shown = 0
            for _, row in total_df.iterrows():
                sp = str(row["销售员"])
                dept = str(row.get("销售部门", ""))
                if filter_dept and dept not in filter_dept:
                    continue
                if search_sp and search_sp.strip() and search_sp.strip() not in sp:
                    continue

                sp_df = breakdown.get(sp, pd.DataFrame())
                n_contracts = len(sp_df)
                total_amt = float(row.get("总提成(元)", 0) or 0)

                header_parts = [sp]
                if dept:
                    header_parts.append(dept)
                header_parts.append(f"合同 {n_contracts} 笔")
                header_parts.append(f"总提成 {fmt_money(total_amt)}")
                header = "　·　".join(header_parts)

                with st.expander(header, expanded=False):
                    st.html(meta_row([
                        ("销售部门", dept),
                        ("完成额度提成",
                         fmt_money(row.get("完成额度提成(元)", 0) or 0)),
                        ("利润提成",
                         fmt_money(row.get("利润提成(元)", 0) or 0)),
                        ("回款时效提成",
                         fmt_money(row.get("回款时效提成(元)", 0) or 0)),
                    ]))
                    st.html(kpi_row([
                        ("合同数", f"{n_contracts}", False),
                        ("发货额合计",
                         fmt_money(sp_df["合同发货额"].sum()) if not sp_df.empty else "0.00", False),
                        ("回款额合计",
                         fmt_money(sp_df["合同回款额"].sum()) if not sp_df.empty else "0.00", False),
                        ("合同提成小计",
                         fmt_money(sp_df["合同小计"].sum()) if not sp_df.empty else "0.00", True),
                    ]))

                    if sp_df.empty:
                        st.caption("（未匹配到合同明细，请确认已完成利润/时效提成计算）")
                    else:
                        display_cols = [
                            "主合同编号", "合同编号", "开票单位",
                            "合同发货额", "合同回款额",
                            "完成额度系数", "完成额度提成",
                            "利润系数", "利润提成率", "利润系数(提成率)",
                            "系数来源", "利润提成",
                            "时效天数", "时效系数", "回款时效提成",
                            "合同小计", "状态",
                        ]
                        show_df = sp_df[[c for c in display_cols if c in sp_df.columns]]
                        dataframe_with_fulltext_panel(
                            show_df,
                            key=f"total_sp_contracts_{sp}",
                            fulltext_cols=["开票单位"],
                            height=min(400, 45 + len(show_df) * 36),
                            column_config={
                                "主合同编号": st.column_config.TextColumn(
                                    "主合同编号",
                                    help="分项合同所属的主合同号；无主合同时与合同编号相同。",
                                ),
                                "系数来源": st.column_config.TextColumn(
                                    "系数来源",
                                    help="本行 K 系数的来源：主合同 / 自身 / 未录入。",
                                ),
                                "开票单位": st.column_config.TextColumn(
                                    "开票单位",
                                    help="保留全称；显示区域不足时可点击单元格查看完整文本。",
                                ),
                                "合同发货额": st.column_config.NumberColumn(format="%.2f"),
                                "合同回款额": st.column_config.NumberColumn(format="%.2f"),
                                "完成额度提成": st.column_config.NumberColumn(format="%.2f"),
                                "利润系数": st.column_config.NumberColumn(format="%.4f"),
                                "利润提成": st.column_config.NumberColumn(format="%.2f"),
                                "时效天数": st.column_config.NumberColumn(format="%.1f"),
                                "回款时效提成": st.column_config.NumberColumn(format="%.2f"),
                                "合同小计": st.column_config.NumberColumn(format="%.2f"),
                            },
                        )
                        render_df_download_buttons(
                            sp_df,
                            base_filename=f"{sp}_合同明细",
                            sheet_name="合同明细",
                            key_prefix=f"dl_total_sp_{sp}",
                        )
                shown += 1

            if shown == 0:
                st.info("当前筛选条件下没有销售员。")

        st.markdown("")
        col_dl, col_save = st.columns(2, gap="large")

        sheets = _collect_export_sheets(total_df)

        with col_dl:
            render_multi_download_buttons(
                sheets,
                base_filename="提成汇总",
                key_prefix="total_export_all",
            )

        with col_save:
            session_name = st.text_input("会话名称", value="", placeholder="输入备注名称",
                                          label_visibility="collapsed")
            if st.button("保存到历史记录", use_container_width=True):
                sid = save_calc_session(username, session_name or "未命名", sheets)
                st.success(f"已保存 (ID: {sid})")
