"""下载按钮与导出格式的统一工具。"""

from __future__ import annotations

import hashlib
import io
import pickle
import zipfile

import pandas as pd
import streamlit as st

CSV_MIME = "text/csv"
EXCEL_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
ZIP_MIME = "application/zip"


def _normalize_for_export(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[col]):
            out[col] = out[col].dt.strftime("%Y-%m-%d")
    return out


def _safe_name(name: str) -> str:
    text = str(name or "").strip()
    if not text:
        text = "export"
    return text.replace("/", "_").replace("\\", "_")


def _df_signature(df: pd.DataFrame) -> str:
    normalized = _normalize_for_export(df)
    try:
        blob = pickle.dumps((tuple(normalized.columns), normalized.shape, normalized.to_dict("split")), protocol=4)
    except Exception:
        blob = repr((tuple(normalized.columns), normalized.shape, normalized.to_csv(index=False))).encode(
            "utf-8", errors="ignore"
        )
    return hashlib.md5(blob).hexdigest()


def _results_signature(results: dict[str, pd.DataFrame]) -> str:
    parts = [(str(name), _df_signature(df)) for name, df in results.items()]
    return hashlib.md5(pickle.dumps(parts, protocol=4)).hexdigest()


def _cached_bytes(cache_key: str, signature: str, factory) -> bytes:
    state_key = f"_download_bytes::{cache_key}::{signature}"
    cached = st.session_state.get(state_key)
    if cached is not None:
        return cached
    data = factory()
    st.session_state[state_key] = data
    return data


def dataframe_to_csv_bytes(df: pd.DataFrame) -> bytes:
    signature = f"csv:{_df_signature(df)}"
    return _cached_bytes(
        "single_csv",
        signature,
        lambda: _normalize_for_export(df).to_csv(index=False).encode("utf-8-sig"),
    )


def dataframe_to_excel_bytes(df: pd.DataFrame, sheet_name: str = "Sheet1") -> bytes:
    signature = f"xlsx:{sheet_name}:{_df_signature(df)}"

    def _build() -> bytes:
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            _normalize_for_export(df).to_excel(writer, sheet_name=str(sheet_name)[:31], index=False)
        return buf.getvalue()

    return _cached_bytes("single_xlsx", signature, _build)


def dataframes_to_excel_bytes(results: dict[str, pd.DataFrame]) -> bytes:
    signature = f"multi_xlsx:{_results_signature(results)}"

    def _build() -> bytes:
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            for name, df in results.items():
                _normalize_for_export(df).to_excel(
                    writer, sheet_name=str(name or "sheet")[:31], index=False
                )
        return buf.getvalue()

    return _cached_bytes("multi_xlsx", signature, _build)


def dataframes_to_csv_zip_bytes(results: dict[str, pd.DataFrame]) -> bytes:
    signature = f"multi_zip:{_results_signature(results)}"

    def _build() -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for name, df in results.items():
                csv_bytes = _normalize_for_export(df).to_csv(index=False).encode("utf-8-sig")
                zf.writestr(f"{_safe_name(name)}.csv", csv_bytes)
        return buf.getvalue()

    return _cached_bytes("multi_zip", signature, _build)


def render_df_download_buttons(
    df: pd.DataFrame,
    *,
    base_filename: str,
    sheet_name: str,
    key_prefix: str,
    use_container_width: bool = True,
) -> None:
    name = _safe_name(base_filename)
    csv_bytes = dataframe_to_csv_bytes(df)
    excel_bytes = dataframe_to_excel_bytes(df, sheet_name=sheet_name)

    c1, c2 = st.columns(2, gap="medium")
    with c1:
        st.download_button(
            "下载 CSV",
            csv_bytes,
            f"{name}.csv",
            CSV_MIME,
            key=f"{key_prefix}_csv_dl",
            use_container_width=use_container_width,
        )
    with c2:
        st.download_button(
            "下载 Excel",
            excel_bytes,
            f"{name}.xlsx",
            EXCEL_MIME,
            key=f"{key_prefix}_xlsx_dl",
            use_container_width=use_container_width,
        )


def render_lazy_df_download_buttons(
    df: pd.DataFrame,
    *,
    base_filename: str,
    sheet_name: str,
    key_prefix: str,
    prepare_label: str = "准备下载 CSV / Excel",
    use_container_width: bool = True,
) -> None:
    """延迟构建版的单表下载。

    先只显示一个「准备下载」按钮，用户点击后才真正生成 CSV / Excel 字节并显示
    下载按钮。用于总汇总页这类「同一屏可能有几十上百个下载位」的场景：避免每次
    渲染都对每位销售员即时跑一遍 openpyxl 序列化，把单线程占满导致页面卡死。
    """
    ready_key = f"_dl_ready::{key_prefix}"
    if not st.session_state.get(ready_key):
        if st.button(prepare_label, key=f"{key_prefix}_prep",
                     use_container_width=use_container_width):
            st.session_state[ready_key] = True
        else:
            return
    render_df_download_buttons(
        df,
        base_filename=base_filename,
        sheet_name=sheet_name,
        key_prefix=key_prefix,
        use_container_width=use_container_width,
    )


def render_lazy_multi_download_buttons(
    results_factory,
    *,
    base_filename: str,
    key_prefix: str,
    prepare_label: str = "准备下载（汇总 + 各明细）",
    use_container_width: bool = True,
) -> None:
    """延迟构建版的多 sheet 下载。

    ``results_factory`` 是一个返回 ``{sheet名: DataFrame}`` 的可调用对象，只有在
    用户点击「准备下载」后才会执行——避免每次渲染都汇总并把整本工作簿（含全部
    交货/回款明细）序列化成 Excel。
    """
    ready_key = f"_dl_ready::{key_prefix}"
    if not st.session_state.get(ready_key):
        if st.button(prepare_label, key=f"{key_prefix}_prep",
                     use_container_width=use_container_width):
            st.session_state[ready_key] = True
        else:
            return
    results = results_factory()
    render_multi_download_buttons(
        results,
        base_filename=base_filename,
        key_prefix=key_prefix,
        use_container_width=use_container_width,
    )


def render_multi_download_buttons(
    results: dict[str, pd.DataFrame],
    *,
    base_filename: str,
    key_prefix: str,
    use_container_width: bool = True,
) -> None:
    name = _safe_name(base_filename)
    csv_zip = dataframes_to_csv_zip_bytes(results)
    excel_bytes = dataframes_to_excel_bytes(results)

    c1, c2 = st.columns(2, gap="medium")
    with c1:
        st.download_button(
            "下载 CSV (ZIP)",
            csv_zip,
            f"{name}.zip",
            ZIP_MIME,
            key=f"{key_prefix}_zip_dl",
            use_container_width=use_container_width,
        )
    with c2:
        st.download_button(
            "下载 Excel",
            excel_bytes,
            f"{name}.xlsx",
            EXCEL_MIME,
            key=f"{key_prefix}_xlsx_dl",
            use_container_width=use_container_width,
        )
