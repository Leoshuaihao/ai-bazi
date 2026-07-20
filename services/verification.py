"""逐步验证收敛模块 — 子平格局派

新流程核心：
1. 排盘 → 格局分类 → 生成格局假设向量
2. L1: 格局定向问题（静态字典）→ 用户反馈 → 置信度更新
3. L2: 六亲验证（规则引擎）→ 用户反馈
4. L3-L10: AI 生成针对性问题 → 逐轮收敛 → 锁定
   - L3-L4: 关键流年验证
   - L5-L7: 深度维度验证（事业/健康/婚姻/财运）
   - L8-L10: 鉴别性提问
   - AI 不可用时降级到规则引擎

替代旧的固定7题+反馈翻转流程。
"""

import os
import re
from datetime import datetime
from typing import Optional

from rules.pattern import (
    generate_pattern_hypotheses,
    determine_pattern_type,
    update_confidence,
    is_locked,
    get_month_main_ten_god,
)
from rules.wuxing import WUXING_MAP, get_sheng, get_ke, get_i_sheng, get_i_ke
from services.deepseek_client import call_deepseek
from services.user_data import save_verification_session as _save_db_session
from services.user_data import load_verification_session as _load_db_session


# ============================================================
# 验证问题生成
# ============================================================

# L1: 格局定向问题 — 根据月令格局，问最关键的格局特征
PATTERN_L1_QUESTIONS = {
    "正官格": {
        "question": "你工作中是否更倾向于在规则和秩序下发挥，不太喜欢冒险和自由发挥？",
        "explanation": "正官格的人通常对规则和秩序有天然的尊重，做事习惯先想清楚再行动，追求稳定而非冒险。",
        "pattern_feature": "官星当令，为人正直守法，重名节讲信用",
    },
    "七杀格": {
        "question": "你人生中是否经历过较大的压力或挑战，但事后回头看，那些压力反而促成了你的成长？",
        "explanation": "七杀格的人往往早年在竞争和压力中成长，有不服输的韧性。",
        "pattern_feature": "七杀当令，有魄力敢担当，经历磨难后成长",
    },
    "正财格": {
        "question": "你对机会（特别是赚钱机会）的嗅觉是否比身边人敏锐，而且做事更务实注重结果？",
        "explanation": "正财格的人务实稳健，对实际利益敏感，做事脚踏实地。",
        "pattern_feature": "财星当令，务实稳重，善于理财和把握机会",
    },
    "偏财格": {
        "question": "你是否属于那种直觉很强、做事不拘一格、善于抓住机会的类型？",
        "explanation": "偏财格的人思维灵活，善于抓住稍纵即逝的机会，做事不拘泥于常规。",
        "pattern_feature": "偏财当令，灵活变通，善抓机会",
    },
    "正印格": {
        "question": "你是否从小就比较受长辈或老师的喜爱，学习能力较强，也愿意花时间深入钻研一件事？",
        "explanation": "正印格的人天生有贵人缘和求学之心，喜欢知识的积累和沉淀。",
        "pattern_feature": "印星当令，爱学习有贵人，性格温和良善",
    },
    "偏印格": {
        "question": "你是否对某些特定领域有超乎常人的钻研精神，但又容易沉浸在自己的世界里？",
        "explanation": "偏印格的人思维独特，偏才突出，但不一定合群。",
        "pattern_feature": "偏印当令，思维独特，偏才突出",
    },
    "食神格": {
        "question": "你的才华或创意是否在你的生活或工作中占据了重要位置？是否常有人夸你有才华？",
        "explanation": "食神格的人天生有艺术气质和创造力，性格温和乐观。",
        "pattern_feature": "食神当令，有才华创造力，性格温和乐观",
    },
    "伤官格": {
        "question": "你是否属于那种想法很多、不太喜欢被约束、常有出人意料的好点子的人？",
        "explanation": "伤官格的人思维敏捷、创造力强，但有时锋芒毕露。",
        "pattern_feature": "伤官当令，聪明敏捷，创造力强但有时锋芒太露",
    },
    "从弱格": {
        "question": "你是否感觉自己的人生很多时候是被环境推着走，但反而顺势而为的时候结果更好？",
        "explanation": "从弱格的人不宜独立抗衡，顺势而为反而能有不错的成就。",
        "pattern_feature": "日主极弱，顺势从格",
    },
    "专旺格": {
        "question": "你是否有一种强烈的自我意识和主见，做事情喜欢掌控全局而非被人安排？",
        "explanation": "专旺格的人气势强盛，有领导力和主导欲。",
        "pattern_feature": "日主极旺，气势强盛",
    },
}

# L2: 六亲验证 — 根据排盘初判的格局选择验证方向
def _generate_l2_question(chart_data: dict) -> dict:
    """生成第二层验证问题（六亲方向）"""
    four_pillars = chart_data.get("four_pillars", {})
    day_master = chart_data.get("day_master", "")
    dm_stem = day_master[-1] if day_master else ""

    # 年柱信息
    year_pillar = four_pillars.get("year", {})
    year_stem = year_pillar.get("stem", "")
    year_gods = year_pillar.get("ten_gods", [])

    # 比劫数量（从四柱十神统计）
    bijie_count = 0
    for pillar_name in ["year", "month", "day", "hour"]:
        pillar = four_pillars.get(pillar_name, {})
        gods = pillar.get("ten_gods", [])
        for g in gods:
            tg = g.get("ten_god", "") if isinstance(g, dict) else str(g)
            if tg in ("比肩", "劫财"):
                bijie_count += 1

    if bijie_count >= 3:
        return {
            "type": "siblings",
            "question": "你的命局中比肩和劫财较多，是否兄弟姐妹不少，或者你在成长过程中有较多的同龄伙伴协助？",
            "hint": "比劫多通常意味着人际关系网较广",
        }
    elif bijie_count <= 1:
        return {
            "type": "siblings",
            "question": "从命局来看，你的比肩劫财较少，是否兄弟姐妹不多，或者你更习惯独立处理事情？",
            "hint": "比劫少的人通常独立性较强",
        }
    else:
        # 问父母方向
        return {
            "type": "parents",
            "question": "从年柱来看，你早期家庭环境是否对你后来的发展形成了明显影响——无论是助力还是压力？",
            "hint": "年柱反映家庭背景和早年的影响",
        }


# L3+: 关键流年验证
def _generate_l3_question(chart_data: dict, current_hypotheses: list[dict], round_num: int = 3) -> dict:
    """生成第三层验证问题（关键流年），选取能区分当前假设的年份"""
    dayun = chart_data.get("dayun", [])
    if not dayun:
        return _generate_fallback_question()

    # 选取最近的一个大运交接年或冲合年
    current_year = datetime.now().year
    for du in dayun:
        sy = du.get("start_year", 0) if isinstance(du, dict) else getattr(du, "start_year", 0)
        ey = du.get("end_year", 0) if isinstance(du, dict) else getattr(du, "end_year", 0)
        if sy <= current_year <= ey:
            # 根据 round_num 选择不同年份偏移，避免 L3/L4 重复
            offset = 2 if round_num <= 3 else 5
            key_year = sy + offset
            if key_year > current_year:
                key_year = current_year - 1
            # 根据 round_num 使用不同的问题模板
            if round_num <= 3:
                question = f"大约在{key_year}年前后，你是否经历了一次比较明显的转折——比如工作变动、搬家、或重要的人生决定？"
            else:
                question = f"大约在{key_year}年前后，你的事业或工作方向是否发生过明显变化？"
            return {
                "type": "liunian",
                "year": key_year,
                "question": question,
                "hint": f"该年处于{sy}-{ey}年大运区间，是运势变化的关键节点",
            }

    return _generate_fallback_question()


def _generate_deep_question(chart_data: dict, current_hypotheses: list[dict], round_num: int) -> dict:
    """生成深度验证问题（L4-L7），针对事业/健康/婚姻/财运轮流验证"""
    dayun = chart_data.get("dayun", [])
    if not dayun:
        return _generate_fallback_question()

    current_year = datetime.now().year

    # 根据轮次选择不同维度的验证
    dimensions = [
        {"type": "career", "label": "事业变动"},
        {"type": "health", "label": "健康/伤病"},
        {"type": "marriage", "label": "婚恋感情"},
        {"type": "wealth", "label": "财运起伏"},
    ]
    dim = dimensions[(round_num - 5) % len(dimensions)]

    # 找一个对应维度特征明显的流年
    for du in dayun:
        sy = du.get("start_year", 0) if isinstance(du, dict) else getattr(du, "start_year", 0)
        ey = du.get("end_year", 0) if isinstance(du, dict) else getattr(du, "end_year", 0)
        if sy <= current_year <= ey:
            # 在大运中选不同偏移的年份
            offset_map = {5: 3, 6: 5, 7: 7}  # round→偏移年
            offset = offset_map.get(round_num, round_num)
            key_year = min(sy + offset, ey)
            return {
                "type": f"deep_{dim['type']}",
                "year": key_year,
                "question": f"大约在{key_year}年前后，你在{dim['label']}方面是否经历过比较明显的变化？",
                "hint": f"该年份在大运{sy}-{ey}年区间内，对应{dim['label']}的流年引动",
            }

    return _generate_fallback_question()


def _generate_fallback_question() -> dict:
    return {
        "type": "general",
        "question": "回顾你的人生经历，是否有某个明显的时间点让你感觉自己的人生态度或方向发生了改变？",
        "hint": "人生转折点往往与运势变化相关",
    }


# ============================================================
# AI增强问题生成（L3-L10）
# ============================================================

async def _ai_generate_question(chart_data: dict, hypotheses: list[dict], round_num: int, history: list[dict] = None) -> dict | None:
    """用 AI 生成针对性验证问题。L3-L10 统一入口，按层分策略。

    L3-L4: 关键流年验证 — 基于大运流年 + 格局特征
    L5-L7: 深度维度验证 — 事业/健康/婚姻/财运轮流
    L8-L10: 鉴别性提问 — 区分前两名假设
    """
    if not os.getenv("DEEPSEEK_API_KEY"):
        return None

    top_2 = sorted(hypotheses, key=lambda x: x["confidence"], reverse=True)[:2]
    if not top_2:
        return None

    dm = chart_data.get("day_master", "")
    top = top_2[0]
    dayun_info = _format_dayun_for_prompt(chart_data)

    # 三层策略
    if round_num <= 4:
        confirmed, disproved = _format_history_for_prompt(history)
        prompt, system_prompt = _build_l34_prompt(dm, top, dayun_info, confirmed, disproved)
    elif round_num <= 7:
        confirmed, disproved = _format_history_for_prompt(history)
        dim = _get_dimension_name(round_num)
        prompt, system_prompt = _build_l57_prompt(dm, top, dim, dayun_info, confirmed, disproved)
    else:
        confirmed, disproved = _format_history_for_prompt(history)
        prompt, system_prompt = _build_l810_prompt(dm, top_2, confirmed, disproved)

    try:
        content = await call_deepseek(
            prompt=prompt,
            system_prompt=system_prompt,
            timeout=15,
            temperature=0.3,
            max_tokens=200,
        )
        if content and not content.startswith("[API_"):
            return {"type": "ai_diff", "question": content.strip()}
    except Exception:
        pass

    return None


def _build_l34_prompt(dm: str, top: dict, dayun_info: str, confirmed: str = "", disproved: str = "") -> tuple[str, str]:
    """L3-L4: 关键流年验证 prompt"""
    history_context = ""
    if confirmed:
        history_context += f"\n已确认的特征:\n{confirmed}"
    if disproved:
        history_context += f"\n已否定的特征:\n{disproved}"

    prompt = f"""你是子平格局派命理师。正在通过逐步验证确认命盘的格局。

命盘信息：
- 日主: {dm}
- 当前优先格局假设: {top['pattern']}，用神 {top['yong_shen']}({top['five_element']})，做功方式={top['gong_way']}
{dayun_info}{history_context}

请设计一个关键流年验证问题——根据当前大运的运势特征和该格局的命理规律，问一个用户在该大运期间大概率经历过的、能直接回忆的具体事件。

问题要求：
1. 具体到某个年龄段或时间范围
2. 与该格局的典型人生轨迹相关
3. 用户能用「是的/不是/不太确定」直接回答
4. 不要重复已问过的问题，不要验证已经确认过的特征
5. 只输出问题本身，不要JSON不要解释"""

    system_prompt = "你是子平格局派命理师。输出简洁具体的问题，用户能直接回答。不要重复已问过的问题。"
    return prompt, system_prompt


def _build_l57_prompt(dm: str, top: dict, dim: str, dayun_info: str, confirmed: str, disproved: str) -> tuple[str, str]:
    """L5-L7: 深度维度验证 prompt"""
    history_context = ""
    if confirmed:
        history_context += f"\n用户已确认:\n{confirmed}"
    if disproved:
        history_context += f"\n用户已否定:\n{disproved}"

    prompt = f"""你是子平格局派命理师。正在通过逐步验证确认命盘的格局。

命盘信息：
- 日主: {dm}
- 格局: {top['pattern']}，用神 {top['yong_shen']}({top['five_element']})，做功方式={top['gong_way']}
- 当前验证维度: {dim}
{dayun_info}{history_context}

请设计一个 {dim} 维度的深度验证问题。基于该格局和用神在{dim}方面的命理特征，问一个能验证格局是否准确的问题。

问题要求：
1. 必须结合该格局在{dim}维度的典型特征
2. 不能太泛（如"你事业顺利吗"），要具体
3. 用户能用「是的/不是/不太确定」直接回答
4. 只输出问题本身，不要JSON不要解释"""
    
    system_prompt = "你是子平格局派命理师。结合格局特征问具体的维度验证问题。"
    return prompt, system_prompt


def _build_l810_prompt(dm: str, top_2: list[dict], confirmed: str, disproved: str) -> tuple[str, str]:
    """L8-L10: 鉴别性提问 prompt"""
    history_context = ""
    if confirmed:
        history_context += f"\n用户已确认:\n{confirmed}"
    if disproved:
        history_context += f"\n用户已否定:\n{disproved}"

    prompt = f"""你是子平格局派命理师。正在验证一个命盘，当前有两个主要格局假设：

假设A: {top_2[0]['pattern']}，用神{top_2[0]['yong_shen']}({top_2[0]['five_element']})，做功方式={top_2[0]['gong_way']}，置信度={top_2[0]['confidence']}%
假设B: {top_2[1]['pattern']}，用神{top_2[1]['yong_shen']}({top_2[1]['five_element']})，做功方式={top_2[1]['gong_way']}，置信度={top_2[1]['confidence']}%

日主: {dm}{history_context}

请设计一个能区分这两种假设的鉴别性问题——问一个在假设A下成立但在假设B下不成立的命理特征。
必须结合用户已确认和已否定的信息，问出有区分力的关键问题。
只输出问题本身，不要JSON不要解释。"""
    
    system_prompt = "你是子平格局派命理师。输出简洁的问题，能有效区分两种格局假设。"
    return prompt, system_prompt


# ---- 辅助函数 ----

def _get_dimension_name(round_num: int) -> str:
    """L5→事业, L6→健康, L7→婚姻"""
    dims = {5: "事业变动", 6: "健康伤病", 7: "婚恋感情"}
    return dims.get(round_num, "财运起伏")


def _format_history_for_prompt(history: list[dict]) -> tuple[str, str]:
    """从验证历史中提取已确认和已否定的事实，包含问题文本用于去重"""
    if not history:
        return "", ""
    confirmed, disproved = [], []
    for idx, h in enumerate(history):
        role = h.get("role", "user")
        if role != "user":
            continue
        question = h.get("question", "")
        answer = h.get("answer", "")
        note = h.get("note", "")
        line = f"第{h.get('round', idx+1)}轮"
        if question:
            line += f"问:「{question}」"
        line += f"答: {answer}"
        if note:
            line += f"（补充: {note}）"
        if answer == "accurate":
            confirmed.append(line)
        elif answer == "inaccurate":
            disproved.append(line)
    return "\n".join(confirmed), "\n".join(disproved)


def _format_dayun_for_prompt(chart_data: dict) -> str:
    """格式化当前大运信息为 prompt 可用文本"""
    dayun = chart_data.get("dayun", [])
    if not dayun:
        return ""
    current_year = datetime.now().year
    for du in dayun:
        sy = du.get("start_year", 0) if isinstance(du, dict) else getattr(du, "start_year", 0)
        ey = du.get("end_year", 0) if isinstance(du, dict) else getattr(du, "end_year", 0)
        if sy <= current_year <= ey:
            stem = du.get("stem", "?") if isinstance(du, dict) else getattr(du, "stem", "?")
            branch = du.get("branch", "?") if isinstance(du, dict) else getattr(du, "branch", "?")
            tg = du.get("ten_god", "") if isinstance(du, dict) else getattr(du, "ten_god", "")
            tg_str = f"，十神={tg}" if tg else ""
            return f"- 当前大运: {stem}{branch}（{sy}-{ey}年{tg_str}）\n- 当前年份: {current_year}"
    return ""


# ============================================================
# 会话管理
# ============================================================

_verification_sessions = {}
_SESSION_TTL_SECONDS = 1800  # 30分钟过期


def _cleanup_expired_sessions():
    """清理过期的验证会话，防止内存泄漏"""
    now = datetime.now().timestamp()
    expired = [
        sid for sid, s in _verification_sessions.items()
        if now - s.get("_created_at", 0) > _SESSION_TTL_SECONDS
    ]
    for sid in expired:
        del _verification_sessions[sid]


def init_verification(chart_data: dict, user_id: str = None) -> dict:
    """初始化验证会话

    Args:
        chart_data: 完整排盘数据
        user_id: 可选，登录用户的 ID

    Returns:
        { "session_id": str, "hypotheses": [...], "round": 0, "question": {...} }
    """
    import uuid
    import asyncio

    _cleanup_expired_sessions()

    session_id = str(uuid.uuid4())
    dm_stem = _extract_day_master_stem(chart_data)
    month_branch = _extract_month_branch(chart_data)
    strength_detail = chart_data.get("strength_detail", {})

    hypotheses = generate_pattern_hypotheses(dm_stem, month_branch, strength_detail)
    primary_pattern = determine_pattern_type(dm_stem, month_branch)

    # 生成第一条问题
    l1 = PATTERN_L1_QUESTIONS.get(primary_pattern, PATTERN_L1_QUESTIONS.get("正官格", {}))
    first_question = {
        "round": 1,
        "layer": "L1",
        "question": l1.get("question", "请描述一下你的性格特点？"),
        "explanation": l1.get("explanation", ""),
        "pattern_feature": l1.get("pattern_feature", ""),
        "target_pattern": primary_pattern,
        "options": ["很像", "有点出入", "完全不像"],
    }

    session = {
        "session_id": session_id,
        "user_id": user_id,
        "chart_data": chart_data,
        "hypotheses": hypotheses,
        "round": 1,
        "primary_pattern": primary_pattern,
        "locked": False,
        "history": [],
        "current_question": first_question,
        "_created_at": datetime.now().timestamp(),
    }

    _verification_sessions[session_id] = session

    # 异步持久化到 DB（fire-and-forget，不阻塞返回）
    if user_id:
        try:
            asyncio.ensure_future(_save_db_session(session))
        except Exception:
            pass

    return {
        "session_id": session_id,
        "hypotheses": hypotheses,
        "question": first_question,
    }


async def process_verification(session_id: str, answer: str, note: str = "") -> dict:
    """处理用户反馈，返回下一步

    Returns:
        若未锁定: { "locked": False, "question": {...}, "hypotheses": [...] }
        若已锁定: { "locked": True, "result": {...}, "hypotheses": [...] }
    """
    # 标准化中文答案到英文枚举（防御性，main.py 已做第一层映射）
    _ANSWER_NORMALIZE = {
        "很像": "accurate", "有点出入": "partial", "完全不像": "inaccurate",
        "是的": "accurate", "不太确定": "partial", "不是": "inaccurate",
    }
    answer = _ANSWER_NORMALIZE.get(answer, answer)

    _cleanup_expired_sessions()
    session = _verification_sessions.get(session_id)
    if not session:
        return {"error": "会话不存在或已过期"}

    chart_data = session.get("chart_data", {})
    hypotheses = session.get("hypotheses", [])
    current_question = session.get("current_question", {})

    # 1. 更新置信度
    q_context = {"pattern": current_question.get("target_pattern", session.get("primary_pattern", ""))}
    updated = update_confidence(hypotheses, answer, q_context)

    # 2. 记录历史
    session["history"].append({
        "round": session["round"],
        "question": current_question.get("question", ""),
        "answer": answer,
        "note": note,
    })

    # 3. 检查是否收敛
    sorted_h = sorted(updated, key=lambda x: x["confidence"], reverse=True)

    # 收敛条件（最少5轮后才允许锁定）：
    # a) 置信度 ≥ 70% 且领先第二 ≥ 20%
    # b) 连续2轮首名不变且 ≥ 60%
    MIN_ROUNDS = 5
    MAX_ROUNDS = 10

    locked_result = None
    if session["round"] >= MIN_ROUNDS and sorted_h[0]["confidence"] >= 70:
        second = sorted_h[1]["confidence"] if len(sorted_h) > 1 else 0
        if sorted_h[0]["confidence"] - second >= 20:
            locked_result = sorted_h[0]

    if not locked_result and session["round"] >= MIN_ROUNDS and sorted_h[0]["confidence"] >= 60:
        # 检查连续2轮首名不变
        prev_top = session.get("_prev_top_pattern", "")
        if prev_top and prev_top == sorted_h[0]["pattern"]:
            locked_result = sorted_h[0]

    # 4. 强制锁定条件（最大10轮）
    if session["round"] >= MAX_ROUNDS and not locked_result:
        locked_result = sorted_h[0]  # 第10轮强制以最高置信度锁定

    # 5. 记录本轮首名，供下轮收敛判断
    session["_prev_top_pattern"] = sorted_h[0]["pattern"]

    session["hypotheses"] = sorted_h
    session["round"] += 1

    # 持久化到 DB（fire-and-forget）
    if session.get("user_id"):
        import asyncio
        try:
            asyncio.ensure_future(_save_db_session(session))
        except Exception:
            pass

    if locked_result:
        session["locked"] = True
        return {
            "locked": True,
            "rounds": session["round"] - 1,
            "result": {
                "pattern": locked_result["pattern"],
                "yong_shen": locked_result["yong_shen"],
                "five_element": locked_result["five_element"],
                "gong_way": locked_result["gong_way"],
                "confidence": locked_result["confidence"],
                "pattern_type": locked_result.get("pattern_type", "正格"),
            },
            "hypotheses": sorted_h,
        }

    # 6. 生成下一条问题（L3起优先AI，降级规则引擎）
    round_num = session["round"]
    history = session.get("history", [])
    
    if round_num == 2:
        # L2: 六亲验证（规则引擎）
        next_q = _generate_l2_question(chart_data)
        next_q["round"] = round_num
        next_q["layer"] = "L2"
        next_q["options"] = ["很像", "有点出入", "完全不像"]
        next_q["target_pattern"] = sorted_h[0]["pattern"]
    elif round_num >= 3:
        # L3-L10: 优先AI生成
        ai_q = await _ai_generate_question(chart_data, sorted_h, round_num, history)
        if ai_q:
            next_q = ai_q
            next_q["round"] = round_num
            next_q["layer"] = f"L{round_num}"
            next_q["options"] = ["是的", "不太确定", "不是"] if round_num >= 3 else ["很像", "有点出入", "完全不像"]
            next_q["target_pattern"] = sorted_h[0]["pattern"]
        else:
            # 降级到规则引擎
            if round_num <= 4:
                next_q = _generate_l3_question(chart_data, sorted_h, round_num)
            elif round_num <= 7:
                next_q = _generate_deep_question(chart_data, sorted_h, round_num)
            else:
                next_q = _generate_fallback_question()
            next_q["round"] = round_num
            next_q["layer"] = f"L{round_num}"
            next_q["options"] = ["是的", "不太确定", "不是"]
            next_q["target_pattern"] = sorted_h[0]["pattern"]

    session["current_question"] = next_q

    return {
        "locked": False,
        "question": next_q,
        "hypotheses": sorted_h,
    }


# ============================================================
# 辅助函数
# ============================================================

def _extract_day_master_stem(chart_data: dict) -> str:
    dm = chart_data.get("day_master", "")
    # day_master format: "丁火" → extract "丁"
    return dm[0] if dm else "甲"

def _extract_month_branch(chart_data: dict) -> str:
    fp = chart_data.get("four_pillars", {})
    month = fp.get("month", {})
    return month.get("branch", "子")

def get_session(session_id: str) -> dict | None:
    _cleanup_expired_sessions()
    s = _verification_sessions.get(session_id)
    if s:
        return s
    # 内存中没找到，尝试从 DB 恢复
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # 在 async 上下文中，创建 task 异步查询
            future = asyncio.ensure_future(_load_db_session(session_id))
            # 不能 await，也不能阻塞 — 仅作标识：调用方应为 async
            return None  # 调用方需自行处理
        else:
            s = loop.run_until_complete(_load_db_session(session_id))
            if s:
                _verification_sessions[session_id] = s
            return s
    except Exception:
        pass
    return None


async def get_session_async(session_id: str) -> dict | None:
    """异步版 get_session，支持 DB 恢复"""
    _cleanup_expired_sessions()
    s = _verification_sessions.get(session_id)
    if s:
        return s
    s = await _load_db_session(session_id)
    if s:
        _verification_sessions[session_id] = s
    return s
