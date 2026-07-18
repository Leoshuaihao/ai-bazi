"""Entitlement / feature-gate model."""
from datetime import datetime
from sqlalchemy import String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from orm.db import Base


class Entitlement(Base):
    __tablename__ = "entitlements"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    feature: Mapped[str] = mapped_column(String(50), nullable=False)  # 'liuyue', 'hepan'
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
