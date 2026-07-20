"""逐步验证收敛模块 V3 — 子平派典籍诊断树

流程:
Step1: 月令定格局 → Step2: 透干会支检查 → Step3: 旺衰五等
L1: 格局特征验证 → 纯杂检查 → Phase2: 品质判断(有情×有力)
→ 锁定 / 诊断链(D1-D5) / Phase3: 用神验证(四法)
"""

import os
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
)
from services.deepseek_client import call_deepseek
from services.user_data import save_verification_session as _save_db_session
from services.user_data import load_verification_session as _load_db_session

# ============================================================
# L1 格局特征问题（来自典籍原文，不变）
# ============================================================

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

    # L1 question
    final_pattern = step_results["pattern"]
    l1 = PATTERN_L1_QUESTIONS.get(final_pattern,
          {"question": "请描述一下你的性格特点？", "explanation": "", "pattern_feature": ""})

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
        "purity": None,
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

    sub = session.get("sub_stage", "L1")

    if sub == "L1":
        return await _handle_L1(session, answer)
    elif sub == "purity":
        return await _handle_purity(session, answer)
    elif sub == "phase2_L2":
        return await _handle_phase2_L2(session, answer)
    elif sub == "phase2_L3":
        return await _handle_phase2_L3(session, answer)
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

    if session["quality"] == "下格":
        if l1 == "High":
            # L1是A但品质是下格: 格局对但用神全错
            session["yongshen_regeneration"] = 1
            return await _enter_yongshen(session)
        else:
            return await _enter_diagnosis(session)
    else:
        return await _enter_yongshen(session)


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
