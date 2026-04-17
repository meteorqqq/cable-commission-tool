"""回款时效提成页"""

import streamlit as st
import pandas as pd

from engine.calculator import calc_payment_timeliness, DEFAULT_PAYMENT_TIERS
from db.database import save_rules, load_rules


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
    del_summary = st.session_state.get("del_summary")
    pay_summary = st.session_state.get("pay_summary")

    if timeliness_df is not None:
        st.markdown("")
        tab1, tab2, tab3 = st.tabs(["回款时效提成明细", "出库按月汇总", "回款按月汇总"])

        with tab1:
            st.dataframe(timeliness_df, width="stretch", height=400)
            csv = timeliness_df.to_csv(index=False).encode("utf-8-sig")
            st.download_button("下载时效明细", csv, "回款时效提成.csv", "text/csv",
                               key="dl_timeliness")

        with tab2:
            if del_summary is not None and not del_summary.empty:
                st.dataframe(del_summary, width="stretch", height=400)
                csv = del_summary.to_csv(index=False).encode("utf-8-sig")
                st.download_button("下载出库汇总", csv, "出库按月汇总.csv", "text/csv",
                                   key="dl_del")

        with tab3:
            if pay_summary is not None and not pay_summary.empty:
                st.dataframe(pay_summary, width="stretch", height=400)
                csv = pay_summary.to_csv(index=False).encode("utf-8-sig")
                st.download_button("下载回款汇总", csv, "回款按月汇总.csv", "text/csv",
                                   key="dl_pay")
