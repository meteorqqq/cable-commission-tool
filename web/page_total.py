"""总提成汇总页"""

import io

import streamlit as st
import pandas as pd

from db.database import save_calc_session


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
            st.dataframe(total_df, width="stretch", height=400)

        st.markdown("")
        col_dl, col_save = st.columns(2, gap="large")

        with col_dl:
            buf = io.BytesIO()
            sheets = {"总提成汇总": total_df}
            for key, state_key in [
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
                for key, state_key in [
                    ("完成额度提成", "quota_result"),
                    ("利润提成", "profit_result"),
                    ("回款时效提成", "timeliness_result"),
                ]:
                    df = st.session_state.get(state_key)
                    if df is not None and not df.empty:
                        results[key] = df
                sid = save_calc_session(username, session_name or "未命名", results)
                st.success(f"已保存 (ID: {sid})")
