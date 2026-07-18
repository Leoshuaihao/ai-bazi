"""Auth routes: send-code, login."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from orm.db import get_session
from services.auth import create_and_send_code, verify_code, get_or_create_user, create_jwt

router = APIRouter(prefix="/api/auth", tags=["auth"])


class SendCodeRequest(BaseModel):
    phone: str


class SendCodeResponse(BaseModel):
    ok: bool
    cooldown: int | None = None  # remaining cooldown seconds


class LoginRequest(BaseModel):
    phone: str
    code: str


class UserResponse(BaseModel):
    id: str
    phone: str
    trial_chats_remaining: int


class LoginResponse(BaseModel):
    token: str
    user: UserResponse


@router.post("/send-code", response_model=SendCodeResponse)
async def send_code(req: SendCodeRequest, db: AsyncSession = Depends(get_session)):
    code = await create_and_send_code(db, req.phone)
    if code is None:
        return SendCodeResponse(ok=False, cooldown=60)
    return SendCodeResponse(ok=True)


@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_session)):
    # 开发模式：万能验证码 990204
    is_dev_master = (req.code == "990204")
    if not is_dev_master and not await verify_code(db, req.phone, req.code):
        raise HTTPException(status_code=400, detail="验证码错误或已过期")

    user = await get_or_create_user(db, req.phone)
    token = create_jwt(user.id)

    # 开发模式：自动赋予所有权限
    if is_dev_master:
        from sqlalchemy import select
        from orm.entitlement import Entitlement
        for feat in ("liuyue", "liunian", "hepan"):
            stmt = select(Entitlement).where(Entitlement.user_id == user.id, Entitlement.feature == feat)
            existing = (await db.execute(stmt)).scalars().first()
            if not existing:
                db.add(Entitlement(user_id=user.id, feature=feat))
        # 给 1000 积分
        from orm.points import Points
        pts = await db.get(Points, user.id)
        if not pts:
            pts = Points(user_id=user.id, balance=1000)
            db.add(pts)
        else:
            pts.balance = max(pts.balance, 1000)
        await db.commit()

    return LoginResponse(
        token=token,
        user=UserResponse(
            id=user.id,
            phone=user.phone,
            trial_chats_remaining=user.trial_chats_remaining,
        ),
    )


@router.get("/dev-code/{phone}")
async def get_dev_code(phone: str, db: AsyncSession = Depends(get_session)):
    """开发模式：获取最新验证码（生产环境需删除）"""
    from sqlalchemy import select
    from orm.user import VerificationCode
    stmt = select(VerificationCode).where(
        VerificationCode.phone == phone,
        VerificationCode.used == False,
    ).order_by(VerificationCode.id.desc())
    result = await db.execute(stmt)
    vc = result.scalars().first()
    if vc:
        return {"code": vc.code}
    return {"code": "none"}
