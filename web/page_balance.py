"""结余合同页

列出所有"未结清"合同（累计发货 ≠ 累计回款）的明细，按销售员归组。
支持：
- 一键导出当前结余清单
- 导入上期（例如去年末）结余 Excel，并以"期初发货 / 期初回款"的形式
  追加到当期的 delivery_df / payment_df；方便继续参与回款时效、利润提成
  和完成额度等各项计算，计算完毕再导出本期末的新结余。
"""

from __future__ import annotations

from datetime import datetime
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from engine.calculator import (
    annotate_delivery_business_type,
    annotate_payment_business_type,
    contract_status as _status_of,
)
from web._cache import (
    bump_data_version,
    get_invoice_units_by_contract,
    get_invoice_units_by_contract_sp,
    get_salesperson_dept_map,
    session_cache,
)
from web._download import render_df_download_buttons
from web._ui import fmt_money, section_title, page_intro, empty_state


_BAL_COLS = [
    "销售员", "销售部门", "合同编号", "主合同编号", "开票单位",
    "完成比提成比例", "利润提成率",
    "累计发货额", "累计回款额", "结余金额", "业务标记",
    "状态", "最近发货日期", "最近回款日期",
]

_OPENING_TAG_DELIVERY = "__期初结余__"
_OPENING_TAG_PAYMENT = "__期初结余__"


@session_cache("balance_df", scope="calc")
def _build_balance_df_cached() -> pd.DataFrame:
    return _build_balance_df(
        st.session_state.get("delivery_df"),
        st.session_state.get("payment_df"),
    )


def _build_balance_df(
    delivery_df: pd.DataFrame | None,
    payment_df: pd.DataFrame | None,
) -> pd.DataFrame:
    """按 合同编号 × 销售员 汇总，仅保留累计发货 ≠ 累计回款的"未结清"行。"""
    rows: dict[tuple[str, str], dict] = {}

    if delivery_df is not None and not delivery_df.empty:
        dd = delivery_df.copy()
        dd["发货金额"] = pd.to_numeric(dd.get("发货金额", 0), errors="coerce").fillna(0)
        for (pid, sp), g in dd.groupby(["合同编号", "销售员"]):
            key = (str(pid), str(sp))
            rows.setdefault(key, {})
            rows[key]["累计发货额"] = float(g["发货金额"].sum())
            rows[key]["含退货"] = bool((g["发货金额"] < -0.01).any())
            if "发货日期" in g.columns:
                last = pd.to_datetime(g["发货日期"], errors="coerce").max()
                rows[key]["最近发货日期"] = last if pd.notna(last) else None
            if "主合同编号" in g.columns:
                vals = [v for v in g["主合同编号"].astype(str).tolist()
                        if v and v.lower() not in ("nan", "none")]
                rows[key]["主合同编号"] = vals[0] if vals else str(pid)

    if payment_df is not None and not payment_df.empty:
        pp = payment_df.copy()
        pp["回款金额"] = pd.to_numeric(pp.get("回款金额", 0), errors="coerce").fillna(0)
        for (pid, sp), g in pp.groupby(["合同编号", "销售员"]):
            key = (str(pid), str(sp))
            rows.setdefault(key, {})
            rows[key]["累计回款额"] = float(g["回款金额"].sum())
            rows[key]["含退款"] = bool((g["回款金额"] < -0.01).any())
            if "回款日期" in g.columns:
                last = pd.to_datetime(g["回款日期"], errors="coerce").max()
                rows[key]["最近回款日期"] = last if pd.notna(last) else None
            if "主合同编号" in g.columns and "主合同编号" not in rows[key]:
                vals = [v for v in g["主合同编号"].astype(str).tolist()
                        if v and v.lower() not in ("nan", "none")]
                rows[key]["主合同编号"] = vals[0] if vals else str(pid)

    if not rows:
        return pd.DataFrame(columns=_BAL_COLS)

    inv_sp_map = get_invoice_units_by_contract_sp()
    inv_map = get_invoice_units_by_contract()
    dept_map = get_salesperson_dept_map()
    quota_df = st.session_state.get("quota_result")
    profit_df = st.session_state.get("profit_result")

    quota_rate_map: dict[str, str] = {}
    if quota_df is not None and not quota_df.empty and "销售员" in quota_df.columns:
        for _, r in quota_df.iterrows():
            sp = str(r.get("销售员", "") or "").strip()
            if not sp:
                continue
            quota_rate_map[sp] = str(r.get("提成比例", "") or "")

    profit_rate_map: dict[tuple[str, str], str] = {}
    if (
        profit_df is not None
        and not profit_df.empty
        and "销售员" in profit_df.columns
        and "合同编号" in profit_df.columns
    ):
        for _, r in profit_df.iterrows():
            key = (str(r.get("合同编号", "") or ""), str(r.get("销售员", "") or ""))
            profit_rate_map[key] = str(r.get("利润提成率", "") or "")

    out = []
    for (pid, sp), v in rows.items():
        d = round(v.get("累计发货额", 0.0), 2)
        p = round(v.get("累计回款额", 0.0), 2)
        if abs(d - p) < 0.005:
            continue  # 结清的跳过
        business_flags = []
        if v.get("含退货"):
            business_flags.append("有退货")
        if v.get("含退款"):
            business_flags.append("有退款")
        out.append({
            "销售员": sp,
            "销售部门": dept_map.get(sp, ""),
            "合同编号": pid,
            "主合同编号": v.get("主合同编号", pid) or pid,
            "开票单位": inv_sp_map.get((pid, sp)) or inv_map.get(pid, ""),
            "完成比提成比例": quota_rate_map.get(sp, ""),
            "利润提成率": profit_rate_map.get((pid, sp), ""),
            "累计发货额": d,
            "累计回款额": p,
            "结余金额": round(d - p, 2),
            "业务标记": " / ".join(business_flags),
            "状态": _status_of(d, p),
            "最近发货日期": v.get("最近发货日期"),
            "最近回款日期": v.get("最近回款日期"),
        })

    df = pd.DataFrame(out, columns=_BAL_COLS)
    if df.empty:
        return df
    df["_sp"] = df["销售员"].astype(str)
    df["_pid"] = df["合同编号"].astype(str)
    df["_pid_sort"] = df["_pid"].apply(lambda x: (1 if x == "其他" else 0, x))
    df = (
        df.sort_values(["_sp", "_pid_sort"])
        .drop(columns=["_sp", "_pid", "_pid_sort"])
        .reset_index(drop=True)
    )
    return df


def _count_opening_rows() -> int:
    """当前 session 中已经"应用到数据"的期初结余条数（用于撤销）。"""
    dd = st.session_state.get("delivery_df")
    if dd is None or dd.empty or "来源" not in dd.columns:
        return 0
    return int((dd["来源"].astype(str) == _OPENING_TAG_DELIVERY).sum())


def _parse_opening_excel(path: str) -> pd.DataFrame:
    """宽松解析期初结余 Excel：匹配本页导出的列名，也兼容简写。"""
    raw = pd.read_excel(path)
    raw.columns = [str(c).strip() for c in raw.columns]

    def _pick(aliases: list[str]) -> str | None:
        for a in aliases:
            for c in raw.columns:
                if a == c or a in c:
                    return c
        return None

    col_map = {
        "销售员": _pick(["销售员"]),
        "销售部门": _pick(["销售部门", "部门"]),
        "合同编号": _pick(["合同编号", "合同号"]),
        "主合同编号": _pick(["主合同编号", "主合同号"]),
        "开票单位": _pick(["开票单位", "客户", "单位"]),
        "累计发货额": _pick(["累计发货额", "发货额", "发货金额", "已发货"]),
        "累计回款额": _pick(["累计回款额", "回款额", "回款金额", "已回款"]),
        "最近发货日期": _pick(["最近发货日期", "发货日期"]),
        "最近回款日期": _pick(["最近回款日期", "回款日期"]),
    }
    if not col_map["合同编号"] or not col_map["销售员"]:
        raise ValueError(
            "缺少必需的列：合同编号 / 销售员。当前列："
            f"{list(raw.columns)}"
        )
    if not col_map["累计发货额"] and not col_map["累计回款额"]:
        raise ValueError("缺少发货额或回款额列，无法作为期初结余使用。")

    out = pd.DataFrame()
    out["合同编号"] = raw[col_map["合同编号"]].astype(str).str.strip()
    out["销售员"] = raw[col_map["销售员"]].astype(str).str.strip()
    out["销售部门"] = (
        raw[col_map["销售部门"]].astype(str).str.strip()
        if col_map["销售部门"] else ""
    )
    out["主合同编号"] = (
        raw[col_map["主合同编号"]].astype(str).str.strip()
        if col_map["主合同编号"] else out["合同编号"]
    )
    out.loc[out["主合同编号"].isin(["", "nan", "None"]), "主合同编号"] = out["合同编号"]
    out["开票单位"] = (
        raw[col_map["开票单位"]].astype(str).str.strip()
        if col_map["开票单位"] else ""
    )
    out["累计发货额"] = (
        pd.to_numeric(raw[col_map["累计发货额"]], errors="coerce").fillna(0)
        if col_map["累计发货额"] else 0.0
    )
    out["累计回款额"] = (
        pd.to_numeric(raw[col_map["累计回款额"]], errors="coerce").fillna(0)
        if col_map["累计回款额"] else 0.0
    )
    out["最近发货日期"] = (
        pd.to_datetime(raw[col_map["最近发货日期"]], errors="coerce")
        if col_map["最近发货日期"] else pd.NaT
    )
    out["最近回款日期"] = (
        pd.to_datetime(raw[col_map["最近回款日期"]], errors="coerce")
        if col_map["最近回款日期"] else pd.NaT
    )
    # 扔掉空行
    out = out[(out["合同编号"] != "") & (out["销售员"] != "")].reset_index(drop=True)
    return out


def _apply_opening_to_session(
    opening_df: pd.DataFrame, base_date: pd.Timestamp,
) -> tuple[int, int]:
    """把期初结余追加到 session 的 delivery_df / payment_df。

    返回 (追加发货行数, 追加回款行数)。
    """
    delivery = st.session_state.get("delivery_df")
    payment = st.session_state.get("payment_df")

    d_new_rows: list[dict] = []
    p_new_rows: list[dict] = []
    for _, r in opening_df.iterrows():
        pid = str(r["合同编号"])
        sp = str(r["销售员"])
        main = str(r.get("主合同编号") or pid)
        dept = str(r.get("销售部门") or "")
        inv = str(r.get("开票单位") or "")
        d_amt = float(r.get("累计发货额") or 0)
        p_amt = float(r.get("累计回款额") or 0)
        d_date = r.get("最近发货日期")
        p_date = r.get("最近回款日期")
        d_date = d_date if pd.notna(d_date) else base_date
        p_date = p_date if pd.notna(p_date) else base_date

        if d_amt:
            d_new_rows.append({
                "销售员": sp, "销售部门": dept,
                "合同编号": pid, "主合同编号": main,
                "开票单位": inv, "发货金额": d_amt, "发货日期": d_date,
                "来源": _OPENING_TAG_DELIVERY,
            })
        if p_amt:
            p_new_rows.append({
                "销售员": sp, "销售部门": dept,
                "合同编号": pid, "主合同编号": main,
                "开票单位": inv, "回款金额": p_amt, "回款日期": p_date,
                "核销金额": p_amt,
                "来源": _OPENING_TAG_PAYMENT,
            })

    if d_new_rows:
        d_add = annotate_delivery_business_type(pd.DataFrame(d_new_rows))
        if delivery is None or delivery.empty:
            st.session_state["delivery_df"] = d_add
        else:
            if "来源" not in delivery.columns:
                delivery = delivery.assign(来源="")
            st.session_state["delivery_df"] = pd.concat(
                [delivery, d_add], ignore_index=True, sort=False,
            )

    if p_new_rows:
        p_add = annotate_payment_business_type(pd.DataFrame(p_new_rows))
        if payment is None or payment.empty:
            st.session_state["payment_df"] = p_add
        else:
            if "来源" not in payment.columns:
                payment = payment.assign(来源="")
            st.session_state["payment_df"] = pd.concat(
                [payment, p_add], ignore_index=True, sort=False,
            )

    if d_new_rows or p_new_rows:
        bump_data_version()
    return len(d_new_rows), len(p_new_rows)


def _remove_opening_from_session() -> tuple[int, int]:
    """撤销之前追加的期初结余行。"""
    removed_d = removed_p = 0
    for key, amt_col, tag in (
        ("delivery_df", "发货金额", _OPENING_TAG_DELIVERY),
        ("payment_df", "回款金额", _OPENING_TAG_PAYMENT),
    ):
        df = st.session_state.get(key)
        if df is None or df.empty or "来源" not in df.columns:
            continue
        mask = df["来源"].astype(str) == tag
        n = int(mask.sum())
        if n:
            st.session_state[key] = df.loc[~mask].reset_index(drop=True)
            if key == "delivery_df":
                removed_d = n
            else:
                removed_p = n
    if removed_d or removed_p:
        bump_data_version()
    return removed_d, removed_p


def render_opening_balance_import() -> None:
    """在数据导入页渲染"期初结余"导入区。"""
    st.caption(
        "上传上一期（如去年末）导出的结余表，它会以"
        "「期初发货 / 期初回款」的形式追加到当期数据，"
        "参与回款时效、利润提成与完成额度等各项计算。"
    )

    applied_n = _count_opening_rows()
    c_up, c_date = st.columns([2, 1], gap="large")
    with c_up:
        uploaded = st.file_uploader(
            "期初结余 Excel", type=["xls", "xlsx"], key="opening_uploader",
        )
    with c_date:
        base_date = st.date_input(
            "期初基准日期",
            value=datetime(datetime.now().year, 1, 1),
            key="opening_base_date",
            help="导入行若无发货/回款日期，以此日期作为合成记录的日期。",
        )

    fingerprint = (
        (uploaded.name, uploaded.size) if uploaded is not None else None
    )
    last_fp = st.session_state.get("_opening_uploader_last_fp")
    should_process = uploaded is not None and fingerprint != last_fp

    if should_process:
        st.session_state["_opening_uploader_last_fp"] = fingerprint
        suffix = Path(uploaded.name).suffix
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(uploaded.read())
            tmp_path = tmp.name
        try:
            opening_df = _parse_opening_excel(tmp_path)
            st.session_state["opening_balance_df"] = opening_df
            st.success(f"已识别 {len(opening_df)} 条期初结余，点击下方按钮应用到当期数据。")
        except Exception as e:
            st.error(f"解析失败：{e}")
        finally:
            try:
                import os
                os.unlink(tmp_path)
            except OSError:
                pass

    pending = st.session_state.get("opening_balance_df")
    if isinstance(pending, pd.DataFrame) and not pending.empty:
        with st.expander(
            f"查看已识别的期初结余（{len(pending)} 条）", expanded=False
        ):
            st.dataframe(pending, width="stretch", hide_index=True)

    b1, b2 = st.columns(2)
    with b1:
        disabled = (
            not isinstance(pending, pd.DataFrame) or pending.empty
        )
        if st.button(
            "应用到当期数据",
            type="primary",
            use_container_width=True,
            disabled=disabled,
            key="opening_apply_btn",
        ):
            nd, np_ = _apply_opening_to_session(
                pending, pd.Timestamp(base_date),
            )
            st.success(
                f"已追加：期初发货 {nd} 行；期初回款 {np_} 行。"
                "结余页将自动刷新。"
            )
            st.session_state.pop("opening_balance_df", None)
            st.session_state["_opening_uploader_last_fp"] = None
    with b2:
        if st.button(
            f"撤销已追加的期初（{applied_n} 行）",
            use_container_width=True,
            disabled=applied_n == 0,
            key="opening_revert_btn",
        ):
            rd, rp = _remove_opening_from_session()
            st.success(f"已撤销：发货 {rd} 行；回款 {rp} 行。")


def render_balance(username: str):
    st.html(page_intro(
        "结余合同",
        "聚焦所有未结清合同，适合核对期初结余、应收余额以及预收回款的承接情况。",
        eyebrow="Balance Ledger",
    ))

    delivery_df = st.session_state.get("delivery_df")
    payment_df = st.session_state.get("payment_df")
    if (delivery_df is None or delivery_df.empty) and (
        payment_df is None or payment_df.empty
    ):
        st.warning("请先在数据导入页上传交货或回款数据。")
        return

    applied_n = _count_opening_rows()
    if applied_n:
        st.info(
            f"当前已合并 {applied_n} 行期初结余（可在"
            "「数据导入 → 期初结余」中撤销）。"
        )

    bal = _build_balance_df_cached()

    with st.container(border=True):
        st.subheader("未结清合同清单")

        if bal.empty:
            st.html(empty_state("当前所有合同都已结清", "本期没有剩余应收或预收合同，可以直接导出留档。"))
            return

        total_n = len(bal)
        total_receivable = float((bal["累计发货额"] - bal["累计回款额"]).clip(lower=0).sum())
        total_prepaid = float((bal["累计回款额"] - bal["累计发货额"]).clip(lower=0).sum())
        unique_sp = bal["销售员"].astype(str).nunique()
        m1, m2, m3, m4 = st.columns(4, gap="medium")
        with m1:
            st.metric("未结清合同", f"{total_n}")
        with m2:
            st.metric("涉及销售员", f"{unique_sp}")
        with m3:
            st.metric("应收合计", fmt_money(total_receivable))
        with m4:
            st.metric("预收合计", fmt_money(total_prepaid))

        c1, c2 = st.columns([2, 1], gap="medium")
        with c1:
            kw = st.text_input(
                "搜索合同编号 / 销售员 / 开票单位",
                value="", placeholder="输入关键字过滤表格",
                key="balance_search_kw",
            )
        with c2:
            status_opts = sorted(bal["状态"].unique().tolist())
            picked = st.multiselect(
                "按状态筛选",
                options=status_opts,
                default=[],
                key="balance_status_filter",
            )

        view = bal.copy()
        if kw and kw.strip():
            k = kw.strip().lower()
            mask = (
                view["合同编号"].astype(str).str.lower().str.contains(k, na=False)
                | view["销售员"].astype(str).str.lower().str.contains(k, na=False)
                | view["开票单位"].astype(str).str.lower().str.contains(k, na=False)
                | view["主合同编号"].astype(str).str.lower().str.contains(k, na=False)
            )
            view = view[mask]
        if picked:
            view = view[view["状态"].isin(picked)]

        st.caption(f"显示 {len(view)} / {total_n} 条")

        st.dataframe(
            view,
            width="stretch",
            hide_index=True,
            height=min(480, 45 + len(view) * 36),
            column_config={
                "累计发货额": st.column_config.NumberColumn(format="%.2f"),
                "累计回款额": st.column_config.NumberColumn(format="%.2f"),
                "结余金额": st.column_config.NumberColumn(format="%.2f"),
                "最近发货日期": st.column_config.DatetimeColumn(format="YYYY-MM-DD"),
                "最近回款日期": st.column_config.DatetimeColumn(format="YYYY-MM-DD"),
            },
        )

        # ── 销售员分组视图（与"回款时效提成"风格一致） ──
        st.html(section_title("按销售员分组查看"))
        for sp, sub in view.groupby("销售员"):
            n = len(sub)
            bal_sum = float(sub["结余金额"].sum())
            dept = str(sub["销售部门"].iloc[0] or "")
            header = f"{sp}"
            if dept:
                header += f"　·　{dept}"
            header += f"　·　{n} 条　·　结余 {fmt_money(bal_sum)}"
            with st.expander(header, expanded=False):
                st.dataframe(
                    sub.drop(columns=["销售员", "销售部门"]),
                    width="stretch",
                    hide_index=True,
                    height=min(320, 45 + n * 36),
                    column_config={
                        "累计发货额": st.column_config.NumberColumn(format="%.2f"),
                        "累计回款额": st.column_config.NumberColumn(format="%.2f"),
                        "结余金额": st.column_config.NumberColumn(format="%.2f"),
                        "最近发货日期": st.column_config.DatetimeColumn(format="YYYY-MM-DD"),
                        "最近回款日期": st.column_config.DatetimeColumn(format="YYYY-MM-DD"),
                    },
                )

        st.html(section_title("导出"))
        render_df_download_buttons(
            view,
            base_filename="结余合同",
            sheet_name="结余合同",
            key_prefix="balance_dl",
        )
