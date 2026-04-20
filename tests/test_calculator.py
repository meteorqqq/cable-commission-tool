"""engine/calculator.py 核心纯函数的单元测试。

只覆盖与业务规则最相关的函数，避免耦合 Streamlit / 数据库。
运行：``python -m pytest tests -q``
"""

from __future__ import annotations

import pandas as pd
import pytest

from engine.calculator import (
    clean_dept_name,
    contract_status,
    get_quota_rate,
    calc_profit_k_and_rate,
    get_payment_timeliness_rate,
    calc_quota_commission_by_dept,
    calc_profit_commission,
    calc_payment_timeliness,
    build_salesperson_dept_map,
    ContractPricing,
)


# ── clean_dept_name ────────────────────────────────────────────

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("020201|02-国网事业部", "国网事业部"),
        ("010801|01-渠道事业部", "渠道事业部"),
        ("020201", "020201"),  # 只有编号无中文，原样保留
        ("国网事业部", "国网事业部"),
        ("  02-国网事业部 ", "国网事业部"),
        ("", ""),
        (None, ""),
        (float("nan"), ""),
    ],
)
def test_clean_dept_name(raw, expected):
    assert clean_dept_name(raw) == expected


# ── contract_status ───────────────────────────────────────────

@pytest.mark.parametrize(
    "d, p, expected",
    [
        (100, 100, "已完成"),
        (100, 99.999, "已完成"),    # 1e-2 容差
        (100, 60, "部分回款"),
        (100, 0, "未回款"),
        (0, 0, "未发货"),
        (0, 50, "未发货（已收款）"),
    ],
)
def test_contract_status(d, p, expected):
    assert contract_status(d, p) == expected


# ── get_quota_rate ────────────────────────────────────────────

def test_get_quota_rate_default_tiers():
    tiers = [(80, 0.2), (70, 0.15), (60, 0.1), (0, 0.0)]
    assert get_quota_rate(85, tiers) == pytest.approx(0.002)   # 0.2% → 比例 0.002
    assert get_quota_rate(75, tiers) == pytest.approx(0.0015)
    assert get_quota_rate(60, tiers) == pytest.approx(0.001)
    assert get_quota_rate(50, tiers) == 0.0


# ── calc_profit_k_and_rate ────────────────────────────────────

def test_profit_contract_above_guide():
    k, rate, cat = calc_profit_k_and_rate(
        guide_price=100, contract_price=110, cost_price=80,
        base_rate_pct=0.2, k_max=1.2,
    )
    # k = min(110/100, 1.2) = 1.1
    assert k == pytest.approx(1.1)
    assert rate == pytest.approx(0.2 / 100 * 1.1)
    assert cat == "合同总价≥指导价"


def test_profit_contract_between_cost_and_guide():
    k, rate, cat = calc_profit_k_and_rate(
        guide_price=100, contract_price=90, cost_price=80,
        base_rate_pct=0.2, k_max=1.2,
    )
    # k = 1 - (100 - 90) / (100 - 80) = 0.5
    assert k == pytest.approx(0.5)
    assert rate == pytest.approx(0.2 / 100 * 0.5)
    assert cat == "成本价≤合同总价<指导价"


def test_profit_contract_below_cost():
    k, rate, cat = calc_profit_k_and_rate(
        guide_price=100, contract_price=70, cost_price=80,
        base_rate_pct=0.2, k_max=1.2,
    )
    assert k == 0
    assert rate == 0
    assert cat == "合同总价<成本价(无提成)"


def test_profit_guide_invalid():
    k, rate, cat = calc_profit_k_and_rate(
        guide_price=0, contract_price=90, cost_price=80,
        base_rate_pct=0.2, k_max=1.2,
    )
    assert k == 0 and rate == 0 and cat == "指导价无效"


# ── get_payment_timeliness_rate ────────────────────────────────

def test_timeliness_rate_tiers():
    tiers = [(30, 0.24), (60, 0.2), (90, 0.15), (120, 0.1), (180, 0.05), (999, 0.0)]
    assert get_payment_timeliness_rate(10, tiers) == pytest.approx(0.0024)
    assert get_payment_timeliness_rate(45, tiers) == pytest.approx(0.002)
    assert get_payment_timeliness_rate(150, tiers) == pytest.approx(0.0005)
    assert get_payment_timeliness_rate(500, tiers) == 0.0


# ── build_salesperson_dept_map ─────────────────────────────────

def test_salesperson_dept_map_prefers_delivery():
    d = pd.DataFrame({"销售员": ["A", "B"], "销售部门": ["D1", "D2"]})
    p = pd.DataFrame({"销售员": ["A", "C"], "销售部门": ["D-X", "D3"]})
    m = build_salesperson_dept_map(d, p)
    assert m["A"] == "D1"      # 交货优先
    assert m["B"] == "D2"
    assert m["C"] == "D3"


# ── 端到端轻量校验 ────────────────────────────────────────────

def _sample_delivery():
    return pd.DataFrame([
        {"销售员": "张三", "销售部门": "东部", "合同编号": "C1",
         "发货金额": 50000, "发货日期": pd.Timestamp("2024-01-10")},
        {"销售员": "张三", "销售部门": "东部", "合同编号": "C1",
         "发货金额": 50000, "发货日期": pd.Timestamp("2024-02-10")},
        {"销售员": "李四", "销售部门": "东部", "合同编号": "C2",
         "发货金额": 20000, "发货日期": pd.Timestamp("2024-01-20")},
    ])


def _sample_payment():
    return pd.DataFrame([
        {"销售员": "张三", "销售部门": "东部", "合同编号": "C1",
         "回款金额": 30000, "回款日期": pd.Timestamp("2024-02-01")},
        {"销售员": "张三", "销售部门": "东部", "合同编号": "C1",
         "回款金额": 70000, "回款日期": pd.Timestamp("2024-03-20")},
        {"销售员": "李四", "销售部门": "东部", "合同编号": "C2",
         "回款金额": 20000, "回款日期": pd.Timestamp("2024-02-18")},
    ])


def test_calc_quota_commission_by_dept_ratio_shared():
    d, p = _sample_delivery(), _sample_payment()
    # 部门发货合计 = 120000 元，目标 = 20 万元 = 200000 元 → 完成比 60%
    res = calc_quota_commission_by_dept(d, p, {"东部": 20})
    assert set(res["销售员"]) == {"张三", "李四"}
    assert all(res["部门完成比"] == "60.0%")
    # 60% 档位提成率 0.1% → 每人的个人提成 = 回款额 × 0.001
    zhang = res[res["销售员"] == "张三"].iloc[0]
    assert zhang["完成额度提成(元)"] == pytest.approx(100.0)  # 100000 × 0.001
    li = res[res["销售员"] == "李四"].iloc[0]
    assert li["完成额度提成(元)"] == pytest.approx(20.0)


def test_calc_profit_commission_handles_unpriced_contracts():
    d, p = _sample_delivery(), _sample_payment()
    prices = {"C1": ContractPricing("C1", 100000, 95000, 80000)}  # 只给 C1
    res = calc_profit_commission(d, p, prices)
    assert not res.empty
    c1 = res[res["合同编号"] == "C1"].iloc[0]
    assert c1["利润提成金额"] > 0
    c2 = res[res["合同编号"] == "C2"].iloc[0]
    assert c2["利润提成金额"] == 0
    assert c2["利润分类"] == "未设定价格"


def test_calc_payment_timeliness_fifo_matches():
    d, p = _sample_delivery(), _sample_payment()
    tl, _del_sum, _pay_sum = calc_payment_timeliness(d, p)
    # 张三: 30000 匹配到首笔发货(2024-01-10) → 周期 22 天
    zhang_rows = tl[tl["销售员"] == "张三"].sort_values("回款日期").reset_index(drop=True)
    assert len(zhang_rows) >= 2
    assert zhang_rows.iloc[0]["回款周期(天)"] == 22
    # 李四: 20000 对齐 C2, 周期 29 天
    li_row = tl[tl["销售员"] == "李四"].iloc[0]
    assert li_row["回款周期(天)"] == 29
