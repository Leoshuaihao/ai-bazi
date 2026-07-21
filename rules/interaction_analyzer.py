"""刑冲合害分析器 — 分析流年与命局的互动关系

核心职责：
1. 计算流年干支对四柱的刑冲合害
2. 分析流年五行对用神、忌神、日主的关系
3. 输出结构化的互动结果，供事件规则表匹配
"""

from typing import Optional
from rules.wuxing import WUXING_MAP, get_sheng, get_ke, get_i_sheng, get_i_ke


# ============================================================
# 生克关系
# ============================================================

SHENG_MAP = {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}
KE_MAP = {"木": "土", "土": "水", "水": "火", "火": "金", "金": "木"}
# 逆向：谁生我、谁克我
BEI_SHENG = {v: k for k, v in SHENG_MAP.items()}
BEI_KE = {v: k for k, v in KE_MAP.items()}

# ============================================================
# 刑冲合害对照表
# ============================================================

CLASH = {
    "子": "午", "午": "子",
    "丑": "未", "未": "丑",
    "寅": "申", "申": "寅",
    "卯": "酉", "酉": "卯",
    "辰": "戌", "戌": "辰",
    "巳": "亥", "亥": "巳",
}

LIUHE = {
    "子": "丑", "丑": "子",
    "寅": "亥", "亥": "寅",
    "卯": "戌", "戌": "卯",
    "辰": "酉", "酉": "辰",
    "巳": "申", "申": "巳",
    "午": "未", "未": "午",
}

# 三合局
SANHE = {
    "申子辰": "水", "亥卯未": "木",
    "寅午戌": "火", "巳酉丑": "金",
}

# 半合（生地半合 + 墓库半合）
BANHE = {
    ("申", "子"): "水", ("子", "辰"): "水",
    ("亥", "卯"): "木", ("卯", "未"): "木",
    ("寅", "午"): "火", ("午", "戌"): "火",
    ("巳", "酉"): "金", ("酉", "丑"): "金",
}

# 三刑
XING_PAIRS = {
    ("寅", "巳"): "无恩之刑", ("巳", "申"): "无恩之刑", ("申", "寅"): "无恩之刑",
    ("丑", "戌"): "恃势之刑", ("戌", "未"): "恃势之刑", ("未", "丑"): "恃势之刑",
    ("子", "卯"): "无礼之刑", ("卯", "子"): "无礼之刑",
}

# 六害
HAI = {
    "子": "未", "未": "子",
    "丑": "午", "午": "丑",
    "寅": "巳", "巳": "寅",
    "卯": "辰", "辰": "卯",
    "申": "亥", "亥": "申",
    "酉": "戌", "戌": "酉",
}

# 墓库
MUKU = {"辰": "水", "戌": "火", "丑": "金", "未": "木"}

# 四柱位置名
PILLAR_NAMES = ["年", "月", "日", "时"]


# ============================================================
# 核心分析函数
# ============================================================

def analyze_liunian_interactions(
    liunian_stem: str,
    liunian_branch: str,
    chart_pillars: list[dict],
    yongshen_wuxing: str,
    jishen_wuxing_list: list[str],
    day_master_wuxing: str,
    day_master_stem: str = "",
    yongshen_root_branches: list[str] = None,
    wangshuai: str = "",
    dayun_ganzhi: str = "",
    ten_god_map: dict = None,
) -> dict:
    """核心函数：分析流年对命局的完整互动

    Args:
        liunian_stem: 流年天干（如 "乙")
        liunian_branch: 流年地支（如 "未")
        chart_pillars: 四柱列表 [{"stem": "甲", "branch": "子"}, ...]
        yongshen_wuxing: 用神五行
        jishen_wuxing_list: 忌神五行列表
        day_master_wuxing: 日主五行
        yongshen_root_branches: 用神在地支的根（哪些地支是用神五行）

    Returns:
        {
            "stem_interactions": [...],      # 天干互动
            "branch_interactions": [...],    # 地支互动
            "yongshen_relation": str,        # 流年对用神的关系
            "jishen_relations": [...],       # 流年对忌神的关系
            "daymaster_relation": str,       # 流年对日主的关系
            "is_yongshen_year": bool,        # 是否用神年
            "is_jishen_year": bool,          # 是否忌神年
            "triggered_rules": [str, ...],   # 触发的规则ID列表
            "combined_score": float,         # 综合吉凶分数
        }
    """
    result = {
        "stem_interactions": [],
        "branch_interactions": [],
        "yongshen_relation": "",
        "jishen_relations": [],
        "daymaster_relation": "",
        "is_yongshen_year": False,
        "is_jishen_year": False,
        "triggered_rules": [],
        "combined_score": 0.0,
    }

    liunian_stem_wx = WUXING_MAP.get(liunian_stem, "")
    liunian_branch_wx = WUXING_MAP.get(liunian_branch, "")

    if not liunian_stem_wx:
        return result

    # ============================================================
    # 一、天干层面分析
    # ============================================================

    for i, pillar in enumerate(chart_pillars):
        pos = PILLAR_NAMES[i]
        p_stem = pillar.get("stem", "")
        p_stem_wx = WUXING_MAP.get(p_stem, "")

        if not p_stem_wx:
            continue

        # 天干五合
        gan_he = _check_gan_he(liunian_stem, p_stem)
        if gan_he:
            result["stem_interactions"].append({
                "type": "合",
                "target": f"{pos}干",
                "detail": f"流年{liunian_stem}合{pos}干{p_stem}，化为{gan_he}",
                "pillar": pos,
                "he_hua_wx": gan_he,
            })
            # B3: 用神被合 — 检查被合的天干是否是用神十神
            if ten_god_map and p_stem in ten_god_map:
                tg = ten_god_map[p_stem]
                if _is_yongshen_ten_god(tg, yongshen_wuxing, day_master_wuxing):
                    result["triggered_rules"].append("B3_he_yongshen")
                # E2: 正官被合
                if tg == "正官":
                    result["triggered_rules"].append("E2_zhengguan_bei_he")
                # E6: 偏财被合
                if tg == "偏财":
                    result["triggered_rules"].append("E6_piancai_bei_he")

        # 天干生克
        if SHENG_MAP.get(liunian_stem_wx) == p_stem_wx:
            result["stem_interactions"].append({
                "type": "生",
                "target": f"{pos}干",
                "detail": f"流年生{pos}干",
                "pillar": pos,
            })
        elif KE_MAP.get(liunian_stem_wx) == p_stem_wx:
            result["stem_interactions"].append({
                "type": "克",
                "target": f"{pos}干",
                "detail": f"流年克{pos}干",
                "pillar": pos,
            })

    # ============================================================
    # 二、地支层面分析
    # ============================================================

    for i, pillar in enumerate(chart_pillars):
        pos = PILLAR_NAMES[i]
        p_branch = pillar.get("branch", "")

        # 六冲
        if CLASH.get(liunian_branch) == p_branch:
            result["branch_interactions"].append({
                "type": "冲",
                "target": f"{pos}支",
                "detail": f"流年{liunian_branch}冲{pos}支{p_branch}",
                "pillar": pos,
                "severity": "high",
            })
            result["triggered_rules"].append(f"A{i+1 if i < 3 else 4}_branch_clash_{['year','month','day','hour'][i]}")

        # 六合
        if LIUHE.get(liunian_branch) == p_branch:
            result["branch_interactions"].append({
                "type": "合",
                "target": f"{pos}支",
                "detail": f"流年{liunian_branch}合{pos}支{p_branch}",
                "pillar": pos,
                "severity": "medium",
            })
            idx = {0: 5, 1: 6, 2: 7}.get(i)
            if idx is not None:
                result["triggered_rules"].append(f"A{idx}_branch_he_{['year','month','day'][i]}")

        # 三刑
        xing_key = (liunian_branch, p_branch)
        if xing_key in XING_PAIRS:
            result["branch_interactions"].append({
                "type": "刑",
                "target": f"{pos}支",
                "detail": f"流年{liunian_branch}刑{pos}支{p_branch}（{XING_PAIRS[xing_key]}）",
                "pillar": pos,
                "severity": "medium",
            })
            if i <= 1:
                result["triggered_rules"].append("A8_branch_xing_early")
            elif i == 2:
                result["triggered_rules"].append("A9_branch_xing_day")

        # 六害
        if HAI.get(liunian_branch) == p_branch:
            result["branch_interactions"].append({
                "type": "害",
                "target": f"{pos}支",
                "detail": f"流年{liunian_branch}害{pos}支{p_branch}",
                "pillar": pos,
                "severity": "low",
            })
            result["triggered_rules"].append("A10_branch_hai_any")

        # 值临（伏吟）
        if liunian_branch == p_branch:
            result["branch_interactions"].append({
                "type": "值临",
                "target": f"{pos}支",
                "detail": f"流年{liunian_branch}值临{pos}支",
                "pillar": pos,
                "severity": "medium",
            })
            if i <= 1:
                result["triggered_rules"].append("A11_branch_zhilin_yue")
            elif i == 2:
                result["triggered_rules"].append("A12_branch_zhilin_day")

        # 检查三合局
        _check_sanhe_trigger(result, liunian_branch, [p["branch"] for p in chart_pillars])

        # 半合局（生地半合 + 墓库半合）
        _check_banhe_trigger(result, liunian_branch, p_branch, chart_pillars)

        # 冲墓库
        if liunian_branch in MUKU or p_branch in MUKU:
            if check_is_clash(liunian_branch, p_branch):
                result["branch_interactions"].append({
                    "type": "冲墓",
                    "target": f"{pos}支",
                    "detail": f"流年{liunian_branch}冲{pos}支墓库{p_branch}",
                    "pillar": pos,
                    "severity": "high",
                })
                result["triggered_rules"].append("F4_chongkai_muku")

    # 检查三刑全（流年+命局其他两柱形成完整三刑组）
    _check_sanxing_quan_trigger(result, liunian_branch, chart_pillars)

    # ============================================================
    # 三、用神/忌神/日主层面分析
    # ============================================================

    # 用神分析
    ys_rel = _analyze_element_relation(liunian_stem_wx, liunian_branch_wx, yongshen_wuxing)
    result["yongshen_relation"] = ys_rel

    if ys_rel == "生":
        result["triggered_rules"].append("B1_sheng_yongshen")
        result["is_yongshen_year"] = True
    elif ys_rel == "克":
        result["triggered_rules"].append("B2_ke_yongshen")
    elif ys_rel == "同":
        result["triggered_rules"].append("B5_is_yongshen_year")
        result["is_yongshen_year"] = True

    # 用神之根被冲
    if yongshen_root_branches:
        for root_br in yongshen_root_branches:
            if CLASH.get(liunian_branch) == root_br:
                result["triggered_rules"].append("B4_chong_yongshen_root")

    # 忌神分析
    for js_wx in jishen_wuxing_list:
        js_rel = _analyze_element_relation(liunian_stem_wx, liunian_branch_wx, js_wx)
        result["jishen_relations"].append({"wuxing": js_wx, "relation": js_rel})
        if js_rel == "生":
            result["triggered_rules"].append("C1_sheng_jishen")
        elif js_rel == "克":
            result["triggered_rules"].append("C2_zhi_jishen")
        elif js_rel == "同":
            result["triggered_rules"].append("C3_is_jishen_year")
            result["is_jishen_year"] = True

    # 日主分析
    dm_rel = _analyze_element_relation(liunian_stem_wx, liunian_branch_wx, day_master_wuxing)
    result["daymaster_relation"] = dm_rel

    # 天克地冲日柱
    day_pillar = chart_pillars[2] if len(chart_pillars) > 2 else {}
    day_branch = day_pillar.get("branch", "")
    day_stem = day_pillar.get("stem", "")

    if KE_MAP.get(liunian_stem_wx) == WUXING_MAP.get(day_stem, "") and CLASH.get(liunian_branch) == day_branch:
        result["triggered_rules"].append("D1_tiankedichong_day")

    # D2/D3: 根据身强身弱拆分为不同规则
    is_strong = wangshuai in ("身旺", "偏强", "太旺", "极旺")
    is_weak = wangshuai in ("身弱", "偏弱", "太弱", "极弱")

    if dm_rel == "克":
        if is_weak:
            result["triggered_rules"].append("D2_weak_ke_shen")
        elif is_strong:
            result["triggered_rules"].append("D2_strong_zhi_heng")
        else:
            result["triggered_rules"].append("D2_jishen_ke_shen")
    elif dm_rel == "生":
        if is_weak:
            result["triggered_rules"].append("D3_weak_fu_shen")
        elif is_strong:
            result["triggered_rules"].append("D3_strong_guo_sheng")
        else:
            result["triggered_rules"].append("D3_yongshen_fu_shen")
    elif dm_rel == "泄":
        # 泄身（食伤）：身旺者泄秀为吉，身弱者泄身则耗
        result["triggered_rules"].append("E11_xie_xiu")

    # 日主入墓
    if MUKU.get(liunian_branch) == day_master_wuxing:
        result["triggered_rules"].append("D4_rizhu_rumu")

    # F6/F7: 干支皆为用神/忌神
    stem_is_ys = liunian_stem_wx == yongshen_wuxing or SHENG_MAP.get(liunian_stem_wx) == yongshen_wuxing
    branch_is_ys = liunian_branch_wx == yongshen_wuxing or SHENG_MAP.get(liunian_branch_wx) == yongshen_wuxing
    if stem_is_ys and branch_is_ys:
        result["triggered_rules"].append("F6_both_yongshen")

    stem_is_js = any(liunian_stem_wx == js or SHENG_MAP.get(liunian_stem_wx) == js for js in jishen_wuxing_list)
    branch_is_js = any(liunian_branch_wx == js or SHENG_MAP.get(liunian_branch_wx) == js for js in jishen_wuxing_list)
    if stem_is_js and branch_is_js:
        result["triggered_rules"].append("F7_both_jishen")

    # ============================================================
    # 三点五、大运与流年互动
    # ============================================================
    if dayun_ganzhi and len(dayun_ganzhi) == 2:
        da_stem, da_branch = dayun_ganzhi[0], dayun_ganzhi[1]
        # F5: 流年天克地冲大运
        if KE_MAP.get(liunian_stem_wx) == WUXING_MAP.get(da_stem, "") and CLASH.get(liunian_branch) == da_branch:
            result["triggered_rules"].append("F5_liunian_chong_dayun")
        # G7: 岁运并临
        if liunian_stem == da_stem and liunian_branch == da_branch:
            result["triggered_rules"].append("G7_suiyun_binglin")

    # ============================================================
    # 五、十神层面分析（E类规则激活）
    # ============================================================
    if ten_god_map:
        _analyze_ten_god_interactions(result, liunian_stem, liunian_stem_wx, chart_pillars, ten_god_map, yongshen_wuxing, day_master_wuxing, day_master_stem)
        # G1-G4: 天干五合对用忌神的影响
        _check_ganhe_yongshen_effect(result, liunian_stem, liunian_branch, chart_pillars, yongshen_wuxing, jishen_wuxing_list)
        # G5-G6: 官杀混杂
        _check_guansha_hunza(result, chart_pillars, ten_god_map, liunian_stem, day_master_wuxing, day_master_stem)

    # ============================================================
    # 四、综合评分
    # ============================================================

    result["combined_score"] = _calc_combined_score(result)

    return result


def _check_gan_he(stem1: str, stem2: str) -> Optional[str]:
    """检查天干五合"""
    HE_MAP = {
        ("甲", "己"): "土", ("己", "甲"): "土",
        ("乙", "庚"): "金", ("庚", "乙"): "金",
        ("丙", "辛"): "水", ("辛", "丙"): "水",
        ("丁", "壬"): "木", ("壬", "丁"): "木",
        ("戊", "癸"): "火", ("癸", "戊"): "火",
    }
    return HE_MAP.get((stem1, stem2))


def _analyze_element_relation(liunian_stem_wx: str, liunian_branch_wx: str, target_wx: str) -> str:
    """分析流年五行对目标五行的关系

    Returns: "生" | "克" | "同" | "泄" | "无"
    """
    # 天干为主，地支为辅
    if not liunian_stem_wx or not target_wx:
        return "无"

    # 流年生目标
    if SHENG_MAP.get(liunian_stem_wx) == target_wx or SHENG_MAP.get(liunian_branch_wx) == target_wx:
        return "生"
    # 流年克目标
    if KE_MAP.get(liunian_stem_wx) == target_wx or KE_MAP.get(liunian_branch_wx) == target_wx:
        return "克"
    # 同五行
    if liunian_stem_wx == target_wx or liunian_branch_wx == target_wx:
        return "同"
    # 目标生流年（泄）
    if SHENG_MAP.get(target_wx) == liunian_stem_wx:
        return "泄"

    return "无"


def _check_sanhe_trigger(result: dict, liunian_branch: str, chart_branches: list[str]):
    """检查是否形成三合局"""
    for combo, wx in SANHE.items():
        branches = combo[0] + combo[1] + combo[2]
        if liunian_branch in branches:
            # 检查命局中有没有另外两个
            needed = set(branches) - {liunian_branch}
            if needed.issubset(set(chart_branches)):
                result.setdefault("branch_interactions", []).append({
                    "type": "三合",
                    "target": "全局",
                    "detail": f"流年{liunian_branch}与命局形成三合{wx}局",
                    "severity": "high",
                })
                result.setdefault("triggered_rules", []).append("F3_sanhe_formed")


def _calc_combined_score(result: dict) -> float:
    """综合吉凶评分：正数=吉，负数=凶"""
    score = 0.0

    # 用神年 +2
    if result["is_yongshen_year"]:
        score += 2.0
    # 忌神年 -2
    if result["is_jishen_year"]:
        score -= 2.0

    # 地支互动
    for bi in result.get("branch_interactions", []):
        if bi["type"] == "冲":
            score -= 0.5
        elif bi["type"] == "合":
            score += 0.3
        elif bi["type"] == "刑":
            score -= 0.3
        elif bi["type"] == "害":
            score -= 0.2

    # 天克地冲日柱 -3
    if "D1_tiankedichong_day" in result["triggered_rules"]:
        score -= 3.0

    # 用神受克 -1
    if "B2_ke_yongshen" in result["triggered_rules"]:
        score -= 1.0

    # 用神得生 +1
    if "B1_sheng_yongshen" in result["triggered_rules"]:
        score += 1.0

    # 忌神被制 +1
    if "C2_zhi_jishen" in result["triggered_rules"]:
        score += 1.0

    return round(score, 1)


# ============================================================
# 新增辅助函数：半合、三刑全、十神、天干合、官杀混杂
# ============================================================

def _check_banhe_trigger(result: dict, liunian_branch: str, p_branch: str, chart_pillars: list[dict]):
    """检查半合局"""
    key = (liunian_branch, p_branch)
    banhe_wx = BANHE.get(key)
    if not banhe_wx:
        key = (p_branch, liunian_branch)
        banhe_wx = BANHE.get(key)
    if banhe_wx:
        result.setdefault("branch_interactions", []).append({
            "type": "半合",
            "target": "全局",
            "detail": f"流年{liunian_branch}与命局半合{banhe_wx}局",
            "severity": "medium",
        })
        result.setdefault("triggered_rules", []).append("A13_banhe")


def _check_sanxing_quan_trigger(result: dict, liunian_branch: str, chart_pillars: list[dict]):
    """检查三刑全（流年补齐三刑组）"""
    chart_branches = [p["branch"] for p in chart_pillars]
    for xing_set in [{"寅", "巳", "申"}, {"丑", "戌", "未"}, {"子", "卯"}]:
        if liunian_branch in xing_set:
            needed = xing_set - {liunian_branch}
            if needed.issubset(set(chart_branches)):
                result.setdefault("triggered_rules", []).append("F2_sanxing_quan")
                return


def _is_yongshen_ten_god(ten_god: str, yongshen_wx: str, dm_wx: str) -> bool:
    """判断十神是否是命局用神（按五行匹配）"""
    tg_to_wx = {
        "正官": BEI_KE.get(dm_wx, ""), "七杀": BEI_KE.get(dm_wx, ""),
        "正财": KE_MAP.get(dm_wx, ""), "偏财": KE_MAP.get(dm_wx, ""),
        "正印": BEI_SHENG.get(dm_wx, ""), "偏印": BEI_SHENG.get(dm_wx, ""),
        "食神": SHENG_MAP.get(dm_wx, ""), "伤官": SHENG_MAP.get(dm_wx, ""),
        "比肩": dm_wx, "劫财": dm_wx,
    }
    tg_wx = tg_to_wx.get(ten_god, "")
    return tg_wx == yongshen_wx


def _analyze_ten_god_interactions(
    result: dict, liunian_stem: str, liunian_stem_wx: str,
    chart_pillars: list[dict], ten_god_map: dict,
    yongshen_wx: str, dm_wx: str, dm_char: str = "",
):
    """E类十神规则激活：分析流年十神与命局十神互动"""
    if not liunian_stem_wx or not dm_wx:
        return
    ln_tg = _calc_ten_god_for_stem(liunian_stem, dm_char) if dm_char else _calc_ten_god_for_stem(liunian_stem, liunian_stem)

    for pillar in chart_pillars:
        p_stem = pillar.get("stem", "")
        if p_stem not in ten_god_map:
            continue
        p_tg = ten_god_map[p_stem]

        if p_tg == "正官" and ln_tg == "伤官":
            result["triggered_rules"].append("E1_zhengguan_ke_shang")
        if ln_tg == "七杀" and not _has_zhi_sha(pillar["branch"], dm_wx, chart_pillars):
            result["triggered_rules"].append("E3_qisha_wuzhi")
        if ln_tg == "食神" and p_tg == "七杀":
            result["triggered_rules"].append("E4_qisha_bei_zhi")
        if ln_tg in ("比肩", "劫财") and p_tg in ("正财", "偏财"):
            result["triggered_rules"].append("E5_zhengcai_bei_duo")
        if ln_tg in ("正财", "偏财") and p_tg in ("正印", "偏印"):
            result["triggered_rules"].append("E7_zhengying_bei_po")
        if ln_tg == "偏印" and p_tg == "食神":
            result["triggered_rules"].append("E8_shishen_bei_duo")
        if ln_tg == "伤官" and p_tg == "正官":
            result["triggered_rules"].append("E9_shangguan_jian_guan")
        if ln_tg in ("正官", "七杀") and p_tg in ("比肩", "劫财"):
            result["triggered_rules"].append("E10_bijie_bei_zhi")


def _calc_ten_god_for_stem(stem_char: str, dm_char: str) -> str:
    """计算一个天干对日主的十神（含阴阳区分）

    Args:
        stem_char: 天干字符（如 "甲"、"乙"）
        dm_char: 日主天干字符（如 "丙"）

    Returns:
        完整十神名：正官/七杀/正印/偏印/正财/偏财/食神/伤官/比肩/劫财
    """
    if not stem_char or not dm_char:
        return ""

    stem_wx = WUXING_MAP.get(stem_char, "")
    dm_wx = WUXING_MAP.get(dm_char, "")
    if not stem_wx or not dm_wx:
        return ""

    # 阴阳：阳=1，阴=0
    YINYANG = {"甲": 1, "丙": 1, "戊": 1, "庚": 1, "壬": 1,
               "乙": 0, "丁": 0, "己": 0, "辛": 0, "癸": 0}
    same_yy = YINYANG.get(stem_char, -1) == YINYANG.get(dm_char, -1)

    # 同五行 → 比肩/劫财
    if stem_wx == dm_wx:
        return "比肩" if same_yy else "劫财"

    # 生我 → 正印/偏印
    if SHENG_MAP.get(stem_wx) == dm_wx:
        return "偏印" if same_yy else "正印"

    # 我生 → 食神/伤官
    if SHENG_MAP.get(dm_wx) == stem_wx:
        return "食神" if same_yy else "伤官"

    # 克我 → 七杀/正官
    if KE_MAP.get(stem_wx) == dm_wx:
        return "七杀" if same_yy else "正官"

    # 我克 → 偏财/正财
    if KE_MAP.get(dm_wx) == stem_wx:
        return "偏财" if same_yy else "正财"

    return ""


def _has_zhi_sha(branch: str, dm_wx: str, chart_pillars: list[dict]) -> bool:
    """检查是否有制杀之物（食神或印星天干）"""
    shi_shen_wx = SHENG_MAP.get(dm_wx, "")
    yin_wx = BEI_SHENG.get(dm_wx, "")
    for p in chart_pillars:
        p_wx = WUXING_MAP.get(p.get("stem", ""), "")
        if p_wx in (shi_shen_wx, yin_wx):
            return True
    return False


def _check_ganhe_yongshen_effect(
    result: dict, liunian_stem: str, liunian_branch: str,
    chart_pillars: list[dict], yongshen_wx: str, jishen_wx_list: list[str],
):
    """G1-G4: 天干五合对用忌神的影响"""
    for pillar in chart_pillars:
        p_stem = pillar.get("stem", "")
        gan_he_wx = _check_gan_he(liunian_stem, p_stem)
        if not gan_he_wx:
            continue
        p_wx = WUXING_MAP.get(p_stem, "")
        if p_wx == yongshen_wx or SHENG_MAP.get(p_wx) == yongshen_wx:
            result["triggered_rules"].append("G1_hequ_yongshen")
            return
        if p_wx in jishen_wx_list:
            result["triggered_rules"].append("G2_hequ_jishen")
            return
        if gan_he_wx == yongshen_wx:
            result["triggered_rules"].append("G3_hehua_yongshen")
        if gan_he_wx in jishen_wx_list:
            result["triggered_rules"].append("G4_hehua_jishen")


def _check_guansha_hunza(
    result: dict, chart_pillars: list[dict], ten_god_map: dict,
    liunian_stem: str, dm_wx: str, dm_char: str = "",
):
    """G5: 官杀混杂"""
    guan_count = sum(1 for p in chart_pillars if ten_god_map.get(p.get("stem", ""), "") == "正官")
    sha_count = sum(1 for p in chart_pillars if ten_god_map.get(p.get("stem", ""), "") == "七杀")
    if guan_count > 0 and sha_count > 0:
        ln_tg = _calc_ten_god_for_stem(liunian_stem, dm_char) if dm_char else ""
        if ln_tg in ("正官", "七杀"):
            result["triggered_rules"].append("G5_guansha_hunza_liunian")


# ============================================================
# 便捷函数
# ============================================================

def check_is_clash(branch1: str, branch2: str) -> bool:
    """检查是否六冲"""
    return CLASH.get(branch1) == branch2


def check_is_liuhe(branch1: str, branch2: str) -> bool:
    """检查是否六合"""
    return LIUHE.get(branch1) == branch2


def check_is_xing(branch1: str, branch2: str) -> bool:
    """检查是否相刑"""
    return (branch1, branch2) in XING_PAIRS


def check_is_hai(branch1: str, branch2: str) -> bool:
    """检查是否相害"""
    return HAI.get(branch1) == branch2
