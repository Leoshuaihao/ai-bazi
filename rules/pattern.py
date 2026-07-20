"""格局判定规则引擎 — 子平格局派

核心逻辑：
- "八字用神，专求月令" — 格局由月令地支藏干本气决定
- 格局分类：正格（八格）、变格（从格/专旺）、化格
- v2: 格局与用神分离验证，完全分类（14+种格局），拒绝检测与空间扩展
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

ALL_TEN_GODS = ["正官", "七杀", "正财", "偏财", "正印", "偏印", "食神", "伤官", "比肩", "劫财"]

# 禄位映射：天干 → 禄位地支
LU_POSITIONS = {
    "甲": "寅", "乙": "卯", "丙": "巳", "丁": "午",
    "戊": "巳", "己": "午", "庚": "申", "辛": "酉",
    "壬": "亥", "癸": "子",
}

# 刃位映射（阳干有刃）：天干 → 刃位地支
REN_POSITIONS = {
    "甲": "卯", "丙": "午", "戊": "午", "庚": "酉", "壬": "子",
}

# 天干五合
HEAVENLY_COMBINATIONS = {
    ("甲", "己"): "土", ("己", "甲"): "土",
    ("乙", "庚"): "金", ("庚", "乙"): "金",
    ("丙", "辛"): "水", ("辛", "丙"): "水",
    ("丁", "壬"): "木", ("壬", "丁"): "木",
    ("戊", "癸"): "火", ("癸", "戊"): "火",
}

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
    "正官": "正官格", "七杀": "七杀格",
    "正财": "正财格", "偏财": "偏财格",
    "正印": "正印格", "偏印": "偏印格",
    "食神": "食神格", "伤官": "伤官格",
}

# ============================================================
# 完全分类：全量格局空间生成（V2）
# ============================================================

ALL_STANDARD_PATTERNS = [
    "正官格", "七杀格", "正财格", "偏财格",
    "正印格", "偏印格", "食神格", "伤官格",
]

ALL_SPECIAL_PATTERNS = ["从弱格", "从强格", "专旺格", "化气格", "建禄格", "月刃格"]


def generate_full_pattern_space(day_master_stem: str, month_branch: str,
                                 strength_detail: dict, four_pillars: dict = None) -> list[dict]:
    """生成完全分类格局假设空间（V2核心）

    包含所有 14 种格局，仅格局名+置信度（用神在后阶段单独生成）。

    Returns:
        [{pattern, pattern_type, confidence, _month_main, ...}, ...]
    """
    hypotheses = []

    # 月令相关格局
    month_main_tg = get_month_main_ten_god(day_master_stem, month_branch)
    month_main_pattern = _TG_TO_PATTERN.get(month_main_tg, "")
    month_alt_pattern = _get_alternative_pattern(day_master_stem, month_branch)
    total_score = strength_detail.get("total_score", 50)
    dm_stem = day_master_stem[-1] if day_master_stem else ""

    # 特殊格局检测
    is_very_weak = total_score < 15
    is_very_strong = total_score > 85
    is_jian_lu = LU_POSITIONS.get(dm_stem) == month_branch
    is_yue_ren = REN_POSITIONS.get(dm_stem) == month_branch

    # 化气格检测
    is_hua_qi = False
    hua_qi_wx = ""
    if four_pillars and dm_stem:
        month_pillar = four_pillars.get("month", {})
        month_stem = month_pillar.get("stem", "")
        combo_key = (dm_stem, month_stem)
        if combo_key in HEAVENLY_COMBINATIONS:
            is_hua_qi = True
            hua_qi_wx = HEAVENLY_COMBINATIONS[combo_key]

    # 生成所有格局
    for pattern in ALL_STANDARD_PATTERNS:
        conf = _calc_pattern_init_confidence(
            pattern, month_main_pattern, month_alt_pattern,
            is_very_weak, is_very_strong, is_jian_lu, is_yue_ren, is_hua_qi
        )
        hypotheses.append({
            "pattern": pattern,
            "pattern_type": "正格",
            "confidence": conf,
            "_month_main": pattern == month_main_pattern,
            "_month_alt": pattern == month_alt_pattern,
        })

    # 特殊格局
    if is_very_weak:
        hypotheses.append({"pattern": "从弱格", "pattern_type": "从格", "confidence": 12})
    else:
        hypotheses.append({"pattern": "从弱格", "pattern_type": "从格", "confidence": 3})

    if is_very_strong:
        hypotheses.append({"pattern": "从强格", "pattern_type": "从格", "confidence": 12})
        hypotheses.append({"pattern": "专旺格", "pattern_type": "专旺", "confidence": 12})
    else:
        hypotheses.append({"pattern": "从强格", "pattern_type": "从格", "confidence": 3})
        hypotheses.append({"pattern": "专旺格", "pattern_type": "专旺", "confidence": 3})

    if is_hua_qi:
        hypotheses.append({"pattern": "化气格", "pattern_type": "化格",
                           "confidence": 15, "_hua_qi_wx": hua_qi_wx})
    else:
        hypotheses.append({"pattern": "化气格", "pattern_type": "化格", "confidence": 3})

    if is_jian_lu:
        hypotheses.append({"pattern": "建禄格", "pattern_type": "建禄", "confidence": 18})
    else:
        hypotheses.append({"pattern": "建禄格", "pattern_type": "建禄", "confidence": 3})

    if is_yue_ren:
        hypotheses.append({"pattern": "月刃格", "pattern_type": "月刃", "confidence": 18})
    else:
        hypotheses.append({"pattern": "月刃格", "pattern_type": "月刃", "confidence": 3})

    _normalize(hypotheses)
    return hypotheses


def _calc_pattern_init_confidence(pattern, month_main, month_alt,
                                   is_very_weak, is_very_strong,
                                   is_jian_lu, is_yue_ren, is_hua_qi):
    """计算格局初始置信度"""
    if pattern == month_main:
        if is_very_weak or is_very_strong:
            return 25  # 旺衰极端时月令格局权重降低
        return 35
    if pattern == month_alt:
        return 18
    if is_jian_lu and is_yue_ren:
        return 5  # 建禄月刃同时成立时，普通月令格局降权
    return 8  # 其余正格基础分


# ============================================================
# L1 广义分类问题（V2新增）
# ============================================================

L1_BROAD_QUESTIONS = [
    {
        "id": "authority",
        "question": "工作中你更倾向于带头推动决策、掌控局面，还是更喜欢钻研创作、按自己的节奏来？",
        "explanation": "格局分官杀向（重规则、执行力）和食伤向（重创造、自由度），这是判断格局大类的核心维度。",
        "options": ["带头推动", "偏向创作", "不太好说"],
        "mapping": {
            # 选"带头推动" → 官杀向格局命中
            "带头推动": {
                "正官格": "accurate", "七杀格": "accurate",
                "食神格": "inaccurate", "伤官格": "inaccurate",
            },
            # 选"偏向创作" → 食伤向格局命中
            "偏向创作": {
                "食神格": "accurate", "伤官格": "accurate",
                "正官格": "inaccurate", "七杀格": "inaccurate",
            },
            # "不太好说" → 所有格局 partial
            "不太好说": {},
        },
    },
    {
        "id": "pragmatism",
        "question": "你对实际的利益和机会是否比较敏感、做事看重结果，还是更看重知识积累、精神层面的满足？",
        "explanation": "财向格局务实重利，印向格局重学重养，这是区分财格与印格的关键。",
        "options": ["务实重结果", "重学习修养", "不太好说"],
        "mapping": {
            "务实重结果": {
                "正财格": "accurate", "偏财格": "accurate",
                "正印格": "inaccurate", "偏印格": "inaccurate",
            },
            "重学习修养": {
                "正印格": "accurate", "偏印格": "accurate",
                "正财格": "inaccurate", "偏财格": "inaccurate",
            },
            "不太好说": {},
        },
    },
]


def update_confidence_broad(hypotheses: list[dict], answer: str,
                             question_mapping: dict) -> list[dict]:
    """多目标微分置信度更新（V2新增，用于L1广义分类问题）

    question_mapping: {pattern: "accurate"|"partial"|"inaccurate"}
    """
    for h in hypotheses:
        expected = question_mapping.get(h["pattern"], "partial")
        if answer == expected:
            delta = +12
        elif expected == "partial":
            delta = 0
        else:
            delta = -18
        h["confidence"] = max(1, min(99, h["confidence"] + delta))
    _normalize(hypotheses)
    return hypotheses


# ============================================================
# 用神候选生成（V2新增 — 格局锁定后独立生成）
# ============================================================

# 用神与十神对应关系 + 每个用神对应的问题维度
YONGSHEN_DIMENSIONS = {
    "正印": {"dim": "贵人学历", "question": "你在学业上是否容易得到老师或长辈的欣赏和帮助？"},
    "偏印": {"dim": "偏门专长", "question": "你是否对某个特殊领域有超越常人的钻研天赋？"},
    "比肩": {"dim": "朋辈协作", "question": "你是否常能得到朋友或同事的实质性帮助？"},
    "劫财": {"dim": "竞争人脉", "question": "你是否在人际网络中获益较多，善于借助他人力量？"},
    "食神": {"dim": "才华创作", "question": "你的创造才能或手艺是否在生活中给你带来了实质性的收益或认可？"},
    "伤官": {"dim": "聪明表达", "question": "你是否常能靠自己的聪明才智或表达能力脱颖而出？"},
    "正财": {"dim": "理财务实", "question": "你对金钱和资源的把控是否比身边人更稳更准？"},
    "偏财": {"dim": "商业直觉", "question": "你是否容易抓住别人没注意到的商业或投资机会？"},
    "正官": {"dim": "规则纪律", "question": "你是否在讲规则、有秩序的环境中反而能发挥得更好？"},
    "七杀": {"dim": "决断魄力", "question": "你是否在高压和挑战下反而能做出比平时更好的决策？"},
}


def generate_yongshen_candidates(pattern: str, day_master_stem: str,
                                  strength_detail: dict, month_branch: str,
                                  history: list = None) -> list[dict]:
    """格局锁定后，生成该格局下所有合法用神候选（V2新增）

    Returns:
        [{yong_shen, five_element, gong_way, confidence, dimension, question}, ...]
    """
    candidates = []
    dm_stem = day_master_stem[-1] if day_master_stem else ""
    total_score = strength_detail.get("total_score", 50)
    ri_zhu_strength = strength_detail.get("ri_zhu_strength", "")

    # 旺衰方向
    is_strong = total_score > 50 or ri_zhu_strength in ("偏强", "强", "旺", "太旺", "极旺")

    # 调候需求
    month_num = _branch_to_num(month_branch)
    tiaohou_wx = _get_tiaohou_wuxing(month_num)

    for tg in ALL_TEN_GODS:
        # 过滤：身强排除印/比劫，身弱排除官杀/食伤/财（基本方向）
        is_strong_group = tg in ("比肩", "劫财", "正印", "偏印")
        is_weak_group = tg in ("正官", "七杀", "正财", "偏财", "食神", "伤官")

        if not _is_valid_yongshen_for_pattern(tg, pattern, is_strong):
            continue

        wx = _resolve_five_element(day_master_stem, tg, "")
        if not wx:
            continue

        # 初始置信度
        conf = 10  # 基础分

        # 旺衰加成
        if is_strong and is_weak_group:
            conf += 25
        elif not is_strong and is_strong_group:
            conf += 25

        # 格局规则加成
        if _matches_pattern_rule(tg, pattern):
            conf += 20

        # 调候加成
        if wx == tiaohou_wx:
            conf += 15

        dim_info = YONGSHEN_DIMENSIONS.get(tg, {"dim": "综合", "question": f"{tg}作为用神在哪些方面体现？"})
        gong_way = _get_gong_way_v2(pattern, tg)

        candidates.append({
            "yong_shen": tg,
            "five_element": wx,
            "gong_way": gong_way,
            "confidence": min(conf, 50),
            "dimension": dim_info["dim"],
            "dim_question": dim_info["question"],
        })

    # 排序
    candidates.sort(key=lambda x: x["confidence"], reverse=True)
    _normalize_yongshen(candidates)
    return candidates


def _is_valid_yongshen_for_pattern(tg, pattern, is_strong):
    """检查用神对该格局是否合法"""
    if pattern in ("从弱格", "从强格", "专旺格"):
        return True  # 特殊格局不限制
    if pattern in ("建禄格", "月刃格"):
        return True
    if pattern == "化气格":
        return True

    # 正格：基于顺用/逆用规则
    if is_strong:
        # 身强需要克泄耗
        return tg in ("正官", "七杀", "正财", "偏财", "食神", "伤官")
    else:
        # 身弱需要生扶
        return tg in ("正印", "偏印", "比肩", "劫财")


def _matches_pattern_rule(tg, pattern):
    """用神是否匹配格局顺用/逆用规则"""
    standard = PATTERN_YONGSHEN.get(pattern, [])
    for s_tg, _ in standard:
        if tg == s_tg:
            return True
    return False


def _branch_to_num(branch):
    """地支转月份"""
    mapping = {"寅": 1, "卯": 2, "辰": 3, "巳": 4, "午": 5, "未": 6,
               "申": 7, "酉": 8, "戌": 9, "亥": 10, "子": 11, "丑": 12}
    return mapping.get(branch, 6)


def _get_tiaohou_wuxing(month_num):
    """获取调候五行"""
    if month_num in (10, 11, 12):
        return "火"  # 冬生需火
    if month_num in (4, 5):
        return "水"  # 夏生需水
    if month_num in (1, 2):
        return "金"  # 春生需金（初春晚）
    return ""


def _get_gong_way_v2(pattern, yong_shen):
    """V2版作用功方式描述（扩展）"""
    ways = {
        ("正官格", "正印"): "印化官杀", ("正官格", "偏印"): "印化官杀",
        ("正官格", "正财"): "财生官",
        ("七杀格", "食神"): "食神制杀", ("七杀格", "伤官"): "伤官驾杀",
        ("七杀格", "正印"): "印化七杀",
        ("正财格", "食神"): "食神生财", ("正财格", "正官"): "财生官",
        ("正印格", "正官"): "官生印", ("正印格", "七杀"): "杀生印",
        ("食神格", "正财"): "食神生财",
        ("伤官格", "正印"): "印制伤官",
        ("偏印格", "偏财"): "财制偏印",
        ("偏财格", "正官"): "财生官",
        ("建禄格", "正官"): "禄上官星", ("建禄格", "正财"): "禄上生财",
        ("月刃格", "七杀"): "刃头架杀", ("月刃格", "正官"): "刃头官星",
    }
    def_key = (pattern, yong_shen)
    if def_key in ways:
        return ways[def_key]
    # 特殊格局通配
    if pattern in ("从弱格",):
        return "从弱顺势"
    if pattern in ("从强格",):
        return "从强顺势"
    if pattern in ("专旺格",):
        return "专旺顺势"
    return f"{pattern}用{yong_shen}"


def _normalize_yongshen(candidates):
    """归一化用神置信度"""
    if not candidates:
        return
    for c in candidates:
        c["confidence"] = max(1.0, min(99.0, c["confidence"]))


# ============================================================
# 旧版格局假设生成（保留向后兼容）
# ============================================================

PATTERN_YONGSHEN = {
    "正官格": [("正印", "木"), ("正财", "火"), ("偏印", "木")],
    "正财格": [("食神", "火"), ("正官", "金"), ("伤官", "火")],
    "正印格": [("正官", "金"), ("比肩", "同"), ("七杀", "金")],
    "食神格": [("比肩", "同"), ("正财", "火"), ("劫财", "同")],
    "七杀格": [("食神", "火"), ("正印", "木"), ("伤官", "火")],
    "伤官格": [("正印", "木"), ("偏财", "土"), ("偏印", "木")],
    "偏印格": [("偏财", "土"), ("比肩", "同"), ("正财", "火")],
    "偏财格": [("正官", "金"), ("食神", "火"), ("七杀", "金")],
}


def generate_pattern_hypotheses(day_master_stem: str, month_branch: str,
                                 strength_detail: dict) -> list[dict]:
    """生成格局假设向量（旧版，保留兼容）

    返回多个假设，每个包含 pattern + yong_shen + confidence 等。
    """
    primary_pattern = determine_pattern_type(day_master_stem, month_branch)
    hypotheses = []

    total_score = strength_detail.get("total_score", 50)
    special = _check_special_pattern(strength_detail, day_master_stem)
    if special:
        hypotheses.append(special)

    if primary_pattern:
        candidates = PATTERN_YONGSHEN.get(primary_pattern, [])
        for i, (tg, wx) in enumerate(candidates):
            actual_wx = _resolve_five_element(day_master_stem, tg, wx)
            conf = 35 - i * 8
            hypotheses.append({
                "pattern": primary_pattern, "pattern_type": "正格",
                "yong_shen": tg, "five_element": actual_wx,
                "gong_way": _get_gong_way(primary_pattern, tg),
                "confidence": max(conf, 5), "_month_lord": True,
            })

    alt_pattern = _get_alternative_pattern(day_master_stem, month_branch)
    if alt_pattern and alt_pattern != primary_pattern:
        candidates = PATTERN_YONGSHEN.get(alt_pattern, [])
        for i, (tg, wx) in enumerate(candidates[:2]):
            actual_wx = _resolve_five_element(day_master_stem, tg, wx)
            hypotheses.append({
                "pattern": alt_pattern, "pattern_type": "正格",
                "yong_shen": tg, "five_element": actual_wx,
                "gong_way": _get_gong_way(alt_pattern, tg),
                "confidence": max(20 - i * 8, 5),
            })

    _normalize(hypotheses)
    return hypotheses


# ============================================================
# 辅助函数
# ============================================================

def _check_special_pattern(strength_detail: dict, dm_stem: str) -> dict | None:
    """检查是否为特殊格局（从格/专旺格）"""
    total = strength_detail.get("total_score", 50)
    dm_wx = WUXING_MAP.get(dm_stem, "")
    if total < 15:
        return {
            "pattern": "从弱格", "pattern_type": "从格",
            "yong_shen": "食伤", "five_element": _I_SHENG.get(dm_wx, ""),
            "gong_way": "从弱顺势", "confidence": 15,
        }
    if total > 85:
        return {
            "pattern": "专旺格", "pattern_type": "专旺",
            "yong_shen": "比劫", "five_element": dm_wx,
            "gong_way": "专旺顺势", "confidence": 15,
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
    if ten_god in ("正印", "偏印"):
        return _SHENG.get(dm_wx, "")
    if ten_god in ("比肩", "劫财"):
        return dm_wx
    if ten_god in ("食神", "伤官"):
        return _I_SHENG.get(dm_wx, "")
    if ten_god in ("正财", "偏财"):
        return _I_KE.get(dm_wx, "")
    if ten_god in ("正官", "七杀"):
        return _KE.get(dm_wx, "")
    return fallback


def _get_gong_way(pattern: str, yong_shen: str) -> str:
    """根据格局和用神获取做功方式描述"""
    ways = {
        ("正官格", "正印"): "印化官杀", ("正官格", "偏印"): "印化官杀",
        ("正官格", "正财"): "财生官",
        ("七杀格", "食神"): "食神制杀", ("七杀格", "伤官"): "伤官驾杀",
        ("七杀格", "正印"): "印化七杀",
        ("正财格", "食神"): "食神生财", ("正财格", "正官"): "财生官",
        ("正印格", "正官"): "官生印", ("正印格", "七杀"): "杀生印",
        ("食神格", "正财"): "食神生财",
        ("伤官格", "正印"): "印制伤官",
        ("偏印格", "偏财"): "财制偏印",
        ("偏财格", "正官"): "财生官",
    }
    return ways.get((pattern, yong_shen), f"{pattern}用{yong_shen}")


def _normalize(hypotheses: list[dict]):
    if not hypotheses:
        return
    for h in hypotheses:
        h["confidence"] = max(1.0, min(99.0, h["confidence"]))


def check_hard_constraints(hypotheses: list[dict], dm_stem: str, month_branch: str) -> list[str]:
    """检查格局假设是否违反子平硬约束"""
    warnings = []
    month_pattern = determine_pattern_type(dm_stem, month_branch)
    for h in hypotheses:
        if h["pattern"] == month_pattern and h["confidence"] < 1:
            h["confidence"] = max(h["confidence"], 5)
    return warnings


def is_locked(hypotheses: list[dict]) -> dict | None:
    """判断是否应该锁定。返回锁定结果或 None。"""
    if not hypotheses:
        return None
    sorted_h = sorted(hypotheses, key=lambda x: x["confidence"], reverse=True)
    top = sorted_h[0]
    second = sorted_h[1] if len(sorted_h) > 1 else None
    if top["confidence"] >= 70:
        if second is None or top["confidence"] - second["confidence"] >= 20:
            return top
    return None


# ============================================================
# 置信度更新（保留旧版兼容）
# ============================================================

def update_confidence(hypotheses: list[dict], answer: str,
                       question_context: dict) -> list[dict]:
    """根据用户反馈更新置信度"""
    q_pattern = question_context.get("pattern", "")
    for h in hypotheses:
        is_primary = h["pattern"] == q_pattern
        if answer == "accurate":
            delta = 15 if is_primary else 3
        elif answer == "partial":
            delta = 0 if is_primary else -3
        else:
            delta = -20 if is_primary else -8
        h["confidence"] = max(1, min(99, h["confidence"] + delta))
    _normalize(hypotheses)
    for h in hypotheses:
        if h.get("_month_lord"):
            h["confidence"] = max(h["confidence"], 5)
    return hypotheses
