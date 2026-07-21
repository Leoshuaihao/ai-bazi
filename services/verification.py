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
    _TG_TO_PATTERN,
    _resolve_five_element,
    _calc_ten_god,
    WUXING_MAP,
    # 格局派重构
    PATTERN_XIANGSHEN_RULES,
    JIUYING_TABLE,
    XIANGSHEN_DIMENSIONS,
    determine_yongshen,
    generate_xiangshen_candidates,
    check_chengbai,
    check_jiuying_v2,
    get_tiaohou_weight,
    get_fuyi_weight,
    judge_pattern_quality_v2,
    _get_xiangshen_question,
)
from services.deepseek_client import call_deepseek
from services.user_data import save_verification_session as _save_db_session
from services.user_data import load_verification_session as _load_db_session

# ============================================================
# SmartPredictionSelector 集成 — 用区分度评分驱动题目选取
# ============================================================

# 十神 → SmartPredictionSelector 类别映射
_TEN_GOD_TO_SMART_CATEGORY = {
    "正官": "事业",
    "七杀": "事业",
    "正财": "事业",
    "偏财": "事业",
    "正印": "学历",
    "偏印": "学历",
    "食神": "性格",
    "伤官": "性格",
    "比肩": "兄弟关",
    "劫财": "兄弟关",
}

# 诊断步骤 → SmartPredictionSelector 类别映射
_DIAG_STEP_TO_SMART_CATEGORY = {
    "D1": "关键年份",   # 月令被冲 → 人生突变年份
    "D2": "性格",       # 月令被合 → 双重性格
    "D3": "性格",       # 中气格局 → 性格特征不同
    "D4": "事业",       # 用神救应 → 潜力发挥
    "D5": "父母关",     # 时辰校验 → 与父母信息相关
}


def _smart_rerank_candidates(candidates, uncertainty, asked_list=None):
    """用 SmartPredictionSelector 对相神候选重新排序。

    在原有 confidence 排序基础上，叠加区分度评分作为加权因子，
    使得高区分度的候选优先被验证。

    不修改 SmartPredictionSelector 的评分逻辑，仅调用。
    """
    if not candidates:
        return candidates
    try:
        from services.predictions import SmartPredictionSelector
        selector = SmartPredictionSelector()
    except Exception:
        return candidates

    asked_set = set(asked_list or [])
    history = {
        "asked_counts": {},
        "supplement_streak": 0,
    }
    for c in candidates:
        tg = c.get("ten_god", "")
        if tg in asked_set:
            history["asked_counts"][_TEN_GOD_TO_SMART_CATEGORY.get(tg, "性格")] = \
                history["asked_counts"].get(_TEN_GOD_TO_SMART_CATEGORY.get(tg, "性格"), 0) + 1

    # 为每个候选计算区分度得分
    for c in candidates:
        tg = c.get("ten_god", "")
        category = _TEN_GOD_TO_SMART_CATEGORY.get(tg, "性格")
        score_info = selector.calculate_discrimination_score(
            {"category": category},
            uncertainty=uncertainty or {},
            history=history,
        )
        c["_smart_score"] = score_info["total"]

    # 综合排序：confidence (0-99) 权重 0.6 + smart_score (0-10)*10 权重 0.4
    candidates.sort(
        key=lambda x: x.get("confidence", 50) * 0.6 + x.get("_smart_score", 5) * 10 * 0.4,
        reverse=True,
    )
    return candidates


def _smart_rank_diag_steps(applicable_steps, uncertainty):
    """用 SmartPredictionSelector 对适用的诊断步骤重新排序。

    applicable_steps: list of step numbers (1-5) that are applicable
    Returns: reordered list of step numbers
    """
    if not applicable_steps or len(applicable_steps) <= 1:
        return applicable_steps
    try:
        from services.predictions import SmartPredictionSelector
        selector = SmartPredictionSelector()
    except Exception:
        return applicable_steps

    scored = []
    for step_num in applicable_steps:
        step_key = f"D{step_num}"
        category = _DIAG_STEP_TO_SMART_CATEGORY.get(step_key, "性格")
        score_info = selector.calculate_discrimination_score(
            {"category": category},
            uncertainty=uncertainty or {},
        )
        scored.append((step_num, score_info["total"]))

    scored.sort(key=lambda x: x[1], reverse=True)
    return [s[0] for s in scored]

# ============================================================
# LLM 系统提示词
# ============================================================

SYSTEM_PROMPT = """你是一位严格遵循《子平真诠》格局派体系的子平派命理师。

核心概念（格局派正统）：
- 用神 = 月令定格之物 = 格局本身（直接确定，不竞争）
- 相神 = 辅佐用神成格之物（顺用生护、逆用制化）
- 财官印食为四善神（财含正财偏财），顺用之（保护性使用：生之、护之）
- 杀伤枭刃为四恶神，逆用之（控制性使用：制之、化之）
- 调候法/扶抑法/通关法降级为加权因子，不独立生成候选

顺用配对（善神 → 相神角色）：
- 正官格 → 财生官(生用) + 印护官(护用)
- 正财格/偏财格 → 食伤生财(生用) + 官护财(护用)
- 正印格 → 官杀生印(生用) + 比劫护印(护用)
- 食神格 → 比劫生食(生用) + 财护食(泄用)

逆用配对（恶神 → 相神角色）：
- 七杀格 → 食神制杀(制用) + 印化杀(化用)
- 伤官格 → 印制伤官(制用) + 财泄伤官(泄用)
- 偏印格 → 财制偏印(制用)
- 月刃格 → 官杀制刃(制用)

相神六种角色：
- 生用：相神生用神（如财生官）
- 护用：相神保护用神不受克（如印护官）
- 制用：相神制约忌神（如食神制杀）
- 化用：相神转化凶神（如印化杀）
- 泄用：相神疏导旺气（如食伤泄秀）
- 顺势：相神顺应旺势（如从格顺势）

判断流程（不可颠倒）：
1. 月令定格 → 2. 用神确定 → 3. L1格局特征验证 → 4. 相神验证 → 5. 成败救应 → 6. 格局高低

成败救应：
- 成格：用神有力无破，相神配置齐全
- 败格：用神被克/混/合，需看是否有救应之神
- 救应：制忌之神存在且有力（透干有根=上等，透干无根=中等，暗藏=下等）

常见败因（按格局）：
- 正官格：伤官克官、官杀混杂、官星被合
- 正财格/偏财格：比劫夺财
- 正印格：财星破印
- 食神格：枭神夺食
- 七杀格：杀无制、财星党杀、制杀太过
- 伤官格：伤官无制、伤官见官（伤官伤尽不见官星则为贵格）
- 偏印格：枭神夺食、偏印无制
- 月刃格：阳刃无制、冲刃
- 建禄格：建禄无制
- 从弱格：印比扶身破从
- 专旺格：官杀犯旺

格局高低评判（有情×有力）：
- 有情：用神得生得助，有相神辅佐（如官格有财生印护）
- 有力：用神通根得地，气贯生旺（得月令+透干+有根气）
- 有情有力 = 上格，有情无力 = 中格，无情有力 = 中下格，无情无力 = 下格

用神变化：
- 月令本气不透→取中气余气定格（透干优先）
- 月令被冲→重新审视定格之物是否被破坏，另寻透干之物为用
- 透干变化：月令藏干透出不同则用神不同

天干五合对格局的影响：
- 甲己合土、乙庚合金、丙辛合水、丁壬合木、戊癸合火
- 用神被合（非日主自合）→败格，看合化后能否成新格
- 忌神被合→救应成格
- 日主自合财官→不为合去，不影响格局
- 合一留一→格局反清

重要典籍指引：
- 《子平真诠·论用神》：用神专求月令、顺用逆用规则
- 《子平真诠·论用神成败得失》：成败救应的完整论述
- 《子平真诠·论用神格局高低》：有情有力的评判框架
- 《子平真诠·论用神变化》：月令被合被冲后的格局变化
- 《穷通宝鉴》：调候用神（降级为加权因子）

规则:
1. 每条问题基于命盘数据和典籍理论
2. 用生活化语言，用户可能不理解命理术语
3. 用户有复杂真实情况，不要强迫选不合适选项
4. 用户持续否定时重新审视月令是否被冲/合/压制
5. 保持自然对话感"""


# 动态构建 V2 prompt：优先使用 six_step_prompt 结构化模板
_FALLBACK_V2_APPENDIX = """

## 六步推导框架

本系统采用《子平真诠》格局派六步推导法进行命盘分析：

1. **定格局** — 以月令提纲定格局类型（正格八格/从格/专旺/化气）
2. **辨用神** — 确定用神（=月令定格之物），判断顺用/逆用/顺势模式
3. **明喜忌** — 确定相神配置、喜忌五行、大运喜忌方向，检查成败救应
4. **十神定位** — 统计天干十神分布、地支根气、生克制化链条（主干，优先检查）
5. **宫位取象** — 年/月/日/时四柱对应的人事领域（分支，依赖前四步）
6. **应期锁定** — 大运成格变格效应 + 流年关键节点 + 应期推断

### 中间层主次关系

主干（优先检查）：**十神定位 + 生克制化** — 这是推导的核心，决定命局的主要趋势
分支（不过度纠缠）：**宫位取象 + 刑冲合害** — 在主干明确后展开，不纠缠分支细节

### 推导约束

- 用神专求月令，不可跨格局大类翻转
- 宫位取象必须以十神为根基，不可脱离十神单独宫位推事
- 大运效应标注"运过即止"
- 性格推断注意防范巴纳姆效应"""

# ============================================================
# SYSTEM_PROMPT_V2 — 已删除（Phase 0: V2 在 discrimination.py 中管理独立 prompt）
# ============================================================


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
# ============================================================
# PATTERN_L1_QUESTIONS — 已删除（Phase 0: V2 不用格局特征问题模板，约100行）
# ============================================================


# ============================================================
# PATTERN_L1_QUESTIONS / _get_l1_question — 已删除（Phase 0: V2 不用格局特征问题模板）
# ============================================================

# ============================================================
# DIAGNOSIS_QUESTIONS — 已删除（Phase 0: V2 不用诊断问题模板）
# ============================================================

# 品质问题模板
# ============================================================
# QUALITY_QUESTIONS — 已删除（Phase 0: V2 不用品质问题模板）
# ============================================================


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

# confidence 调整默认值（V3 静态模式用）
_DELTA_DEFAULTS = {
    "accurate": 15,
    "partial": 3,
    "inaccurate": -20,
}

# guardrail: LLM 建议的单轮 confidence 增量上限
_LLM_DELTA_MAX = 25


def _get_delta(session, answer, defaults=None):
    """获取 confidence 调整值

    混合框架核心：优先使用 LLM 建议的 delta（有 guardrail），
    否则用 defaults 中的固定值。

    - session: 验证会话（从中取出 _llm_delta 并消费）
    - answer: 归一化后的回答 (accurate/partial/inaccurate)
    - defaults: 自定义默认值字典，None 时用 _DELTA_DEFAULTS
    """
    llm_delta = session.pop("_llm_delta", None)
    if llm_delta is not None:
        try:
            return max(-_LLM_DELTA_MAX, min(_LLM_DELTA_MAX, int(llm_delta)))
        except (ValueError, TypeError):
            pass
    d = defaults or _DELTA_DEFAULTS
    return d.get(answer, 0)


# ============================================================
# _get_quality_question / QUALITY_QUESTIONS — 已删除（Phase 0: V2 不用品质问题模板）
# ============================================================


# ============================================================
# init_verification (V3)
# ============================================================

def init_verification(chart_data: dict, user_id: str = None, uncertainty: dict = None) -> dict:
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

    # Step 4 (新增): 确定用神（=月令定格之物，直接确定，不竞争）
    final_pattern = step_results["pattern"]
    yongshen = determine_yongshen(final_pattern, dm_stem, month_branch, chart_data)
    step_results["yongshen"] = yongshen

    # Step 5 (新增): 生成相神候选（按顺用/逆用规则）
    xiangshen_candidates = generate_xiangshen_candidates(final_pattern, dm_stem, chart_data)
    step_results["xiangshen_candidates"] = xiangshen_candidates

    # Phase 0: L1 问题生成已删除。V2 使用 discrimination.py 替代。
    final_pattern = step_results["pattern"]

    first_question = {
        "round": 1, "layer": "L1",
        "question": f"系统判定你的格局为{final_pattern}（旺衰={wangshuai['level']}），请使用 V2 断前事流程进行验证。",
        "explanation": "V2 已废弃旧 L1 问题模板",
        "options": ["是", "不是", "记不清了"],
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
        "quality_youqing": None,
        "quality_youli": None,
        "diagnosis_count": 0,
        "diagnosis_sub_stage": 1,
        "diagnosis_path": [],
        # 格局派重构：用神/相神/成败救应
        "yongshen": yongshen,  # 用神 = 月令定格之物（直接确定）
        "xiangshen_candidates": xiangshen_candidates,  # 相神候选列表
        "confirmed_xiangshen": None,  # 验证后确认的相神
        "chengbai_result": None,  # 成败检测结果
        "jiuying_result": None,  # 救应检测结果
        "chengbai_status": None,  # 成格/败格有救/败格无救
        "history": [],
        "current_question": first_question,
        "_created_at": datetime.now().timestamp(),
        # SmartPredictionSelector 集成：存储不确定性报告供后续选题使用
        "uncertainty": uncertainty,
    }

    # 不确定性驱动的初始置信度调整
    if uncertainty:
        overall_risk = uncertainty.get("overall_risk", 0.0)
        if overall_risk > 0.6:
            session["confidence"] = max(10, session["confidence"] - 10)
        elif overall_risk > 0.3:
            session["confidence"] = max(15, session["confidence"] - 5)

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

    # === 混合框架：静态管流程，LLM 管内容 ===

    # 1. LLM 解读自由文本（如有）→ 得到 mapped_answer + delta
    if _has_llm() and note:
        llm_result = await _llm_interpret(session, answer, note)
        if llm_result:
            answer = llm_result.get("mapped_answer", answer)
            session["_llm_delta"] = llm_result.get("delta", 0)
            if llm_result.get("extracted_facts"):
                session.setdefault("_llm_facts", []).extend(llm_result["extracted_facts"])
        else:
            # LLM 解读失败 → 降级为 partial（中间值，不偏不倚）
            answer = "partial"

    # 2. V2 已废弃旧 handler。旧流程不再走 dispatch_static。
    #    新流程请使用 services/discrimination.py::init_verification_v2()
    result = {
        "locked": True,
        "stage": "done",
        "message": "V2 已废弃旧验证流程。请使用 POST /api/predictions/start (V2) 启动新流程。",
        "question": None,
    }

    # 3. 清理 LLM 临时数据
    session.pop("_llm_delta", None)

    return result


async def _llm_interpret(session, answer, note):
    """LLM 解读用户自由文本回答 — 返回 mapped_answer + delta

    混合框架：LLM 只负责解读，不控制流程。
    delta 是对当前被验证对象（格局/相神）的信心调整建议。
    """
    facts = session.get("_llm_facts", [])
    history = _format_chat_history(session)
    pattern = session.get("pattern", "")
    wangshuai = session.get("step_results", {}).get("wangshuai", {})
    cq = session.get("current_question", {})
    sub = session.get("sub_stage", "L1")
    yongshen = session.get("yongshen", {})

    # 相神阶段传入候选列表
    candidates_info = ""
    if sub.startswith("xs_"):
        cands = session.get("xiangshen_candidates", [])
        target = cq.get("target_xiangshen", "")
        candidates_info = "\n".join([
            f"- {c['ten_god']}({c['five_element']}): confidence={c['confidence']}, way={c.get('gong_way','')}"
            + (" ← 当前验证" if c['ten_god'] == target else "")
            for c in cands[:5]
        ])

    ys_info = f"用神={yongshen.get('ten_god','')}({yongshen.get('five_element','')}), 模式={yongshen.get('mode','')}" if yongshen else ""

    # 动态典籍检索（与 _llm_enhance_question 共享同一逻辑）
    classical = _get_classical_reference(session, sub)

    candidates_line = f"当前相神候选:\n{candidates_info}" if candidates_info else ""
    prompt = f"""用户八字: {pattern}格, 旺衰={wangshuai.get('level','?')}
{f"用神: {ys_info}" if ys_info else ""}
当前阶段: {sub}
{candidates_line}

典籍参考:
{classical}

对话历史:
{history}

你刚才问的问题: {cq.get('question','')}
用户回答: {answer}
用户补充说明: {note}

已知事实: {', '.join(facts) if facts else '无'}

请基于典籍理论解读用户回答，输出JSON(不要markdown标记):
{{"mapped_answer":"accurate|partial|inaccurate","delta":-25到25的整数,"extracted_facts":[""],"internal":"你的命理分析"}}

delta含义:
- 正数=用户回答支持当前方向（+25=强烈支持, +15=支持, +5=微弱支持）
- 负数=用户回答否定当前方向（-25=强烈否定, -15=否定, -5=微弱否定）
- 0=不确定或中立

注意: delta是对当前被验证的相神/格局的信心调整值。"""
    content = await _llm_ask(SYSTEM_PROMPT, prompt, 250)
    if not content:
        return None
    try:
        result = json.loads(content)
        try:
            result["delta"] = int(result.get("delta", 0))
        except (ValueError, TypeError):
            result["delta"] = 0
        return result
    except Exception:
        return {"mapped_answer": answer, "delta": 0, "extracted_facts": [note]}


# ============================================================
# _llm_enhance_question — 已删除（Phase 0: V2 由 discrimination.py 统一管理 AI 出题）
# ============================================================


def _clean_classical_text(text: str) -> str:
    """清理典籍文本中的噪音：DB元数据、现代摘要、多余空行"""
    import re
    # 去掉 "## 核心要点" 及之后的所有内容（现代摘要，非古籍原文，AI会误引）
    text = re.sub(r'\n## 核心要点.*', '', text, flags=re.DOTALL)
    # 去掉 DB 元数据尾注
    text = re.sub(r'\n---\n版本：.*', '', text, flags=re.DOTALL)
    text = re.sub(r'\n录入日期：.*', '', text)
    text = re.sub(r'\n用途：RAG检索.*', '', text)
    # 压缩连续空行
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _get_classical_reference(session, stage: str = "pattern") -> str:
    """使用项目 RAG 检索器（FTS5 全文检索 281 章典籍）"""
    from services.rag_retriever import retrieve_by_stage

    pattern = session.get("pattern", "")
    chart = session.get("chart_data", {})
    sr = session.get("step_results", {})

    # 将验证阶段映射到 RAG 阶段（格局派重构后）
    rag_stage = "pattern"
    if stage.startswith("xs_"):
        # 相神验证阶段 → 检索相神/顺用/逆用相关典籍
        rag_stage = "xiangshen"
    elif stage.startswith("jiuying_") or stage == "chengbai":
        # 成败救应阶段 → 检索成败/救应相关典籍
        rag_stage = "chengbai"
    elif stage.startswith("quality_"):
        # 格局高低阶段 → 检索有情/有力相关典籍
        rag_stage = "quality"

    dm = chart.get("day_master", "")
    dm_wx = _get_wuxing(dm)
    month_branch = sr.get("wangshuai", {}).get("level", "") or \
                   chart.get("four_pillars", {}).get("month", {}).get("branch", "")

    try:
        keywords = [pattern.replace("格", "")]
        if stage.startswith("xs_"):
            keywords.extend(["相神", "顺用", "逆用", "用神", "辅佐", "成格"])
        elif stage.startswith("jiuying_") or stage == "chengbai":
            keywords.extend(["成败", "救应", "破格", "败因"])
            # 增加具体败因关键词
            defeat_causes = session.get("defeat_causes", [])
            if defeat_causes:
                keywords.extend(defeat_causes)
        elif stage.startswith("quality_"):
            keywords.extend(["有情", "有力", "生扶", "通根", "格局高低"])

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
                txt = r.get("text", r.get("excerpt", ""))
                txt = _clean_classical_text(txt)
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


# ============================================================
# _dispatch_static — 已删除（Phase 0: V2 不使用旧路由）
# ============================================================


# ============================================================
# L1 / Purity Handler — 已删除（Phase 0: V2 不使用旧的 L1 格局特征问答）
# ============================================================


# ============================================================
# 相神验证 / 成败救应 / 格局高低 — 已删除（Phase 0: V2 由 discrimination.py + feedback_adjuster.py 替代）
# ============================================================


# ============================================================
# 诊断链 — 已删除（Phase 0: V2 不使用旧诊断/相神/成败 handler）
# ============================================================


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
