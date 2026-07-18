"""典籍原文判断模块 - 基于AI+原文判断日主得令、格局、旺衰、用神"""

import os
import re

from services.deepseek_client import call_deepseek

# ============================================================
# System Prompt
# ============================================================

SYSTEM_PROMPT = """你是一位严格遵循《子平真诠》《滴天髓》《穷通宝鉴》体系的子平派命理师。

你的任务是：根据提供的【经典原文】和【排盘数据】，以典籍原文为依据进行判断。

判断规则（必须严格遵守）：
1. 月令判断遵循《子平真诠》"用神专求月令"原则
2. 旺衰判断遵循《滴天髓》"能知衰旺之真机"原则
3. 调候判断遵循《穷通宝鉴》十天干按月取用原则
4. 格局判断遵循《子平真诠》"凡格从月令定"原则
5. 所有判断必须引用具体原文作为依据，不可主观臆断
6. 只遵循子平派体系，不混用其他流派

输出要求：
- 每条判断必须标注出典（书名+章节）
- 推理过程简明扼要，不超过150字
- 语言准确、客观"""


# ============================================================
# API Call
# ============================================================

async def _call_deepseek(prompt: str, system_prompt: str, timeout: int = 30) -> str:
    """Call DeepSeek API for classical judgment.

    Delegates to services.deepseek_client.call_deepseek.
    """
    return await call_deepseek(
        prompt=prompt,
        system_prompt=system_prompt,
        timeout=timeout,
        model="deepseek-chat",
        temperature=0.5,
        max_tokens=2000,
    )


def _is_error_response(response: str) -> bool:
    """Check if the API returned an error indicator instead of a valid judgment."""
    return bool(response) and response.startswith("[API_")


# ============================================================
# Format RAG results for prompt
# ============================================================

def _format_rag_results(rag_results: list[dict], max_chars: int = 4000) -> str:
    """Format RAG results into a prompt section with source attribution."""
    sections = []
    total_chars = 0

    for i, r in enumerate(rag_results, 1):
        source = r.get("source", "佚名")
        chapter = r.get("chapter", "")
        # Use the first 800 chars of full text as excerpt
        full_text = r.get("full_text", r.get("text", ""))
        excerpt = full_text[:800]
        if len(full_text) > 800:
            excerpt += "..."

        entry = f"\n### 原文{i}：《{source}·{chapter}》\n{excerpt}\n"
        if total_chars + len(entry) > max_chars:
            break
        sections.append(entry)
        total_chars += len(entry)

    return "\n".join(sections)


# ============================================================
# Prompt builders
# ============================================================

def _build_deling_prompt(chart_data: dict, rag_results: list[dict]) -> str:
    """Build prompt for deling (得令) judgment."""
    ri_zhu = chart_data.get("ri_zhu", "")
    ri_zhu_wx = chart_data.get("ri_zhu_wuxing", "")
    month_branch = chart_data.get("month_branch", "")
    month_hidden = chart_data.get("month_hidden_stems", [])

    hidden_desc = ", ".join(
        f"{h.get('stem', '')}({h.get('ten_god', '')})" for h in month_hidden
    ) if month_hidden else "无"

    return f"""请根据以下【经典原文】和【排盘数据】，判断日主的得令情况。

【排盘数据】
日主：{ri_zhu}（五行{ri_zhu_wx}）
月令地支：{month_branch}
月令藏干：{hidden_desc}

【经典原文】（关于得令/月令判断的原文）
{_format_rag_results(rag_results)}

请判断：
1. 日主是得令还是失令？（必须引用原文说明判断依据）
2. 得令的程度如何？（当令/略得令/失令）
3. 你的推理过程（不超过100字）

输出格式（请严格按此格式输出）：
得令情况：[当令/略得令/失令]
原文依据：[引用具体原文段落，标注出典]
推理过程：[简要推理]"""


def _build_wangshuai_prompt(chart_data: dict, rag_results: list[dict]) -> str:
    """Build prompt for wangshuai (旺衰) comprehensive judgment."""
    ri_zhu = chart_data.get("ri_zhu", "")
    ri_zhu_wx = chart_data.get("ri_zhu_wuxing", "")
    month_branch = chart_data.get("month_branch", "")
    month_stem = chart_data.get("month_stem", "")

    # Build four-pillar description
    year_stem = chart_data.get("year_stem", "")
    year_branch = chart_data.get("year_branch", "")
    day_branch = chart_data.get("day_branch", "")
    hour_stem = chart_data.get("hour_stem", "")
    hour_branch = chart_data.get("hour_branch", "")

    pillars_desc = f"""四柱：年{year_stem}{year_branch}、月{month_stem}{month_branch}、日{ri_zhu}{day_branch}、时{hour_stem}{hour_branch}
天干透出：年{year_stem}、月{month_stem}、时{hour_stem}（日主{ri_zhu}）"""

    month_hidden = chart_data.get("month_hidden_stems", [])
    hidden_desc = ", ".join(
        f"{h.get('stem', '')}({h.get('ten_god', '')})" for h in month_hidden
    ) if month_hidden else "无"

    return f"""请根据以下【经典原文】和【排盘数据】，判断日主的旺衰情况。

【排盘数据】
日主：{ri_zhu}（五行{ri_zhu_wx}）
月令地支：{month_branch}，月令藏干：{hidden_desc}
{pillars_desc}

【经典原文】（关于旺衰判断）
{_format_rag_results(rag_results)}

请判断：
1. 日主在月令是得令还是失令？（引用《滴天髓》或《子平真诠》原文）
2. 日主在地支中有无根基？根基深浅如何？
3. 天干有无生扶或帮身？
4. 综合判断日主旺衰（偏强/中和/偏弱/太旺/太弱）

输出格式（请严格按此格式输出）：
得令情况：[得令/略得令/失令]（引用原文）
根基情况：[有根/无根/根浅]（引用原文）
天干帮身：[有/无]（具体说明）
综合结论：[偏强/中和/偏弱/太旺/太弱]
解释：[用通俗语言解释，100-200字]"""


def _build_pattern_prompt(chart_data: dict, rag_results: list[dict]) -> str:
    """Build prompt for pattern (格局) judgment."""
    ri_zhu = chart_data.get("ri_zhu", "")
    ri_zhu_wx = chart_data.get("ri_zhu_wuxing", "")
    month_branch = chart_data.get("month_branch", "")
    month_stem = chart_data.get("month_stem", "")

    return f"""请根据以下【经典原文】和【排盘数据】，判断命局的格局类型。

【排盘数据】
日主：{ri_zhu}（五行{ri_zhu_wx}）
月柱：{month_stem}{month_branch}

【经典原文】（关于格局判断的原文）
{_format_rag_results(rag_results)}

请判断：
1. 此命局属于什么格局？（正官格/七杀格/财格/印格/食神格/伤官格/建禄格/从格等）
2. 格局的成败如何？
3. 引用原文说明判断依据

输出格式：
格局类型：[格局名称]
格局成败：[成格/败格/带忌]
原文依据：[引用具体原文段落，标注出典]
推理过程：[简要推理]"""


def _build_yongshen_prompt(chart_data: dict, rag_results: list[dict]) -> str:
    """Build prompt for yongshen (用神) three-angle judgment."""
    ri_zhu = chart_data.get("ri_zhu", "")
    ri_zhu_wx = chart_data.get("ri_zhu_wuxing", "")
    strength = chart_data.get("ri_zhu_strength", "")
    pattern = chart_data.get("pattern", "")

    # Extract month number from month_branch
    month_branch = chart_data.get("month_branch", "")
    MONTH_MAP = {
        "寅": "正月", "卯": "二月", "辰": "三月", "巳": "四月",
        "午": "五月", "未": "六月", "申": "七月", "酉": "八月",
        "戌": "九月", "亥": "十月", "子": "十一月", "丑": "十二月",
    }
    month_name = MONTH_MAP.get(month_branch, f"{month_branch}月")

    return f"""请从以下三个角度分析命局的用神：

【排盘数据】
日主：{ri_zhu}（五行{ri_zhu_wx}）
日主旺衰：{strength}
月令：{month_name}（{month_branch}）
当前格局：{pattern}

【经典原文】（关于用神判断）
{_format_rag_results(rag_results)}

请从以下三个角度分别判断用神，必须引用典籍原文：

角度一：扶抑法（《滴天髓》《子平真诠》）
- 日主{strength}，按照"旺则抑之，衰则扶之"原则
- 判断扶抑用神是什么五行？

角度二：调候法（《穷通宝鉴》）
- 日主{ri_zhu}，生于{month_name}
- 根据《穷通宝鉴》的调候规则，这个月需要什么五行来调节寒暖湿燥？

角度三：格局法（《子平真诠》）
- 当前格局是{pattern}
- 根据《子平真诠》的格局用神规则，这个格局需要什么五行？

综合结论：
- 三种方法结论是否一致？
- 如果一致，这个用神比较可靠
- 如果不一致，解释为什么会有差异，给出优先级建议（通常：格局用神 > 调候用神 > 扶抑用神）

输出格式（请严格按此格式输出）：
扶抑用神：[五行]
调候用神：[五行]
格局用神：[五行]
一致性：[一致/部分一致/矛盾]
综合分析：[解释差异原因和优先级建议，50-100字]
综合结论：[推荐的用神五行]"""


# ============================================================
# Parse AI responses
# ============================================================

def _parse_field(response: str, field_name: str, patterns: list[str] = None) -> str:
    """Parse a single field from an AI response using regex patterns."""
    if patterns is None:
        patterns = [rf"{field_name}[：:]\s*(.+)"]
    for pattern in patterns:
        match = re.search(pattern, response)
        if match:
            return match.group(1).strip()
    return ""


def _parse_deling_response(response: str) -> dict:
    """Parse AI response for deling judgment.

    Returns a dict with parse_status field indicating success or failure.
    When parsing fails, raw_response is preserved and key fields are marked.
    """
    result = {
        "deling_status": "",
        "deling_level": "",
        "source_citation": "",
        "reasoning": "",
        "raw_response": response,
        "parse_status": "ok",
    }

    result["deling_status"] = _parse_field(response, "得令情况")
    result["source_citation"] = _parse_field(response, "原文依据")
    result["reasoning"] = _parse_field(response, "推理过程")

    # Determine deling level
    status = result["deling_status"]
    if "当令" in status:
        result["deling_level"] = "当令"
    elif "略得令" in status:
        result["deling_level"] = "略得令"
    elif "失令" in status:
        result["deling_level"] = "失令"
    elif "得令" in status:
        result["deling_level"] = "得令"

    # Check if parsing was successful (key field must be populated)
    if not result["deling_status"]:
        result["parse_status"] = "解析失败：AI 未按预期格式返回得令情况，请查看 raw_response"

    return result


def _parse_wangshuai_response(response: str) -> dict:
    """Parse AI response for wangshuai (旺衰) judgment.

    Returns a dict with:
        deling_status, root_status, tian_gan_bang, conclusion, explanation,
        raw_response, parse_status
    """
    result = {
        "deling_status": "",
        "root_status": "",
        "tian_gan_bang": "",
        "conclusion": "",
        "explanation": "",
        "raw_response": response,
        "parse_status": "ok",
    }

    result["deling_status"] = _parse_field(response, "得令情况")
    result["root_status"] = _parse_field(response, "根基情况")
    result["tian_gan_bang"] = _parse_field(response, "天干帮身")
    result["conclusion"] = _parse_field(response, "综合结论")
    result["explanation"] = _parse_field(response, "解释")

    # Check if parsing was successful
    if not result["conclusion"]:
        result["parse_status"] = "解析失败：AI 未按预期格式返回综合结论，请查看 raw_response"

    return result


def _parse_pattern_response(response: str) -> dict:
    """Parse AI response for pattern judgment.

    Returns a dict with parse_status field indicating success or failure.
    When parsing fails, raw_response is preserved and key fields are marked.
    """
    result = {
        "pattern_type": "",
        "pattern_result": "",
        "source_citation": "",
        "reasoning": "",
        "raw_response": response,
        "parse_status": "ok",
    }

    result["pattern_type"] = _parse_field(response, "格局类型")
    result["pattern_result"] = _parse_field(response, "格局成败")
    result["source_citation"] = _parse_field(response, "原文依据")
    result["reasoning"] = _parse_field(response, "推理过程")

    # Check if parsing was successful (key field must be populated)
    if not result["pattern_type"]:
        result["parse_status"] = "解析失败：AI 未按预期格式返回格局类型，请查看 raw_response"

    return result


def _parse_yongshen_response(response: str) -> dict:
    """Parse AI response for three-angle yongshen judgment.

    Returns a dict with:
        fuyi_yongshen, tiaohou_yongshen, geju_yongshen,
        consistency, comprehensive_analysis, final_conclusion,
        raw_response, parse_status
    Also backward-compatible fields: yongshen_wuxing, xishen_wuxing, jishen_wuxing, principle
    """
    result = {
        # Three-angle fields
        "fuyi_yongshen": "",
        "tiaohou_yongshen": "",
        "geju_yongshen": "",
        "consistency": "",
        "comprehensive_analysis": "",
        "final_conclusion": "",
        # Backward-compatible fields
        "yongshen_wuxing": "",
        "xishen_wuxing": "",
        "jishen_wuxing": "",
        "principle": "",
        "source_citation": "",
        "reasoning": "",
        "raw_response": response,
        "parse_status": "ok",
    }

    result["fuyi_yongshen"] = _parse_field(response, "扶抑用神")
    result["tiaohou_yongshen"] = _parse_field(response, "调候用神")
    result["geju_yongshen"] = _parse_field(response, "格局用神")
    result["consistency"] = _parse_field(response, "一致性")
    result["comprehensive_analysis"] = _parse_field(response, "综合分析")
    result["final_conclusion"] = _parse_field(response, "综合结论")

    # Backward-compatible: yongshen_wuxing maps to final_conclusion
    result["yongshen_wuxing"] = result["final_conclusion"]
    result["principle"] = f"三角度综合（扶抑={result['fuyi_yongshen']}，调候={result['tiaohou_yongshen']}，格局={result['geju_yongshen']}）"

    # Check if parsing was successful
    if not result["final_conclusion"] and not result["fuyi_yongshen"]:
        result["parse_status"] = "解析失败：AI 未按预期格式返回用神分析，请查看 raw_response"

    return result


# ============================================================
# Mock Mode - template-based judgment
# ============================================================

def _mock_deling_judge(chart_data: dict, rag_results: list[dict]) -> dict:
    """Template-based deling judgment from retrieved texts."""
    ri_zhu_wx = chart_data.get("ri_zhu_wuxing", "")
    month_branch = chart_data.get("month_branch", "")

    # Find month-branch-specific content from rag
    deling_texts = [r for r in rag_results if "旺衰" in r.get("topic", "") or "得令" in r.get("topic", "") or "用神" in r.get("topic", "")]
    if not deling_texts:
        deling_texts = rag_results[:3] if rag_results else []

    # Build source citations
    citations = []
    for r in deling_texts[:2]:
        full_text = r.get("full_text", r.get("text", ""))
        excerpt = full_text[:200].replace("\n", " ")
        citations.append(f"《{r['source']}·{r['chapter']}》：{excerpt}")

    source_str = "；".join(citations) if citations else "《子平真诠·论用神》：用神专求月令，以日干配月令地支，而生克不同，格局分焉。"

    # Simple rule-based judgment based on month branch and day master wuxing
    MONTH_WUXING = {
        "寅": "木", "卯": "木",
        "巳": "火", "午": "火",
        "申": "金", "酉": "金",
        "亥": "水", "子": "水",
        "辰": "土", "戌": "土", "丑": "土", "未": "土",
    }
    month_wx = MONTH_WUXING.get(month_branch, "")

    if month_wx == ri_zhu_wx:
        status = "得令"
        level = "当令"
        reasoning = f"月令{month_branch}属{month_wx}，与日主五行{ri_zhu_wx}相同。月令与日主同五行，日主得月令之气为当令，力量最强。"
    elif _is_yin_star(ri_zhu_wx, month_wx):
        status = "得令"
        level = "得令"
        reasoning = f"月令{month_branch}属{month_wx}，为日主{ri_zhu_wx}之印星。月令印星生扶日主，日主有根有源，为得令。"
    else:
        status = "失令"
        level = "失令"
        reasoning = f"月令{month_branch}属{month_wx}，与日主五行{ri_zhu_wx}无直接生扶关系。日主在月令中不得助力，为失令。"

    return {
        "deling_status": status,
        "deling_level": level,
        "source_citation": source_str,
        "reasoning": reasoning,
        "method": "mock_template",
    }


def _mock_wangshuai_judge(chart_data: dict, rag_results: list[dict]) -> dict:
    """Template-based wangshuai (旺衰) comprehensive judgment."""
    ri_zhu = chart_data.get("ri_zhu", "")
    ri_zhu_wx = chart_data.get("ri_zhu_wuxing", "")
    month_branch = chart_data.get("month_branch", "")
    strength = chart_data.get("ri_zhu_strength", "中和")

    # Determine deling
    MONTH_WUXING = {
        "寅": "木", "卯": "木",
        "巳": "火", "午": "火",
        "申": "金", "酉": "金",
        "亥": "水", "子": "水",
        "辰": "土", "戌": "土", "丑": "土", "未": "土",
    }
    month_wx = MONTH_WUXING.get(month_branch, "")

    if month_wx == ri_zhu_wx:
        deling_text = f"得令（月令{month_branch}与日主同五行）"
        deling_quote = "《滴天髓》：月令为提纲，旺衰之枢纽也"
    elif _is_yin_star(ri_zhu_wx, month_wx):
        deling_text = f"略得令（月令{month_branch}为印星生扶）"
        deling_quote = "《滴天髓》：月令为提纲，旺衰之枢纽也"
    else:
        deling_text = f"失令（月令{month_branch}克泄日主{ri_zhu_wx}）"
        deling_quote = "《子平真诠》：月令者，八字之提纲也，旺衰由是而定"

    # Determine root based on strength_detail
    root_text = ""
    root_quote = "《滴天髓》：欲识三元万法宗，先观帝载与神功（根基为旺衰之根本）"
    if strength in ("太旺", "偏强"):
        root_text = "有根（地支有本气或中气根）"
    elif strength == "中和":
        root_text = "根浅（地支有中气或余气根）"
    else:
        root_text = "无根/根浅（地支根基薄弱）"

    # Tian gan bang
    tian_gan_text = ""
    if strength in ("太旺", "偏强"):
        tian_gan_text = "有天干生扶/帮身"
    elif strength == "中和":
        tian_gan_text = "天干帮身力量一般"
    else:
        tian_gan_text = "天干无有力帮身/生扶不足"

    # Map rule engine strength to classical conclusion
    strength_to_conclusion = {
        "太旺": "太旺",
        "偏强": "偏强",
        "中和": "中和",
        "偏弱": "偏弱",
        "太弱": "太弱",
        "极弱": "太弱",
        "极强": "太旺",
    }
    conclusion = strength_to_conclusion.get(strength, "中和")

    # Build explanation
    explanation = (
        f"日主{ri_zhu}（{ri_zhu_wx}）生于{month_branch}月，{deling_text}。"
        f"四柱地支综合来看{root_text}。"
        f"天干方面{tian_gan_text}。"
        f"综合判断日主旺衰为{conclusion}。"
    )

    # Build citations
    wangshuai_texts = [r for r in rag_results if "旺衰" in r.get("topic", "")]
    if not wangshuai_texts:
        wangshuai_texts = rag_results[:2] if rag_results else []

    citations = []
    for r in wangshuai_texts[:2]:
        full_text = r.get("full_text", r.get("text", ""))
        excerpt = full_text[:200].replace("\n", " ")
        citations.append(f"《{r['source']}·{r['chapter']}》：{excerpt}")

    source_str = "；".join(citations) if citations else f"{deling_quote}；{root_quote}"

    return {
        "deling_status": deling_text,
        "root_status": root_text,
        "tian_gan_bang": tian_gan_text,
        "conclusion": conclusion,
        "explanation": explanation,
        "source_citation": source_str,
        "method": "mock_template",
    }


def _mock_pattern_judge(chart_data: dict, rag_results: list[dict]) -> dict:
    """Template-based pattern judgment."""
    month_branch = chart_data.get("month_branch", "")
    ri_zhu_wx = chart_data.get("ri_zhu_wuxing", "")

    # Build citations from relevant texts
    pattern_texts = [r for r in rag_results if "格局" in r.get("topic", "")]
    if not pattern_texts:
        pattern_texts = rag_results[:2] if rag_results else []

    citations = []
    for r in pattern_texts[:2]:
        full_text = r.get("full_text", r.get("text", ""))
        excerpt = full_text[:200].replace("\n", " ")
        citations.append(f"《{r['source']}·{r['chapter']}》：{excerpt}")

    source_str = "；".join(citations) if citations else "《子平真诠·论格局》：月令者，八字之提纲也。凡格从月令定，故曰格局。"

    reasoning = f"月令为{month_branch}，日主五行{ri_zhu_wx}。根据《子平真诠》'凡格从月令定'原则，格局取月令本气为格。"

    return {
        "pattern_type": "正格",
        "pattern_result": "待进一步确认",
        "source_citation": source_str,
        "reasoning": reasoning,
        "method": "mock_template",
    }


def _mock_yongshen_judge(chart_data: dict, rag_results: list[dict]) -> dict:
    """Template-based three-angle yongshen judgment."""
    ri_zhu = chart_data.get("ri_zhu", "")
    ri_zhu_wx = chart_data.get("ri_zhu_wuxing", "")
    strength = chart_data.get("ri_zhu_strength", "中和")
    pattern = chart_data.get("pattern", "")
    month_branch = chart_data.get("month_branch", "")

    SELF_WX = ri_zhu_wx
    # Five-element cycle: 金生水，水生木，木生火，火生土，土生金
    SHENG_CYCLE = {"金": "水", "水": "木", "木": "火", "火": "土", "土": "金"}
    # Reverse: 生我者
    SHENG_ME = {v: k for k, v in SHENG_CYCLE.items()}
    # 我克者
    KE_CYCLE = {"金": "木", "木": "土", "土": "水", "水": "火", "火": "金"}
    # 克我者
    KE_ME = {v: k for k, v in KE_CYCLE.items()}

    # --- Angle 1: 扶抑法 ---
    if strength in ("偏强", "太旺", "极强"):
        fuyi_ys = KE_ME.get(SELF_WX, "")  # 官杀（克我）
    elif strength in ("偏弱", "太弱", "极弱"):
        fuyi_ys = SHENG_ME.get(SELF_WX, "")  # 印星（生我）
    else:
        fuyi_ys = SHENG_ME.get(SELF_WX, "")  # 中和偏扶

    # --- Angle 2: 调候法 (Qiongtong Baojian) ---
    # Simplified tiaohou rules based on day master + month
    TIAOHOU_RULES = {
        # 甲木
        ("甲", "寅"): "火", ("甲", "卯"): "火", ("甲", "辰"): "火",
        ("甲", "巳"): "水", ("甲", "午"): "水", ("甲", "未"): "水",
        ("甲", "申"): "火", ("甲", "酉"): "火", ("甲", "戌"): "火",
        ("甲", "亥"): "火", ("甲", "子"): "火", ("甲", "丑"): "火",
        # 乙木
        ("乙", "寅"): "火", ("乙", "卯"): "水", ("乙", "辰"): "水",
        ("乙", "巳"): "水", ("乙", "午"): "水", ("乙", "未"): "水",
        ("乙", "申"): "火", ("乙", "酉"): "火", ("乙", "戌"): "火",
        ("乙", "亥"): "火", ("乙", "子"): "火", ("乙", "丑"): "火",
        # 丙火
        ("丙", "寅"): "水", ("丙", "卯"): "水", ("丙", "辰"): "水",
        ("丙", "巳"): "水", ("丙", "午"): "水", ("丙", "未"): "水",
        ("丙", "申"): "水", ("丙", "酉"): "水", ("丙", "戌"): "水",
        ("丙", "亥"): "木", ("丙", "子"): "木", ("丙", "丑"): "木",
        # 丁火
        ("丁", "寅"): "木", ("丁", "卯"): "木", ("丁", "辰"): "木",
        ("丁", "巳"): "水", ("丁", "午"): "水", ("丁", "未"): "水",
        ("丁", "申"): "木", ("丁", "酉"): "木", ("丁", "戌"): "木",
        ("丁", "亥"): "木", ("丁", "子"): "木", ("丁", "丑"): "木",
        # 戊土
        ("戊", "寅"): "火", ("戊", "卯"): "火", ("戊", "辰"): "火",
        ("戊", "巳"): "水", ("戊", "午"): "水", ("戊", "未"): "水",
        ("戊", "申"): "火", ("戊", "酉"): "火", ("戊", "戌"): "火",
        ("戊", "亥"): "火", ("戊", "子"): "火", ("戊", "丑"): "火",
        # 己土
        ("己", "寅"): "火", ("己", "卯"): "火", ("己", "辰"): "火",
        ("己", "巳"): "水", ("己", "午"): "水", ("己", "未"): "水",
        ("己", "申"): "火", ("己", "酉"): "火", ("己", "戌"): "火",
        ("己", "亥"): "火", ("己", "子"): "火", ("己", "丑"): "火",
        # 庚金
        ("庚", "寅"): "火", ("庚", "卯"): "火", ("庚", "辰"): "火",
        ("庚", "巳"): "水", ("庚", "午"): "水", ("庚", "未"): "水",
        ("庚", "申"): "火", ("庚", "酉"): "火", ("庚", "戌"): "火",
        ("庚", "亥"): "火", ("庚", "子"): "火", ("庚", "丑"): "火",
        # 辛金
        ("辛", "寅"): "火", ("辛", "卯"): "火", ("辛", "辰"): "火",
        ("辛", "巳"): "水", ("辛", "午"): "水", ("辛", "未"): "水",
        ("辛", "申"): "火", ("辛", "酉"): "火", ("辛", "戌"): "火",
        ("辛", "亥"): "火", ("辛", "子"): "火", ("辛", "丑"): "火",
        # 壬水
        ("壬", "寅"): "火", ("壬", "卯"): "火", ("壬", "辰"): "火",
        ("壬", "巳"): "水", ("壬", "午"): "水", ("壬", "未"): "水",
        ("壬", "申"): "火", ("壬", "酉"): "火", ("壬", "戌"): "火",
        ("壬", "亥"): "火", ("壬", "子"): "火", ("壬", "丑"): "火",
        # 癸水
        ("癸", "寅"): "火", ("癸", "卯"): "火", ("癸", "辰"): "火",
        ("癸", "巳"): "水", ("癸", "午"): "水", ("癸", "未"): "水",
        ("癸", "申"): "火", ("癸", "酉"): "火", ("癸", "戌"): "火",
        ("癸", "亥"): "火", ("癸", "子"): "火", ("癸", "丑"): "火",
    }
    tiaohou_ys = TIAOHOU_RULES.get((ri_zhu, month_branch), "火")

    # --- Angle 3: 格局法 ---
    # Simplified: based on pattern type
    if "从弱" in pattern:
        geju_ys = KE_ME.get(SELF_WX, "")  # 顺弱势取官杀
    elif "从强" in pattern:
        geju_ys = SHENG_ME.get(SELF_WX, "")  # 顺强势取印星
    elif "身强" in pattern:
        geju_ys = KE_ME.get(SELF_WX, "")  # 取官杀
    elif "身弱" in pattern:
        geju_ys = SHENG_ME.get(SELF_WX, "")  # 取印星
    else:
        geju_ys = SHENG_ME.get(SELF_WX, "")

    # --- Consistency check ---
    angles = [fuyi_ys, tiaohou_ys, geju_ys]
    unique = len(set(a for a in angles if a))
    if unique == 1:
        consistency = "一致"
        consistency_note = "三种方法结论一致，用神可靠度较高"
    elif unique == 2:
        consistency = "部分一致"
        consistency_note = "两种方法一致，建议优先参考格局法"
    else:
        consistency = "矛盾"
        consistency_note = "三种方法各执一说，建议以格局用神为准（格局用神 > 调候用神 > 扶抑用神）"

    # Final conclusion: prefer geju > tiaohou > fuyi
    final_yongshen = geju_ys or tiaohou_ys or fuyi_ys

    # Build citations
    yongshen_texts = [r for r in rag_results if "用神" in r.get("topic", "")]
    if not yongshen_texts:
        yongshen_texts = rag_results[:2] if rag_results else []

    citations = []
    for r in yongshen_texts[:2]:
        full_text = r.get("full_text", r.get("text", ""))
        excerpt = full_text[:200].replace("\n", " ")
        citations.append(f"《{r['source']}·{r['chapter']}》：{excerpt}")

    source_str = "；".join(citations) if citations else (
        "《子平真诠·论用神》：用神者，命中最需要之物也。旺则抑之，衰则扶之。；"
        "《穷通宝鉴》：各月调候取用，以寒暖湿燥为急务。"
    )

    return {
        # Three-angle
        "fuyi_yongshen": fuyi_ys,
        "tiaohou_yongshen": tiaohou_ys,
        "geju_yongshen": geju_ys,
        "consistency": consistency,
        "comprehensive_analysis": consistency_note,
        "final_conclusion": final_yongshen,
        # Backward-compatible
        "yongshen_wuxing": final_yongshen,
        "xishen_wuxing": SHENG_ME.get(final_yongshen, ""),
        "jishen_wuxing": KE_ME.get(SELF_WX, ""),
        "principle": f"三角度综合（扶抑={fuyi_ys}，调候={tiaohou_ys}，格局={geju_ys}），{consistency_note}",
        "source_citation": source_str,
        "reasoning": f"扶抑法：日主{strength}→取{fuyi_ys}；调候法：{ri_zhu}生{month_branch}月→取{tiaohou_ys}；格局法：{pattern}→取{geju_ys}。{consistency_note}",
        "method": "mock_template",
    }


def _is_yin_star(day_master_wx: str, target_wx: str) -> bool:
    """Check if target_wx is the 印星 (element that gives birth to) of day_master_wx."""
    SHENG_ME = {"金": "土", "木": "水", "水": "金", "火": "木", "土": "火"}
    return SHENG_ME.get(day_master_wx, "") == target_wx


# ============================================================
# Main Functions - Individual Judgments
# ============================================================

async def judge_deling_from_classics(
    chart_data: dict, rag_results: list[dict]
) -> dict:
    """
    Judge deling (得令) based on classical texts + AI.

    Args:
        chart_data: chart info with ri_zhu, ri_zhu_wuxing, month_branch, etc.
        rag_results: RAG-retrieved chapter texts

    Returns:
        dict with deling_status, deling_level, source_citation, reasoning
    """
    prompt = _build_deling_prompt(chart_data, rag_results)
    response = await _call_deepseek(prompt, SYSTEM_PROMPT)

    if response and not _is_error_response(response):
        result = _parse_deling_response(response)
        result["method"] = "ai_deepseek"
        return result

    # Fallback to mock on empty response or API error
    return _mock_deling_judge(chart_data, rag_results)


async def judge_wangshuai_from_classics(
    chart_data: dict, rag_results: list[dict]
) -> dict:
    """从典籍原文判断日主旺衰

    判断日主在月令得令与否、在地支有无根基、天干帮身情况，
    最终给出综合旺衰结论。不依赖分数，直接从原文推理。

    Args:
        chart_data: chart info with ri_zhu, ri_zhu_wuxing, month_branch,
                    year_stem/branch, day_branch, hour_stem/branch, etc.
        rag_results: RAG-retrieved chapter texts

    Returns:
        dict with:
            deling_status: 得令情况
            root_status: 根基情况
            tian_gan_bang: 天干帮身
            conclusion: 综合结论（偏强/中和/偏弱/太旺/太弱）
            explanation: 通俗解释
            source_citation: 原文引用
    """
    prompt = _build_wangshuai_prompt(chart_data, rag_results)
    response = await _call_deepseek(prompt, SYSTEM_PROMPT)

    if response and not _is_error_response(response):
        result = _parse_wangshuai_response(response)
        result["method"] = "ai_deepseek"
        return result

    return _mock_wangshuai_judge(chart_data, rag_results)


async def judge_pattern_from_classics(
    chart_data: dict, rag_results: list[dict]
) -> dict:
    """
    Judge pattern (格局) based on classical texts + AI.

    Args:
        chart_data: chart info
        rag_results: RAG-retrieved chapter texts

    Returns:
        dict with pattern_type, pattern_result, source_citation, reasoning
    """
    prompt = _build_pattern_prompt(chart_data, rag_results)
    response = await _call_deepseek(prompt, SYSTEM_PROMPT)

    if response and not _is_error_response(response):
        result = _parse_pattern_response(response)
        result["method"] = "ai_deepseek"
        return result

    return _mock_pattern_judge(chart_data, rag_results)


async def judge_yongshen_from_classics(
    chart_data: dict, rag_results: list[dict]
) -> dict:
    """从典籍原文多角度判断用神

    返回三个角度的分析 + 综合结论：
    - 扶抑法（《滴天髓》《子平真诠》）：身强取克泄耗，身弱取生扶
    - 调候法（《穷通宝鉴》）：按日干+月份取调候用神
    - 格局法（《子平真诠》）：取格局所需的用神

    Args:
        chart_data: chart info including ri_zhu_strength, pattern
        rag_results: RAG-retrieved chapter texts

    Returns:
        dict with three-angle analysis + final conclusion,
        plus backward-compatible yongshen_wuxing, xishen_wuxing, etc.
    """
    prompt = _build_yongshen_prompt(chart_data, rag_results)
    response = await _call_deepseek(prompt, SYSTEM_PROMPT, timeout=35)

    if response and not _is_error_response(response):
        result = _parse_yongshen_response(response)
        result["method"] = "ai_deepseek"
        return result

    return _mock_yongshen_judge(chart_data, rag_results)


# ============================================================
# Main Functions - Combined Judgment
# ============================================================

async def judge_from_classics(
    chart_data: dict, rag_results: list[dict]
) -> dict:
    """
    Full classical judgment: wangshuai + deling + pattern + yongshen (three-angle).

    This is the main entry point for the /api/classical-analysis endpoint.

    Args:
        chart_data: complete chart data with ri_zhu, ri_zhu_wuxing, month_branch,
                    month_hidden_stems, ri_zhu_strength, etc.
        rag_results: RAG-retrieved chapter texts

    Returns:
        dict with wangshuai, deling, pattern, yongshen sections, each with source citations
    """
    has_api_key = bool(os.getenv("DEEPSEEK_API_KEY"))

    if has_api_key:
        # Run all judgments in parallel with a single combined prompt
        combined_prompt = _build_combined_prompt(chart_data, rag_results)
        response = await _call_deepseek(combined_prompt, SYSTEM_PROMPT, timeout=60)
        if response and not _is_error_response(response):
            return _parse_combined_response(response, chart_data, rag_results)

    # Mock mode: individual template judgments
    wangshuai = _mock_wangshuai_judge(chart_data, rag_results)
    deling = _mock_deling_judge(chart_data, rag_results)
    pattern = _mock_pattern_judge(chart_data, rag_results)
    yongshen = _mock_yongshen_judge(chart_data, rag_results)

    return {
        "wangshuai": wangshuai,
        "deling": deling,
        "pattern": pattern,
        "yongshen": yongshen,
        "sources": _build_source_list(rag_results),
        "method": "mock_template",
    }


def _build_combined_prompt(chart_data: dict, rag_results: list[dict]) -> str:
    """Build a combined prompt for all judgments: wangshuai + pattern + yongshen."""
    ri_zhu = chart_data.get("ri_zhu", "")
    ri_zhu_wx = chart_data.get("ri_zhu_wuxing", "")
    month_branch = chart_data.get("month_branch", "")
    month_stem = chart_data.get("month_stem", "")
    strength = chart_data.get("ri_zhu_strength", "")
    pattern_rule = chart_data.get("pattern", "")
    yongshen_rule = chart_data.get("yongshen_rule", {})

    # Build four-pillar description
    year_stem = chart_data.get("year_stem", "")
    year_branch = chart_data.get("year_branch", "")
    day_branch = chart_data.get("day_branch", "")
    hour_stem = chart_data.get("hour_stem", "")
    hour_branch = chart_data.get("hour_branch", "")

    # Extract month number
    MONTH_MAP = {
        "寅": "正月", "卯": "二月", "辰": "三月", "巳": "四月",
        "午": "五月", "未": "六月", "申": "七月", "酉": "八月",
        "戌": "九月", "亥": "十月", "子": "十一月", "丑": "十二月",
    }
    month_name = MONTH_MAP.get(month_branch, f"{month_branch}月")

    return f"""请根据以下【经典原文】和【排盘数据】，完成四项判断。

【排盘数据】
日主：{ri_zhu}（五行{ri_zhu_wx}）
月柱：{month_stem}{month_branch}（{month_name}）
四柱：年{year_stem}{year_branch}、月{month_stem}{month_branch}、日{ri_zhu}{day_branch}、时{hour_stem}{hour_branch}
日主旺衰（规则引擎参考）：{strength}
格局（规则引擎参考）：{pattern_rule}
用神（规则引擎参考）：{yongshen_rule}

【经典原文】
{_format_rag_results(rag_results, max_chars=6000)}

请完成以下四项判断。每项必须引用具体原文并标注出典（书名+章节）。

## 一、旺衰判断
判断日主得令情况、根基深浅、天干帮身情况，综合判断日主旺衰。
引用《滴天髓》或《子平真诠》关于旺衰判断的原文。

## 二、格局判断
判断命局格局类型及成败。引用《子平真诠》关于格局的原文。

## 三、用神判断（三个角度）
从扶抑法（《滴天髓》）、调候法（《穷通宝鉴》）、格局法（《子平真诠》）三个角度判断用神，
分析三种方法的结论是否一致，给出综合结论。

请按以下格式输出：
---旺衰---
得令情况：[得令/略得令/失令]（引用原文）
根基情况：[有根/无根/根浅]（引用原文）
天干帮身：[有/无]（具体说明）
综合结论：[偏强/中和/偏弱/太旺/太弱]
解释：[通俗解释，100-200字]

---格局---
格局类型：...
格局成败：...
原文依据：...
推理过程：...

---用神---
扶抑用神：[五行]
调候用神：[五行]
格局用神：[五行]
一致性：[一致/部分一致/矛盾]
综合分析：[解释差异原因和优先级建议]
综合结论：[推荐的用神五行]"""


def _parse_combined_response(
    response: str, chart_data: dict, rag_results: list[dict]
) -> dict:
    """Parse the combined AI response into structured judgment."""
    # Extract sections
    wangshuai_section = _extract_section(response, "旺衰")
    pattern_section = _extract_section(response, "格局")
    yongshen_section = _extract_section(response, "用神")

    wangshuai = _parse_wangshuai_response(wangshuai_section) if wangshuai_section else _mock_wangshuai_judge(chart_data, rag_results)
    pattern = _parse_pattern_response(pattern_section) if pattern_section else _mock_pattern_judge(chart_data, rag_results)
    yongshen = _parse_yongshen_response(yongshen_section) if yongshen_section else _mock_yongshen_judge(chart_data, rag_results)

    wangshuai["method"] = "ai_deepseek"
    pattern["method"] = "ai_deepseek"
    yongshen["method"] = "ai_deepseek"

    return {
        "wangshuai": wangshuai,
        "deling": _extract_deling_from_wangshuai(wangshuai),
        "pattern": pattern,
        "yongshen": yongshen,
        "sources": _build_source_list(rag_results),
        "method": "ai_deepseek",
    }


def _extract_deling_from_wangshuai(wangshuai: dict) -> dict:
    """Extract deling info from wangshuai result for backward compatibility."""
    deling_status = wangshuai.get("deling_status", "")
    deling_level = ""
    if "当令" in deling_status:
        deling_level = "当令"
    elif "略得令" in deling_status:
        deling_level = "略得令"
    elif "失令" in deling_status:
        deling_level = "失令"
    elif "得令" in deling_status:
        deling_level = "得令"

    return {
        "deling_status": deling_status,
        "deling_level": deling_level,
        "source_citation": wangshuai.get("source_citation", ""),
        "reasoning": wangshuai.get("explanation", ""),
        "method": wangshuai.get("method", ""),
    }


def _extract_section(text: str, section_name: str) -> str:
    """Extract a named section from the combined response."""
    pattern = rf"---{section_name}---\s*(.*?)(?=---\w+---|$)"
    match = re.search(pattern, text, re.DOTALL)
    return match.group(1).strip() if match else ""


def _build_source_list(rag_results: list[dict]) -> list[dict]:
    """Build a deduplicated source list from RAG results."""
    sources = []
    seen = set()
    for r in rag_results:
        key = (r.get("source", ""), r.get("chapter", ""))
        if key not in seen:
            seen.add(key)
            full_text = r.get("full_text") or r.get("text") or ""
            excerpt = " ".join(str(full_text).split())[:260]
            sources.append({
                "source": r.get("source", ""),
                "chapter": r.get("chapter", ""),
                "chapter_id": r.get("id", ""),
                "topic": r.get("topic", ""),
                "context": r.get("context", ""),
                "excerpt": excerpt,
                "score": r.get("score", 0),
                "keywords_matched": r.get("keywords_matched", []),
            })
    return sources


# ============================================================
# Mock: local template analysis (no API key)
# ============================================================

def mock_classical_judge(chart_data: dict, rag_results: list[dict]) -> dict:
    """
    Local template analysis (no API call).
    Extracts key sentences from retrieved texts and generates templated judgment.

    This is the synchronous version of judge_from_classics for mock mode.
    """
    wangshuai = _mock_wangshuai_judge(chart_data, rag_results)
    deling = _mock_deling_judge(chart_data, rag_results)
    pattern = _mock_pattern_judge(chart_data, rag_results)
    yongshen = _mock_yongshen_judge(chart_data, rag_results)

    return {
        "wangshuai": wangshuai,
        "deling": deling,
        "pattern": pattern,
        "yongshen": yongshen,
        "sources": _build_source_list(rag_results),
        "method": "mock_template",
    }
