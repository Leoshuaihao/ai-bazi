"""P0 重分析模块 - 从 chart_data 重新计算旺衰 + 典籍分析 + 出典列表

供 calibrate_confirm_time 等端点复用，避免在每个端点中内联相同逻辑。
"""

import copy

from rules.yongshen import calculate_strength_detail, _determine_yongshen_detail
from rules.wuxing import WUXING_MAP, HIDDEN_STEMS_MAP
from services.rag_retriever import (
    retrieve_relevant_texts,
    extract_keywords_from_chart,
    retrieve_by_keywords,
    retrieve_all_stages,
    merge_stage_results,
)
from services.classical_judge import mock_classical_judge


def _source_excerpt(item: dict, limit: int = 260) -> str:
    text = item.get("full_text") or item.get("text") or ""
    return " ".join(str(text).split())[:limit]


def _format_sources(rag_results: list[dict]) -> list[dict]:
    sources = []
    seen = set()
    for r in rag_results:
        key = (r.get("source", ""), r.get("chapter", ""))
        if key in seen:
            continue
        seen.add(key)
        sources.append({
            "source": r.get("source", ""),
            "chapter": r.get("chapter", ""),
            "chapter_id": r.get("id", ""),
            "topic": r.get("topic", ""),
            "context": r.get("context", ""),
            "excerpt": _source_excerpt(r),
            "score": r.get("score", 0),
            "keywords_matched": r.get("keywords_matched", []),
        })
    return sources


def _build_classical_chart_data(chart_data: dict, strength_detail: dict) -> dict:
    pillars = chart_data.get("four_pillars", {})
    month_pillar = pillars.get("month", {})
    day_pillar = pillars.get("day", {})
    year_pillar = pillars.get("year", {})
    hour_pillar = pillars.get("hour", {})
    month_branch = month_pillar.get("branch", "")

    month_hidden = HIDDEN_STEMS_MAP.get(month_branch, [])
    month_hidden_stems = [
        {"stem": hs.get("stem", ""), "ten_god": hs.get("ten_god", "")}
        for hs in month_hidden
    ]

    day_master = chart_data.get("day_master", "")
    return {
        "ri_zhu": day_master,
        "ri_zhu_wuxing": WUXING_MAP.get(day_master, ""),
        "month_branch": month_branch,
        "month_stem": month_pillar.get("stem", ""),
        "month_hidden_stems": month_hidden_stems,
        "ri_zhu_strength": strength_detail.get("ri_zhu_strength", ""),
        "pattern": strength_detail.get("pattern", ""),
        "yongshen_rule": strength_detail.get("yongshen", {}),
        "year_stem": year_pillar.get("stem", ""),
        "year_branch": year_pillar.get("branch", ""),
        "day_branch": day_pillar.get("branch", ""),
        "hour_stem": hour_pillar.get("stem", ""),
        "hour_branch": hour_pillar.get("branch", ""),
    }


def _append_note(text: str, note: str) -> str:
    text = str(text or "").strip()
    note = str(note or "").strip()
    if not note:
        return text
    if note in text:
        return text
    return f"{text} {note}".strip()


def _derive_ai_yongshen(updated: dict, ai_result: dict) -> str:
    classical_yongshen = (
        updated.get("classical_analysis", {})
        .get("yongshen", {})
    )
    wf = ai_result.get("wangshuai_fix") or {}
    pf = ai_result.get("pattern_fix") or {}
    yf = ai_result.get("yongshen_fix") or {}

    for item in (wf, pf, yf):
        for key in ("ai_yongshen", "suggested_yongshen"):
            value = item.get(key)
            if value:
                return value

    if yf.get("triggered"):
        angle = yf.get("best_angle")
        angle_to_field = {
            "fuyi": "fuyi_yongshen",
            "tiaohou": "tiaohou_yongshen",
            "geju": "geju_yongshen",
        }
        return classical_yongshen.get(angle_to_field.get(angle, ""), "")

    return ""


def apply_ai_fix_to_analysis(updated: dict, ai_result: dict) -> dict:
    """Merge AI correction suggestions into recalculated P0 analysis.

    Reanalysis recomputes the formula-based base. This helper applies the
    non-formula correction layer so the chart summary, classics and forecast
    all read from the same corrected judgment.
    """
    merged = copy.deepcopy(updated)
    if not ai_result:
        return merged

    detail = merged.setdefault("strength_detail", {})
    yongshen = detail.setdefault("yongshen", {})
    classical = merged.setdefault("classical_analysis", {})

    wf = ai_result.get("wangshuai_fix") or {}
    pf = ai_result.get("pattern_fix") or {}
    yf = ai_result.get("yongshen_fix") or {}

    suggested_strength = wf.get("suggested_strength") if wf.get("triggered") else ""
    suggested_pattern = pf.get("suggested_pattern") if pf.get("triggered") else ""
    suggested_yongshen = _derive_ai_yongshen(merged, ai_result)

    if suggested_strength:
        previous = wf.get("current_strength") or detail.get("ri_zhu_strength", "")
        detail["ri_zhu_strength"] = suggested_strength
        wangshuai = classical.setdefault("wangshuai", {})
        wangshuai["conclusion"] = suggested_strength
        if previous and previous != suggested_strength:
            wangshuai["explanation"] = _append_note(
                wangshuai.get("explanation") or wangshuai.get("reasoning") or "",
                f"断前事反馈校正后，旺衰由{previous}调整为{suggested_strength}。",
            )

    if suggested_pattern:
        previous = pf.get("current_pattern") or detail.get("pattern", "")
        detail["pattern"] = suggested_pattern
        pattern = classical.setdefault("pattern", {})
        pattern["pattern_result"] = suggested_pattern
        if previous and previous != suggested_pattern:
            pattern["reasoning"] = _append_note(
                pattern.get("reasoning") or "",
                f"断前事反馈校正后，格局由{previous}调整为{suggested_pattern}。",
            )

    if suggested_yongshen:
        previous = yongshen.get("primary", "")
        yongshen["primary"] = suggested_yongshen
        # 优先使用 AI 输出的喜神/忌神（三者不重复，AI 已验证一致性）
        ai_auxiliary = yf.get("ai_auxiliary") or ai_result.get("ai_auxiliary")
        ai_secondary = yf.get("ai_secondary") or ai_result.get("ai_secondary")
        ai_ji_shen = yf.get("ai_ji_shen") or ai_result.get("ai_ji_shen")
        if ai_secondary and ai_ji_shen:
            # 硬校验：三者不可重复
            if len({suggested_yongshen, ai_secondary, ai_ji_shen}) < 3:
                # AI 输出矛盾，回退到公式
                ai_secondary = ai_ji_shen = ""
            else:
                yongshen["secondary"] = ai_secondary
                yongshen["ji_shen"] = ai_ji_shen
                rederived_ji = ai_ji_shen
                if ai_auxiliary:
                    yongshen["auxiliary"] = ai_auxiliary
        if not ai_secondary or not ai_ji_shen:
            # 回退到公式推导（仅当 AI 未提供喜忌时）
            day_master_wuxing = detail.get("ri_zhu_wuxing", "")
            if not day_master_wuxing:
                day_master_stem = detail.get("ri_zhu", "")
                day_master_wuxing = WUXING_MAP.get(day_master_stem, "")
            rederived = _determine_yongshen_detail(
                {
                    "ri_zhu_strength": detail["ri_zhu_strength"],
                    "pattern": detail["pattern"],
                    "total_score": detail.get("total_score", 0),
                    "cong_ge": detail.get("cong_ge", False),
                    "cong_type": detail.get("cong_type", ""),
                },
                day_master_wuxing,
            )
            yongshen["secondary"] = rederived["secondary"]
            yongshen["ji_shen"] = rederived["ji_shen"]
            rederived_ji = rederived["ji_shen"]
        yongshen_section = classical.setdefault("yongshen", {})
        yongshen_section["final_conclusion"] = suggested_yongshen
        yongshen_section["yongshen_wuxing"] = suggested_yongshen
        yongshen_section["reasoning"] = _append_note(
            yongshen_section.get("reasoning")
            or yongshen_section.get("comprehensive_analysis")
            or "",
            f"断前事反馈显示{yf.get('best_angle_label', '校正后的角度')}更贴合，"
            f"用神由{previous or '原判断'}调整为{suggested_yongshen}，"
            f"喜忌同步重推导为忌{rederived_ji}。",
        )

    # 旺衰或格局被 AI 修正后，用神/喜忌需要基于新旺衰重新推导
    # 因为用神是旺衰的函数（身强→克泄耗，身弱→生扶），不联动就会脱节
    if (suggested_strength or suggested_pattern) and not suggested_yongshen:
        day_master_wuxing = detail.get("ri_zhu_wuxing", "")
        if not day_master_wuxing:
            day_master_stem = detail.get("ri_zhu", "")
            day_master_wuxing = WUXING_MAP.get(day_master_stem, "")
        new_yongshen = _determine_yongshen_detail(
            {
                "ri_zhu_strength": detail["ri_zhu_strength"],
                "pattern": detail["pattern"],
                "total_score": detail.get("total_score", 0),
                "cong_ge": detail.get("cong_ge", False),
                "cong_type": detail.get("cong_type", ""),
            },
            day_master_wuxing,
        )
        detail["yongshen"].update(new_yongshen)
        yongshen_section = classical.setdefault("yongshen", {})
        yongshen_section["final_conclusion"] = new_yongshen.get("primary", "")
        yongshen_section["yongshen_wuxing"] = new_yongshen.get("primary", "")
        yongshen_section["reasoning"] = _append_note(
            yongshen_section.get("reasoning")
            or yongshen_section.get("comprehensive_analysis")
            or "",
            f"旺衰校正为{detail['ri_zhu_strength']}后，用神同步重推导为{new_yongshen.get('primary','')}。",
        )

    return merged


def reanalyze_chart(chart_data: dict) -> dict:
    """用 chart_data 重新计算 strength_detail + classical_analysis + sources。

    从 chart_data 中提取四柱原始数据，重新运行旺衰分析和典籍分析，
    返回修正后的 P0 分析结果。

    Args:
        chart_data: 排盘数据字典（来自 BaziChart.model_dump()），
                    需包含 four_pillars、day_master 等字段

    Returns:
        {
            "strength_detail": dict,    # 旺衰分析详细结果
            "classical_analysis": dict, # 典籍原文分析（模板模式）
            "sources": list[dict],      # 出典列表
        }
    """
    # 1. 从 chart_data 重建四柱原始数据
    pillars = chart_data.get("four_pillars", {})
    four_pillars_raw = {
        pos: {
            "stem": pillars[pos]["stem"],
            "branch": pillars[pos]["branch"],
        }
        for pos in ["year", "month", "day", "hour"]
    }
    day_master = chart_data.get("day_master", "")

    all_hidden = []
    for pos in ["year", "month", "day", "hour"]:
        for hs in pillars[pos].get("hidden_stems", []):
            all_hidden.append({"stem": hs["stem"], "weight": hs.get("weight", 0.5)})

    # 2. 重新计算旺衰
    new_strength = calculate_strength_detail(day_master, four_pillars_raw, all_hidden)

    # 3. RAG 检索相关典籍原文（按阶段加权）
    analysis_chart_data = _build_classical_chart_data(chart_data, new_strength)
    keywords = extract_keywords_from_chart(analysis_chart_data)
    stage_results = retrieve_all_stages(
        keywords,
        ri_zhu_wuxing=analysis_chart_data.get("ri_zhu_wuxing", ""),
        month_branch=analysis_chart_data.get("month_branch", ""),
        per_stage_k=4,
    )
    rag_results = merge_stage_results(stage_results, top_k=10)

    if not rag_results:
        rag_results = retrieve_relevant_texts(new_strength, top_k=10)

    # 4. 典籍分析（模板模式，不调用 AI）
    new_classical = mock_classical_judge(analysis_chart_data, rag_results)

    # 5. 构建出典列表
    new_sources = _format_sources(rag_results)

    return {
        "strength_detail": new_strength,
        "classical_analysis": new_classical,
        "sources": new_sources,
    }
