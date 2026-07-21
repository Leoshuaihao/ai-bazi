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
    # 月令为比劫，月令本身不可取用，另寻四柱透干
    "比肩": "建禄格",
    "劫财": "月刃格",
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
    # 月令无用神（比劫当令），另取四柱透干
    # 建禄格：日主乘旺，喜克泄耗（官杀制、食伤泄、财星耗）
    "建禄格": [("正官", "金"), ("食神", "火"), ("正财", "土")],
    # 月刃格：刃为凶神，必须官杀制刃或食伤泄刃
    "月刃格": [("七杀", "金"), ("正官", "金"), ("食神", "火")],
    # 特殊格局
    # 从弱格：顺势用官杀/财/食伤（忌印比生扶）
    "从弱格": [("七杀", "金"), ("正财", "土"), ("食神", "火")],
    # 专旺格：食伤泄秀为主，次取印比顺势（忌官杀犯旺）
    "专旺格": [("食神", "火"), ("正印", "木"), ("比肩", "同")],
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
                "_month_lord": True,  # 标记为月令主格局，置信度更新时受硬约束保护
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
        # 建禄格
        ("建禄格", "正官"): "官制禄",
        ("建禄格", "食神"): "食神泄秀",
        ("建禄格", "正财"): "财耗禄",
        # 月刃格
        ("月刃格", "七杀"): "杀制刃",
        ("月刃格", "正官"): "官制刃",
        ("月刃格", "食神"): "食神泄刃",
        # 特殊格局
        ("从弱格", "七杀"): "从弱杀顺势",
        ("从弱格", "正财"): "从弱财顺势",
        ("从弱格", "食神"): "从弱食伤顺势",
        ("专旺格", "食神"): "食神泄秀",
        ("专旺格", "正印"): "印生旺",
        ("专旺格", "比肩"): "比劫助旺",
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


# ============================================================
# V3 新增函数（T1-T6）
# ============================================================

# 六冲对
_OPPOSITES = {"子": "午", "午": "子", "丑": "未", "未": "丑",
              "寅": "申", "申": "寅", "卯": "酉", "酉": "卯",
              "辰": "戌", "戌": "辰", "巳": "亥", "亥": "巳"}

# 六合对
_COMBINATIONS = {"子": "丑", "丑": "子", "寅": "亥", "亥": "寅",
                  "卯": "戌", "戌": "卯", "辰": "酉", "酉": "辰",
                  "巳": "申", "申": "巳", "午": "未", "未": "午"}

# 三合局
_SANHE = {
    ("寅", "午", "戌"): "火", ("申", "子", "辰"): "水",
    ("巳", "酉", "丑"): "金", ("亥", "卯", "未"): "木",
}

# 三会局
_SANHUI = {
    ("寅", "卯", "辰"): "木", ("巳", "午", "未"): "火",
    ("申", "酉", "戌"): "金", ("亥", "子", "丑"): "水",
}

# 正偏十神配对（纯杂检测用）
_PURITY_PAIRS = {
    "正官格": ("正官", "七杀"), "七杀格": ("七杀", "正官"),
    "正财格": ("正财", "偏财"), "偏财格": ("偏财", "正财"),
    "正印格": ("正印", "偏印"), "偏印格": ("偏印", "正印"),
    "食神格": ("食神", "伤官"), "伤官格": ("伤官", "食神"),
}

# 通关五行映射
_TONGGUAN_MAP = {
    ("金", "木"): "水", ("木", "金"): "水",
    ("水", "火"): "木", ("火", "水"): "木",
    ("土", "水"): "金", ("水", "土"): "金",
    ("火", "金"): "土", ("金", "火"): "土",
    ("木", "土"): "火", ("土", "木"): "火",
}


def _extract_dm_stem(chart_data: dict) -> str:
    dm = chart_data.get("day_master", "")
    if isinstance(dm, dict):
        return dm.get("stem", "甲")
    return dm[-1] if dm else "甲"


def detect_ganzhi_touchu(chart_data: dict) -> dict:
    """T1: 检查月支藏干中哪个在天干透出"""
    fp = chart_data.get("four_pillars", {})
    month = fp.get("month", {})
    month_branch = month.get("branch", "")
    month_stems = get_month_stems(month_branch) if month_branch else []
    dm_stem = _extract_dm_stem(chart_data)

    gan_set = set()
    for pos in ["year", "month", "day", "hour"]:
        s = fp.get(pos, {}).get("stem", "")
        if s:
            gan_set.add(s)

    branch_stem_weight = {}
    for pos in ["year", "month", "day", "hour"]:
        hs = fp.get(pos, {}).get("hidden_stems", [])
        for entry in hs:
            if isinstance(entry, dict):
                stem = entry.get("stem", "")
                branch_stem_weight[stem] = max(branch_stem_weight.get(stem, 0), entry.get("weight", 0))

    result = {"touched_stem": None, "touched_ten_god": None, "level": None, "is_strong": False}
    for i, stem in enumerate(month_stems):
        if stem in gan_set:
            level = "本气" if i == 0 else ("中气" if i == 1 else "余气")
            result["touched_stem"] = stem
            result["touched_ten_god"] = _calc_ten_god(dm_stem, stem) if dm_stem else ""
            result["level"] = level
            result["is_strong"] = branch_stem_weight.get(stem, 0) >= 0.3
            return result
    return result


def detect_zhi_heju(chart_data: dict, month_branch: str) -> dict:
    """T2: 检查月支参与的三合三会"""
    fp = chart_data.get("four_pillars", {})
    all_branches = [fp.get(pos, {}).get("branch", "") for pos in ["year", "month", "day", "hour"]]

    if month_branch not in all_branches:
        all_branches.append(month_branch)

    result = {"type": None, "hua_wuxing": None, "is_complete": False, "pending": False}

    for (b1, b2, b3), wx in _SANHE.items():
        if month_branch in (b1, b2, b3):
            matches = sum(1 for b in (b1, b2, b3) if b in all_branches)
            if matches == 3:
                result.update({"type": "三合", "hua_wuxing": wx, "is_complete": True, "pending": True})
                return result
            elif matches == 2:
                result.update({"type": "半合", "hua_wuxing": wx})

    for (b1, b2, b3), wx in _SANHUI.items():
        if month_branch in (b1, b2, b3):
            matches = sum(1 for b in (b1, b2, b3) if b in all_branches)
            if matches == 3:
                result.update({"type": "三会", "hua_wuxing": wx, "is_complete": True, "pending": True})
                return result

    return result


def resolve_pending_heju(session_data: dict, wangshuai_level: str) -> dict:
    """Step3 完成后解析 pending 合局真假"""
    pending = session_data.get("pending_change") or {}
    if not pending.get("is_pending"):
        return session_data

    is_wang = wangshuai_level in ("极旺", "身旺")
    session_data["pending_change"]["resolved"] = True

    if is_wang:
        session_data["pattern"] = pending["candidate_pattern"]
        session_data["pattern_source"] = "三合变格" if "三合" in str(session_data.get("zhi_heju", "")) else "三会变格"
        session_data["pending_change"]["resolved_to"] = pending["candidate_pattern"]
    else:
        session_data["pending_change"]["resolved_to"] = None

    return session_data


def judge_wangshuai_level(chart_data: dict, strength_detail: dict) -> dict:
    """T3: 旺衰五等判断"""
    total = strength_detail.get("total_score", 50)
    ri_zhu = strength_detail.get("ri_zhu_strength", "")

    if total > 85 or ri_zhu in ("极旺",):
        level, direction = "极旺", "克泄耗"
    elif total >= 65:
        level, direction = "身旺", "克泄耗"
    elif total >= 35:
        level, direction = "中和", "灵活"
    elif total >= 15:
        level, direction = "身弱", "生扶"
    else:
        level, direction = "极弱", "生扶"

    return {"level": level, "deling": total >= 50, "dedi": total >= 60,
            "desheng": total >= 45, "dezhu": total >= 55, "yongshen_direction": direction}


def check_purity(pattern: str, chart_data: dict) -> dict:
    """T4: 检查格局的十神是否混杂"""
    pair = _PURITY_PAIRS.get(pattern)
    if not pair:
        return {"is_mixed": False, "mix_type": None, "mix_stems": None}

    tg_a, tg_b = pair
    dm_stem = _extract_dm_stem(chart_data)
    fp = chart_data.get("four_pillars", {})
    found_a, found_b = False, False

    for pos in ["year", "month", "day", "hour"]:
        stem = fp.get(pos, {}).get("stem", "")
        tg = _calc_ten_god(dm_stem, stem) if stem else ""
        if tg == tg_a:
            found_a = True
        if tg == tg_b:
            found_b = True

    if found_a and found_b:
        mix_name = f"{tg_a}{tg_b}混杂"
        return {"is_mixed": True, "mix_type": mix_name, "mix_stems": [tg_a, tg_b]}
    return {"is_mixed": False, "mix_type": None, "mix_stems": None}


def check_jiuying(chart_data: dict, yongshen_tg: str) -> dict:
    """T5: 救应检测"""
    dm_stem = _extract_dm_stem(chart_data)
    fp = chart_data.get("four_pillars", {})
    yongshen_wx = _resolve_five_element(dm_stem, yongshen_tg, "")
    if not yongshen_wx:
        return {"has_protection": False, "protection_blocked": False, "blocker": None}

    protector_wx = _SHENG.get(yongshen_wx, "")
    has_protection = False
    protector_tg = None

    for pos in ["year", "month", "day", "hour"]:
        p = fp.get(pos, {})
        stem = p.get("stem", "")
        if WUXING_MAP.get(stem, "") == protector_wx:
            tg = _calc_ten_god(dm_stem, stem)
            if tg != yongshen_tg:
                has_protection, protector_tg = True, tg
                break
        for hs in p.get("hidden_stems", []):
            s = hs.get("stem", "") if isinstance(hs, dict) else hs
            if WUXING_MAP.get(s, "") == protector_wx:
                has_protection = True
                break

    if not has_protection:
        return {"has_protection": False, "protection_blocked": False, "blocker": None}

    protection_blocked = False
    blocker = None
    if protector_tg:
        for pos in ["year", "month", "day", "hour"]:
            stem = fp.get(pos, {}).get("stem", "")
            tg = _calc_ten_god(dm_stem, stem) if stem else ""
            if tg != protector_tg and _KE.get(WUXING_MAP.get(stem, ""), "") == protector_wx:
                protection_blocked, blocker = True, tg
                break

    return {"has_protection": True, "protection_blocked": protection_blocked, "blocker": blocker}


def find_wuxing_clash(chart_data: dict) -> tuple | None:
    """T6a: 检测四柱五行对立"""
    fp = chart_data.get("four_pillars", {})
    wx_count = {"金": 0, "木": 0, "水": 0, "火": 0, "土": 0}
    total = 0

    for pos in ["year", "month", "day", "hour"]:
        p = fp.get(pos, {})
        stem, branch = p.get("stem", ""), p.get("branch", "")
        if stem:
            wx = WUXING_MAP.get(stem, "")
            if wx:
                wx_count[wx] += 1
                total += 1
        if branch:
            pass  # 地支不计入简版
        for hs in p.get("hidden_stems", []):
            s = hs.get("stem", "") if isinstance(hs, dict) else hs
            wx = WUXING_MAP.get(s, "")
            w = hs.get("weight", 0.3) if isinstance(hs, dict) else 0.3
            if wx:
                wx_count[wx] += w
                total += w

    if total == 0:
        return None

    clash_pairs = [("金", "木"), ("水", "火"), ("土", "水"), ("火", "金"), ("木", "土")]
    for a, b in clash_pairs:
        va, vb = wx_count.get(a, 0), wx_count.get(b, 0)
        if va + vb >= total * 0.6 and abs(va - vb) <= 2:
            return (a, b)
    return None


def get_tongguan_wuxing(pair: tuple) -> str:
    """T6b: 获取通关五行"""
    return _TONGGUAN_MAP.get(pair, "")


# ============================================================
# 格局派重构：相神规则表 + 救应表 + 新函数
# 基于《子平真诠》格局派体系
# ============================================================

# 相神维度映射（用于问题生成）
XIANGSHEN_DIMENSIONS = {
    "正印": "贵人学历", "偏印": "偏门专长",
    "比肩": "朋辈协作", "劫财": "竞争人脉",
    "食神": "才华创作", "伤官": "聪明表达",
    "正财": "理财务实", "偏财": "商业直觉",
    "正官": "规则纪律", "七杀": "决断魄力",
}

# 相神问题模板
_XIANGSHEN_QUESTIONS = {
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


# 相神问题模板（按角色区分）
_XIANGSHEN_QUESTIONS_BY_ROLE = {
    "正印": {
        "护用": "你是否感觉有一种无形的力量在背后保护你，让你在困难时总能化险为夷？",
        "化用": "你是否能把外界的压力转化为成长的动力，就像弹簧一样越压越强？",
        "生用": "你在学业或专业领域是否容易得到持续的指导和支持？",
    },
    "偏印": {
        "制用": "你是否能用自己的独特见解化解困境，找到别人看不到的出路？",
        "化用": "你是否能把不寻常的经历或知识转化为自己的优势？",
        "生用": "你是否对某个特殊领域有超越常人的钻研天赋？",
    },
    "比肩": {
        "护用": "你是否常能得到朋友或同事的实质性帮助，在关键时刻有人站台？",
        "生用": "你是否在团队合作中自然而然地成为核心，带动身边的人？",
        "顺势": "你是否发现自己和志同道合的人一起做事时效率最高？",
    },
    "劫财": {
        "制用": "你是否擅长在竞争中制衡对手，让自己处于有利位置？",
        "生用": "你是否在人际网络中获益较多，善于借助他人力量？",
        "顺势": "你是否发现在竞争激烈的环境中反而更能激发你的潜力？",
    },
    "食神": {
        "制用": "你是否擅长在混乱或高压的环境中找到秩序，把威胁变成机会？",
        "泄用": "你的创造力和才华是否有一个稳定的输出渠道，能持续产生成果？",
        "生用": "你是否自然而然地就能为他人或团队创造价值？",
    },
    "伤官": {
        "制用": "你是否能用自己的聪明才智化解规矩和约束带来的限制？",
        "泄用": "你是否有一个让你充分释放才华和创意的舞台？",
        "生用": "你是否常能靠自己的聪明才智或表达能力脱颖而出？",
    },
    "正财": {
        "护用": "你是否有稳定的资源或财富在为你保驾护航？",
        "泄用": "你是否善于把才华和机会转化为实在的收益？",
        "生用": "你对金钱和资源的把控是否比身边人更稳更准？",
    },
    "偏财": {
        "护用": "你是否有灵活的资源渠道在关键时刻为你提供支撑？",
        "泄用": "你是否善于把商业直觉转化为实际收益？",
        "生用": "你是否容易抓住别人没注意到的商业或投资机会？",
    },
    "正官": {
        "制用": "你是否能在规则和秩序的框架内有效控制局面？",
        "护用": "你是否有权威人士或制度在背后支持你的发展？",
        "生用": "你是否在讲规则、有秩序的环境中反而能发挥得更好？",
    },
    "七杀": {
        "制用": "你是否擅长直接面对并控制高压和危机局面？",
        "化用": "你是否能把外部的压力和威胁转化为前进的动力？",
        "生用": "你是否在高压和挑战下反而能做出比平时更好的决策？",
    },
}


def _infer_role(way: str) -> str:
    """从做功方式推断相神角色"""
    if "制" in way or "驾" in way:
        return "制用"
    elif "化" in way:
        return "化用"
    elif "泄" in way or "泄秀" in way:
        return "泄用"
    elif "护" in way or "保护" in way:
        return "护用"
    elif "生" in way and "泄" not in way:
        return "生用"
    elif "顺势" in way or "从" in way:
        return "顺势"
    return "生用"  # 默认


def _get_xiangshen_question(tg: str, way: str = "") -> str:
    """获取相神验证问题（按角色区分）"""
    role = _infer_role(way) if way else ""
    if role:
        role_questions = _XIANGSHEN_QUESTIONS_BY_ROLE.get(tg, {})
        if role in role_questions:
            return role_questions[role]
    return _XIANGSHEN_QUESTIONS.get(tg, f"{tg}作为相神在哪些方面体现？")


# ------------------------------------------------------------
# PATTERN_XIANGSHEN_RULES — 相神规则表（替代 PATTERN_YONGSHEN）
# 用神=月令定格之物（直接确定），相神=辅佐用神成格之物
# ------------------------------------------------------------

PATTERN_XIANGSHEN_RULES = {
    # === 顺用四格（善神） ===
    "正官格": {
        "yongshen": "正官",
        "mode": "顺用",
        "xiangshen_candidates": [
            {"ten_god": "正财", "role": "生用", "way": "财生官", "priority": 1},
            {"ten_god": "正印", "role": "护用", "way": "印护官", "priority": 2},
            {"ten_god": "偏财", "role": "生用", "way": "财生官", "priority": 3},
            {"ten_god": "偏印", "role": "护用", "way": "印护官", "priority": 4},
        ],
        "jishen": ["伤官", "七杀"],
        "defeat_causes": ["伤官克官", "官杀混杂", "官星被合"],
    },
    "正印格": {
        "yongshen": "正印",
        "mode": "顺用",
        "xiangshen_candidates": [
            {"ten_god": "正官", "role": "生用", "way": "官生印", "priority": 1},
            {"ten_god": "七杀", "role": "生用", "way": "杀生印", "priority": 2},
            {"ten_god": "比肩", "role": "护用", "way": "比劫护印", "priority": 3},
        ],
        "jishen": ["正财", "偏财"],
        "defeat_causes": ["财星破印"],
    },
    "食神格": {
        "yongshen": "食神",
        "mode": "顺用",
        "xiangshen_candidates": [
            {"ten_god": "比肩", "role": "生用", "way": "比劫生食", "priority": 1},
            {"ten_god": "正财", "role": "泄用", "way": "食神生财", "priority": 2},
            {"ten_god": "劫财", "role": "生用", "way": "比劫生食", "priority": 3},
        ],
        "jishen": ["偏印"],
        "defeat_causes": ["枭神夺食"],
    },
    "正财格": {
        "yongshen": "正财",
        "mode": "顺用",
        "xiangshen_candidates": [
            {"ten_god": "食神", "role": "生用", "way": "食伤生财", "priority": 1},
            {"ten_god": "正官", "role": "护用", "way": "官制比劫护财", "priority": 2},
            {"ten_god": "伤官", "role": "生用", "way": "食伤生财", "priority": 3},
        ],
        "jishen": ["比肩", "劫财"],
        "defeat_causes": ["比劫夺财"],
    },
    # === 逆用四格（恶神） ===
    "七杀格": {
        "yongshen": "七杀",
        "mode": "逆用",
        "xiangshen_candidates": [
            {"ten_god": "食神", "role": "制用", "way": "食神制杀", "priority": 1},
            {"ten_god": "正印", "role": "化用", "way": "印化七杀", "priority": 2},
            {"ten_god": "偏印", "role": "化用", "way": "印化七杀", "priority": 3},
            {"ten_god": "伤官", "role": "制用", "way": "伤官驾杀", "priority": 4},
        ],
        "jishen": ["正财", "偏财"],
        "defeat_causes": ["杀无制", "财星党杀", "制杀太过"],
    },
    "伤官格": {
        "yongshen": "伤官",
        "mode": "逆用",
        "xiangshen_candidates": [
            {"ten_god": "正印", "role": "制用", "way": "印制伤官", "priority": 1},
            {"ten_god": "偏印", "role": "制用", "way": "印制伤官", "priority": 2},
            {"ten_god": "偏财", "role": "泄用", "way": "财泄伤官", "priority": 3},
            {"ten_god": "正财", "role": "泄用", "way": "财泄伤官", "priority": 4},
        ],
        "jishen": ["正官"],
        "defeat_causes": ["伤官无制", "伤官见官"],
    },
    "偏印格": {
        "yongshen": "偏印",
        "mode": "逆用",
        "xiangshen_candidates": [
            {"ten_god": "偏财", "role": "制用", "way": "财制偏印", "priority": 1},
            {"ten_god": "正财", "role": "制用", "way": "财制偏印", "priority": 2},
        ],
        "jishen": [],
        "defeat_causes": ["枭神夺食", "偏印无制"],
    },
    "偏财格": {
        "yongshen": "偏财",
        "mode": "顺用",
        "xiangshen_candidates": [
            {"ten_god": "食神", "role": "生用", "way": "食伤生财", "priority": 1},
            {"ten_god": "正官", "role": "护用", "way": "官护财", "priority": 2},
            {"ten_god": "伤官", "role": "生用", "way": "食伤生财", "priority": 3},
        ],
        "jishen": ["比肩", "劫财"],
        "defeat_causes": ["比劫夺财"],
    },
    # === 建禄格/月刃格（比劫当令，月令定格之物为比肩/劫财，逆用制之化之） ===
    "建禄格": {
        "yongshen": "比肩",
        "mode": "逆用",
        "xiangshen_candidates": [
            {"ten_god": "正官", "role": "制用", "way": "官制禄", "priority": 1},
            {"ten_god": "七杀", "role": "制用", "way": "杀制禄", "priority": 2},
            {"ten_god": "正财", "role": "泄用", "way": "禄生财", "priority": 3},
            {"ten_god": "食神", "role": "泄用", "way": "食伤泄秀", "priority": 4},
        ],
        "jishen": [],
        "defeat_causes": ["建禄无制"],
    },
    "月刃格": {
        "yongshen": "劫财",
        "mode": "逆用",
        "xiangshen_candidates": [
            {"ten_god": "七杀", "role": "制用", "way": "杀制刃", "priority": 1},
            {"ten_god": "正官", "role": "制用", "way": "官制刃", "priority": 2},
            {"ten_god": "食神", "role": "泄用", "way": "食伤泄刃", "priority": 3},
        ],
        "jishen": [],
        "defeat_causes": ["阳刃无制", "冲刃"],
    },
    # === 特殊格局 ===
    "从弱格": {
        "yongshen": "从势",
        "mode": "顺势",
        "xiangshen_candidates": [
            {"ten_god": "七杀", "role": "顺势", "way": "从杀顺势", "priority": 1},
            {"ten_god": "正财", "role": "顺势", "way": "从财顺势", "priority": 2},
            {"ten_god": "食神", "role": "顺势", "way": "从儿顺势", "priority": 3},
        ],
        "jishen": ["正印", "偏印", "比肩", "劫财"],
        "defeat_causes": ["印比扶身破从"],
    },
    "专旺格": {
        "yongshen": "比肩",
        "mode": "顺势",
        "xiangshen_candidates": [
            {"ten_god": "食神", "role": "泄秀", "way": "食伤泄秀", "priority": 1},
            {"ten_god": "正印", "role": "生扶", "way": "印生旺神", "priority": 2},
            {"ten_god": "比肩", "role": "顺势", "way": "比劫顺势", "priority": 3},
        ],
        "jishen": ["正官", "七杀"],
        "defeat_causes": ["官杀犯旺"],
    },
    # === 化气格（天干五合化气，用神=化神） ===
    "化气格": {
        "yongshen": "化神",
        "mode": "顺势",
        "xiangshen_candidates": [
            {"ten_god": "食神", "role": "泄秀", "way": "食伤泄化神之秀", "priority": 1},
            {"ten_god": "正财", "role": "顺势", "way": "财星顺势", "priority": 2},
            {"ten_god": "正印", "role": "生扶", "way": "印星生扶化神", "priority": 3},
        ],
        "jishen": ["正官", "七杀"],
        "defeat_causes": ["化神被克", "日主有根破化"],
    },
}


# ------------------------------------------------------------
# JIUYING_TABLE — 救应对应表（败因 → 救应之神 → 救应机制）
# 基于《子平真诠·论用神成败救应》
# ------------------------------------------------------------

JIUYING_TABLE = {
    "伤官克官": {
        "jiuying_shen": ["正印", "偏印"],
        "mechanism": "印制伤官，伤官不克官",
        "source": "《子平真诠》",
    },
    "官杀混杂": {
        "jiuying_shen": ["食神"],
        "mechanism": "食神制杀留官，或合去七杀留正官",
        "source": "《子平真诠》《渊海子平》",
    },
    "官星被合": {
        "jiuying_shen": [],
        "mechanism": "看合化后能否成新格",
        "source": "【补充】《子平真诠》论十干合而不合",
    },
    "比劫夺财": {
        "jiuying_shen": ["正官", "七杀"],
        "mechanism": "官杀制比劫，护财不破",
        "source": "《子平真诠》",
    },
    "财星破印": {
        "jiuying_shen": ["正官", "七杀"],
        "mechanism": "官杀通关：财生官杀，官杀生印",
        "source": "《子平真诠》",
    },
    "枭神夺食": {
        "jiuying_shen": ["偏财", "正财"],
        "mechanism": "财制偏印，护食神",
        "source": "《子平真诠》",
    },
    "杀无制": {
        "jiuying_shen": ["食神", "正印", "偏印"],
        "mechanism": "食神制杀或印星化杀",
        "source": "《子平真诠》",
    },
    "财星党杀": {
        "jiuying_shen": ["比肩", "劫财"],
        "mechanism": "比劫制财，断其党援",
        "source": "【补充】《子平真诠》推论",
    },
    "制杀太过": {
        "jiuying_shen": ["偏财", "正财"],
        "mechanism": "财泄食神生七杀，恢复平衡",
        "source": "《子平真诠》",
    },
    "伤官无制": {
        "jiuying_shen": ["正印", "偏印", "偏财", "正财"],
        "mechanism": "印制伤官或财泄伤官",
        "source": "《子平真诠》",
    },
    "伤官见官": {
        "jiuying_shen": ["偏财", "正财", "正印"],
        "mechanism": "财通关（伤官生财，财生官）或印制伤官护官",
        "source": "《子平真诠》",
    },
    "阳刃无制": {
        "jiuying_shen": ["正官", "七杀"],
        "mechanism": "官杀制刃",
        "source": "《子平真诠》",
    },
    "冲刃": {
        "jiuying_shen": [],
        "mechanism": "合住冲刃之神解冲",
        "source": "【补充】《滴天髓》合解冲理论",
    },
    "建禄无制": {
        "jiuying_shen": ["正官", "七杀", "食神"],
        "mechanism": "官杀制禄或食伤泄秀",
        "source": "《子平真诠》",
    },
    "印比扶身破从": {
        "jiuying_shen": [],
        "mechanism": "无救应，从格被破",
        "source": "《子平真诠》",
    },
    "官杀犯旺": {
        "jiuying_shen": [],
        "mechanism": "无救应，专旺格被破",
        "source": "《子平真诠》",
    },
    "用神被合": {
        "jiuying_shen": [],
        "mechanism": "看合化后能否成新格",
        "source": "【补充】《子平真诠》论十干合而不合",
    },
    "用神被冲": {
        "jiuying_shen": [],
        "mechanism": "合住冲神以解冲",
        "source": "【补充】《子平真诠》第22章月令逢冲理论",
    },
    "偏印无制": {
        "jiuying_shen": ["偏财", "正财"],
        "mechanism": "财制偏印，使偏印不夺食不扰命",
        "source": "《子平真诠》",
    },
    "化神被克": {
        "jiuying_shen": ["正印"],
        "mechanism": "印星生扶化神，化解克神",
        "source": "《子平真诠》论化气格",
    },
    "日主有根破化": {
        "jiuying_shen": [],
        "mechanism": "日主有根则化不真，无救应需看真假化",
        "source": "《子平真诠》论十干配合性情",
    },
}


# ------------------------------------------------------------
# 格局派核心函数
# ------------------------------------------------------------

# 天干五合: (stem_a, stem_b) → 化气五行
_TIAN_GAN_HE = {
    ("甲", "己"): "土", ("己", "甲"): "土",
    ("乙", "庚"): "金", ("庚", "乙"): "金",
    ("丙", "辛"): "水", ("辛", "丙"): "水",
    ("丁", "壬"): "木", ("壬", "丁"): "木",
    ("戊", "癸"): "火", ("癸", "戊"): "火",
}


def _check_tian_gan_he(stem_a: str, stem_b: str) -> str | None:
    """检查两个天干是否五合，返回化气五行或None"""
    return _TIAN_GAN_HE.get((stem_a, stem_b))


def _determine_congshi_yongshen(dm_stem: str, chart_data: dict) -> str:
    """从弱格动态确定用神：命局中最旺的十神（从杀/从财/从儿）

    优先级：七杀 > 正财/偏财 > 食神/伤官
    （按命局中出现的力量强弱判断）
    """
    fp = chart_data.get("four_pillars", {})
    tg_counts = {}

    for pos in ["year", "month", "day", "hour"]:
        stem = fp.get(pos, {}).get("stem", "")
        if stem and stem != dm_stem:
            tg = _calc_ten_god(dm_stem, stem)
            tg_counts[tg] = tg_counts.get(tg, 0) + 1
        # 藏干也计入
        for hs in fp.get(pos, {}).get("hidden_stems", []):
            s = hs.get("stem", "") if isinstance(hs, dict) else hs
            w = hs.get("weight", 0.3) if isinstance(hs, dict) else 0.3
            if s and s != dm_stem:
                tg = _calc_ten_god(dm_stem, s)
                tg_counts[tg] = tg_counts.get(tg, 0) + w

    # 优先从杀，次从财，再从儿
    priority_order = ["七杀", "正官", "正财", "偏财", "食神", "伤官"]
    best_tg = ""
    best_score = 0
    for tg in priority_order:
        score = tg_counts.get(tg, 0)
        if score > best_score:
            best_score = score
            best_tg = tg

    return best_tg if best_tg else "七杀"  # 默认从杀


def determine_yongshen(pattern: str, dm_stem: str, month_branch: str, chart_data: dict = None) -> dict:
    """确定用神（=月令定格之物，直接确定，不竞争）

    返回: {
        "ten_god": "正官",
        "five_element": "金",
        "pattern": "正官格",
        "mode": "顺用",
    }
    """
    rules = PATTERN_XIANGSHEN_RULES.get(pattern, {})
    ys_tg = rules.get("yongshen", "")
    mode = rules.get("mode", "")

    # 从弱格：动态确定用神为命局中最旺的十神（从杀/从财/从儿）
    if ys_tg == "从势" and chart_data:
        ys_tg = _determine_congshi_yongshen(dm_stem, chart_data)

    wx = _resolve_five_element(dm_stem, ys_tg, "")
    return {
        "ten_god": ys_tg,
        "five_element": wx,
        "pattern": pattern,
        "mode": mode,
    }


def _check_shen_in_chart(ten_god: str, dm_stem: str, chart_data: dict) -> bool:
    """检查某十神是否在四柱天干中存在"""
    fp = chart_data.get("four_pillars", {})
    for pos in ["year", "month", "day", "hour"]:
        stem = fp.get(pos, {}).get("stem", "")
        if stem:
            tg = _calc_ten_god(dm_stem, stem)
            if tg == ten_god:
                return True
    # 也检查地支藏干
    for pos in ["year", "month", "day", "hour"]:
        for hs in fp.get(pos, {}).get("hidden_stems", []):
            s = hs.get("stem", "") if isinstance(hs, dict) else hs
            if s:
                tg = _calc_ten_god(dm_stem, s)
                if tg == ten_god:
                    return True
    return False


def _check_shen_status(ten_god: str, chart_data: dict) -> tuple:
    """检查某十神在命局中的状态：(exists, has_root, touches_dry)

    - exists: 是否在四柱中存在（天干或藏干）
    - has_root: 是否在地支有本气根
    - touches_dry: 是否透干（天干出现）
    """
    fp = chart_data.get("four_pillars", {})
    dm_stem = _extract_dm_stem(chart_data)
    exists = False
    touches_dry = False
    has_root = False

    for pos in ["year", "month", "day", "hour"]:
        stem = fp.get(pos, {}).get("stem", "")
        if stem:
            tg = _calc_ten_god(dm_stem, stem)
            if tg == ten_god:
                exists = True
                touches_dry = True

    for pos in ["year", "month", "day", "hour"]:
        for hs in fp.get(pos, {}).get("hidden_stems", []):
            s = hs.get("stem", "") if isinstance(hs, dict) else hs
            w = hs.get("weight", 0.3) if isinstance(hs, dict) else 0.3
            if s:
                tg = _calc_ten_god(dm_stem, s)
                if tg == ten_god:
                    exists = True
                    if w >= 0.5:
                        has_root = True

    return (exists, has_root, touches_dry)


def generate_xiangshen_candidates(pattern: str, dm_stem: str, chart_data: dict) -> list:
    """按顺用/逆用规则生成相神候选

    返回候选列表，每个候选:
    {
        "role": "相神",
        "ten_god": "正财",
        "five_element": "火",
        "gong_way": "财生官",
        "priority": 1,
        "confidence": 50,
        "exists_in_chart": True/False,
        "dim": "财运事业",
        "question": "...",
    }
    """
    rules = PATTERN_XIANGSHEN_RULES.get(pattern, {})
    candidates_spec = rules.get("xiangshen_candidates", [])

    candidates = []
    for spec in candidates_spec:
        tg = spec["ten_god"]
        wx = _resolve_five_element(dm_stem, tg, "")
        exists = _check_shen_in_chart(tg, dm_stem, chart_data)

        candidates.append({
            "role": "相神",
            "ten_god": tg,
            "five_element": wx,
            "gong_way": spec["way"],
            "priority": spec["priority"],
            "confidence": 50 + (10 if exists else 0),
            "exists_in_chart": exists,
            "dim": XIANGSHEN_DIMENSIONS.get(tg, "综合"),
            "question": _get_xiangshen_question(tg, spec["way"]),
        })

    return candidates


def _check_guanxing_be_he(dm_stem: str, chart_data: dict) -> bool:
    """检测正官星是否被天干五合（非日主自合）

    《子平真诠·论十干合而不合》："甲用辛官，透丙作合，而官非其官"
    日主自合不为合去："乙用庚官，日干之乙与庚作合，是我之官，是我合之"
    """
    fp = chart_data.get("four_pillars", {})
    # 找到正官天干
    guan_stem = None
    guan_pos = None
    for pos in ["year", "month", "hour"]:
        stem = fp.get(pos, {}).get("stem", "")
        if stem and _calc_ten_god(dm_stem, stem) == "正官":
            guan_stem = stem
            guan_pos = pos
            break
    if not guan_stem:
        return False

    # 检查是否有其他天干与正官五合（排除日主自合）
    for pos in ["year", "month", "hour"]:
        if pos == guan_pos:
            continue
        stem = fp.get(pos, {}).get("stem", "")
        if stem and stem != dm_stem:
            if _check_tian_gan_he(guan_stem, stem):
                return True
    return False


def _check_yongshen_be_he(pattern: str, dm_stem: str, chart_data: dict) -> bool:
    """检测用神是否被天干五合（非日主自合）"""
    rules = PATTERN_XIANGSHEN_RULES.get(pattern, {})
    ys_tg_name = rules.get("yongshen", "")
    if not ys_tg_name or ys_tg_name == "从势":
        return False

    fp = chart_data.get("four_pillars", {})
    # 找到用神天干
    ys_stem = None
    ys_pos = None
    for pos in ["year", "month", "hour"]:
        stem = fp.get(pos, {}).get("stem", "")
        if stem and _calc_ten_god(dm_stem, stem) == ys_tg_name:
            ys_stem = stem
            ys_pos = pos
            break
    if not ys_stem:
        return False

    # 检查是否有其他天干与用神五合（排除日主自合）
    for pos in ["year", "month", "hour"]:
        if pos == ys_pos:
            continue
        stem = fp.get(pos, {}).get("stem", "")
        if stem and stem != dm_stem:
            if _check_tian_gan_he(ys_stem, stem):
                return True
    return False


def _check_yongshen_chong(pattern: str, chart_data: dict) -> bool:
    """检测月令（用神之根）是否被地支六冲"""
    fp = chart_data.get("four_pillars", {})
    month_branch = fp.get("month", {}).get("branch", "")
    if not month_branch:
        return False

    opposite = _OPPOSITES.get(month_branch, "")
    if not opposite:
        return False

    # 检查年支、日支、时支是否冲月令
    for pos in ["year", "day", "hour"]:
        b = fp.get(pos, {}).get("branch", "")
        if b == opposite:
            return True
    return False


def _check_defeat_cause(cause_name: str, pattern: str, chart_data: dict) -> bool:
    """检测命局中是否存在某败因"""
    dm_stem = _extract_dm_stem(chart_data)
    fp = chart_data.get("four_pillars", {})

    # 收集四柱所有天干十神
    all_tg = set()
    for pos in ["year", "month", "day", "hour"]:
        stem = fp.get(pos, {}).get("stem", "")
        if stem:
            all_tg.add(_calc_ten_god(dm_stem, stem))

    if cause_name == "伤官克官":
        return "伤官" in all_tg and "正官" in all_tg
    elif cause_name == "官杀混杂":
        return "正官" in all_tg and "七杀" in all_tg
    elif cause_name == "官星被合":
        # 正官透干且被他干五合（非日主自合）
        return _check_guanxing_be_he(dm_stem, chart_data)
    elif cause_name == "比劫夺财":
        return ("比肩" in all_tg or "劫财" in all_tg) and ("正财" in all_tg or "偏财" in all_tg)
    elif cause_name == "财星破印":
        return ("正财" in all_tg or "偏财" in all_tg) and ("正印" in all_tg or "偏印" in all_tg)
    elif cause_name == "枭神夺食":
        return "偏印" in all_tg and "食神" in all_tg
    elif cause_name == "杀无制":
        return "七杀" in all_tg and "食神" not in all_tg and "正印" not in all_tg and "偏印" not in all_tg
    elif cause_name == "财星党杀":
        return ("正财" in all_tg or "偏财" in all_tg) and "七杀" in all_tg
    elif cause_name == "制杀太过":
        # 食神数量 >= 2 且七杀存在
        sg_count = sum(1 for pos in ["year", "month", "day", "hour"]
                       if _calc_ten_god(dm_stem, fp.get(pos, {}).get("stem", "")) == "食神")
        return sg_count >= 2 and "七杀" in all_tg
    elif cause_name == "伤官无制":
        # 伤官伤尽（不见正官）则为贵格，不判败
        if pattern == "伤官格" and "正官" not in all_tg:
            # 检查藏干中也无正官
            has_guan_hidden = False
            for pos in ["year", "month", "day", "hour"]:
                for hs in fp.get(pos, {}).get("hidden_stems", []):
                    s = hs.get("stem", "") if isinstance(hs, dict) else hs
                    if s and _calc_ten_god(dm_stem, s) == "正官":
                        has_guan_hidden = True
                        break
            if not has_guan_hidden:
                return False  # 伤官伤尽，不判败
        return "伤官" in all_tg and "正印" not in all_tg and "偏印" not in all_tg
    elif cause_name == "伤官见官":
        return "伤官" in all_tg and "正官" in all_tg
    elif cause_name == "阳刃无制":
        return pattern == "月刃格" and "正官" not in all_tg and "七杀" not in all_tg
    elif cause_name == "冲刃":
        # 简化：月刃格且月令被冲
        month_branch = fp.get("month", {}).get("branch", "")
        for pos in ["year", "day"]:
            b = fp.get(pos, {}).get("branch", "")
            if b and b == _OPPOSITES.get(month_branch, ""):
                return True
        return False
    elif cause_name == "建禄无制":
        return pattern == "建禄格" and "正官" not in all_tg and "七杀" not in all_tg and "食神" not in all_tg
    elif cause_name == "印比扶身破从":
        if pattern != "从弱格":
            return False
        return "正印" in all_tg or "偏印" in all_tg or "比肩" in all_tg or "劫财" in all_tg
    elif cause_name == "官杀犯旺":
        if pattern != "专旺格":
            return False
        return "正官" in all_tg or "七杀" in all_tg
    elif cause_name == "用神被合":
        return _check_yongshen_be_he(pattern, dm_stem, chart_data)
    elif cause_name == "用神被冲":
        return _check_yongshen_chong(pattern, chart_data)
    elif cause_name == "偏印无制":
        # 偏印格中偏印透干且无财星制之
        return pattern == "偏印格" and "偏印" in all_tg and "偏财" not in all_tg and "正财" not in all_tg
    elif cause_name == "化神被克":
        # 化气格中化神五行被克
        if pattern != "化气格":
            return False
        huaqi_wx = _detect_huaqi_wuxing(dm_stem, chart_data)
        if not huaqi_wx:
            return False
        ke_wx = _KE.get(huaqi_wx, "")
        for pos in ["year", "month", "day", "hour"]:
            stem = fp.get(pos, {}).get("stem", "")
            if stem and WUXING_MAP.get(stem, "") == ke_wx and stem != dm_stem:
                return True
        return False
    elif cause_name == "日主有根破化":
        # 化气格中日主有根则化不真
        if pattern != "化气格":
            return False
        dm_wx = WUXING_MAP.get(dm_stem, "")
        for pos in ["year", "month", "day", "hour"]:
            for hs in fp.get(pos, {}).get("hidden_stems", []):
                s = hs.get("stem", "") if isinstance(hs, dict) else hs
                w = hs.get("weight", 0.3) if isinstance(hs, dict) else 0.3
                if s and WUXING_MAP.get(s, "") == dm_wx and w >= 0.5:
                    return True
        return False

    return False


def check_chengbai(pattern: str, yongshen: dict, xiangshen: dict, chart_data: dict) -> dict:
    """成败检测：检测命局中是否有克用神、混用神之物

    返回: {
        "is_defeated": False,
        "defeat_causes": [],
        "has_xiangshen": True,
    }
    """
    rules = PATTERN_XIANGSHEN_RULES.get(pattern, {})
    defeat_cause_names = rules.get("defeat_causes", [])

    causes_found = []
    for cause_name in defeat_cause_names:
        if _check_defeat_cause(cause_name, pattern, chart_data):
            causes_found.append(cause_name)

    return {
        "is_defeated": len(causes_found) > 0,
        "defeat_causes": causes_found,
        "has_xiangshen": xiangshen.get("exists_in_chart", False) if xiangshen else False,
    }


def _level_rank(level: str) -> int:
    """救应等级转数字"""
    ranks = {"无": 0, "下等": 1, "中等": 2, "上等": 3}
    return ranks.get(level, 0)


def check_jiuying_v2(pattern: str, defeat_causes: list, chart_data: dict) -> dict:
    """救应检测：检测是否有制忌之神

    返回: {
        "has_jiuying": True,
        "jiuying_shen": "正印",
        "jiuying_level": "上等",
        "mechanism": "印制伤官",
    }
    """
    best_jiuying = None
    best_level = "无"
    best_mechanism = ""

    for cause_name in defeat_causes:
        rule = JIUYING_TABLE.get(cause_name, {})
        jiuying_shens = rule.get("jiuying_shen", [])

        for shen in jiuying_shens:
            exists, has_root, touches = _check_shen_status(shen, chart_data)
            if exists:
                if touches and has_root:
                    level = "上等"
                elif touches:
                    level = "中等"
                else:
                    level = "下等"

                if _level_rank(level) > _level_rank(best_level):
                    best_jiuying = shen
                    best_level = level
                    best_mechanism = rule.get("mechanism", "")

    return {
        "has_jiuying": best_jiuying is not None,
        "jiuying_shen": best_jiuying,
        "jiuying_level": best_level,
        "mechanism": best_mechanism,
    }


# ------------------------------------------------------------
# 化气格检测
# ------------------------------------------------------------

def _detect_huaqi_wuxing(dm_stem: str, chart_data: dict) -> str | None:
    """检测天干五合化气，返回化神五行或None

    《子平真诠·论十干配合性情》：日干与月干或时干五合，化神当令乘旺为真化
    """
    fp = chart_data.get("four_pillars", {})
    month_stem = fp.get("month", {}).get("stem", "")
    hour_stem = fp.get("hour", {}).get("stem", "")

    # 日干与月干或时干五合
    for partner in [month_stem, hour_stem]:
        if partner and partner != dm_stem:
            huaqi_wx = _check_tian_gan_he(dm_stem, partner)
            if huaqi_wx:
                return huaqi_wx
    return None


def check_huaqi_ge(dm_stem: str, chart_data: dict) -> dict | None:
    """检测命局是否构成化气格

    条件：
    1. 日干与月干或时干形成天干五合
    2. 化神五行在月令得气（月令本气或藏干与化神同类）
    3. 日主无强根（真化条件）

    返回: {"is_huaqi": True, "huaqi_wuxing": "土", "is_zhen": True} 或 None
    """
    huaqi_wx = _detect_huaqi_wuxing(dm_stem, chart_data)
    if not huaqi_wx:
        return None

    fp = chart_data.get("four_pillars", {})
    month_branch = fp.get("month", {}).get("branch", "")

    # 检查化神是否在月令得气
    month_stems = get_month_stems(month_branch) if month_branch else []
    month_wx = [WUXING_MAP.get(s, "") for s in month_stems]
    if huaqi_wx not in month_wx:
        return None  # 化神不得月令，不构成化气格

    # 检查日主是否有强根（真化vs假化）
    dm_wx = WUXING_MAP.get(dm_stem, "")
    has_strong_root = False
    for pos in ["year", "month", "day", "hour"]:
        for hs in fp.get(pos, {}).get("hidden_stems", []):
            s = hs.get("stem", "") if isinstance(hs, dict) else hs
            w = hs.get("weight", 0.3) if isinstance(hs, dict) else 0.3
            if s and WUXING_MAP.get(s, "") == dm_wx and w >= 0.5:
                has_strong_root = True
                break

    is_zhen = not has_strong_root

    return {
        "is_huaqi": True,
        "huaqi_wuxing": huaqi_wx,
        "is_zhen": is_zhen,
        "pattern": "化气格",
    }


# ------------------------------------------------------------
# 用神变化检测
# ------------------------------------------------------------

def check_yongshen_bianhua(pattern: str, dm_stem: str, chart_data: dict) -> dict:
    """检测用神是否因月令逢冲或透干变化而需变更

    《子平真诠·论用神变化》：
    - 月令逢冲而用神变者，须从他处另寻用神
    - 透干变化：月令藏干透出不同天干则用神不同

    返回: {
        "has_bianhua": bool,
        "reason": "月令逢冲" / "透干变化" / "",
        "new_yongshen": "十神名" or "",
    }
    """
    fp = chart_data.get("four_pillars", {})
    month_branch = fp.get("month", {}).get("branch", "")

    # 1. 月令逢冲 → 用神可能变化
    if _check_yongshen_chong(pattern, chart_data):
        # 月令被冲，另寻透干之物为用
        month_stems = get_month_stems(month_branch) if month_branch else []
        # 优先找月令中气/余气透干
        for i, stem in enumerate(month_stems[1:], 1):  # 跳过本气
            for pos in ["year", "month", "hour"]:
                tg_stem = fp.get(pos, {}).get("stem", "")
                if tg_stem == stem:
                    new_tg = _calc_ten_god(dm_stem, stem)
                    if new_tg and new_tg not in ("比肩", "劫财"):
                        return {
                            "has_bianhua": True,
                            "reason": "月令逢冲",
                            "new_yongshen": new_tg,
                        }
        # 如果中气余气都未透，找四柱中其他透干的官杀/食伤/财星
        for pos in ["year", "month", "hour"]:
            stem = fp.get(pos, {}).get("stem", "")
            if stem and stem != dm_stem:
                tg = _calc_ten_god(dm_stem, stem)
                if tg in ("正官", "七杀", "食神", "伤官", "正财", "偏财",
                          "正印", "偏印"):
                    return {
                        "has_bianhua": True,
                        "reason": "月令逢冲",
                        "new_yongshen": tg,
                    }

    # 2. 透干变化：月令中气/余气透出且力量强于本气
    touchu = detect_ganzhi_touchu(chart_data)
    if touchu and touchu.get("level") in ("中气", "余气") and touchu.get("is_strong"):
        new_tg = touchu.get("touched_ten_god", "")
        if new_tg and new_tg not in ("比肩", "劫财"):
            current_ys = PATTERN_XIANGSHEN_RULES.get(pattern, {}).get("yongshen", "")
            if new_tg != current_ys:
                return {
                    "has_bianhua": True,
                    "reason": "透干变化",
                    "new_yongshen": new_tg,
                }

    return {"has_bianhua": False, "reason": "", "new_yongshen": ""}


# ------------------------------------------------------------
# 加权因子函数（调候/扶抑降级为加权因子）
# ------------------------------------------------------------

# 调候五行矩阵: (日干, 月支) → 首选调候五行
# 基于《穷通宝鉴》十天干十二月令调候用神表
_TIAOHOU_MATRIX = {
    "甲": {"寅": "火", "卯": "火", "辰": "木", "巳": "水", "午": "水", "未": "水",
           "申": "金", "酉": "金", "戌": "木", "亥": "火", "子": "火", "丑": "火"},
    "乙": {"寅": "火", "卯": "火", "辰": "木", "巳": "水", "午": "水", "未": "水",
           "申": "水", "酉": "水", "戌": "木", "亥": "火", "子": "火", "丑": "火"},
    "丙": {"寅": "水", "卯": "水", "辰": "水", "巳": "金", "午": "水", "未": "金",
           "申": "水", "酉": "水", "戌": "木", "亥": "木", "子": "水", "丑": "水"},
    "丁": {"寅": "木", "卯": "木", "辰": "木", "巳": "水", "午": "水", "未": "水",
           "申": "木", "酉": "木", "戌": "木", "亥": "木", "子": "木", "丑": "木"},
    "戊": {"寅": "火", "卯": "火", "辰": "木", "巳": "水", "午": "水", "未": "水",
           "申": "火", "酉": "火", "戌": "木", "亥": "火", "子": "火", "丑": "火"},
    "己": {"寅": "火", "卯": "火", "辰": "木", "巳": "水", "午": "水", "未": "水",
           "申": "火", "酉": "火", "戌": "木", "亥": "火", "子": "火", "丑": "火"},
    "庚": {"寅": "火", "卯": "火", "辰": "木", "巳": "水", "午": "水", "未": "水",
           "申": "火", "酉": "火", "戌": "木", "亥": "火", "子": "火", "丑": "火"},
    "辛": {"寅": "水", "卯": "水", "辰": "木", "巳": "水", "午": "水", "未": "水",
           "申": "水", "酉": "水", "戌": "木", "亥": "火", "子": "火", "丑": "火"},
    "壬": {"寅": "金", "卯": "金", "辰": "木", "巳": "金", "午": "金", "未": "水",
           "申": "木", "酉": "木", "戌": "木", "亥": "火", "子": "火", "丑": "火"},
    "癸": {"寅": "金", "卯": "金", "辰": "木", "巳": "金", "午": "金", "未": "水",
           "申": "金", "酉": "金", "戌": "木", "亥": "火", "子": "火", "丑": "火"},
}


def _get_tiaohou_wuxing(dm_stem: str, month_branch: str) -> str:
    """获取调候五行（基于穷通宝鉴十天干十二月令表）"""
    matrix = _TIAOHOU_MATRIX.get(dm_stem, {})
    return matrix.get(month_branch, "")


def get_tiaohou_weight(dm_stem: str, month_branch: str, candidate: dict) -> int:
    """调候加权因子：返回对候选的加权分（-30 ~ +30）"""
    tiaohou_wx = _get_tiaohou_wuxing(dm_stem, month_branch)
    if not tiaohou_wx:
        return 0

    candidate_wx = candidate.get("five_element", "")
    if candidate_wx == tiaohou_wx:
        return 30
    elif _SHENG.get(candidate_wx, "") == tiaohou_wx or _SHENG.get(tiaohou_wx, "") == candidate_wx:
        return 15
    elif candidate_wx == _KE.get(tiaohou_wx, "") or tiaohou_wx == _KE.get(candidate_wx, ""):
        return -15
    return 0


def get_fuyi_weight(wangshuai_level: str, candidate: dict) -> int:
    """扶抑加权因子：返回对候选的加权分（-20 ~ +20）"""
    if wangshuai_level in ("极旺", "身旺"):
        if candidate.get("ten_god") in ("正官", "七杀", "正财", "偏财", "食神", "伤官"):
            return 20
        else:
            return -10
    elif wangshuai_level in ("极弱", "身弱"):
        if candidate.get("ten_god") in ("正印", "偏印", "比肩", "劫财"):
            return 20
        else:
            return -10
    return 0


# ------------------------------------------------------------
# 格神取运 — 大运喜忌规则表
# 基于《子平真诠》各格局取运章节
# ------------------------------------------------------------

PATTERN_DAYUN_RULES = {
    "正官格": {"xi": ["正财运", "偏财运", "正印运", "偏印运"], "ji": ["伤官运", "七杀运"]},
    "七杀格": {"xi": ["食神运", "正印运", "偏印运"], "ji": ["正财运", "偏财运"]},
    "正财格": {"xi": ["食神运", "伤官运", "正官运"], "ji": ["比肩运", "劫财运"]},
    "偏财格": {"xi": ["食神运", "伤官运", "正官运"], "ji": ["比肩运", "劫财运"]},
    "正印格": {"xi": ["正官运", "七杀运", "比肩运"], "ji": ["正财运", "偏财运"]},
    "偏印格": {"xi": ["偏财运", "正财运"], "ji": ["食神运"]},
    "食神格": {"xi": ["比肩运", "劫财运", "正财运"], "ji": ["偏印运"]},
    "伤官格": {"xi": ["正印运", "偏印运", "偏财运"], "ji": ["正官运"]},
    "建禄格": {"xi": ["正官运", "七杀运", "食神运", "正财运"], "ji": ["比肩运", "劫财运"]},
    "月刃格": {"xi": ["七杀运", "正官运", "食神运"], "ji": ["比肩运", "劫财运"]},
    "从弱格": {"xi": ["七杀运", "正财运", "偏财运", "食神运"], "ji": ["正印运", "偏印运", "比肩运"]},
    "专旺格": {"xi": ["食神运", "伤官运", "正印运"], "ji": ["正官运", "七杀运"]},
    "化气格": {"xi": ["食神运", "正财运", "正印运"], "ji": ["正官运", "七杀运"]},
}


def get_dayun_xiji(pattern: str) -> dict:
    """获取格局的大运喜忌

    返回: {"xi": ["正财运", ...], "ji": ["伤官运", ...]}
    """
    return PATTERN_DAYUN_RULES.get(pattern, {"xi": [], "ji": []})


# ------------------------------------------------------------
# 真从假从判断
# ------------------------------------------------------------

def check_zhen_jia_cong(chart_data: dict) -> dict:
    """判断从弱格/专旺格的真假

    《子平真诠》《滴天髓》任铁樵注：
    - 真从：日主无根无气，完全顺应旺神
    - 假从：日主有微根或印比暗藏，从得不纯

    返回: {"is_zhen": bool, "reason": str}
    """
    dm_stem = _extract_dm_stem(chart_data)
    fp = chart_data.get("four_pillars", {})
    dm_wx = WUXING_MAP.get(dm_stem, "")

    # 检查日主是否有根（本气或中气藏干与日主同类）
    has_root = False
    has_yin_bi = False  # 有印比暗藏

    for pos in ["year", "month", "day", "hour"]:
        for hs in fp.get(pos, {}).get("hidden_stems", []):
            s = hs.get("stem", "") if isinstance(hs, dict) else hs
            w = hs.get("weight", 0.3) if isinstance(hs, dict) else 0.3
            if not s:
                continue
            hs_wx = WUXING_MAP.get(s, "")
            tg = _calc_ten_god(dm_stem, s)
            # 同类五行（比劫根）
            if hs_wx == dm_wx and w >= 0.3:
                has_root = True
            # 印星或比肩劫财暗藏
            if tg in ("正印", "偏印", "比肩", "劫财"):
                has_yin_bi = True

    # 也检查天干
    for pos in ["year", "month", "hour"]:
        stem = fp.get(pos, {}).get("stem", "")
        if stem:
            tg = _calc_ten_god(dm_stem, stem)
            if tg in ("正印", "偏印", "比肩", "劫财"):
                has_yin_bi = True

    if not has_root and not has_yin_bi:
        return {"is_zhen": True, "reason": "日主无根无印比，真从"}
    elif has_root:
        return {"is_zhen": False, "reason": "日主有根，假从"}
    else:
        return {"is_zhen": False, "reason": "日主有印比暗藏，假从不纯"}


# ------------------------------------------------------------
# 格局高低评判（在用神+成败救应之后）
# ------------------------------------------------------------

def _calc_youqing_score(pattern: str, yongshen: dict, xiangshen: dict, chart_data: dict) -> int:
    """计算有情分数 (0-4)"""
    score = 0
    dm_stem = _extract_dm_stem(chart_data)
    fp = chart_data.get("four_pillars", {})

    ys_tg = yongshen.get("ten_god", "")
    ys_wx = yongshen.get("five_element", "")

    # Q-01: 用神贴近日主（日支、月干、时干）
    day_branch = fp.get("day", {}).get("branch", "")
    month_stem = fp.get("month", {}).get("stem", "")
    hour_stem = fp.get("hour", {}).get("stem", "")
    near_positions = []
    if month_stem:
        near_positions.append(_calc_ten_god(dm_stem, month_stem))
    if hour_stem:
        near_positions.append(_calc_ten_god(dm_stem, hour_stem))
    # 日支藏干
    for hs in fp.get("day", {}).get("hidden_stems", []):
        s = hs.get("stem", "") if isinstance(hs, dict) else hs
        if s:
            near_positions.append(_calc_ten_god(dm_stem, s))
    if ys_tg in near_positions:
        score += 1

    # Q-02: 用神不被天干五合（日主自合不为合去）
    if not _check_yongshen_be_he(pattern, dm_stem, chart_data):
        score += 1

    # Q-04: 相神配置齐全
    if xiangshen and xiangshen.get("exists_in_chart"):
        score += 1

    # Q-06: 五行流通（相神→用神→日主形成相生）
    if xiangshen and xiangshen.get("exists_in_chart"):
        xs_wx = xiangshen.get("five_element", "")
        dm_wx = WUXING_MAP.get(dm_stem, "")
        # 相神生用神 或 用神生日主
        if _SHENG.get(xs_wx, "") == ys_wx or _SHENG.get(ys_wx, "") == dm_wx:
            score += 1

    return score


def _calc_youli_score(pattern: str, yongshen: dict, xiangshen: dict, chart_data: dict) -> int:
    """计算有力分数 (0-4)"""
    score = 0
    dm_stem = _extract_dm_stem(chart_data)
    fp = chart_data.get("four_pillars", {})

    ys_tg = yongshen.get("ten_god", "")

    # L-01: 用神得月令（月令本气即用神，格局法中默认满足）
    score += 1

    # L-02 + L-03: 用神有根 + 透干
    exists, has_root, touches = _check_shen_status(ys_tg, chart_data)
    if touches:
        score += 1
    if has_root:
        score += 1

    # L-05: 用神有生源（相神存在且是生用神的角色）
    if xiangshen and xiangshen.get("exists_in_chart"):
        role = xiangshen.get("gong_way", "")
        if "生" in role or "护" in role:
            score += 1

    return score


def judge_pattern_quality_v2(
    pattern: str, yongshen: dict, xiangshen: dict,
    chengbai: dict, jiuying: dict, chart_data: dict
) -> str:
    """格局高低评判（在用神+成败救应之后）

    返回: "上格" / "中格" / "中下格" / "下格"
    """
    # 败格无救 → 下格
    if chengbai.get("is_defeated") and not jiuying.get("has_jiuying", False):
        return "下格"

    youqing_score = _calc_youqing_score(pattern, yongshen, xiangshen, chart_data)
    youli_score = _calc_youli_score(pattern, yongshen, xiangshen, chart_data)

    # 败格有救 → 根据救应等级
    if chengbai.get("is_defeated") and jiuying.get("has_jiuying"):
        level = jiuying.get("jiuying_level", "无")
        if level == "上等":
            return "中格"
        elif level == "中等":
            return "中下格"
        else:
            return "下格"

    # 无败因 → 按有情有力评判
    if youqing_score >= 3 and youli_score >= 3:
        return "上格"
    elif youqing_score >= 2 and youli_score >= 2:
        return "中格"
    elif youqing_score >= 1 or youli_score >= 1:
        return "中下格"
    else:
        return "下格"


# ============================================================
# 化气格五要素验证表
# 基于《子平真诠·论十干配合性情》
# ============================================================

HUAHUAGE_CONDITIONS = {
    "戊癸合火": {
        "合化天干": ("戊", "癸"),
        "化神五行": "火",
        "化神当令（月令）": ["巳", "午", "寅", "戌"],
        "透干条件": "戊或癸透于月干或时干，日干参与合化",
        "通根条件": "化神火在月支有本气或中气根",
        "无克破条件": "无水（壬癸）强力克化神火",
        "真化标志": "日主无强根（无本气根）",
        "source": "《子平真诠·论十干配合性情》",
    },
    "甲己合化土": {
        "合化天干": ("甲", "己"),
        "化神五行": "土",
        "化神当令（月令）": ["辰", "戌", "丑", "未", "巳", "午"],
        "透干条件": "甲或己透于月干或时干，日干参与合化",
        "通根条件": "化神土在月支有本气或中气根",
        "无克破条件": "无木（甲乙）强力克化神土",
        "真化标志": "日主无强根（无本气根）",
        "source": "《子平真诠·论十干配合性情》",
    },
    "乙庚合化金": {
        "合化天干": ("乙", "庚"),
        "化神五行": "金",
        "化神当令（月令）": ["申", "酉", "戌", "丑"],
        "透干条件": "乙或庚透于月干或时干，日干参与合化",
        "通根条件": "化神金在月支有本气或中气根",
        "无克破条件": "无火（丙丁）强力克化神金",
        "真化标志": "日主无强根（无本气根）",
        "source": "《子平真诠·论十干配合性情》",
    },
    "丙辛合化水": {
        "合化天干": ("丙", "辛"),
        "化神五行": "水",
        "化神当令（月令）": ["亥", "子", "申", "辰"],
        "透干条件": "丙或辛透于月干或时干，日干参与合化",
        "通根条件": "化神水在月支有本气或中气根",
        "无克破条件": "无土（戊己）强力克化神水",
        "真化标志": "日主无强根（无本气根）",
        "source": "《子平真诠·论十干配合性情》",
    },
    "丁壬合化木": {
        "合化天干": ("丁", "壬"),
        "化神五行": "木",
        "化神当令（月令）": ["寅", "卯", "亥", "未"],
        "透干条件": "丁或壬透于月干或时干，日干参与合化",
        "通根条件": "化神木在月支有本气或中气根",
        "无克破条件": "无金（庚辛）强力克化神木",
        "真化标志": "日主无强根（无本气根）",
        "source": "《子平真诠·论十干配合性情》",
    },
}

# ============================================================
# 增强版从格检测
# ============================================================

def check_congge_detailed(chart_data: dict, dm_stem: str) -> dict:
    """详细从格判断（增强版）

    假从三要素量化：
    1. 根浅力薄：仅余气通根（非本气/中气）
    2. 生扶＜20%：全局比劫印绶力量 < 20%
    3. 自顾不暇：虽有劫印，但被克/被泄/被合

    《滴天髓·从化》：
    '真从之象有几人，假从亦可发其身'

    Args:
        chart_data: 排盘数据（含 four_pillars）
        dm_stem: 日主天干

    Returns:
        {
            "is_congge": bool,
            "cong_type": "真从"|"假从"|"非从",
            "cong_subtype": "从杀"|"从财"|"从儿"|"从强"|...,
            "root_detail": {...},
            "support_ratio": float,
            "restricted_support": bool,
            "detail": str,
            "classical_source": str,
        }
    """
    dm_wx = WUXING_MAP.get(dm_stem, "")
    fp = chart_data.get("four_pillars", {})

    # === 1. 根气量化 ===
    root_detail = _quantify_roots_detailed(dm_wx, fp)
    has_benzhi_root = root_detail["has_benzhi_root"]
    has_zhongqi_root = root_detail["has_zhongqi_root"]
    has_yuqi_root = root_detail["has_yuqi_root"]
    total_root_weight = root_detail["total_weight"]

    # === 2. 全局生扶力量占比 ===
    bi_jie_yin_force = _calc_support_force_detailed(dm_wx, fp, dm_stem)
    total_force = _calc_total_force_detailed(dm_wx, fp)
    support_ratio = bi_jie_yin_force / max(total_force, 1)

    # === 3. 比劫印绶"自顾不暇"检查 ===
    restricted_support = _check_restricted_support_detailed(dm_wx, fp, dm_stem)

    # === 从格类型判定 ===
    if total_root_weight == 0 and support_ratio < 0.10:
        cong_type = "真从"
        cong_subtype = _determine_cong_subtype_detailed(fp, dm_stem)
        detail = "日主无根无气，全局无生扶，真从"
    elif (has_yuqi_root or total_root_weight < 0.3) and support_ratio < 0.20:
        cong_type = "假从"
        cong_subtype = _determine_cong_subtype_detailed(fp, dm_stem)
        if restricted_support:
            detail = (
                f"日主根浅力薄（根重{total_root_weight}），"
                "劫印自顾不暇，假从"
            )
        else:
            detail = (
                f"日主有微根（根重{total_root_weight}），"
                f"但印比力量不足（占比{support_ratio:.0%}），假从"
            )
    elif support_ratio < 0.15 and restricted_support:
        cong_type = "假从"
        cong_subtype = _determine_cong_subtype_detailed(fp, dm_stem)
        detail = "日主虽略有根气，但劫印自顾不暇，从局成立"
    else:
        cong_type = "非从"
        cong_subtype = ""
        detail = (
            f"不满足从格条件"
            f"（根重{total_root_weight}，"
            f"印比占比{support_ratio:.0%}）"
        )

    return {
        "is_congge": cong_type in ("真从", "假从"),
        "cong_type": cong_type,
        "cong_subtype": cong_subtype,
        "root_detail": root_detail,
        "support_ratio": round(support_ratio, 2),
        "restricted_support": restricted_support,
        "detail": detail,
        "classical_source": (
            "《滴天髓·从化》：'真从之象有几人，假从亦可发其身'"
        ),
    }


def _quantify_roots_detailed(dm_wx: str, fp: dict) -> dict:
    """量化日主在各柱藏干中的根气"""
    has_benzhi = False
    has_zhongqi = False
    has_yuqi = False
    total = 0.0

    for pos in ["year", "month", "day", "hour"]:
        for hs in fp.get(pos, {}).get("hidden_stems", []):
            s = hs.get("stem", "") if isinstance(hs, dict) else hs
            w = hs.get("weight", 0.0) if isinstance(hs, dict) else 0.3
            if WUXING_MAP.get(s, "") == dm_wx:
                total += w
                if w >= 0.5:
                    has_benzhi = True
                elif w >= 0.3:
                    has_zhongqi = True
                else:
                    has_yuqi = True

    return {
        "has_benzhi_root": has_benzhi,
        "has_zhongqi_root": has_zhongqi,
        "has_yuqi_root": has_yuqi,
        "total_weight": round(total, 1),
    }


def _calc_support_force_detailed(dm_wx: str, fp: dict, dm_stem: str) -> float:
    """计算全局生扶力量（印比总和）"""
    force = 0.0

    # 天干权重
    for pos in ["year", "month", "day", "hour"]:
        stem = fp.get(pos, {}).get("stem", "")
        if not stem or stem == dm_stem:
            continue
        tg = _calc_ten_god(dm_stem, stem)
        if tg in ("正印", "偏印", "比肩", "劫财"):
            force += 1.5

    # 地支藏干权重
    for pos in ["year", "month", "day", "hour"]:
        for hs in fp.get(pos, {}).get("hidden_stems", []):
            s = hs.get("stem", "") if isinstance(hs, dict) else hs
            w = hs.get("weight", 0.3) if isinstance(hs, dict) else 0.3
            if s:
                tg = _calc_ten_god(dm_stem, s)
                if tg in ("正印", "偏印", "比肩", "劫财") and s != dm_stem:
                    force += w

    return force


def _calc_total_force_detailed(dm_wx: str, fp: dict) -> float:
    """计算全局十神力量总和"""
    dm_stem = _extract_dm_stem({"four_pillars": fp, "day_master": ""})
    if not dm_stem:
        # 从fp推断日主天干
        day_stem = fp.get("day", {}).get("stem", "")
        if day_stem:
            dm_stem = day_stem
        else:
            dm_stem = "甲"  # fallback

    force = 0.0

    # 天干权重
    for pos in ["year", "month", "day", "hour"]:
        stem = fp.get(pos, {}).get("stem", "")
        if stem:
            force += 1.5

    # 地支藏干权重
    for pos in ["year", "month", "day", "hour"]:
        for hs in fp.get(pos, {}).get("hidden_stems", []):
            w = hs.get("weight", 0.3) if isinstance(hs, dict) else 0.3
            force += w

    return max(force, 1.0)


def _check_restricted_support_detailed(dm_wx: str, fp: dict, dm_stem: str) -> bool:
    """检查比劫印绶是否'自顾不暇'（被克/被泄/被合）

    如果生扶日主的印比被克制或泄气，则它们自身难保，
    无力有效生扶日主——这是假从的重要条件。
    """
    # 收集所有印比十神对应的天干
    support_stems = []
    for pos in ["year", "month", "hour"]:
        stem = fp.get(pos, {}).get("stem", "")
        if stem:
            tg = _calc_ten_god(dm_stem, stem)
            if tg in ("正印", "偏印", "比肩", "劫财") and stem != dm_stem:
                support_stems.append((stem, tg, pos))

    if not support_stems:
        return True  # 无支持力量 = 自顾不暇

    # 检查每个支持力量是否被克
    restricted_count = 0
    for s_stem, s_tg, s_pos in support_stems:
        s_wx = WUXING_MAP.get(s_stem, "")

        # 是否被克
        ke_wx = _KE.get(s_wx, "")  # 克s_wx的五行
        if ke_wx:
            for pos in ["year", "month", "hour"]:
                if pos == s_pos:
                    continue
                other_stem = fp.get(pos, {}).get("stem", "")
                if other_stem and WUXING_MAP.get(other_stem, "") == ke_wx:
                    restricted_count += 1
                    break

    # 超过一半的支持力量被限制 → 自顾不暇
    return restricted_count >= len(support_stems) / 2


def _determine_cong_subtype_detailed(fp: dict, dm_stem: str) -> str:
    """确定从格子类型：从杀/从财/从儿/从强"""
    tg_counts = {}
    for pos in ["year", "month", "day", "hour"]:
        stem = fp.get(pos, {}).get("stem", "")
        if stem and stem != dm_stem:
            tg = _calc_ten_god(dm_stem, stem)
            tg_counts[tg] = tg_counts.get(tg, 0) + 1
        for hs in fp.get(pos, {}).get("hidden_stems", []):
            s = hs.get("stem", "") if isinstance(hs, dict) else hs
            w = hs.get("weight", 0.3) if isinstance(hs, dict) else 0.3
            if s and s != dm_stem:
                tg = _calc_ten_god(dm_stem, s)
                tg_counts[tg] = tg_counts.get(tg, 0) + w

    priority_order = ["七杀", "正官", "正财", "偏财", "食神", "伤官"]
    best_tg = ""
    best_score = 0
    for tg in priority_order:
        score = tg_counts.get(tg, 0)
        if score > best_score:
            best_score = score
            best_tg = tg

    subtype_map = {
        "七杀": "从杀", "正官": "从杀",
        "正财": "从财", "偏财": "从财",
        "食神": "从儿", "伤官": "从儿",
    }
    return subtype_map.get(best_tg, "从弱")


# ============================================================
# 化气格五要素验证
# ============================================================

def check_huaqi_ge_5elements(dm_stem: str, chart_data: dict) -> dict:
    """化气格五要素完整验证

    五要素：
    1. 合化：日干与月干/时干形成天干五合
    2. 当令：化神五行在月令得气（月令本气或藏干与化神同类）
    3. 透干：化神五行在天干透出
    4. 通根：化神五行在地支有根（本气或中气）
    5. 无克破：化神五行不被强力克制

    五要素全满足 → 真化（is_zhen=True）
    要素不全部满足 → condition_met列表记录，is_zhen=False

    Args:
        dm_stem: 日主天干
        chart_data: 排盘数据

    Returns:
        {
            "is_huaqi": bool,
            "score": int,  # 满足条件数 0-5
            "conditions_met": [...],
            "conditions_missing": [...],
            "is_zhen": bool,
            "huaqi_wuxing": str,
            "detail": str,
            "classical_source": str,
        }
    """
    from rules.pattern import _check_tian_gan_he

    fp = chart_data.get("four_pillars", {})
    month_stem = fp.get("month", {}).get("stem", "")
    hour_stem = fp.get("hour", {}).get("stem", "")
    month_branch = fp.get("month", {}).get("branch", "")

    conditions_met = []
    conditions_missing = []
    huaqi_wx = ""

    # === 要素1：合化 ===
    has_he = False
    for partner in [month_stem, hour_stem]:
        if partner and partner != dm_stem:
            hw = _TIAN_GAN_HE.get((dm_stem, partner))
            if hw:
                huaqi_wx = hw
                has_he = True
                conditions_met.append("要素1: 合化成立")
                break

    if not has_he:
        return {
            "is_huaqi": False,
            "score": 0,
            "conditions_met": [],
            "conditions_missing": ["要素1: 日干未与月干/时干五合"],
            "is_zhen": False,
            "huaqi_wuxing": "",
            "detail": "日干未参与天干五合，不构成化气格",
            "classical_source": "《子平真诠·论十干配合性情》",
        }

    # === 要素2：化神当令 ===
    if huaqi_wx and month_branch:
        month_stems_list = get_month_stems(month_branch)
        month_wx_list = [WUXING_MAP.get(s, "") for s in month_stems_list]
        if huaqi_wx in month_wx_list:
            conditions_met.append("要素2: 化神当令（月令得气）")
        else:
            conditions_missing.append(
                f"要素2: 化神{huaqi_wx}不在月令{month_branch}当令"
            )

    # === 要素3：透干 ===
    has_tougan = False
    for pos in ["year", "month", "day", "hour"]:
        stem = fp.get(pos, {}).get("stem", "")
        if stem and WUXING_MAP.get(stem, "") == huaqi_wx:
            has_tougan = True
            break
    if has_tougan:
        conditions_met.append("要素3: 化神透干")
    else:
        conditions_missing.append("要素3: 化神未透干")

    # === 要素4：通根 ===
    has_tonggen = False
    for pos in ["year", "month", "day", "hour"]:
        branch = fp.get(pos, {}).get("branch", "")
        if branch and WUXING_MAP.get(branch, "") == huaqi_wx:
            has_tonggen = True
            break
        # 也检查藏干
        for hs in fp.get(pos, {}).get("hidden_stems", []):
            s = hs.get("stem", "") if isinstance(hs, dict) else hs
            w = hs.get("weight", 0.3) if isinstance(hs, dict) else 0.3
            if s and WUXING_MAP.get(s, "") == huaqi_wx and w >= 0.3:
                has_tonggen = True
                break
        if has_tonggen:
            break
    if has_tonggen:
        conditions_met.append("要素4: 化神通根")
    else:
        conditions_missing.append("要素4: 化神未通根")

    # === 要素5：无克破 ===
    ke_wx = _KE.get(huaqi_wx, "")
    has_kepo = False
    if ke_wx:
        for pos in ["year", "month", "day", "hour"]:
            stem = fp.get(pos, {}).get("stem", "")
            # 排除日主和合化伙伴（合化伙伴本身是化气格的参与者）
            if stem and WUXING_MAP.get(stem, "") == ke_wx and stem != dm_stem:
                # 检查是否是合化伙伴
                is_partner = False
                for partner in [month_stem, hour_stem]:
                    if partner and partner != dm_stem:
                        hw = _TIAN_GAN_HE.get((dm_stem, partner))
                        if hw and stem == partner:
                            is_partner = True
                            break
                if not is_partner:
                    has_kepo = True
                    conditions_missing.append(
                        f"要素5: 化神被{ke_wx}（{stem}）克制"
                    )
                    break
            # 检查地支
            branch = fp.get(pos, {}).get("branch", "")
            if branch and WUXING_MAP.get(branch, "") == ke_wx:
                has_kepo = True
                conditions_missing.append(
                    f"要素5: 化神被{ke_wx}克制（地支{branch}）"
                )
                break
    if not has_kepo:
        conditions_met.append("要素5: 化神无克破")

    score = len(conditions_met)
    is_zhen = score == 5

    return {
        "is_huaqi": score >= 3,  # 至少3个条件满足才视为有化气倾向
        "score": score,
        "conditions_met": conditions_met,
        "conditions_missing": conditions_missing,
        "is_zhen": is_zhen,
        "huaqi_wuxing": huaqi_wx,
        "detail": f"化气格五要素验证：{score}/5 满足",
        "classical_source": "《子平真诠·论十干配合性情》",
    }
