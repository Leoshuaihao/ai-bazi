"""六亲双轨交叉证伪法 — V2 核心模块

理论依据：
- 《子平真诠·论六亲》"以十神定其本，以宫位明其位，以旺衰判其力。三者合参，六亲之事可推矣。"
- V2 报告 §3.2：十神定性 + 宫位定位双轨交叉证伪
- V2 报告 §3.4：六亲与大运联合证伪

纯规则引擎，不依赖 AI/HTTP/DB。

暴露接口：
- assess_liuqin(chart_data, pattern, yongshen) → LiuqinAssessment
- generate_liuqin_question(item, six_kin_type) → QuestionV2
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal, Optional

from rules.pattern import _calc_ten_god, determine_yongshen, WUXING_MAP
from rules.wuxing import WUXING_MAP as WX_MAP_EXT, HIDDEN_STEMS_MAP

# ============================================================
# 数据类
# ============================================================

@dataclass
class LiuqinItem:
    """单类六亲的双轨评估结果。

    V2-3.2: 双轨一致 → consistency="confirmed"
            双轨矛盾 → consistency="contradictory"（降级为推测性结论）
    """
    ten_god_dim: Literal["吉", "凶", "平"]      # 十神维度判断
    gongwei_dim: Literal["吉", "凶", "平"]       # 宫位维度判断
    consistency: Literal["confirmed", "tentative", "contradictory"]
    confidence: float                            # [0.0, 1.0]
    detail: dict = field(default_factory=dict)   # 详细得分字典


@dataclass
class LiuqinAssessment:
    """六亲双轨评估完整结果。

    V2-3.2: 四条六亲（父母、兄弟、配偶、子女）各自独立评估。
    """
    parents: LiuqinItem
    siblings: LiuqinItem
    spouse: LiuqinItem
    children: LiuqinItem


@dataclass
class QuestionV2:
    """V2 验证问题格式。

    V2-4.1: 包含 D(q) 鉴别力分数、targets 字典、问题骨架。
    """
    id: str
    category: str                               # "六亲存亡" | "六亲关系" | "大运事件" | ...
    question_text: str
    options: list[str] = field(default_factory=lambda: ["是", "不是", "记不清了"])
    dq_score: float = 0.0                       # 鉴别力分数 D(q)
    targets: dict = field(default_factory=dict)  # 该问题旨在验证的参数
    skeleton: Optional[dict] = None              # AI 出题骨架
    classical_reference: Optional[str] = None    # 典籍引用（由调用方注入）

    def model_dump(self) -> dict:
        return {
            "id": self.id,
            "category": self.category,
            "question_text": self.question_text,
            "options": self.options,
            "dq_score": self.dq_score,
            "targets": self.targets,
            "skeleton": self.skeleton,
            "classical_reference": self.classical_reference,
        }


# ============================================================
# 常量：十神配六亲映射
# ============================================================

SIX_KIN_TO_TEN_GOD: dict[str, str] = {
    "mother":     "正印",   # 《子平真诠·论六亲》"正印为母"
    "father":     "偏财",   # "偏财为父"
    "wife":       "正财",   # "我克者为财星，乃妻妾"（男命）
    "husband":    "正官",   # "克我者为官星，乃夫"（女命）
    "son":        "七杀",   # 男命以七杀为子
    "daughter":   "正官",   # 男命以正官为女
    "brother":    "比肩",   # "比肩为同性之兄弟"
    "sister":     "劫财",   # "劫财为异性之兄弟"
}

# 六亲 → 主宫位映射 (V2-3.2)
SIX_KIN_TO_PILLAR: dict[str, str] = {
    "mother":   "month",   # 母居月柱（父母兄弟宫）
    "father":   "month",   # 父居月柱
    "wife":     "day",     # 日支夫妻宫
    "husband":  "day",     # 日支夫妻宫
    "son":      "hour",    # 时柱子女宫
    "daughter": "hour",    # 时柱子女宫
    "brother":  "month",   # 月柱父母兄弟宫
    "sister":   "month",   # 月柱父母兄弟宫
}

# 十神五行推算（基于日主五行）
# 十神 → (我克/克我/生我/我生/同我的方向, 阴阳关系)
_TEN_GOD_DIRECTION: dict[str, tuple[str, bool]] = {
    "正官": ("克我", True),  "七杀": ("克我", False),
    "正印": ("生我", True),  "偏印": ("生我", False),
    "食神": ("我生", True),  "伤官": ("我生", False),
    "正财": ("我克", True),  "偏财": ("我克", False),
    "比肩": ("同我", True),  "劫财": ("同我", False),
}

# ============================================================
# 双轨一致性判定矩阵 (V2-3.2 / V2 算法 §11.4)
# ============================================================

CONSISTENCY_MATRIX: dict[tuple[str, str], tuple[str, float]] = {
    # (ten_god_result, gongwei_result) → (consistency_level, confidence)
    ("吉", "吉"): ("confirmed",      0.85),
    ("吉", "平"): ("tentative",      0.60),
    ("吉", "凶"): ("contradictory",  0.35),
    ("平", "吉"): ("tentative",      0.55),
    ("平", "平"): ("tentative",      0.50),
    ("平", "凶"): ("tentative",      0.40),
    ("凶", "吉"): ("contradictory",  0.35),
    ("凶", "平"): ("tentative",      0.40),
    ("凶", "凶"): ("confirmed",      0.85),
}

# 地支六冲
_BRANCH_CHONG: dict[str, str] = {
    "子": "午", "午": "子", "丑": "未", "未": "丑",
    "寅": "申", "申": "寅", "卯": "酉", "酉": "卯",
    "辰": "戌", "戌": "辰", "巳": "亥", "亥": "巳",
}

# 地支相刑
_BRANCH_XING = {
    ("寅", "巳"), ("巳", "申"), ("申", "寅"),
    ("丑", "戌"), ("戌", "未"), ("未", "丑"),
    ("子", "卯"), ("卯", "子"),
}

# 地支相害
_BRANCH_HAI: dict[str, str] = {
    "子": "未", "未": "子", "丑": "午", "午": "丑",
    "寅": "巳", "巳": "寅", "卯": "辰", "辰": "卯",
    "申": "亥", "亥": "申", "酉": "戌", "戌": "酉",
}

# ============================================================
# 核心函数：assess_liuqin()
# ============================================================

def assess_liuqin(
    chart_data: dict,
    pattern: str,
    yongshen: dict,
) -> LiuqinAssessment:
    """六亲双轨评估主函数。

    V2-3.2: 对父母/兄弟/配偶/子女分别执行十神维度+宫位维度双轨评估，
    通过一致性判定矩阵合成最终结论。

    Args:
        chart_data: 排盘数据 {day_master, four_pillars, gender, ...}
        pattern: 格局类型（如"正官格"）
        yongshen: 用神 {"ten_god": str, "five_element": str, "mode": str}

    Returns:
        LiuqinAssessment: 四条六亲的完整评估
    """
    gender = chart_data.get("gender", "男")

    # === 父母评估 ===
    mother_tg, mother_detail = _score_ten_god(
        chart_data, "mother", gender, pattern, yongshen
    )
    father_tg, father_detail = _score_ten_god(
        chart_data, "father", gender, pattern, yongshen
    )
    parents_gw, parents_gw_detail = _score_gongwei(chart_data, "father")

    # 父母十神取较凶者
    parents_tg = _merge_parents_ten_god(mother_tg, father_tg)
    parents_cons, parents_conf = CONSISTENCY_MATRIX[(parents_tg, parents_gw)]

    # === 兄弟评估 ===
    sibling_tg, sibling_tg_detail = _score_ten_god(
        chart_data, "brother", gender, pattern, yongshen
    )
    sibling_gw, sibling_gw_detail = _score_gongwei(chart_data, "brother")
    sibling_cons, sibling_conf = CONSISTENCY_MATRIX[(sibling_tg, sibling_gw)]

    # === 配偶评估 ===
    spouse_kin = "wife" if gender == "男" else "husband"
    spouse_tg, spouse_tg_detail = _score_ten_god(
        chart_data, spouse_kin, gender, pattern, yongshen
    )
    spouse_gw, spouse_gw_detail = _score_gongwei(chart_data, spouse_kin)
    spouse_cons, spouse_conf = CONSISTENCY_MATRIX[(spouse_tg, spouse_gw)]

    # === 子女评估 ===
    child_kin = "son" if gender == "男" else "daughter"
    child_tg, child_tg_detail = _score_ten_god(
        chart_data, child_kin, gender, pattern, yongshen
    )
    child_gw, child_gw_detail = _score_gongwei(chart_data, child_kin)
    child_cons, child_conf = CONSISTENCY_MATRIX[(child_tg, child_gw)]

    return LiuqinAssessment(
        parents=LiuqinItem(
            ten_god_dim=parents_tg,
            gongwei_dim=parents_gw,
            consistency=parents_cons,
            confidence=parents_conf,
            detail={
                "mother_ten_god": mother_detail,
                "father_ten_god": father_detail,
                "gongwei": parents_gw_detail,
            },
        ),
        siblings=LiuqinItem(
            ten_god_dim=sibling_tg,
            gongwei_dim=sibling_gw,
            consistency=sibling_cons,
            confidence=sibling_conf,
            detail={
                "ten_god": sibling_tg_detail,
                "gongwei": sibling_gw_detail,
            },
        ),
        spouse=LiuqinItem(
            ten_god_dim=spouse_tg,
            gongwei_dim=spouse_gw,
            consistency=spouse_cons,
            confidence=spouse_conf,
            detail={
                "ten_god": spouse_tg_detail,
                "gongwei": spouse_gw_detail,
            },
        ),
        children=LiuqinItem(
            ten_god_dim=child_tg,
            gongwei_dim=child_gw,
            consistency=child_cons,
            confidence=child_conf,
            detail={
                "ten_god": child_tg_detail,
                "gongwei": child_gw_detail,
            },
        ),
    )


# ============================================================
# 十神维度打分 (V2 算法 §11.2)
# ============================================================

def _score_ten_god(
    chart_data: dict,
    six_kin_type: str,
    gender: str,
    pattern: str,
    yongshen: dict,
) -> tuple[Literal["吉", "凶", "平"], dict]:
    """十神维度打分。

    V2-2.1 Step 4 + V2-3.2:
    1. 确定六亲对应十神
    2. 检查十神在四柱中的出现情况
    3. 评估十神旺衰（得令/得地/得生/得助）
    4. 判断十神喜忌（用神/喜神/忌神/闲神）
    5. 综合判定吉/凶/平
    """
    ten_god = SIX_KIN_TO_TEN_GOD.get(six_kin_type, "")
    if not ten_god:
        return ("平", {"error": f"未知六亲类型: {six_kin_type}"})

    # Step 1-2: 查找十神出现位置
    occurrences = _find_ten_god_occurrences(chart_data, ten_god)

    # Step 3: 评估旺衰
    wangshuai_score = _evaluate_ten_god_wangshuai(occurrences, chart_data, ten_god)

    # Step 4: 判断喜忌
    xiji = _determine_ten_god_xiji(ten_god, yongshen)

    detail = {
        "六亲": six_kin_type,
        "十神": ten_god,
        "出现位置": [occ["pillar"] for occ in occurrences],
        "旺衰分数": round(wangshuai_score, 2),
        "喜忌": xiji,
        "透干": any(occ["is_stem"] for occ in occurrences),
        "通根": any(occ["is_rooted"] for occ in occurrences),
    }

    is_controlled = _check_ten_god_controlled(occurrences, chart_data)

    # 规则 1: 用神/喜神 + 旺相 → 吉
    if xiji in ("用神", "喜神") and wangshuai_score >= 0.6:
        return ("吉", detail)

    # 规则 2: 忌神 + 旺相且无制 → 凶
    if xiji == "忌神" and wangshuai_score >= 0.6 and not is_controlled:
        return ("凶", detail)

    # 规则 3: 忌神 + 受制或弱 → 平
    if xiji == "忌神" and (wangshuai_score < 0.4 or is_controlled):
        return ("平", detail)

    # 规则 4: 用神/喜神 + 弱或受克 → 凶（用神无力）
    if xiji in ("用神", "喜神") and wangshuai_score < 0.4:
        return ("凶", detail)

    # 规则 5: 十神虚浮无根
    if not detail["通根"] and detail["透干"]:
        detail["虚浮警告"] = True
        return ("平", detail)

    # 规则 6: 缺位
    if len(occurrences) == 0:
        return ("平", detail)

    return ("平", detail)


def _find_ten_god_occurrences(chart_data: dict, target_ten_god: str) -> list[dict]:
    """查找指定十神在四柱中出现的位置。

    Returns:
        [{"pillar": "year", "is_stem": True, "is_rooted": False, ...}, ...]
    """
    occurrences = []
    day_master = chart_data.get("day_master", "")
    pillars = chart_data.get("four_pillars", {})

    for pos in ["year", "month", "day", "hour"]:
        pillar = pillars.get(pos, {})
        stem = pillar.get("stem", "")
        branch = pillar.get("branch", "")

        # 天干
        if stem:
            tg = _calc_ten_god(day_master, stem)
            if tg == target_ten_god:
                occurrences.append({
                    "pillar": pos,
                    "is_stem": True,
                    "is_rooted": False,
                    "stem_or_branch": stem,
                    "ten_god": tg,
                })

        # 地支藏干
        hidden = pillar.get("hidden_stems", [])
        for hs in hidden:
            hs_stem = hs.get("stem", "")
            if hs_stem:
                tg = _calc_ten_god(day_master, hs_stem)
                if tg == target_ten_god:
                    # 地支本气有根
                    is_rooted = (hs == hidden[0]) if hidden else False
                    occurrences.append({
                        "pillar": pos,
                        "is_stem": False,
                        "is_rooted": is_rooted,
                        "stem_or_branch": hs_stem,
                        "ten_god": tg,
                        "branch": branch,
                    })

    return occurrences


def _evaluate_ten_god_wangshuai(
    occurrences: list[dict],
    chart_data: dict,
    ten_god: str,
) -> float:
    """四要素旺衰评估 (V2-2.1)。

    得令(w=0.35) + 得地(w=0.30) + 得生(w=0.20) + 得助(w=0.15)
    """
    score = 0.0
    if not occurrences:
        return 0.0

    # 得令：月令是否生助十神五行
    month_branch = chart_data.get("four_pillars", {}).get("month", {}).get("branch", "")
    ten_god_wuxing = _resolve_ten_god_wuxing(chart_data.get("day_master", ""), ten_god)
    if _branch_supports_wuxing(month_branch, ten_god_wuxing):
        score += 0.35

    # 得地：地支是否有根
    if any(occ.get("is_rooted") for occ in occurrences):
        score += 0.30

    # 得生：是否有印星生助
    if _has_yin_support(chart_data, ten_god_wuxing):
        score += 0.20

    # 得助：是否有同类十神比助
    if len(occurrences) >= 2:
        score += 0.15

    return min(score, 1.0)


def _resolve_ten_god_wuxing(day_master: str, ten_god: str) -> str:
    """从日主和十神反推十神对应的五行。"""
    dm_wx = WUXING_MAP.get(day_master, "土")
    direction, _ = _TEN_GOD_DIRECTION.get(ten_god, ("同我", True))

    from rules.wuxing import get_sheng, get_ke, get_i_sheng, get_i_ke

    if direction == "克我":
        return get_ke(dm_wx)
    elif direction == "生我":
        return get_sheng(dm_wx)
    elif direction == "我生":
        return get_i_sheng(dm_wx)
    elif direction == "我克":
        return get_i_ke(dm_wx)
    else:  # 同我
        return dm_wx


def _branch_supports_wuxing(branch: str, wuxing: str) -> bool:
    """地支是否支持该五行（月令生助判断）。"""
    branch_wx = WUXING_MAP.get(branch, "")
    if not branch_wx:
        # 地支不在基本五行表中，查藏干本气
        hidden = HIDDEN_STEMS_MAP.get(branch, [])
        if hidden:
            branch_wx = WUXING_MAP.get(hidden[0].get("stem", ""), "")
    if not branch_wx or not wuxing:
        return False

    from rules.wuxing import get_sheng
    # 地支五行 == 十神五行 或 生十神五行
    return branch_wx == wuxing or get_sheng(branch_wx) == wuxing


def _has_yin_support(chart_data: dict, wuxing: str) -> bool:
    """检查天干中是否有印星生助该五行。"""
    # 印星 = 生该五行的五行
    from rules.wuxing import get_sheng
    yin_wx = get_sheng(wuxing)
    if not yin_wx:
        return False

    for pos in ["year", "month", "day", "hour"]:
        stem = chart_data.get("four_pillars", {}).get(pos, {}).get("stem", "")
        if WUXING_MAP.get(stem, "") == yin_wx:
            return True
    return False


def _determine_ten_god_xiji(ten_god: str, yongshen: dict) -> str:
    """判断十神喜忌 (V2-2.1 Step 3)。

    Returns: "用神" | "喜神" | "忌神" | "闲神"
    """
    ys_tg = yongshen.get("ten_god", "")
    xishen_list = yongshen.get("xishen_list", [])
    jishen_list = yongshen.get("jishen_list", [])

    if ten_god == ys_tg:
        return "用神"
    if ten_god in xishen_list:
        return "喜神"
    if ten_god in jishen_list:
        return "忌神"
    return "闲神"


def _check_ten_god_controlled(occurrences: list[dict], chart_data: dict) -> bool:
    """检查十神是否受制（被克/被合）。忌神被制 → 凶性降低。"""
    for occ in occurrences:
        pillar = occ["pillar"]
        occ_stem = occ.get("stem_or_branch", "")

        # 检查同柱或相邻柱是否有克制关系
        pillars = chart_data.get("four_pillars", {})
        target_pillar = pillars.get(pillar, {})
        other_stems = {
            p: pillars[p].get("stem", "")
            for p in ["year", "month", "day", "hour"] if p != pillar
        }
        # 检查天干五合
        for other_p, other_stem in other_stems.items():
            if _check_stem_he(occ_stem, other_stem):
                return True

    return False


# ============================================================
# 宫位维度打分 (V2 算法 §11.3)
# ============================================================

def _score_gongwei(
    chart_data: dict,
    six_kin_type: str,
) -> tuple[Literal["吉", "凶", "平"], dict]:
    """宫位维度打分。

    V2-3.2:
    1. 确定六亲→主宫位
    2. 分析宫位受冲/克/刑/害
    3. 判断宫位干支旺衰喜忌
    """
    pillar = SIX_KIN_TO_PILLAR.get(six_kin_type, "month")
    gongwei_data = chart_data.get("four_pillars", {}).get(pillar, {})
    stem = gongwei_data.get("stem", "")
    branch = gongwei_data.get("branch", "")
    day_master = chart_data.get("day_master", "")

    # 冲克分析
    chong_ke = _analyze_gongwei_chong_ke(chart_data, pillar)
    severity = chong_ke.get("total_severity", 0)

    # 宫位喜忌
    gongwei_xiji = _evaluate_gongwei_xiji(stem, branch, day_master)

    detail = {
        "宫位": pillar,
        "天干": stem,
        "地支": branch,
        "冲克状态": chong_ke,
        "喜忌": gongwei_xiji,
    }

    # 规则 1: 宫位严重受冲克（severity >= 5）→ 凶
    if severity >= 5:
        return ("凶", detail)

    # 规则 2: 中度受冲克
    if severity >= 3:
        if gongwei_xiji == "忌神":
            return ("凶", detail)
        return ("平", detail)

    # 规则 3: 轻微受冲克
    if severity > 0:
        return ("平", detail)

    # 规则 4: 无冲克 + 用神/喜神 → 吉
    if gongwei_xiji in ("用神", "喜神"):
        return ("吉", detail)

    # 规则 5: 无冲克 + 忌神 → 平
    return ("平", detail)


def _analyze_gongwei_chong_ke(chart_data: dict, pillar: str) -> dict:
    """宫位冲克分析 (V2-3.4)。

    检查目标宫位与其他柱的地支六冲、天干相克、地支相刑/相害。
    """
    pillars = chart_data.get("four_pillars", {})
    target = pillars.get(pillar, {})
    target_branch = target.get("branch", "")
    target_stem = target.get("stem", "")

    result = {"冲": [], "克": [], "刑": [], "害": [], "total_severity": 0}

    for other_pillar in ["year", "month", "day", "hour"]:
        if other_pillar == pillar:
            continue
        other = pillars.get(other_pillar, {})
        other_branch = other.get("branch", "")
        other_stem = other.get("stem", "")

        # 地支六冲
        if _BRANCH_CHONG.get(target_branch) == other_branch:
            result["冲"].append({"with": other_pillar, "severity": 3})

        # 天干相克
        if _check_stem_ke(target_stem, other_stem):
            result["克"].append({"with": other_pillar, "severity": 3})

        # 地支相刑
        if (target_branch, other_branch) in _BRANCH_XING or \
           (other_branch, target_branch) in _BRANCH_XING:
            result["刑"].append({"with": other_pillar, "severity": 2})

        # 地支相害
        if _BRANCH_HAI.get(target_branch) == other_branch:
            result["害"].append({"with": other_pillar, "severity": 2})

    result["total_severity"] = sum(
        item["severity"]
        for key in ["冲", "克", "刑", "害"]
        for item in result[key]
    )
    return result


def _check_stem_ke(stem_a: str, stem_b: str) -> bool:
    """检查两个天干是否相克。"""
    wx_a = WUXING_MAP.get(stem_a, "")
    wx_b = WUXING_MAP.get(stem_b, "")
    if not wx_a or not wx_b:
        return False
    from rules.wuxing import get_ke
    return get_ke(wx_a) == wx_b or get_ke(wx_b) == wx_a


def _check_stem_he(stem_a: str, stem_b: str) -> bool:
    """检查两个天干是否五合。"""
    HE_PAIRS = {
        ("甲", "己"), ("己", "甲"), ("乙", "庚"), ("庚", "乙"),
        ("丙", "辛"), ("辛", "丙"), ("丁", "壬"), ("壬", "丁"),
        ("戊", "癸"), ("癸", "戊"),
    }
    return (stem_a, stem_b) in HE_PAIRS


def _evaluate_gongwei_xiji(stem: str, branch: str, day_master: str) -> str:
    """评估宫位干支的喜忌（相对于日主）。

    V2-2.1 Step 5: 宫位为忌神时取象可信度降低。
    """
    if not stem or not day_master:
        return "闲神"

    tg = _calc_ten_god(day_master, stem)
    # 简化判断：十神对应喜忌
    # 正官/正印/正财/食神 偏吉；七杀/偏印/伤官 偏忌
    good = {"正官", "正印", "正财", "食神"}
    bad = {"七杀", "偏印", "伤官", "劫财"}
    neutral = {"比肩", "偏财"}

    if tg in good:
        return "喜神"
    elif tg in bad:
        return "忌神"
    elif tg in neutral:
        return "闲神"
    return "闲神"


def _merge_parents_ten_god(mother_result: str, father_result: str) -> str:
    """父母十神维度合并：取较凶者。"""
    order = {"凶": 3, "平": 2, "吉": 1}
    m = order.get(mother_result, 2)
    f = order.get(father_result, 2)
    return mother_result if m >= f else father_result


# ============================================================
# 问题生成：generate_liuqin_question() (V2 算法 §12)
# ============================================================

def generate_liuqin_question(
    item: LiuqinItem,
    six_kin_type: Literal["parents", "siblings", "spouse", "children"],
) -> QuestionV2:
    """根据六亲评估结果生成验证问题。

    V2-4.1: 六亲存亡类问题 D(q) 最高（≥0.8）。
    文本由模板生成，不依赖 AI。

    Args:
        item: 六亲评估结果
        six_kin_type: 六亲类别

    Returns:
        QuestionV2: 包含 question_text、options、dq_score、targets、skeleton
    """
    # 计算 D(q)
    dq = _compute_liuqin_dq(item)

    # 生成问题文本
    cat, question_text = _build_liuqin_question_text(item, six_kin_type)

    # 构建问题骨架（供 AI 出题消费）
    skeleton = {
        "template_id": _map_six_kin_to_skeleton_id(six_kin_type),
        "category": cat,
        "six_kin_type": six_kin_type,
        "ten_god_dim": item.ten_god_dim,
        "gongwei_dim": item.gongwei_dim,
        "consistency": item.consistency,
        "confidence": item.confidence,
        "detail_keys": list(item.detail.keys()) if item.detail else [],
    }

    # 构建 targets
    targets = {
        "dimension": f"liuqin_{six_kin_type}",
        "ten_god_dim": item.ten_god_dim,
        "gongwei_dim": item.gongwei_dim,
    }

    return QuestionV2(
        id=f"q_liuqin_{six_kin_type}",
        category=cat,
        question_text=question_text,
        options=["是", "不是", "记不清了"],
        dq_score=round(dq, 2),
        targets=targets,
        skeleton=skeleton,
    )


def _compute_liuqin_dq(item: LiuqinItem) -> float:
    """计算六亲问题的鉴别力 D(q) = I(q) / T(q)。

    V2-4.1: 六亲存亡类 I(q) 极高（信息增益 25-35%）、T(q) 极小（二值事实）。
    六亲关系类 I(q) 中高、T(q) 中等。

    Returns:
        float: D(q) ∈ [0.0, 1.0]
    """
    # 信息增益 I(q): 基于双轨一致性
    if item.consistency == "contradictory":
        i_score = 0.35  # 矛盾时鉴别力最高
    elif item.consistency == "tentative":
        i_score = 0.20
    else:  # confirmed
        i_score = 0.15

    # 调整：confidence 越高 → I 略降（因为已经很确定，再问收益低）
    i_score = i_score * (1.0 - item.confidence * 0.3)

    # 模糊容忍度 T(q): 二值判断 → T 极低
    ten_god_is_extreme = item.ten_god_dim in ("吉", "凶")
    gongwei_is_extreme = item.gongwei_dim in ("吉", "凶")
    if ten_god_is_extreme and gongwei_is_extreme:
        t_score = 0.05  # 两维都极端，几乎无模糊空间
    elif ten_god_is_extreme or gongwei_is_extreme:
        t_score = 0.15
    else:
        t_score = 0.30

    dq = i_score / max(t_score, 0.01)
    return min(dq, 1.0)


def _build_liuqin_question_text(
    item: LiuqinItem,
    six_kin_type: str,
) -> tuple[str, str]:
    """根据六亲评估构建自然语言问题。

    Returns:
        (category, question_text)
    """
    kin_names = {
        "parents": "父母", "siblings": "兄弟姐妹",
        "spouse": "配偶", "children": "子女",
    }
    kin_name = kin_names.get(six_kin_type, six_kin_type)

    if item.ten_god_dim == "凶" or item.gongwei_dim == "凶":
        category = "六亲存亡"
        if six_kin_type == "parents":
            question = "您的父母是否健在？或者年轻时父母关系中是否有过重大变故（如离异、长期分离等）？"
        elif six_kin_type == "spouse":
            question = "您的婚姻是否顺利？是否出现过重大感情波折或分离？"
        elif six_kin_type == "siblings":
            question = "您的兄弟姐妹是否都健在？或者与手足之间的关系是否有过重大矛盾？"
        else:
            question = f"您的{kin_name}方面是否经历过较大的波折或不顺？"
    elif item.ten_god_dim == "吉" and item.gongwei_dim == "吉":
        category = "六亲关系"
        if six_kin_type == "parents":
            question = "您的父母是否都健在，并且家庭关系和睦，父母对您的成长有较好的支持？"
        elif six_kin_type == "spouse":
            question = "您的婚姻是否比较顺遂，配偶对您的事业或生活有积极的帮助？"
        elif six_kin_type == "siblings":
            question = "您的兄弟姐妹是否较多（或关系密切），对您的人生有积极影响？"
        else:
            question = f"您的{kin_name}是否比较顺遂，关系和谐？"
    else:
        category = "六亲关系"
        question = f"关于您的{kin_name}，命盘显示信息不太明确。能否简单描述一下基本情况？"

    return category, question


def _map_six_kin_to_skeleton_id(six_kin_type: str) -> str:
    """六亲类别 → QuestionSkeleton 模板 ID。"""
    mapping = {
        "parents": "parents_survival",
        "siblings": "sibling_relation",
        "spouse": "marriage_timing",
        "children": "parents_survival",  # 子女存亡模板复用
    }
    return mapping.get(six_kin_type, "parents_survival")


# ============================================================
# 便捷函数
# ============================================================

def assess_liuqin_from_chart(
    chart_data: dict,
) -> LiuqinAssessment:
    """便捷入口：从排盘数据自动推断 pattern 和 yongshen 后执行评估。

    Args:
        chart_data: 排盘数据字典（含 day_master, four_pillars, gender, month_branch 等）

    Returns:
        LiuqinAssessment
    """
    from rules.pattern import determine_pattern_type, get_month_main_ten_god

    day_master = chart_data.get("day_master", "")
    month_branch = chart_data.get("four_pillars", {}).get("month", {}).get("branch", "")
    if not month_branch:
        # 月柱缺失则从 month_pillar 字段取
        month_data = chart_data.get("month_pillar") or chart_data.get("month", {})
        month_branch = month_data.get("branch", "") if isinstance(month_data, dict) else str(month_data)

    pattern = determine_pattern_type(day_master, month_branch)
    yongshen = determine_yongshen(pattern, day_master, month_branch, chart_data)

    return assess_liuqin(chart_data, pattern, yongshen)
