"""SQLAlchemy 数据模型"""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Text, DateTime, ForeignKey, Index,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class CalcSession(Base):
    __tablename__ = "calc_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(100), nullable=False)
    name = Column(String(200), default="")
    created_at = Column(DateTime, default=datetime.now)

    results = relationship("SessionResult", back_populates="session",
                           cascade="all, delete-orphan")


class SessionResult(Base):
    __tablename__ = "session_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("calc_sessions.id"), nullable=False)
    result_type = Column(String(50), nullable=False)
    data_json = Column(Text, nullable=False)

    session = relationship("CalcSession", back_populates="results")


class SavedRule(Base):
    __tablename__ = "saved_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(100), nullable=False)
    rule_type = Column(String(50), nullable=False)
    rule_data_json = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # 每个 (用户, 规则类型) 至多一条记录；唯一索引让并发写可靠地走 upsert，
    # 杜绝竞态下产生重复行。对既有库由 database._ensure_saved_rules_unique 迁移补建。
    __table_args__ = (
        Index("uq_saved_rules_user_type", "username", "rule_type", unique=True),
    )


class ContractPrice(Base):
    __tablename__ = "contract_pricing"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(100), nullable=False)
    project_id = Column(String(100), nullable=False)
    guide_price = Column(Float, default=0.0)
    contract_price = Column(Float, default=0.0)
    cost_price = Column(Float, default=0.0)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class ImportedSnapshot(Base):
    """用户最近一次导入的交货/回款全量明细（含全部合同编号及行级数据）"""

    __tablename__ = "imported_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(100), nullable=False, unique=True)
    delivery_json = Column(Text, nullable=True)
    payment_json = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class SharedResult(Base):
    """全工作台共享的「最新一次计算结果」。

    每个 (workspace, result_type) 至多一条记录，保存对应计算结果 DataFrame 的
    JSON。任一账号点「计算」后写入这里，其他账号登录时即可直接载入，无需重算。
    """

    __tablename__ = "shared_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace = Column(String(100), nullable=False, default="__shared__")
    result_type = Column(String(50), nullable=False)
    data_json = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        Index("uq_shared_results_ws_type", "workspace", "result_type", unique=True),
    )
