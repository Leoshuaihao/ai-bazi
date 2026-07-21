"""事前不确定参数预标注器

五维标注：时辰风险(shichen)、用神争议度(yongshen)、旺衰模糊度(wangshuai)、
格局多解性(pattern)、从格真假(congge)。

理论依据：
- 《滴天髓·真假》"真假参差难辨论，不明不暗受迍邅"
- 《滴天髓·旺衰》"木太旺者似金，喜火之炼也；木旺极者似火，喜水之克也"
- 《子平真诠·论用神成败得失》"有先败后成者……有先成后败者……"
- 《滴天髓·从化》"真从之象有几人，假从亦可发其身"
- 《滴天髓·生时》"时之不的当者，十有四五"

纯规则引擎，含 Mock 回退。
"""

from dataclasses import dataclass, field
from typing import Optional


# ============================================================
# 数据模型
# ============================================================

@dataclass
class UncertaintyItem:
    """单维度不确定参数标注"""
    dimension: str          # "shichen"|"yongshen"|"wangshuai"|"pattern"|"congge"
    risk_score: float       # 0.0-1.0, 越高越不确定
    label: str              # "低风险"|"中风险"|"高风险"
    detail: str             # 文字说明


@dataclass
class UncertaintyReport:
    """五维不确定参数预标注报告"""
    items: list[UncertaintyItem]
    overall_risk: float     # 综合风险 0-1
    suggested_questions: list[str] = field(default_factory=list)


# ============================================================
# 辅助常量
# ============================================================

# 节气的平均日期（月/日），用于粗略估计节气交接距离
JIEQI_APPROX = {
    1: [(6, "小寒"), (20, "大寒")],
    2: [(4, "立春"), (19, "雨水")],
    3: [(6, "惊蛰"), (21, "春分")],
    4: [(5, "清明"), (20, "谷雨")],
    5: [(6, "立夏"), (21, "小满")],
    6: [(6, "芒种"), (21, "夏至")],
    7: [(7, "小暑"), (23, "大暑")],
    8: [(8, "立秋"), (23, "处暑")],
    9: [(8, "白露"), (23, "秋分")],
    10: [(8, "寒露"), (24, "霜降")],
    11: [(8, "立冬"), (22, "小雪")],
    12: [(7, "大雪"), (22, "冬至")],
}


# ============================================================
# 维度 1: 时辰风险 (shichen)
# ============================================================

def _label_shichen_risk(
    hour: int,
    minute: int,
    birth_longitude: float = 120.0,
    month: int = 1,
    day: int = 1,
    memory_uncertain: bool = False,
) -> UncertaintyItem:
    """标注时辰风险。

    量化标准：
    - 子时(23:00-01:00) +0.3
    - 经度偏差>30min +0.25
    - 节气交接±1h +0.25
    - 记忆模糊标注 +0.2
    上限 1.0

    Args:
        hour: 出生小时 (0-23)
        minute: 出生分钟 (0-59)
        birth_longitude: 出生地经度 (默认北京 120°)
        month: 出生月份
        day: 出生日
        memory_uncertain: 命主是否对出生时间记忆模糊

    Returns:
        UncertaintyItem
    """
    risk = 0.0
    details = []

    # 1.1 子时边界
    if hour == 23 or hour == 0:
        risk += 0.3
        details.append("子时出生，存在子初/子正边界歧义")

    # 1.2 经度偏差 > 30 分钟（即经度差 > 7.5°）
    lon_offset = abs(120.0 - birth_longitude) * 4  # 分钟
    if lon_offset > 30:
        risk += 0.25
        details.append(
            f"出生地经度偏差{lon_offset:.0f}分钟（东经{birth_longitude}°），"
            f"真太阳时校正可能改变时辰"
        )

    # 1.3 节气交接 ±1 小时内
    jieqi_hours = _get_jieqi_distance(month, day, hour)
    if jieqi_hours is not None and jieqi_hours <= 1.0:
        risk += 0.25
        details.append(
            f"出生时间距节气交接仅{int(jieqi_hours * 60)}分钟，月柱可能错排"
        )

    # 1.4 记忆模糊标注
    if memory_uncertain:
        risk += 0.2
        details.append("命主对出生时间记忆模糊")

    return UncertaintyItem(
        dimension="shichen",
        risk_score=min(risk, 1.0),
        label="高风险" if risk > 0.5 else ("中风险" if risk > 0.2 else "低风险"),
        detail="；".join(details) if details else "时辰信息明确，无显著风险",
    )


def _get_jieqi_distance(month: int, day: int, hour: int) -> Optional[float]:
    """计算出生时间与最近节气的距离（小时）。

    使用近似节气日期，返回距最近节气的绝对小时数。
    若距离 > 24h，返回 None（不构成风险）。
    """
    if month not in JIEQI_APPROX:
        return None

    # 计算出生日期的绝对小时偏移（以月初为基准）
    birth_hours = (day - 1) * 24 + hour

    min_distance = float("inf")
    for jieqi_day, _ in JIEQI_APPROX[month]:
        jieqi_hours = (jieqi_day - 1) * 24  # 节气在当天0点
        distance = abs(birth_hours - jieqi_hours)
        if distance < min_distance:
            min_distance = distance

    # 也检查前一个月的最后一个节气和后一个月的第一个节气
    # 上月最后一个节气
    prev_month = month - 1 if month > 1 else 12
    if prev_month in JIEQI_APPROX:
        last_jieqi = JIEQI_APPROX[prev_month][-1]
        # 上月节气在月末，计算跨月距离
        jieqi_day = last_jieqi[0]
        # 假设上月有30天
        prev_month_days = 30
        prev_jieqi_hours = (prev_month_days - 1) * 24 - (jieqi_day - 1) * 24
        distance = abs(birth_hours + prev_jieqi_hours)
        if distance < min_distance:
            min_distance = distance

    # 下个月第一个节气
    next_month = month + 1 if month < 12 else 1
    if next_month in JIEQI_APPROX:
        first_jieqi = JIEQI_APPROX[next_month][0]
        jieqi_day = first_jieqi[0]
        # 当前月天数
        cur_month_days = 30
        next_jieqi_hours = (cur_month_days - day) * 24 + (jieqi_day - 1) * 24
        distance = abs(next_jieqi_hours - hour)
        if distance < min_distance:
            min_distance = distance

    # 距离 > 24 小时则不构成风险
    if min_distance > 24:
        return None
    return min_distance


# ============================================================
# 维度 2: 用神争议度 (yongshen)
# ============================================================

def _label_yongshen_risk(
    yongshen_data: dict,
    chart_data: dict,
) -> UncertaintyItem:
    """标注用神争议度。

    量化标准：
    - 月令多透(2+干透出) +0.4
    - 三合局边界 +0.3
    - 用神被伤但救应 +0.3
    上限 1.0

    Args:
        yongshen_data: 用神分析数据, e.g. {"primary": "火", "ji_shen": "水", "pattern": "正官格"}
        chart_data: 排盘数据 dict

    Returns:
        UncertaintyItem
    """
    risk = 0.0
    details = []

    # 2.1 月令多透检查
    month_pillar = chart_data.get("four_pillars", {}).get("month", {})
    hidden_stems = month_pillar.get("hidden_stems", [])
    if len(hidden_stems) >= 2:
        # 检查是否有2+干透出
        touched_count = 0
        touched_details = []
        for hs in hidden_stems:
            stem = hs.get("stem", "") if isinstance(hs, dict) else hs
            weight = hs.get("weight", 0.0) if isinstance(hs, dict) else 0.3
            # 检查天干是否透出此藏干
            for pos in ["year", "month", "day", "hour"]:
                pillar = chart_data.get("four_pillars", {}).get(pos, {})
                if pillar.get("stem", "") == stem:
                    touched_count += 1
                    touched_details.append(f"{pos}={stem}")
                    break

        if touched_count >= 2:
            risk += 0.4
            details.append(
                f"月令藏干多透（{','.join(touched_details)}），可能产生多种用神"
            )

    # 2.2 三合局边界
    month_branch = month_pillar.get("branch", "")
    day_pillar = chart_data.get("four_pillars", {}).get("day", {})
    day_branch = day_pillar.get("branch", "")

    # 半合局检查：月支与日支是否构成半合
    _HALF_HE_MAP = {
        "申": {"子": "申子半合水", "辰": "申辰半合水"},
        "子": {"申": "申子半合水", "辰": "子辰半合水"},
        "辰": {"申": "申辰半合水", "子": "子辰半合水"},
        "亥": {"卯": "亥卯半合木", "未": "亥未半合木"},
        "卯": {"亥": "亥卯半合木", "未": "卯未半合木"},
        "未": {"亥": "亥未半合木", "卯": "卯未半合木"},
        "寅": {"午": "寅午半合火", "戌": "寅戌半合火"},
        "午": {"寅": "寅午半合火", "戌": "午戌半合火"},
        "戌": {"寅": "寅戌半合火", "午": "午戌半合火"},
        "巳": {"酉": "巳酉半合金", "丑": "巳丑半合金"},
        "酉": {"巳": "巳酉半合金", "丑": "酉丑半合金"},
        "丑": {"巳": "巳丑半合金", "酉": "酉丑半合金"},
    }

    if month_branch in _HALF_HE_MAP:
        if day_branch in _HALF_HE_MAP[month_branch]:
            risk += 0.3
            details.append(
                f"月支{month_branch}与日支{day_branch}构成半合局"
                f"（{_HALF_HE_MAP[month_branch][day_branch]}），若补齐则用神可能改变"
            )

    # 2.3 用神被伤但救应
    primary = yongshen_data.get("primary", "")
    ji_shen = yongshen_data.get("ji_shen", "")

    # 检查用神在四柱是否透干
    # WUXING_MAP: stem -> wuxing
    from rules.wuxing import WUXING_MAP
    ys_wx = primary

    # 用神透干检查
    ys_touches = False
    ji_touches = False
    for pos in ["year", "month", "day", "hour"]:
        pillar = chart_data.get("four_pillars", {}).get(pos, {})
        stem = pillar.get("stem", "")
        if WUXING_MAP.get(stem, "") == ys_wx:
            ys_touches = True
        if WUXING_MAP.get(stem, "") == ji_shen:
            ji_touches = True

    # 用神被伤但救应检查：用神忌神同时透出
    if ys_touches and ji_touches:
        risk += 0.3
        details.append(
            f"用神{primary}与忌神{ji_shen}同时透于天干，用神被伤但有救应可能"
        )

    return UncertaintyItem(
        dimension="yongshen",
        risk_score=min(risk, 1.0),
        label="高风险" if risk > 0.5 else ("中风险" if risk > 0.2 else "低风险"),
        detail="；".join(details) if details else "用神判定无明显争议",
    )


# ============================================================
# 维度 3: 旺衰模糊度 (wangshuai)
# ============================================================

def _label_wangshuai_risk(strength_detail: dict) -> UncertaintyItem:
    """标注旺衰模糊度。

    量化标准：
    - 得分在[35,45]∪[55,65] → 中风险 0.5
    - 得分在(45,55) → 高风险 0.8
    - 其余低风险
    上限 1.0

    Args:
        strength_detail: 旺衰分析详情，含 total_score, deling, dedi, desheng, dezhu

    Returns:
        UncertaintyItem
    """
    total = strength_detail.get("total_score", 50)
    risk = 0.0
    details = []

    # 旺衰五等边界：
    # 极旺(>85) → 身旺(65-85) → 中和(35-65) → 身弱(15-35) → 极弱(<15)

    if 35 <= total <= 45:
        risk = 0.5
        details.append(
            f"得分{total}处于身弱与中和边界[35,45]，取用方向可能有歧义"
        )
    elif 55 <= total <= 65:
        risk = 0.5
        details.append(
            f"得分{total}处于身旺与中和边界[55,65]，取用方向可能有歧义"
        )
    elif 45 < total < 55:
        risk = 0.8
        details.append(
            f"得分{total}处于中和核心区域(45,55)，旺衰难辨，高风险"
        )
    else:
        risk = 0.1
        details.append(f"得分{total}，旺衰判定明确")

    return UncertaintyItem(
        dimension="wangshuai",
        risk_score=min(risk, 1.0),
        label="高风险" if risk > 0.5 else ("中风险" if risk > 0.2 else "低风险"),
        detail="；".join(details),
    )


# ============================================================
# 维度 4: 格局多解性 (pattern)
# ============================================================

def _label_pattern_risk(
    pattern: str,
    strength_detail: dict,
    chart_data: dict,
) -> UncertaintyItem:
    """标注格局多解性。

    量化标准：
    - 从格条件接近满足 +0.5
    - 化气格条件部分满足(3-4/5) +0.4
    - 调候冲突 +0.3
    上限 1.0

    Args:
        pattern: 格局名称
        strength_detail: 旺衰详情
        chart_data: 排盘数据

    Returns:
        UncertaintyItem
    """
    risk = 0.0
    details = []
    total = strength_detail.get("total_score", 50)

    # 4.1 从格条件接近满足
    if 70 <= total <= 85 and "从" not in pattern:
        risk += 0.5
        details.append(
            f"得分{total}处于正格身旺与从强格边界，从格条件接近满足"
        )
    elif 15 <= total <= 30 and "从" not in pattern:
        risk += 0.5
        details.append(
            f"得分{total}处于正格身弱与从弱格边界，从格条件接近满足"
        )

    # 4.2 化气格条件部分满足检查
    huaqi_score = _check_huaqi_conditions(chart_data)
    if 3 <= huaqi_score <= 4:
        risk += 0.4
        details.append(
            f"化气格条件部分满足({huaqi_score}/5)，存在化气格可能性"
        )
    elif huaqi_score == 5:
        risk += 0.3
        details.append("化气格条件全部满足(5/5)，需确认是否应按化气格论")

    # 4.3 调候冲突
    # 简单检查：月令是否克日主
    from rules.wuxing import WUXING_MAP, get_ke
    day_master = chart_data.get("day_master", "")
    dm_wx = WUXING_MAP.get(day_master, "")

    # 检查月令是否克日主
    month_pillar = chart_data.get("four_pillars", {}).get("month", {})
    month_branch = month_pillar.get("branch", "")
    # 地支五行映射（简化）
    ZHI_WUXING = {
        "子": "水", "丑": "土", "寅": "木", "卯": "木",
        "辰": "土", "巳": "火", "午": "火", "未": "土",
        "申": "金", "酉": "金", "戌": "土", "亥": "水",
    }
    month_wx = ZHI_WUXING.get(month_branch, "")
    if month_wx and dm_wx:
        # get_ke(dm_wx) 返回克日主的五行
        if get_ke(dm_wx) == month_wx:
            risk += 0.3
            details.append(
                f"月令{month_branch}({month_wx})克日主({dm_wx})，"
                f"调候需求与格局用神可能有冲突"
            )

    return UncertaintyItem(
        dimension="pattern",
        risk_score=min(risk, 1.0),
        label="高风险" if risk > 0.5 else ("中风险" if risk > 0.2 else "低风险"),
        detail="；".join(details) if details else "格局判定无多解性",
    )


def _check_huaqi_conditions(chart_data: dict) -> int:
    """检查化气格五要素满足度。

    返回满足条件数 0-5：
    1. 天干五合
    2. 化神五行
    3. 化神当令
    4. 化神透干
    5. 无克破
    """
    score = 0

    # 天干五合对
    HUAHE_PAIRS = {
        ("甲", "己"): "土",
        ("乙", "庚"): "金",
        ("丙", "辛"): "水",
        ("丁", "壬"): "木",
        ("戊", "癸"): "火",
    }

    # 地支五行
    ZHI_WUXING = {
        "子": "水", "丑": "土", "寅": "木", "卯": "木",
        "辰": "土", "巳": "火", "午": "火", "未": "土",
        "申": "金", "酉": "金", "戌": "土", "亥": "水",
    }

    day_stem = chart_data.get("day_master", "")
    month_pillar = chart_data.get("four_pillars", {}).get("month", {})
    month_stem = month_pillar.get("stem", "")

    # 1. 天干五合：日干与月干是否合
    hua_wx = None
    for (a, b), wx in HUAHE_PAIRS.items():
        if (day_stem == a and month_stem == b) or (day_stem == b and month_stem == a):
            hua_wx = wx
            score += 1  # 合化天干条件满足
            break

    if hua_wx:
        # 2. 化神五行（同上）
        score += 1

        # 3. 化神当令
        month_branch = month_pillar.get("branch", "")
        if ZHI_WUXING.get(month_branch, "") == hua_wx:
            score += 1

        # 4. 化神透干
        for pos in ["year", "month", "day", "hour"]:
            pillar = chart_data.get("four_pillars", {}).get(pos, {})
            stem_wx = _stem_to_wuxing(pillar.get("stem", ""))
            if stem_wx == hua_wx:
                score += 1
                break

        # 5. 无克破：化神不被克
        from rules.wuxing import get_ke
        ke_hua = get_ke(hua_wx)
        has_ke = False
        for pos in ["year", "month", "day", "hour"]:
            pillar = chart_data.get("four_pillars", {}).get(pos, {})
            stem_wx = _stem_to_wuxing(pillar.get("stem", ""))
            if stem_wx == ke_hua:
                has_ke = True
                break
        if not has_ke:
            score += 1

    return score


def _stem_to_wuxing(stem: str) -> str:
    """天干转五行"""
    from rules.wuxing import WUXING_MAP
    return WUXING_MAP.get(stem, "")


# ============================================================
# 维度 5: 从格真假 (congge)
# ============================================================

def _label_congge_risk(
    pattern: str,
    strength_detail: dict,
    chart_data: dict,
) -> UncertaintyItem:
    """标注从格真假。

    量化标准：
    - 日主有微根(仅余气通根) +0.5
    - 生扶力量<20% +0.3
    上限 1.0

    Args:
        pattern: 格局名称
        strength_detail: 旺衰详情
        chart_data: 排盘数据

    Returns:
        UncertaintyItem
    """
    # 只有当前格局与从格相关时才计算
    if "从" not in pattern and "专旺" not in pattern:
        return UncertaintyItem(
            dimension="congge",
            risk_score=0.0,
            label="低风险",
            detail="非从格格局，不适用",
        )

    risk = 0.0
    details = []

    from rules.wuxing import WUXING_MAP
    day_master = chart_data.get("day_master", "")
    dm_wx = WUXING_MAP.get(day_master, "")

    # 检查日主根气
    max_root_weight = 0.0
    has_benqi_root = False
    four_pillars = chart_data.get("four_pillars", {})

    for pos in ["year", "month", "day", "hour"]:
        pillar = four_pillars.get(pos, {})
        hidden_stems = pillar.get("hidden_stems", [])
        for hs in hidden_stems:
            stem = hs.get("stem", "") if isinstance(hs, dict) else hs
            weight = hs.get("weight", 0.0) if isinstance(hs, dict) else 0.3
            if WUXING_MAP.get(stem, "") == dm_wx:
                max_root_weight = max(max_root_weight, weight)
                if weight >= 0.5:
                    has_benqi_root = True

    # 检查生扶力量
    support_force = _calc_support_force(dm_wx, four_pillars)
    total_force = _calc_total_force(four_pillars)
    support_ratio = support_force / max(total_force, 1)

    # 日主有微根(仅余气通根)
    if max_root_weight > 0 and max_root_weight < 0.5 and not has_benqi_root:
        risk += 0.5
        details.append(
            f"日主仅余气通根（最大权重{max_root_weight}），"
            f"界于'无根无气'与'根浅力薄'之间"
        )

    # 生扶力量 < 20%
    if support_ratio < 0.20:
        risk += 0.3
        details.append(
            f"生扶力量占比{support_ratio:.0%}，不足20%，从而不纯"
        )

    return UncertaintyItem(
        dimension="congge",
        risk_score=min(risk, 1.0),
        label="高风险" if risk > 0.5 else ("中风险" if risk > 0.2 else "低风险"),
        detail="；".join(details) if details else "从格判定清晰",
    )


def _calc_support_force(dm_wx: str, four_pillars: dict) -> float:
    """计算日主生扶力量（印星+比劫力量）"""
    from rules.wuxing import WUXING_MAP, get_sheng

    # 生我者（印星）、同我者（比劫）
    sheng_wx = get_sheng(dm_wx)  # 生助日主的五行
    total = 0.0
    for pos in ["year", "month", "day", "hour"]:
        pillar = four_pillars.get(pos, {})
        stem = pillar.get("stem", "")
        wx = WUXING_MAP.get(stem, "")
        if wx:
            # 生我（印）
            if wx == sheng_wx:
                total += 1.0
            # 同我（比劫）
            if wx == dm_wx:
                total += 1.0

        # 地支藏干检查
        for hs in pillar.get("hidden_stems", []):
            hs_stem = hs.get("stem", "") if isinstance(hs, dict) else hs
            hs_wx = WUXING_MAP.get(hs_stem, "")
            hs_weight = hs.get("weight", 0.3) if isinstance(hs, dict) else 0.3
            if hs_wx:
                if hs_wx == sheng_wx:
                    total += hs_weight
                if hs_wx == dm_wx:
                    total += hs_weight

    return total


def _calc_total_force(four_pillars: dict) -> float:
    """计算全局总力量"""
    total = 0.0
    for pos in ["year", "month", "day", "hour"]:
        pillar = four_pillars.get(pos, {})
        # 天干
        if pillar.get("stem"):
            total += 1.0
        # 地支藏干
        for hs in pillar.get("hidden_stems", []):
            weight = hs.get("weight", 0.3) if isinstance(hs, dict) else 0.3
            total += weight
    return total


# ============================================================
# 主函数
# ============================================================

def generate_uncertainty_report(
    chart_data: dict,
    yongshen_data: dict,
    strength_detail: Optional[dict] = None,
    birth_longitude: float = 120.0,
    memory_uncertain: bool = False,
) -> UncertaintyReport:
    """生成不确定参数预标注报告。

    Args:
        chart_data: 排盘数据 dict（BaziChart.model_dump() 格式）
        yongshen_data: 用神分析结果 dict
        strength_detail: 旺衰分析详情（可选，含 total_score）
        birth_longitude: 出生地经度（默认北京 120°）
        memory_uncertain: 命主是否对出生时间记忆模糊

    Returns:
        UncertaintyReport: 五维标注报告
    """
    items = []

    # 获取出生信息
    birth_info = chart_data.get("birth_info", {})
    hour = birth_info.get("hour", 12)
    minute = birth_info.get("minute", 0)
    month = birth_info.get("month", 1)
    day = birth_info.get("day", 1)

    pattern = yongshen_data.get("pattern", "")

    if strength_detail is None:
        strength_detail = {"total_score": 50}

    # 维度 1: 时辰风险
    items.append(_label_shichen_risk(
        hour=hour,
        minute=minute,
        birth_longitude=birth_longitude,
        month=month,
        day=day,
        memory_uncertain=memory_uncertain,
    ))

    # 维度 2: 用神争议度
    items.append(_label_yongshen_risk(yongshen_data, chart_data))

    # 维度 3: 旺衰模糊度
    items.append(_label_wangshuai_risk(strength_detail))

    # 维度 4: 格局多解性
    items.append(_label_pattern_risk(pattern, strength_detail, chart_data))

    # 维度 5: 从格真假
    items.append(_label_congge_risk(pattern, strength_detail, chart_data))

    # 综合风险 = 五个维度平均值
    overall = sum(item.risk_score for item in items) / max(len(items), 1)
    overall = round(overall, 2)

    # 生成建议验证问题（按风险分排序取 Top 3）
    sorted_items = sorted(items, key=lambda x: -x.risk_score)
    suggested = [
        f"[{item.dimension}] {item.label}: {item.detail}"
        for item in sorted_items[:3]
    ]

    return UncertaintyReport(
        items=items,
        overall_risk=overall,
        suggested_questions=suggested,
    )


def mock_uncertainty_report() -> UncertaintyReport:
    """无数据时的保守回退：所有维度标注中风险。

    Returns:
        UncertaintyReport
    """
    dimensions = ["shichen", "yongshen", "wangshuai", "pattern", "congge"]
    return UncertaintyReport(
        items=[
            UncertaintyItem(
                dimension=d,
                risk_score=0.3,
                label="中风险",
                detail="缺少排盘数据，默认中风险",
            )
            for d in dimensions
        ],
        overall_risk=0.3,
        suggested_questions=["建议完成排盘后再进行不确定参数分析"],
    )


class UncertaintyLabeler:
    """五维不确定参数预标注器（API 入口封装）

    自动从 chart_data 中提取 yongshen_data 和 strength_detail，
    调用 generate_uncertainty_report() 生成报告。
    """

    def generate_uncertainty_report(self, chart_data: dict) -> dict:
        """从排盘数据生成五维风险预标注报告。

        Args:
            chart_data: 排盘数据 dict（BaziChart.model_dump() 格式）

        Returns:
            dict: 包含 items, overall_risk, suggested_questions
        """
        yongshen_data = chart_data.get("yongshen", {})
        strength_detail = chart_data.get("strength_detail", {})

        birth_info = chart_data.get("birth_info", {})
        birth_longitude = chart_data.get("true_solar_info", {}).get("longitude", 120.0)

        report = generate_uncertainty_report(
            chart_data=chart_data,
            yongshen_data=yongshen_data,
            strength_detail=strength_detail,
            birth_longitude=birth_longitude,
        )
        return {
            "items": [
                {
                    "dimension": item.dimension,
                    "risk_score": item.risk_score,
                    "label": item.label,
                    "detail": item.detail,
                }
                for item in report.items
            ],
            "overall_risk": report.overall_risk,
            "suggested_questions": report.suggested_questions,
        }
