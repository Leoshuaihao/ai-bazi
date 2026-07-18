"""Order model for payment tracking."""
import uuid
from datetime import datetime
from sqlalchemy import String, Integer, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from orm.db import Base


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    product: Mapped[str] = mapped_column(String(50), nullable=False)  # 'liuyue', 'points_pack', 'hepan'
    amount: Mapped[int] = mapped_column(Integer, nullable=False)  # 单位：分
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, paid, expired, cancelled
    payment_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)  # 聚合支付订单号
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
