"""Points balance and transaction log."""
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from orm.db import Base


class Points(Base):
    __tablename__ = "points"

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    balance: Mapped[int] = mapped_column(Integer, default=0)
    gifted_this_month: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class PointsLog(Base):
    __tablename__ = "points_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)  # 正=获得，负=消耗
    reason: Mapped[str] = mapped_column(String(50), nullable=False)  # 'purchase', 'invite', 'daily', 'gift_in', 'gift_out', 'chat_cost'
    related_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)  # 赠送/邀请相关用户
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
