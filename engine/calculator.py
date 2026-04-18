"""
电缆售货员提成计算引擎

三部分独立计算，规则均可自定义:
  1. 完成额度提成 (表四)
  2. 利润提成 (表五)
  3. 回款时效提成 (表六)
"""

from __future__ import annotations

import pandas as pd
import numpy as np
from dataclasses import dataclass, field


# ── 默认规则 ─────────────────────────────────────────────────

DEFAULT_QUOTA_TIERS = [
    (80, 0.2),   # 完成比≥80% → 提成率0.2%
    (70, 0.15),  # 70%~80% → 0.15%
    (60, 0.1),   # 60%~70% → 0.1%
    (0,  0.0),   # <60% → 0
]

DEFAULT_PROFIT_BASE_RATE = 0.2    # 基础提成率 0.2%
DEFAULT_PROFIT_K_MAX = 1.2        # K系数上限

DEFAULT_PAYMENT_TIERS = [
    (30,  0.24),   # ≤30天  → 0.2%×1.2 = 0.24%
    (60,  0.2),    # 31~60天 → 0.2%
    (90,  0.15),   # 61~90天 → 0.15%
    (120, 0.1),    # 91~120天 → 0.1%
    (180, 0.05),   # 121~180天 → 0.05%
    (999, 0.0),    # >180天 → 0
]


# ── 通用计算函数 ─────────────────────────────────────────────

def get_quota_rate(completion_pct: float, tiers: list[tuple[float, float]]) -> float:
    """completion_pct: 百分比数字(如85表示85%), tiers: [(阈值%, 提成率%), ...]"""
    for threshold, rate_pct in sorted(tiers, key=lambda x: -x[0]):
        if completion_pct >= threshold:
            return rate_pct / 100
    return 0.0


def calc_profit_k_and_rate(guide_price: float, contract_price: float,
                            cost_price: float, base_rate_pct: float,
                            k_max: float):
    """返回 (k_factor, rate, category). base_rate_pct: 百分比数字如0.2"""
    base_rate = base_rate_pct / 100
    if guide_price <= 0:
        return 0.0, 0.0, "指导价无效"

    if contract_price >= guide_price:
        k = min(contract_price / guide_price, k_max)
        return k, base_rate * k, "合同总价≥指导价"
    elif contract_price >= cost_price:
        denom = guide_price - cost_price
        if denom <= 0:
            return 1.0, base_rate, "指导价=成本价(特殊)"
        k = 1.0 - (guide_price - contract_price) / denom
        return k, base_rate * k, "成本价≤合同总价<指导价"
    else:
        return 0.0, 0.0, "合同总价<成本价(无提成)"


def get_payment_timeliness_rate(cycle_days: int,
                                 tiers: list[tuple[int, float]]) -> float:
    """tiers: [(天数上限, 提成率%), ...]"""
    for max_days, rate_pct in sorted(tiers, key=lambda x: x[0]):
        if cycle_days <= max_days:
            return rate_pct / 100
    return 0.0


# ── 数据模型 ─────────────────────────────────────────────────

@dataclass
class ContractPricing:
    project_id: str
    guide_price: float = 0.0
    contract_price: float = 0.0
    cost_price: float = 0.0


# ── Excel 读取 ───────────────────────────────────────────────

def _detect_header_row(path: str) -> int:
    probe = pd.read_excel(path, header=None, nrows=10)
    for i in range(min(5, len(probe))):
        row_vals = [str(v).strip() for v in probe.iloc[i] if pd.notna(v)]
        if len(row_vals) >= 3 and not any(v.startswith("Unnamed") for v in row_vals):
            return i
    return 0


def load_delivery_excel(path: str) -> pd.DataFrame:
    header_row = _detect_header_row(path)
    df = pd.read_excel(path, header=header_row)
    df.columns = [str(c).strip() for c in df.columns]

    col_map = {}
    for col in df.columns:
        if "销售员编号" in col:
            col_map[col] = "销售员编号"
        elif "销售员" in col and "编号" not in col:
            col_map[col] = "销售员"
        elif "销售部门" in col:
            col_map[col] = "销售部门"
        elif "实际发货金额" in col or "发货金额" in col:
            col_map[col] = "发货金额"
        elif "实际发货日期" in col or "发货日期" in col:
            col_map[col] = "发货日期"
        elif "工程项目号" in col:
            col_map[col] = "工程项目号"
        elif "订货单位" in col:
            col_map[col] = "订货单位"
        elif "开票单位" in col:
            col_map[col] = "开票单位"
    df = df.rename(columns=col_map)

    if "工程项目号" not in df.columns:
        df["工程项目号"] = ""
    df["工程项目号"] = df["工程项目号"].astype("string").str.strip()
    df.loc[df["工程项目号"].isin(["", "nan", "None"]) | df["工程项目号"].isna(),
           "工程项目号"] = "其他"

    if "销售员" in df.columns:
        df = df[df["销售员"].notna() & (df["销售员"].astype(str).str.strip() != "")]

    df["发货金额"] = pd.to_numeric(df["发货金额"], errors="coerce").fillna(0)
    df["发货日期"] = pd.to_datetime(df["发货日期"], errors="coerce")
    return df.reset_index(drop=True)


def load_payment_excel(path: str) -> pd.DataFrame:
    header_row = _detect_header_row(path)
    df = pd.read_excel(path, header=header_row)
    df.columns = [str(c).strip() for c in df.columns]

    col_map = {}
    for col in df.columns:
        if "收款金额" in col or "回款金额" in col:
            col_map[col] = "回款金额"
        elif "回款日期" in col or "收款日期" in col:
            col_map[col] = "回款日期"
        elif "工程项目号" in col:
            col_map[col] = "工程项目号"
        elif "销售部门" in col:
            col_map[col] = "销售部门"
        elif "销售员编号" in col:
            col_map[col] = "销售员编号"
        elif "销售员" in col and "编号" not in col:
            col_map[col] = "销售员"
        elif "开票单位" in col:
            col_map[col] = "开票单位"
        elif "订货单位" in col:
            col_map[col] = "订货单位"
        elif "核销金额" in col:
            col_map[col] = "核销金额"
    df = df.rename(columns=col_map)

    if "工程项目号" not in df.columns:
        df["工程项目号"] = ""
    df["工程项目号"] = df["工程项目号"].astype("string").str.strip()
    df.loc[df["工程项目号"].isin(["", "nan", "None"]) | df["工程项目号"].isna(),
           "工程项目号"] = "其他"

    if "销售员" in df.columns:
        df = df[df["销售员"].notna() & (df["销售员"].astype(str).str.strip() != "")]

    df["回款金额"] = pd.to_numeric(df["回款金额"], errors="coerce").fillna(0)
    df["回款日期"] = pd.to_datetime(df["回款日期"], errors="coerce")
    return df.reset_index(drop=True)


def load_contract_pricing_excel(path: str) -> dict[str, "ContractPricing"]:
    header_row = _detect_header_row(path)
    df = pd.read_excel(path, header=header_row)
    df.columns = [str(c).strip() for c in df.columns]

    pid_col = guide_col = contract_col = cost_col = None
    for col in df.columns:
        cl = col.replace(" ", "")
        if "工程项目号" in cl or "合同号" in cl or "项目号" in cl or "合同编号" in cl:
            pid_col = col
        elif "指导价" in cl:
            guide_col = col
        elif "合同价" in cl or "合同总价" in cl:
            contract_col = col
        elif "成本价" in cl or "成本" in cl:
            cost_col = col

    if pid_col is None:
        raise ValueError("未找到「工程项目号/合同号」列")

    result: dict[str, ContractPricing] = {}
    for _, row in df.iterrows():
        pid = str(row[pid_col]).strip()
        if not pid or pid == "nan":
            continue

        def _safe(c):
            if c is None:
                return 0.0
            v = row.get(c)
            if pd.isna(v):
                return 0.0
            try:
                return float(v)
            except (ValueError, TypeError):
                return 0.0

        result[pid] = ContractPricing(
            project_id=pid,
            guide_price=_safe(guide_col),
            contract_price=_safe(contract_col),
            cost_price=_safe(cost_col),
        )
    return result


def extract_project_list(delivery_df: pd.DataFrame | None,
                         payment_df: pd.DataFrame | None) -> list[str]:
    projects = set()
    if delivery_df is not None and "工程项目号" in delivery_df.columns:
        projects.update(delivery_df["工程项目号"].dropna().astype(str).unique())
    if payment_df is not None and "工程项目号" in payment_df.columns:
        projects.update(payment_df["工程项目号"].dropna().astype(str).unique())
    return sorted(projects)


def build_contract_overview(delivery_df: pd.DataFrame | None,
                            payment_df: pd.DataFrame | None) -> pd.DataFrame:
    """按工程项目号汇总：交货/回款行数与金额，覆盖仅出现在单侧的合同号。"""
    pids: set[str] = set()
    if delivery_df is not None and not delivery_df.empty and "工程项目号" in delivery_df.columns:
        pids.update(delivery_df["工程项目号"].dropna().astype(str).unique())
    if payment_df is not None and not payment_df.empty and "工程项目号" in payment_df.columns:
        pids.update(payment_df["工程项目号"].dropna().astype(str).unique())
    rows = []
    for pid in sorted(pids):
        d_lines = d_amt = 0
        if delivery_df is not None and not delivery_df.empty and "工程项目号" in delivery_df.columns:
            m = delivery_df["工程项目号"].astype(str) == pid
            d_lines = int(m.sum())
            if "发货金额" in delivery_df.columns:
                d_amt = float(delivery_df.loc[m, "发货金额"].sum())
        p_lines = p_amt = 0
        if payment_df is not None and not payment_df.empty and "工程项目号" in payment_df.columns:
            m = payment_df["工程项目号"].astype(str) == pid
            p_lines = int(m.sum())
            if "回款金额" in payment_df.columns:
                p_amt = float(payment_df.loc[m, "回款金额"].sum())
        if d_lines > 0 and p_lines > 0:
            tag = "交货与回款均有"
        elif d_lines > 0:
            tag = "仅交货明细"
        else:
            tag = "仅回款明细"
        rows.append({
            "工程项目号": pid,
            "交货行数": d_lines,
            "交货金额合计": round(d_amt, 2),
            "回款行数": p_lines,
            "回款金额合计": round(p_amt, 2),
            "数据情况": tag,
        })
    return pd.DataFrame(rows)


def list_salespersons(delivery_df: pd.DataFrame | None,
                      payment_df: pd.DataFrame | None) -> list[str]:
    names: set[str] = set()
    for df in (delivery_df, payment_df):
        if df is None or df.empty or "销售员" not in df.columns:
            continue
        names.update(str(n).strip() for n in df["销售员"].dropna().unique())
    return sorted(n for n in names if n)


def build_salesperson_detail(
    salesperson: str,
    delivery_df: pd.DataFrame | None,
    payment_df: pd.DataFrame | None,
) -> dict:
    """返回某销售员的所有合同明细与汇总。

    结构:
        {
            "销售员": str,
            "销售部门": str,
            "总发货额": float, "总回款额": float, "未回款额": float,
            "合同数": int,
            "合同列表": [
                {
                    "工程项目号": str,   # "其他" 表示无合同号
                    "订货单位": list[str],
                    "开票单位": list[str],
                    "发货明细": DataFrame(发货日期/发货金额/订货单位/开票单位),
                    "回款明细": DataFrame(回款日期/回款金额/开票单位/核销金额),
                    "发货额": float, "回款额": float, "未回款额": float,
                    "状态": "已完成" | "未发货" | "部分回款" | "未回款",
                }, ...
            ]
        }
    """
    dept_map = _build_salesperson_dept_map(delivery_df, payment_df)
    dept = dept_map.get(salesperson, "")

    def _empty(cols):
        return pd.DataFrame(columns=cols)

    del_rows = (
        delivery_df[delivery_df["销售员"].astype(str) == salesperson].copy()
        if delivery_df is not None and not delivery_df.empty and "销售员" in delivery_df.columns
        else _empty(["工程项目号", "发货日期", "发货金额", "订货单位", "开票单位"])
    )
    pay_rows = (
        payment_df[payment_df["销售员"].astype(str) == salesperson].copy()
        if payment_df is not None and not payment_df.empty and "销售员" in payment_df.columns
        else _empty(["工程项目号", "回款日期", "回款金额", "开票单位", "核销金额"])
    )

    if "发货日期" in del_rows.columns:
        del_rows["发货日期"] = pd.to_datetime(del_rows["发货日期"], errors="coerce")
    if "回款日期" in pay_rows.columns:
        pay_rows["回款日期"] = pd.to_datetime(pay_rows["回款日期"], errors="coerce")

    pids = set(del_rows["工程项目号"].astype(str).unique()) if not del_rows.empty else set()
    pids.update(pay_rows["工程项目号"].astype(str).unique() if not pay_rows.empty else [])

    def _order_key(pid: str):
        return (1 if pid == "其他" else 0, pid)

    contracts = []
    total_del = total_pay = 0.0
    for pid in sorted(pids, key=_order_key):
        d = del_rows[del_rows["工程项目号"].astype(str) == pid] if not del_rows.empty else _empty(
            ["发货日期", "发货金额", "订货单位", "开票单位"])
        p = pay_rows[pay_rows["工程项目号"].astype(str) == pid] if not pay_rows.empty else _empty(
            ["回款日期", "回款金额", "开票单位", "核销金额"])

        d_amt = float(d["发货金额"].sum()) if "发货金额" in d.columns else 0.0
        p_amt = float(p["回款金额"].sum()) if "回款金额" in p.columns else 0.0
        total_del += d_amt
        total_pay += p_amt

        if d_amt == 0 and p_amt > 0:
            status = "未发货（已收款）"
        elif d_amt == 0:
            status = "未发货"
        elif p_amt <= 0:
            status = "未回款"
        elif p_amt + 1e-2 >= d_amt:
            status = "已完成"
        else:
            status = "部分回款"

        customers: set[str] = set()
        invoice_units: set[str] = set()
        for col_src, bag in [
            ("订货单位", customers),
            ("开票单位", invoice_units),
        ]:
            if col_src in d.columns:
                bag.update(str(x).strip() for x in d[col_src].dropna().unique() if str(x).strip())
            if col_src in p.columns:
                bag.update(str(x).strip() for x in p[col_src].dropna().unique() if str(x).strip())

        d_cols = [c for c in ["发货日期", "发货金额", "订货单位", "开票单位"] if c in d.columns]
        p_cols = [c for c in ["回款日期", "回款金额", "开票单位", "核销金额", "订货单位"]
                  if c in p.columns]

        d_show = d[d_cols].sort_values("发货日期") if "发货日期" in d_cols else d[d_cols]
        p_show = p[p_cols].sort_values("回款日期") if "回款日期" in p_cols else p[p_cols]

        contracts.append({
            "工程项目号": pid,
            "订货单位": sorted(customers),
            "开票单位": sorted(invoice_units),
            "发货明细": d_show.reset_index(drop=True),
            "回款明细": p_show.reset_index(drop=True),
            "发货额": round(d_amt, 2),
            "回款额": round(p_amt, 2),
            "未回款额": round(max(d_amt - p_amt, 0), 2),
            "状态": status,
        })

    return {
        "销售员": salesperson,
        "销售部门": dept,
        "总发货额": round(total_del, 2),
        "总回款额": round(total_pay, 2),
        "未回款额": round(max(total_del - total_pay, 0), 2),
        "合同数": len(contracts),
        "合同列表": contracts,
    }


def _build_salesperson_dept_map(
    delivery_df: pd.DataFrame | None,
    payment_df: pd.DataFrame | None = None,
) -> dict[str, str]:
    """从交货和回款双表合并 销售员→销售部门 映射；交货优先。"""
    mapping: dict[str, str] = {}
    for src in (delivery_df, payment_df):
        if src is None or src.empty:
            continue
        if "销售员" not in src.columns or "销售部门" not in src.columns:
            continue
        for _, row in src[["销售员", "销售部门"]].drop_duplicates().iterrows():
            sp, dept = row["销售员"], row["销售部门"]
            if pd.isna(sp) or pd.isna(dept):
                continue
            sp, dept = str(sp).strip(), str(dept).strip()
            if not sp or not dept:
                continue
            mapping.setdefault(sp, dept)
    return mapping


# ══════════════════════════════════════════════════════════════
# 第一部分: 完成额度提成
# ══════════════════════════════════════════════════════════════

def calc_quota_commission_by_dept(delivery_df: pd.DataFrame,
                                  payment_df: pd.DataFrame,
                                  dept_targets: dict[str, float],
                                  tiers: list[tuple[float, float]] | None = None) -> pd.DataFrame:
    """完成额度提成。

    - 部门完成比 = 部门全员发货额合计 / 部门目标额（同部门共享同一完成比）。
    - 完成额度提成 = 个人回款额 × 对应档位提成率。
    """
    if tiers is None:
        tiers = DEFAULT_QUOTA_TIERS

    dept_map = _build_salesperson_dept_map(delivery_df, payment_df)

    sp_del = delivery_df.groupby("销售员")["发货金额"].sum().reset_index()
    sp_del.columns = ["销售员", "个人发货额"]

    sp_pay = payment_df.groupby("销售员")["回款金额"].sum().reset_index()
    sp_pay.columns = ["销售员", "个人回款额"]

    sp = pd.merge(sp_del, sp_pay, on="销售员", how="outer").fillna(0)
    sp["销售部门"] = sp["销售员"].map(dept_map).fillna("")

    dept_total_del = sp.groupby("销售部门")["个人发货额"].sum()

    rows = []
    for _, r in sp.iterrows():
        dept = r["销售部门"]
        target_wan = dept_targets.get(dept, 0)
        target_yuan = target_wan * 10000
        actual_del = dept_total_del.get(dept, 0)

        ratio_pct = (actual_del / target_yuan * 100) if target_yuan > 0 else 0
        rate = get_quota_rate(ratio_pct, tiers)

        rows.append({
            "销售员": r["销售员"],
            "销售部门": dept,
            "个人发货额(元)": round(r["个人发货额"], 2),
            "个人回款额(元)": round(r["个人回款额"], 2),
            "部门实际发货(万元)": round(actual_del / 10000, 2),
            "部门目标额(万元)": round(target_wan, 2),
            "部门完成比": f"{ratio_pct:.1f}%",
            "提成比例": f"{rate*100:.2f}%",
            "完成额度提成(元)": round(r["个人回款额"] * rate, 2),
        })

    return pd.DataFrame(rows) if rows else pd.DataFrame()


# ══════════════════════════════════════════════════════════════
# 第二部分: 利润提成
# ══════════════════════════════════════════════════════════════

def calc_profit_commission(delivery_df: pd.DataFrame,
                           payment_df: pd.DataFrame,
                           contract_prices: dict[str, ContractPricing],
                           base_rate_pct: float | None = None,
                           k_max: float | None = None) -> pd.DataFrame:
    if base_rate_pct is None:
        base_rate_pct = DEFAULT_PROFIT_BASE_RATE
    if k_max is None:
        k_max = DEFAULT_PROFIT_K_MAX

    dept_map = _build_salesperson_dept_map(delivery_df, payment_df)

    contract_pay = payment_df.groupby(["销售员", "工程项目号"])["回款金额"].sum().reset_index()
    contract_pay.columns = ["销售员", "工程项目号", "合同回款额"]

    rows = []
    for _, r in contract_pay.iterrows():
        pid = r["工程项目号"]
        pricing = contract_prices.get(pid)

        if pricing and pricing.guide_price > 0:
            k, rate, cat = calc_profit_k_and_rate(
                pricing.guide_price, pricing.contract_price,
                pricing.cost_price, base_rate_pct, k_max)
            rows.append({
                "工程项目号": pid,
                "销售员": r["销售员"],
                "销售部门": dept_map.get(r["销售员"], ""),
                "合同回款额": round(r["合同回款额"], 2),
                "指导价": pricing.guide_price,
                "合同价": pricing.contract_price,
                "成本价": pricing.cost_price,
                "K系数": round(k, 4),
                "利润提成率": f"{rate*100:.4f}%",
                "利润分类": cat,
                "利润提成金额": round(r["合同回款额"] * rate, 2),
            })
        else:
            rows.append({
                "工程项目号": pid,
                "销售员": r["销售员"],
                "销售部门": dept_map.get(r["销售员"], ""),
                "合同回款额": round(r["合同回款额"], 2),
                "指导价": np.nan,
                "合同价": np.nan,
                "成本价": np.nan,
                "K系数": np.nan,
                "利润提成率": "未设定价格",
                "利润分类": "未设定价格",
                "利润提成金额": 0.0,
            })

    return pd.DataFrame(rows) if rows else pd.DataFrame()


# ══════════════════════════════════════════════════════════════
# 第三部分: 回款时效提成 + 出库/回款明细
# ══════════════════════════════════════════════════════════════

def calc_payment_timeliness(delivery_df: pd.DataFrame,
                            payment_df: pd.DataFrame,
                            tiers: list[tuple[int, float]] | None = None):
    if tiers is None:
        tiers = DEFAULT_PAYMENT_TIERS

    delivery_df = delivery_df.copy()
    payment_df = payment_df.copy()
    if "发货日期" in delivery_df.columns:
        delivery_df["发货日期"] = pd.to_datetime(delivery_df["发货日期"], errors="coerce")
    if "回款日期" in payment_df.columns:
        payment_df["回款日期"] = pd.to_datetime(payment_df["回款日期"], errors="coerce")

    dept_map = _build_salesperson_dept_map(delivery_df, payment_df)

    # ── 出库明细 ──
    del_detail = delivery_df.copy()
    del_detail["发货月份"] = del_detail["发货日期"].dt.strftime("%Y-%m")
    del_summary = del_detail.groupby(
        ["销售员", "工程项目号", "发货月份"]
    )["发货金额"].agg(["sum", "count"]).reset_index()
    del_summary.columns = ["销售员", "工程项目号", "发货月份", "发货金额合计", "发货笔数"]
    del_summary["销售部门"] = del_summary["销售员"].map(dept_map).fillna("")
    del_summary["发货金额合计"] = del_summary["发货金额合计"].round(2)
    del_summary = del_summary[["工程项目号", "销售员", "销售部门",
                               "发货月份", "发货笔数", "发货金额合计"]]

    # ── 回款明细 ──
    pay_detail = payment_df.copy()
    pay_detail["回款月份"] = pay_detail["回款日期"].dt.strftime("%Y-%m")
    pay_summary = pay_detail.groupby(
        ["销售员", "工程项目号", "回款月份"]
    )["回款金额"].agg(["sum", "count"]).reset_index()
    pay_summary.columns = ["销售员", "工程项目号", "回款月份", "回款金额合计", "回款笔数"]
    pay_summary["销售部门"] = pay_summary["销售员"].map(dept_map).fillna("")
    pay_summary["回款金额合计"] = pay_summary["回款金额合计"].round(2)
    pay_summary = pay_summary[["工程项目号", "销售员", "销售部门",
                                "回款月份", "回款笔数", "回款金额合计"]]

    # ── FIFO 匹配 ──
    timeliness_rows = []

    for (salesperson, project), grp_pay in payment_df.groupby(["销售员", "工程项目号"]):
        grp_del = delivery_df[
            (delivery_df["销售员"] == salesperson) & (delivery_df["工程项目号"] == project)
        ].sort_values("发货日期").copy()

        dept = dept_map.get(salesperson, "")

        if grp_del.empty:
            for _, pr in grp_pay.iterrows():
                timeliness_rows.append({
                    "工程项目号": project, "销售员": salesperson, "销售部门": dept,
                    "回款金额": round(pr["回款金额"], 2), "回款日期": pr["回款日期"],
                    "匹配发货日期": None, "回款周期(天)": None,
                    "时效提成比例": "无匹配发货", "时效提成金额": 0,
                })
            continue

        del_remaining = grp_del[["发货日期", "发货金额"]].values.tolist()
        del_idx = 0

        for _, pr in grp_pay.sort_values("回款日期").iterrows():
            pay_amount = pr["回款金额"]
            pay_date = pr["回款日期"]

            while pay_amount > 0.01 and del_idx < len(del_remaining):
                d_date, d_remain = del_remaining[del_idx]
                matched = min(pay_amount, d_remain)

                if pd.notna(pay_date) and pd.notna(d_date):
                    cycle = (pd.Timestamp(pay_date) - pd.Timestamp(d_date)).days
                else:
                    cycle = None

                rate = get_payment_timeliness_rate(cycle, tiers) if cycle is not None else 0

                timeliness_rows.append({
                    "工程项目号": project, "销售员": salesperson, "销售部门": dept,
                    "回款金额": round(matched, 2), "回款日期": pay_date,
                    "匹配发货日期": d_date, "回款周期(天)": cycle,
                    "时效提成比例": f"{rate*100:.4f}%",
                    "时效提成金额": round(matched * rate, 2),
                })

                del_remaining[del_idx][1] -= matched
                if del_remaining[del_idx][1] < 0.01:
                    del_idx += 1
                pay_amount -= matched

            if pay_amount > 0.01:
                timeliness_rows.append({
                    "工程项目号": project, "销售员": salesperson, "销售部门": dept,
                    "回款金额": round(pay_amount, 2), "回款日期": pay_date,
                    "匹配发货日期": None, "回款周期(天)": None,
                    "时效提成比例": "超出发货额", "时效提成金额": 0,
                })

    timeliness_df = pd.DataFrame(timeliness_rows) if timeliness_rows else pd.DataFrame()
    return timeliness_df, del_summary, pay_summary


# ══════════════════════════════════════════════════════════════
# 导出
# ══════════════════════════════════════════════════════════════

def export_results_to_excel(results: dict, output_path: str):
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        for sheet_name, df in results.items():
            if df is not None and not df.empty:
                out = df.copy()
                for col in out.columns:
                    if pd.api.types.is_datetime64_any_dtype(out[col]):
                        out[col] = out[col].dt.strftime("%Y-%m-%d")
                out.to_excel(writer, sheet_name=sheet_name, index=False)
