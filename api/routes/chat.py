"""AI chat route with points gating."""
import os
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from orm.db import get_session
from orm.user import User
from services.gate import require_auth
from services.points import consume_points, get_balance

router = APIRouter(prefix="/api/chat", tags=["chat"])

# DeepSeek 配置
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
CHAT_COST = 5  # 积分/轮


class ChatRequest(BaseModel):
    message: str
    context: str = ""  # 命盘摘要上下文


class ChatResponse(BaseModel):
    reply: str
    trial_remaining: int | None = None  # 试用剩余次数
    points_remaining: int | None = None  # 积分剩余


@router.post("", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    user_id: str = Depends(require_auth),
    db: AsyncSession = Depends(get_session),
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")

    # Check trial first
    if user.trial_chats_remaining > 0:
        user.trial_chats_remaining -= 1
        await db.commit()
        reply = await _call_deepseek(req.message, req.context)
        return ChatResponse(reply=reply, trial_remaining=user.trial_chats_remaining)

    # Consume points
    ok = await consume_points(db, user_id, CHAT_COST, "chat_cost")
    if not ok:
        raise HTTPException(status_code=402, detail="积分不足，请购买积分")

    reply = await _call_deepseek(req.message, req.context)
    pts = await get_balance(db, user_id)
    return ChatResponse(reply=reply, points_remaining=pts.balance)


async def _call_deepseek(message: str, context: str) -> str:
    """Call DeepSeek API."""
    import httpx

    system_prompt = (
        "你是专业的八字命理师，基于用户提供的命盘信息进行分析。"
        "回答要专业但易懂，引用典籍时注明出处。"
        f"用户命盘摘要：{context}" if context else "请先完成排盘和校准。"
    )

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.post(
                f"{DEEPSEEK_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "deepseek-chat",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": message},
                    ],
                    "max_tokens": 1000,
                    "temperature": 0.7,
                },
            )
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except Exception:
            return "抱歉，AI 暂时不可用，请稍后再试。"
