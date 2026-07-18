"""用神分析模块 - 增强版旺衰判断引擎"""

from models import YongShen
from rules.wuxing import (
    WUXING_MAP, HIDDEN_STEMS_MAP,
    get_sheng, get_ke, get_i_sheng, get_i_ke, get_tonglei,
)


# ============================================================
# 得令判断（月令藏干细化）
# ============================================================

def _calc_deling(day_master_wuxing: str, month_branch: str) -> dict:
    """
    得令判断

    月令藏干分本气、中气、余气，每种与日主的关系不同：
    - 本气与日主同五行：+50（最强得令）
    - 本气是印星：+35
    - 中气与日主同五行：+25
    - 中气是印星：+15
    - 余气与日主同五行：+10
    - 余气是印星：+5
    - 本气是官杀/食伤/财星：+0（失令）
    """
    sheng_wuxing = get_sheng(day_master_wuxing)  # 印星五行
    month_hidden = HIDDEN_STEMS_MAP.get(month_branch, [])

    score = 0
    details = []
    position_names = ["本气", "中气", "余气"]

    # 分数表：{position_index: {同五行: score, 印星: score}}
    score_table = {
        0: {"tong": 50, "yin": 35},   # 本气
        1: {"tong": 25, "yin": 15},   # 中气
        2: {"tong": 10, "yin": 5},    # 余气
    }

    for i, hs in enumerate(month_hidden):
        stem = hs["stem"]
        stem_wx = WUXING_MAP.get(stem, "")
        pos_name = position_names[i] if i < len(position_names) else f"余气{i-1}"

        if stem_wx == day_master_wuxing:
            s = score_table.get(i, {}).get("tong", 0)
            score += s
            details.append(f"{month_branch}月令{pos_name}{stem}({stem_wx})与日主同五行 +{s}")
        elif stem_wx == sheng_wuxing:
            s = score_table.get(i, {}).get("yin", 0)
            score += s
            details.append(f"{month_branch}月令{pos_name}{stem}({stem_wx})为印星 +{s}")
        else:
            details.append(f"{month_branch}月令{pos_name}{stem}({stem_wx})非生助 +0")

    if score >= 50:
        conclusion = "当令（月令本气与日主同五行，最旺）"
    elif score >= 25:
        conclusion = "得令（月令有生助之力）"
    elif score > 0:
        conclusion = "略得令（月令中气/余气有生助）"
    else:
        conclusion = "失令（月令不克泄耗日主则无助力）"

    return {
        "score": score,
        "max_score": 50,
        "detail": details,
        "conclusion": conclusion,
    }


# ============================================================
# 得地判断（四柱地支藏干根）
# ============================================================

def _calc_dedi(day_master_wuxing: str, four_pillars: dict) -> dict:
    """
    得地判断：看四柱所有地支中是否有日主的根

    根分三等：
    - 本气根：地支藏干第一个与日主同五行 → +16分
    - 中气根：地支藏干第二个与日主同五行 → +8分
    - 余气根：地支藏干第三个与日主同五行 → +4分

    遍历年支、月支、日支、时支
    """
    pos_labels = {"year": "年支", "month": "月支", "day": "日支", "hour": "时支"}
    position_scores = {0: 16, 1: 8, 2: 4}
    position_names = ["本气", "中气", "余气"]

    score = 0
    details = []

    for pos in ["year", "month", "day", "hour"]:
        branch = four_pillars[pos]["branch"]
        hidden = HIDDEN_STEMS_MAP.get(branch, [])
        label = pos_labels[pos]
        found_root = False

        for i, hs in enumerate(hidden):
            stem = hs["stem"]
            stem_wx = WUXING_MAP.get(stem, "")
            if stem_wx == day_master_wuxing:
                s = position_scores.get(i, 4)
                score += s
                pos_name = position_names[i] if i < len(position_names) else "余气"
                details.append(
                    f"{label}{branch}藏{pos_name}{stem}({stem_wx})为日主根 +{s}"
                )
                found_root = True

        if not found_root:
            details.append(f"{label}{branch}无日主根 +0")

    if score >= 40:
        conclusion = "得地有力（多地支有根）"
    elif score >= 24:
        conclusion = "得地中等（部分地支有根）"
    elif score >= 8:
        conclusion = "得地较弱（仅个别地支有根）"
    else:
        conclusion = "不得地（地支无根或根极弱）"

    return {
        "score": score,
        "max_score": 64,  # 4柱 × 16分
        "detail": details,
        "conclusion": conclusion,
    }


# ============================================================
# 得生判断（印星生扶）
# ============================================================

def _calc_desheng(day_master_wuxing: str, four_pillars: dict) -> dict:
    """
    得生判断：看印星是否生扶日主

    印星 = 生我者
    - 天干透出印星：+12/个
    - 地支藏干印星（本气）：+10/个
    - 地支藏干印星（中气）：+5/个
    - 地支藏干印星（余气）：+2/个
    """
    sheng_wuxing = get_sheng(day_master_wuxing)  # 印星五行
    pos_labels = {"year": "年", "month": "月", "day": "日", "hour": "时"}
    position_scores = {0: 10, 1: 5, 2: 2}
    position_names = ["本气", "中气", "余气"]

    score = 0
    details = []

    # 天干透出印星
    for pos in ["year", "month", "day", "hour"]:
        stem = four_pillars[pos]["stem"]
        stem_wx = WUXING_MAP.get(stem, "")
        if stem_wx == sheng_wuxing:
            score += 12
            details.append(f"{pos_labels[pos]}干{stem}({stem_wx})为印星 +12")

    # 地支藏干印星
    for pos in ["year", "month", "day", "hour"]:
        branch = four_pillars[pos]["branch"]
        hidden = HIDDEN_STEMS_MAP.get(branch, [])
        for i, hs in enumerate(hidden):
            stem = hs["stem"]
            stem_wx = WUXING_MAP.get(stem, "")
            if stem_wx == sheng_wuxing:
                s = position_scores.get(i, 2)
                score += s
                pos_name = position_names[i] if i < len(position_names) else "余气"
                details.append(
                    f"{pos_labels[pos]}支{branch}藏{pos_name}{stem}({stem_wx})为印星 +{s}"
                )

    if score >= 30:
        conclusion = "得生有力（多处印星生扶）"
    elif score >= 15:
        conclusion = "得生中等（有印星生扶）"
    elif score > 0:
        conclusion = "得生较弱（印星力量有限）"
    else:
        conclusion = "不得生（无印星生扶）"

    return {
        "score": score,
        "detail": details,
        "conclusion": conclusion,
    }


# ============================================================
# 得助判断（比劫帮身）
# ============================================================

def _calc_dezhu(day_master_wuxing: str, four_pillars: dict) -> dict:
    """
    得助判断：看比劫是否帮身

    比劫 = 同我者
    - 天干透出比劫：+10/个
    - 地支藏干比劫（本气）：+8/个
    - 地支藏干比劫（中气）：+4/个
    - 地支藏干比劫（余气）：+2/个
    """
    tonglei_wuxing = get_tonglei(day_master_wuxing)  # 比劫五行（同日主）
    pos_labels = {"year": "年", "month": "月", "day": "日", "hour": "时"}
    position_scores = {0: 8, 1: 4, 2: 2}
    position_names = ["本气", "中气", "余气"]

    score = 0
    details = []

    # 天干透出比劫（跳过日干自身，日主不算比劫）
    for pos in ["year", "month", "hour"]:
        stem = four_pillars[pos]["stem"]
        stem_wx = WUXING_MAP.get(stem, "")
        if stem_wx == tonglei_wuxing:
            score += 10
            details.append(f"{pos_labels[pos]}干{stem}({stem_wx})为比劫 +10")

    # 地支藏干比劫
    for pos in ["year", "month", "day", "hour"]:
        branch = four_pillars[pos]["branch"]
        hidden = HIDDEN_STEMS_MAP.get(branch, [])
        for i, hs in enumerate(hidden):
            stem = hs["stem"]
            stem_wx = WUXING_MAP.get(stem, "")
            if stem_wx == tonglei_wuxing:
                s = position_scores.get(i, 2)
                score += s
                pos_name = position_names[i] if i < len(position_names) else "余气"
                details.append(
                    f"{pos_labels[pos]}支{branch}藏{pos_name}{stem}({stem_wx})为比劫 +{s}"
                )

    if score >= 30:
        conclusion = "得助有力（比劫众多帮身）"
    elif score >= 15:
        conclusion = "得助中等（有比劫帮身）"
    elif score > 0:
        conclusion = "得助较弱（比劫力量有限）"
    else:
        conclusion = "不得助（无比劫帮身）"

    return {
        "score": score,
        "detail": details,
        "conclusion": conclusion,
    }


# ============================================================
# 克泄耗判断（反向力量）
# ============================================================

def _calc_ke_xie_hao(day_master_wuxing: str, four_pillars: dict) -> dict:
    """
    克泄耗判断：计算反向力量

    - 官杀（克我）：天干-10/个，地支藏干本气-8/个，中气-4/个，余气-2/个
    - 食伤（我生）：天干-8/个，地支藏干本气-6/个，中气-3/个，余气-1/个
    - 财星（我克）：天干-8/个，地支藏干本气-6/个，中气-3/个，余气-1/个
    """
    ke_wuxing = get_ke(day_master_wuxing)        # 官杀（克我）
    i_sheng_wuxing = get_i_sheng(day_master_wuxing)  # 食伤（我生）
    i_ke_wuxing = get_i_ke(day_master_wuxing)    # 财星（我克）

    pos_labels = {"year": "年", "month": "月", "day": "日", "hour": "时"}
    position_names = ["本气", "中气", "余气"]

    # 官杀扣分表
    guan_sha_scores = {0: 8, 1: 4, 2: 2}
    # 食伤/财星扣分表
    shi_shang_scores = {0: 6, 1: 3, 2: 1}

    total_penalty = 0
    details = {"guan_sha": [], "shi_shang": [], "cai_xing": []}

    for pos in ["year", "month", "day", "hour"]:
        stem = four_pillars[pos]["stem"]
        stem_wx = WUXING_MAP.get(stem, "")
        branch = four_pillars[pos]["branch"]
        hidden = HIDDEN_STEMS_MAP.get(branch, [])

        # 天干
        if stem_wx == ke_wuxing:
            total_penalty += 10
            details["guan_sha"].append(f"{pos_labels[pos]}干{stem}({stem_wx})为官杀 -10")
        elif stem_wx == i_sheng_wuxing:
            total_penalty += 8
            details["shi_shang"].append(f"{pos_labels[pos]}干{stem}({stem_wx})为食伤 -8")
        elif stem_wx == i_ke_wuxing:
            total_penalty += 8
            details["cai_xing"].append(f"{pos_labels[pos]}干{stem}({stem_wx})为财星 -8")

        # 地支藏干
        for i, hs in enumerate(hidden):
            hs_stem = hs["stem"]
            hs_wx = WUXING_MAP.get(hs_stem, "")
            pos_name = position_names[i] if i < len(position_names) else "余气"

            if hs_wx == ke_wuxing:
                s = guan_sha_scores.get(i, 2)
                total_penalty += s
                details["guan_sha"].append(
                    f"{pos_labels[pos]}支{branch}藏{pos_name}{hs_stem}({hs_wx})为官杀 -{s}"
                )
            elif hs_wx == i_sheng_wuxing:
                s = shi_shang_scores.get(i, 1)
                total_penalty += s
                details["shi_shang"].append(
                    f"{pos_labels[pos]}支{branch}藏{pos_name}{hs_stem}({hs_wx})为食伤 -{s}"
                )
            elif hs_wx == i_ke_wuxing:
                s = shi_shang_scores.get(i, 1)
                total_penalty += s
                details["cai_xing"].append(
                    f"{pos_labels[pos]}支{branch}藏{pos_name}{hs_stem}({hs_wx})为财星 -{s}"
                )

    all_details = details["guan_sha"] + details["shi_shang"] + details["cai_xing"]

    if total_penalty == 0:
        conclusion = "无克泄耗（日主不受克制）"
    elif total_penalty <= 15:
        conclusion = "克泄耗较轻"
    elif total_penalty <= 30:
        conclusion = "克泄耗中等"
    else:
        conclusion = "克泄耗较重（日主受克泄耗明显）"

    return {
        "score": -total_penalty,
        "detail": all_details,
        "detail_by_type": details,
        "conclusion": conclusion,
    }


# ============================================================
# 综合判断 + 从格检测
# ============================================================

def _judge_strength(
    total_score: int,
    four_pillars: dict,
    day_master_wuxing: str,
) -> dict:
    """
    综合判断日主强弱

    ≥ 80：太旺（检查是否从强格）
    60-80：偏强
    40-60：中和
    20-40：偏弱
    < 20：太弱（检查是否从弱格）

    从格判断：
    - 从弱格：总分<15 且四柱天干无比劫印星透出
    - 从强格：总分>85 且四柱天干无官杀财星透出
    """
    sheng_wuxing = get_sheng(day_master_wuxing)
    tonglei_wuxing = get_tonglei(day_master_wuxing)
    ke_wuxing = get_ke(day_master_wuxing)
    i_ke_wuxing = get_i_ke(day_master_wuxing)

    # 四柱天干（排除日干自身，日主不算比劫）
    other_stems = [four_pillars[p]["stem"] for p in ["year", "month", "hour"]]
    other_wuxings = [WUXING_MAP.get(s, "") for s in other_stems]

    has_bi_yin = any(
        wx in (day_master_wuxing, sheng_wuxing) for wx in other_wuxings
    )
    has_guan_cai = any(
        wx in (ke_wuxing, i_ke_wuxing) for wx in other_wuxings
    )

    # 基本强弱判断
    if total_score >= 80:
        strength = "太旺"
    elif total_score >= 60:
        strength = "偏强"
    elif total_score >= 40:
        strength = "中和"
    elif total_score >= 20:
        strength = "偏弱"
    else:
        strength = "太弱"

    # 从格检测
    cong_ge = False
    cong_type = ""

    if total_score < 15 and not has_bi_yin:
        cong_ge = True
        cong_type = "从弱格"
    elif total_score > 85 and not has_guan_cai:
        cong_ge = True
        cong_type = "从强格"

    if cong_ge:
        pattern = cong_type
        ri_zhu_strength = "极弱" if "弱" in cong_type else "极强"
    else:
        pattern = f"正格-身{'强' if total_score >= 60 else '弱' if total_score < 40 else '中和'}"
        ri_zhu_strength = strength

    return {
        "total_score": total_score,
        "ri_zhu_strength": ri_zhu_strength,
        "pattern": pattern,
        "cong_ge": cong_ge,
        "cong_type": cong_type,
    }


# ============================================================
# 用神判断（增强版）
# ============================================================

def _determine_yongshen_detail(strength_result: dict, day_master_wuxing: str) -> dict:
    """根据旺衰判断结果确定用神

    正格身强：用神=官杀，喜神=财星，忌神=印星
    正格身弱：用神=印星，喜神=比劫，忌神=官杀
    从弱格：用神=官杀/食伤/财星（顺其气势）
    从强格：用神=印星/比劫（顺其气势）

    注意：用 ri_zhu_strength / pattern 判断强弱，不用 total_score。
    因为 AI 校正后旺衰标签会被修改，但 total_score 不会被更新，
    继续用 total_score 会导致用神与校正后的旺衰脱节。
    """
    ri_zhu_strength = strength_result.get("ri_zhu_strength", "")
    pattern = strength_result.get("pattern", "")
    is_strong = any(kw in (ri_zhu_strength + pattern) for kw in ("强", "旺"))
    is_weak = any(kw in (ri_zhu_strength + pattern) for kw in ("弱",))

    if strength_result["cong_ge"]:
        if "弱" in strength_result["cong_type"]:
            primary = get_ke(day_master_wuxing)
            secondary = get_i_sheng(day_master_wuxing)
            ji_shen = get_sheng(day_master_wuxing)
        else:
            primary = get_sheng(day_master_wuxing)
            secondary = get_tonglei(day_master_wuxing)
            ji_shen = get_ke(day_master_wuxing)
    elif is_strong:
        primary = get_ke(day_master_wuxing)
        secondary = get_i_ke(day_master_wuxing)
        ji_shen = get_sheng(day_master_wuxing)
    elif is_weak:
        primary = get_sheng(day_master_wuxing)
        secondary = get_tonglei(day_master_wuxing)
        ji_shen = get_ke(day_master_wuxing)
    else:
        # 中和或无法判断：偏弱处理
        primary = get_sheng(day_master_wuxing)
        secondary = get_tonglei(day_master_wuxing)
        ji_shen = get_ke(day_master_wuxing)

    return {
        "primary": primary,
        "secondary": secondary,
        "ji_shen": ji_shen,
    }


# ============================================================
# 主函数：完整旺衰判断
# ============================================================

def calculate_strength_detail(
    day_master_stem: str,
    four_pillars: dict,
    hidden_stems_list: list,
) -> dict:
    """
    完整的日主旺衰判断，输出每一步的详细数据

    Args:
        day_master_stem: 日主天干（如 "己"）
        four_pillars: 四柱数据 {"year": {"stem": "庚", "branch": "午"}, ...}
        hidden_stems_list: 藏干列表（向后兼容，本函数主要使用 HIDDEN_STEMS_MAP）

    Returns:
        {
            "ri_zhu": "己",
            "ri_zhu_wuxing": "土",
            "deling": { 得令详情 },
            "dedi": { 得地详情 },
            "desheng": { 得生详情 },
            "dezhu": { 得助详情 },
            "ke_xie_hao": { 克泄耗详情 },
            "total_score": 35,
            "ri_zhu_strength": "偏弱",
            "pattern": "正格-身弱",
            "cong_ge": false,
            "yongshen": { "primary": "火", "secondary": "土", "ji_shen": "木" }
        }
    """
    day_master_wuxing = WUXING_MAP.get(day_master_stem, "")
    month_branch = four_pillars["month"]["branch"]

    # 1. 得令
    deling = _calc_deling(day_master_wuxing, month_branch)

    # 2. 得地
    dedi = _calc_dedi(day_master_wuxing, four_pillars)

    # 3. 得生
    desheng = _calc_desheng(day_master_wuxing, four_pillars)

    # 4. 得助
    dezhu = _calc_dezhu(day_master_wuxing, four_pillars)

    # 5. 克泄耗
    ke_xie_hao = _calc_ke_xie_hao(day_master_wuxing, four_pillars)

    # 6. 综合得分
    total_score = (
        deling["score"]
        + dedi["score"]
        + desheng["score"]
        + dezhu["score"]
        + ke_xie_hao["score"]
    )

    # 7. 综合判断
    strength_result = _judge_strength(total_score, four_pillars, day_master_wuxing)

    # 8. 用神判断
    yongshen = _determine_yongshen_detail(strength_result, day_master_wuxing)

    return {
        "ri_zhu": day_master_stem,
        "ri_zhu_wuxing": day_master_wuxing,
        "deling": deling,
        "dedi": dedi,
        "desheng": desheng,
        "dezhu": dezhu,
        "ke_xie_hao": ke_xie_hao,
        "total_score": total_score,
        "ri_zhu_strength": strength_result["ri_zhu_strength"],
        "pattern": strength_result["pattern"],
        "cong_ge": strength_result["cong_ge"],
        "yongshen": yongshen,
    }


# ============================================================
# 向后兼容：原 determine_yongshen 接口
# ============================================================

def determine_yongshen(
    day_master_stem: str,
    four_pillars: dict,
    hidden_stems_list: list,
    wuxing_score: dict,
) -> YongShen:
    """
    用神判断（向后兼容接口）

    内部调用 calculate_strength_detail，返回 YongShen 模型。
    """
    detail = calculate_strength_detail(
        day_master_stem=day_master_stem,
        four_pillars=four_pillars,
        hidden_stems_list=hidden_stems_list,
    )

    return YongShen(
        primary=detail["yongshen"]["primary"],
        secondary=detail["yongshen"]["secondary"],
        ji_shen=detail["yongshen"]["ji_shen"],
        pattern=detail["pattern"],
        ri_zhu_strength=detail["ri_zhu_strength"],
    )


# ============================================================
# 新增：典籍AI判断路径（不改变原有逻辑）
# ============================================================

async def calculate_strength_with_classics(
    day_master_stem: str,
    four_pillars: dict,
    hidden_stems_list: list,
    rag_results: list[dict] | None = None,
) -> dict:
    """
    增强版旺衰判断：规则引擎 + 典籍AI判断

    先运行规则引擎计算，再调用典籍AI进行原文验证。
    返回合并后的结果，包含规则引擎数据和AI/模板典籍判断。

    Args:
        day_master_stem: 日主天干
        four_pillars: 四柱数据
        hidden_stems_list: 藏干列表
        rag_results: RAG检索到的原文段落（可选，如未提供则不调用AI）

    Returns:
        {
            "rule_engine": { ...calculate_strength_detail 的返回 ... },
            "classical_judgment": { ...AI/模板判断结果 ... }
        }
    """
    from rules.wuxing import WUXING_MAP, HIDDEN_STEMS_MAP

    # 1. 规则引擎计算
    detail = calculate_strength_detail(
        day_master_stem=day_master_stem,
        four_pillars=four_pillars,
        hidden_stems_list=hidden_stems_list,
    )

    # 2. 构建 chart_data 供典籍判断
    month_branch = four_pillars["month"]["branch"]
    month_stem = four_pillars["month"]["stem"]
    month_hidden = HIDDEN_STEMS_MAP.get(month_branch, [])
    month_hidden_stems = [
        {"stem": hs.get("stem", ""), "ten_god": hs.get("ten_god", "")}
        for hs in month_hidden
    ]

    chart_data = {
        "ri_zhu": day_master_stem,
        "ri_zhu_wuxing": WUXING_MAP.get(day_master_stem, ""),
        "month_branch": month_branch,
        "month_stem": month_stem,
        "month_hidden_stems": month_hidden_stems,
        "ri_zhu_strength": detail["ri_zhu_strength"],
        "pattern": detail["pattern"],
        "yongshen_rule": detail["yongshen"],
    }

    # 3. 典籍判断（如果有RAG结果）
    classical_judgment = None
    if rag_results:
        import os
        if os.getenv("DEEPSEEK_API_KEY"):
            from services.classical_judge import judge_from_classics
            classical_judgment = await judge_from_classics(chart_data, rag_results)
        else:
            from services.classical_judge import mock_classical_judge
            classical_judgment = mock_classical_judge(chart_data, rag_results)

    return {
        "rule_engine": detail,
        "classical_judgment": classical_judgment,
    }
