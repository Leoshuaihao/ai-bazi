"""八字排盘核心引擎 - 基于 lunar-python"""

from lunar_python import Solar

from models import (
    BaziChart, Pillar, HiddenStem,
    DayunPeriod, ShenshaItem, WuxingScore, YongShen,
)
from rules.shensha import calculate_shensha
from rules.wuxing import (
    WUXING_MAP, HIDDEN_STEMS_MAP, calculate_wuxing_score, get_wuxing,
)
from rules.yongshen import determine_yongshen

# 五行属性
_WUXING = {"甲": "木", "乙": "木", "丙": "火", "丁": "火", "戊": "土",
           "己": "土", "庚": "金", "辛": "金", "壬": "水", "癸": "水"}
_YINYANG = {"甲": 1, "乙": 0, "丙": 1, "丁": 0, "戊": 1,
            "己": 0, "庚": 1, "辛": 0, "壬": 1, "癸": 0}
_SHENG = {"金": "土", "木": "水", "水": "金", "火": "木", "土": "火"}
_KE = {"金": "火", "木": "金", "水": "土", "火": "水", "土": "木"}
_I_SHENG = {"金": "水", "木": "火", "水": "木", "火": "土", "土": "金"}
_I_KE = {"金": "木", "木": "土", "水": "火", "火": "金", "土": "水"}


def _calc_ten_god(day_master_stem: str, other_stem: str) -> str:
    """计算十神（用于大运十神）"""
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


def _parse_ganzhi(gz: str) -> tuple[str, str]:
    """从干支字符串解析天干和地支"""
    if not gz or len(gz) < 2:
        return ("", "")
    return (gz[0], gz[1])


def _build_hidden_stems(branch: str, day_master_stem: str, hidden_gan_list: list[str]) -> list[HiddenStem]:
    """
    构建藏干列表（含十神）

    lunar-python 只返回藏干名称列表，权重从 hidden_stems.json 获取。
    """
    weight_data = HIDDEN_STEMS_MAP.get(branch, [])
    result = []
    for i, stem in enumerate(hidden_gan_list):
        # 匹配权重：先按顺序匹配 weight_data，找不到则用默认值
        weight = 0.5
        for wd in weight_data:
            if wd["stem"] == stem:
                weight = wd["weight"]
                break
        ten_god = _calc_ten_god(day_master_stem, stem)
        result.append(HiddenStem(stem=stem, weight=weight, ten_god=ten_god))
    return result


def calculate_bazi(year: int, month: int, day: int, hour: int, minute: int, gender: str) -> BaziChart:
    """
    完整排盘计算

    Args:
        year: 公历年
        month: 公历月
        day: 公历日
        hour: 出生小时（0-23，24小时制）
        minute: 出生分钟（0-59）
        gender: "male" 或 "female"

    Returns:
        BaziChart 对象
    """
    # === 1. 使用 lunar-python 排四柱 ===
    solar = Solar.fromYmdHms(year, month, day, hour, minute, 0)
    lunar = solar.getLunar()
    bazi = lunar.getEightChar()

    year_gz = bazi.getYear()   # 如 "庚午"
    month_gz = bazi.getMonth() # 如 "己卯"
    day_gz = bazi.getDay()     # 如 "己卯"
    time_gz = bazi.getTime()   # 如 "戊辰"

    year_stem, year_branch = _parse_ganzhi(year_gz)
    month_stem, month_branch = _parse_ganzhi(month_gz)
    day_stem, day_branch = _parse_ganzhi(day_gz)
    hour_stem, hour_branch = _parse_ganzhi(time_gz)

    day_master_stem = day_stem

    # === 2. 构建四柱数据 ===
    pillars_raw = {
        "year": {"stem": year_stem, "branch": year_branch},
        "month": {"stem": month_stem, "branch": month_branch},
        "day": {"stem": day_stem, "branch": day_branch},
        "hour": {"stem": hour_stem, "branch": hour_branch},
    }

    # === 3. 十神 ===
    stem_shishen = {
        "year": bazi.getYearShiShenGan(),
        "month": bazi.getMonthShiShenGan(),
        "day": "日主",
        "hour": bazi.getTimeShiShenGan(),
    }

    # 地支十神（取第一个，即本气十神）
    def _first_branch_shishen(shishen_list):
        if isinstance(shishen_list, list) and shishen_list:
            return shishen_list[0]
        return str(shishen_list) if shishen_list else ""

    branch_shishen = {
        "year": _first_branch_shishen(bazi.getYearShiShenZhi()),
        "month": _first_branch_shishen(bazi.getMonthShiShenZhi()),
        "day": "日支",
        "hour": _first_branch_shishen(bazi.getTimeShiShenZhi()),
    }

    # === 4. 藏干 ===
    hidden_gan = {
        "year": bazi.getYearHideGan(),
        "month": bazi.getMonthHideGan(),
        "day": bazi.getDayHideGan(),
        "hour": bazi.getTimeHideGan(),
    }

    # === 5. 纳音 ===
    nayin = {
        "year": bazi.getYearNaYin(),
        "month": bazi.getMonthNaYin(),
        "day": bazi.getDayNaYin(),
        "hour": bazi.getTimeNaYin(),
    }

    # === 6. 长生十二宫 ===
    dishi = {
        "year": bazi.getYearDiShi(),
        "month": bazi.getMonthDiShi(),
        "day": bazi.getDayDiShi(),
        "hour": bazi.getTimeDiShi(),
    }

    # === 7. 构建四柱详细信息 ===
    four_pillars = {}
    all_hidden_stems = []

    for pos in ["year", "month", "day", "hour"]:
        stem = pillars_raw[pos]["stem"]
        branch = pillars_raw[pos]["branch"]

        hidden_stems = _build_hidden_stems(branch, day_master_stem, hidden_gan[pos])
        all_hidden_stems.extend([{"stem": hs.stem, "weight": hs.weight} for hs in hidden_stems])

        four_pillars[pos] = Pillar(
            stem=stem,
            branch=branch,
            stem_ten_god=stem_shishen[pos],
            branch_ten_god=branch_shishen[pos],
            hidden_stems=hidden_stems,
            nayin=nayin[pos],
            dishi=dishi[pos],
        )

    # === 8. 大运 ===
    gender_int = 1 if gender == "male" else 0
    yun = bazi.getYun(gender_int)
    dayun_list = []
    for d in yun.getDaYun():
        gz = d.getGanZhi()
        if not gz:
            continue  # 跳过起运前的空大运
        du_stem, du_branch = _parse_ganzhi(gz)
        ten_god = _calc_ten_god(day_master_stem, du_stem)
        dayun_list.append(DayunPeriod(
            stem=du_stem,
            branch=du_branch,
            ten_god=ten_god,
            start_age=d.getStartAge(),
            end_age=d.getEndAge(),
            start_year=d.getStartYear(),
            end_year=d.getEndYear(),
        ))

    # === 9. 旬空 ===
    kongwang_str = bazi.getDayXunKong()
    kongwang = [kongwang_str[0], kongwang_str[1]] if kongwang_str and len(kongwang_str) >= 2 else []

    # === 10. 命宫 / 胎元 ===
    minggong = bazi.getMingGong()
    taiyuan = bazi.getTaiXi()

    # === 11. 神煞（自定义模块） ===
    shensha = calculate_shensha(four_pillars)

    # === 12. 五行力量（自定义模块） ===
    wuxing_score = calculate_wuxing_score(pillars_raw, all_hidden_stems)

    # === 13. 用神分析（自定义模块） ===
    yongshen = determine_yongshen(
        day_master_stem=day_master_stem,
        four_pillars=pillars_raw,
        hidden_stems_list=all_hidden_stems,
        wuxing_score={
            "金": wuxing_score.jin,
            "木": wuxing_score.mu,
            "水": wuxing_score.shui,
            "火": wuxing_score.huo,
            "土": wuxing_score.tu,
        },
    )

    return BaziChart(
        four_pillars=four_pillars,
        day_master=day_master_stem,
        gender=gender,
        dayun=dayun_list,
        shensha=shensha,
        kongwang=kongwang,
        wuxing_score=wuxing_score,
        yongshen=yongshen,
        minggong=minggong,
        taiyuan=taiyuan,
    )
