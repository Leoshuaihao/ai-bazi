"""流年流月计算模块 - 基于干支纪年法

流年：某公历年份对应的干支（年柱），60年一循环
流月：某年某农历月的干支（月柱），依五虎遁法推算
"""

from rules.wuxing import WUXING_MAP

# 天干地支基础表
TIAN_GAN = ["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸"]
DI_ZHI = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"]

# 农历月地支顺序：正月寅 → 十二月丑
YUE_ZHI = ["寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥", "子", "丑"]

# 五虎遁：年干 → 正月（寅月）月干索引
# 甲己之年丙作首，乙庚之岁戊为头，丙辛必定寻庚起，丁壬壬位顺行流，戊癸何方发，甲寅之上好追求
_WU_HU_START: dict[str, int] = {
    "甲": 2, "己": 2,   # 正月丙寅（丙=天干索引2）
    "乙": 4, "庚": 4,   # 正月戊寅（戊=天干索引4）
    "丙": 6, "辛": 6,   # 正月庚寅（庚=天干索引6）
    "丁": 8, "壬": 8,   # 正月壬寅（壬=天干索引8）
    "戊": 0, "癸": 0,   # 正月甲寅（甲=天干索引0）
}

# 天干五行、阴阳（与 bazi_engine 保持一致）
_WUXING = {"甲": "木", "乙": "木", "丙": "火", "丁": "火", "戊": "土",
           "己": "土", "庚": "金", "辛": "金", "壬": "水", "癸": "水"}
_YINYANG = {"甲": 1, "乙": 0, "丙": 1, "丁": 0, "戊": 1,
            "己": 0, "庚": 1, "辛": 0, "壬": 1, "癸": 0}
_SHENG = {"金": "土", "木": "水", "水": "金", "火": "木", "土": "火"}
_I_SHENG = {"金": "水", "木": "火", "水": "木", "火": "土", "土": "金"}
_I_KE = {"金": "木", "木": "土", "水": "火", "火": "金", "土": "水"}
_KE = {"金": "火", "木": "金", "水": "土", "火": "水", "土": "木"}


def _get_year_ganzhi(year: int) -> tuple[str, str]:
    """通过干支纪年公式计算公历年的年柱。

    干支纪年60年一循环，公元4年为甲子年（index=0）。
    公式: index = (year - 4) % 60，天干=index%10，地支=index%12
    """
    index = (year - 4) % 60
    return TIAN_GAN[index % 10], DI_ZHI[index % 12]


def _get_month_ganzhi(year_stem: str, month: int) -> tuple[str, str]:
    """通过五虎遁法计算某年某农历月的月柱。

    Args:
        year_stem: 年天干（如 "丁"）
        month: 农历月序数，1=正月（寅月），12=十二月（丑月）

    Returns:
        (月天干, 月地支) 元组
    """
    start_idx = _WU_HU_START.get(year_stem, 0)
    gan_idx = (start_idx + month - 1) % 10
    zhi_idx = (month - 1) % 12
    return TIAN_GAN[gan_idx], YUE_ZHI[zhi_idx]


def _calc_ten_god(day_master_stem: str, other_stem: str) -> str:
    """计算十神：other_stem 相对于 day_master_stem 的十神关系。"""
    dm_wx = _WUXING.get(day_master_stem, "")
    ot_wx = _WUXING.get(other_stem, "")
    if not dm_wx or not ot_wx:
        return ""
    same_yy = _YINYANG[day_master_stem] == _YINYANG[other_stem]
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
# 公开 API
# ============================================================


def get_liunian(year: int) -> dict:
    """获取某公历年份的流年干支。

    示例：get_liunian(2027) → {"year": 2027, "stem": "丁", "branch": "未", "ganzhi": "丁未"}
    """
    stem, branch = _get_year_ganzhi(year)
    return {
        "year": year,
        "stem": stem,
        "branch": branch,
        "ganzhi": stem + branch,
        "wuxing": WUXING_MAP.get(stem, ""),
    }


def get_liunian_list(start_year: int, count: int = 10) -> list[dict]:
    """获取连续N年的流年列表。

    Args:
        start_year: 起始公历年份
        count: 年份数量，默认10

    Returns:
        按年份升序排列的流年字典列表
    """
    result = []
    for y in range(start_year, start_year + count):
        result.append(get_liunian(y))
    return result


def get_liuyue(year: int, month: int) -> dict:
    """获取某公历年的某农历月的流月干支。

    Args:
        year: 公历年份
        month: 农历月序数，1=正月（寅月，约公历2月），12=十二月（丑月，约公历1月）

    Returns:
        {"year": 2027, "month": 1, "stem": "壬", "branch": "寅", "ganzhi": "壬寅", "wuxing": "水"}

    示例：get_liuyue(2027, 1) → 正月壬寅
    """
    if month < 1 or month > 12:
        raise ValueError(f"month 必须在 1-12 之间，收到: {month}")
    year_stem, _ = _get_year_ganzhi(year)
    stem, branch = _get_month_ganzhi(year_stem, month)
    return {
        "year": year,
        "month": month,
        "stem": stem,
        "branch": branch,
        "ganzhi": stem + branch,
        "wuxing": WUXING_MAP.get(stem, ""),
    }


def get_liuyue_list(year: int) -> list[dict]:
    """获取某公历年12个农历月的流月列表。

    Returns:
        按农历月序（1=正月~12=十二月）排列的流月字典列表
    """
    return [get_liuyue(year, m) for m in range(1, 13)]


def classify_liunian(
    liunian_gz: dict,
    day_master_stem: str,
    yongshen_wuxing: str,
    ji_shen_wuxing: str,
) -> dict:
    """判断流年对命主是好是坏（基于用神/忌神体系）。

    Args:
        liunian_gz: get_liunian() 返回的字典
        day_master_stem: 日主天干（如 "庚"）
        yongshen_wuxing: 用神五行（如 "火"）
        ji_shen_wuxing: 忌神五行（如 "水"）

    Returns:
        {
            "ten_god": "正官",           # 流年天干对日主的十神
            "is_yongshen_year": True,     # 是否用神年
            "is_ji_shen_year": False,     # 是否忌神年
            "label": "用神年✅",           # 分类标签
            "advice": "此年正官星入命，..."  # 简要建议
        }

    判断逻辑：
    1. 先看流年天干五行 → 天干对日主的十神
    2. 再看流年天干/地支五行是否匹配用神或忌神
    3. 若干支同时涉及用神和忌神，以天干五行为主
    """
    year_stem = liunian_gz.get("stem", "")
    year_branch = liunian_gz.get("branch", "")

    # 1. 十神
    ten_god = _calc_ten_god(day_master_stem, year_stem)

    # 2. 流年干支五行
    stem_wx = WUXING_MAP.get(year_stem, "")
    branch_wx = WUXING_MAP.get(year_branch, "")

    # 3. 判断用神/忌神
    is_yongshen = (stem_wx == yongshen_wuxing) or (branch_wx == yongshen_wuxing)
    is_jishen = (stem_wx == ji_shen_wuxing) or (branch_wx == ji_shen_wuxing)

    # 干支同时涉及用神和忌神时，以天干为准
    if is_yongshen and is_jishen:
        if stem_wx == yongshen_wuxing:
            is_jishen = False
        elif stem_wx == ji_shen_wuxing:
            is_yongshen = False

    # 4. 标签与建议
    tg_label = f"{ten_god}星入命" if ten_god else "流年"

    if is_yongshen:
        label = "用神年✅"
        advice = (
            f"此年{tg_label}，用神{yongshen_wuxing}当令，天地之气助身，"
            f"运势上扬。宜积极进取，把握机遇，乘势而上。"
        )
    elif is_jishen:
        label = "忌神年⚠️"
        advice = (
            f"此年{tg_label}，忌神{ji_shen_wuxing}当令，运势受制。"
            f"宜保守稳健，谨言慎行，以守为攻，等待时机。"
        )
    else:
        label = "平年"
        advice = (
            f"此年{tg_label}，五行之气不偏不倚，运势平稳。"
            f"宜按部就班，稳扎稳打，积蓄力量。"
        )

    return {
        "ten_god": ten_god,
        "is_yongshen_year": is_yongshen,
        "is_ji_shen_year": is_jishen,
        "label": label,
        "advice": advice,
    }
