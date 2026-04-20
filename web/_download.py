"""下载按钮与导出格式的统一工具。"""

from __future__ import annotations

import io
import os
import sys
import zipfile
from pathlib import Path

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


def _default_save_dir() -> Path:
    # PyInstaller 等打包场景：优先保存到 exe 同目录
    if getattr(sys, "frozen", False):
        try:
            return Path(sys.executable).resolve().parent
        except Exception:
            pass
    home = Path(os.path.expanduser("~"))
    downloads = home / "Downloads"
    if downloads.exists():
        return downloads
    return home


def _save_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _render_save_button(
    *,
    label: str,
    output_path: Path,
    payload: bytes,
    key: str,
    use_container_width: bool,
) -> None:
    if st.button(label, key=key, use_container_width=use_container_width):
        try:
            _save_bytes(output_path, payload)
            st.success(f"已保存到本地：{output_path}")
        except Exception as e:
            st.error(f"保存失败：{e}")


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
    save_dir = _default_save_dir()
    csv_path = save_dir / f"{name}.csv"
    xlsx_path = save_dir / f"{name}.xlsx"

    c1, c2 = st.columns(2, gap="medium")
    with c1:
        _render_save_button(
            label="保存 CSV 到本地",
            output_path=csv_path,
            payload=csv_bytes,
            key=f"{key_prefix}_csv_save",
            use_container_width=use_container_width,
        )
    with c2:
        _render_save_button(
            label="保存 Excel 到本地",
            output_path=xlsx_path,
            payload=excel_bytes,
            key=f"{key_prefix}_xlsx_save",
            use_container_width=use_container_width,
        )
    st.caption(f"默认保存目录：{save_dir}")


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
    save_dir = _default_save_dir()
    zip_path = save_dir / f"{name}.zip"
    xlsx_path = save_dir / f"{name}.xlsx"

    c1, c2 = st.columns(2, gap="medium")
    with c1:
        _render_save_button(
            label="保存 CSV (ZIP) 到本地",
            output_path=zip_path,
            payload=csv_zip,
            key=f"{key_prefix}_zip_save",
            use_container_width=use_container_width,
        )
    with c2:
        _render_save_button(
            label="保存 Excel 到本地",
            output_path=xlsx_path,
            payload=excel_bytes,
            key=f"{key_prefix}_xlsx_save",
            use_container_width=use_container_width,
        )
    st.caption(f"默认保存目录：{save_dir}")
