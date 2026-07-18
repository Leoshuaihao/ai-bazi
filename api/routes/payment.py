"""Payment routes: create order, callback."""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from orm.db import get_session
from orm.order import Order
from services.gate import require_auth
from services.payment import create_payment_link, verify_callback, process_paid_order, PRODUCTS

router = APIRouter(prefix="/api/payment", tags=["payment"])


class CreateOrderRequest(BaseModel):
    product: str  # 'liuyue', 'points_pack', 'hepan'


class CreateOrderResponse(BaseModel):
    order_id: str
    pay_url: str | None


@router.post("/create-order", response_model=CreateOrderResponse)
async def create_order(
    req: CreateOrderRequest,
    user_id: str = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    if req.product not in PRODUCTS:
        raise HTTPException(status_code=400, detail="未知产品")

    product = PRODUCTS[req.product]
    order = Order(
        user_id=user_id,
        product=req.product,
        amount=product["amount"],
    )
    db.add(order)
    await db.commit()
    await db.refresh(order)

    pay_url = await create_payment_link(order)
    return CreateOrderResponse(order_id=order.id, pay_url=pay_url)


@router.post("/callback")
async def payment_callback(request: Request, db: AsyncSession = Depends(get_session)):
    """xorpay 支付回调——无需鉴权（由聚合支付服务器调用）"""
    data = await request.json()
    sign = data.get("sign", "")

    if not verify_callback(data, sign):
        raise HTTPException(status_code=400, detail="签名验证失败")

    order_id = data.get("out_trade_no")
    order = await db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")

    if order.status != "pending":
        return {"status": "ok"}  # 幂等

    await process_paid_order(db, order)
    return {"status": "ok"}
