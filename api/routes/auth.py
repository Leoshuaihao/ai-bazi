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
    if not await verify_code(db, req.phone, req.code):
        raise HTTPException(status_code=400, detail="验证码错误或已过期")

    user = await get_or_create_user(db, req.phone)
    token = create_jwt(user.id)

    return LoginResponse(
        token=token,
        user=UserResponse(
            id=user.id,
            phone=user.phone,
            trial_chats_remaining=user.trial_chats_remaining,
        ),
    )
