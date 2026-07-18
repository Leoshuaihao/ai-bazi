"""Auth routes: register, login, token."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from orm.db import get_session
from services.auth import (
    create_and_send_code, verify_code, get_or_create_user,
    register_user, login_user, create_jwt, verify_jwt,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ── Models ──

class RegisterRequest(BaseModel):
    username: str
    password: str

    @field_validator("username")
    @classmethod
    def username_valid(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 2 or len(v) > 30:
            raise ValueError("用户名 2-30 个字符")
        return v

    @field_validator("password")
    @classmethod
    def password_valid(cls, v: str) -> str:
        if len(v) < 6 or len(v) > 64:
            raise ValueError("密码 6-64 个字符")
        return v


class PasswordLoginRequest(BaseModel):
    username: str
    password: str


class SendCodeRequest(BaseModel):
    phone: str


class SendCodeResponse(BaseModel):
    ok: bool
    cooldown: int | None = None


class LoginRequest(BaseModel):
    phone: str
    code: str


class UserResponse(BaseModel):
    id: str
    username: str
    phone: str | None = None
    trial_chats_remaining: int


class LoginResponse(BaseModel):
    token: str
    user: UserResponse


# ── Helpers ──

def _user_response(user) -> UserResponse:
    return UserResponse(
        id=user.id,
        username=user.username,
        phone=getattr(user, "phone", None),
        trial_chats_remaining=user.trial_chats_remaining,
    )


# ── Password Auth (primary) ──

@router.post("/register", response_model=LoginResponse)
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_session)):
    user = await register_user(db, req.username, req.password)
    if not user:
        raise HTTPException(status_code=409, detail="用户名已被占用")
    token = create_jwt(user.id)
    return LoginResponse(token=token, user=_user_response(user))


@router.post("/login-password", response_model=LoginResponse)
async def login_password(req: PasswordLoginRequest, db: AsyncSession = Depends(get_session)):
    user = await login_user(db, req.username, req.password)
    if not user:
        raise HTTPException(status_code=400, detail="用户名或密码错误")
    token = create_jwt(user.id)
    return LoginResponse(token=token, user=_user_response(user))


@router.get("/me", response_model=UserResponse)
async def me(token: str, db: AsyncSession = Depends(get_session)):
    user_id = verify_jwt(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    from sqlalchemy import select
    from orm.user import User
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return _user_response(user)


# ── Phone Auth (legacy, kept for future SMS) ──

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
    return LoginResponse(token=token, user=_user_response(user))
