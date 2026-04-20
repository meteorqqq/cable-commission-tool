"""总提成汇总页"""

import io

import streamlit as st
import pandas as pd

from db.database import save_calc_session
from web._ui import fmt_money, meta_row, kpi_row
from web._table import dataframe_with_fulltext_panel
from web._cache import (
    get_invoice_units_by_contract_sp, get_contract_overview, session_cache,
)


def _status_of(d_amt: float, p_amt: float) -> str:
    if d_amt <= 0 and p_amt > 0:
        return "未发货（已收款）"
    if d_amt <= 0 and p_amt <= 0:
        return "未发货"
    if p_amt <= 0:
        return "未回款"
    if p_amt + 1e-2 >= d_amt:
        return "已完成"
    return "部分回款"


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
                "状态": r.get("状态", ""),
            }

    tl_lookup: dict[tuple[str, str], dict] = {}
    if timeliness_df is not None and not timeliness_df.empty:
        for (sp, pid), grp in timeliness_df.groupby(["销售员", "合同编号"]):
            pay = pd.to_numeric(grp.get("回款金额", 0), errors="coerce").fillna(0)
            tl_amt = pd.to_numeric(grp.get("时效提成金额", 0), errors="coerce").fillna(0)
            days = pd.to_numeric(grp.get("回款周期(天)", 0), errors="coerce").fillna(0)
            pay_sum = float(pay.sum())
            tl_sum = float(tl_amt.sum())
            ratio = (tl_sum / pay_sum) if pay_sum > 1e-9 else 0.0
            day_avg = float((days * pay).sum() / pay_sum) if pay_sum > 1e-9 else 0.0
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

        by_sp.setdefault(sp, []).append({
            "合同编号": pid,
            "开票单位": inv_sp_map.get((pid, sp), ""),
            "合同发货额": d_amt,
            "合同回款额": p_amt,
            "完成额度系数": f"{quota_ratio * 100:.2f}%",
            "完成额度提成": quota_amt,
            "利润系数": round(float(prof.get("利润系数", 0.0)), 4),
            "利润提成率": prof.get("利润提成率", "") or "",
            "利润系数(提成率)": f"{profit_ratio * 100:.2f}%",
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
        df["_sort"] = df["合同编号"].apply(lambda x: (1 if str(x) == "其他" else 0, str(x)))
        df = df.sort_values(["_sort", "合同编号"]).drop(columns=["_sort"]).reset_index(drop=True)
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
                "合同编号": r["合同编号"],
                "开票单位": r["开票单位"],
                "合同发货额": r["合同发货额"],
                "合同回款额": r["合同回款额"],
                "完成额度系数": r.get("完成额度系数", ""),
                "完成额度提成": r.get("完成额度提成", 0.0),
                "利润系数": r.get("利润系数", 0.0),
                "利润提成率": r.get("利润提成率", ""),
                "利润系数(提成率)": r.get("利润系数(提成率)", ""),
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
    flat["_sort"] = flat["合同编号"].apply(
        lambda x: (1 if str(x) == "其他" else 0, str(x))
    )
    flat = flat.sort_values(["销售员", "_sort", "合同编号"]).drop(columns=["_sort"]).reset_index(drop=True)
    return flat


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
                            "合同编号", "开票单位", "合同发货额", "合同回款额",
                            "完成额度系数", "完成额度提成",
                            "利润系数", "利润提成率", "利润系数(提成率)", "利润提成",
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
                        csv = sp_df.to_csv(index=False).encode("utf-8-sig")
                        st.download_button(
                            f"下载 {sp} 的合同明细",
                            csv, f"{sp}_合同明细.csv", "text/csv",
                            key=f"dl_total_sp_{sp}",
                        )
                shown += 1

            if shown == 0:
                st.info("当前筛选条件下没有销售员。")

        st.markdown("")
        col_dl, col_save = st.columns(2, gap="large")

        with col_dl:
            buf = io.BytesIO()
            sheets = {"总提成汇总": total_df}

            flat_breakdown = _build_contract_breakdown_flat(total_df)
            if not flat_breakdown.empty:
                sheets["销售员合同明细"] = flat_breakdown

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

            with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                for name, df in sheets.items():
                    out = df.copy()
                    for col in out.columns:
                        if pd.api.types.is_datetime64_any_dtype(out[col]):
                            out[col] = out[col].dt.strftime("%Y-%m-%d")
                    out.to_excel(writer, sheet_name=name, index=False)

            st.download_button(
                "导出全部结果 (Excel)",
                buf.getvalue(),
                "提成汇总.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

        with col_save:
            session_name = st.text_input("会话名称", value="", placeholder="输入备注名称",
                                          label_visibility="collapsed")
            if st.button("保存到历史记录", use_container_width=True):
                results = {"总提成汇总": total_df}

                flat_breakdown = _build_contract_breakdown_flat(total_df)
                if not flat_breakdown.empty:
                    results["销售员合同明细"] = flat_breakdown

                ov = get_contract_overview()
                if ov is not None and not ov.empty:
                    results["合同编号汇总"] = ov
                for key, state_key in [
                    ("交货明细", "delivery_df"),
                    ("回款明细", "payment_df"),
                    ("完成额度提成", "quota_result"),
                    ("利润提成", "profit_result"),
                    ("回款时效提成", "timeliness_result"),
                ]:
                    df = st.session_state.get(state_key)
                    if df is not None and not df.empty:
                        results[key] = df
                sid = save_calc_session(username, session_name or "未命名", results)
                st.success(f"已保存 (ID: {sid})")
