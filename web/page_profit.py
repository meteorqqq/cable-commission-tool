"""利润提成页"""

import tempfile
from pathlib import Path

import streamlit as st
import pandas as pd

from engine.calculator import (
    calc_profit_commission, ContractPricing,
    load_contract_pricing_excel, DEFAULT_PROFIT_BASE_RATE, DEFAULT_PROFIT_K_MAX,
)
from web._cache import (
    get_invoice_units_by_contract, get_invoice_units_by_contract_sp,
    get_project_list, bump_calc_version,
)
from db.database import (
    save_rules, load_rules, save_contract_prices, load_contract_prices,
)


def _profit_result_for_arrow(df: pd.DataFrame) -> pd.DataFrame:
    """消除空字符串与数值混用的 object 列，避免 Streamlit/pyarrow 序列化失败。"""
    out = df.copy()
    for c in ("合同发货额", "合同回款额", "指导价", "合同价", "成本价", "K系数", "利润提成金额"):
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    return out


def _build_price_df(username: str) -> pd.DataFrame:
    delivery_df = st.session_state.get("delivery_df")
    projects = get_project_list()

    saved_prices = {p["project_id"]: p for p in load_contract_prices(username)}
    inv_map = get_invoice_units_by_contract()

    proj_totals = st.session_state.get("_proj_delivery_totals_cache")
    cache_key = f"_proj_delivery_totals::v{st.session_state.get('_data_version', 0)}"
    if cache_key in st.session_state:
        proj_totals = st.session_state[cache_key]
    else:
        proj_totals = {}
        if delivery_df is not None and "合同编号" in delivery_df.columns:
            for pid, grp in delivery_df.groupby("合同编号"):
                proj_totals[pid] = round(grp["发货金额"].sum(), 2)
        st.session_state[cache_key] = proj_totals

    rows = []
    for pid in projects:
        inv = inv_map.get(pid, "")
        if pid in saved_prices:
            sp = saved_prices[pid]
            rows.append({
                "合同编号": pid,
                "开票单位": inv,
                "指导价": sp["guide_price"],
                "合同价": sp["contract_price"],
                "成本价": sp["cost_price"],
            })
        else:
            total = proj_totals.get(pid, 0)
            rows.append({
                "合同编号": pid, "开票单位": inv,
                "指导价": total, "合同价": total, "成本价": 0.0,
            })

    if not rows:
        return pd.DataFrame(columns=["合同编号", "开票单位", "指导价", "合同价", "成本价"])
    out = pd.DataFrame(rows)
    for c in ("指导价", "合同价", "成本价"):
        out[c] = pd.to_numeric(out[c], errors="coerce")
    return out


def render_profit(username: str):
    st.header("利润提成")

    delivery_df = st.session_state.get("delivery_df")
    payment_df = st.session_state.get("payment_df")

    if delivery_df is None or payment_df is None:
        st.warning("请先在数据导入页上传交货和回款数据")
        return

    col_rule, col_import = st.columns(2, gap="large")

    with col_rule:
        with st.container(border=True):
            st.subheader("规则设置")
            saved = load_rules(username, "profit")
            base_rate = saved["base_rate"] if saved else DEFAULT_PROFIT_BASE_RATE
            k_max = saved["k_max"] if saved else DEFAULT_PROFIT_K_MAX

            base_rate = st.number_input("基础提成率 (%)", value=float(base_rate),
                                         min_value=0.0, step=0.01, format="%.4f")
            k_max = st.number_input("K 系数上限", value=float(k_max),
                                     min_value=0.0, step=0.1, format="%.2f")

            if st.button("保存规则", key="save_profit_rules"):
                save_rules(username, "profit", {"base_rate": base_rate, "k_max": k_max})
                st.success("规则已保存")

    with col_import:
        with st.container(border=True):
            st.subheader("导入合同价格")
            uploaded = st.file_uploader("上传合同价格 Excel", type=["xls", "xlsx", "csv"],
                                         key="pricing_uploader")
            if uploaded is not None:
                with tempfile.NamedTemporaryFile(delete=False, suffix=Path(uploaded.name).suffix) as tmp:
                    tmp.write(uploaded.read())
                    tmp_path = tmp.name
                try:
                    pricing_map = load_contract_pricing_excel(tmp_path)
                    imported_rows = []
                    for pid, p in pricing_map.items():
                        imported_rows.append({
                            "project_id": pid,
                            "guide_price": p.guide_price,
                            "contract_price": p.contract_price,
                            "cost_price": p.cost_price,
                        })
                    save_contract_prices(username, imported_rows)
                    st.success(f"已导入 {len(imported_rows)} 条合同价格")
                    st.rerun()
                except Exception as e:
                    st.error(f"导入失败: {e}")

    with st.container(border=True):
        st.subheader("合同价格表")
        price_df = _build_price_df(username)
        edited_prices = st.data_editor(
            price_df,
            width="stretch",
            key="price_editor",
            disabled=["合同编号", "开票单位"],
            height=300,
            column_config={
                "开票单位": st.column_config.TextColumn(
                    "开票单位", help="按合同编号自动汇总（来自交货 / 回款明细），仅供识别。",
                ),
                "指导价": st.column_config.NumberColumn(
                    "指导价", format="%.2f", min_value=None, step=0.01
                ),
                "合同价": st.column_config.NumberColumn(
                    "合同价", format="%.2f", min_value=None, step=0.01
                ),
                "成本价": st.column_config.NumberColumn(
                    "成本价", format="%.2f", min_value=None, step=0.01
                ),
            },
        )

        c1, c2 = st.columns(2)
        with c1:
            if st.button("保存价格表", use_container_width=True):
                rows = []
                for _, r in edited_prices.iterrows():
                    gp = pd.to_numeric(r["指导价"], errors="coerce")
                    cp = pd.to_numeric(r["合同价"], errors="coerce")
                    cos = pd.to_numeric(r["成本价"], errors="coerce")
                    rows.append({
                        "project_id": r["合同编号"],
                        "guide_price": float(0 if pd.isna(gp) else gp),
                        "contract_price": float(0 if pd.isna(cp) else cp),
                        "cost_price": float(0 if pd.isna(cos) else cos),
                    })
                save_contract_prices(username, rows)
                st.success("价格已保存到数据库")
        with c2:
            if st.button("计算利润提成", type="primary", use_container_width=True):
                prices = {}
                for _, r in edited_prices.iterrows():
                    pid = r["合同编号"]
                    gp = pd.to_numeric(r["指导价"], errors="coerce")
                    cp = pd.to_numeric(r["合同价"], errors="coerce")
                    cos = pd.to_numeric(r["成本价"], errors="coerce")
                    prices[pid] = ContractPricing(
                        project_id=pid,
                        guide_price=float(0 if pd.isna(gp) else gp),
                        contract_price=float(0 if pd.isna(cp) else cp),
                        cost_price=float(0 if pd.isna(cos) else cos),
                    )
                try:
                    result = calc_profit_commission(
                        delivery_df, payment_df, prices,
                        base_rate_pct=base_rate, k_max=k_max)
                    st.session_state["profit_result"] = result
                    bump_calc_version()
                    st.success(f"计算完成，共 {len(result)} 条记录")
                except Exception as e:
                    st.error(f"计算出错: {e}")

    result = st.session_state.get("profit_result")
    if result is not None and not result.empty:
        display_df = _profit_result_for_arrow(result)
        if (
            "合同编号" in display_df.columns
            and "销售员" in display_df.columns
            and "开票单位" not in display_df.columns
        ):
            inv_sp_map = get_invoice_units_by_contract_sp()
            inv_map = get_invoice_units_by_contract()
            keys = list(zip(display_df["合同编号"].astype(str), display_df["销售员"].astype(str)))
            display_df.insert(
                display_df.columns.get_loc("合同编号") + 1,
                "开票单位",
                [inv_sp_map.get(k) or inv_map.get(k[0], "") for k in keys],
            )

        with st.container(border=True):
            st.subheader("计算结果")

            m1, m2, m3, m4 = st.columns(4, gap="medium")
            total_n = len(display_df)
            commissioned_n = int((display_df.get("利润提成金额", pd.Series(dtype=float)).fillna(0) > 0).sum())
            total_pay = float(pd.to_numeric(display_df.get("合同回款额", 0), errors="coerce").fillna(0).sum())
            total_commission = float(pd.to_numeric(display_df.get("利润提成金额", 0), errors="coerce").fillna(0).sum())
            with m1:
                st.metric("合同总数", f"{total_n}")
            with m2:
                st.metric("已结提成合同", f"{commissioned_n}")
            with m3:
                st.metric("回款合计", f"{total_pay:,.2f}")
            with m4:
                st.metric("利润提成合计", f"{total_commission:,.2f}")

            if "状态" in display_df.columns:
                status_options = ["已完成", "部分回款", "未回款", "未发货", "未发货（已收款）"]
                status_options = [s for s in status_options if s in set(display_df["状态"].unique())]
                picked = st.multiselect(
                    "按状态筛选",
                    options=status_options,
                    default=[],
                    key="profit_filter_status",
                )
                if picked:
                    display_df = display_df[display_df["状态"].isin(picked)]

            st.dataframe(
                display_df,
                width="stretch",
                height=420,
                column_config={
                    "开票单位": st.column_config.TextColumn(
                        "开票单位", help="保留全称；显示区域不足时可点击单元格查看完整文本。"
                    ),
                    "合同发货额": st.column_config.NumberColumn(format="%.2f"),
                    "合同回款额": st.column_config.NumberColumn(format="%.2f"),
                    "指导价": st.column_config.NumberColumn(format="%.2f"),
                    "合同价": st.column_config.NumberColumn(format="%.2f"),
                    "成本价": st.column_config.NumberColumn(format="%.2f"),
                    "K系数": st.column_config.NumberColumn(format="%.4f"),
                    "利润提成金额": st.column_config.NumberColumn(format="%.2f"),
                },
            )
            csv = display_df.to_csv(index=False).encode("utf-8-sig")
            st.download_button("下载结果 CSV", csv, "利润提成.csv", "text/csv")
