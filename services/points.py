"""Points business logic."""
from sqlalchemy.ext.asyncio import AsyncSession
from orm.points import Points, PointsLog


async def get_balance(db: AsyncSession, user_id: str) -> Points:
    """Get or create points record."""
    pts = await db.get(Points, user_id)
    if not pts:
        pts = Points(user_id=user_id, balance=0)
        db.add(pts)
        await db.flush()
    return pts


async def consume_points(db: AsyncSession, user_id: str, amount: int, reason: str) -> bool:
    """Consume points. Returns True if sufficient balance."""
    if amount <= 0:
        return True
    pts = await get_balance(db, user_id)
    if pts.balance < amount:
        return False
    pts.balance -= amount
    db.add(PointsLog(user_id=user_id, amount=-amount, reason=reason))
    await db.commit()
    return True


async def add_points(db: AsyncSession, user_id: str, amount: int, reason: str, related_user_id: str | None = None):
    """Add points."""
    pts = await get_balance(db, user_id)
    pts.balance += amount
    db.add(PointsLog(
        user_id=user_id,
        amount=amount,
        reason=reason,
        related_user_id=related_user_id,
    ))
    await db.commit()


async def gift_points(db: AsyncSession, from_user_id: str, to_user_id: str, amount: int) -> bool:
    """Gift points. Checks monthly limit (50). Returns True on success."""
    if amount <= 0:
        return False
    from_pts = await get_balance(db, from_user_id)
    if from_pts.balance < amount:
        return False
    if from_pts.gifted_this_month + amount > 50:
        return False

    from_pts.balance -= amount
    from_pts.gifted_this_month += amount
    db.add(PointsLog(user_id=from_user_id, amount=-amount, reason="gift_out", related_user_id=to_user_id))

    to_pts = await get_balance(db, to_user_id)
    to_pts.balance += amount
    db.add(PointsLog(user_id=to_user_id, amount=amount, reason="gift_in", related_user_id=from_user_id))

    await db.commit()
    return True
