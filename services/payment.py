"""Payment service: order creation, callback verification, fulfillment."""
import hashlib
import hmac
import os
import httpx
from sqlalchemy import update as sa_update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from orm.order import Order
from orm.entitlement import Entitlement
from orm.points import Points, PointsLog

# xorpay 聚合支付配置（示例——替换为实际商户参数）
XORPAY_APP_ID = os.getenv("XORPAY_APP_ID", "")
XORPAY_API_SECRET = os.getenv("XORPAY_API_SECRET", "")
XORPAY_BASE_URL = "https://xorpay.com/api"

# 产品定义
PRODUCTS = {
    "liuyue": {"name": "流月详批", "amount": 990, "points": 100},  # 金额单位：分
    "points_pack": {"name": "积分补充包", "amount": 690, "points": 100},
    "hepan": {"name": "合盘", "amount": 1800, "points": 0},
}


async def create_order(db: AsyncSession, user_id: str, product: str, amount: int | None = None) -> Order:
    """Create a pending order. Amount defaults to product price if not given."""
    if product not in PRODUCTS:
        raise ValueError(f"Unknown product: {product}")
    if amount is None:
        amount = PRODUCTS[product]["amount"]
    order = Order(user_id=user_id, product=product, amount=amount, status="pending")
    db.add(order)
    await db.commit()
    await db.refresh(order)
    return order


async def create_payment_link(order: Order, return_url: str = "") -> str | None:
    """Call xorpay to create a payment link. Returns payment URL or None."""
    payload = {
        "app_id": XORPAY_APP_ID,
        "out_trade_no": order.id,
        "total_amount": order.amount,
        "subject": PRODUCTS.get(order.product, {}).get("name", "命理服务"),
        "return_url": return_url,
    }
    # Sign the payload
    payload["sign"] = _sign(payload, XORPAY_API_SECRET)

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.post(f"{XORPAY_BASE_URL}/pay", json=payload)
            data = resp.json()
            if data.get("code") == 0:
                return data.get("data", {}).get("pay_url")
        except Exception:
            pass
    return None


def verify_callback(data: dict, sign: str) -> bool:
    """Verify xorpay callback signature."""
    expected = _sign(data, XORPAY_API_SECRET)
    return hmac.compare_digest(expected, sign)


async def process_paid_order(db: AsyncSession, order: Order):
    """Fulfill a paid order: grant entitlements + points."""
    if order.status == "paid":
        return
    order.status = "paid"
    from datetime import datetime
    order.paid_at = datetime.utcnow()

    product = PRODUCTS.get(order.product, {})
    points_to_add = product.get("points", 0)

    # Grant entitlement for the product (except points_pack which only adds points)
    if order.product in ("liuyue", "hepan"):
        db.add(Entitlement(user_id=order.user_id, feature=order.product))

    # Add points
    if points_to_add > 0:
        pts = await db.get(Points, order.user_id)
        if not pts:
            pts = Points(user_id=order.user_id, balance=0)
            db.add(pts)
            try:
                async with db.begin_nested():  # savepoint
                    await db.flush()
            except IntegrityError:
                # Another concurrent request created the Points row — we got it
                pts = await db.get(Points, order.user_id)
        await db.execute(
            sa_update(Points).where(Points.user_id == order.user_id).values(
                balance=Points.balance + points_to_add
            )
        )
        await db.refresh(pts)
        db.add(PointsLog(
            user_id=order.user_id,
            amount=points_to_add,
            reason="purchase",
        ))

    await db.commit()


def _sign(data: dict, secret: str) -> str:
    """Sign data with MD5 (common for Chinese payment providers)."""
    # Remove sign key if present, sort keys, concat, append secret, MD5
    items = sorted([(k, v) for k, v in data.items() if k != "sign"])
    raw = "&".join([f"{k}={v}" for k, v in items]) + secret
    return hashlib.md5(raw.encode()).hexdigest()
