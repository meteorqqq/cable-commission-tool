"""engine/calculator.py 核心纯函数的单元测试。

只覆盖与业务规则最相关的函数，避免耦合 Streamlit / 数据库。
运行：``python -m pytest tests -q``
"""

from __future__ import annotations

import pandas as pd
import pytest

from engine.calculator import (
    annotate_delivery_business_type,
    annotate_payment_business_type,
    extract_isolated_returns,
    clean_dept_name,
    contract_status,
    get_quota_rate,
    calc_profit_k_and_rate,
    get_payment_timeliness_rate,
    calc_quota_commission_by_dept,
    calc_profit_commission,
    calc_payment_timeliness,
    build_contract_overview,
    build_salesperson_dept_map,
    build_contract_dept_map,
    build_salesperson_detail,
    build_main_contract_map,
    load_contract_pricing_excel,
    load_delivery_excel,
    load_payment_excel,
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
        (100, -20, "未回款"),
        (0, 0, "未发货"),
        (0, -50, "未发货"),
        (0, 50, "未发货（已收款）"),
        (-100, 0, "未发货"),
        (-100, 50, "未发货（已收款）"),
        (-100, -50, "未发货"),
    ],
)
def test_contract_status(d, p, expected):
    assert contract_status(d, p) == expected


def test_annotate_business_type_marks_negative_amounts():
    delivery = pd.DataFrame({"发货金额": [100, -20, 0]})
    payment = pd.DataFrame({"回款金额": [100, -30, 0]})

    delivery_out = annotate_delivery_business_type(delivery)
    payment_out = annotate_payment_business_type(payment)

    assert delivery_out["业务类型"].tolist() == ["发货", "退货", "发货"]
    assert payment_out["业务类型"].tolist() == ["回款", "退款", "回款"]


def test_annotate_payment_business_type_keeps_existing_explicit_label():
    payment = pd.DataFrame({
        "回款金额": [-30],
        "业务类型": ["孤立退货"],
    })

    payment_out = annotate_payment_business_type(payment)

    assert payment_out.loc[0, "业务类型"] == "孤立退货"


def test_extract_isolated_returns_keeps_only_unmatched_negative_delivery():
    delivery = pd.DataFrame([
        {"销售员": "张三", "销售部门": "东部", "合同编号": "C1",
         "发货日期": pd.Timestamp("2024-01-01"), "发货金额": 1000},
        {"销售员": "张三", "销售部门": "东部", "合同编号": "C1",
         "发货日期": pd.Timestamp("2024-01-02"), "发货金额": -400},
        {"销售员": "张三", "销售部门": "东部", "合同编号": "C1",
         "发货日期": pd.Timestamp("2024-01-03"), "发货金额": -900},
        {"销售员": "李四", "销售部门": "东部", "合同编号": "C2",
         "发货日期": pd.Timestamp("2024-01-01"), "发货金额": -500},
    ])

    res = extract_isolated_returns(delivery)

    assert len(res) == 2
    c1 = res[res["合同编号"] == "C1"].iloc[0]
    c2 = res[res["合同编号"] == "C2"].iloc[0]
    assert c1["孤立退货金额"] == pytest.approx(-300.0)
    assert c1["业务类型"] == "孤立退货"
    assert c2["孤立退货金额"] == pytest.approx(-500.0)


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


# ── build_contract_overview ────────────────────────────────────

def test_build_contract_overview_summarizes_both_sides_and_flags():
    delivery = pd.DataFrame([
        {"合同编号": "C2", "发货金额": 200},
        {"合同编号": "C1", "发货金额": 100},
        {"合同编号": "C1", "发货金额": -30},
        {"合同编号": None, "发货金额": 999},
    ])
    payment = pd.DataFrame([
        {"合同编号": "C1", "回款金额": 50},
        {"合同编号": "C3", "回款金额": 80},
        {"合同编号": "C3", "回款金额": -10},
        {"合同编号": None, "回款金额": 999},
    ])

    res = build_contract_overview(delivery, payment)

    assert res["合同编号"].tolist() == ["C1", "C2", "C3"]
    c1 = res[res["合同编号"] == "C1"].iloc[0]
    assert c1["交货行数"] == 2
    assert c1["交货金额合计"] == pytest.approx(70.0)
    assert c1["回款行数"] == 1
    assert c1["回款金额合计"] == pytest.approx(50.0)
    assert c1["业务标记"] == "有退货"
    assert c1["数据情况"] == "交货与回款均有"

    c2 = res[res["合同编号"] == "C2"].iloc[0]
    assert c2["数据情况"] == "仅交货明细"

    c3 = res[res["合同编号"] == "C3"].iloc[0]
    assert c3["数据情况"] == "仅回款明细"
    assert c3["业务标记"] == "有退款"


# ── build_salesperson_dept_map ─────────────────────────────────

def test_salesperson_dept_map_prefers_delivery():
    d = pd.DataFrame({"销售员": ["A", "B"], "销售部门": ["D1", "D2"]})
    p = pd.DataFrame({"销售员": ["A", "C"], "销售部门": ["D-X", "D3"]})
    m = build_salesperson_dept_map(d, p)
    assert m["A"] == "D1"      # 交货优先
    assert m["B"] == "D2"
    assert m["C"] == "D3"


# ── build_contract_dept_map / 跨部门展示 ───────────────────────

def test_build_contract_dept_map_is_per_contract():
    """部门是合同的属性：同一销售员不同合同分属不同部门。"""
    d = pd.DataFrame([
        {"销售员": "米卢奇", "合同编号": "H1", "销售部门": "海外事业部"},
        {"销售员": "米卢奇", "合同编号": "N1", "销售部门": "东北大区"},
    ])
    p = pd.DataFrame([
        {"销售员": "米卢奇", "合同编号": "N1", "销售部门": "东北大区"},
    ])
    m = build_contract_dept_map(d, p)
    assert m[("米卢奇", "H1")] == "海外事业部"
    assert m[("米卢奇", "N1")] == "东北大区"


def test_build_salesperson_detail_reports_all_departments():
    """销售员详情应汇总该销售员涉及的全部部门，并给每个合同标注归属部门。"""
    d = pd.DataFrame([
        {"销售员": "米卢奇", "销售部门": "海外事业部", "合同编号": "H1",
         "发货金额": 1000, "发货日期": pd.Timestamp("2026-01-10"),
         "订货单位": "客户H", "开票单位": "客户H"},
        {"销售员": "米卢奇", "销售部门": "东北大区", "合同编号": "N1",
         "发货金额": 2000, "发货日期": pd.Timestamp("2026-01-11"),
         "订货单位": "客户N", "开票单位": "客户N"},
    ])
    p = pd.DataFrame([
        {"销售员": "米卢奇", "销售部门": "海外事业部", "合同编号": "H1",
         "回款金额": 1000, "回款日期": pd.Timestamp("2026-02-10"), "开票单位": "客户H"},
    ])
    detail = build_salesperson_detail("米卢奇", d, p)
    assert set(detail["部门列表"]) == {"海外事业部", "东北大区"}
    assert "海外事业部" in detail["销售部门"] and "东北大区" in detail["销售部门"]
    by_pid = {c["合同编号"]: c["销售部门"] for c in detail["合同列表"]}
    assert by_pid["H1"] == "海外事业部"
    assert by_pid["N1"] == "东北大区"


def test_calc_profit_commission_dept_is_per_contract():
    """利润提成结果的「销售部门」列应按合同归属，而非按人取单一部门。"""
    d = pd.DataFrame([
        {"销售员": "米卢奇", "销售部门": "海外事业部", "合同编号": "H1",
         "发货金额": 1000, "发货日期": pd.Timestamp("2026-01-10")},
        {"销售员": "米卢奇", "销售部门": "东北大区", "合同编号": "N1",
         "发货金额": 2000, "发货日期": pd.Timestamp("2026-01-11")},
    ])
    p = pd.DataFrame([
        {"销售员": "米卢奇", "销售部门": "海外事业部", "合同编号": "H1",
         "回款金额": 1000, "回款日期": pd.Timestamp("2026-02-10")},
        {"销售员": "米卢奇", "销售部门": "东北大区", "合同编号": "N1",
         "回款金额": 2000, "回款日期": pd.Timestamp("2026-02-11")},
    ])
    res = calc_profit_commission(d, p, {})
    dept_by_pid = {r["合同编号"]: r["销售部门"] for _, r in res.iterrows()}
    assert dept_by_pid["H1"] == "海外事业部"
    assert dept_by_pid["N1"] == "东北大区"


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


def test_calc_quota_commission_splits_cross_department_salesperson():
    """同一销售员横跨两个部门时，按部门各出一行、各自完成比定档，
    且不会把某部门的发货串入另一部门（回归：米卢奇案例）。"""
    d = pd.DataFrame([
        # 米卢奇在海外事业部
        {"销售员": "米卢奇", "销售部门": "海外事业部", "合同编号": "H1", "发货金额": 100000},
        # 米卢奇在东北大区
        {"销售员": "米卢奇", "销售部门": "东北大区", "合同编号": "N1", "发货金额": 300000},
        # 东北同事，使东北部门完成比独立成立
        {"销售员": "张三", "销售部门": "东北大区", "合同编号": "N2", "发货金额": 100000},
    ])
    p = pd.DataFrame([
        {"销售员": "米卢奇", "销售部门": "海外事业部", "合同编号": "H1", "回款金额": 100000},
        {"销售员": "米卢奇", "销售部门": "东北大区", "合同编号": "N1", "回款金额": 200000},
        {"销售员": "张三", "销售部门": "东北大区", "合同编号": "N2", "回款金额": 100000},
    ])
    # 海外目标 5 万 → 100000/50000 = 200%（≥80% 档 0.2%）
    # 东北目标 50 万 → (300000+100000)/500000 = 80%（0.2% 档）
    res = calc_quota_commission_by_dept(d, p, {"海外事业部": 5, "东北大区": 50})

    mlq = res[res["销售员"] == "米卢奇"]
    assert set(mlq["销售部门"]) == {"海外事业部", "东北大区"}  # 拆成两行

    hw = mlq[mlq["销售部门"] == "海外事业部"].iloc[0]
    nb = mlq[mlq["销售部门"] == "东北大区"].iloc[0]

    # 关键回归：海外部门实际发货只含海外那 10 万，东北的 30 万没被串进来
    assert hw["部门实际发货(万元)"] == pytest.approx(10.0)
    assert nb["部门实际发货(万元)"] == pytest.approx(40.0)

    assert hw["部门完成比"] == "200.0%"
    assert hw["完成额度提成(元)"] == pytest.approx(200.0)   # 100000 × 0.2%
    assert nb["部门完成比"] == "80.0%"
    assert nb["完成额度提成(元)"] == pytest.approx(400.0)   # 200000 × 0.2%

    # 个人发货/回款额按部门拆分，互不串台
    assert hw["个人发货额(元)"] == pytest.approx(100000.0)
    assert nb["个人发货额(元)"] == pytest.approx(300000.0)


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


def test_build_main_contract_map_defaults_to_self():
    d = pd.DataFrame({"合同编号": ["A", "B", "C"]})
    p = pd.DataFrame({"合同编号": ["A", "D"]})
    m = build_main_contract_map(d, p)
    # 没有"主合同编号"列时，main == self
    assert m == {"A": "A", "B": "B", "C": "C", "D": "D"}


def test_build_main_contract_map_reads_parent():
    d = pd.DataFrame({
        "合同编号": ["S1", "S2", "M1", "X"],
        "主合同编号": ["M1", "M1", "M1", ""],   # X 留空 → 回落自身
    })
    p = pd.DataFrame({
        "合同编号": ["S1", "Y"],
        "主合同编号": ["M1", "M2"],
    })
    m = build_main_contract_map(d, p)
    assert m["S1"] == "M1"
    assert m["S2"] == "M1"
    assert m["M1"] == "M1"
    assert m["X"] == "X"
    assert m["Y"] == "M2"


def test_calc_profit_commission_sub_uses_parent_pricing():
    """主合同有价时，分项沿用主合同 K 系数；分项自身未录入的价会被忽略。"""
    d = pd.DataFrame([
        {"销售员": "张三", "销售部门": "东部", "合同编号": "SUB-1",
         "发货金额": 10000, "发货日期": pd.Timestamp("2024-01-10")},
        {"销售员": "张三", "销售部门": "东部", "合同编号": "SUB-2",
         "发货金额": 20000, "发货日期": pd.Timestamp("2024-01-20")},
    ])
    p = pd.DataFrame([
        {"销售员": "张三", "销售部门": "东部", "合同编号": "SUB-1",
         "回款金额": 10000, "回款日期": pd.Timestamp("2024-02-10")},
        {"销售员": "张三", "销售部门": "东部", "合同编号": "SUB-2",
         "回款金额": 20000, "回款日期": pd.Timestamp("2024-02-20")},
    ])
    prices = {"MAIN-1": ContractPricing("MAIN-1", 100, 110, 80)}  # k = 1.1
    main_map = {"SUB-1": "MAIN-1", "SUB-2": "MAIN-1", "MAIN-1": "MAIN-1"}

    res = calc_profit_commission(d, p, prices, main_contract_map=main_map)
    assert set(res["合同编号"]) == {"SUB-1", "SUB-2"}

    for _, row in res.iterrows():
        assert row["系数来源"] == "主合同"
        assert row["K系数"] == pytest.approx(1.1)
        assert row["主合同编号"] == "MAIN-1"
        # 沿用主合同 K=1.1，提成 = 回款 × 0.2% × 1.1
        expected = round(row["合同回款额"] * 0.002 * 1.1, 2)
        assert row["利润提成金额"] == pytest.approx(expected)


def test_calc_profit_commission_falls_back_to_self_when_parent_missing():
    d = pd.DataFrame([
        {"销售员": "张三", "销售部门": "东部", "合同编号": "SUB-1",
         "发货金额": 10000, "发货日期": pd.Timestamp("2024-01-10")},
    ])
    p = pd.DataFrame([
        {"销售员": "张三", "销售部门": "东部", "合同编号": "SUB-1",
         "回款金额": 10000, "回款日期": pd.Timestamp("2024-02-10")},
    ])
    # 主合同未录价；分项自己有价 → 用自身
    prices = {"SUB-1": ContractPricing("SUB-1", 100, 90, 80)}
    main_map = {"SUB-1": "MAIN-1"}

    res = calc_profit_commission(d, p, prices, main_contract_map=main_map)
    row = res.iloc[0]
    assert row["系数来源"] == "自身"
    assert row["主合同编号"] == "MAIN-1"
    assert row["利润提成金额"] > 0


def test_load_contract_pricing_excel_splits_multi_pid_cell(tmp_path):
    """合同编号一格里有多个号（顿号/逗号/斜杠/分号/换行）应拆成多条。"""
    df = pd.DataFrame([
        {"合同编号": "RYDB260420007、RYDB260420008",
         "指导价": 125412.9129, "合同价": 126679.71, "成本价": 124779.5144},
        {"合同编号": "RYDB260430001, RYDB260430002 / RYDB260430003",
         "指导价": 100, "合同价": 110, "成本价": 80},
        {"合同编号": "RYDB260440009;RYDB260440010\nRYDB260440011",
         "指导价": 50, "合同价": 55, "成本价": 40},
        {"合同编号": "RYDB260450001", "指导价": 1, "合同价": 1, "成本价": 1},
    ])
    path = tmp_path / "prices.xlsx"
    df.to_excel(path, index=False)

    result = load_contract_pricing_excel(str(path))

    # 每一组都被拆开且共享同样的价格
    assert result["RYDB260420007"].guide_price == pytest.approx(125412.9129)
    assert result["RYDB260420008"].contract_price == pytest.approx(126679.71)
    assert result["RYDB260430002"].cost_price == pytest.approx(80)
    assert result["RYDB260430003"].guide_price == 100
    assert result["RYDB260440009"].guide_price == 50
    assert result["RYDB260440010"].guide_price == 50
    assert result["RYDB260440011"].guide_price == 50
    assert result["RYDB260450001"].guide_price == 1
    # 2 + 3 + 3 + 1 = 9
    assert len(result) == 9


def test_load_delivery_excel_reads_csv(tmp_path):
    """上传入口允许 .csv，加载器必须能读 CSV（含中文 GBK 编码），
    否则给 pd.read_excel 喂 CSV 会直接报错。"""
    df = pd.DataFrame([
        {"销售员": "张三", "销售部门": "东部", "合同编号": "C1",
         "发货金额": 100, "发货日期": "2026-01-01"},
        {"销售员": "李四", "销售部门": "东部", "合同编号": "C2",
         "发货金额": 200, "发货日期": "2026-01-02"},
    ])
    p_utf8 = tmp_path / "d_utf8.csv"
    df.to_csv(p_utf8, index=False, encoding="utf-8-sig")
    out = load_delivery_excel(str(p_utf8))
    assert len(out) == 2
    assert out["发货金额"].sum() == pytest.approx(300)

    # 中文 CSV 常见 GBK 编码也要能读
    p_gbk = tmp_path / "d_gbk.csv"
    df.to_csv(p_gbk, index=False, encoding="gbk")
    out_gbk = load_delivery_excel(str(p_gbk))
    assert len(out_gbk) == 2
    assert set(out_gbk["合同编号"]) == {"C1", "C2"}


def test_load_payment_excel_reads_csv(tmp_path):
    p = pd.DataFrame([
        {"销售员": "张三", "销售部门": "东部", "合同编号": "C1",
         "回款金额": 50, "回款日期": "2026-02-01"},
    ])
    path = tmp_path / "p.csv"
    p.to_csv(path, index=False, encoding="utf-8-sig")
    out = load_payment_excel(str(path))
    assert len(out) == 1
    assert out["回款金额"].sum() == pytest.approx(50)


def test_load_contract_pricing_excel_accepts_project_name_as_pid(tmp_path):
    """价格表用「项目名称」当合同标识列也应识别（回归：实际表头
    ['项目名称', '指导价', '成本价', '合同价']，没有「合同编号」列）。
    关键：价格列「合同价」绝不能被误判成标识列。"""
    df = pd.DataFrame([
        {"项目名称": "RYDB260507003", "指导价": 100, "成本价": 80, "合同价": 110},
        {"项目名称": "RYDB250611006", "指导价": 50, "成本价": 40, "合同价": 55},
    ])
    path = tmp_path / "prices_by_name.xlsx"
    df.to_excel(path, index=False)

    result = load_contract_pricing_excel(str(path))
    assert set(result.keys()) == {"RYDB260507003", "RYDB250611006"}
    r = result["RYDB260507003"]
    assert r.guide_price == pytest.approx(100)
    assert r.contract_price == pytest.approx(110)  # 合同价识别正确，未被当成标识列
    assert r.cost_price == pytest.approx(80)


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


def test_calc_payment_timeliness_refund_reverses_latest():
    """负回款（退款）应按 LIFO 冲销上一次正回款，产生同比例的负提成。"""
    d = pd.DataFrame([
        {"销售员": "王五", "销售部门": "销售部", "合同编号": "C9",
         "发货日期": pd.Timestamp("2024-01-01"), "发货金额": 10000,
         "订货单位": "X", "开票单位": "X"},
    ])
    p = pd.DataFrame([
        {"销售员": "王五", "销售部门": "销售部", "合同编号": "C9",
         "回款日期": pd.Timestamp("2024-02-10"), "回款金额": 10000,
         "核销金额": 10000, "开票单位": "X"},
        {"销售员": "王五", "销售部门": "销售部", "合同编号": "C9",
         "回款日期": pd.Timestamp("2024-03-01"), "回款金额": -4000,
         "核销金额": -4000, "开票单位": "X"},
    ])
    tl, _, _ = calc_payment_timeliness(d, p)
    rows = tl.sort_values("回款日期").reset_index(drop=True)
    # 两条记录：一条正、一条冲销
    assert len(rows) == 2
    r_pos, r_neg = rows.iloc[0], rows.iloc[1]
    # 正回款全额匹配
    assert r_pos["回款金额"] == 10000
    assert r_pos["时效提成金额"] > 0
    rate_pos = r_pos["时效提成金额"] / r_pos["回款金额"]
    # 负回款按同比例产生负提成，且匹配到同一笔发货
    assert r_neg["回款金额"] == -4000
    assert r_neg["匹配发货日期"] == pd.Timestamp("2024-01-01")
    assert r_neg["业务类型"] == "退款"
    assert "退款冲销" in str(r_neg["时效提成比例"])
    assert r_neg["时效提成金额"] == round(-4000 * rate_pos, 2)


def test_calc_payment_timeliness_refund_without_history():
    """先退款后没有可冲销记录：生成一条占位行，提成为 0。"""
    d = pd.DataFrame([
        {"销售员": "赵六", "销售部门": "销售部", "合同编号": "C10",
         "发货日期": pd.Timestamp("2024-01-01"), "发货金额": 5000,
         "订货单位": "X", "开票单位": "X"},
    ])
    p = pd.DataFrame([
        {"销售员": "赵六", "销售部门": "销售部", "合同编号": "C10",
         "回款日期": pd.Timestamp("2024-02-01"), "回款金额": -1000,
         "核销金额": -1000, "开票单位": "X"},
    ])
    tl, _, _ = calc_payment_timeliness(d, p)
    assert len(tl) == 1
    row = tl.iloc[0]
    assert row["回款金额"] == -1000
    assert row["业务类型"] == "退款"
    assert row["时效提成金额"] == 0
    assert row["时效提成比例"] == "无可冲销记录"


def test_calc_payment_timeliness_negative_delivery_excluded_from_pool():
    """退货（负发货）不应进入 FIFO 池，避免把正回款"反向匹配"掉。"""
    d = pd.DataFrame([
        {"销售员": "孙七", "销售部门": "销售部", "合同编号": "C11",
         "发货日期": pd.Timestamp("2024-01-01"), "发货金额": 8000,
         "订货单位": "X", "开票单位": "X"},
        {"销售员": "孙七", "销售部门": "销售部", "合同编号": "C11",
         "发货日期": pd.Timestamp("2024-01-15"), "发货金额": -3000,
         "订货单位": "X", "开票单位": "X"},
    ])
    p = pd.DataFrame([
        {"销售员": "孙七", "销售部门": "销售部", "合同编号": "C11",
         "回款日期": pd.Timestamp("2024-02-10"), "回款金额": 8000,
         "核销金额": 8000, "开票单位": "X"},
    ])
    tl, _, _ = calc_payment_timeliness(d, p)
    # 单一正回款全额匹配到 2024-01-01 那笔正发货（而非被负发货抵扣）
    assert len(tl) == 1
    assert tl.iloc[0]["回款金额"] == 8000
    assert tl.iloc[0]["业务类型"] == "回款"
    assert tl.iloc[0]["匹配发货日期"] == pd.Timestamp("2024-01-01")


def test_calc_payment_timeliness_generates_isolated_return_placeholder():
    d = pd.DataFrame([
        {"销售员": "钱八", "销售部门": "销售部", "合同编号": "C12",
         "发货日期": pd.Timestamp("2024-01-15"), "发货金额": -2500,
         "订货单位": "X", "开票单位": "X"},
    ])
    p = pd.DataFrame(columns=["销售员", "销售部门", "合同编号", "回款日期", "回款金额", "核销金额", "开票单位"])

    tl, _, _ = calc_payment_timeliness(d, p)

    assert len(tl) == 1
    row = tl.iloc[0]
    assert row["业务类型"] == "孤立退货"
    assert row["回款金额"] == pytest.approx(-2500.0)
    assert row["时效提成金额"] == 0
    assert row["时效提成比例"] == "孤立退货（无历史发货）"


def test_calc_payment_timeliness_includes_customer_unit():
    d = pd.DataFrame([
        {"销售员": "周九", "销售部门": "销售部", "合同编号": "C13",
         "发货日期": pd.Timestamp("2024-01-01"), "发货金额": 8000,
         "订货单位": "客户甲", "开票单位": "开票甲"},
    ])
    p = pd.DataFrame([
        {"销售员": "周九", "销售部门": "销售部", "合同编号": "C13",
         "回款日期": pd.Timestamp("2024-01-20"), "回款金额": 5000,
         "核销金额": 5000, "开票单位": "开票甲"},
    ])

    tl, _, _ = calc_payment_timeliness(d, p)

    assert len(tl) == 1
    assert "客户单位" in tl.columns
    assert tl.iloc[0]["客户单位"] == "客户甲"


def test_calc_payment_timeliness_duplicate_payment_then_refund_keeps_commission():
    """重复付款 + 退款：退款应先冲减"超出发货额"的重复回款，不能把已
    合理计提的提成清零（回归：杨凯 RYDB260507003）。"""
    d = pd.DataFrame([
        {"销售员": "杨凯", "销售部门": "能源", "合同编号": "C1",
         "发货日期": pd.Timestamp("2026-05-14"), "发货金额": 79627.20,
         "订货单位": "X", "开票单位": "X"},
        {"销售员": "杨凯", "销售部门": "能源", "合同编号": "C1",
         "发货日期": pd.Timestamp("2026-05-14"), "发货金额": 176553.60,
         "订货单位": "X", "开票单位": "X"},
    ])
    p = pd.DataFrame([
        # 客户把全款付了两次（重复付款），随后退回一次
        {"销售员": "杨凯", "销售部门": "能源", "合同编号": "C1",
         "回款日期": pd.Timestamp("2026-05-13"), "回款金额": 256180.80,
         "核销金额": 256180.80, "开票单位": "X"},
        {"销售员": "杨凯", "销售部门": "能源", "合同编号": "C1",
         "回款日期": pd.Timestamp("2026-05-13"), "回款金额": 256180.80,
         "核销金额": 256180.80, "开票单位": "X"},
        {"销售员": "杨凯", "销售部门": "能源", "合同编号": "C1",
         "回款日期": pd.Timestamp("2026-05-14"), "回款金额": -256180.80,
         "核销金额": -256180.80, "开票单位": "X"},
    ])
    tl, _, _ = calc_payment_timeliness(d, p)
    total = float(pd.to_numeric(tl["时效提成金额"], errors="coerce").fillna(0).sum())
    # 一笔有效回款在时效内（提前 1 天，≤30 天档 0.24%）→ 应保留提成，而非 0
    expected = round(79627.20 * 0.0024, 2) + round(176553.60 * 0.0024, 2)
    assert total == pytest.approx(expected)
    assert total > 0
    # 退款行应冲的是"超出发货额"的过量回款，提成 0
    refund_rows = tl[tl["业务类型"] == "退款"]
    assert (refund_rows["时效提成金额"].abs() < 0.005).all()
    assert (refund_rows["时效提成比例"] == "超出发货额退款冲销").all()


def test_calc_payment_timeliness_overpayment_partial_refund_keeps_matched():
    """大额超付后部分退款：退款冲减超付部分，已匹配回款的提成保留（回归：
    程强 RYDB250611006）。"""
    d = pd.DataFrame([
        {"销售员": "程强", "销售部门": "渠道", "合同编号": "C2",
         "发货日期": pd.Timestamp("2026-01-16"), "发货金额": 15550.34,
         "订货单位": "X", "开票单位": "X"},
    ])
    p = pd.DataFrame([
        {"销售员": "程强", "销售部门": "渠道", "合同编号": "C2",
         "回款日期": pd.Timestamp("2026-04-17"), "回款金额": 229002.39,
         "核销金额": 229002.39, "开票单位": "X"},
        {"销售员": "程强", "销售部门": "渠道", "合同编号": "C2",
         "回款日期": pd.Timestamp("2026-05-15"), "回款金额": -96906.40,
         "核销金额": -96906.40, "开票单位": "X"},
        {"销售员": "程强", "销售部门": "渠道", "合同编号": "C2",
         "回款日期": pd.Timestamp("2026-05-31"), "回款金额": -45865.32,
         "核销金额": -45865.32, "开票单位": "X"},
    ])
    tl, _, _ = calc_payment_timeliness(d, p)
    total = float(pd.to_numeric(tl["时效提成金额"], errors="coerce").fillna(0).sum())
    # 匹配到 15550.34（周期 91 天 → 0.1% 档），退款只冲超付，不动这笔提成
    assert total == pytest.approx(round(15550.34 * 0.001, 2))
    assert total > 0
