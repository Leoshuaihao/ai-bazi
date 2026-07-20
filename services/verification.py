"""逐步验证收敛模块 — 子平格局派 V2

V2 核心变化：
1. 格局/用神分离验证：先锁定格局（Phase 1），再锁定用神（Phase 2）
2. 完全分类：14种格局全部进假设空间，用神覆盖十神全集的合法子集
3. 拒绝检测 + 空间扩展：持续否定时自动扩展搜索空间
4. L1 改为2条广义分类问题，可批量排除4-6种格局

流程：
- L1: 2条广义分类问题（authority + pragmatism）
- L2-L5: 格局区分验证（AI生成）
- L6-L8: 用神验证（格局锁后独立收敛）
- 格局/用神任何阶段触发拒绝检测 → 空间扩展
"""

import os
import re
import uuid
import asyncio
from datetime import datetime
from typing import Optional

from rules.pattern import (
    generate_full_pattern_space,
    generate_yongshen_candidates,
    update_confidence,
    update_confidence_broad,
    L1_BROAD_QUESTIONS,
    ALL_STANDARD_PATTERNS,
    ALL_SPECIAL_PATTERNS,
)
from services.deepseek_client import call_deepseek
from services.user_data import save_verification_session as _save_db_session
from services.user_data import load_verification_session as _load_db_session


# ============================================================
# 会话管理
# ============================================================

_verification_sessions = {}
_SESSION_TTL_SECONDS = 1800


def _cleanup_expired_sessions():
    now = datetime.now().timestamp()
    expired = [
        sid for sid, s in _verification_sessions.items()
        if now - s.get("_created_at", 0) > _SESSION_TTL_SECONDS
    ]
    for sid in expired:
        del _verification_sessions[sid]


# ============================================================
# 初始化（V2完全分类）
# ============================================================

def init_verification(chart_data: dict, user_id: str = None) -> dict:
    _cleanup_expired_sessions()
    session_id = str(uuid.uuid4())

    dm_stem = _extract_day_master_stem(chart_data)
    month_branch = _extract_month_branch(chart_data)
    strength_detail = chart_data.get("strength_detail", {})
    four_pillars = chart_data.get("four_pillars", {})

    hypotheses = generate_full_pattern_space(
        dm_stem, month_branch, strength_detail, four_pillars
    )

    l1_q = L1_BROAD_QUESTIONS[0]
    first_question = {
        "round": 1,
        "layer": "L1",
        "question": l1_q["question"],
        "explanation": l1_q["explanation"],
        "options": l1_q["options"],
        "_l1_id": l1_q["id"],
        "_l1_index": 0,
    }

    session = {
        "session_id": session_id,
        "user_id": user_id,
        "chart_data": chart_data,
        "hypotheses": hypotheses,
        "round": 1,
        "stage": "pattern",
        "locked_pattern": None,
        "locked_yongshen": None,
        "yongshen_candidates": None,
        "expansion_count": 0,
        "max_expansions": 2,
        "l1_answered": 0,
        "history": [],
        "current_question": first_question,
        "_created_at": datetime.now().timestamp(),
        "_prev_top_pattern": "",
        "_prev_top_yongshen": "",
        "_pattern_consecutive": 0,
        "_yongshen_consecutive": 0,
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
        "hypotheses": hypotheses,
        "question": first_question,
    }


# ============================================================
# 反馈处理（V2核心分发）
# ============================================================

_ANSWER_NORMALIZE = {
    "很像": "accurate", "有点出入": "partial", "完全不像": "inaccurate",
    "是的": "accurate", "不太确定": "partial", "不是": "inaccurate",
    "带头推动": "accurate", "偏向创作": "inaccurate", "不太好说": "partial",
    "务实重结果": "accurate", "重学习修养": "inaccurate",
}


async def process_verification(session_id: str, answer: str, note: str = "") -> dict:
    answer = _ANSWER_NORMALIZE.get(answer, answer)

    _cleanup_expired_sessions()
    session = _verification_sessions.get(session_id)
    if not session:
        return {"error": "会话不存在或已过期"}

    current_question = session.get("current_question", {})
    stage = session.get("stage", "pattern")

    session["history"].append({
        "round": session["round"],
        "stage": stage,
        "question": current_question.get("question", ""),
        "answer": answer,
        "note": note,
    })

    if stage == "pattern":
        return await _handle_pattern_stage(session, answer)
    elif stage == "yongshen":
        return await _handle_yongshen_stage(session, answer)
    else:
        return {"error": "无效的会话阶段"}


# ============================================================
# Phase 1: 格局验证
# ============================================================

async def _handle_pattern_stage(session: dict, answer: str) -> dict:
    l1_index = session.get("l1_answered", 0)
    hypotheses = session["hypotheses"]

    # L1: 广义分类问题（最多2条）
    if l1_index < len(L1_BROAD_QUESTIONS):
        l1_q = L1_BROAD_QUESTIONS[l1_index]
        mapping = l1_q["mapping"].get(answer, {})
        if mapping:
            hypotheses = update_confidence_broad(hypotheses, answer, mapping)
        session["l1_answered"] = l1_index + 1

        if session["l1_answered"] < len(L1_BROAD_QUESTIONS):
            next_l1 = L1_BROAD_QUESTIONS[session["l1_answered"]]
            next_q = {
                "round": session["round"] + 1,
                "layer": "L1",
                "question": next_l1["question"],
                "explanation": next_l1["explanation"],
                "options": next_l1["options"],
                "_l1_id": next_l1["id"],
                "_l1_index": session["l1_answered"],
            }
            session["round"] += 1
            session["hypotheses"] = hypotheses
            session["current_question"] = next_q
            return {
                "locked": False, "stage": "pattern",
                "question": next_q,
                "hypotheses": sorted(hypotheses, key=lambda x: x["confidence"], reverse=True),
            }

    # L2+: 格局区分验证
    # 先更新置信度（针对上一题的目标格局）
    prev_q = session.get("current_question", {})
    target = prev_q.get("target_pattern", "")
    if target:
        hypotheses = update_confidence(hypotheses, answer, {"pattern": target})

    sorted_h = sorted(hypotheses, key=lambda x: x["confidence"], reverse=True)
    session["hypotheses"] = sorted_h
    session["round"] += 1

    locked = _check_pattern_lock(session, sorted_h)
    if locked:
        return await _enter_yongshen_stage(session, sorted_h)

    rejection = check_rejection(session)
    if rejection:
        session["hypotheses"] = await _expand_pattern_space(session)
        sorted_h = session["hypotheses"]

    next_q = await _generate_pattern_diff_question(session)
    session["current_question"] = next_q

    return {
        "locked": False, "stage": "pattern",
        "question": next_q,
        "hypotheses": sorted_h,
    }


def _check_pattern_lock(session: dict, sorted_h: list) -> dict | None:
    if not sorted_h:
        return None
    top = sorted_h[0]
    second = sorted_h[1] if len(sorted_h) > 1 else None

    # L1的2条 + 至少1条L2 → 最少第3轮
    if session["round"] < 3:
        return None

    if top["confidence"] >= 60:
        if second is None or top["confidence"] - second["confidence"] >= 25:
            return top

    prev_top = session.get("_prev_top_pattern", "")
    if prev_top == top["pattern"] and top["confidence"] >= 50:
        consecutive = session.get("_pattern_consecutive", 0) + 1
        session["_pattern_consecutive"] = consecutive
        if consecutive >= 3:
            return top
    else:
        session["_pattern_consecutive"] = 1

    if session["round"] >= 7:
        return top

    session["_prev_top_pattern"] = top["pattern"]
    return None


# ============================================================
# Phase 2: 用神验证
# ============================================================

async def _enter_yongshen_stage(session: dict, sorted_patterns: list) -> dict:
    locked_pattern = sorted_patterns[0]

    chart_data = session["chart_data"]
    dm_stem = _extract_day_master_stem(chart_data)
    month_branch = _extract_month_branch(chart_data)
    strength_detail = chart_data.get("strength_detail", {})
    history = session.get("history", [])

    session["stage"] = "yongshen"
    session["locked_pattern"] = {
        "pattern": locked_pattern["pattern"],
        "pattern_type": locked_pattern.get("pattern_type", "正格"),
        "confidence": locked_pattern["confidence"],
    }

    yongshen_candidates = generate_yongshen_candidates(
        locked_pattern["pattern"], dm_stem, strength_detail, month_branch, history
    )
    session["yongshen_candidates"] = yongshen_candidates
    session["_yongshen_consecutive"] = 0

    if not yongshen_candidates:
        return await _rollback_pattern(session)

    top_ys = yongshen_candidates[0]
    first_q = {
        "round": session["round"],
        "layer": f"L{session['round']}",
        "stage": "yongshen",
        "question": top_ys.get("dim_question", f"请描述与{top_ys['yong_shen']}相关的经历"),
        "explanation": f"验证用神 {top_ys['yong_shen']}({top_ys['five_element']})",
        "options": ["是的", "不太确定", "不是"],
        "target_yongshen": top_ys["yong_shen"],
    }
    session["current_question"] = first_q

    return {
        "locked": False, "stage": "yongshen",
        "question": first_q,
        "yongshen_candidates": yongshen_candidates,
        "locked_pattern": session["locked_pattern"],
    }


async def _handle_yongshen_stage(session: dict, answer: str) -> dict:
    candidates = session.get("yongshen_candidates", [])
    current_q = session.get("current_question", {})
    target_ys = current_q.get("target_yongshen", "")

    for c in candidates:
        is_target = c["yong_shen"] == target_ys
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

    for c in candidates:
        c["confidence"] = max(1.0, min(99.0, c["confidence"]))

    candidates.sort(key=lambda x: x["confidence"], reverse=True)
    session["yongshen_candidates"] = candidates
    session["round"] += 1

    locked = _check_yongshen_lock(session, candidates)
    if locked:
        return _finalize(session, candidates)

    rejection = check_rejection(session)
    if rejection:
        if session.get("expansion_count", 0) >= session.get("max_expansions", 2):
            return await _rollback_pattern(session)
        session["yongshen_candidates"] = await _expand_yongshen_space(session)
        candidates = session["yongshen_candidates"]

    next_q = _generate_next_yongshen_question(session, candidates)
    session["current_question"] = next_q

    return {
        "locked": False, "stage": "yongshen",
        "question": next_q,
        "yongshen_candidates": candidates,
        "locked_pattern": session["locked_pattern"],
    }


def _check_yongshen_lock(session: dict, candidates: list) -> dict | None:
    if not candidates:
        return None
    top = candidates[0]
    second = candidates[1] if len(candidates) > 1 else None

    yongshen_rounds = sum(1 for h in session["history"] if h.get("stage") == "yongshen")
    if yongshen_rounds < 2:
        return None

    if top["confidence"] >= 65:
        if second is None or top["confidence"] - second["confidence"] >= 20:
            return top

    prev_top = session.get("_prev_top_yongshen", "")
    if prev_top == top["yong_shen"] and top["confidence"] >= 55:
        consecutive = session.get("_yongshen_consecutive", 0) + 1
        session["_yongshen_consecutive"] = consecutive
        if consecutive >= 2:
            return top
    else:
        session["_yongshen_consecutive"] = 1

    if yongshen_rounds >= 7:
        return top

    session["_prev_top_yongshen"] = top["yong_shen"]
    return None


def _finalize(session: dict, candidates: list) -> dict:
    locked = session["locked_pattern"]
    top_ys = candidates[0]
    session["stage"] = "locked"
    session["locked_yongshen"] = top_ys

    return {
        "locked": True, "stage": "done",
        "rounds": session["round"],
        "result": {
            "pattern": locked["pattern"],
            "pattern_confidence": locked["confidence"],
            "yong_shen": top_ys["yong_shen"],
            "yongshen_confidence": top_ys["confidence"],
            "five_element": top_ys["five_element"],
            "gong_way": top_ys["gong_way"],
            "pattern_type": locked.get("pattern_type", "正格"),
        },
        "hypotheses": candidates,
        "expansion_attempted": session.get("expansion_count", 0) > 0,
        "total_rounds": session["round"],
    }


# ============================================================
# 拒绝检测与空间扩展
# ============================================================

def check_rejection(session: dict) -> str | None:
    history = session["history"]
    if len(history) < 3:
        return None

    recent = history[-3:]
    if all(h["answer"] == "inaccurate" for h in recent):
        return "consecutive_rejection"

    stage_specific = [h for h in history if h.get("stage") == session.get("stage")]
    if len(stage_specific) >= 3:
        accurate_rate = sum(1 for h in stage_specific if h["answer"] == "accurate") / len(stage_specific)
        if accurate_rate < 0.3:
            return "low_accuracy"

    hypotheses = session.get("hypotheses") or session.get("yongshen_candidates") or []
    if hypotheses and max(h["confidence"] for h in hypotheses) < 30:
        return "all_low_confidence"

    return None


async def _expand_pattern_space(session: dict) -> list:
    count = session.get("expansion_count", 0)
    if count >= session.get("max_expansions", 2):
        return session["hypotheses"]

    session["expansion_count"] = count + 1
    chart_data = session["chart_data"]
    existing = {h["pattern"] for h in session["hypotheses"]}
    history = session.get("history", [])

    # 尝试 AI 推荐新格局
    if os.getenv("DEEPSEEK_API_KEY"):
        try:
            suggested = await _ai_suggest_patterns(chart_data, history, existing)
            if suggested:
                for s in suggested:
                    if s.get("pattern") not in existing:
                        session["hypotheses"].append({
                            "pattern": s["pattern"],
                            "pattern_type": s.get("pattern_type", "正格"),
                            "confidence": s.get("confidence", 15),
                        })
        except Exception:
            pass

    # 提升已有的低分格局权重
    for h in session["hypotheses"]:
        if h["confidence"] < 10:
            h["confidence"] = min(h["confidence"] + 8, 15)

    return session["hypotheses"]


async def _expand_yongshen_space(session: dict) -> list:
    count = session.get("expansion_count", 0)
    if count >= session.get("max_expansions", 2):
        return session.get("yongshen_candidates", [])

    session["expansion_count"] = count + 1

    locked_pattern = session["locked_pattern"]["pattern"]
    chart_data = session["chart_data"]
    dm_stem = _extract_day_master_stem(chart_data)
    month_branch = _extract_month_branch(chart_data)
    strength_detail = chart_data.get("strength_detail", {})

    new_candidates = generate_yongshen_candidates(
        locked_pattern, dm_stem, strength_detail, month_branch,
        session.get("history", [])
    )
    # 给新增候选额外加分
    for c in new_candidates:
        c["confidence"] = min(c["confidence"] + 10, 40)

    session["yongshen_candidates"] = new_candidates
    return new_candidates


async def _rollback_pattern(session: dict) -> dict:
    """用神验证持续失败 → 怀疑格局错了 → 回退"""
    chart_data = session["chart_data"]
    dm_stem = _extract_day_master_stem(chart_data)
    month_branch = _extract_month_branch(chart_data)
    strength_detail = chart_data.get("strength_detail", {})
    four_pillars = chart_data.get("four_pillars", {})
    history = session.get("history", [])

    session["stage"] = "pattern"
    session["expansion_count"] = session.get("expansion_count", 0) + 1

    hypotheses = generate_full_pattern_space(
        dm_stem, month_branch, strength_detail, four_pillars
    )
    # 提升非月令格局权重（因为月令格局可能错了）
    for h in hypotheses:
        if not h.get("_month_main"):
            h["confidence"] = min(h["confidence"] + 10, 25)

    if os.getenv("DEEPSEEK_API_KEY"):
        existing = {h["pattern"] for h in hypotheses}
        try:
            suggested = await _ai_suggest_patterns(chart_data, history, existing)
            if suggested:
                for s in suggested:
                    if s.get("pattern") not in existing:
                        hypotheses.append({
                            "pattern": s["pattern"],
                            "pattern_type": s.get("pattern_type", "正格"),
                            "confidence": s.get("confidence", 20),
                        })
        except Exception:
            pass

    session["hypotheses"] = hypotheses
    session["round"] += 1

    next_q = {
        "round": session["round"],
        "layer": f"L{session['round']}",
        "question": "之前的问题似乎都不太符合你的情况。让我们换个角度——能否用一句话描述你的做事风格或人生中最突出的特点？",
        "explanation": "格局回退，需要重新探索",
        "options": ["有道理，让我补充", "不对，换个方向"],
    }
    session["current_question"] = next_q

    return {
        "locked": False, "stage": "pattern",
        "question": next_q,
        "hypotheses": sorted(hypotheses, key=lambda x: x["confidence"], reverse=True),
        "rollback": True,
    }


# ============================================================
# 问题生成
# ============================================================

async def _generate_pattern_diff_question(session: dict) -> dict:
    """生成格局区分验证问题"""
    sorted_h = session["hypotheses"]
    chart_data = session["chart_data"]
    dm = chart_data.get("day_master", "")
    history = session.get("history", [])

    top_2 = sorted_h[:2]
    if len(top_2) < 2:
        return _make_fallback_q(session["round"])

    # 尝试AI生成
    if os.getenv("DEEPSEEK_API_KEY"):
        try:
            confirmed, disproved = _format_history_for_prompt(history)
            prompt = f"""你是子平格局派命理师。正在验证命盘的格局。

日主: {dm}
当前最高格局假设:
A: {top_2[0]['pattern']}（置信度{top_2[0]['confidence']}%）
B: {top_2[1]['pattern']}（置信度{top_2[1]['confidence']}%）
{confirmed}
{disproved}

请设计一个能有效区分格局A和格局B的问题。问一个在格局A命主身上成立、但在格局B命主身上不成立的特征。
只输出问题本身，不要JSON不要解释。用户能用「是的/不太确定/不是」回答。"""
            content = await call_deepseek(prompt=prompt, system_prompt="你是子平格局派命理师", timeout=12, temperature=0.3, max_tokens=150)
            if content and not content.startswith("[API_"):
                return {
                    "round": session["round"], "layer": f"L{session['round']}",
                    "stage": "pattern", "question": content.strip(),
                    "options": ["是的", "不太确定", "不是"],
                    "target_pattern": sorted_h[0]["pattern"],
                }
        except Exception:
            pass

    # 无AI时用规则生成区分问题
    return _make_pattern_diff_rule_q(session["round"], top_2)


def _make_pattern_diff_rule_q(round_num: int, top_2: list) -> dict:
    """规则引擎生成格局区分问题（无AI兜底）"""
    a, b = top_2[0]["pattern"], top_2[1]["pattern"]

    # 格局区分模板：一问能排除一半
    diff_pairs = {
        ("正官格", "七杀格"): "你是否在压力和挑战下反而能激发潜能，而不是更倾向按规则稳步前进？",
        ("七杀格", "正官格"): "你是否在压力和挑战下反而能激发潜能，而不是更倾向按规则稳步前进？",
        ("正印格", "偏印格"): "你是否更喜欢广泛学习而非深入一个领域钻研？",
        ("偏印格", "正印格"): "你是否更喜欢广泛学习而非深入一个领域钻研？",
        ("正财格", "偏财格"): "你理财是偏向稳健积蓄还是敢于投资博取更大回报？",
        ("偏财格", "正财格"): "你理财是偏向稳健积蓄还是敢于投资博取更大回报？",
        ("食神格", "伤官格"): "你的创造力是温和输出还是锋芒毕露？",
        ("伤官格", "食神格"): "你的创造力是温和输出还是锋芒毕露？",
    }
    key = (a, b)
    if key in diff_pairs:
        q = diff_pairs[key]
    else:
        q = f"下面两种描述，哪个更符合你——A: 更注重结果和实际利益  B: 更注重过程和自我提升？"

    return {
        "round": round_num, "layer": f"L{round_num}",
        "stage": "pattern",
        "question": q,
        "options": ["是的(A)", "更偏(B)", "不太好说"],
        "target_pattern": a,
    }


def _generate_next_yongshen_question(session: dict, candidates: list) -> dict:
    """生成用神验证问题"""
    chart_data = session["chart_data"]
    dm = chart_data.get("day_master", "")

    # 找下一个未问过的用神
    asked = set()
    for h in session.get("history", []):
        q = h.get("question", "")
        for c in candidates:
            if c["yong_shen"] in q:
                asked.add(c["yong_shen"])

    for c in candidates:
        if c["yong_shen"] not in asked:
            return {
                "round": session["round"], "layer": f"L{session['round']}",
                "stage": "yongshen",
                "question": c.get("dim_question", f"{c['yong_shen']}作为用神在哪些方面体现？"),
                "explanation": f"验证用神 {c['yong_shen']}({c['five_element']}) — {c.get('dimension', '综合')}",
                "options": ["是的", "不太确定", "不是"],
                "target_yongshen": c["yong_shen"],
            }

    # 所有用神都问过一遍了，返回兜底
    top = candidates[0]
    return {
        "round": session["round"], "layer": f"L{session['round']}",
        "stage": "yongshen",
        "question": f"综合来看，{top['yong_shen']}({top['five_element']})作为用神是否最贴合你的实际经历？",
        "explanation": "最后一轮综合确认",
        "options": ["是的", "不太确定", "不是"],
        "target_yongshen": top["yong_shen"],
    }


def _make_fallback_q(round_num: int) -> dict:
    fallbacks = [
        "请简单描述你的性格特征或处事风格。",
        "在团队中你通常扮演什么角色？",
        "面对压力时你通常如何应对？",
        "你觉得自己最大的优势是什么？",
        "工作中你喜欢独当一面还是配合他人？",
        "回头看过去几年，哪个决定对你影响最大？",
    ]
    idx = (round_num - 3) % len(fallbacks)  # L3 起用
    return {
        "round": round_num, "layer": f"L{round_num}",
        "stage": "pattern",
        "question": fallbacks[max(0, min(idx, len(fallbacks) - 1))],
        "explanation": "格局待确认",
        "options": ["是的", "不太确定", "不是"],
        "target_pattern": "",
    }


async def _ai_suggest_patterns(chart_data, history, existing) -> list:
    """AI推荐被遗漏的格局候补"""
    dm = chart_data.get("day_master", "")
    confirmed, disproved = _format_history_for_prompt(history)
    prompt = f"""用户在格局验证中持续否定当前假设。请根据以下信息推荐可能的格局候补。

日主: {dm}
当前已排除/否定:
{disproved}
用户确认:
{confirmed}

请推荐2-3个可能的格局（从标准八格或特殊格局中选择），每个给出置信度和理由。
输出JSON: [{{"pattern": "格局名", "pattern_type": "正格/从格/专旺", "confidence": 20}}]"""
    try:
        content = await call_deepseek(prompt=prompt, system_prompt="你是子平格局派命理师，输出JSON数组", timeout=12, temperature=0.3, max_tokens=300)
        if content and not content.startswith("[API_"):
            import json
            return json.loads(content) if isinstance(content, str) else content
    except Exception:
        pass
    return []


# ============================================================
# 辅助函数
# ============================================================

def _extract_day_master_stem(chart_data: dict) -> str:
    dm = chart_data.get("day_master", "")
    return dm[-1] if dm else "甲"

def _extract_month_branch(chart_data: dict) -> str:
    fp = chart_data.get("four_pillars", {})
    month = fp.get("month", {})
    return month.get("branch", "子")

def _format_history_for_prompt(history: list) -> tuple:
    if not history:
        return "", ""
    confirmed, disproved = [], []
    for idx, h in enumerate(history):
        role = h.get("answer", "")
        q = h.get("question", "")
        n = h.get("note", "")
        stage = h.get("stage", "")
        line = f"第{h.get('round', idx + 1)}轮[{stage}]"
        if q:
            line += f": {q[:60]}"
        line += f" → {'✅命中' if role == 'accurate' else '⚠️部分' if role == 'partial' else '❌否定'}"
        if n:
            line += f" (补充: {n})"
        if role == "accurate":
            confirmed.append(line)
        elif role == "inaccurate":
            disproved.append(line)
    return "\n".join(confirmed), "\n".join(disproved)

def get_session(session_id: str) -> dict | None:
    _cleanup_expired_sessions()
    return _verification_sessions.get(session_id)

async def get_session_async(session_id: str) -> dict | None:
    _cleanup_expired_sessions()
    s = _verification_sessions.get(session_id)
    if s:
        return s
    s = await _load_db_session(session_id)
    if s:
        _verification_sessions[session_id] = s
    return s
