"""
电缆售货员提成计算引擎

三部分独立计算，规则均可自定义:
  1. 完成额度提成 (表四)
  2. 利润提成 (表五)
  3. 回款时效提成 (表六)
"""

from __future__ import annotations

import re

import pandas as pd
import numpy as np
from dataclasses import dataclass, field


_DEPT_CODE_RE = re.compile(r"^[\s]*\d[\d]*\s*\|?\s*")
_DEPT_PREFIX_RE = re.compile(r"^[\s]*\d[\d]*\s*[-－—_]\s*")


def contract_status(d_amt: float, p_amt: float) -> str:
    """按发货额 / 回款额判定合同状态。

    口径与各页面保持一致：
    - 未发货 / 未发货（已收款） / 未回款 / 部分回款 / 已完成
    """
    try:
        d = float(d_amt or 0)
        p = float(p_amt or 0)
    except (TypeError, ValueError):
        return "未发货"
    if d <= 0 and p > 0:
        return "未发货（已收款）"
    if d <= 0:
        return "未发货"
    if p <= 0:
        return "未回款"
    if p + 1e-2 >= d:
        return "已完成"
    return "部分回款"


def clean_dept_name(value) -> str:
    """去掉销售部门字段中的编号前缀，保留中文名称。

    例如:
        "020201|02-国网事业部" -> "国网事业部"
        "010801|01-渠道事业部" -> "渠道事业部"
        "020201" / "" / NaN     -> ""
    """
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    s = str(value).strip()
    if not s or s.lower() in ("nan", "none"):
        return ""
    if "|" in s:
        s = s.split("|", 1)[1].strip()
    s = _DEPT_PREFIX_RE.sub("", s).strip()
    return s


def _normalize_dept_column(df: pd.DataFrame) -> pd.DataFrame:
    if "销售部门" in df.columns:
        df["销售部门"] = df["销售部门"].map(clean_dept_name)
    return df


def format_date_columns(
    df: pd.DataFrame | None,
    cols: list[str] | None = None,
) -> pd.DataFrame:
    """展示前把 datetime / date 列格式化为 'YYYY-MM-DD' 字符串(NaT->空)。

    若 cols 为 None，则自动识别所有 datetime 类型列。返回新副本。
    """
    if df is None or df.empty:
        return df if df is not None else pd.DataFrame()

    out = df.copy()
    if cols is None:
        cols = [c for c in out.columns if pd.api.types.is_datetime64_any_dtype(out[c])]
    for c in cols:
        if c not in out.columns:
            continue
        s = out[c]
        if not pd.api.types.is_datetime64_any_dtype(s):
            s = pd.to_datetime(s, errors="coerce")
        out[c] = s.dt.strftime("%Y-%m-%d").where(s.notna(), "")
    return out


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
        elif "主合同编号" in col or "主合同号" in col:
            col_map[col] = "主合同编号"
        elif "合同编号" in col or "合同号" in col:
            col_map[col] = "合同编号"
        elif any(k in col for k in (
            "订货单位", "购货单位", "购方", "购买方", "客户名称", "客户单位",
            "采购方", "买方", "客户",
        )):
            col_map[col] = "订货单位"
        elif any(k in col for k in ("开票单位", "销方", "销售方")):
            col_map[col] = "开票单位"
    df = df.rename(columns=col_map)

    if "合同编号" not in df.columns:
        df["合同编号"] = ""
    df["合同编号"] = df["合同编号"].astype("string").str.strip()
    df.loc[df["合同编号"].isin(["", "nan", "None"]) | df["合同编号"].isna(),
           "合同编号"] = "其他"

    # 主合同编号：缺失时回落到合同编号自身（自己即主合同）
    if "主合同编号" not in df.columns:
        df["主合同编号"] = df["合同编号"]
    else:
        df["主合同编号"] = df["主合同编号"].astype("string").str.strip()
        empty_main = df["主合同编号"].isin(["", "nan", "None"]) | df["主合同编号"].isna()
        df.loc[empty_main, "主合同编号"] = df.loc[empty_main, "合同编号"]

    if "销售员" in df.columns:
        df = df[df["销售员"].notna() & (df["销售员"].astype(str).str.strip() != "")]

    df["发货金额"] = pd.to_numeric(df["发货金额"], errors="coerce").fillna(0)
    df["发货日期"] = pd.to_datetime(df["发货日期"], errors="coerce")
    df = _normalize_dept_column(df)
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
        elif "主合同编号" in col or "主合同号" in col:
            col_map[col] = "主合同编号"
        elif "合同编号" in col or "合同号" in col:
            col_map[col] = "合同编号"
        elif "销售部门" in col:
            col_map[col] = "销售部门"
        elif "销售员编号" in col:
            col_map[col] = "销售员编号"
        elif "销售员" in col and "编号" not in col:
            col_map[col] = "销售员"
        elif any(k in col for k in ("开票单位", "销方", "销售方")):
            col_map[col] = "开票单位"
        elif any(k in col for k in (
            "订货单位", "购货单位", "购方", "购买方", "客户名称", "客户单位",
            "采购方", "买方", "客户",
        )):
            col_map[col] = "订货单位"
        elif "核销金额" in col or "核销" in col:
            col_map[col] = "核销金额"
    df = df.rename(columns=col_map)

    if "合同编号" not in df.columns:
        df["合同编号"] = ""
    df["合同编号"] = df["合同编号"].astype("string").str.strip()
    df.loc[df["合同编号"].isin(["", "nan", "None"]) | df["合同编号"].isna(),
           "合同编号"] = "其他"

    if "主合同编号" not in df.columns:
        df["主合同编号"] = df["合同编号"]
    else:
        df["主合同编号"] = df["主合同编号"].astype("string").str.strip()
        empty_main = df["主合同编号"].isin(["", "nan", "None"]) | df["主合同编号"].isna()
        df.loc[empty_main, "主合同编号"] = df.loc[empty_main, "合同编号"]

    if "销售员" in df.columns:
        df = df[df["销售员"].notna() & (df["销售员"].astype(str).str.strip() != "")]

    df["回款金额"] = pd.to_numeric(df["回款金额"], errors="coerce").fillna(0)
    if "核销金额" in df.columns:
        df["核销金额"] = pd.to_numeric(df["核销金额"], errors="coerce").fillna(0)
    df["回款日期"] = pd.to_datetime(df["回款日期"], errors="coerce")
    df = _normalize_dept_column(df)
    return df.reset_index(drop=True)


def load_contract_pricing_excel(path: str) -> dict[str, "ContractPricing"]:
    """读取合同价格 Excel。

    支持的列别名（模糊匹配，忽略空白和"（元）"等后缀）：
      - 合同编号 / 合同号 / 项目号
      - 指导价 / 基准价 / 目标价 / 标准价 / 参考价
      - 合同价 / 合同总价 / 合同金额 / 销售价 / 成交价
      - 成本价 / 成本 / 制造成本 / 采购价
    """
    header_row = _detect_header_row(path)
    df = pd.read_excel(path, header=header_row)
    df.columns = [str(c).strip() for c in df.columns]

    def _norm(s: str) -> str:
        return (
            str(s).replace(" ", "").replace("（元）", "").replace("(元)", "")
            .replace("（", "").replace("）", "")
        )

    pid_col = guide_col = contract_col = cost_col = None
    for col in df.columns:
        cl = _norm(col)
        if pid_col is None and ("合同编号" in cl or "合同号" in cl or "项目号" in cl):
            pid_col = col
        elif guide_col is None and any(k in cl for k in (
            "指导价", "基准价", "目标价", "标准价", "参考价"
        )):
            guide_col = col
        elif contract_col is None and any(k in cl for k in (
            "合同总价", "合同金额", "合同价", "销售价", "成交价"
        )):
            contract_col = col
        elif cost_col is None and any(k in cl for k in (
            "成本价", "制造成本", "采购价", "成本"
        )):
            cost_col = col

    if pid_col is None:
        raise ValueError(
            "未找到「合同编号/合同号/项目号」列。实际表头为："
            f"{list(df.columns)}"
        )
    if guide_col is None and contract_col is None and cost_col is None:
        raise ValueError(
            "未识别到任何价格列（指导价 / 合同价 / 成本价）。实际表头为："
            f"{list(df.columns)}"
        )

    result: dict[str, ContractPricing] = {}
    # 一格里可能写了多个合同号（如 "RYDB260420007、RYDB260420008"），支持
    # 中/英文顿号、逗号、斜杠、分号、竖线、换行、多空格等常见分隔符。
    _split_re = re.compile(r"[、,，/;；|\n\r\t]+| {2,}")

    def _split_pids(raw: object) -> list[str]:
        if raw is None or pd.isna(raw):
            return []
        parts = [p.strip() for p in _split_re.split(str(raw))]
        return [p for p in parts if p and p.lower() not in ("nan", "none")]

    for _, row in df.iterrows():
        pids = _split_pids(row[pid_col])
        if not pids:
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

        gp_v = _safe(guide_col)
        cp_v = _safe(contract_col)
        cos_v = _safe(cost_col)
        for pid in pids:
            result[pid] = ContractPricing(
                project_id=pid,
                guide_price=gp_v,
                contract_price=cp_v,
                cost_price=cos_v,
            )
    return result


def load_contract_pricing_excel_with_meta(path: str) -> tuple[dict[str, "ContractPricing"], dict]:
    """与 :func:`load_contract_pricing_excel` 相同，但额外返回诊断信息。

    诊断 dict 含：
      - columns: 原始识别出的表头列表
      - matched: {pid_col, guide_col, contract_col, cost_col} 匹配到的真实列名
      - raw_rows: Excel 总行数（不含空合同号）
      - total: 去重后合同号数（== len(result)）
      - priced: 三项价格中至少一项 > 0 的条目数
      - zero_pids: 三项价格全部为 0 的合同号列表
      - duplicate_pids: {合同号: 出现次数} —— 仅列出次数 > 1 的
    """
    header_row = _detect_header_row(path)
    df = pd.read_excel(path, header=header_row)
    df.columns = [str(c).strip() for c in df.columns]

    result = load_contract_pricing_excel(path)
    # 只要合同号存在，就视为"已录入一条价格记录"，无论数值为正/负/0。
    priced = len(result)
    zero_pids: list[str] = []

    # 复用上面的识别逻辑来抓出命中列名（无侵入的再跑一次）
    def _norm(s: str) -> str:
        return (
            str(s).replace(" ", "").replace("（元）", "").replace("(元)", "")
            .replace("（", "").replace("）", "")
        )
    matched: dict[str, str | None] = {
        "pid_col": None, "guide_col": None, "contract_col": None, "cost_col": None,
    }
    for col in df.columns:
        cl = _norm(col)
        if matched["pid_col"] is None and ("合同编号" in cl or "合同号" in cl or "项目号" in cl):
            matched["pid_col"] = col
        elif matched["guide_col"] is None and any(k in cl for k in (
            "指导价", "基准价", "目标价", "标准价", "参考价"
        )):
            matched["guide_col"] = col
        elif matched["contract_col"] is None and any(k in cl for k in (
            "合同总价", "合同金额", "合同价", "销售价", "成交价"
        )):
            matched["contract_col"] = col
        elif matched["cost_col"] is None and any(k in cl for k in (
            "成本价", "制造成本", "采购价", "成本"
        )):
            matched["cost_col"] = col

    raw_rows = 0
    dup_counts: dict[str, int] = {}
    split_rows = 0  # 发生"一格多号"拆分的 Excel 行数
    pid_col = matched.get("pid_col")
    _split_re = re.compile(r"[、,，/;；|\n\r\t]+| {2,}")
    if pid_col is not None and pid_col in df.columns:
        for v in df[pid_col]:
            if pd.isna(v):
                continue
            parts = [p.strip() for p in _split_re.split(str(v))]
            parts = [p for p in parts if p and p.lower() not in ("nan", "none")]
            if not parts:
                continue
            if len(parts) > 1:
                split_rows += 1
            for pid in parts:
                raw_rows += 1
                dup_counts[pid] = dup_counts.get(pid, 0) + 1
    duplicate_pids = {pid: n for pid, n in dup_counts.items() if n > 1}

    meta = {
        "columns": list(df.columns),
        "matched": matched,
        "raw_rows": raw_rows,
        "total": len(result),
        "priced": priced,
        "zero_pids": zero_pids,
        "duplicate_pids": duplicate_pids,
        "split_rows": split_rows,
    }
    return result, meta


def extract_project_list(delivery_df: pd.DataFrame | None,
                         payment_df: pd.DataFrame | None) -> list[str]:
    projects = set()
    if delivery_df is not None and "合同编号" in delivery_df.columns:
        projects.update(delivery_df["合同编号"].dropna().astype(str).unique())
    if payment_df is not None and "合同编号" in payment_df.columns:
        projects.update(payment_df["合同编号"].dropna().astype(str).unique())
    return sorted(projects)


def build_main_contract_map(
    delivery_df: pd.DataFrame | None,
    payment_df: pd.DataFrame | None,
) -> dict[str, str]:
    """构建 分项合同 → 主合同 的映射。

    规则：
    - 任一数据源（交货 / 回款）有 (合同编号, 主合同编号) 行时建立映射；
    - 同一分项出现多个不同的主合同时，取出现次数最多者（通常只会是一个）；
    - 主合同编号缺失 / 为空时视为自身即主合同，不会产生多余映射；
    - 返回值一定覆盖所有出现过的合同编号，若无主合同则 main == self。
    """
    pair_counts: dict[tuple[str, str], int] = {}

    def _collect(df: pd.DataFrame | None):
        if df is None or df.empty:
            return
        if "合同编号" not in df.columns:
            return
        if "主合同编号" in df.columns:
            pairs = (
                df[["合同编号", "主合同编号"]]
                .astype("string")
                .fillna("")
            )
        else:
            pairs = pd.DataFrame({
                "合同编号": df["合同编号"].astype("string").fillna(""),
                "主合同编号": df["合同编号"].astype("string").fillna(""),
            })
        for _, row in pairs.iterrows():
            sub = str(row["合同编号"]).strip()
            main = str(row["主合同编号"]).strip()
            if not sub or sub.lower() in ("nan", "none"):
                continue
            if not main or main.lower() in ("nan", "none"):
                main = sub
            pair_counts[(sub, main)] = pair_counts.get((sub, main), 0) + 1

    _collect(delivery_df)
    _collect(payment_df)

    by_sub: dict[str, dict[str, int]] = {}
    for (sub, main), cnt in pair_counts.items():
        by_sub.setdefault(sub, {})[main] = by_sub.setdefault(sub, {}).get(main, 0) + cnt

    out: dict[str, str] = {}
    for sub, counts in by_sub.items():
        main = max(counts.items(), key=lambda kv: (kv[1], kv[0] != sub))[0]
        out[sub] = main if main else sub
    return out


def invoice_units_by_contract(
    delivery_df: pd.DataFrame | None,
    payment_df: pd.DataFrame | None,
) -> dict[str, str]:
    """按合同编号汇总开票单位（多个用 ' / ' 连接）；无开票单位时回落到订货单位。"""
    bucket: dict[str, set[str]] = {}

    def _collect(df: pd.DataFrame | None, col: str):
        if df is None or df.empty or "合同编号" not in df.columns or col not in df.columns:
            return
        for pid, grp in df.groupby(df["合同编号"].astype(str)):
            for v in grp[col].dropna().unique():
                s = str(v).strip()
                if s and s.lower() not in ("nan", "none"):
                    bucket.setdefault(pid, set()).add(s)

    for df in (delivery_df, payment_df):
        _collect(df, "开票单位")

    fallback: dict[str, set[str]] = {}
    for df in (delivery_df, payment_df):
        if df is None or df.empty or "合同编号" not in df.columns or "订货单位" not in df.columns:
            continue
        for pid, grp in df.groupby(df["合同编号"].astype(str)):
            for v in grp["订货单位"].dropna().unique():
                s = str(v).strip()
                if s and s.lower() not in ("nan", "none"):
                    fallback.setdefault(pid, set()).add(s)

    out: dict[str, str] = {}
    pids = set(bucket) | set(fallback)
    for pid in pids:
        names = bucket.get(pid) or fallback.get(pid) or set()
        if names:
            out[pid] = " / ".join(sorted(names))
    return out


def invoice_units_by_contract_sp(
    delivery_df: pd.DataFrame | None,
    payment_df: pd.DataFrame | None,
) -> dict[tuple[str, str], str]:
    """按 (合同编号, 销售员) 汇总开票单位；无开票单位时回落到订货单位。

    对于 "其他" 这种兜底合同号，可以按销售员拆分显示，避免把所有人的客户都串到一起。
    """
    bucket: dict[tuple[str, str], set[str]] = {}

    def _collect(df: pd.DataFrame | None, col: str, target: dict[tuple[str, str], set[str]]):
        if df is None or df.empty:
            return
        if "合同编号" not in df.columns or "销售员" not in df.columns or col not in df.columns:
            return
        keys = list(zip(df["合同编号"].astype(str), df["销售员"].astype(str)))
        for (pid, sp), v in zip(keys, df[col]):
            if pd.isna(v):
                continue
            s = str(v).strip()
            if not s or s.lower() in ("nan", "none"):
                continue
            target.setdefault((pid, sp), set()).add(s)

    for df in (delivery_df, payment_df):
        _collect(df, "开票单位", bucket)

    fallback: dict[tuple[str, str], set[str]] = {}
    for df in (delivery_df, payment_df):
        _collect(df, "订货单位", fallback)

    out: dict[tuple[str, str], str] = {}
    keys = set(bucket) | set(fallback)
    for k in keys:
        names = bucket.get(k) or fallback.get(k) or set()
        if names:
            out[k] = " / ".join(sorted(names))
    return out


def build_contract_overview(delivery_df: pd.DataFrame | None,
                            payment_df: pd.DataFrame | None) -> pd.DataFrame:
    """按合同编号汇总：交货/回款行数与金额，覆盖仅出现在单侧的合同号。"""
    pids: set[str] = set()
    if delivery_df is not None and not delivery_df.empty and "合同编号" in delivery_df.columns:
        pids.update(delivery_df["合同编号"].dropna().astype(str).unique())
    if payment_df is not None and not payment_df.empty and "合同编号" in payment_df.columns:
        pids.update(payment_df["合同编号"].dropna().astype(str).unique())
    rows = []
    for pid in sorted(pids):
        d_lines = d_amt = 0
        if delivery_df is not None and not delivery_df.empty and "合同编号" in delivery_df.columns:
            m = delivery_df["合同编号"].astype(str) == pid
            d_lines = int(m.sum())
            if "发货金额" in delivery_df.columns:
                d_amt = float(delivery_df.loc[m, "发货金额"].sum())
        p_lines = p_amt = 0
        if payment_df is not None and not payment_df.empty and "合同编号" in payment_df.columns:
            m = payment_df["合同编号"].astype(str) == pid
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
            "合同编号": pid,
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
    profit_df: pd.DataFrame | None = None,
    timeliness_df: pd.DataFrame | None = None,
) -> dict:
    """返回某销售员的所有合同明细与汇总。

    若提供 profit_df / timeliness_df（来自利润提成 / 回款时效提成的计算结果），
    每个合同会额外附带利润提成额、时效提成额及时效提成明细。

    结构:
        {
            "销售员": str, "销售部门": str,
            "总发货额": float, "总回款额": float, "未回款额": float,
            "总利润提成": float, "总时效提成": float,
            "合同数": int,
            "合同列表": [
                {
                    "合同编号": str,   # "其他" 表示无合同号
                    "订货单位": list[str], "开票单位": list[str],
                    "发货明细": DataFrame, "回款明细": DataFrame,
                    "发货额": float, "回款额": float, "未回款额": float,
                    "状态": "已完成" | ... ,
                    "利润提成": float, "利润提成率": str, "利润分类": str,
                    "时效提成": float,
                    "时效提成明细": DataFrame(回款日期/匹配发货日期/回款周期(天)/时效提成比例/时效提成金额),
                }, ...
            ]
        }
    """
    dept_map = _build_salesperson_dept_map(delivery_df, payment_df)
    dept = dept_map.get(salesperson, "")

    profit_lookup: dict[str, dict] = {}
    if profit_df is not None and not profit_df.empty and "销售员" in profit_df.columns:
        sub = profit_df[profit_df["销售员"].astype(str) == salesperson]
        for _, r in sub.iterrows():
            pid = str(r.get("合同编号", "")).strip()
            if not pid:
                continue
            try:
                amt = float(r.get("利润提成金额", 0) or 0)
            except (TypeError, ValueError):
                amt = 0.0
            profit_lookup[pid] = {
                "利润提成": round(amt, 2),
                "利润提成率": str(r.get("利润提成率", "")),
                "利润分类": str(r.get("利润分类", "")),
            }

    tl_grouped: dict[str, pd.DataFrame] = {}
    tl_amount: dict[str, float] = {}
    if timeliness_df is not None and not timeliness_df.empty and "销售员" in timeliness_df.columns:
        sub = timeliness_df[timeliness_df["销售员"].astype(str) == salesperson]
        cols_pref = ["回款日期", "回款金额", "匹配发货日期", "回款周期(天)",
                     "时效提成比例", "时效提成金额"]
        for pid, grp in sub.groupby(sub["合同编号"].astype(str)):
            keep = [c for c in cols_pref if c in grp.columns]
            tl_grouped[pid] = grp[keep].reset_index(drop=True)
            tl_amount[pid] = round(
                float(pd.to_numeric(grp.get("时效提成金额", 0), errors="coerce").fillna(0).sum()),
                2,
            )

    def _empty(cols):
        return pd.DataFrame(columns=cols)

    del_rows = (
        delivery_df[delivery_df["销售员"].astype(str) == salesperson].copy()
        if delivery_df is not None and not delivery_df.empty and "销售员" in delivery_df.columns
        else _empty(["合同编号", "发货日期", "发货金额", "订货单位", "开票单位"])
    )
    pay_rows = (
        payment_df[payment_df["销售员"].astype(str) == salesperson].copy()
        if payment_df is not None and not payment_df.empty and "销售员" in payment_df.columns
        else _empty(["合同编号", "回款日期", "回款金额", "开票单位", "核销金额"])
    )

    if "发货日期" in del_rows.columns:
        del_rows["发货日期"] = pd.to_datetime(del_rows["发货日期"], errors="coerce")
    if "回款日期" in pay_rows.columns:
        pay_rows["回款日期"] = pd.to_datetime(pay_rows["回款日期"], errors="coerce")

    del_by_pid: dict[str, pd.DataFrame] = {}
    if not del_rows.empty and "合同编号" in del_rows.columns:
        for pid, grp in del_rows.groupby(del_rows["合同编号"].astype(str)):
            del_by_pid[pid] = grp
    pay_by_pid: dict[str, pd.DataFrame] = {}
    if not pay_rows.empty and "合同编号" in pay_rows.columns:
        for pid, grp in pay_rows.groupby(pay_rows["合同编号"].astype(str)):
            pay_by_pid[pid] = grp

    pids = set(del_by_pid) | set(pay_by_pid)

    def _order_key(pid: str):
        return (1 if pid == "其他" else 0, pid)

    empty_del = _empty(["发货日期", "发货金额", "订货单位", "开票单位"])
    empty_pay = _empty(["回款日期", "回款金额", "开票单位", "核销金额"])

    contracts = []
    total_del = total_pay = 0.0
    for pid in sorted(pids, key=_order_key):
        d = del_by_pid.get(pid, empty_del)
        p = pay_by_pid.get(pid, empty_pay)

        d_amt = float(d["发货金额"].sum()) if "发货金额" in d.columns else 0.0
        p_amt = float(p["回款金额"].sum()) if "回款金额" in p.columns else 0.0
        total_del += d_amt
        total_pay += p_amt

        status = contract_status(d_amt, p_amt)

        def _unique_nonempty(series: pd.Series) -> list[str]:
            return [str(x).strip() for x in series.dropna().unique() if str(x).strip()]

        invoice_units: set[str] = set()
        for src in (d, p):
            if "开票单位" in src.columns:
                invoice_units.update(_unique_nonempty(src["开票单位"]))

        customers: set[str] = set()
        for src in (d, p):
            if "订货单位" in src.columns:
                customers.update(_unique_nonempty(src["订货单位"]))
        if not customers and invoice_units:
            customers = set(invoice_units)

        def _fill_missing(df_in: pd.DataFrame, col: str, fallback: list[str]) -> pd.DataFrame:
            """若该列在 df 中存在但部分行为空，用 fallback 中的值补齐。"""
            if df_in.empty or not fallback:
                if not df_in.empty and col not in df_in.columns and fallback:
                    df_in = df_in.copy()
                    df_in[col] = " / ".join(fallback)
                return df_in
            df_in = df_in.copy()
            if col not in df_in.columns:
                df_in[col] = " / ".join(fallback)
                return df_in
            fill_value = " / ".join(fallback)
            s = df_in[col].astype("string").str.strip()
            mask = s.isin(["", "nan", "None"]) | s.isna()
            df_in.loc[mask, col] = fill_value
            return df_in

        cust_list = sorted(customers)
        inv_list = sorted(invoice_units)
        d = _fill_missing(d, "订货单位", cust_list)
        d = _fill_missing(d, "开票单位", inv_list)
        p = _fill_missing(p, "订货单位", cust_list)
        p = _fill_missing(p, "开票单位", inv_list)

        d_cols = [c for c in ["发货日期", "发货金额", "订货单位", "开票单位"] if c in d.columns]
        p_cols = [c for c in ["回款日期", "回款金额", "核销金额", "开票单位", "订货单位"]
                  if c in p.columns]

        d_show = d[d_cols].sort_values("发货日期") if "发货日期" in d_cols else d[d_cols]
        p_show = p[p_cols].sort_values("回款日期") if "回款日期" in p_cols else p[p_cols]

        prof = profit_lookup.get(pid, {})
        contracts.append({
            "合同编号": pid,
            "订货单位": sorted(customers),
            "开票单位": sorted(invoice_units),
            "发货明细": d_show.reset_index(drop=True),
            "回款明细": p_show.reset_index(drop=True),
            "发货额": round(d_amt, 2),
            "回款额": round(p_amt, 2),
            "未回款额": round(max(d_amt - p_amt, 0), 2),
            "状态": status,
            "利润提成": prof.get("利润提成", 0.0),
            "利润提成率": prof.get("利润提成率", ""),
            "利润分类": prof.get("利润分类", ""),
            "时效提成": tl_amount.get(pid, 0.0),
            "时效提成明细": tl_grouped.get(pid, pd.DataFrame()),
        })

    total_profit = round(sum(c["利润提成"] for c in contracts), 2)
    total_timeliness = round(sum(c["时效提成"] for c in contracts), 2)

    return {
        "销售员": salesperson,
        "销售部门": dept,
        "总发货额": round(total_del, 2),
        "总回款额": round(total_pay, 2),
        "未回款额": round(max(total_del - total_pay, 0), 2),
        "总利润提成": total_profit,
        "总时效提成": total_timeliness,
        "合同数": len(contracts),
        "合同列表": contracts,
    }


def build_salesperson_dept_map(
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


_build_salesperson_dept_map = build_salesperson_dept_map  # 兼容旧引用


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
                           k_max: float | None = None,
                           main_contract_map: dict[str, str] | None = None) -> pd.DataFrame:
    """按合同计算利润提成。

    ``main_contract_map``：分项合同 → 主合同的映射。若主合同已录入价格，则分项
    合同沿用主合同的 K 系数 / 提成率（"归属" 主合同口径）；否则再回落到分项
    自身的价格。为空或 None 时退化为旧逻辑（仅按合同号自身查价）。
    """
    if base_rate_pct is None:
        base_rate_pct = DEFAULT_PROFIT_BASE_RATE
    if k_max is None:
        k_max = DEFAULT_PROFIT_K_MAX
    if main_contract_map is None:
        main_contract_map = {}

    dept_map = _build_salesperson_dept_map(delivery_df, payment_df)

    pay_grp = (
        payment_df.groupby(["销售员", "合同编号"])["回款金额"].sum().reset_index()
        if payment_df is not None and not payment_df.empty
        else pd.DataFrame(columns=["销售员", "合同编号", "回款金额"])
    )
    pay_grp.columns = ["销售员", "合同编号", "合同回款额"]

    del_grp = (
        delivery_df.groupby(["销售员", "合同编号"])["发货金额"].sum().reset_index()
        if delivery_df is not None and not delivery_df.empty
        else pd.DataFrame(columns=["销售员", "合同编号", "发货金额"])
    )
    del_grp.columns = ["销售员", "合同编号", "合同发货额"]

    contracts = pd.merge(del_grp, pay_grp, on=["销售员", "合同编号"], how="outer").fillna(0)

    def _resolve_pricing(pid: str) -> tuple[ContractPricing | None, str, str]:
        """返回 (使用的定价, 主合同编号, 系数来源)。

        系数来源：
          - "自身"：用分项自己的价
          - "主合同"：用主合同的价（分项自身未录入）
          - "未录入"：均未录入
        """
        main_pid = str(main_contract_map.get(str(pid), pid))
        main_pricing = contract_prices.get(main_pid)
        self_pricing = contract_prices.get(str(pid))

        # 以"是否存在记录"为准，不再看具体数值；数值的合法性由 calc_profit_k_and_rate 处理。
        if main_pricing is not None and str(main_pid) != str(pid):
            return main_pricing, main_pid, "主合同"
        if self_pricing is not None:
            return self_pricing, main_pid, "自身"
        if main_pricing is not None:
            return main_pricing, main_pid, "自身"
        return None, main_pid, "未录入"

    rows = []
    for _, r in contracts.iterrows():
        pid = str(r["合同编号"])
        d_amt = float(r["合同发货额"])
        p_amt = float(r["合同回款额"])
        status = contract_status(d_amt, p_amt)

        pricing, main_pid, src = _resolve_pricing(pid)

        base = {
            "合同编号": pid,
            "主合同编号": main_pid,
            "销售员": r["销售员"],
            "销售部门": dept_map.get(r["销售员"], ""),
            "合同发货额": round(d_amt, 2),
            "合同回款额": round(p_amt, 2),
            "状态": status,
        }

        if pricing is not None:
            k, rate, cat = calc_profit_k_and_rate(
                pricing.guide_price, pricing.contract_price,
                pricing.cost_price, base_rate_pct, k_max)
            if src == "主合同":
                cat = f"{cat}（沿用主合同{main_pid}）"
            base.update({
                "指导价": pricing.guide_price,
                "合同价": pricing.contract_price,
                "成本价": pricing.cost_price,
                "K系数": round(k, 4),
                "利润提成率": f"{rate*100:.4f}%",
                "利润分类": cat,
                "系数来源": src,
                "利润提成金额": round(p_amt * rate, 2),
            })
        else:
            base.update({
                "指导价": np.nan,
                "合同价": np.nan,
                "成本价": np.nan,
                "K系数": np.nan,
                "利润提成率": "未设定价格",
                "利润分类": "未设定价格",
                "系数来源": "未录入",
                "利润提成金额": 0.0,
            })
        rows.append(base)

    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["_sort"] = df["合同编号"].apply(lambda x: (1 if str(x) == "其他" else 0, str(x)))
    df["_main_sort"] = df["主合同编号"].apply(lambda x: (1 if str(x) == "其他" else 0, str(x)))
    return (
        df.sort_values(["_main_sort", "_sort", "销售员"])
        .drop(columns=["_sort", "_main_sort"])
        .reset_index(drop=True)
    )


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
        ["销售员", "合同编号", "发货月份"]
    )["发货金额"].agg(["sum", "count"]).reset_index()
    del_summary.columns = ["销售员", "合同编号", "发货月份", "发货金额合计", "发货笔数"]
    del_summary["销售部门"] = del_summary["销售员"].map(dept_map).fillna("")
    del_summary["发货金额合计"] = del_summary["发货金额合计"].round(2)
    del_summary = del_summary[["合同编号", "销售员", "销售部门",
                               "发货月份", "发货笔数", "发货金额合计"]]

    # ── 回款明细 ──
    pay_detail = payment_df.copy()
    pay_detail["回款月份"] = pay_detail["回款日期"].dt.strftime("%Y-%m")
    pay_summary = pay_detail.groupby(
        ["销售员", "合同编号", "回款月份"]
    )["回款金额"].agg(["sum", "count"]).reset_index()
    pay_summary.columns = ["销售员", "合同编号", "回款月份", "回款金额合计", "回款笔数"]
    pay_summary["销售部门"] = pay_summary["销售员"].map(dept_map).fillna("")
    pay_summary["回款金额合计"] = pay_summary["回款金额合计"].round(2)
    pay_summary = pay_summary[["合同编号", "销售员", "销售部门",
                                "回款月份", "回款笔数", "回款金额合计"]]

    # ── FIFO 匹配（支持退款：按 LIFO 冲销已匹配历史）──
    timeliness_rows = []

    for (salesperson, project), grp_pay in payment_df.groupby(["销售员", "合同编号"]):
        grp_del = delivery_df[
            (delivery_df["销售员"] == salesperson) & (delivery_df["合同编号"] == project)
        ].sort_values("发货日期").copy()

        dept = dept_map.get(salesperson, "")

        if grp_del.empty:
            for _, pr in grp_pay.iterrows():
                timeliness_rows.append({
                    "合同编号": project, "销售员": salesperson, "销售部门": dept,
                    "回款金额": round(pr["回款金额"], 2), "回款日期": pr["回款日期"],
                    "匹配发货日期": None, "回款周期(天)": None,
                    "时效提成比例": "无匹配发货", "时效提成金额": 0,
                })
            continue

        # 只把"正发货"放入 FIFO 池；负发货（退货）不参与回款匹配
        del_remaining = [
            [d_date, float(d_amt)]
            for d_date, d_amt in grp_del[["发货日期", "发货金额"]].values.tolist()
            if float(d_amt) > 0.01
        ]
        del_idx = 0

        # 已匹配历史栈（供负回款 LIFO 冲销用）
        # 每项：[发货日, 剩余可冲销金额, rate]
        allocation_stack: list[list] = []

        for _, pr in grp_pay.sort_values("回款日期").iterrows():
            pay_amount = float(pr["回款金额"])
            pay_date = pr["回款日期"]

            # ── 正回款：FIFO 消耗正发货 ──
            if pay_amount > 0.01:
                while pay_amount > 0.01 and del_idx < len(del_remaining):
                    d_date, d_remain = del_remaining[del_idx]
                    matched = min(pay_amount, d_remain)

                    if pd.notna(pay_date) and pd.notna(d_date):
                        cycle = (pd.Timestamp(pay_date) - pd.Timestamp(d_date)).days
                    else:
                        cycle = None

                    rate = (
                        get_payment_timeliness_rate(cycle, tiers)
                        if cycle is not None else 0
                    )

                    timeliness_rows.append({
                        "合同编号": project, "销售员": salesperson, "销售部门": dept,
                        "回款金额": round(matched, 2), "回款日期": pay_date,
                        "匹配发货日期": d_date, "回款周期(天)": cycle,
                        "时效提成比例": f"{rate*100:.4f}%",
                        "时效提成金额": round(matched * rate, 2),
                    })
                    allocation_stack.append([d_date, matched, rate])

                    del_remaining[del_idx][1] -= matched
                    if del_remaining[del_idx][1] < 0.01:
                        del_idx += 1
                    pay_amount -= matched

                if pay_amount > 0.01:
                    timeliness_rows.append({
                        "合同编号": project, "销售员": salesperson, "销售部门": dept,
                        "回款金额": round(pay_amount, 2), "回款日期": pay_date,
                        "匹配发货日期": None, "回款周期(天)": None,
                        "时效提成比例": "超出发货额", "时效提成金额": 0,
                    })

            # ── 负回款（退款）：LIFO 冲销之前的匹配记录 ──
            elif pay_amount < -0.01:
                need = -pay_amount  # 待冲销正数
                while need > 0.01 and allocation_stack:
                    d_date, avail, rate = allocation_stack[-1]
                    take = min(need, avail)

                    if pd.notna(pay_date) and pd.notna(d_date):
                        cycle = (pd.Timestamp(pay_date) - pd.Timestamp(d_date)).days
                    else:
                        cycle = None

                    timeliness_rows.append({
                        "合同编号": project, "销售员": salesperson, "销售部门": dept,
                        "回款金额": round(-take, 2), "回款日期": pay_date,
                        "匹配发货日期": d_date, "回款周期(天)": cycle,
                        "时效提成比例": f"{rate*100:.4f}% (退款冲销)",
                        "时效提成金额": round(-take * rate, 2),
                    })

                    allocation_stack[-1][1] -= take
                    if allocation_stack[-1][1] < 0.01:
                        allocation_stack.pop()
                    need -= take

                if need > 0.01:
                    # 没有历史可冲销（先退款后收款等异常场景）
                    timeliness_rows.append({
                        "合同编号": project, "销售员": salesperson, "销售部门": dept,
                        "回款金额": round(-need, 2), "回款日期": pay_date,
                        "匹配发货日期": None, "回款周期(天)": None,
                        "时效提成比例": "无可冲销记录", "时效提成金额": 0,
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
