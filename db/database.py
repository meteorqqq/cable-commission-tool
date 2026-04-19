"""数据库连接与操作

优先使用环境变量 / Streamlit Secrets 中的 ``DATABASE_URL``（远程 Postgres 等），
未设置时回落到仓库内的本地 SQLite，保留本地开发体验。

部署到 Streamlit Cloud 时，必须在 App → Settings → Secrets 中配置：

    DATABASE_URL = "postgresql+psycopg2://user:password@host/db?sslmode=require"
"""

from __future__ import annotations
import io
import json
import os
from pathlib import Path
from datetime import datetime

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from db.models import (
    Base, CalcSession, SessionResult, SavedRule, ContractPrice, ImportedSnapshot,
)

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "app.db"


def _resolve_db_url() -> str:
    """按优先级解析数据库连接串：环境变量 > st.secrets > 本地 SQLite。"""
    url = os.environ.get("DATABASE_URL")
    if url:
        return _normalize_url(url)
    try:
        import streamlit as st  # 延迟导入，避免脚本式调用时强依赖
        if hasattr(st, "secrets") and "DATABASE_URL" in st.secrets:
            return _normalize_url(str(st.secrets["DATABASE_URL"]))
    except Exception:
        pass
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{DB_PATH}"


def _normalize_url(url: str) -> str:
    """兼容 Neon / Heroku 给的 postgres:// 旧前缀。"""
    if url.startswith("postgres://"):
        url = "postgresql+psycopg2://" + url[len("postgres://"):]
    elif url.startswith("postgresql://") and "+psycopg2" not in url and "+psycopg" not in url:
        url = "postgresql+psycopg2://" + url[len("postgresql://"):]
    return url


def get_engine():
    url = _resolve_db_url()
    engine_kwargs: dict = {"echo": False}
    if url.startswith("postgresql"):
        engine_kwargs.update(pool_pre_ping=True, pool_recycle=300)
    engine = create_engine(url, **engine_kwargs)
    Base.metadata.create_all(engine)
    return engine


_engine = None
_SessionLocal = None


def get_session() -> Session:
    global _engine, _SessionLocal
    if _engine is None:
        _engine = get_engine()
        _SessionLocal = sessionmaker(bind=_engine)
    return _SessionLocal()


# ── 计算会话 ──────────────────────────────────────────────

def save_calc_session(username: str, name: str,
                      results: dict[str, pd.DataFrame]) -> int:
    sess = get_session()
    try:
        cs = CalcSession(username=username, name=name)
        sess.add(cs)
        sess.flush()

        for rtype, df in results.items():
            if df is not None and not df.empty:
                data = df.copy()
                for col in data.columns:
                    if pd.api.types.is_datetime64_any_dtype(data[col]):
                        data[col] = data[col].dt.strftime("%Y-%m-%d")
                sr = SessionResult(
                    session_id=cs.id,
                    result_type=rtype,
                    data_json=data.to_json(orient="records", force_ascii=False),
                )
                sess.add(sr)

        sess.commit()
        return cs.id
    finally:
        sess.close()


def list_sessions(username: str | None = None) -> list[dict]:
    sess = get_session()
    try:
        q = sess.query(CalcSession).order_by(CalcSession.created_at.desc())
        if username:
            q = q.filter(CalcSession.username == username)
        rows = []
        for cs in q.all():
            rows.append({
                "id": cs.id,
                "username": cs.username,
                "name": cs.name,
                "created_at": cs.created_at.strftime("%Y-%m-%d %H:%M:%S") if cs.created_at else "",
                "result_types": [r.result_type for r in cs.results],
            })
        return rows
    finally:
        sess.close()


def load_session_results(session_id: int) -> dict[str, pd.DataFrame]:
    sess = get_session()
    try:
        results = {}
        for sr in sess.query(SessionResult).filter_by(session_id=session_id).all():
            results[sr.result_type] = pd.read_json(io.StringIO(sr.data_json), orient="records")
        return results
    finally:
        sess.close()


def delete_session(session_id: int):
    sess = get_session()
    try:
        cs = sess.query(CalcSession).get(session_id)
        if cs:
            sess.delete(cs)
            sess.commit()
    finally:
        sess.close()


# ── 规则持久化 ────────────────────────────────────────────

def save_rules(username: str, rule_type: str, rule_data: object):
    sess = get_session()
    try:
        existing = sess.query(SavedRule).filter_by(
            username=username, rule_type=rule_type).first()
        data_json = json.dumps(rule_data, ensure_ascii=False)
        if existing:
            existing.rule_data_json = data_json
            existing.updated_at = datetime.now()
        else:
            sess.add(SavedRule(
                username=username, rule_type=rule_type,
                rule_data_json=data_json))
        sess.commit()
    finally:
        sess.close()


def load_rules(username: str, rule_type: str) -> object | None:
    sess = get_session()
    try:
        row = sess.query(SavedRule).filter_by(
            username=username, rule_type=rule_type).first()
        return json.loads(row.rule_data_json) if row else None
    finally:
        sess.close()


# ── 合同价格持久化 ────────────────────────────────────────

def save_contract_prices(username: str, prices: list[dict]):
    sess = get_session()
    try:
        sess.query(ContractPrice).filter_by(username=username).delete()
        for p in prices:
            sess.add(ContractPrice(
                username=username,
                project_id=p["project_id"],
                guide_price=p.get("guide_price", 0),
                contract_price=p.get("contract_price", 0),
                cost_price=p.get("cost_price", 0),
            ))
        sess.commit()
    finally:
        sess.close()


def load_contract_prices(username: str) -> list[dict]:
    sess = get_session()
    try:
        rows = sess.query(ContractPrice).filter_by(username=username).all()
        return [{
            "project_id": r.project_id,
            "guide_price": r.guide_price,
            "contract_price": r.contract_price,
            "cost_price": r.cost_price,
        } for r in rows]
    finally:
        sess.close()


def _dataframe_to_records_json(df: pd.DataFrame) -> str:
    data = df.copy()
    for col in data.columns:
        if pd.api.types.is_datetime64_any_dtype(data[col]):
            data[col] = data[col].dt.strftime("%Y-%m-%d")
    return data.to_json(orient="records", force_ascii=False)


def save_import_snapshots(
    username: str,
    delivery_df: pd.DataFrame | None = None,
    payment_df: pd.DataFrame | None = None,
):
    """持久化交货/回款 Excel 解析后的全量明细；仅更新传入的非空表。"""
    sess = get_session()
    try:
        row = sess.query(ImportedSnapshot).filter_by(username=username).first()
        if row is None:
            row = ImportedSnapshot(username=username)
            sess.add(row)
            sess.flush()
        if delivery_df is not None and not delivery_df.empty:
            row.delivery_json = _dataframe_to_records_json(delivery_df)
        if payment_df is not None and not payment_df.empty:
            row.payment_json = _dataframe_to_records_json(payment_df)
        row.updated_at = datetime.now()
        sess.commit()
    finally:
        sess.close()


def _normalize_loaded_df(df: pd.DataFrame | None) -> pd.DataFrame | None:
    if df is None or df.empty:
        return df
    if "合同编号" in df.columns:
        df["合同编号"] = df["合同编号"].astype("string").str.strip()
        df.loc[
            df["合同编号"].isin(["", "nan", "None"]) | df["合同编号"].isna(),
            "合同编号",
        ] = "其他"
    for dcol in ("发货日期", "回款日期"):
        if dcol in df.columns:
            df[dcol] = pd.to_datetime(df[dcol], errors="coerce")
    if "销售部门" in df.columns:
        from engine.calculator import clean_dept_name
        df["销售部门"] = df["销售部门"].map(clean_dept_name)
    return df


def load_import_snapshots(username: str) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    sess = get_session()
    try:
        row = sess.query(ImportedSnapshot).filter_by(username=username).first()
        if row is None:
            return None, None
        delivery = (
            pd.read_json(io.StringIO(row.delivery_json), orient="records")
            if row.delivery_json
            else None
        )
        payment = (
            pd.read_json(io.StringIO(row.payment_json), orient="records")
            if row.payment_json
            else None
        )
        return _normalize_loaded_df(delivery), _normalize_loaded_df(payment)
    finally:
        sess.close()
