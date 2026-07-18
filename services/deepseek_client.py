"""统一的 DeepSeek API 调用封装

提供 call_deepseek() 函数，统一处理 API Key 检查、请求发送、超时和错误处理。
有 Key 时调用 AI 并返回响应文本，无 Key 时返回空字符串。
"""

import os
import httpx


async def call_deepseek(
    prompt: str,
    system_prompt: str = "",
    timeout: int = 60,
    model: str = "deepseek-chat",
    temperature: float = 0.5,
    max_tokens: int = 2000,
) -> str:
    """统一的 DeepSeek API 调用。

    Args:
        prompt: 用户提示词
        system_prompt: 系统提示词（可选，为空时不发送 system message）
        timeout: 请求超时时间（秒），默认 60
        model: 模型名称，默认 deepseek-chat
        temperature: 采样温度，默认 0.5
        max_tokens: 最大输出 token 数，默认 2000

    Returns:
        AI 返回的文本内容；无 API Key 时返回空字符串；
        超时/错误时返回以 [API_ 开头的错误标记字符串
    """
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        return ""

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                "https://api.deepseek.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
    except httpx.TimeoutException:
        return "[API_TIMEOUT]"
    except httpx.HTTPStatusError as e:
        return f"[API_ERROR: HTTP {e.response.status_code}]"
    except Exception:
        return "[API_ERROR]"
