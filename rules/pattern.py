"""格局判定规则引擎 — 子平格局派

核心逻辑：
- "八字用神，专求月令" — 格局由月令地支藏干本气决定
- 格局分类：正格（八格）、变格（从格/专旺）、化格
- 硬约束：月令优先、官杀优先、格局不可跨大类翻转
"""
import json
import os

# 加载数据
_data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
with open(os.path.join(_data_dir, "hidden_stems.json"), "r", encoding="utf-8") as f:
    HIDDEN_STEMS_MAP = json.load(f)
with open(os.path.join(_data_dir, "wuxing_map.json"), "r", encoding="utf-8") as f:
    WUXING_MAP = json.load(f)

# ============================================================
# 基础映射
# ============================================================

YINYANG = {
    "甲": "阳", "丙": "阳", "戊": "阳", "庚": "阳", "壬": "阳",
    "乙": "阴", "丁": "阴", "己": "阴", "辛": "阴", "癸": "阴",
}

_SHENG = {"金": "土", "木": "水", "水": "金", "火": "木", "土": "火"}
_I_SHENG = {"金": "水", "木": "火", "水": "木", "火": "土", "土": "金"}
_KE = {"金": "火", "木": "金", "水": "土", "火": "水", "土": "木"}
_I_KE = {"金": "木", "木": "土", "水": "火", "火": "金", "土": "水"}

# 月令→格局十神映射 (月令藏干本气天干相对于日主的十神)
# 正官格: 月令本气为克我且阴阳相异
# 七杀格: 月令本气为克我且阴阳相同
# 等...

# ============================================================
# 十神计算
# ============================================================

def _calc_ten_god(day_master_stem: str, other_stem: str) -> str:
    dm_wx = WUXING_MAP.get(day_master_stem, "")
    ot_wx = WUXING_MAP.get(other_stem, "")
    if not dm_wx or not ot_wx:
        return ""
    same_yy = YINYANG.get(day_master_stem, "") == YINYANG.get(other_stem, "")
    if dm_wx == ot_wx:
        return "比肩" if same_yy else "劫财"
    if _SHENG[dm_wx] == ot_wx:
        return "偏印" if same_yy else "正印"
    if _I_SHENG[dm_wx] == ot_wx:
        return "食神" if same_yy else "伤官"
    if _I_KE[dm_wx] == ot_wx:
        return "偏财" if same_yy else "正财"
    if _KE[dm_wx] == ot_wx:
        return "七杀" if same_yy else "正官"
    return ""


# ============================================================
# 月令取格
# ============================================================

def get_month_stems(month_branch: str) -> list[str]:
    """获取月支藏干列表（本气→中气→余气）"""
    entries = HIDDEN_STEMS_MAP.get(month_branch, [])
    if entries and isinstance(entries[0], dict):
        return [e["stem"] for e in entries]
    return entries

def get_month_main_ten_god(day_master_stem: str, month_branch: str) -> str:
    """月令本气相对于日主的十神（决定格局类型）"""
    stems = get_month_stems(month_branch)
    if not stems:
        return ""
    return _calc_ten_god(day_master_stem, stems[0])

def determine_pattern_type(day_master_stem: str, month_branch: str) -> str:
    """根据月令确定格局类型（八格之一）"""
    ten_god = get_month_main_ten_god(day_master_stem, month_branch)
    return _TG_TO_PATTERN.get(ten_god, "")

_TG_TO_PATTERN = {
    "正官": "正官格",
    "七杀": "七杀格",
    "正财": "正财格",
    "偏财": "偏财格",
    "正印": "正印格",
    "偏印": "偏印格",
    "食神": "食神格",
    "伤官": "伤官格",
}

# ============================================================
# 格局假设生成
# ============================================================

# 正格用神规则（子平真诠：顺用/逆用）
# 吉神顺用：正官→财生官+印护官；正财→食生财+官护财；正印→官生印+比劫护印；食神→比劫生食+财护食
# 凶神逆用：七杀→食制杀+印制杀；伤官→印制伤+财化伤；偏印→财制偏印+比劫护身；劫财→官制劫

PATTERN_YONGSHEN = {
    # 吉神顺用
    "正官格": [("正印", "木"), ("正财", "火"), ("偏印", "木")],
    "正财格": [("食神", "火"), ("正官", "金"), ("伤官", "火")],
    "正印格": [("正官", "金"), ("比肩", "同"), ("七杀", "金")],
    "食神格": [("比肩", "同"), ("正财", "火"), ("劫财", "同")],
    # 凶神逆用
    "七杀格": [("食神", "火"), ("正印", "木"), ("伤官", "火")],
    "伤官格": [("正印", "木"), ("偏财", "土"), ("偏印", "木")],
    "偏印格": [("偏财", "土"), ("比肩", "同"), ("正财", "火")],
    "偏财格": [("正官", "金"), ("食神", "火"), ("七杀", "金")],
}

def generate_pattern_hypotheses(day_master_stem: str, month_branch: str,
                                 strength_detail: dict) -> list[dict]:
    """生成格局假设向量

    返回多个假设，每个包含：
    - pattern: 格局名称
    - yong_shen: 用神十神
    - five_element: 用神五行
    - gong_way: 做功方式
    - confidence: 初始置信度 (0-100)
    - pattern_type: 正格/从格/专旺
    """

    primary_pattern = determine_pattern_type(day_master_stem, month_branch)
    hypotheses = []

    # 1. 检查是否为特殊格局（从格/专旺）
    total_score = strength_detail.get("total_score", 50)
    special = _check_special_pattern(strength_detail, day_master_stem)
    if special:
        hypotheses.append(special)

    # 2. 主格局（月令本气）
    if primary_pattern:
        candidates = PATTERN_YONGSHEN.get(primary_pattern, [])
        for i, (tg, wx) in enumerate(candidates):
            # 将十神转换为五行
            actual_wx = _resolve_five_element(day_master_stem, tg, wx)
            conf = 35 - i * 8  # 第一候选35%，递减
            hypotheses.append({
                "pattern": primary_pattern,
                "pattern_type": "正格",
                "yong_shen": tg,
                "five_element": actual_wx,
                "gong_way": _get_gong_way(primary_pattern, tg),
                "confidence": max(conf, 5),
            })

    # 3. 次格局（月令中气/余气）
    alt_pattern = _get_alternative_pattern(day_master_stem, month_branch)
    if alt_pattern and alt_pattern != primary_pattern:
        candidates = PATTERN_YONGSHEN.get(alt_pattern, [])
        for i, (tg, wx) in enumerate(candidates[:2]):  # 最多2个候选
            actual_wx = _resolve_five_element(day_master_stem, tg, wx)
            hypotheses.append({
                "pattern": alt_pattern,
                "pattern_type": "正格",
                "yong_shen": tg,
                "five_element": actual_wx,
                "gong_way": _get_gong_way(alt_pattern, tg),
                "confidence": max(20 - i * 8, 5),
            })

    # 归一化
    _normalize(hypotheses)
    return hypotheses


def _check_special_pattern(strength_detail: dict, dm_stem: str) -> dict | None:
    """检查是否为特殊格局（从格/专旺格）"""
    total = strength_detail.get("total_score", 50)
    ri_zhu_strength = strength_detail.get("ri_zhu_strength", "")

    # 从弱格：得分 < 15
    if total < 15:
        return {
            "pattern": "从弱格",
            "pattern_type": "从格",
            "yong_shen": "食伤",
            "five_element": _I_SHENG.get(WUXING_MAP.get(dm_stem, ""), ""),
            "gong_way": "从弱顺势",
            "confidence": 15,
        }

    # 从强格（专旺）：得分 > 85
    if total > 85:
        return {
            "pattern": "专旺格",
            "pattern_type": "专旺",
            "yong_shen": "比劫",
            "five_element": WUXING_MAP.get(dm_stem, ""),
            "gong_way": "专旺顺势",
            "confidence": 15,
        }

    return None


def _get_alternative_pattern(dm_stem: str, month_branch: str) -> str:
    """从月令中气/余气获取备选格局"""
    stems = get_month_stems(month_branch)
    if len(stems) >= 2:
        tg = _calc_ten_god(dm_stem, stems[1])
        if tg in _TG_TO_PATTERN:
            return _TG_TO_PATTERN[tg]
    return ""


def _resolve_five_element(dm_stem: str, ten_god: str, fallback: str) -> str:
    """根据日主天干和十神推算用神五行"""
    dm_wx = WUXING_MAP.get(dm_stem, "")

    # 印星 → 生我者
    if ten_god in ("正印", "偏印"):
        return _SHENG.get(dm_wx, "")
    # 比劫 → 同我
    if ten_god in ("比肩", "劫财"):
        return dm_wx
    # 食伤 → 我生者
    if ten_god in ("食神", "伤官"):
        return _I_SHENG.get(dm_wx, "")
    # 财星 → 我克者
    if ten_god in ("正财", "偏财"):
        return _I_KE.get(dm_wx, "")
    # 官杀 → 克我者
    if ten_god in ("正官", "七杀"):
        return _KE.get(dm_wx, "")

    return fallback


def _get_gong_way(pattern: str, yong_shen: str) -> str:
    """根据格局和用神获取做功方式描述"""
    ways = {
        ("正官格", "正印"): "印化官杀",
        ("正官格", "偏印"): "印化官杀",
        ("正官格", "正财"): "财生官",
        ("七杀格", "食神"): "食神制杀",
        ("七杀格", "伤官"): "伤官驾杀",
        ("七杀格", "正印"): "印化七杀",
        ("正财格", "食神"): "食神生财",
        ("正财格", "正官"): "财生官",
        ("正印格", "正官"): "官生印",
        ("正印格", "七杀"): "杀生印",
        ("食神格", "正财"): "食神生财",
        ("伤官格", "正印"): "印制伤官",
        ("偏印格", "偏财"): "财制偏印",
        ("偏财格", "正官"): "财生官",
    }
    return ways.get((pattern, yong_shen), f"{pattern}用{yong_shen}")


def _normalize(hypotheses: list[dict]):
    """归一化置信度，确保无负数且无溢出"""
    if not hypotheses:
        return
    for h in hypotheses:
        h["confidence"] = max(1.0, min(99.0, h["confidence"]))


# ============================================================
# 硬约束检查
# ============================================================

def check_hard_constraints(hypotheses: list[dict], dm_stem: str, month_branch: str) -> list[str]:
    """检查格局假设是否违反子平硬约束。返回警告列表。"""
    warnings = []
    month_pattern = determine_pattern_type(dm_stem, month_branch)

    for h in hypotheses:
        # 约束1: 月令格局基础分数不能为0
        if h["pattern"] == month_pattern and h["confidence"] < 1:
            h["confidence"] = max(h["confidence"], 5)

        # 约束2: 格局类型不可跨大类（正格不能变为从格/专旺）
        # 这个在置信度更新时不翻转，由 convergence 算法保证

    return warnings


def is_locked(hypotheses: list[dict]) -> dict | None:
    """判断是否应该锁定。返回锁定结果或 None。"""
    if not hypotheses:
        return None

    sorted_h = sorted(hypotheses, key=lambda x: x["confidence"], reverse=True)
    top = sorted_h[0]
    second = sorted_h[1] if len(sorted_h) > 1 else None

    # 条件1: 置信度 ≥ 70% 且领先第二名 ≥ 20%
    if top["confidence"] >= 70:
        if second is None or top["confidence"] - second["confidence"] >= 20:
            return top

    # 条件2: 置信度 ≥ 60% 且连续2轮居首（需外部传入收敛轮数）
    return None


# ============================================================
# 置信度更新
# ============================================================

def update_confidence(hypotheses: list[dict], answer: str,
                       question_context: dict) -> list[dict]:
    """根据用户反馈更新置信度

    Args:
        hypotheses: 当前假设列表
        answer: "accurate" | "partial" | "inaccurate"
        question_context: {"pattern": str, "ten_god": str, "five_element": str} 所问的问题对应的格局信息

    Returns:
        更新后的 hypotheses
    """
    q_pattern = question_context.get("pattern", "")

    for h in hypotheses:
        is_primary = h["pattern"] == q_pattern

        if answer == "accurate":
            delta = 15 if is_primary else 3
        elif answer == "partial":
            delta = 0 if is_primary else -3
        else:  # inaccurate
            delta = -20 if is_primary else -8

        h["confidence"] = max(1, min(99, h["confidence"] + delta))

    _normalize(hypotheses)

    # 硬约束保护：月令格局基础分不低于5
    for h in hypotheses:
        if h.get("_month_lord"):  # 由generate标记为月令格局
            h["confidence"] = max(h["confidence"], 5)

    return hypotheses
