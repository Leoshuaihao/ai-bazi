"""Auth gate: require_auth + require_entitlement decorators as FastAPI dependencies."""
from fastapi import Header, HTTPException, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from orm.db import get_session
from orm.entitlement import Entitlement
from services.auth import verify_jwt


async def require_auth(authorization: str = Header(None), db: AsyncSession = Depends(get_session)) -> str:
    """Extract and verify JWT. Returns user_id. Raises 401."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="请先登录")
    token = authorization[7:]
    user_id = verify_jwt(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    return user_id


def require_entitlement(feature: str):
    """Factory: returns a dependency that checks user has purchased a feature."""
    async def check(user_id: str = Depends(require_auth), db: AsyncSession = Depends(get_session)) -> str:
        stmt = select(Entitlement).where(
            Entitlement.user_id == user_id,
            Entitlement.feature == feature,
        )
        result = await db.execute(stmt)
        if not result.scalars().first():
            raise HTTPException(status_code=402, detail="请先解锁此功能")
        return user_id
    return check
