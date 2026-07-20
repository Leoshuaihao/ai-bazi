"""User data persistence — CRUD for chart records, verification records, and sessions."""

from datetime import datetime, timezone, timedelta

from sqlalchemy import select, delete
from sqlalchemy.dialects.sqlite import insert as sqlite_upsert

from orm.db import async_session
from orm.user_data import ChartRecord, VerificationRecord, VerificationSessionModel


async def save_chart_record(user_id: str, birth_info: dict, chart_data: dict) -> str:
    """保存排盘记录，返回 record id"""
    async with async_session() as db:
        record = ChartRecord(
            user_id=user_id,
            birth_info=birth_info,
            chart_data=chart_data,
        )
        db.add(record)
        await db.commit()
        await db.refresh(record)
        return record.id


async def get_user_charts(user_id: str, limit: int = 20) -> list[dict]:
    """获取用户最近的排盘记录"""
    async with async_session() as db:
        stmt = (
            select(ChartRecord)
            .where(ChartRecord.user_id == user_id)
            .order_by(ChartRecord.created_at.desc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        return [r.to_dict() for r in result.scalars()]


async def save_verification_record(
    user_id: str,
    chart_record_id: str | None,
    result: dict,
    history: list
) -> str:
    """保存验证结果，返回 record id"""
    async with async_session() as db:
        record = VerificationRecord(
            user_id=user_id,
            chart_record_id=chart_record_id,
            pattern=result.get("pattern", ""),
            pattern_type=result.get("pattern_type", "正格"),
            yong_shen=result.get("yong_shen", ""),
            five_element=result.get("five_element", ""),
            gong_way=result.get("gong_way", ""),
            confidence=int(result.get("confidence", 0)),
            rounds=int(result.get("rounds", 0)),
            history=history,
        )
        db.add(record)
        await db.commit()
        await db.refresh(record)
        return record.id


async def get_user_verifications(user_id: str, limit: int = 20) -> list[dict]:
    """获取用户最近的验证记录"""
    async with async_session() as db:
        stmt = (
            select(VerificationRecord)
            .where(VerificationRecord.user_id == user_id)
            .order_by(VerificationRecord.created_at.desc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        return [r.to_dict() for r in result.scalars()]


# ---- Session persistence ----

_SESSION_TTL = timedelta(minutes=30)


async def save_verification_session(data: dict):
    """持久化一个验证会话（upsert by session_id）"""
    async with async_session() as db:
        sid = data["session_id"]
        expires = datetime.now(timezone.utc) + _SESSION_TTL

        values = {
            "id": sid,
            "user_id": data.get("user_id"),
            "chart_data": data.get("chart_data", {}),
            "hypotheses": data.get("hypotheses", []),
            "round": data.get("round", 1),
            "history": data.get("history", []),
            "primary_pattern": data.get("primary_pattern", ""),
            "locked": bool(data.get("locked", False)),
            "locked_result": data.get("locked_result"),
            "_prev_top_pattern": data.get("_prev_top_pattern", ""),
            "current_question": data.get("current_question"),
            "expires_at": expires,
            "created_at": datetime.now(timezone.utc),
        }

        stmt = sqlite_upsert(VerificationSessionModel).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["id"],
            set_={k: values[k] for k in values if k != "id"},
        )
        await db.execute(stmt)
        await db.commit()


async def load_verification_session(session_id: str) -> dict | None:
    """从 DB 加载验证会话"""
    async with async_session() as db:
        stmt = select(VerificationSessionModel).where(
            VerificationSessionModel.id == session_id,
            VerificationSessionModel.expires_at > datetime.now(timezone.utc),
        )
        result = await db.execute(stmt)
        model = result.scalar_one_or_none()
        if not model:
            return None
        return model.to_session_dict()


async def delete_expired_sessions():
    """清理过期的验证会话"""
    async with async_session() as db:
        stmt = delete(VerificationSessionModel).where(
            VerificationSessionModel.expires_at <= datetime.now(timezone.utc)
        )
        await db.execute(stmt)
        await db.commit()
