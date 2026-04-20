"""轻量级的 session-scope 缓存。

Streamlit 每次重跑脚本都会重建 page 函数里的临时 DataFrame，对重聚合
非常不友好。我们用 ``st.session_state`` 按数据版本号缓存结果：

- ``bump_data_version()``：原始数据变化（上传 Excel / 加载快照）时调用
- ``bump_calc_version()``：某个提成计算结果刷新时调用
- ``@session_cache("key", scope="data" | "calc")``：声明式缓存

语义很简单：同一版本下同一 key 只会计算一次；升版本后自动清理旧结果，
避免 ``st.session_state`` 无限膨胀。
"""

from __future__ import annotations

from functools import wraps

import streamlit as st


_DATA_VERSION_KEY = "_data_version"
_CALC_VERSION_KEY = "_calc_version"


def data_version() -> int:
    return int(st.session_state.get(_DATA_VERSION_KEY, 0))


def calc_version() -> int:
    return int(st.session_state.get(_CALC_VERSION_KEY, 0))


def bump_data_version() -> int:
    v = data_version() + 1
    st.session_state[_DATA_VERSION_KEY] = v
    # 同时让 calc 派生结果失效
    bump_calc_version()
    return v


def bump_calc_version() -> int:
    v = calc_version() + 1
    st.session_state[_CALC_VERSION_KEY] = v
    return v


def _prune_old_memo(prefix: str, keep_suffix: str) -> None:
    keep = f"{prefix}{keep_suffix}"
    for k in list(st.session_state.keys()):
        if isinstance(k, str) and k.startswith(prefix) and k != keep:
            del st.session_state[k]


def invalidate_calc_cache() -> None:
    """提成计算结果变更时调用，废弃所有 calc-scope 的缓存。"""
    bump_calc_version()


def session_cache(name: str, scope: str = "data"):
    """按版本号缓存函数结果到 ``st.session_state``。

    Parameters
    ----------
    name : str
        缓存逻辑键，同名函数共享同一缓存桶。
    scope : {"data", "calc"}
        依赖的版本号。"data" 随原始数据变化失效，
        "calc" 随任一提成计算结果变化失效。
    """
    if scope not in ("data", "calc"):
        raise ValueError("scope must be 'data' or 'calc'")

    def deco(fn):
        prefix = f"_memo::{name}::"

        @wraps(fn)
        def wrapped(*args, **kwargs):
            v = data_version() if scope == "data" else calc_version()
            suffix = f"v{v}"
            key = f"{prefix}{suffix}"
            if key in st.session_state:
                return st.session_state[key]
            _prune_old_memo(prefix, suffix)
            result = fn(*args, **kwargs)
            st.session_state[key] = result
            return result

        return wrapped

    return deco


# ── 常用重聚合函数的缓存代理 ──
# 这些函数只依赖 session_state 里的 delivery_df / payment_df，
# 故可以 data-scope 缓存；Excel 重传 / 快照加载会 bump_data_version 使其失效。

def get_invoice_units_by_contract():
    """{合同编号 -> 开票单位字符串}"""
    from engine.calculator import invoice_units_by_contract  # 延迟导入避免循环

    @session_cache("inv_units_by_contract", scope="data")
    def _compute():
        return invoice_units_by_contract(
            st.session_state.get("delivery_df"),
            st.session_state.get("payment_df"),
        )

    return _compute()


def get_invoice_units_by_contract_sp():
    """{(合同编号, 销售员) -> 开票单位字符串}"""
    from engine.calculator import invoice_units_by_contract_sp

    @session_cache("inv_units_by_contract_sp", scope="data")
    def _compute():
        return invoice_units_by_contract_sp(
            st.session_state.get("delivery_df"),
            st.session_state.get("payment_df"),
        )

    return _compute()


def get_project_list():
    """所有出现过的合同编号（去重、已排序）"""
    from engine.calculator import extract_project_list

    @session_cache("project_list", scope="data")
    def _compute():
        return extract_project_list(
            st.session_state.get("delivery_df"),
            st.session_state.get("payment_df"),
        )

    return _compute()


def get_contract_overview():
    """合同编号 × 金额/笔数 概览 DataFrame"""
    from engine.calculator import build_contract_overview

    @session_cache("contract_overview", scope="data")
    def _compute():
        return build_contract_overview(
            st.session_state.get("delivery_df"),
            st.session_state.get("payment_df"),
        )

    return _compute()

