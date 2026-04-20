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

import hashlib
import pickle
from functools import wraps

import streamlit as st


_DATA_VERSION_KEY = "_data_version"
_CALC_VERSION_KEY = "_calc_version"
_PRICE_VERSION_KEY = "_price_version"


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


def price_version() -> int:
    return int(st.session_state.get(_PRICE_VERSION_KEY, 0))


def bump_price_version() -> int:
    v = price_version() + 1
    st.session_state[_PRICE_VERSION_KEY] = v
    return v


def _prune_old_memo(prefix: str, keep_version: str) -> None:
    """只保留当前版本的所有分参数缓存，丢弃旧版本所有残留。"""
    keep = f"{prefix}{keep_version}::"
    for k in list(st.session_state.keys()):
        if isinstance(k, str) and k.startswith(prefix) and not k.startswith(keep):
            del st.session_state[k]


def _args_key(args: tuple, kwargs: dict) -> str:
    """把函数调用参数序列化成一个短哈希，作为 cache key 的一部分。

    pickle 兜底处理 DataFrame / 自定义对象等非 JSON 可序列化的值。
    """
    if not args and not kwargs:
        return "noargs"
    try:
        blob = pickle.dumps((args, tuple(sorted(kwargs.items()))), protocol=4)
    except Exception:
        blob = repr((args, sorted(kwargs.items()))).encode("utf-8", errors="ignore")
    return hashlib.md5(blob).hexdigest()[:16]


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
    if scope not in ("data", "calc", "price"):
        raise ValueError("scope must be 'data', 'calc' or 'price'")

    def deco(fn):
        prefix = f"_memo::{name}::"

        @wraps(fn)
        def wrapped(*args, **kwargs):
            if scope == "data":
                v = data_version()
            elif scope == "calc":
                v = calc_version()
            else:
                v = price_version()
            version = f"v{v}"
            arg_hash = _args_key(args, kwargs)
            key = f"{prefix}{version}::{arg_hash}"
            if key in st.session_state:
                return st.session_state[key]
            _prune_old_memo(prefix, version)
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


def get_salesperson_dept_map() -> dict[str, str]:
    """{销售员 -> 销售部门}，按当前 delivery/payment 数据缓存。"""
    from engine.calculator import build_salesperson_dept_map

    @session_cache("salesperson_dept_map", scope="data")
    def _compute():
        return build_salesperson_dept_map(
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


def _group_by_pid_sp(df, key_cols=("合同编号", "销售员")):
    """把 df 按 (合同编号, 销售员) 预先分组成 dict[(pid, sp)] -> DataFrame。

    一次 groupby + O(N) 分桶，后续取子集都是 O(1)。
    """
    import pandas as pd
    if df is None or df.empty:
        return {}
    if any(c not in df.columns for c in key_cols):
        return {}
    keys = list(zip(*(df[c].astype(str) for c in key_cols)))
    out: dict[tuple, list[int]] = {}
    for idx, k in enumerate(keys):
        out.setdefault(k, []).append(idx)
    positions = df.reset_index(drop=True)
    return {k: positions.iloc[idxs] for k, idxs in out.items()}


def get_delivery_by_pid_sp():
    """{(合同编号, 销售员) -> 子 DataFrame}，用于渲染时快速取出该合同明细。"""
    @session_cache("delivery_by_pid_sp", scope="data")
    def _compute():
        return _group_by_pid_sp(st.session_state.get("delivery_df"))
    return _compute()


def get_payment_by_pid_sp():
    @session_cache("payment_by_pid_sp", scope="data")
    def _compute():
        return _group_by_pid_sp(st.session_state.get("payment_df"))
    return _compute()


def get_timeliness_by_pid_sp():
    """时效明细按 (合同编号, 销售员) 预分组。依赖计算结果 → calc scope。"""
    @session_cache("timeliness_by_pid_sp", scope="calc")
    def _compute():
        return _group_by_pid_sp(st.session_state.get("timeliness_result"))
    return _compute()

