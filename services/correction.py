"""P1 Phase 2: 双路径修正模块

路径一：时钟修正（hour_fix）
  - 生成候选时钟（±1, ±2，共4个）
  - 对每个候选时钟重新排盘、生成断事
  - 多时钟对比，推荐最佳时钟

路径二：AI判断修正（ai_fix）
  - fix_wangshuai: 从反角度重新判断旺衰
  - fix_pattern: 正格↔从格切换
  - fix_yongshen_priority: 对比三个角度准确率
"""

import os
import json
from typing import Optional

from models import BirthInfo
from services.calibration import judge_core_gates
from services.deepseek_client import call_deepseek


# ============================================================
# 时辰对照表
# ============================================================

SHICHEN_NAMES = [
    "子时", "丑时", "寅时", "卯时", "辰时", "巳时",
    "午时", "未时", "申时", "酉时", "戌时", "亥时",
]

# 每个时辰对应的 hour 值（24小时制，取中间值）
SHICHEN_HOUR_MAP = {
    0: "子时", 1: "丑时", 2: "丑时",
    3: "寅时", 4: "寅时",
    5: "卯时", 6: "卯时",
    7: "辰时", 8: "辰时",
    9: "巳时", 10: "巳时",
    11: "午时", 12: "午时",
    13: "未时", 14: "未时",
    15: "申时", 16: "申时",
    17: "酉时", 18: "酉时",
    19: "戌时", 20: "戌时",
    21: "亥时", 22: "亥时",
    23: "子时",
}


def get_shichen_name(hour: int) -> str:
    """根据小时获取时辰名称"""
    return SHICHEN_HOUR_MAP.get(hour, SHICHEN_NAMES[0])


# ============================================================
# 路径一：时钟修正
# ============================================================

def generate_candidate_hours(current_hour: int) -> list[int]:
    """
    生成候选时钟：原始时钟 ±1, ±2，循环取模，排除原始时钟自身，返回4个候选。

    Args:
        current_hour: 当前出生小时（0-23）

    Returns:
        4个候选小时列表，按偏移顺序排列 [-2, -1, +1, +2]
    """
    candidates = []
    for offset in [-2, -1, 1, 2]:
        h = (current_hour + offset) % 24
        candidates.append(h)
    return candidates


async def try_candidate_hours(
    birth_info: dict,
    feedbacks: list[dict],
    predictions: list[dict],
) -> dict:
    """
    对每个候选时钟重新排盘、生成断事，用原有反馈计算准确率。

    有 DEEPSEEK_API_KEY 时使用 AI 生成断事，无 Key 时使用 Mock 模板生成。

    Args:
        birth_info: 出生信息 {"year": int, "month": int, "day": int, "hour": int, "minute": int, "gender": str}
        feedbacks: 用户原始反馈列表
        predictions: 原始推断列表（用于对比）

    Returns:
        {
            "original_hour": int,
            "original_shichen": str,
            "comparisons": [...],
            "recommended": str,
            "recommended_hour": int,
            "all_failed": bool,
        }
    """
    from bazi_engine import calculate_bazi

    original_hour = birth_info.get("hour", 12)
    candidate_hours = generate_candidate_hours(original_hour)

    # 计算原始准确率作为基准
    core_result = judge_core_gates(feedbacks, predictions)
    base_core_pass = core_result["pass_count"]
    base_total_accurate = sum(
        1 for f in feedbacks if f.get("status") == "accurate"
    )
    base_total_partial = sum(
        1 for f in feedbacks if f.get("status") == "partial"
    )

    comparisons = [
        {
            "hour": original_hour,
            "shichen": get_shichen_name(original_hour),
            "hour_value": original_hour,
            "core_pass": base_core_pass,
            "aux_pass": 0,
            "total_accurate": base_total_accurate,
            "total_partial": base_total_partial,
            "score": base_core_pass * 30 + base_total_accurate * 10 + base_total_partial * 5,
            "is_original": True,
        }
    ]

    # 对每个候选时钟进行试算
    has_api_key = bool(os.getenv("DEEPSEEK_API_KEY"))

    for ch in candidate_hours:
        try:
            # 重新排盘
            chart = calculate_bazi(
                year=birth_info["year"],
                month=birth_info["month"],
                day=birth_info["day"],
                hour=ch,
                minute=birth_info.get("minute", 0),
                gender=birth_info.get("gender", "male"),
            )

            # Phase 0: V2 已废弃 AI+Mock 预测生成。correction.py 暂时返回空列表。
            candidate_preds = []

            candidate_preds_dict = [p.model_dump() for p in candidate_preds]
            core_result_ch = judge_core_gates(feedbacks, candidate_preds_dict)

            total_accurate = sum(
                1 for f in feedbacks if f.get("status") == "accurate"
            )
            total_partial = sum(
                1 for f in feedbacks if f.get("status") == "partial"
            )
            # 辅助项：将原始反馈映射到候选预测
            aux_pass = 0
            for p in candidate_preds_dict:
                if not p.get("is_core"):
                    for fb in feedbacks:
                        if fb.get("prediction_id") == p["id"]:
                            status = fb.get("status", "")
                            if status in ("accurate", "partial"):
                                aux_pass += 1
                            break

            score = (
                core_result_ch["pass_count"] * 30
                + total_accurate * 10
                + total_partial * 5
            )

            comparisons.append({
                "hour": ch,
                "shichen": get_shichen_name(ch),
                "hour_value": ch,
                "core_pass": core_result_ch["pass_count"],
                "aux_pass": aux_pass,
                "total_accurate": total_accurate,
                "total_partial": total_partial,
                "score": score,
                "is_original": False,
                "chart_summary": {
                    "day_master": chart.day_master,
                    "ri_zhu_strength": chart.yongshen.ri_zhu_strength,
                    "pattern": chart.yongshen.pattern,
                    "yongshen": chart.yongshen.primary,
                },
            })
        except Exception as e:
            # 某个候选时钟排盘失败，跳过
            comparisons.append({
                "hour": ch,
                "shichen": get_shichen_name(ch),
                "hour_value": ch,
                "core_pass": 0,
                "aux_pass": 0,
                "total_accurate": 0,
                "total_partial": 0,
                "score": 0,
                "is_original": False,
                "error": str(e),
            })

    # 按评分排序（排除原始时钟）
    candidates_only = [c for c in comparisons if not c.get("is_original") and "error" not in c]
    candidates_only.sort(key=lambda c: c["score"], reverse=True)

    # 确定推荐
    best_candidate = candidates_only[0] if candidates_only else None
    all_failed = not best_candidate or best_candidate["score"] <= base_core_pass * 30

    if best_candidate and best_candidate["score"] > base_core_pass * 30:
        recommended = best_candidate["shichen"]
        recommended_hour = best_candidate["hour"]
    else:
        recommended = get_shichen_name(original_hour)
        recommended_hour = original_hour
        all_failed = True

    return {
        "original_hour": original_hour,
        "original_shichen": get_shichen_name(original_hour),
        "comparisons": comparisons,
        "recommended": recommended,
        "recommended_hour": recommended_hour,
        "all_failed": all_failed,
    }


async def apply_correction(
    birth_info: dict,
    new_hour: int,
    original_feedbacks: list[dict],
) -> dict:
    """
    用户确认修正后，用新时钟重跑完整P0全链路。

    有 DEEPSEEK_API_KEY 时使用 AI 生成断事，无 Key 时使用 Mock 模板生成。

    Args:
        birth_info: 出生信息
        new_hour: 确认的新时钟小时值

    Returns:
        重新排盘的完整结果，包含 chart + strength_detail + predictions
    """
    from bazi_engine import calculate_bazi
    from rules.yongshen import calculate_strength_detail
    from rules.wuxing import WUXING_MAP, HIDDEN_STEMS_MAP

    chart = calculate_bazi(
        year=birth_info["year"],
        month=birth_info["month"],
        day=birth_info["day"],
        hour=new_hour,
        minute=birth_info.get("minute", 0),
        gender=birth_info.get("gender", "male"),
    )

    # 旺衰分析
    four_pillars_raw = {}
    all_hidden_stems = []
    for pos in ["year", "month", "day", "hour"]:
        pillar = chart.four_pillars[pos]
        four_pillars_raw[pos] = {
            "stem": pillar.stem,
            "branch": pillar.branch,
        }
        for hs in pillar.hidden_stems:
            all_hidden_stems.append({"stem": hs.stem, "weight": hs.weight})

    strength_detail = calculate_strength_detail(
        day_master_stem=chart.day_master,
        four_pillars=four_pillars_raw,
        hidden_stems_list=all_hidden_stems,
    )

    # Phase 0: V2 已废弃预测生成。返回空列表。
    new_predictions = []

    new_predictions_dict = [p.model_dump() for p in new_predictions]

    return {
        "chart": chart_data,
        "strength_detail": strength_detail,
        "predictions": new_predictions_dict,
        "applied_hour": new_hour,
        "applied_shichen": get_shichen_name(new_hour),
        "correction_type": "hour_fix",
    }


# ============================================================
# 路径二：AI判断修正
# ============================================================

# --- AI Helper ---

CORRECTION_SYSTEM_PROMPT = """你是一位精通子平派命理学的命理师，拥有30年实战经验。
你的任务是：根据用户的八字排盘数据和断前事反馈，分析旺衰/格局/用神判断是否准确，并给出修正建议。

分析原则：
1. 旺衰判断遵循《滴天髓》"能知衰旺之真机"原则
2. 格局判断遵循《子平真诠》"凡格从月令定"原则
3. 用神判断遵循《穷通宝鉴》调候法和《滴天髓》扶抑法
4. 必须以用户反馈为最终依据——如果用户反馈多条"不准"，说明原判断需要修正
5. 推理过程简明扼要

输出格式（严格JSON，不要包含其他内容）：
{
  "analysis": "分析当前判断可能的问题（100-200字）",
  "suggested_strength": "建议的旺衰（偏强/偏弱/中和/太旺/太弱）",
  "suggested_pattern": "建议的格局",
  "suggested_yongshen": "建议的用神五行",
  "reasoning": "修正推理依据"
}"""


async def _call_deepseek_for_correction(
    prompt: str, system_prompt: str = None, timeout: int = 30
) -> str:
    """调用 DeepSeek API 进行修正分析。

    Delegates to services.deepseek_client.call_deepseek.
    """
    if system_prompt is None:
        system_prompt = CORRECTION_SYSTEM_PROMPT

    return await call_deepseek(
        prompt=prompt,
        system_prompt=system_prompt,
        timeout=timeout,
        model="deepseek-chat",
        temperature=0.5,
        max_tokens=1500,
    )


def _parse_correction_json(response: str) -> dict:
    """从 AI 响应中解析修正 JSON 结果。"""
    if not response or response.startswith("[API_"):
        return {}

    # 尝试直接解析
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        pass

    # 尝试提取 JSON 对象
    import re
    match = re.search(r"\{.*\}", response, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return {}


def _format_chart_summary(chart_data: dict) -> str:
    """格式化排盘摘要，供 AI 修正使用。"""
    pillars = chart_data.get("four_pillars", {})
    day_master = chart_data.get("day_master", "")
    yongshen = chart_data.get("yongshen", {})
    strength_detail = chart_data.get("strength_detail", {})

    pos_names = {"year": "年柱", "month": "月柱", "day": "日柱", "hour": "时柱"}
    lines = [f"日主：{day_master}"]

    for pos in ["year", "month", "day", "hour"]:
        p = pillars.get(pos, {})
        stem = p.get("stem", "")
        branch = p.get("branch", "")
        stem_tg = p.get("stem_ten_god", "")
        lines.append(f"{pos_names[pos]}：{stem}{branch}（{stem_tg}）")

    ys_primary = yongshen.get("primary", "")
    ys_pattern = yongshen.get("pattern", "")
    ys_strength = yongshen.get("ri_zhu_strength", "")
    total_score = strength_detail.get("total_score", "")

    lines.append(f"当前旺衰判断：{ys_strength}（总分{total_score}）")
    lines.append(f"当前格局：{ys_pattern}")
    lines.append(f"当前用神：{ys_primary}")

    return "\n".join(lines)


def _format_classical_refs(chart_data: dict) -> str:
    """从 chart_data 中提取典籍参考文本作为 AI prompt 的依据。"""
    strength_detail = chart_data.get("strength_detail", {})
    classical = chart_data.get("classical_analysis", {})

    parts = []

    deling = strength_detail.get("deling", {})
    dedi = strength_detail.get("dedi", {})
    if deling or dedi:
        parts.append("【规则引擎旺衰分解】")
        if deling:
            parts.append(f"得令（月令）：{deling.get('reason', '')} 得分 {deling.get('score', 0)}")
        if dedi:
            parts.append(f"得地（地支根气）：得分 {dedi.get('score', 0)}")
        parts.append(f"总分：{strength_detail.get('total_score', '')}")

    wangshuai = classical.get("wangshuai", {})
    pattern = classical.get("pattern", {})
    yongshen_cls = classical.get("yongshen", {})

    if wangshuai.get("explanation") or wangshuai.get("reasoning"):
        parts.append(f"【典籍旺衰判断】{wangshuai.get('explanation') or wangshuai.get('reasoning', '')}")

    if pattern.get("reasoning") or pattern.get("source_citation"):
        parts.append(f"【典籍格局判断】{pattern.get('reasoning') or pattern.get('source_citation', '')}")

    if yongshen_cls.get("reasoning") or yongshen_cls.get("comprehensive_analysis"):
        parts.append(f"【典籍用神判断】{yongshen_cls.get('reasoning') or yongshen_cls.get('comprehensive_analysis', '')}")

    return "\n".join(parts) if parts else ""


def _format_feedback_summary(feedbacks: list[dict], predictions: list[dict]) -> str:
    """格式化用户反馈摘要。"""
    pred_map = {p.get("id"): p for p in predictions}
    lines = []
    for fb in feedbacks:
        pid = fb.get("prediction_id", "")
        pred = pred_map.get(pid, {})
        category = pred.get("category", pid)
        status = fb.get("status", "unknown")
        status_cn = {"accurate": "准", "partial": "部分准", "inaccurate": "不准"}.get(status, status)
        note = fb.get("note", "")
        line = f"- {category}：{status_cn}"
        if note:
            line += f"（备注：{note}）"
        lines.append(line)
    return "\n".join(lines)


async def _ai_fix_wangshuai(chart_data: dict, feedbacks: list[dict], predictions: list[dict]) -> dict:
    """调用 AI 分析旺衰修正方向。"""
    chart_summary = _format_chart_summary(chart_data)
    fb_summary = _format_feedback_summary(feedbacks, predictions)

    inaccurate_fbs = [fb for fb in feedbacks if fb.get("status") == "inaccurate"]
    inaccurate_categories = []
    pred_map = {p.get("id"): p for p in predictions}
    for fb in inaccurate_fbs:
        pred = pred_map.get(fb.get("prediction_id"), {})
        cat = pred.get("category", fb.get("prediction_id", ""))
        inaccurate_categories.append(cat)

    prompt = f"""以下是一位用户的八字排盘和断前事反馈数据。

【排盘数据】
{chart_summary}

【用户反馈】
{fb_summary}

【反馈分析】
用户对以下类别的推断反馈为"不准"：{", ".join(inaccurate_categories) if inaccurate_categories else "无"}

⚠️ 注意：用户反馈中可能包含"备注"文字——这是用户补充的个人背景信息。你必须认真理解这些背景信息，因为它们揭示了推断与真实情况的偏差原因。例如用户备注"我爸妈其实很早就离婚了"，说明之前基于"父母完整"前提的推断都需重新审视。

{_format_classical_refs(chart_data)}

请分析：
1. 对照上述典籍依据，根据用户反馈中的背景信息，当前的旺衰判断可能是哪里出了问题？应参照哪部经典重新判断？
2. 应该调整为身强还是身弱？为什么？请引用典籍原文支持你的判断。
3. 调整后的用神应该是什么？

请严格按照JSON格式输出。"""

    response = await _call_deepseek_for_correction(prompt)
    return _parse_correction_json(response)


async def _ai_fix_pattern(chart_data: dict, feedbacks: list[dict], predictions: list[dict]) -> dict:
    """调用 AI 分析格局修正方向。"""
    chart_summary = _format_chart_summary(chart_data)
    fb_summary = _format_feedback_summary(feedbacks, predictions)
    strength_detail = chart_data.get("strength_detail", {})
    total_score = strength_detail.get("total_score", 50)

    prompt = f"""以下是一位用户的八字排盘和断前事反馈数据。日主旺衰总分处于边界区域（{total_score}分），格局判断可能需要修正。

【排盘数据】
{chart_summary}

【用户反馈】
{fb_summary}

{_format_classical_refs(chart_data)}

请分析：
1. 对照典籍依据，当前格局判断是否需要从正格切换为从格（或反之）？
2. 从用户反馈和典籍原文来看，哪个方向的格局更合理？
3. 修正后的用神应该是什么？

请严格按照JSON格式输出。"""

    response = await _call_deepseek_for_correction(prompt)
    return _parse_correction_json(response)


async def _ai_fix_yongshen(chart_data: dict, feedbacks: list[dict], predictions: list[dict]) -> dict:
    """调用 AI 分析用神优先级修正方向。"""
    chart_summary = _format_chart_summary(chart_data)
    fb_summary = _format_feedback_summary(feedbacks, predictions)

    prompt = f"""以下是一位用户的八字排盘和断前事反馈数据。三个角度的用神判断准确率差异较大，需要确定优先级。

【排盘数据】
{chart_summary}

【用户反馈】
{fb_summary}

{_format_classical_refs(chart_data)}

请分析：
1. 对照典籍依据，从用户反馈来看，扶抑法、调候法、格局法三者哪个更准确？
2. 应该优先采用哪个角度的用神？请引用对应的典籍原文支持你的判断。
3. 综合推荐：用神五行（1个汉字）、喜神五行（1个汉字）、忌神五行（1个汉字）。

请在输出中明确给出以下字段（严格JSON格式）：
- analysis: 你的分析推理（结合用户反馈和典籍依据）
- suggested_yongshen: 最终推荐的用神五行（1个汉字：金/木/水/火/土）
- suggested_secondary: 基于用神推导的喜神五行（1个汉字）
- suggested_ji_shen: 基于用神推导的忌神五行（1个汉字）

**硬约束：用神、喜神、忌神必须互不重复。**
用神是帮你的元素，喜神是辅佐用神的元素，忌神是对你不利的元素——三者必须是三个不同的五行。

请严格按照JSON格式输出。"""

    response = await _call_deepseek_for_correction(prompt)
    return _parse_correction_json(response)


async def fix_wangshuai(
    chart_data: dict,
    feedbacks: list[dict],
    predictions: list[dict],
) -> dict:
    """
    旺衰修正：与旺衰强相关的"不准确"反馈 >= 50% 时触发。

    修正方式：从反角度重新判断旺衰，生成新的推断内容。

    旺衰强相关的类别：性格、父母关、事业（这些与日主旺衰直接相关）

    Args:
        chart_data: 排盘数据
        feedbacks: 用户反馈
        predictions: 推断列表

    Returns:
        修正结果，包含新的旺衰判断和推断建议
    """
    # 判断旺衰强相关的反馈
    wangshuai_related_categories = ["性格", "父母关", "事业"]
    pred_map = {p["id"]: p for p in predictions}
    fb_map = {f["prediction_id"]: f for f in feedbacks}

    related_feedbacks = []
    for fb in feedbacks:
        pred = pred_map.get(fb["prediction_id"])
        if pred and pred.get("category") in wangshuai_related_categories:
            related_feedbacks.append(fb)

    if not related_feedbacks:
        return {
            "triggered": False,
            "reason": "无旺衰相关反馈",
            "suggestion": "",
        }

    inaccurate_count = sum(
        1 for fb in related_feedbacks if fb.get("status") == "inaccurate"
    )
    total_count = len(related_feedbacks)
    inaccurate_ratio = inaccurate_count / total_count if total_count > 0 else 0

    triggered = inaccurate_ratio >= 0.5

    # 当前旺衰信息
    yongshen = chart_data.get("yongshen", {})
    current_strength = yongshen.get("ri_zhu_strength", "中和")
    primary = chart_data.get("yongshen", {}).get("primary", "")
    ji_shen = chart_data.get("yongshen", {}).get("ji_shen", "")

    # 是否包含用户补充笔记（笔记=用户明确告知系统判断有偏差）
    has_notes = any(str(fb.get("note", "")).strip() for fb in feedbacks)

    # 硬编码翻转仅在没有笔记且没有 AI 时作为降级 fallback
    opposite_map = {
        "偏强": "偏弱", "太旺": "太弱", "极强": "极弱",
        "偏弱": "偏强", "太弱": "太旺", "极弱": "极强",
        "中和": "偏弱",
    }
    suggested_strength = ""
    if triggered and not has_notes:
        suggested_strength = opposite_map.get(current_strength, "中和")

    suggestion = ""
    if triggered:
        suggestion = (
            f"当前日主判断为{current_strength}，"
            f"从不准确反馈来看需要重新评估旺衰方向。"
        )
    else:
        suggestion = f"旺衰相关反馈不准确率 {inaccurate_ratio:.0%}，未达到50%触发阈值，无需修正。"

    result = {
        "triggered": triggered,
        "has_notes": has_notes,
        "inaccurate_count": inaccurate_count,
        "total_count": total_count,
        "inaccurate_ratio": round(inaccurate_ratio, 2),
        "current_strength": current_strength,
        "suggested_strength": suggested_strength,
        "current_yongshen": primary,
        "suggestion": suggestion,
    }

    # AI enrichment: 当触发或有笔记时，调用 AI 获取更详细的分析
    if (triggered or has_notes) and os.getenv("DEEPSEEK_API_KEY"):
        try:
            ai_analysis = await _ai_fix_wangshuai(chart_data, feedbacks, predictions)
            if ai_analysis:
                result["ai_analysis"] = ai_analysis
                ai_strength = ai_analysis.get("suggested_strength")
                if ai_strength and ai_strength in (
                    "偏强", "偏弱", "中和", "太旺", "太弱", "极强", "极弱"
                ):
                    result["suggested_strength"] = ai_strength
                ai_suggestion = ai_analysis.get("analysis") or ai_analysis.get("reasoning")
                if ai_suggestion:
                    result["suggestion"] = ai_suggestion
                ai_yongshen = ai_analysis.get("suggested_yongshen")
                if ai_yongshen:
                    result["ai_yongshen"] = ai_yongshen
                ai_secondary = ai_analysis.get("suggested_secondary")
                if ai_secondary:
                    result["ai_secondary"] = ai_secondary
                ai_ji_shen = ai_analysis.get("suggested_ji_shen")
                if ai_ji_shen:
                    result["ai_ji_shen"] = ai_ji_shen
        except Exception:
            pass

    return result


async def fix_pattern(
    chart_data: dict,
    feedbacks: list[dict],
    predictions: list[dict],
) -> dict:
    """
    格局修正：旺衰修正无效，且日主总分在边界区域（15-25或75-85）时触发。

    修正方式：正格↔从格切换。

    边界区域说明：
    - 总分 15-25：偏弱边界，可能为从弱格
    - 总分 75-85：偏强边界，可能为从强格

    Args:
        chart_data: 排盘数据（须包含 strength_detail）
        feedbacks: 用户反馈
        predictions: 推断列表

    Returns:
        修正结果，包含格局切换建议
    """
    strength_detail = chart_data.get("strength_detail", {})
    total_score = strength_detail.get("total_score", 50)
    current_pattern = chart_data.get("yongshen", {}).get("pattern", "未知")

    # 判断是否在边界区域
    is_boundary_low = 15 <= total_score < 25
    is_boundary_high = 75 <= total_score <= 85
    in_boundary = is_boundary_low or is_boundary_high

    # 判断是否正格和从格之间的切换
    is_zheng_ge = "正格" in current_pattern
    is_cong_ge = "从" in current_pattern

    if in_boundary:
        if is_zheng_ge:
            suggested_pattern = (
                f"从弱格（总分{total_score}偏低，可能从弱）"
                if is_boundary_low
                else f"从强格（总分{total_score}偏高，可能从强）"
            )
        elif is_cong_ge:
            suggested_pattern = (
                f"正格-身弱（总分{total_score}在边界，可能按正格论）"
                if is_boundary_low
                else f"正格-身强（总分{total_score}在边界，可能按正格论）"
            )
        else:
            suggested_pattern = f"待定（总分{total_score}在边界区域）"
    else:
        suggested_pattern = current_pattern

    # 检查婚姻关反馈
    marriage_fb = None
    for fb in feedbacks:
        for p in predictions:
            if p["id"] == fb["prediction_id"] and "婚姻" in p.get("category", ""):
                marriage_fb = fb
                break

    triggered = in_boundary and (
        (marriage_fb and marriage_fb.get("status") == "inaccurate")
    )

    # 是否包含用户补充笔记
    has_notes = any(str(fb.get("note", "")).strip() for fb in feedbacks)
    should_call_ai = (in_boundary or triggered or has_notes) and os.getenv("DEEPSEEK_API_KEY")

    suggestion = ""
    if triggered:
        suggestion = (
            f"日主总分 {total_score} 处于格局边界区域（15-25或75-85）。"
            f"当前格局为 {current_pattern}，建议重新评估。"
            f"格局切换后，核心三关推断可能有显著改善。"
        )
    elif in_boundary:
        suggestion = (
            f"日主总分 {total_score} 处于格局边界区域。"
            f"建议关注 {current_pattern} 的准确性。"
        )
    else:
        suggestion = f"日主总分 {total_score} 不在边界区域，格局修正不触发。"

    result = {
        "triggered": triggered,
        "has_notes": has_notes,
        "total_score": total_score,
        "in_boundary": in_boundary,
        "is_boundary_low": is_boundary_low,
        "is_boundary_high": is_boundary_high,
        "current_pattern": current_pattern,
        "suggested_pattern": suggested_pattern,
        "suggestion": suggestion,
    }

    # AI enrichment: 在边界、触发、或有笔记时调用 AI
    if should_call_ai:
        try:
            ai_analysis = await _ai_fix_pattern(chart_data, feedbacks, predictions)
            if ai_analysis:
                result["ai_analysis"] = ai_analysis
                ai_pattern = ai_analysis.get("suggested_pattern")
                if ai_pattern:
                    result["suggested_pattern"] = ai_pattern
                ai_suggestion = ai_analysis.get("analysis") or ai_analysis.get("reasoning")
                if ai_suggestion:
                    result["suggestion"] = ai_suggestion
        except Exception:
            pass

    return result


async def fix_yongshen_priority(
    chart_data: dict,
    feedbacks: list[dict],
    predictions: list[dict],
) -> dict:
    """
    用神优先级修正：旺衰+格局修正后仍不理想时触发。

    修正方式：对比扶抑/调候/格局三个角度哪个准确率最高，
    以准确率最高的角度作为优先用神判断依据。

    三个角度与推断类别的关联：
    - 扶抑法 → 性格、父母关（旺衰直接相关）
    - 调候法 → 婚姻关、事业（环境和人际关系相关）
    - 格局法 → 兄弟关、事业（社会地位相关）

    Args:
        chart_data: 排盘数据（须包含 classical_analysis 或 yongshen 三个角度数据）
        feedbacks: 用户反馈
        predictions: 推断列表

    Returns:
        修正结果，包含三个角度对比分析
    """
    pred_map = {p["id"]: p for p in predictions}
    fb_map = {f["prediction_id"]: f for f in feedbacks}

    # 推断类别与用神角度的关联映射
    category_to_angle = {
        "性格": "fuyi",      # 性格与旺衰直接相关 → 扶抑法
        "父母关": "fuyi",     # 父母关与旺衰相关 → 扶抑法
        "兄弟关": "geju",     # 兄弟关与社会结构相关 → 格局法
        "学历": "tiaohou",    # 学历与天赋环境 → 调候法
        "婚姻关": "tiaohou",  # 婚姻与情感环境 → 调候法
        "事业": "geju",       # 事业与社会成就 → 格局法
        "关键年份": "fuyi",   # 关键年份与运势起伏 → 扶抑法
    }

    # 统计每个角度的准确率
    angle_scores = {
        "fuyi": {"accurate": 0, "partial": 0, "inaccurate": 0, "total": 0},
        "tiaohou": {"accurate": 0, "partial": 0, "inaccurate": 0, "total": 0},
        "geju": {"accurate": 0, "partial": 0, "inaccurate": 0, "total": 0},
    }

    for fb in feedbacks:
        pred = pred_map.get(fb["prediction_id"])
        if not pred:
            continue
        category = pred.get("category", "")
        angle = category_to_angle.get(category, "fuyi")
        status = fb.get("status", "")
        if status in ("accurate", "partial", "inaccurate"):
            angle_scores[angle][status] += 1
            angle_scores[angle]["total"] += 1

    # 计算每个角度的综合准确率
    angle_accuracy = {}
    for angle, scores in angle_scores.items():
        if scores["total"] > 0:
            accuracy = (scores["accurate"] + scores["partial"] * 0.5) / scores["total"]
        else:
            accuracy = 0
        angle_accuracy[angle] = {
            "accuracy": round(accuracy, 2),
            "accurate": scores["accurate"],
            "partial": scores["partial"],
            "inaccurate": scores["inaccurate"],
            "total": scores["total"],
        }

    # 排序
    sorted_angles = sorted(
        angle_accuracy.items(), key=lambda x: x[1]["accuracy"], reverse=True
    )

    best_angle = sorted_angles[0][0] if sorted_angles else "fuyi"
    angle_labels = {
        "fuyi": "扶抑法（《滴天髓》）",
        "tiaohou": "调候法（《穷通宝鉴》）",
        "geju": "格局法（《子平真诠》）",
    }

    # 检查是否三个角度差异较大
    accuracies = [a["accuracy"] for _, a in sorted_angles]
    max_diff = max(accuracies) - min(accuracies) if len(accuracies) >= 2 else 0
    triggered = max_diff >= 0.3  # 差异超过30%触发
    has_notes = any(str(fb.get("note", "")).strip() for fb in feedbacks)

    suggestion = ""
    if triggered:
        best_label = angle_labels.get(best_angle, best_angle)
        suggestion = (
            f"三个角度的准确率差异较大（最大差异 {max_diff:.0%}）。"
            f"建议优先采用 {best_label} 的判断结果作为用神依据，"
            f"其准确率为 {angle_accuracy[best_angle]['accuracy']:.0%}。"
        )
    else:
        suggestion = (
            f"三个角度的准确率差异不大（最大差异 {max_diff:.0%}），"
            f"无需调整优先级。继续使用综合结论。"
        )

    result = {
        "triggered": triggered,
        "has_notes": has_notes,
        "max_difference": round(max_diff, 2),
        "angle_accuracy": angle_accuracy,
        "best_angle": best_angle,
        "best_angle_label": angle_labels.get(best_angle, best_angle),
        "ranked_angles": [
            {"angle": a[0], "label": angle_labels.get(a[0], a[0]), **a[1]}
            for a in sorted_angles
        ],
        "suggestion": suggestion,
    }

    # AI enrichment: 触发或有笔记时调用 AI
    if (triggered or has_notes) and os.getenv("DEEPSEEK_API_KEY"):
        try:
            ai_analysis = await _ai_fix_yongshen(chart_data, feedbacks, predictions)
            if ai_analysis:
                result["ai_analysis"] = ai_analysis
                ai_suggestion = ai_analysis.get("analysis") or ai_analysis.get("reasoning")
                if ai_suggestion:
                    result["suggestion"] = ai_suggestion
                ai_yongshen = ai_analysis.get("suggested_yongshen")
                if ai_yongshen:
                    result["ai_yongshen"] = ai_yongshen
        except Exception:
            pass

    return result


async def _ai_fix_unified(
    chart_data: dict,
    feedbacks: list[dict] | None = None,
    predictions: list[dict] | None = None,
) -> dict:
    """统一 AI 命盘分析：一次性输出旺衰、格局、用神、喜神、忌神、辅用神。

    无 feedbacks 时做初判（仅排盘+典籍），有 feedbacks 时做校正（+反馈+角度对比）。
    """
    chart_summary = _format_chart_summary(chart_data)
    classical_refs = _format_classical_refs(chart_data)
    feedbacks = feedbacks or []
    predictions = predictions or []
    has_feedback = bool(feedbacks)

    # 角度准确率对比（仅校正时）
    angle_comparison = []
    if has_feedback:
        category_to_angle = {
            u"性格": "fuyi", u"父母关": "fuyi", u"兄弟关": "geju", u"学历": "tiaohou",
            u"婚姻关": "tiaohou", u"事业": "geju", u"关键年份": "fuyi",
        }
        angle_scores = {"fuyi": 0, "tiaohou": 0, "geju": 0}
        angle_totals = {"fuyi": 0, "tiaohou": 0, "geju": 0}
        for fb in feedbacks:
            pred = {p.get("id"): p for p in predictions}.get(fb.get("prediction_id"), {})
            cat = pred.get("category", "")
            angle = category_to_angle.get(cat, "fuyi")
            status = fb.get("status", "")
            if status == "accurate":
                angle_scores[angle] += 1
            elif status == "partial":
                angle_scores[angle] += 0.5
            angle_totals[angle] += 1
        for angle, label in [("fuyi", u"扶抑法"), ("tiaohou", u"调候法"), ("geju", u"格局法")]:
            total = angle_totals[angle]
            acc = f"{angle_scores[angle]}/{total}" if total else u"无数据"
            angle_comparison.append(f"{label}：{acc}")

    # 反馈区域
    fb_section = ""
    if has_feedback:
        fb_summary = _format_feedback_summary(feedbacks, predictions)
        angle_section = "\n【三角度准确率对比】\n" + "\n".join(angle_comparison)
        fb_section = f"""

【用户反馈】
{fb_summary}
{angle_section}"""

    prompt = f"""你是一位精通子平派的命理师。以下是一位用户的八字排盘{'和断前事反馈' if has_feedback else ''}。

【排盘数据】
{chart_summary}

【典籍依据】
{classical_refs}{fb_section}

请基于上述所有信息，进行一次{'校正分析' if has_feedback else '初次命盘分析'}。注意：

1. 旺衰是根本——旺衰决定用神的大方向（身强→克泄耗，身弱→生扶）。
   调候法和格局法是在旺衰方向内的细化和补充，不能推翻旺衰方向。""" + ("""如果用户反馈显示调候法准确率更高，说明季节性因素更显著，但不等于要推翻旺衰方向。只有在旺衰确实判断错误时（从用户反馈中有明确证据表明身强/身弱判反了），才修正旺衰。""" if has_feedback else "") + """

2. 用神、喜神、忌神必须三者互不相同。用神是帮你的，喜神是辅佐用神的，
   忌神是对你不利的。如果出现重复，说明分析有误。

3. 辅用神 (auxiliary) 是调候法或格局法需要的辅助元素。它帮助主用神更好地
   发挥作用，但本身不是主用神。例如丁火偏弱，主用神=木(印星生火)，
   辅用神=金(穷通宝鉴\"劈甲引丁\")。辅用神与主用神不可相同，可以为空。

4. 输出的所有判断必须引用典籍原文作为依据。""" + ("根据用户反馈调整时，需解释为什么之前的判断需要修正。" if has_feedback else "") + """

请严格按以下 JSON 格式输出（不要输出其他内容）：

{{
  "analysis": "你的完整分析推理（200-400字）",
  "ri_zhu_strength": "日主旺衰判断（身强/偏强/中和/偏弱/身弱）",
  "pattern": "格局类型（如：正格-身强）",
  "yongshen": "用神五行（1个汉字：金/木/水/火/土）",
  "suggested_auxiliary": "辅用神五行（1个汉字，如无需辅用神则留空字符串）",
  "suggested_secondary": "喜神五行（1个汉字，不可与用神重复）",
  "suggested_ji_shen": "忌神五行（1个汉字，不可与用神重复）"
}}"""

    response = await _call_deepseek_for_correction(prompt)
    return _parse_correction_json(response)

async def run_ai_fix(
    chart_data: dict,
    feedbacks: list[dict],
    predictions: list[dict],
    fix_stage: int = 1,
) -> dict:
    """
    按阶段执行AI修正路径。

    Stage 1: fix_wangshuai（旺衰修正）
    Stage 2: fix_pattern（格局修正，旺衰修正无效后触发）
    Stage 3: fix_yongshen_priority（用神优先级修正，格局修正后仍不理想触发）

    Args:
        chart_data: 排盘数据
        feedbacks: 用户反馈
        predictions: 推断列表
        fix_stage: 修正阶段（1/2/3）

    Returns:
        各阶段的修正结果
    """
    result = {
        "fix_stage": fix_stage,
        "wangshuai_fix": None,
        "pattern_fix": None,
        "yongshen_fix": None,
    }

    # 统一 AI 校正：一次调用覆盖旺衰+格局+用神+喜忌
    unified = None
    if os.getenv("DEEPSEEK_API_KEY"):
        try:
            unified = await _ai_fix_unified(chart_data, feedbacks, predictions)
        except Exception:
            pass

    if unified:
        # 拆分统一结果为三个 fix 字段（保持向后兼容）
        result["wangshuai_fix"] = {
            "triggered": bool(unified.get("ri_zhu_strength")),
            "suggested_strength": unified.get("ri_zhu_strength", ""),
            "ai_analysis": unified.get("analysis", ""),
        }
        result["pattern_fix"] = {
            "triggered": bool(unified.get("pattern")),
            "suggested_pattern": unified.get("pattern", ""),
            "ai_analysis": unified.get("analysis", ""),
        }
        result["yongshen_fix"] = {
            "triggered": bool(unified.get("yongshen")),
            "ai_yongshen": unified.get("yongshen", ""),
            "ai_auxiliary": unified.get("suggested_auxiliary", ""),
            "ai_secondary": unified.get("suggested_secondary", ""),
            "ai_ji_shen": unified.get("suggested_ji_shen", ""),
            "ai_analysis": unified.get("analysis", ""),
            "best_angle_label": unified.get("best_angle_label", ""),
        }
        return result

    # 统一调用失败时回退到分步调用
    if fix_stage >= 1:
        result["wangshuai_fix"] = await fix_wangshuai(chart_data, feedbacks, predictions)

    if fix_stage >= 2:
        result["pattern_fix"] = await fix_pattern(chart_data, feedbacks, predictions)

    if fix_stage >= 3:
        result["yongshen_fix"] = await fix_yongshen_priority(chart_data, feedbacks, predictions)

    return result


# ============================================================
# P1 Phase 3: 闭环完善 - 轮数控制 + 双路径切换 + 降级处理
# ============================================================

MAX_CORRECTION_ROUNDS = 2  # 最大修正轮数


def init_correction_state(session: dict) -> dict:
    """
    初始化或获取修正闭环状态。

    在 session 中管理以下字段：
    - correction_state.round: 当前轮数（0表示尚未开始修正）
    - correction_state.history: 每次修正的历史记录
    - correction_state.current_path: 当前修正路径
    - correction_state.degraded: 是否已降级
    - correction_state.before_snapshot: 修正前的快照（用于对比展示）

    Args:
        session: 会话字典

    Returns:
        修正状态字典（也会写入 session["correction_state"]）
    """
    if "correction_state" not in session:
        session["correction_state"] = {
            "round": 0,
            "history": [],
            "current_path": None,
            "degraded": False,
            "degraded_reason": "",
            "before_snapshot": None,
        }
    return session["correction_state"]


def take_before_snapshot(session: dict) -> dict:
    """
    在修正开始前，保存当前命盘的快照，用于修正前后对比。

    快照内容包括：时柱、旺衰结论、用神、日主强弱

    Args:
        session: 会话字典

    Returns:
        快照字典
    """
    chart_data = session.get("chart_data", {})
    yongshen = chart_data.get("yongshen", {})
    hour_pillar = {}
    if "four_pillars" in chart_data and "hour" in chart_data["four_pillars"]:
        hour_pillar = chart_data["four_pillars"]["hour"]

    snapshot = {
        "hour_pillar": {
            "stem": hour_pillar.get("stem", ""),
            "branch": hour_pillar.get("branch", ""),
            "stem_ten_god": hour_pillar.get("stem_ten_god", ""),
            "nayin": hour_pillar.get("nayin", ""),
        },
        "wangshuai": {
            "ri_zhu_strength": yongshen.get("ri_zhu_strength", ""),
            "pattern": yongshen.get("pattern", ""),
        },
        "yongshen": {
            "primary": yongshen.get("primary", ""),
            "secondary": yongshen.get("secondary", ""),
            "ji_shen": yongshen.get("ji_shen", ""),
        },
        "birth_hour": session.get("birth_info", {}).get("hour", 0),
        "birth_shichen": get_shichen_name(
            session.get("birth_info", {}).get("hour", 0)
        ),
    }
    return snapshot


def build_correction_comparison(
    session: dict, before_snapshot: dict
) -> dict:
    """
    构建修正前后对比数据。

    对比内容：
    - 时柱变化（天干、地支、十神）
    - 旺衰结论变化（日主强弱、格局）
    - 用神变化（用神、喜神、忌神）

    Args:
        session: 会话字典（修正后）
        before_snapshot: 修正前快照

    Returns:
        对比结果字典
    """
    chart_data = session.get("chart_data", {})
    yongshen = chart_data.get("yongshen", {})
    hour_pillar = {}
    if "four_pillars" in chart_data and "hour" in chart_data["four_pillars"]:
        hour_pillar = chart_data["four_pillars"]["hour"]

    after = {
        "hour_pillar": {
            "stem": hour_pillar.get("stem", ""),
            "branch": hour_pillar.get("branch", ""),
            "stem_ten_god": hour_pillar.get("stem_ten_god", ""),
            "nayin": hour_pillar.get("nayin", ""),
        },
        "wangshuai": {
            "ri_zhu_strength": yongshen.get("ri_zhu_strength", ""),
            "pattern": yongshen.get("pattern", ""),
        },
        "yongshen": {
            "primary": yongshen.get("primary", ""),
            "secondary": yongshen.get("secondary", ""),
            "ji_shen": yongshen.get("ji_shen", ""),
        },
        "birth_hour": session.get("birth_info", {}).get("hour", 0),
    }

    # 计算变化
    before_hour = before_snapshot.get("hour_pillar", {})
    after_hour = after.get("hour_pillar", {})

    hour_changed = (
        before_hour.get("stem") != after_hour.get("stem")
        or before_hour.get("branch") != after_hour.get("branch")
    )

    wangshuai_changed = (
        before_snapshot.get("wangshuai", {}).get("ri_zhu_strength")
        != after.get("wangshuai", {}).get("ri_zhu_strength")
    )

    pattern_changed = (
        before_snapshot.get("wangshuai", {}).get("pattern")
        != after.get("wangshuai", {}).get("pattern")
    )

    yongshen_primary_changed = (
        before_snapshot.get("yongshen", {}).get("primary")
        != after.get("yongshen", {}).get("primary")
    )

    shichen_changed = (
        before_snapshot.get("birth_shichen")
        != get_shichen_name(after.get("birth_hour", 0))
    )

    # 生成文字描述的变化
    changes = []
    if hour_changed:
        changes.append(
            f"时柱：{before_hour.get('stem','')}{before_hour.get('branch','')} "
            f"→ {after_hour.get('stem','')}{after_hour.get('branch','')}"
        )
    if shichen_changed:
        changes.append(
            f"时辰：{before_snapshot.get('birth_shichen','')} "
            f"→ {get_shichen_name(after.get('birth_hour', 0))}"
        )
    if wangshuai_changed:
        changes.append(
            f"日主强弱：{before_snapshot.get('wangshuai', {}).get('ri_zhu_strength','')} "
            f"→ {after.get('wangshuai', {}).get('ri_zhu_strength','')}"
        )
    if pattern_changed:
        changes.append(
            f"格局：{before_snapshot.get('wangshuai', {}).get('pattern','')} "
            f"→ {after.get('wangshuai', {}).get('pattern','')}"
        )
    if yongshen_primary_changed:
        changes.append(
            f"用神：{before_snapshot.get('yongshen', {}).get('primary','')} "
            f"→ {after.get('yongshen', {}).get('primary','')}"
        )

    any_changed = hour_changed or wangshuai_changed or pattern_changed or yongshen_primary_changed

    return {
        "before": before_snapshot,
        "after": after,
        "changes": changes,
        "hour_changed": hour_changed,
        "wangshuai_changed": wangshuai_changed,
        "pattern_changed": pattern_changed,
        "yongshen_primary_changed": yongshen_primary_changed,
        "shichen_changed": shichen_changed,
        "any_changed": any_changed,
    }


def determine_next_path(
    correction_state: dict, verdict: str, last_result: dict = None
) -> str:
    """
    决定下一步修正路径。

    路径切换逻辑：
    - "ai_fix_first"：先走路径二（AI修正），1轮无效后自动切路径一（时钟修正）
    - "ai_fix"：走路径二（AI修正）
    - "hour_fix"：走路径一（时钟修正）
    - 如果当前是第1轮且 verdict 是 ai_fix_first，第1轮用 ai_fix
    - 如果第1轮 ai_fix 无效（无改善），第2轮强制切 hour_fix

    Args:
        correction_state: 修正状态
        verdict: 原始判定结果
        last_result: 上一轮修正结果（如果有）

    Returns:
        下一步路径: "hour_fix" | "ai_fix" | "degrade"
    """
    current_round = correction_state["round"]

    # 第1轮：按 verdict 指示的路径
    if current_round == 0:
        if verdict == "ai_fix_first":
            correction_state["current_path"] = "ai_fix"
            return "ai_fix"
        elif verdict == "ai_fix":
            correction_state["current_path"] = "ai_fix"
            return "ai_fix"
        elif verdict == "hour_fix":
            correction_state["current_path"] = "hour_fix"
            return "hour_fix"
        else:
            # passed 不应进入修正
            return "degrade"

    # 第2轮及以后
    if current_round >= MAX_CORRECTION_ROUNDS:
        return "degrade"

    # 第2轮：如果上一轮是 ai_fix 且无效，切换到 hour_fix
    if current_round == 1:
        prev_path = correction_state["current_path"]
        if prev_path == "ai_fix":
            # 检查上一轮是否有效
            if last_result and not last_result.get("any_improvement", False):
                # AI修正无效，切到时修修正
                correction_state["current_path"] = "hour_fix"
                return "hour_fix"
            elif last_result and last_result.get("any_improvement"):
                # AI修正有效，继续AI修正
                return "ai_fix"
            else:
                # 无上轮结果，切换到时钟修正
                correction_state["current_path"] = "hour_fix"
                return "hour_fix"

        elif prev_path == "hour_fix":
            if last_result and not last_result.get("any_improvement", False):
                # 时钟修正也无效，降级
                return "degrade"
            elif last_result and last_result.get("any_improvement"):
                return "hour_fix"
            else:
                return "degrade"

    return "degrade"


async def run_correction_round(
    session: dict, correction_type: str = None, new_hour: int = None
) -> dict:
    """
    执行一轮修正闭环。

    完整流程：
    1. 初始化/获取修正状态
    2. 检查是否已超过最大轮数或已降级
    3. 决定修正路径
    4. 执行修正
    5. 评估修正效果
    6. 构建对比数据
    7. 返回结果（含是否继续、下一步路径等）

    Args:
        session: 会话字典（包含 birth_info, chart_data, feedbacks, predictions）
        correction_type: 用户指定的修正类型（可选，为空时自动决定）
        new_hour: 新时钟小时值（hour_fix 时需要）

    Returns:
        {
            "round": int,              # 当前轮数
            "correction_type": str,    # 执行的修正类型
            "verdict": dict,           # 本次修正后的校验结果
            "comparison": dict,        # 修正前后对比
            "correction_result": dict, # 修正执行结果
            "can_continue": bool,      # 是否可以继续修正
            "need_degrade": bool,      # 是否需要降级
            "degrade_reason": str,     # 降级原因
            "next_path": str,          # 下一步路径建议
            "message": str,            # 用户提示信息
        }
    """
    from services.calibration import run_calibration

    # 初始化修正状态
    cs = init_correction_state(session)

    # 检查是否已降级
    if cs.get("degraded"):
        return {
            "round": cs["round"],
            "correction_type": None,
            "verdict": None,
            "comparison": None,
            "correction_result": None,
            "can_continue": False,
            "need_degrade": True,
            "degrade_reason": cs.get("degraded_reason", "系统已降级"),
            "next_path": None,
            "message": "系统已降级，无法继续修正。" + cs.get("degraded_reason", ""),
        }

    # 检查轮数
    if cs["round"] >= MAX_CORRECTION_ROUNDS:
        cs["degraded"] = True
        cs["degraded_reason"] = (
            f"已达到最大修正轮数（{MAX_CORRECTION_ROUNDS}轮），"
            f"系统无法在当前条件下给出可靠推断，建议确认出生时辰。"
        )
        return {
            "round": cs["round"],
            "correction_type": None,
            "verdict": None,
            "comparison": None,
            "correction_result": None,
            "can_continue": False,
            "need_degrade": True,
            "degrade_reason": cs["degraded_reason"],
            "next_path": None,
            "message": cs["degraded_reason"],
        }

    # 在修正开始前保存快照（仅第1轮）
    if cs["round"] == 0:
        cs["before_snapshot"] = take_before_snapshot(session)

    # 决定修正路径
    if correction_type:
        actual_type = correction_type
    else:
        # 从第一次 calibrate 结果中取 verdict
        last_calibration = cs.get("last_calibration", {})
        verdict_key = last_calibration.get("verdict", {}).get("verdict", "ai_fix_first")
        actual_type = determine_next_path(cs, verdict_key)

    if actual_type == "degrade":
        cs["degraded"] = True
        cs["degraded_reason"] = (
            "双路径修正均未产生有效改善，"
            "系统无法在当前条件下给出可靠推断，建议确认出生时辰。"
        )
        return {
            "round": cs["round"],
            "correction_type": None,
            "verdict": None,
            "comparison": None,
            "correction_result": None,
            "can_continue": False,
            "need_degrade": True,
            "degrade_reason": cs["degraded_reason"],
            "next_path": None,
            "message": cs["degraded_reason"],
        }

    # 执行修正
    cs["round"] += 1
    current_round = cs["round"]
    cs["current_path"] = actual_type

    correction_result = None
    comparison = None

    if actual_type in ("ai_fix", "ai_fix_first"):
        # 路径二：AI修正
        chart_data = session.get("chart_data", {})
        feedbacks = session.get("feedbacks", [])
        predictions = session.get("predictions", [])

        ai_result = await run_ai_fix(chart_data, feedbacks, predictions, fix_stage=3)

        # 判断AI修正是否触发了任何一项
        any_triggered = False
        if ai_result.get("wangshuai_fix", {}).get("triggered"):
            any_triggered = True
        if ai_result.get("pattern_fix", {}).get("triggered"):
            any_triggered = True
        if ai_result.get("yongshen_fix", {}).get("triggered"):
            any_triggered = True

        correction_result = {
            "ai_fix_result": ai_result,
            "any_improvement": any_triggered,
        }

        # AI修正没有改变排盘数据，对比快照用原始数据
        if cs.get("before_snapshot"):
            comparison = build_correction_comparison(session, cs["before_snapshot"])
            # AI修正场景下，旺衰/用神对比可能不同
            if ai_result.get("wangshuai_fix", {}).get("triggered"):
                comparison["wangshuai_changed"] = True
                comparison["any_changed"] = True
                comparison["changes"].append(
                    f"AI建议旺衰调整：{ai_result['wangshuai_fix']['current_strength']} "
                    f"→ {ai_result['wangshuai_fix']['suggested_strength']}"
                )

    elif actual_type == "hour_fix":
        # 路径一：时钟修正
        if new_hour is None:
            # 如果没有指定 new_hour，尝试从候选时钟中找最佳
            birth_info = session.get("birth_info", {})
            feedbacks = session.get("feedbacks", [])
            predictions = session.get("predictions", [])

            if birth_info and feedbacks and predictions:
                candidate_result = await try_candidate_hours(birth_info, feedbacks, predictions)

                if candidate_result.get("all_failed"):
                    # 所有候选时钟都失败了
                    correction_result = {
                        "candidate_result": candidate_result,
                        "any_improvement": False,
                        "all_candidates_failed": True,
                    }
                else:
                    # 使用推荐时钟
                    new_hour = candidate_result.get("recommended_hour")
                    correction_result = {
                        "candidate_result": candidate_result,
                        "any_improvement": True,
                        "all_candidates_failed": False,
                    }

        if new_hour is not None:
            # 应用时钟修正
            birth_info = session.get("birth_info", {})
            feedbacks = session.get("feedbacks", [])
            applied = await apply_correction(birth_info, new_hour, feedbacks)

            # 更新 session 数据
            session["chart_data"] = applied["chart"]
            session["predictions"] = applied["predictions"]
            session["birth_info"]["hour"] = new_hour

            # 构建对比
            if cs.get("before_snapshot"):
                comparison = build_correction_comparison(session, cs["before_snapshot"])

            if correction_result is None:
                correction_result = {
                    "applied_result": applied,
                    "any_improvement": True,
                    "all_candidates_failed": False,
                }
            else:
                correction_result["applied_result"] = applied

    # 重新运行校验判定
    feedbacks = session.get("feedbacks", [])
    predictions = session.get("predictions", [])
    new_verdict = run_calibration(feedbacks, predictions)

    # 判断修正是否有效
    verdict_key = new_verdict.get("verdict", {}).get("verdict", "")
    improved = verdict_key == "passed" or correction_result.get("any_improvement", False)

    # 记录历史
    history_entry = {
        "round": current_round,
        "path": actual_type,
        "verdict": new_verdict,
        "improved": improved,
        "comparison": comparison,
    }
    cs["history"].append(history_entry)
    cs["last_calibration"] = new_verdict

    # 如果修正后校验通过，结束修正
    if verdict_key == "passed":
        return {
            "round": current_round,
            "correction_type": actual_type,
            "verdict": new_verdict,
            "comparison": comparison,
            "correction_result": correction_result,
            "can_continue": False,
            "need_degrade": False,
            "degrade_reason": "",
            "next_path": None,
            "message": f"第{current_round}轮修正后校验通过，命盘准确度达标。",
        }

    # 决定下一步
    if not improved:
        # 当前路径无效
        if actual_type == "ai_fix":
            # AI修正无效 → 尝试切到时钟修正
            if current_round < MAX_CORRECTION_ROUNDS:
                next_path = "hour_fix"
                message = (
                    f"第{current_round}轮AI修正未能改善校验结果。"
                    f"建议尝试时钟修正（路径一）。"
                )
                can_continue = True
            else:
                next_path = None
                cs["degraded"] = True
                cs["degraded_reason"] = (
                    f"已完成{MAX_CORRECTION_ROUNDS}轮修正，"
                    f"AI修正和时钟修正均未能产生有效改善。"
                    f"系统无法在当前条件下给出可靠推断，建议确认出生时辰。"
                )
                message = cs["degraded_reason"]
                can_continue = False
        elif actual_type == "hour_fix":
            if current_round < MAX_CORRECTION_ROUNDS and correction_result.get("all_candidates_failed"):
                # 候选时钟全失败，试试AI修正
                next_path = "ai_fix"
                message = (
                    f"第{current_round}轮时钟修正中所有候选时钟均未改善结果。"
                    f"建议尝试AI修正（路径二）。"
                )
                can_continue = True
            else:
                next_path = None
                cs["degraded"] = True
                cs["degraded_reason"] = (
                    f"已完成{MAX_CORRECTION_ROUNDS}轮修正，"
                    f"时钟修正未能产生有效改善。"
                    f"系统无法在当前条件下给出可靠推断，建议确认出生时辰。"
                )
                message = cs["degraded_reason"]
                can_continue = False
        else:
            next_path = None
            can_continue = current_round < MAX_CORRECTION_ROUNDS
            message = "修正效果不明显，请确认是否需要继续。"
    else:
        # 当前路径有效，可以继续
        if current_round < MAX_CORRECTION_ROUNDS:
            next_path = actual_type
            message = f"第{current_round}轮修正已完成，有改善。可以继续下一轮修正以进一步优化。"
            can_continue = True
        else:
            next_path = None
            message = f"已完成{MAX_CORRECTION_ROUNDS}轮修正，修正已完成。"
            can_continue = False

    return {
        "round": current_round,
        "correction_type": actual_type,
        "verdict": new_verdict,
        "comparison": comparison,
        "correction_result": correction_result,
        "can_continue": can_continue,
        "need_degrade": not can_continue and not improved and current_round >= MAX_CORRECTION_ROUNDS,
        "degrade_reason": cs.get("degraded_reason", ""),
        "next_path": next_path,
        "message": message,
    }


def get_correction_status(session: dict) -> dict:
    """
    获取当前会话的修正状态摘要。

    Args:
        session: 会话字典

    Returns:
        修正状态摘要
    """
    cs = session.get("correction_state", {})
    if not cs:
        return {
            "round": 0,
            "degraded": False,
            "history": [],
            "can_continue": True,
        }

    return {
        "round": cs.get("round", 0),
        "degraded": cs.get("degraded", False),
        "degraded_reason": cs.get("degraded_reason", ""),
        "current_path": cs.get("current_path"),
        "history": cs.get("history", []),
        "can_continue": (
            not cs.get("degraded", False)
            and cs.get("round", 0) < MAX_CORRECTION_ROUNDS
        ),
    }
