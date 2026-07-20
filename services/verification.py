"""逐步验证收敛模块 V4 — LLM 100% 介入

V4核心: LLM驱动全流程对话, 不可用时降级到V3静态模式
"""

import os
import json
import uuid
import asyncio
from datetime import datetime

from rules.pattern import (
    determine_pattern_type,
    detect_ganzhi_touchu,
    detect_zhi_heju,
    resolve_pending_heju,
    judge_wangshuai_level,
    check_purity,
    check_jiuying,
    find_wuxing_clash,
    get_tongguan_wuxing,
    PATTERN_YONGSHEN,
    _TG_TO_PATTERN,
    _resolve_five_element,
    _calc_ten_god,
    _get_gong_way,
    WUXING_MAP,
)
from services.deepseek_client import call_deepseek
from services.user_data import save_verification_session as _save_db_session
from services.user_data import load_verification_session as _load_db_session

# ============================================================
# LLM 系统提示词
# ============================================================

SYSTEM_PROMPT = """你是一位严格遵循《子平真诠》《滴天髓》《穷通宝鉴》体系的子平派命理师。

核心原则:
- "八字用神，专求月令" — 格局由月令地支藏干本气决定
- "财官印食顺用，杀伤枭刃逆用" — 用神选择遵循顺用/逆用规则
- "透干会支，乃为真用" — 天干透出和地支三合三会可以改变用神
- "有情无情，有力无力" — 格局品质由用神是否有生扶保护和通根得地决定
- "救应两字，乃命学精华所在" — 格局被克时看是否有制忌护用

规则:
1. 每条问题基于命盘数据和典籍理论
2. 用户可能不理解命理术语，用生活化语言
3. 用户有复杂真实情况，不要强迫选不合适选项
4. 用户持续否定时重新审视月令是否被冲/合/压制
5. 保持自然对话感"""


def _has_llm():
    return bool(os.getenv("DEEPSEEK_API_KEY"))


async def _llm_ask(system: str, prompt: str, max_tokens: int = 300) -> str | None:
    """调用 LLM，失败返回 None"""
    try:
        content = await call_deepseek(prompt=prompt, system_prompt=system,
                                       timeout=12, temperature=0.5, max_tokens=max_tokens)
        if content and not content.startswith("[API_"):
            return content
    except Exception:
        pass
    return None


# ============================================================
# L1 格局特征问题（V3升级：区分旺衰两版）
# ============================================================
PATTERN_L1_QUESTIONS = {
    "正官格": {
        "strong": {"question": "你工作中是否更倾向于在规则和秩序下发挥，不太喜欢冒险和自由发挥？",
                   "explanation": "正官格身旺者重视规则带来的安全感和成就。",
                   "pattern_feature": "官星当令，为人正直守法，重名节讲信用"},
        "weak": {"question": "你是否在工作中感到规则和制度对你有较大的约束，想突破又常常被拉回来？",
                 "explanation": "正官格身弱者容易被外界制度压制，需要身旺方能承载官贵。",
                 "pattern_feature": "官星当令但日主偏弱，制度感强但承载吃力"},
    },
    "七杀格": {
        "strong": {"question": "你人生中是否经历过较大的压力或挑战，但事后回头看，那些压力反而促成了你的成长？",
                   "explanation": "七杀格身旺者把压力当跳板，愈挫愈勇。",
                   "pattern_feature": "七杀当令身旺，有魄力敢担当，经历磨难后成长"},
        "weak": {"question": "你是否长期承受比较大的压力或制约，感觉自己被压得比较紧，很多事想做但力不从心？",
                 "explanation": "七杀格身弱者杀星攻身，需要印星化杀或食神制杀来缓解。",
                 "pattern_feature": "七杀当令但日主偏弱，杀旺攻身，需制化方显其功"},
    },
    "正财格": {
        "strong": {"question": "你对机会特别是赚钱机会的嗅觉是否敏锐，做事务实注重结果？",
                   "explanation": "正财格身旺者能驾驭财富，务实稳重。",
                   "pattern_feature": "财星当令身旺，务实稳重，善于理财和把握机会"},
        "weak": {"question": "你是否对赚钱机会很在意，但常常感觉自己抓不住、或者机会来了又错过了？",
                 "explanation": "正财格身弱者财多身弱，能看见但难抓住。",
                 "pattern_feature": "财星当令但日主偏弱，财多身弱，需比劫分财或印星扶持"},
    },
    "偏财格": {
        "strong": {"question": "你是否属于那种直觉很强、做事不拘一格、善于抓住稍纵即逝机会的类型？",
                   "explanation": "偏财格身旺者灵活善变，善于抓住商业机会。",
                   "pattern_feature": "偏财当令身旺，灵活变通，善抓机会"},
        "weak": {"question": "你是否经常有一些好想法或看到好机会，但落地执行的时候却总是差一口气？",
                 "explanation": "偏财格身弱者想法多变但执行力跟不上。",
                 "pattern_feature": "偏财当令但日主偏弱，机会多而承载难"},
    },
    "正印格": {
        "strong": {"question": "你是否从小就受长辈喜爱，学习能力较强，愿意花时间深入钻研一件事？",
                   "explanation": "正印格身旺者贵人运好，学有所成。",
                   "pattern_feature": "印星当令身旺，爱学习有贵人，性格温和良善"},
        "weak": {"question": "你是否渴望有好的引路人来指点自己，但总觉得遇到的人帮助力度不够、或者一直没有遇到对的人？",
                 "explanation": "正印格身弱者需要印生扶但印星无力，求学之路多波折。",
                 "pattern_feature": "印星当令但日主偏弱，贵人助力有但不够"},
    },
    "偏印格": {
        "strong": {"question": "你是否对某些特定领域有超乎常人的钻研精神，但容易沉浸在自己的世界里？",
                   "explanation": "偏印格身旺者偏才突出，思维独特。",
                   "pattern_feature": "偏印当令身旺，思维独特，偏才突出"},
        "weak": {"question": "你是否对某个领域有深入兴趣，但感觉外界不太理解你、或者你的想法很难得到认可？",
                 "explanation": "偏印格身弱者才华有但被埋没的感觉较强。",
                 "pattern_feature": "偏印当令但日主偏弱，独特才华难被认可"},
    },
    "食神格": {
        "strong": {"question": "你的才华创意在生活或工作中是否占据了重要位置，常有人夸你有才华？",
                   "explanation": "食神格身旺者创造力和艺术感自然流露。",
                   "pattern_feature": "食神当令身旺，有才华创造力，性格温和乐观"},
        "weak": {"question": "你是否内心其实有很多才华和想法，但总觉得表达出来或者把它们变成实际的东西比较困难？",
                 "explanation": "食神格身弱者才华内秀但输出困难。",
                 "pattern_feature": "食神当令但日主偏弱，才华内秀而输出不足"},
    },
    "伤官格": {
        "strong": {"question": "你是否属于想法很多、不喜被约束、常有出人意料的好点子的人？",
                   "explanation": "伤官格身旺者思维敏捷，锋芒毕露。",
                   "pattern_feature": "伤官当令身旺，聪明敏捷，创造力强但有时锋芒太露"},
        "weak": {"question": "你是否有很多想法但常常被人否定或环境不允许你做出来，导致内心比较压抑？",
                 "explanation": "伤官格身弱者才华被压，容易愤世嫉俗。",
                 "pattern_feature": "伤官当令但日主偏弱，想法多而施展难"},
    },
    "从弱格": {
        "strong": {"question": "你是否感觉自己的人生很多时候是被环境推着走，但反而顺势而为的时候结果更好？",
                   "explanation": "从弱格的人不宜独立抗衡，顺势而为反而能有不错的成就。",
                   "pattern_feature": "日主极弱，顺势从格"},
        "weak": {"question": "你是否感觉自己的人生很多时候是被环境推着走，但反而顺势而为的时候结果更好？",
                 "explanation": "从弱格本身为极弱，只有一个版本。",
                 "pattern_feature": "日主极弱，顺势从格"},
    },
    "专旺格": {
        "strong": {"question": "你是否有一种强烈的自我意识和主见，做事情喜欢掌控全局而非被人安排？",
                   "explanation": "专旺格的人气势强盛，有领导力和主导欲。",
                   "pattern_feature": "日主极旺，气势强盛"},
        "weak": {"question": "你是否有一种强烈的自我意识和主见，做事情喜欢掌控全局而非被人安排？",
                 "explanation": "专旺格本身为极旺，只有一个版本。",
                 "pattern_feature": "日主极旺，气势强盛"},
    },
}


def _get_l1_question(pattern: str, wangshuai_level: str) -> dict:
    """根据旺衰选择L1问题版本"""
    entry = PATTERN_L1_QUESTIONS.get(pattern, PATTERN_L1_QUESTIONS.get("正官格", {}))
    is_strong = wangshuai_level in ("极旺", "身旺", "中和")
    if isinstance(entry, dict) and "strong" in entry:
        return entry["strong"] if is_strong else entry["weak"]
    return entry  # 兼容旧格式

# 诊断问题模板
DIAGNOSIS_QUESTIONS = {
    "D1_chong": "你是否觉得自己性格或人生方向发生过比较突然的转变？",
    "D2_he": "你是否在不同环境或人生阶段下，会表现出完全不同的性格特质？",
    "D4_jiuying": "你是否觉得自己有些潜力被某些因素限制住了，没有完全发挥出来？",
    "D5_time": "前面几个方向似乎都不太符合。你的出生时间是准确的吗？",
}

# 品质问题模板
QUALITY_QUESTIONS = {
    "youqing": {
        "食神": "在压力大的时候，你是否有某种宣泄或舒缓的方式——比如创作、运动，或者其他让你释放的渠道——来帮你把压力转化为动力？",
        "伤官": "在压力大的时候，你是否有某种宣泄或舒缓的方式——比如创作、运动，或者其他让你释放的渠道——来帮你把压力转化为动力？",
        "正印": "你是否容易得到长辈或老师的欣赏和帮助，让你在困难时有人指点？",
        "偏印": "你是否容易得到长辈或老师的欣赏和帮助，让你在困难时有人指点？",
        "比肩": "你是否经常能得到朋友或同事的实质性帮助？",
        "劫财": "你是否经常能得到朋友或同事的实质性帮助？",
        "正财": "你是否有稳定的财源或资源渠道来支撑你的发展？",
        "偏财": "你是否有稳定的财源或资源渠道来支撑你的发展？",
        "正官": "你是否有权威人士或制度在背后支持你的发展？",
        "七杀": "你是否有权威人士或制度在背后支持你的发展？",
    },
    "youli": {
        "食神": "你的才华或创造力是否在实际生活或工作中产生了比较实在的、别人能看到的成果——而不是只停留在想法或爱好层面？",
        "伤官": "你的才华或创造力是否在实际生活或工作中产生了比较实在的、别人能看到的成果——而不是只停留在想法或爱好层面？",
        "正印": "你的学习和积累是否转化为了实际的能力提升或职业发展？",
        "偏印": "你的学习和积累是否转化为了实际的能力提升或职业发展？",
        "比肩": "你的朋友或同伴对你的人生产生了实质性的积极影响吗？",
        "劫财": "你的朋友或同伴对你的人生产生了实质性的积极影响吗？",
        "正财": "你的理财能力是否给你带来了相当的财富积累？",
        "偏财": "你的理财能力是否给你带来了相当的财富积累？",
        "正官": "规则和秩序是否真正让你在事业上获得了进步？",
        "七杀": "规则和秩序是否真正让你在事业上获得了进步？",
    },
}

# 用神验证问题维度
YONGSHEN_DIMENSIONS = {
    "正印": "贵人学历", "偏印": "偏门专长",
    "比肩": "朋辈协作", "劫财": "竞争人脉",
    "食神": "才华创作", "伤官": "聪明表达",
    "正财": "理财务实", "偏财": "商业直觉",
    "正官": "规则纪律", "七杀": "决断魄力",
}

YONGSHEN_QUESTIONS = {
    "正印": "你在学业上是否容易得到老师或长辈的欣赏和帮助？",
    "偏印": "你是否对某个特殊领域有超越常人的钻研天赋？",
    "比肩": "你是否常能得到朋友或同事的实质性帮助？",
    "劫财": "你是否在人际网络中获益较多，善于借助他人力量？",
    "食神": "你的创造才能或手艺是否在生活中给你带来了实质性的收益或认可？",
    "伤官": "你是否常能靠自己的聪明才智或表达能力脱颖而出？",
    "正财": "你对金钱和资源的把控是否比身边人更稳更准？",
    "偏财": "你是否容易抓住别人没注意到的商业或投资机会？",
    "正官": "你是否在讲规则、有秩序的环境中反而能发挥得更好？",
    "七杀": "你是否在高压和挑战下反而能做出比平时更好的决策？",
}

# ============================================================
# 会话管理
# ============================================================

_verification_sessions = {}
_SESSION_TTL_SECONDS = 1800


def _cleanup_expired_sessions():
    now = datetime.now().timestamp()
    expired = [sid for sid, s in _verification_sessions.items()
               if now - s.get("_created_at", 0) > _SESSION_TTL_SECONDS]
    for sid in expired:
        del _verification_sessions[sid]


_ANSWER_NORMALIZE = {
    "很像": "accurate", "有点出入": "partial", "完全不像": "inaccurate",
    "是的": "accurate", "不太确定": "partial", "不是": "inaccurate",
    "是": "accurate", "带头推动": "accurate", "偏向创作": "inaccurate",
    "不太好说": "partial", "务实重结果": "accurate", "重学习修养": "inaccurate",
    "有道理，让我补充": "accurate", "不对，换个方向": "inaccurate",
    "准确": "accurate", "不准": "inaccurate",
    "说说具体的": "custom",   # V4: 自由文本入口
}


def _get_yongshen_question(tg: str) -> str:
    return YONGSHEN_QUESTIONS.get(tg, f"{tg}作为用神在哪些方面体现？")


def _get_quality_question(qtype: str, tg: str) -> str:
    return QUALITY_QUESTIONS.get(qtype, {}).get(tg,
           "请描述这个方面在你生活中的体现。")


# ============================================================
# init_verification (V3)
# ============================================================

def init_verification(chart_data: dict, user_id: str = None) -> dict:
    _cleanup_expired_sessions()
    session_id = str(uuid.uuid4())

    dm_stem = _extract_dm_stem(chart_data)
    month_branch = _extract_month_branch(chart_data)
    strength_detail = chart_data.get("strength_detail") or {}

    # Step 1: 月令定格局
    pattern = determine_pattern_type(dm_stem, month_branch)
    step_results = {
        "pattern": pattern,
        "pattern_source": "月令本气",
    }

    # Step 2: 透干会支检查
    touchu = detect_ganzhi_touchu(chart_data)
    heju = detect_zhi_heju(chart_data, month_branch)

    step_results["gan_touchu"] = touchu
    step_results["zhi_heju"] = heju
    step_results["pending_change"] = {"is_pending": False, "candidate_pattern": None,
                                       "resolved": False, "resolved_to": None}

    if touchu["level"] in ("中气", "余气") and touchu["is_strong"]:
        new_pattern = _TG_TO_PATTERN.get(touchu["touched_ten_god"], "")
        if new_pattern and new_pattern != pattern:
            step_results["pattern"] = new_pattern
            step_results["pattern_source"] = "天干透出"

    if heju["pending"]:
        heju_pattern = _resolve_heju_pattern(dm_stem, heju["hua_wuxing"])
        if heju_pattern:
            step_results["pending_change"] = {
                "is_pending": True,
                "candidate_pattern": heju_pattern,
                "resolved": False,
                "resolved_to": None,
            }

    # Step 3: 旺衰五等
    wangshuai = judge_wangshuai_level(chart_data, strength_detail)
    step_results["wangshuai"] = wangshuai

    # Resolve pending heju
    if step_results["pending_change"]["is_pending"]:
        step_results = resolve_pending_heju(step_results, wangshuai["level"])

    # L1 question (旺衰自适应)
    final_pattern = step_results["pattern"]
    l1 = _get_l1_question(final_pattern, wangshuai["level"])

    first_question = {
        "round": 1, "layer": "L1",
        "question": l1["question"],
        "explanation": l1.get("explanation", ""),
        "pattern_feature": l1.get("pattern_feature", ""),
        "target_pattern": final_pattern,
        "options": ["很像", "有点出入", "完全不像"],
    }

    session = {
        "session_id": session_id,
        "user_id": user_id,
        "chart_data": chart_data,
        "pattern": final_pattern,
        "step_results": step_results,
        "round": 1,
        "stage": "pattern",
        "sub_stage": "L1",
        "l1_answer": None,
        "confidence": abs(wangshuai["level"] == "极旺" and 25 or
                          wangshuai["level"] == "身旺" and 30 or
                          wangshuai["level"] == "中和" and 20 or
                          wangshuai["level"] == "身弱" and 25 or 20),
        "quality": None,
        "purity": "纯",  # 默认纯，仅在纯杂检查后可能改为"杂"
        "phase2_youqing": None,
        "phase2_youli": None,
        "diagnosis_count": 0,
        "diagnosis_sub_stage": 1,
        "diagnosis_path": [],
        "yongshen_candidates": None,
        "yongshen_regeneration": 0,
        "locked_yongshen": None,
        "history": [],
        "current_question": first_question,
        "_created_at": datetime.now().timestamp(),
    }

    _verification_sessions[session_id] = session

    if user_id:
        try:
            asyncio.ensure_future(_save_db_session(session))
        except Exception:
            pass

    return {
        "session_id": session_id,
        "stage": "pattern",
        "sub_stage": "L1",
        "question": first_question,
        "step_results": {
            "pattern": final_pattern,
            "pattern_source": step_results["pattern_source"],
            "gan_touchu": touchu,
            "wangshuai_level": wangshuai["level"],
        },
    }


def _resolve_heju_pattern(dm_stem, hua_wx):
    """根据化神五行和日主天干推断合化后的格局"""
    tg = _resolve_five_element(dm_stem, "比肩", "")
    return None  # 简化处理：由 AI 生成问题时间接处理


# ============================================================
# process_verification (V3)
# ============================================================

async def process_verification(session_id: str, answer: str, note: str = "") -> dict:
    answer = _ANSWER_NORMALIZE.get(answer, answer)

    _cleanup_expired_sessions()
    session = _verification_sessions.get(session_id)
    if not session:
        return {"error": "会话不存在或已过期"}

    cq = session.get("current_question", {})

    session["history"].append({
        "round": session["round"],
        "stage": session.get("stage"),
        "sub_stage": session.get("sub_stage"),
        "question": cq.get("question", ""),
        "answer": answer,
        "note": note,
    })

    # V4: LLM 100% 介入 — 有 API Key 时优先用 LLM 驱动
    if _has_llm() and note:
        # 用户写了自由文本 → LLM 解读
        llm_result = await _llm_interpret(session, answer, note)
        if llm_result:
            answer = llm_result.get("mapped_answer", answer)
            if llm_result.get("extracted_facts"):
                session.setdefault("_llm_facts", []).extend(llm_result["extracted_facts"])

    sub = session.get("sub_stage", "L1")
    result = None

    # V4: 尝试 LLM 生成下一个问题
    if _has_llm():
        result = await _llm_next(session, sub, answer)

    if result is None:
        # LLM 不可用或失败 → 降级到 V3 静态 handler
        result = await _dispatch_static(session, sub, answer)
    else:
        # LLM 返回了 action → 处理 advance_stage / backtrack
        action = result.get("action")
        if action == "advance_stage":
            return await _advance_to_next_stage(session)
        elif action == "backtrack":
            return await _enter_diagnosis(session)

    return result


async def _advance_to_next_stage(session):
    """统一阶段流转 — LLM 判定可以跳时调用"""
    sub = session.get("sub_stage", "L1")
    session["round"] += 1

    transitions = {
        "L1": lambda: _enter_phase2_with_purity(session),
        "purity": lambda: _enter_phase2(session),
        "phase2_L2": lambda: _advance_static(session, "phase2_L2", "accurate"),
        "phase2_L3": lambda: _advance_static(session, "phase2_L3", "accurate"),
    }
    if sub in transitions:
        return await transitions[sub]()
    if sub.startswith("diag_"):
        return await _enter_phase2(session)
    if sub.startswith("ys_"):
        return await _handle_yongshen(session, "accurate")
    return await _enter_phase2(session)


async def _enter_phase2_with_purity(session):
    """L1→Phase2: 先静默执行纯杂检测再进Phase2"""
    purity = check_purity(session["pattern"], session["chart_data"])
    session["purity_result"] = purity
    if not session.get("purity"):
        session["purity"] = "杂" if purity["is_mixed"] else "纯"
    session["l1_answer"] = session.get("l1_answer", "Medium")
    session["diagnosis_path"].append({"step": "L1", "action": "格局特征验证-LLM跳过"})
    return await _enter_phase2(session)


async def _llm_interpret(session, answer, note):
    """LLM 解读用户自由文本回答"""
    facts = session.get("_llm_facts", [])
    history = _format_chat_history(session)
    pattern = session.get("pattern", "")
    wangshuai = session.get("step_results", {}).get("wangshuai", {})

    prompt = f"""用户八字: {session.get('pattern', '?')}格, 旺衰={wangshuai.get('level','?')}
对话历史:
{history}

你刚才问的问题: {session.get('current_question',{}).get('question','')}
用户回答: {answer}
用户补充说明: {note}

已知事实: {', '.join(facts) if facts else '无'}

请解读用户回答，输出JSON(不要markdown标记):
{{"mapped_answer":"accurate|partial|inaccurate","extracted_facts":[""],"internal":"你的分析"}}"""
    content = await _llm_ask(SYSTEM_PROMPT, prompt, 200)
    if not content:
        return None
    try:
        return json.loads(content)
    except:
        return {"mapped_answer": answer, "extracted_facts": [note]}


async def _llm_next(session, sub, prev_answer):
    """LLM 生成当前阶段的下一个问题或判定"""
    if sub.endswith("_L3") or sub in ("ys_3", "ys_2"):
        return None  # 阶段末尾交给状态机

    history = _format_chat_history(session)
    sr = session.get("step_results", {})
    wangshuai = sr.get("wangshuai", {})
    pattern = session.get("pattern", "")
    classical = _get_classical_reference(session, sub)

    prompt = f"""你正在验证一个八字命盘。

命盘: {pattern}格, 日主{session['chart_data'].get('day_master','')}, 旺衰={wangshuai.get('level','?')}(方向={wangshuai.get('yongshen_direction','')})
透干: {sr.get('gan_touchu',{})}

典籍参考:
{classical}

对话历史:
{history}

当前阶段: {sub}

请生成你的下一步行动。输出JSON(不要markdown标记):
{{"action":"ask_question|advance_stage|backtrack","interaction_mode":"confirm|followup","question":"你的问题","options":["选项1","选项2","选项3"],"internal_analysis":"命理师内部判断","confidence":0-100}}

规则:
- 问题必须用生活化语言，不含命理术语
- internal_analysis 是你后台的命理判断，不是给用户看的
- 如果当前格局特征已足够确认，action="advance_stage"
- 如果用户持续否定，可以 action="backtrack" 回到诊断链"""
    content = await _llm_ask(SYSTEM_PROMPT, prompt, 350)
    if not content:
        return None
    try:
        llm = json.loads(content)
    except:
        return None

    action = llm.get("action", "ask_question")
    session["round"] += 1

    # advance_stage / backtrack → 返回 action 让状态机处理
    if action in ("advance_stage", "backtrack"):
        session["_llm_last_quality"] = llm.get("internal_analysis", "")
        return {"action": action, "confidence": llm.get("confidence", 50)}

    elif action == "ask_question":
        q = {
            "round": session["round"], "layer": f"L{session['round']}",
            "question": llm["question"],
            "explanation": "",
            "options": llm.get("options", ["很像", "有点出入", "完全不像"]),
            "interaction_mode": llm.get("interaction_mode", "confirm"),
            "llm_generated": True,
        }
        session["current_question"] = q
        # 存内部分析供后续参考
        if llm.get("internal_analysis"):
            session.setdefault("_llm_analyses", []).append(llm["internal_analysis"])
        return {"locked": False, "stage": session.get("stage", "pattern"),
                "sub_stage": session.get("sub_stage", sub), "question": q}

    return None


async def _advance_static(session, sub, answer):
    """辅助：用静态handler获取下一阶段结果"""
    return await _dispatch_static(session, sub, answer)


def _get_classical_reference(session, stage: str = "pattern") -> str:
    """使用项目 RAG 检索器（FTS5 全文检索 281 章典籍）"""
    from services.rag_retriever import retrieve_by_stage

    pattern = session.get("pattern", "")
    chart = session.get("chart_data", {})
    sr = session.get("step_results", {})

    # 将验证阶段映射到 RAG 阶段
    rag_stage = "pattern"
    if stage.startswith("ys_") or "yongshen" in stage:
        rag_stage = "yongshen"
    elif "phase2_L2" in stage or "phase2_L3" in stage:
        rag_stage = "pattern"

    dm = chart.get("day_master", "")
    dm_wx = _get_wuxing(dm)
    month_branch = sr.get("wangshuai", {}).get("level", "") or \
                   chart.get("four_pillars", {}).get("month", {}).get("branch", "")

    try:
        keywords = [pattern.replace("格", "")]
        if rag_stage == "yongshen":
            keywords.extend(["用神", "顺用", "逆用"])
        elif "phase2" in stage:
            keywords.extend(["有情", "有力", "生扶", "通根"])

        results = retrieve_by_stage(
            stage=rag_stage,
            keywords=keywords,
            ri_zhu_wuxing=dm_wx,
            month_branch=month_branch,
            top_k=5,
        )
        if results:
            lines = []
            for r in results[:4]:
                src = r.get("source", "?")
                ch = r.get("chapter", "?")
                txt = r.get("text", r.get("excerpt", ""))[:120]
                lines.append(f"《{src}·{ch}》：{txt}")
            return "\n".join(lines)
    except Exception:
        pass

    return "（典籍数据不可用）"


def _get_wuxing(dm):
    mapping = {"甲": "木", "乙": "木", "丙": "火", "丁": "火", "戊": "土",
               "己": "土", "庚": "金", "辛": "金", "壬": "水", "癸": "水"}
    return mapping.get(dm[-1] if dm else "", "")


def _format_chat_history(session):
    lines = []
    for h in session.get("history", [])[-6:]:
        role = "命理师" if h.get("role") == "ai" else "用户"
        q = h.get("question", "")[:60]
        a = h.get("answer", "")
        note = h.get("note", "")
        line = f"{role}: {q} → {a}"
        if note:
            line += f" (补充: {note})"
        lines.append(line)
    return "\n".join(lines)


async def _dispatch_static(session, sub, answer):
    """V3 静态 handler — 当 LLM 不可用时降级到此"""
    if sub == "L1":
        return await _handle_L1(session, answer)
    elif sub == "purity":
        return await _handle_purity(session, answer)
    elif sub == "phase2_L2":
        return await _handle_phase2_L2(session, answer)
    elif sub == "phase2_L3":
        return await _handle_phase2_L3(session, answer)
    elif sub == "tongguan":
        return await _handle_tongguan(session, answer)
    elif sub.startswith("diag_"):
        return await _handle_diagnosis(session, answer)
    elif sub.startswith("ys_"):
        return await _handle_yongshen(session, answer)
    else:
        return {"error": f"未知子阶段: {sub}"}


# ============================================================
# L1 Handler
# ============================================================

async def _handle_L1(session, answer):
    session["l1_answer"] = "High" if answer == "accurate" else ("Medium" if answer == "partial" else "Low")

    if answer == "accurate":
        session["confidence"] = min(99, session["confidence"] + 15)
    elif answer == "partial":
        pass
    else:
        session["confidence"] = max(1, session["confidence"] - 20)

    session["diagnosis_path"].append({"step": "L1", "action": f"格局特征验证-{session['pattern']}",
                                       "answer": session["l1_answer"]})

    if session["l1_answer"] == "Low":
        # 纯杂检查
        purity = check_purity(session["pattern"], session["chart_data"])
        session["purity_result"] = purity
        if purity["is_mixed"]:
            session["sub_stage"] = "purity"
            session["round"] += 1
            q = {
                "round": session["round"], "layer": f"L{session['round']}",
                "question": f"你是否感觉自己性格中有矛盾的两面——{purity['mix_stems'][0]}和{purity['mix_stems'][1]}的特征同时存在？",
                "explanation": f"检测到{purity['mix_type']}，可能使格局特征模糊。",
                "options": ["是", "不太确定", "不是"],
            }
            session["current_question"] = q
            return {"locked": False, "stage": "pattern", "sub_stage": "purity",
                    "question": q, "purity_check": purity}
        else:
            # 不混杂 → 直接进诊断链
            return await _enter_diagnosis(session)

    # 进 Phase 2
    # Fix: L1 B(有点出入) → 先静默检查是否有混杂或待确认合局
    if session["l1_answer"] == "Medium":
        purity = check_purity(session["pattern"], session["chart_data"])
        heju = session.get("step_results", {}).get("zhi_heju", {})
        session["purity_result"] = purity
        if purity["is_mixed"] or heju.get("pending"):
            session["purity"] = "杂" if purity["is_mixed"] else "纯"
            session["diagnosis_path"].append({"step": "L1", "action": "有点出入-检测混杂/合局",
                                               "mixed": purity["is_mixed"], "heju_pending": heju.get("pending")})
        else:
            session["diagnosis_path"].append({"step": "L1", "action": "有点出入-无特殊检测"})
    return await _enter_phase2(session)


async def _handle_purity(session, answer):
    if answer == "accurate":
        session["purity"] = "杂"
        session["confidence"] = max(1, session["confidence"] * 0.7)
        return await _enter_phase2(session)
    else:
        session["purity"] = "纯"
        return await _enter_diagnosis(session)


# ============================================================
# Phase 2: 品质判断
# ============================================================

async def _enter_phase2(session):
    session["stage"] = "pattern"
    session["sub_stage"] = "phase2_L2"
    session["round"] += 1

    chart = session["chart_data"]
    dm_stem = _extract_dm_stem(chart)
    month_branch = _extract_month_branch(chart)
    pattern = session["pattern"]
    yongshen_candidates = PATTERN_YONGSHEN.get(pattern, [])
    top_tg = yongshen_candidates[0][0] if yongshen_candidates else "食神"
    session["_phase2_yongshen_tg"] = top_tg

    q_text = _get_quality_question("youqing", top_tg)
    q = {
        "round": session["round"], "layer": f"L{session['round']}",
        "question": q_text,
        "explanation": f"验证{pattern}的用神{top_tg}是否有辅助力量",
        "options": ["很像", "有点出入", "完全不像"],
        "target": top_tg,
    }
    session["current_question"] = q

    return {"locked": False, "stage": "pattern", "sub_stage": "phase2_L2",
            "question": q, "pattern": pattern}


async def _handle_phase2_L2(session, answer):
    session["phase2_youqing"] = answer == "accurate"
    session["diagnosis_path"].append({"step": "L2", "action": "有情判断",
                                       "result": "有情" if session["phase2_youqing"] else "无情"})

    session["stage"] = "pattern"
    session["sub_stage"] = "phase2_L3"
    session["round"] += 1

    tg = session.get("_phase2_yongshen_tg", "食神")
    q_text = _get_quality_question("youli", tg)
    q = {
        "round": session["round"], "layer": f"L{session['round']}",
        "question": q_text,
        "explanation": f"验证{tg}是否有实体力量支撑",
        "options": ["很像", "有点出入", "完全不像"],
        "target": tg,
    }
    session["current_question"] = q

    return {"locked": False, "stage": "pattern", "sub_stage": "phase2_L3",
            "question": q, "pattern": session["pattern"]}


async def _handle_phase2_L3(session, answer):
    session["phase2_youli"] = answer == "accurate"
    session["diagnosis_path"].append({"step": "L3", "action": "有力判断",
                                       "result": "有力" if session["phase2_youli"] else "无力"})

    youqing = session.get("phase2_youqing", False)
    youli = session.get("phase2_youli", False)

    if youqing and youli:
        session["quality"] = "上格"
    elif youqing and not youli:
        session["quality"] = "中格"
    elif not youqing and youli:
        session["quality"] = "中下格"
    else:
        session["quality"] = "下格"

    l1 = session.get("l1_answer", "Medium")

    if "下格" in str(session["quality"]):
        if l1 == "High":
            session["yongshen_regeneration"] = 1
            return await _enter_yongshen(session)
        else:
            clash = find_wuxing_clash(session["chart_data"])
            if clash and not session.get("_tongguan_checked"):
                session["_tongguan_checked"] = True
                session["stage"] = "pattern"
                session["sub_stage"] = "tongguan"
                session["round"] += 1
                wx_a, wx_b = clash
                q = {"round": session["round"], "layer": f"L{session['round']}",
                     "question": "你是否感觉自己性格中有内在的矛盾——两种不同的力量互相拉扯，让你难以完全发挥？",
                     "explanation": f"检测五行对峙({wx_a}vs{wx_b})", "options": ["是", "不太确定", "不是"],
                     "tongguan_clash": clash}
                session["current_question"] = q
                return {"locked": False, "stage": "pattern", "sub_stage": "tongguan",
                        "question": q, "tongguan_check": True}
            return await _enter_diagnosis(session)
    else:
        return await _enter_yongshen(session)


async def _handle_tongguan(session, answer):
    """处理通关检查问题"""
    session["diagnosis_path"].append({"step": "tongguan", "answer": answer})
    if answer == "accurate":
        session["quality"] = "中格"
        session["_tongguan_confirmed"] = True
        return await _enter_yongshen(session)
    else:
        return await _enter_diagnosis(session)


# ============================================================
# 诊断链
# ============================================================

async def _enter_diagnosis(session):
    session["stage"] = "diagnosis"
    session["diagnosis_count"] = 0
    session["diagnosis_sub_stage"] = 1
    session["round"] += 1

    return await _run_diagnosis_step(session, 1)


async def _run_diagnosis_step(session, step_num):
    session["diagnosis_sub_stage"] = step_num
    chart = session["chart_data"]
    dm_stem = _extract_dm_stem(chart)
    month_branch = _extract_month_branch(chart)
    fp = chart.get("four_pillars", {})

    if step_num == 1:
        # D1: 月令被冲
        d1 = _check_month_branch_chong(fp, month_branch)
        if d1["is_chong"]:
            q = {"round": session["round"], "layer": f"L{session['round']}",
                 "question": DIAGNOSIS_QUESTIONS["D1_chong"],
                 "explanation": "检测月令是否被冲",
                 "options": ["是", "不太确定", "不是"],
                 "diag_step": "D1", "diag_data": d1}
            session["current_question"] = q
            session["sub_stage"] = "diag_D1"
            return {"locked": False, "stage": "diagnosis", "sub_stage": "diag_D1",
                    "question": q, "diagnosis_step": "D1"}
        else:
            session["round"] += 1
            return await _run_diagnosis_step(session, step_num + 1)

    elif step_num == 2:
        d2 = _check_month_branch_he(fp, month_branch)
        if d2["is_he"]:
            q = {"round": session["round"], "layer": f"L{session['round']}",
                 "question": DIAGNOSIS_QUESTIONS["D2_he"],
                 "explanation": "检测月令是否被合",
                 "options": ["是", "不太确定", "不是"],
                 "diag_step": "D2", "diag_data": d2}
            session["current_question"] = q
            session["sub_stage"] = "diag_D2"
            return {"locked": False, "stage": "diagnosis", "sub_stage": "diag_D2",
                    "question": q, "diagnosis_step": "D2"}
        else:
            session["round"] += 1
            return await _run_diagnosis_step(session, step_num + 1)

    elif step_num == 3:
        stems = _get_month_hidden_stems(month_branch)
        if len(stems) >= 2:
            tg2 = _calc_ten_god(dm_stem, stems[1])
            alt_pattern = _TG_TO_PATTERN.get(tg2, "")
            if alt_pattern and alt_pattern != session["pattern"]:
                l1_q = PATTERN_L1_QUESTIONS.get(alt_pattern, {})
                q_text = f"之前的方向不太符合。换个角度——{l1_q.get('question', '请描述你的特点')}"
                q = {"round": session["round"], "layer": f"L{session['round']}",
                     "question": q_text,
                     "explanation": f"尝试中气格局: {alt_pattern}",
                     "options": ["很像", "有点出入", "完全不像"],
                     "diag_step": "D3", "alt_pattern": alt_pattern}
                session["current_question"] = q
                session["sub_stage"] = "diag_D3"
                return {"locked": False, "stage": "diagnosis", "sub_stage": "diag_D3",
                        "question": q, "diagnosis_step": "D3"}
        session["round"] += 1
        return await _run_diagnosis_step(session, step_num + 1)

    elif step_num == 4:
        q = {"round": session["round"], "layer": f"L{session['round']}",
             "question": DIAGNOSIS_QUESTIONS["D4_jiuying"],
             "explanation": "检测用神救应是否到位",
             "options": ["是", "不太确定", "不是"],
             "diag_step": "D4"}
        session["current_question"] = q
        session["sub_stage"] = "diag_D4"
        return {"locked": False, "stage": "diagnosis", "sub_stage": "diag_D4",
                "question": q, "diagnosis_step": "D4"}

    elif step_num == 5:
        q = {"round": session["round"], "layer": f"L{session['round']}",
             "question": DIAGNOSIS_QUESTIONS["D5_time"],
             "explanation": "时辰校验",
             "options": ["准确", "不太确定", "不准"],
             "diag_step": "D5"}
        session["current_question"] = q
        session["sub_stage"] = "diag_D5"
        return {"locked": False, "stage": "diagnosis", "sub_stage": "diag_D5",
                "question": q, "diagnosis_step": "D5"}

    return {"error": "无效诊断步骤"}


async def _handle_diagnosis(session, answer):
    sub = session.get("sub_stage")
    step_num = session.get("diagnosis_sub_stage", 1)

    session["diagnosis_path"].append({"step": f"D{step_num}", "answer": answer})

    if answer == "accurate":
        if sub == "diag_D1":
            d1 = session.get("current_question", {}).get("diag_data", {})
            if d1.get("has_rescue"):
                session["confidence"] = max(1, session["confidence"] * 0.7)
                return await _enter_phase2(session)
            else:
                session["round"] += 1
                # 冲散→中气, 但之后也要静默检查救应
                session["_from_chong_san"] = True
                return await _run_diagnosis_step(session, 3)  # 冲散→中气
        elif sub == "diag_D2":
            session["round"] += 1
            session["sub_stage"] = "L1"
            session["confidence"] = 20
            return {"locked": False, "stage": "pattern", "sub_stage": "L1",
                    "question": session["current_question"], "pattern_changed": True}
        elif sub == "diag_D3":
            alt = session.get("current_question", {}).get("alt_pattern", "")
            if alt:
                session["pattern"] = alt
                session["confidence"] = 25
                session["purity"] = None
                session["quality"] = None
                # 冲散路径: 静默注入救应数据
                if session.get("_from_chong_san"):
                    tg = PATTERN_YONGSHEN.get(alt, [("食神","火")])[0][0]
                    jiuying = check_jiuying(session["chart_data"], tg)
                    session["_jiuying_data"] = jiuying
                    session["_from_chong_san"] = False
                    session["diagnosis_path"].append({"step": "D4_silent", "action": "救应静默检测",
                                                       "result": jiuying})
                return await _enter_phase2(session)
        elif sub == "diag_D4":
            return await _enter_phase2(session)
        elif sub == "diag_D5":
            session["confidence"] = max(1, session["confidence"] * 0.6)
            return await _enter_phase2(session)
    else:
        if sub == "diag_D5" and answer == "partial":
            return {"locked": True, "stage": "done", "result": None,
                    "message": "无法确认，请重新确认出生时间"}
        if sub == "diag_D5" and answer == "inaccurate":
            return {"locked": True, "stage": "done", "result": None,
                    "message": "请回到首页重新录入"}
        session["diagnosis_count"] = session.get("diagnosis_count", 0) + 1
        if session["diagnosis_count"] >= 3:
            session["round"] += 1
            return await _run_diagnosis_step(session, 5)  # 跳至时辰
        session["round"] += 1
        return await _run_diagnosis_step(session, step_num + 1)

    return await _enter_yongshen(session)


def _check_month_branch_chong(fp, month_branch):
    from rules.pattern import _OPPOSITES
    opp = _OPPOSITES.get(month_branch)
    is_chong = False
    has_rescue = False
    for pos in ["year", "day"]:
        b = fp.get(pos, {}).get("branch", "")
        if b == opp:
            is_chong = True
    return {"is_chong": is_chong, "has_rescue": has_rescue}


def _check_month_branch_he(fp, month_branch):
    from rules.pattern import _COMBINATIONS
    he_with = _COMBINATIONS.get(month_branch)
    is_he = False
    for pos in ["year", "day"]:
        b = fp.get(pos, {}).get("branch", "")
        if b == he_with:
            is_he = True
    return {"is_he": is_he}


def _get_month_hidden_stems(month_branch):
    from rules.pattern import get_month_stems
    return get_month_stems(month_branch)


# ============================================================
# Phase 3: 用神验证
# ============================================================

async def _enter_yongshen(session):
    session["stage"] = "yongshen"
    chart = session["chart_data"]
    dm_stem = _extract_dm_stem(chart)
    month_branch = _extract_month_branch(chart)
    wangshuai = session.get("step_results", {}).get("wangshuai", {})
    direction = wangshuai.get("yongshen_direction", "灵活")
    pattern = session["pattern"]

    candidates = _generate_yongshen_candidates(pattern, dm_stem, direction, chart, month_branch)
    session["yongshen_candidates"] = candidates
    session["_yongshen_asked"] = []
    session["yongshen_regeneration"] = session.get("yongshen_regeneration", 0)
    session["round"] += 1

    if not candidates:
        session["sub_stage"] = "ys_done"
        return _finalize_locked(session)

    session["sub_stage"] = "ys_1"
    top = candidates[0]
    session["_yongshen_asked"].append(top["yong_shen"])
    q = {
        "round": session["round"], "layer": f"L{session['round']}",
        "question": top.get("question", _get_yongshen_question(top["yong_shen"])),
        "explanation": f"验证用神 {top['yong_shen']}({top['five_element']}) — {top.get('dim', '')}",
        "options": ["是的", "不太确定", "不是"],
        "target_yongshen": top["yong_shen"],
    }
    session["current_question"] = q

    return {"locked": False, "stage": "yongshen", "sub_stage": "ys_1",
            "question": q, "yongshen_candidates": candidates,
            "locked_pattern": {"pattern": pattern, "quality": session.get("quality")}}


async def _handle_yongshen(session, answer):
    candidates = session.get("yongshen_candidates", [])
    cq = session.get("current_question", {})
    target = cq.get("target_yongshen", "")
    sub = session.get("sub_stage", "ys_1")

    for c in candidates:
        is_target = c["yong_shen"] == target
        if is_target:
            if answer == "accurate":
                c["confidence"] = min(99, c["confidence"] + 15)
            elif answer == "partial":
                c["confidence"] = min(99, c["confidence"] + 3)
            else:
                c["confidence"] = max(1, c["confidence"] - 20)
        else:
            if answer == "accurate":
                c["confidence"] = max(1, c["confidence"] - 5)
            elif answer == "inaccurate":
                c["confidence"] = min(99, c["confidence"] + 3)

    candidates.sort(key=lambda x: x["confidence"], reverse=True)
    session["yongshen_candidates"] = candidates

    if sub == "ys_3" or (sub == "ys_2" and session.get("yongshen_regeneration", 0) > 1):
        return _finalize_locked(session)

    top = candidates[0]
    if top["confidence"] >= 65 and (len(candidates) < 2 or top["confidence"] - candidates[1]["confidence"] >= 20):
        return _finalize_locked(session)

    next_idx = int(sub.split("_")[1]) + 1
    if next_idx > 3:
        if session.get("yongshen_regeneration", 0) < 2:
            session["yongshen_regeneration"] = session.get("yongshen_regeneration", 0) + 1
            session["yongshen_candidates"] = [{"confidence": max(1, c["confidence"] + 5)} if c is candidates[0] else c for c in candidates]
            next_idx = 1

    session["sub_stage"] = f"ys_{next_idx}"
    session["round"] += 1

    asked = session.get("_yongshen_asked", [])
    next_ys = None
    for c in candidates:
        if c["yong_shen"] not in asked:
            next_ys = c
            break
    if not next_ys:
        next_ys = candidates[0]

    asked.append(next_ys["yong_shen"])
    session["_yongshen_asked"] = asked

    q = {
        "round": session["round"], "layer": f"L{session['round']}",
        "question": next_ys.get("question", _get_yongshen_question(next_ys["yong_shen"])),
        "explanation": f"验证用神 {next_ys['yong_shen']}({next_ys['five_element']})",
        "options": ["是的", "不太确定", "不是"],
        "target_yongshen": next_ys["yong_shen"],
    }
    session["current_question"] = q

    return {"locked": False, "stage": "yongshen", "sub_stage": session["sub_stage"],
            "question": q, "yongshen_candidates": candidates,
            "locked_pattern": {"pattern": session["pattern"], "quality": session.get("quality")}}


def _finalize_locked(session):
    session["stage"] = "locked"
    candidates = session.get("yongshen_candidates", [])
    top = candidates[0] if candidates else {"yong_shen": "食神", "five_element": "火",
                                              "gong_way": "格局法", "confidence": 50}
    session["locked_yongshen"] = top

    return {
        "locked": True, "stage": "done",
        "rounds": session["round"],
        "result": {
            "pattern": session["pattern"],
            "pattern_confidence": session["confidence"],
            "yong_shen": top["yong_shen"],
            "yongshen_confidence": top["confidence"],
            "five_element": top.get("five_element", ""),
            "gong_way": top.get("gong_way", ""),
            "pattern_type": "正格",
        },
        "quality": session.get("quality", "中格"),
        "purity": session.get("purity", "纯"),
        "pattern_source": session.get("step_results", {}).get("pattern_source", "月令本气"),
        "diagnosis_path": session.get("diagnosis_path", []),
        "credibility": "high" if session.get("quality") in ("上格", "中格") else "medium",
        "expansion_attempted": session.get("diagnosis_count", 0) > 0,
        "total_rounds": session["round"],
    }


# ============================================================
# 用神候选生成
# ============================================================

def _generate_yongshen_candidates(pattern, dm_stem, direction, chart_data, month_branch):
    candidates = []

    wuxing_factor = {"木": 1, "火": 2, "土": 3, "金": 4, "水": 5}

    # 1. 格局法 ×2.0
    pattern_candidates = PATTERN_YONGSHEN.get(pattern, [])
    for tg, wx_fallback in pattern_candidates:
        wx = _resolve_five_element(dm_stem, tg, wx_fallback)
        if wx:
            candidates.append({
                "yong_shen": tg, "five_element": wx,
                "gong_way": _get_gong_way(pattern, tg) if _get_gong_way else f"{pattern}用{tg}",
                "confidence": 35, "weight": 2.0, "source": "格局法",
                "dim": YONGSHEN_DIMENSIONS.get(tg, "综合"),
                "question": _get_yongshen_question(tg),
            })

    # 2. 调候法 ×1.5
    tiaohou_wx = _get_tiaohou_wuxing(_branch_to_num(month_branch))
    if tiaohou_wx:
        existing = {c["five_element"] for c in candidates}
        if tiaohou_wx not in existing:
            tg = _wx_to_potential_yongshen(dm_stem, tiaohou_wx, direction)
            if tg:
                candidates.append({
                    "yong_shen": tg, "five_element": tiaohou_wx,
                    "gong_way": f"调候用{tg}",
                    "confidence": 25, "weight": 1.5, "source": "调候法",
                    "dim": YONGSHEN_DIMENSIONS.get(tg, "综合"),
                    "question": _get_yongshen_question(tg),
                })

    # 3. 扶抑法 ×1.0
    is_strong = direction == "克泄耗"
    wx_map = {}
    for tg in ("正官", "七杀", "正财", "偏财", "食神", "伤官", "正印", "偏印", "比肩", "劫财"):
        wx = _resolve_five_element(dm_stem, tg, "")
        if wx:
            wx_map[tg] = wx

    for tg, wx in wx_map.items():
        existing = {c["yong_shen"] for c in candidates}
        if tg in existing:
            continue
        is_support = tg in ("正印", "偏印", "比肩", "劫财")
        is_drain = tg in ("正官", "七杀", "正财", "偏财", "食神", "伤官")
        if (is_strong and is_drain) or (not is_strong and is_support):
            candidates.append({
                "yong_shen": tg, "five_element": wx,
                "gong_way": f"扶抑用{tg}",
                "confidence": 15, "weight": 1.0, "source": "扶抑法",
                "dim": YONGSHEN_DIMENSIONS.get(tg, "综合"),
                "question": _get_yongshen_question(tg),
            })

    # 4. 通关法 ×1.5
    clash = find_wuxing_clash(chart_data)
    if clash:
        tongguan_wx = get_tongguan_wuxing(clash)
        if tongguan_wx:
            existing = {c["five_element"] for c in candidates}
            if tongguan_wx not in existing:
                tg = _wx_to_potential_yongshen(dm_stem, tongguan_wx, direction)
                if tg:
                    candidates.append({
                        "yong_shen": tg, "five_element": tongguan_wx,
                        "gong_way": f"通关用{tg}",
                        "confidence": 22, "weight": 1.5, "source": "通关法",
                        "dim": YONGSHEN_DIMENSIONS.get(tg, "综合"),
                        "question": _get_yongshen_question(tg),
                    })

    candidates.sort(key=lambda x: x["confidence"] * x["weight"], reverse=True)
    return candidates


def _wx_to_potential_yongshen(dm_stem, target_wx, direction):
    dm_wx = WUXING_MAP_VAL.get(dm_stem, "")
    for tg, wx in [("正印", _SHENG_VAL.get(dm_wx, "")), ("偏印", _SHENG_VAL.get(dm_wx, "")),
                    ("比肩", dm_wx), ("劫财", dm_wx),
                    ("食神", _I_SHENG_VAL.get(dm_wx, "")), ("伤官", _I_SHENG_VAL.get(dm_wx, "")),
                    ("正财", _I_KE_VAL.get(dm_wx, "")), ("偏财", _I_KE_VAL.get(dm_wx, "")),
                    ("正官", _KE_VAL.get(dm_wx, "")), ("七杀", _KE_VAL.get(dm_wx, ""))]:
        if wx == target_wx:
            return tg
    return None


def _branch_to_num(branch):
    mapping = {"寅": 1, "卯": 2, "辰": 3, "巳": 4, "午": 5, "未": 6,
               "申": 7, "酉": 8, "戌": 9, "亥": 10, "子": 11, "丑": 12}
    return mapping.get(branch, 6)


def _get_tiaohou_wuxing(month_num):
    if month_num in (10, 11, 12):
        return "火"
    if month_num in (4, 5):
        return "水"
    return ""


# 五行映射 (简版，与 pattern.py 保持同步)
WUXING_MAP_VAL = {"甲": "木", "乙": "木", "丙": "火", "丁": "火", "戊": "土",
                   "己": "土", "庚": "金", "辛": "金", "壬": "水", "癸": "水"}
_SHENG_VAL = {"金": "土", "木": "水", "水": "金", "火": "木", "土": "火"}
_I_SHENG_VAL = {"金": "水", "木": "火", "水": "木", "火": "土", "土": "金"}
_KE_VAL = {"金": "火", "木": "金", "水": "土", "火": "水", "土": "木"}
_I_KE_VAL = {"金": "木", "木": "土", "水": "火", "火": "金", "土": "水"}


# ============================================================
# 辅助函数
# ============================================================

def _extract_dm_stem(chart_data):
    dm = chart_data.get("day_master", "")
    return dm[-1] if dm else "甲"


def _extract_month_branch(chart_data):
    return chart_data.get("four_pillars", {}).get("month", {}).get("branch", "子")


def get_session(session_id):
    _cleanup_expired_sessions()
    return _verification_sessions.get(session_id)


async def get_session_async(session_id):
    _cleanup_expired_sessions()
    s = _verification_sessions.get(session_id)
    if s:
        return s
    s = await _load_db_session(session_id)
    if s:
        _verification_sessions[session_id] = s
    return s
