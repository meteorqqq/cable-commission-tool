"""利润提成页"""

import os
import tempfile
from pathlib import Path

import streamlit as st
import pandas as pd

from engine.calculator import (
    calc_profit_commission, ContractPricing,
    load_contract_pricing_excel_with_meta,
    DEFAULT_PROFIT_BASE_RATE, DEFAULT_PROFIT_K_MAX,
)
from web._cache import (
    get_invoice_units_by_contract, get_invoice_units_by_contract_sp,
    get_project_list, get_main_contract_map,
    bump_calc_version, bump_price_version, price_version, session_cache,
)
from web._download import render_df_download_buttons
from web._table import dataframe_with_fulltext_panel
from web._ui import (
    fmt_money, split_units, truncate_units_text,
    meta_row, section_title, kpi_row, unit_pills, page_intro,
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


@session_cache("saved_prices_map", scope="price")
def _saved_prices_map(username: str) -> dict:
    return {p["project_id"]: p for p in load_contract_prices(username)}


_PRICE_COLS = ["主合同编号", "合同编号", "开票单位", "指导价", "合同价", "成本价",
               "系数来源", "录价状态"]


def _build_price_df(username: str) -> pd.DataFrame:
    """按主合同分组的价格录入表。

    - 主合同未录价时，分项合同可单独录价；
    - 主合同录价后，分项沿用主合同系数（列"系数来源"标记"主合同"）；
    - 从未录价的行「指导价/合同价/成本价」显示为 0，状态列标"未录价"，等待用户输入。
      不再用发货总额作默认值。
    """
    projects = get_project_list()
    saved_prices = _saved_prices_map(username)
    inv_map = get_invoice_units_by_contract()
    main_map = get_main_contract_map()

    # 行集合 = 发货/回款里出现的合同号 ∪ 主合同号 ∪ 已保存价格的合同号
    # 最后一项保证：从 Excel 导入但当前交货/回款里不存在的合同号，也能出现在价格表里
    pids: set[str] = {str(p) for p in projects}
    pids.update(str(v) for v in main_map.values())
    pids.update(str(k) for k in saved_prices.keys())

    # 主合同 -> [分项列表]，用于主合同行从分项聚合开票单位
    main_to_subs: dict[str, list[str]] = {}
    for sub, main in main_map.items():
        main_to_subs.setdefault(str(main), []).append(str(sub))

    def _lookup_invoice(pid: str, main_pid: str) -> str:
        inv = inv_map.get(pid, "")
        if inv:
            return inv
        # 主合同本身没有发货/回款时，把所有分项的开票单位聚合起来
        parts: set[str] = set()
        for sub in main_to_subs.get(main_pid, []):
            val = inv_map.get(sub, "")
            if val:
                for piece in str(val).split(" / "):
                    piece = piece.strip()
                    if piece:
                        parts.add(piece)
        # 分项行兜底：用主合同的开票单位
        if not parts and pid != main_pid:
            val = inv_map.get(main_pid, "")
            if val:
                parts.update(p.strip() for p in str(val).split(" / ") if p.strip())
        return " / ".join(sorted(parts))

    def _has_value(sp) -> bool:
        if not sp:
            return False
        return (
            (sp.get("guide_price") or 0) != 0
            or (sp.get("contract_price") or 0) != 0
            or (sp.get("cost_price") or 0) != 0
        )

    def _price_source(pid: str) -> str:
        """某个合同号在计算时会用哪份价格？以"是否有非零价格"判定。"""
        main_pid = main_map.get(pid, pid)
        main_ok = _has_value(saved_prices.get(main_pid))
        self_ok = _has_value(saved_prices.get(pid))
        if main_ok and main_pid != pid:
            return "主合同"
        if self_ok:
            return "自身"
        if main_ok:
            return "自身"
        return "未录价"

    rows = []
    for pid in pids:
        main_pid = main_map.get(pid, pid)
        inv = _lookup_invoice(pid, main_pid)
        sp = saved_prices.get(pid)
        gp = float(sp["guide_price"]) if sp else 0.0
        cp = float(sp["contract_price"]) if sp else 0.0
        cos = float(sp["cost_price"]) if sp else 0.0

        status_self = "已录价" if _has_value(sp) else "未录价"
        src = _price_source(pid)

        rows.append({
            "主合同编号": main_pid,
            "合同编号": pid,
            "开票单位": inv,
            "指导价": gp,
            "合同价": cp,
            "成本价": cos,
            "系数来源": src,
            "录价状态": status_self,
        })

    if not rows:
        return pd.DataFrame(columns=_PRICE_COLS)
    out = pd.DataFrame(rows)
    for c in ("指导价", "合同价", "成本价"):
        out[c] = pd.to_numeric(out[c], errors="coerce")

    # 排序：主合同优先，主合同 == 分项的行排第一（作为"主合同本身"），其余分项紧随
    out["_is_main"] = (out["主合同编号"] == out["合同编号"]).astype(int)
    out["_k_main"] = out["主合同编号"].apply(lambda x: (1 if str(x) == "其他" else 0, str(x)))
    out["_k_sub"] = out["合同编号"].apply(lambda x: (1 if str(x) == "其他" else 0, str(x)))
    out = (
        out.sort_values(["_k_main", "_is_main", "_k_sub"], ascending=[True, False, True])
        .drop(columns=["_is_main", "_k_main", "_k_sub"])
        .reset_index(drop=True)
    )
    return out[_PRICE_COLS]


def _render_price_groups(price_df: pd.DataFrame) -> None:
    """按主合同编号聚类展示价格/分项合同明细（只读）。

    - 主合同行排在本组最前；
    - 每组 expander 头部展示：开票单位、分项数、已录价比例；
    - 大量主合同时支持搜索与"仅含分项"开关；
    - 编辑仍在上方的"合同价格表"里做；这里纯查看，避免控件状态冲突。
    """
    if price_df is None or price_df.empty:
        return

    df = price_df.copy()
    df["主合同编号"] = df["主合同编号"].astype(str)
    df["合同编号"] = df["合同编号"].astype(str)

    with st.container(border=True):
        st.subheader("按主合同分组查看")
        st.caption(
            "每个主合同展开后显示其下所有分项合同。如需修改价格，请回到上方"
            "「合同价格表」编辑（此处为只读视图）。"
        )

        fc1, fc2, fc3 = st.columns([2, 1, 1], gap="medium")
        with fc1:
            kw = st.text_input(
                "搜索主合同编号或开票单位", value="", placeholder="输入关键字过滤主合同",
                key="price_group_search",
            )
        with fc2:
            only_with_subs = st.checkbox(
                "隐藏独立合同", value=False, key="price_group_only_subs",
                help="勾选后只显示主合同+分项的层级组；独立合同列表会被隐藏。",
            )
        with fc3:
            expand_all = st.checkbox(
                "默认展开全部", value=False, key="price_group_expand_all",
                help="展开后如果组太多会比较长；建议搭配搜索使用。",
            )

        # 按主合同聚合
        grouped: dict[str, pd.DataFrame] = {}
        for main_pid, grp in df.groupby("主合同编号"):
            grouped[str(main_pid)] = grp

        # 区分"真·主合同组"（组内除主合同自身外还有其他分项）和"独立合同"
        real_main_pids: list[str] = []
        standalone_pids: list[str] = []
        for mpid, g in grouped.items():
            has_sub = (g["合同编号"] != g["主合同编号"]).any()
            if has_sub:
                real_main_pids.append(mpid)
            else:
                standalone_pids.append(mpid)

        # "其他" 放最后，其余按字母序
        def _order_key(mpid: str):
            return (1 if mpid == "其他" else 0, mpid)

        real_main_pids.sort(key=_order_key)
        standalone_pids.sort(key=_order_key)

        def _match(mpid: str) -> bool:
            sub = grouped[mpid]
            k = kw.strip().lower() if kw else ""
            if not k:
                return True
            if k in mpid.lower():
                return True
            for inv in sub["开票单位"].astype(str).fillna(""):
                if k in inv.lower():
                    return True
            for p in sub["合同编号"].astype(str):
                if k in p.lower():
                    return True
            return False

        real_main_pids = [m for m in real_main_pids if _match(m)]
        if not only_with_subs:
            standalone_pids = [m for m in standalone_pids if _match(m)]
        else:
            standalone_pids = []

        total_mains = len(real_main_pids)
        total_subs = sum(
            int((grouped[m]["合同编号"] != grouped[m]["主合同编号"]).sum())
            for m in real_main_pids
        )
        st.caption(
            f"主合同层级 {total_mains} 组（含 {total_subs} 个分项）；"
            f"独立合同 {len(standalone_pids)} 条。"
        )

        if not real_main_pids and not standalone_pids:
            st.info("没有匹配的合同。")
            return

        MAX_GROUPS = 200

        def _render_main_group(mpid: str) -> None:
            sub = grouped[mpid].copy()
            sub["_is_main"] = (sub["主合同编号"] == sub["合同编号"]).astype(int)
            sub = sub.sort_values(
                ["_is_main", "合同编号"], ascending=[False, True]
            ).drop(columns=["_is_main"]).reset_index(drop=True)

            n_total = len(sub)
            n_subs = int((sub["合同编号"] != sub["主合同编号"]).sum())
            n_priced = int((sub["录价状态"] == "已录价").sum())

            unit_set: list[str] = []
            seen: set[str] = set()
            for v in sub["开票单位"].astype(str):
                for u in split_units(v):
                    if u not in seen:
                        seen.add(u)
                        unit_set.append(u)
            inv_short = truncate_units_text(" / ".join(unit_set), max_n=1, max_chars=22)

            title_segs = [str(mpid)]
            if inv_short:
                title_segs.append(inv_short)
            title_segs.append(f"分项 {n_subs}")
            title_segs.append(f"录价 {n_priced}/{n_total}")
            header = "　·　".join(title_segs)

            with st.expander(header, expanded=expand_all):
                st.html(meta_row([
                    ("主合同编号", str(mpid)),
                    ("分项数", f"{n_subs}"),
                    ("录价状态", f"{n_priced} / {n_total}"),
                ]))

                if unit_set:
                    st.html(section_title(f"开票单位（{len(unit_set)}）"))
                    st.html(unit_pills(unit_set))

                main_row = sub[sub["合同编号"] == mpid]
                if not main_row.empty:
                    r0 = main_row.iloc[0]
                    gp = float(pd.to_numeric(r0.get("指导价", 0), errors="coerce") or 0)
                    cp = float(pd.to_numeric(r0.get("合同价", 0), errors="coerce") or 0)
                    cos = float(pd.to_numeric(r0.get("成本价", 0), errors="coerce") or 0)
                    if gp or cp or cos:
                        st.html(section_title("主合同价格"))
                        st.html(kpi_row([
                            ("指导价", fmt_money(gp), False),
                            ("合同价", fmt_money(cp), False),
                            ("成本价", fmt_money(cos), False),
                        ]))

                st.html(section_title("合同明细"))
                show_cols = [c for c in [
                    "合同编号", "指导价", "合同价", "成本价",
                    "系数来源", "录价状态",
                ] if c in sub.columns]
                st.dataframe(
                    sub[show_cols],
                    width="stretch",
                    hide_index=True,
                    height=min(320, 45 + n_total * 36),
                    column_config={
                        "指导价": st.column_config.NumberColumn(format="%.2f"),
                        "合同价": st.column_config.NumberColumn(format="%.2f"),
                        "成本价": st.column_config.NumberColumn(format="%.2f"),
                        "系数来源": st.column_config.TextColumn("系数来源"),
                        "录价状态": st.column_config.TextColumn("录价状态"),
                    },
                )

        if real_main_pids:
            st.html(section_title(f"主合同 · 分项层级（{len(real_main_pids)} 组）"))
            truncated = len(real_main_pids) > MAX_GROUPS
            for mpid in real_main_pids[:MAX_GROUPS]:
                _render_main_group(mpid)
            if truncated:
                st.warning(
                    f"结果较多，仅展示前 {MAX_GROUPS} 个主合同。请用上方搜索框缩小范围。"
                )

        if standalone_pids:
            st.html(section_title(f"独立合同（{len(standalone_pids)} 条，无主/分关系）"))
            # 独立合同用一张扁平表展示即可，不用 expander，避免堆一大堆折叠框。
            rows_df = pd.concat(
                [grouped[m] for m in standalone_pids[:max(MAX_GROUPS * 5, 1000)]],
                ignore_index=True,
            )
            show_cols = [c for c in [
                "合同编号", "开票单位", "指导价", "合同价", "成本价",
                "系数来源", "录价状态",
            ] if c in rows_df.columns]
            st.dataframe(
                rows_df[show_cols],
                width="stretch",
                hide_index=True,
                height=min(480, 45 + len(rows_df) * 36),
                column_config={
                    "开票单位": st.column_config.TextColumn("开票单位"),
                    "指导价": st.column_config.NumberColumn(format="%.2f"),
                    "合同价": st.column_config.NumberColumn(format="%.2f"),
                    "成本价": st.column_config.NumberColumn(format="%.2f"),
                    "系数来源": st.column_config.TextColumn("系数来源"),
                    "录价状态": st.column_config.TextColumn("录价状态"),
                },
            )
            if len(standalone_pids) > max(MAX_GROUPS * 5, 1000):
                st.warning(
                    f"独立合同过多，仅展示前 {max(MAX_GROUPS * 5, 1000)} 条。请使用搜索缩小范围。"
                )


def render_profit(username: str):
    st.html(page_intro(
        "利润提成",
        "根据合同价格、指导价与成本价生成利润提成率，并按合同回款额自动计算提成。",
        eyebrow="Profit Engine",
    ))

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
            # 用 (文件名, 大小) 作为指纹，避免 rerun 后重复处理同一个文件
            # 进入死循环（file_uploader 会在后续每次 rerun 时继续持有该文件）。
            fingerprint = (uploaded.name, uploaded.size) if uploaded is not None else None
            last_fp = st.session_state.get("_pricing_uploader_last_fp")
            should_process = uploaded is not None and fingerprint != last_fp
            if should_process:
                st.session_state["_pricing_uploader_last_fp"] = fingerprint
                suffix = Path(uploaded.name).suffix
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                    tmp.write(uploaded.read())
                    tmp_path = tmp.name
                try:
                    pricing_map, meta = load_contract_pricing_excel_with_meta(tmp_path)
                    imported_rows = [
                        {
                            "project_id": pid,
                            "guide_price": p.guide_price,
                            "contract_price": p.contract_price,
                            "cost_price": p.cost_price,
                        }
                        for pid, p in pricing_map.items()
                    ]
                    save_contract_prices(username, imported_rows)
                    bump_price_version()

                    matched = meta.get("matched", {})
                    raw_rows = meta.get("raw_rows", 0)
                    total = meta.get("total", 0)
                    dup_pids = meta.get("duplicate_pids", {}) or {}
                    split_rows = meta.get("split_rows", 0)

                    st.success(f"已导入 {total} 条合同价格")

                    with st.expander("导入详情", expanded=False):
                        split_note = (
                            f"；其中 {split_rows} 行包含多个合同号已自动拆分"
                            if split_rows else ""
                        )
                        st.caption(
                            f"Excel 合同号条目 {raw_rows}；去重后 {total}{split_note}。"
                        )
                        st.caption(
                            f"识别列　合同号：`{matched.get('pid_col') or '未识别'}`"
                            f"　指导价：`{matched.get('guide_col') or '未识别'}`"
                            f"　合同价：`{matched.get('contract_col') or '未识别'}`"
                            f"　成本价：`{matched.get('cost_col') or '未识别'}`"
                        )
                        if dup_pids:
                            st.caption(f"重复合同号 {len(dup_pids)} 个（取最后一行）")
                            st.code(
                                "\n".join(f"{pid} × {n}" for pid, n in
                                          sorted(dup_pids.items(), key=lambda x: -x[1])[:50]),
                                language="text",
                            )

                    if total == 0:
                        st.warning(
                            "未识别到任何合同号 —— 请检查「合同编号」列是否存在。"
                            f"当前表头为：\n\n`{meta.get('columns', [])}`"
                        )
                    # 导入完成后不再调用 st.rerun()；价格表缓存已由 bump_price_version 失效，
                    # 页面随后的渲染会自然读取新数据。强制 rerun 反而会把上面的诊断信息抹掉。
                except Exception as e:
                    st.error(f"导入失败: {e}")
                finally:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass

    with st.container(border=True):
        st.subheader("合同价格表")
        price_df = _build_price_df(username)

        total_n = len(price_df)
        unpriced_n = int((price_df["录价状态"] == "未录价").sum()) if total_n else 0
        priced_n = total_n - unpriced_n
        main_contracts_n = int((price_df["主合同编号"] == price_df["合同编号"]).sum()) if total_n else 0
        st.caption(
            f"共 {total_n} 条（其中主合同 {main_contracts_n} 条，已录价 {priced_n} 条，"
            f"未录价 {unpriced_n} 条）。主合同录入价格后，其下属分项合同默认沿用主合同系数。"
        )

        # ── 诊断区：帮助快速定位"导入了但表里看不到价格"的问题 ──
        saved_prices = _saved_prices_map(username)
        saved_ids = set(saved_prices.keys())
        table_ids = set(price_df["合同编号"].astype(str).tolist()) if total_n else set()
        missing_ids = sorted(saved_ids - table_ids)
        with st.expander(
            f"📋 诊断：数据库已保存价格 {len(saved_prices)} 条",
            expanded=False,
        ):
            if not saved_prices:
                st.warning("数据库里还没有任何已保存的合同价格。请先导入或手动录入。")
            else:
                st.write("**已录入价格样例（前 10 条）：**")
                sample = pd.DataFrame([
                    {
                        "合同编号": pid,
                        "指导价": sp.get("guide_price"),
                        "合同价": sp.get("contract_price"),
                        "成本价": sp.get("cost_price"),
                        "在上方表里": "是" if pid in table_ids else "否",
                    }
                    for pid, sp in list(saved_prices.items())[:10]
                ])
                st.dataframe(sample, width="stretch", hide_index=True)

                if missing_ids:
                    st.warning(
                        f"⚠️ 有 {len(missing_ids)} 条价格保存在库里，但合同号不在当前"
                        "「发货/回款」数据中，所以没出现在上方表格里。"
                        "这些价格会在下一次你导入了包含这些合同号的发货/回款数据后显示；"
                        "但它们目前已生效，计算利润提成时仍会被使用。"
                    )
                    with st.container():
                        st.caption("前 20 个未出现的合同号：")
                        st.code("\n".join(missing_ids[:20]), language="text")
                else:
                    st.success("所有已保存的合同号都已在上方表格中展示。")

        fc1, fc2, fc3 = st.columns([2, 1, 1], gap="medium")
        with fc1:
            search_kw = st.text_input(
                "搜索合同编号、主合同或开票单位", value="", placeholder="输入关键字过滤表格",
                key="price_search_kw",
            )
        with fc2:
            fill_filter = st.selectbox(
                "价格填写状态",
                options=["全部", "已录价", "未录价", "成本价未填"],
                index=0, key="price_filter_fill",
            )
        with fc3:
            scope_filter = st.selectbox(
                "范围",
                options=["全部", "仅主合同", "仅分项合同"],
                index=0, key="price_filter_scope",
            )

        view_df = price_df
        if search_kw and search_kw.strip():
            kw = search_kw.strip()
            mask = (
                view_df["合同编号"].astype(str).str.contains(kw, case=False, na=False)
                | view_df["主合同编号"].astype(str).str.contains(kw, case=False, na=False)
                | view_df["开票单位"].astype(str).str.contains(kw, case=False, na=False)
            )
            view_df = view_df[mask]
        if fill_filter != "全部":
            gp = pd.to_numeric(view_df["指导价"], errors="coerce").fillna(0)
            cp = pd.to_numeric(view_df["合同价"], errors="coerce").fillna(0)
            cos = pd.to_numeric(view_df["成本价"], errors="coerce").fillna(0)
            if fill_filter == "已录价":
                view_df = view_df[(gp > 0) | (cp > 0) | (cos > 0)]
            elif fill_filter == "未录价":
                view_df = view_df[(gp == 0) & (cp == 0) & (cos == 0)]
            elif fill_filter == "成本价未填":
                view_df = view_df[cos == 0]
        if scope_filter == "仅主合同":
            view_df = view_df[view_df["主合同编号"] == view_df["合同编号"]]
        elif scope_filter == "仅分项合同":
            view_df = view_df[view_df["主合同编号"] != view_df["合同编号"]]

        st.caption(f"显示 {len(view_df)} / {len(price_df)} 条；编辑后点击下方按钮保存。")

        # 关键：key 随 price_version 变化 —— 每次导入 Excel / 保存价格表后，
        # data_editor 会被视作全新控件，清空之前缓存的"编辑状态"，避免把旧的 0
        # 当作用户编辑覆盖回刚导入的价格。
        editor_baseline = view_df.reset_index(drop=True)
        edited_prices = st.data_editor(
            editor_baseline,
            width="stretch",
            key=f"price_editor_v{price_version()}",
            disabled=["主合同编号", "合同编号", "开票单位", "系数来源", "录价状态"],
            height=340,
            column_config={
                "主合同编号": st.column_config.TextColumn(
                    "主合同编号",
                    help="来自交货/回款明细的「主合同编号」列；主合同 == 合同编号 时即为主合同自身。",
                ),
                "合同编号": st.column_config.TextColumn("合同编号"),
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
                "系数来源": st.column_config.TextColumn(
                    "系数来源",
                    help="计算利润提成时实际使用的是哪份价格："
                         "主合同 / 自身 / 未录入。",
                ),
                "录价状态": st.column_config.TextColumn(
                    "录价状态",
                    help="本合同行是否已录入价格（不考虑主合同沿用）。",
                ),
            },
        )

        def _merge_edits_into_full(full_df: pd.DataFrame,
                                   edited_subset: pd.DataFrame,
                                   baseline_subset: pd.DataFrame) -> pd.DataFrame:
            """把"真正被用户改动"的行合并回完整价格表。

            之前的实现会把整个 editor 返回值无脑覆盖到 full_df，
            遇到 Streamlit 控件状态残留时，会错误地把刚导入的非零价格冲成 0。
            这里改成对比 baseline（本次渲染输入）与 edited 的差异，
            只把真正变化的单元格覆盖回去。
            """
            if edited_subset is None or edited_subset.empty:
                return full_df
            merged = full_df.set_index("合同编号").copy()
            ed = edited_subset.set_index("合同编号")
            base_src = (
                baseline_subset
                if isinstance(baseline_subset, pd.DataFrame) and not baseline_subset.empty
                else edited_subset
            )
            base = base_src.set_index("合同编号")
            price_cols = ("指导价", "合同价", "成本价")
            for pid in ed.index:
                if pid not in merged.index:
                    continue
                for col in price_cols:
                    if col not in ed.columns:
                        continue
                    new_val = pd.to_numeric(ed.loc[pid, col], errors="coerce")
                    old_val = (
                        pd.to_numeric(base.loc[pid, col], errors="coerce")
                        if pid in base.index and col in base.columns
                        else None
                    )
                    # 与基线一致（或都为 NaN）→ 认定无编辑，保留 full_df 原值
                    if old_val is not None and (
                        (pd.isna(new_val) and pd.isna(old_val))
                        or (pd.notna(new_val) and pd.notna(old_val)
                            and abs(float(new_val) - float(old_val)) < 1e-9)
                    ):
                        continue
                    merged.loc[pid, col] = 0.0 if pd.isna(new_val) else float(new_val)
            return merged.reset_index()

        c1, c2 = st.columns(2)
        with c1:
            if st.button("保存价格表", use_container_width=True):
                merged = _merge_edits_into_full(price_df, edited_prices, editor_baseline)
                rows = []
                for _, r in merged.iterrows():
                    gp = pd.to_numeric(r["指导价"], errors="coerce")
                    cp = pd.to_numeric(r["合同价"], errors="coerce")
                    cos = pd.to_numeric(r["成本价"], errors="coerce")
                    gp_v = float(0 if pd.isna(gp) else gp)
                    cp_v = float(0 if pd.isna(cp) else cp)
                    cos_v = float(0 if pd.isna(cos) else cos)
                    # 仅保存：原本已录价，或者本次用户将任一价格改成非 0。
                    # 否则大量未录价的 0 行会被写入 DB，导致下次计算时被当成"已录价"。
                    already_priced = str(r.get("录价状态", "")) == "已录价"
                    has_value = gp_v != 0 or cp_v != 0 or cos_v != 0
                    if not (already_priced or has_value):
                        continue
                    rows.append({
                        "project_id": r["合同编号"],
                        "guide_price": gp_v,
                        "contract_price": cp_v,
                        "cost_price": cos_v,
                    })
                save_contract_prices(username, rows)
                bump_price_version()
                st.success(f"已保存 {len(rows)} 条合同价格")
        with c2:
            if st.button("计算利润提成", type="primary", use_container_width=True):
                merged = _merge_edits_into_full(price_df, edited_prices, editor_baseline)
                prices = {}
                # 判定某合同"真的录过价"的标准：
                #  - 三项价格（指导/合同/成本）至少一项 ≠ 0
                # 只看是否存在 DB 记录不靠谱，因为历史上可能把 0 行写进了库。
                # 如此未录价合同在计算端会落到"系数来源=未录入"。
                for _, r in merged.iterrows():
                    pid = r["合同编号"]
                    gp = pd.to_numeric(r["指导价"], errors="coerce")
                    cp = pd.to_numeric(r["合同价"], errors="coerce")
                    cos = pd.to_numeric(r["成本价"], errors="coerce")
                    gp_v = float(0 if pd.isna(gp) else gp)
                    cp_v = float(0 if pd.isna(cp) else cp)
                    cos_v = float(0 if pd.isna(cos) else cos)
                    if gp_v == 0 and cp_v == 0 and cos_v == 0:
                        continue
                    prices[pid] = ContractPricing(
                        project_id=pid,
                        guide_price=gp_v,
                        contract_price=cp_v,
                        cost_price=cos_v,
                    )
                try:
                    main_map = get_main_contract_map()
                    result = calc_profit_commission(
                        delivery_df, payment_df, prices,
                        base_rate_pct=base_rate, k_max=k_max,
                        main_contract_map=main_map,
                    )
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

        # 主合同编号若与自身相同（独立合同，没有真实父合同），展示为空白。
        if "主合同编号" in display_df.columns and "合同编号" in display_df.columns:
            same = display_df["主合同编号"].astype(str) == display_df["合同编号"].astype(str)
            display_df.loc[same, "主合同编号"] = ""

        with st.container(border=True):
            st.subheader("计算结果")

            m1, m2, m3, m4 = st.columns(4, gap="medium")
            total_n = len(display_df)
            commissioned_n = int((display_df.get("利润提成金额", pd.Series(dtype=float)).fillna(0).abs() > 0.005).sum())
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

            fc1, fc2 = st.columns([1, 1], gap="medium")
            with fc1:
                if "状态" in display_df.columns:
                    status_options = [
                        "已完成", "部分回款", "未回款", "未发货", "未发货（已收款）",
                    ]
                    status_options = [s for s in status_options
                                       if s in set(display_df["状态"].unique())]
                    picked = st.multiselect(
                        "按状态筛选",
                        options=status_options,
                        default=[],
                        key="profit_filter_status",
                    )
                    if picked:
                        display_df = display_df[display_df["状态"].isin(picked)]
            with fc2:
                if "系数来源" in display_df.columns:
                    # 始终列出全部选项（主合同 / 自身 / 未录入），
                    # 即便当前结果里没有某一类，也方便对比切换。
                    src_options = ["主合同", "自身", "未录入"]
                    picked_src = st.multiselect(
                        "按系数来源筛选",
                        options=src_options,
                        default=[],
                        key="profit_filter_src",
                    )
                    if picked_src:
                        display_df = display_df[display_df["系数来源"].isin(picked_src)]

            dataframe_with_fulltext_panel(
                display_df,
                key="profit_result_selectable",
                fulltext_cols=["开票单位"],
                height=420,
                column_config={
                    "开票单位": st.column_config.TextColumn(
                        "开票单位", help="保留全称；显示区域不足时可点击单元格查看完整文本。"
                    ),
                    "主合同编号": st.column_config.TextColumn(
                        "主合同编号", help="若分项合同归属某主合同，此列显示主合同号；否则与合同编号相同。",
                    ),
                    "系数来源": st.column_config.TextColumn(
                        "系数来源",
                        help="本行 K 系数的来源：主合同 / 自身 / 未录入。",
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
            render_df_download_buttons(
                display_df,
                base_filename="利润提成",
                sheet_name="利润提成",
                key_prefix="profit_result",
            )

    _render_price_groups(price_df)
