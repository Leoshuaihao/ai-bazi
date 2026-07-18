"""Invite routes."""
import secrets
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from orm.db import get_session
from orm.invite import Invite
from services.gate import require_auth

router = APIRouter(prefix="/api/invite", tags=["invite"])


class CreateLinkResponse(BaseModel):
    invite_token: str
    invite_url: str


@router.post("/create-link", response_model=CreateLinkResponse)
async def create_invite_link(
    user_id: str = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    token = secrets.token_urlsafe(32)
    invite = Invite(inviter_id=user_id, token=token)
    db.add(invite)
    await db.commit()
    url = f"/invite/{token}"  # 前端路由
    return CreateLinkResponse(invite_token=token, invite_url=url)


@router.get("/track/{token}")
async def track_invite(token: str, db: AsyncSession = Depends(get_session)):
    """Public endpoint: resolve invite token to inviter ID."""
    from sqlalchemy import select
    stmt = select(Invite).where(Invite.token == token)
    result = await db.execute(stmt)
    invite = result.scalars().first()
    if not invite:
        raise HTTPException(status_code=404, detail="邀请链接无效")
    return {"inviter_id": invite.inviter_id}
