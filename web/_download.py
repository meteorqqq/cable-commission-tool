"""下载按钮与导出格式的统一工具。"""

from __future__ import annotations

import io
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


def dataframe_to_excel_bytes(df: pd.DataFrame, sheet_name: str = "Sheet1") -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        _normalize_for_export(df).to_excel(writer, sheet_name=str(sheet_name)[:31], index=False)
    return buf.getvalue()


def dataframes_to_excel_bytes(results: dict[str, pd.DataFrame]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for name, df in results.items():
            _normalize_for_export(df).to_excel(
                writer, sheet_name=str(name or "sheet")[:31], index=False
            )
    return buf.getvalue()


def dataframes_to_csv_zip_bytes(results: dict[str, pd.DataFrame]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, df in results.items():
            csv_bytes = _normalize_for_export(df).to_csv(index=False).encode("utf-8-sig")
            zf.writestr(f"{_safe_name(name)}.csv", csv_bytes)
    return buf.getvalue()


def render_df_download_buttons(
    df: pd.DataFrame,
    *,
    base_filename: str,
    sheet_name: str,
    key_prefix: str,
    use_container_width: bool = True,
) -> None:
    name = _safe_name(base_filename)
    csv_bytes = df.to_csv(index=False).encode("utf-8-sig")
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
