"""数据库连接与操作

优先使用环境变量 / Streamlit Secrets 中的 ``DATABASE_URL``（远程 Postgres 等），
未设置时回落到仓库内的本地 SQLite，保留本地开发体验。

部署到 Streamlit Cloud 时，必须在 App → Settings → Secrets 中配置：

    DATABASE_URL = "postgresql+psycopg2://user:password@host/db?sslmode=require"
"""

from __future__ import annotations
import base64
import gzip
import io
import json
import os
from pathlib import Path
from datetime import datetime

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker, Session

try:
    from sqlalchemy.dialects.postgresql import insert as _pg_insert
except Exception:
    _pg_insert = None  # SQLite 场景下不会用到

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


def _is_postgres() -> bool:
    try:
        return _engine is not None and _engine.dialect.name == "postgresql"
    except Exception:
        return False


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
                sr = SessionResult(
                    session_id=cs.id,
                    result_type=rtype,
                    data_json=_dataframe_to_records_json(df),
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
            raw = _decode_json_blob(sr.data_json)
            results[sr.result_type] = pd.read_json(io.StringIO(raw), orient="records")
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
    """把规则按 (username, rule_type) upsert 到 saved_rules。"""
    data_json = json.dumps(rule_data, ensure_ascii=False)
    sess = get_session()
    try:
        if _is_postgres() and _pg_insert is not None:
            stmt = _pg_insert(SavedRule.__table__).values(
                username=username,
                rule_type=rule_type,
                rule_data_json=data_json,
                updated_at=datetime.now(),
            )
            # 注意：saved_rules 没有 (username, rule_type) 的 UNIQUE 约束，
            # 这里退回到"先查再改/插"的语义，和原实现保持一致。
            existing = sess.query(SavedRule).filter_by(
                username=username, rule_type=rule_type).first()
            if existing:
                existing.rule_data_json = data_json
                existing.updated_at = datetime.now()
            else:
                sess.execute(stmt)
            sess.commit()
            return

        existing = sess.query(SavedRule).filter_by(
            username=username, rule_type=rule_type).first()
        if existing:
            existing.rule_data_json = data_json
            existing.updated_at = datetime.now()
            sess.commit()
            return
        sess.add(SavedRule(
            username=username, rule_type=rule_type,
            rule_data_json=data_json))
        try:
            sess.commit()
        except IntegrityError:
            sess.rollback()
            existing = sess.query(SavedRule).filter_by(
                username=username, rule_type=rule_type).first()
            if existing is None:
                raise
            existing.rule_data_json = data_json
            existing.updated_at = datetime.now()
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


_GZ_PREFIX = "gz:"


def _encode_json_blob(raw_json: str) -> str:
    """对较大的 JSON 做 gzip + base64 压缩，小的直接明文存以便调试。"""
    if not raw_json:
        return raw_json
    if len(raw_json) < 4096:
        return raw_json
    compressed = gzip.compress(raw_json.encode("utf-8"), compresslevel=6)
    return _GZ_PREFIX + base64.b64encode(compressed).decode("ascii")


def _decode_json_blob(blob: str | None) -> str | None:
    if not blob:
        return blob
    if blob.startswith(_GZ_PREFIX):
        compressed = base64.b64decode(blob[len(_GZ_PREFIX):])
        return gzip.decompress(compressed).decode("utf-8")
    return blob


def _dataframe_to_records_json(df: pd.DataFrame) -> str:
    data = df.copy()
    for col in data.columns:
        if pd.api.types.is_datetime64_any_dtype(data[col]):
            data[col] = data[col].dt.strftime("%Y-%m-%d")
    return _encode_json_blob(data.to_json(orient="records", force_ascii=False))


def save_import_snapshots(
    username: str,
    delivery_df: pd.DataFrame | None = None,
    payment_df: pd.DataFrame | None = None,
):
    """持久化交货/回款 Excel 解析后的全量明细；仅更新传入的非空表。

    使用 "尝试 INSERT，撞 unique 约束就改 UPDATE" 的双保险，
    避免 Streamlit 反复重跑脚本时多个会话并行触发 UniqueViolation。
    """
    new_delivery = (
        _dataframe_to_records_json(delivery_df)
        if delivery_df is not None and not delivery_df.empty
        else None
    )
    new_payment = (
        _dataframe_to_records_json(payment_df)
        if payment_df is not None and not payment_df.empty
        else None
    )

    sess = get_session()
    try:
        if _is_postgres() and _pg_insert is not None:
            set_cols = {"updated_at": datetime.now()}
            if new_delivery is not None:
                set_cols["delivery_json"] = new_delivery
            if new_payment is not None:
                set_cols["payment_json"] = new_payment
            stmt = _pg_insert(ImportedSnapshot.__table__).values(
                username=username,
                delivery_json=new_delivery,
                payment_json=new_payment,
                updated_at=datetime.now(),
            ).on_conflict_do_update(
                index_elements=["username"], set_=set_cols,
            )
            sess.execute(stmt)
            sess.commit()
            return

        row = sess.query(ImportedSnapshot).filter_by(username=username).first()
        if row is None:
            row = ImportedSnapshot(
                username=username,
                delivery_json=new_delivery,
                payment_json=new_payment,
            )
            sess.add(row)
            try:
                sess.commit()
                return
            except IntegrityError:
                sess.rollback()
                row = sess.query(ImportedSnapshot).filter_by(
                    username=username).first()
                if row is None:
                    raise

        if new_delivery is not None:
            row.delivery_json = new_delivery
        if new_payment is not None:
            row.payment_json = new_payment
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
    # 旧快照可能没有「主合同编号」列，回落到合同编号自身以保证计算链路兼容
    if "合同编号" in df.columns:
        if "主合同编号" not in df.columns:
            df["主合同编号"] = df["合同编号"]
        else:
            df["主合同编号"] = df["主合同编号"].astype("string").str.strip()
            empty_main = df["主合同编号"].isin(["", "nan", "None"]) | df["主合同编号"].isna()
            df.loc[empty_main, "主合同编号"] = df.loc[empty_main, "合同编号"]
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
        delivery_json = _decode_json_blob(row.delivery_json)
        payment_json = _decode_json_blob(row.payment_json)
        delivery = (
            pd.read_json(io.StringIO(delivery_json), orient="records")
            if delivery_json
            else None
        )
        payment = (
            pd.read_json(io.StringIO(payment_json), orient="records")
            if payment_json
            else None
        )
        return _normalize_loaded_df(delivery), _normalize_loaded_df(payment)
    finally:
        sess.close()
