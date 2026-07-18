"""Invite tracking."""
from datetime import datetime
from sqlalchemy import String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from orm.db import Base


class Invite(Base):
    __tablename__ = "invites"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    inviter_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    invitee_id: Mapped[str | None] = mapped_column(String(36), nullable=True)  # null until invitee registers
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    reward_granted: Mapped[bool] = mapped_column(default=False)  # 是否已发放积分
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # 邀请完成时间
