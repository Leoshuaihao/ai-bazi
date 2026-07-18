"""Points API routes."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from orm.db import get_session
from services.gate import require_auth
from services import points as points_svc

router = APIRouter(prefix="/api/points", tags=["points"])


class BalanceResponse(BaseModel):
    balance: int
    gifted_this_month: int


class GiftRequest(BaseModel):
    to_user_id: str
    amount: int


@router.get("/balance", response_model=BalanceResponse)
async def get_balance(
    user_id: str = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    pts = await points_svc.get_balance(db, user_id)
    return BalanceResponse(balance=pts.balance, gifted_this_month=pts.gifted_this_month)


@router.post("/gift")
async def gift_points(
    req: GiftRequest,
    user_id: str = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    ok = await points_svc.gift_points(db, user_id, req.to_user_id, req.amount)
    if not ok:
        raise HTTPException(status_code=400, detail="积分不足或超过本月赠送限额")
    return {"ok": True}
