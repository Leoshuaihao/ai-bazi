"""User data persistence models — chart records, verification results, sessions."""

import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy import Column, String, Integer, Boolean, DateTime, JSON, ForeignKey, Index, Text
from orm.db import Base


def _new_id():
    return str(uuid.uuid4())


def _now():
    return datetime.now(timezone.utc)


class ChartRecord(Base):
    """排盘记录 — 用户每次排盘的结果"""
    __tablename__ = "chart_records"

    id = Column(String(36), primary_key=True, default=_new_id)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    birth_info = Column(JSON, nullable=False)    # {year, month, day, hour, minute, city, calendar, gender}
    chart_data = Column(JSON, nullable=False)     # full chart from /api/chart
    created_at = Column(DateTime, nullable=False, default=_now)

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "birth_info": self.birth_info,
            "chart_data": self.chart_data,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class VerificationRecord(Base):
    """验证结果记录 — 断前事验证锁定的格局/用神"""
    __tablename__ = "verification_records"

    id = Column(String(36), primary_key=True, default=_new_id)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    chart_record_id = Column(String(36), ForeignKey("chart_records.id", ondelete="SET NULL"), nullable=True)
    pattern = Column(String(50), nullable=False)
    pattern_type = Column(String(20), nullable=False)
    yong_shen = Column(String(20), nullable=False)
    five_element = Column(String(10), nullable=False)
    gong_way = Column(String(100), nullable=True)
    confidence = Column(Integer, nullable=False)
    rounds = Column(Integer, nullable=False)
    history = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_now)

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "chart_record_id": self.chart_record_id,
            "pattern": self.pattern,
            "pattern_type": self.pattern_type,
            "yong_shen": self.yong_shen,
            "five_element": self.five_element,
            "gong_way": self.gong_way,
            "confidence": self.confidence,
            "rounds": self.rounds,
            "history": self.history,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class VerificationSessionModel(Base):
    """验证会话持久化 — 替代内存 _verification_sessions"""
    __tablename__ = "verification_sessions"

    id = Column(String(36), primary_key=True)  # = session_id
    user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    chart_data = Column(JSON, nullable=False)
    hypotheses = Column(JSON, nullable=False)
    round = Column(Integer, nullable=False, default=1)
    history = Column(JSON, nullable=True)
    primary_pattern = Column(String(50), nullable=True)
    locked = Column(Boolean, nullable=False, default=False)
    locked_result = Column(JSON, nullable=True)
    _prev_top_pattern = Column(String(50), nullable=True)
    current_question = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_now)
    expires_at = Column(DateTime, nullable=False)

    def to_session_dict(self):
        return {
            "session_id": self.id,
            "chart_data": self.chart_data,
            "hypotheses": self.hypotheses,
            "round": self.round,
            "primary_pattern": self.primary_pattern,
            "locked": self.locked,
            "locked_result": self.locked_result,
            "history": self.history or [],
            "current_question": self.current_question,
            "_prev_top_pattern": self._prev_top_pattern,
            "_created_at": self.created_at.timestamp() if self.created_at else 0,
        }
