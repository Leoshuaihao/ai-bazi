"""断未来模块 - 基于校准命盘预测未来运势

支持两种模式：
1. AI 生成（有 DEEPSEEK_API_KEY 时）：调用 DeepSeek API
2. Mock 模板（无 API Key 时）：基于大运流年规则生成模板化预测

四个维度：事业 / 财运 / 婚姻 / 健康
每个维度包含：总体趋势、关键年份、具体建议
"""

import os
import json
import re
import datetime

from models import BaziChart
from rules.wuxing import WUXING_MAP, HIDDEN_STEMS_MAP, get_sheng, get_ke, get_i_sheng, get_i_ke
from services.deepseek_client import call_deepseek
from services.liunian import get_liunian_list, classify_liunian


# ============================================================
# 辅助函数
# ============================================================

def _find_current_dayun(dayun: list, current_year: int = None) -> dict:
    """找到当前所处的大运。

    Args:
        dayun: 大运列表（Dict 或 DayunPeriod 对象）
        current_year: 当前年份，默认取系统年份

    Returns:
        当前大运信息 dict，如果找不到返回第一个大运
    """
    if current_year is None:
        current_year = datetime.datetime.now().year

    for du in dayun:
        if hasattr(du, "start_year"):
            sy = du.start_year
            ey = du.end_year
        else:
            sy = du.get("start_year", 0)
            ey = du.get("end_year", 0)

        if sy <= current_year <= ey:
            return {
                "stem": du.stem if hasattr(du, "stem") else du.get("stem", ""),
                "branch": du.branch if hasattr(du, "branch") else du.get("branch", ""),
                "ten_god": du.ten_god if hasattr(du, "ten_god") else du.get("ten_god", ""),
                "start_age": du.start_age if hasattr(du, "start_age") else du.get("start_age", 0),
                "end_age": du.end_age if hasattr(du, "end_age") else du.get("end_age", 0),
                "start_year": sy,
                "end_year": ey,
            }

    # 找不到当前大运，返回第一个
    if dayun:
        du = dayun[0]
        return {
            "stem": du.stem if hasattr(du, "stem") else du.get("stem", ""),
            "branch": du.branch if hasattr(du, "branch") else du.get("branch", ""),
            "ten_god": du.ten_god if hasattr(du, "ten_god") else du.get("ten_god", ""),
            "start_age": du.start_age if hasattr(du, "start_age") else du.get("start_age", 0),
            "end_age": du.end_age if hasattr(du, "end_age") else du.get("end_age", 0),
            "start_year": du.start_year if hasattr(du, "start_year") else du.get("start_year", 0),
            "end_year": du.end_year if hasattr(du, "end_year") else du.get("end_year", 0),
        }

    return {
        "stem": "", "branch": "", "ten_god": "",
        "start_age": 0, "end_age": 0, "start_year": 0, "end_year": 0,
    }


def _get_upcoming_dayun(dayun: list, current_year: int = None) -> list[dict]:
    """获取未来大运列表（包含当前大运和之后的大运）。

    Args:
        dayun: 大运列表
        current_year: 当前年份

    Returns:
        未来大运信息列表
    """
    if current_year is None:
        current_year = datetime.datetime.now().year

    upcoming = []
    for du in dayun:
        if hasattr(du, "start_year"):
            ey = du.end_year
            sy = du.start_year
        else:
            ey = du.get("end_year", 0)
            sy = du.get("start_year", 0)

        # 包含当前及未来大运
        if ey >= current_year - 5:  # 稍微前推，覆盖当前边缘
            upcoming.append({
                "stem": du.stem if hasattr(du, "stem") else du.get("stem", ""),
                "branch": du.branch if hasattr(du, "branch") else du.get("branch", ""),
                "ten_god": du.ten_god if hasattr(du, "ten_god") else du.get("ten_god", ""),
                "start_age": du.start_age if hasattr(du, "start_age") else du.get("start_age", 0),
                "end_age": du.end_age if hasattr(du, "end_age") else du.get("end_age", 0),
                "start_year": sy,
                "end_year": ey,
            })

    return upcoming[:5]  # 最多5步大运


def _get_key_years_from_dayun(dayun: list, day_master_stem: str, yongshen: dict) -> list[str]:
    """从大运交接和用神关系提取关键年份。

    Returns:
        关键年份字符串列表（如 ["2027", "2030", "2035"]）
    """
    import datetime
    current_year = datetime.datetime.now().year
    years = [current_year]  # 当前年必在关键年份中

    ys_wx = yongshen.get("primary", "") if isinstance(yongshen, dict) else getattr(yongshen, "primary", "")
    ys_ji = yongshen.get("ji_shen", "") if isinstance(yongshen, dict) else getattr(yongshen, "ji_shen", "")
    dm_wx = WUXING_MAP.get(day_master_stem, "")

    for du in dayun:
        if hasattr(du, "start_year"):
            sy = du.start_year
            ey = du.end_year
            stem = du.stem
            branch = du.branch
        else:
            sy = du.get("start_year", 0)
            ey = du.get("end_year", 0)
            stem = du.get("stem", "")
            branch = du.get("branch", "")

        # 大运交接年
        if sy >= current_year and sy not in years:
            years.append(sy)

        # 大运天干为用神
        stem_wx = WUXING_MAP.get(stem, "")
        if stem_wx == ys_wx and sy >= current_year and sy not in years:
            years.append(sy)

        # 大运天干为忌神（需注意的年份）
        if stem_wx == ys_ji and sy >= current_year and sy not in years:
            years.append(sy)

        if len(years) >= 5:
            break

    return sorted([str(y) for y in years[:5]])


# ============================================================
# 板块差异化选年（按十神 + 维度规则）
# ============================================================

# 每个维度优先选哪些十神流年
DIM_TEN_GOD = {
    "career":       ["正官", "七杀", "正印", "偏印"],   # 官杀主事业晋升，印星主资历
    "wealth":       ["正财", "偏财", "食神", "伤官"],   # 财星主进财，食伤主生财
    "marriage":     ["正财", "偏财", "正官", "七杀"],   # 财星(男命妻)、官杀(女命夫)
    "relationship": ["正印", "偏印"],                   # 印星主贵人、长辈助力
    "health":       [],                                 # 用忌神判断，不按十神
}

def _get_dim_key_years(
    dayun: list,
    day_master_stem: str,
    yongshen: dict,
    dim: str,
    current_dayun: dict = None,
    gender: str = "male",
) -> list[str]:
    """按维度独立选关键年份——避免5个板块返回完全相同的key_years。

    选年规则：
    - career：流年天干十神为 正官/七杀/正印/偏印
    - wealth：流年天干十神为 正财/偏财/食神/伤官
    - marriage：男命看 正财/偏财，女命看 正官/七杀
    - relationship：流年天干十神为 正印/偏印（贵人星）
    - health：忌神五行流年 或 冲克日主的流年

    Args:
        dayun: 大运列表
        day_master_stem: 日主天干
        yongshen: 用神信息
        dim: 维度名 career/wealth/marriage/relationship/health
        current_dayun: 当前大运（限定年份范围）
        gender: 性别，marriage 维度按性别区分

    Returns:
        该维度的关键年份字符串列表（2-3个）
    """
    import datetime
    current_year = datetime.datetime.now().year

    ys_wx = yongshen.get("primary", "") if isinstance(yongshen, dict) else getattr(yongshen, "primary", "")
    ys_ji = yongshen.get("ji_shen", "") if isinstance(yongshen, dict) else getattr(yongshen, "ji_shen", "")

    # 限定在当前大运范围内选年
    du_start = current_year
    du_end = current_year + 10
    if current_dayun:
        du_start = current_dayun.get("start_year", current_year)
        du_end = current_dayun.get("end_year", current_year + 10)
    effective_start = max(du_start, current_year)

    # 婚姻维度按性别筛选目标十神
    target_tg = DIM_TEN_GOD.get(dim, [])
    if dim == "marriage":
        target_tg = ["正财", "偏财"] if gender == "male" else ["正官", "七杀"]

    # 60甲子
    GAN_C = ["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸"]
    # 十神计算（复用 liunian._calc_ten_god 逻辑，避免循环 import）
    _WUXING = {"甲": "木", "乙": "木", "丙": "火", "丁": "火", "戊": "土",
               "己": "土", "庚": "金", "辛": "金", "壬": "水", "癸": "水"}
    _YINYANG = {"甲": 1, "乙": 0, "丙": 1, "丁": 0, "戊": 1,
                "己": 0, "庚": 1, "辛": 0, "壬": 1, "癸": 0}
    _SHENG = {"金": "土", "木": "水", "水": "金", "火": "木", "土": "火"}
    _I_SHENG = {"金": "水", "木": "火", "水": "木", "火": "土", "土": "金"}
    _I_KE = {"金": "木", "木": "土", "水": "火", "火": "金", "土": "水"}
    _KE = {"金": "火", "木": "金", "水": "土", "火": "水", "土": "木"}

    def _tg(dm: str, other: str) -> str:
        dm_wx = _WUXING.get(dm, "")
        ot_wx = _WUXING.get(other, "")
        if not dm_wx or not ot_wx:
            return ""
        same_yy = _YINYANG[dm] == _YINYANG[other]
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

    dm_wx = _WUXING.get(day_master_stem, "")

    # 遍历大运范围内所有流年，按维度规则筛
    matched = []
    for y in range(effective_start, du_end + 1):
        idx = (y - 4) % 60
        stem = GAN_C[idx % 10]
        stem_wx = _WUXING.get(stem, "")
        tg = _tg(day_master_stem, stem)

        if dim == "health":
            # 忌神五行流年 或 冲克日主流年
            is_jishen = (stem_wx == ys_ji)
            # 冲克日主：KE[dm_wx] 即克日主的五行
            is_chong_ke = (stem_wx == _KE.get(dm_wx, ""))
            if is_jishen or is_chong_ke:
                matched.append(str(y))
        else:
            if tg in target_tg:
                matched.append(str(y))

        if len(matched) >= 3:
            break

    # 兜底：若该维度匹配不足，用大运范围内不同偏移位置的年份补足
    # 各维度用不同偏移，避免兜底时趋同
    DIM_OFFSETS = {
        "career":       [0, 1, 2],        # 大运起始段
        "wealth":       [3, 4, 5],        # 中前段
        "marriage":     [6, 7],           # 中后段
        "relationship": [8, 9],           # 后段
        "health":       [1, 5, 9],        # 分散
    }
    if len(matched) < 2:
        offsets = DIM_OFFSETS.get(dim, [0, 1, 2])
        all_years = list(range(effective_start, du_end + 1))
        for off in offsets:
            if off < len(all_years):
                y = str(all_years[off])
                if y not in matched:
                    matched.append(y)
            if len(matched) >= 3:
                break

    return sorted(matched[:3])


def _build_dayun_summary(dayun: list, current_dayun: dict, birth_year: int) -> str:
    """构建大运摘要文本供 prompt 使用。"""
    current_year = datetime.datetime.now().year
    age = current_year - birth_year

    lines = [
        f"命主当前年龄：{age}岁（{current_year}年）",
    ]
    if current_dayun.get("stem"):
        lines.append(
            f"当前所处大运：{current_dayun['stem']}{current_dayun['branch']}"
            f"（{current_dayun['ten_god']}运），"
            f"{current_dayun['start_year']}年-{current_dayun['end_year']}年"
            f"（{current_dayun['start_age']}岁-{current_dayun['end_age']}岁）"
        )

    lines.append("未来大运：")
    upcoming = _get_upcoming_dayun(dayun, current_year)
    for du in upcoming:
        lines.append(
            f"  {du['stem']}{du['branch']}（{du['ten_god']}运），"
            f"{du['start_year']}-{du['end_year']}年"
            f"（{du['start_age']}-{du['end_age']}岁）"
        )

    return "\n".join(lines)


# ============================================================
# Mock 模板生成（无 API Key 时使用）
# ============================================================

def _mock_career_forecast(chart: BaziChart, chart_data: dict, current_dayun: dict) -> dict:
    """Mock 事业运预测。"""
    dm = chart.day_master
    dm_wx = WUXING_MAP.get(dm, "土")
    ys = chart.yongshen
    ys_wx = ys.primary
    pattern = ys.pattern

    # 用神五行 → 事业方向
    CAREER_DIRECTION = {
        "金": "适合需要决断力和纪律性的领域，如金融、法律、管理、工程技术",
        "木": "适合需要创造力和沟通力的领域，如教育、文化、设计、医疗健康",
        "水": "适合需要智慧和变通力的领域，如咨询、贸易、物流、信息技术",
        "火": "适合需要热情和表现力的领域，如传媒、演艺、营销、公共服务",
        "土": "适合需要稳定和协调力的领域，如房地产、建筑、农业、行政管理",
    }

    direction = CAREER_DIRECTION.get(ys_wx, "适合发挥自身优势的多元化领域")

    cur_ten_god = current_dayun.get("ten_god", "")
    if "官" in cur_ten_god or "杀" in cur_ten_god:
        trend = "当前大运走官杀运，事业上压力与机遇并存，适合在体制内或管理岗位上深耕。"
        trend += "未来几年宜稳中求进，不宜频繁跳槽或激进创业。"
    elif "财" in cur_ten_god:
        trend = "当前大运走财运，事业发展与财富积累密切相关。适合开拓市场、拓展业务，"
        trend += "但需注意不要因追求短期利益而忽视长期规划。"
    elif "印" in cur_ten_god:
        trend = "当前大运走印运，适合学习深造、积累资源和人脉。"
        trend += "事业上宜以稳为主，打好基础，等待合适时机再发力。"
    elif "食" in cur_ten_god or "伤" in cur_ten_god:
        trend = "当前大运走食伤运，创意和技术能力突出，适合发挥个人专长。"
        trend += "可能有创业或转型的想法，但需谨慎评估风险。"
    else:
        trend = "当前大运走比劫运，竞争较为激烈，需注意人际关系和团队协作。"
        trend += "适合与志同道合者合作，资源共享，互利共赢。"

    key_years = _get_dim_key_years(chart.dayun, dm, ys, "career", current_dayun)
    years_str = "、".join(key_years[:3]) if key_years else "未来3-5年"
    advice = (
        f"{direction}。{years_str}是事业发展的重要窗口期，"
        f"建议提前做好准备，抓住机遇。同时注意保持{'低调' if '劫' in cur_ten_god else '稳健'}，"
        f"避免因好大喜功而陷入困境。《滴天髓》云："
        f"知进退存亡而不失其正者，其唯圣人乎。顺时应势，方为长久之道。"
    )

    return {
        "summary": trend,
        "key_years": key_years,
        "advice": advice,
    }


def _mock_wealth_forecast(chart: BaziChart, chart_data: dict, current_dayun: dict) -> dict:
    """Mock 财运预测。"""
    dm = chart.day_master
    dm_wx = WUXING_MAP.get(dm, "土")
    ys = chart.yongshen
    ys_wx = ys.primary
    ys_ji = ys.ji_shen

    cur_ten_god = current_dayun.get("ten_god", "")

    # 根据当前大运十神判断财运趋势
    if "财" in cur_ten_god:
        trend = "当前大运走财运，正财偏财皆有进益之时。收入渠道可能增多，"
        trend += "理财投资方面容易看到回报。但需注意偏财不宜贪多，正财最为稳妥。"
    elif "官" in cur_ten_god or "杀" in cur_ten_god:
        trend = "当前大运走官杀运，财运以正财为主，通过职位晋升或事业拓展带来收入增长。"
        trend += "不建议高风险投资，稳健理财为上策。"
    elif "印" in cur_ten_god:
        trend = "当前大运走印运，财运较为平稳，适合做长期投资和储蓄。"
        trend += "大额消费和投资需三思而行，不宜轻信他人推荐的投资项目。"
    elif "食" in cur_ten_god or "伤" in cur_ten_god:
        trend = "当前大运走食伤运，可通过专业技能或创意获得收入。"
        trend += "副业或兼职可能带来额外收益，但需注意开源节流，避免冲动消费。"
    else:
        trend = "当前大运走比劫运，财运方面需注意合伙投资的风险。"
        trend += "建议以个人能力赚钱为主，避免与他人有过多金钱往来。理财宜保守。"

    key_years = _get_dim_key_years(chart.dayun, dm, ys, "wealth", current_dayun)
    years_str = "、".join(key_years[:3]) if key_years else "未来3-5年"
    advice = (
        f"财运方面，{years_str}是值得重点关注的时期。"
        "建议遵循'开源节流、稳中求进'的原则，"
        f"忌神{ys_ji}旺的年份要特别注意财务风险管控。"
        "《子平真诠》：财为养命之源，不可不察。理财之道，在于量入为出，知足常乐。"
    )

    return {
        "summary": trend,
        "key_years": key_years,
        "advice": advice,
    }


def _mock_marriage_forecast(chart: BaziChart, chart_data: dict, current_dayun: dict) -> dict:
    """Mock 婚姻运预测。"""
    dm = chart.day_master
    dm_wx = WUXING_MAP.get(dm, "土")
    day_branch = chart.four_pillars["day"].branch
    day_stem = dm

    cur_ten_god = current_dayun.get("ten_god", "")

    # 日支五行 → 感情特征
    branch_wx = WUXING_MAP.get(day_branch, "")
    if branch_wx == get_ke(dm_wx):
        base = "日坐官杀，配偶在关系中可能较为主动，婚姻中需注意沟通方式。"
    elif branch_wx == get_i_ke(dm_wx):
        base = "日坐财星，婚姻与物质生活关系密切，务实的态度有助于感情稳定。"
    elif branch_wx == get_sheng(dm_wx):
        base = "日坐印星，在感情中容易得到对方的理解和支持，婚姻生活较为温馨。"
    elif branch_wx == dm_wx:
        base = "日坐比肩，夫妻双方性格相似，如同朋友般相处，但需注意避免因个性相冲而产生摩擦。"
    else:
        base = "日坐食伤，感情生活中富有情趣和创造力，但需注意表达方式，避免无意中伤害对方。"

    if "官" in cur_ten_god or "杀" in cur_ten_god:
        trend = base + "当前大运走官杀运，已婚者与伴侣关系可能面临一些考验，"
        trend += "需多沟通、少计较。单身者有机会遇到心仪对象，但需冷静观察，不宜草率决定。"
    elif "财" in cur_ten_god:
        trend = base + "当前大运走财运，感情与物质生活密切相关。"
        trend += "已婚者宜共同规划家庭财务，增进感情；单身者可能通过工作或社交圈认识合适的对象。"
    elif "印" in cur_ten_god:
        trend = base + "当前大运走印运，感情生活较为稳定平和。"
        trend += "已婚者家庭和睦，单身者可能通过长辈介绍认识对象。适合谈婚论嫁。"
    elif "食" in cur_ten_god or "伤" in cur_ten_god:
        trend = base + "当前大运走食伤运，感情上可能有一些浪漫邂逅。"
        trend += "已婚者需注意保持婚姻的新鲜感；单身者有机会遇到志趣相投之人。"
    else:
        trend = base + "当前大运走比劫运，感情中可能有竞争或第三方的干扰。"
        trend += "建议在感情中保持自信，同时给予对方足够的空间和信任。"

    key_years = _get_dim_key_years(chart.dayun, dm, chart.yongshen, "marriage", current_dayun, chart.gender)
    years_str = "、".join(key_years[:3]) if key_years else "未来3-5年"
    advice = (
        f"感情方面，{years_str}是感情发展的关键时期。"
        f"《渊海子平》：夫妇之道，阴阳和合。婚姻重在互相理解和包容，"
        f"命理只是参考，真正的幸福需要两人共同经营。"
    )

    return {
        "summary": trend,
        "key_years": key_years,
        "advice": advice,
    }


def _mock_health_forecast(chart: BaziChart, chart_data: dict, current_dayun: dict) -> dict:
    """Mock 健康运预测。"""
    dm = chart.day_master
    dm_wx = WUXING_MAP.get(dm, "土")
    ys = chart.yongshen
    ys_ji = ys.ji_shen

    # 忌神五行 → 健康关注
    HEALTH_FOCUS = {
        "金": "肺部和呼吸系统，注意呼吸道疾病、皮肤问题。建议多做有氧运动，避免长时间处在空气质量差的环境",
        "木": "肝胆和筋骨方面，注意情绪管理，避免长期熬夜。建议规律作息，适当进行拉伸运动",
        "水": "肾脏和泌尿系统，注意保暖和水分补充。建议避免过度劳累，保持良好的饮水习惯",
        "火": "心脏和血液循环，注意控制情绪波动，避免过度兴奋或焦虑。建议定期检查心血管健康",
        "土": "脾胃和消化系统，注意饮食规律，避免暴饮暴食。建议少食多餐，多吃易消化的食物",
    }

    focus = HEALTH_FOCUS.get(ys_ji, "整体健康平衡，注意劳逸结合，保持良好的生活习惯")

    cur_ten_god = current_dayun.get("ten_god", "")
    if "官" in cur_ten_god or "杀" in cur_ten_god:
        trend = "当前大运走官杀运，压力较大，需特别关注心理健康。"
    elif "财" in cur_ten_god:
        trend = "当前大运走财运，整体健康状况尚可，但需注意不要因忙于赚钱而忽视身体。"
    elif "印" in cur_ten_god:
        trend = "当前大运走印运，利于养身调理，是调养身体的好时机。"
    elif "食" in cur_ten_god or "伤" in cur_ten_god:
        trend = "当前大运走食伤运，精力较为充沛，但需注意不要过度消耗。"
    else:
        trend = "当前大运走比劫运，身体素质总体不错，但竞争压力可能影响精神状态。"

    trend += f"在忌神{ys_ji}旺的年份，要特别关注健康。{focus}。"

    key_years = _get_dim_key_years(chart.dayun, dm, ys, "health", current_dayun)
    years_str = "、".join(key_years[:3]) if key_years else "未来3-5年"
    advice = (
        f"健康方面，{years_str}需特别注意身体状况。"
        f"《黄帝内经》：上工治未病，不治已病。预防胜于治疗，"
        f"建议定期体检，保持良好作息，适度运动。身心健康是一切的基础。"
    )

    return {
        "summary": trend,
        "key_years": key_years,
        "advice": advice,
    }


def _mock_relationship_forecast(chart: BaziChart, chart_data: dict, current_dayun: dict) -> dict:
    """Mock 贵人运预测。

    贵人运以印星（生我者）为核心——印星主长辈、师长、提携之人。
    """
    dm = chart.day_master
    dm_wx = WUXING_MAP.get(dm, "土")
    ys = chart.yongshen
    ys_wx = ys.primary if hasattr(ys, "primary") else ys.get("primary", "")

    cur_ten_god = current_dayun.get("ten_god", "")

    # 印星五行 → 贵人方向
    sheng_wx = get_sheng(dm_wx)  # 生我者=印星
    GUIMAP = {
        "金": "贵人多来自法律、金融、管理领域的长辈或上级",
        "木": "贵人多来自教育、医疗、文化领域的师长或前辈",
        "水": "贵人多来自智慧型行业，如咨询、策划、研究的智者",
        "火": "贵人多来自传媒、演艺、公共服务领域的热情之人",
        "土": "贵人多来自房地产、建筑、农业领域的稳健之人",
    }
    gui_hint = GUIMAP.get(sheng_wx, "贵人来自各方，宜广结善缘")

    if "印" in cur_ten_god:
        trend = "当前大运走印运，贵人运旺盛。长辈、师长愿意提携，"
        trend += "宜虚心请教，把握学习机会。" + gui_hint + "。"
    elif "官" in cur_ten_god or "杀" in cur_ten_god:
        trend = "当前大运走官杀运，贵人多来自职场上级或权威人士。"
        trend += "认真履职可得赏识，但需注意官杀亦主压力，宜以德服人。"
    elif "财" in cur_ten_god:
        trend = "当前大运走财运，贵人多与利益往来相关。"
        trend += "合作伙伴可能带来机会，但需明辨利弊，避免因利失义。"
    elif "食" in cur_ten_god or "伤" in cur_ten_god:
        trend = "当前大运走食伤运，贵人多来自同辈或晚辈。"
        trend += "以才情待人，可得知音；但需注意言语分寸，避免恃才傲物。"
    else:
        trend = "当前大运走比劫运，贵人运较弱，同辈多为竞争者而非助力。"
        trend += "宜独立自强，广结善缘，等待印星流年再求贵人。"

    key_years = _get_dim_key_years(chart.dayun, dm, ys, "relationship", current_dayun)
    years_str = "、".join(key_years[:3]) if key_years else "未来3-5年"
    advice = (
        f"贵人运方面，{years_str}是结交贵人、获得提携的关键时期。"
        f"《滴天髓》：贵人者，助我者也。印星当令，贵人自至。"
        f"宜谦逊有礼，多结善缘，贵人在德不在求。"
    )

    return {
        "summary": trend,
        "key_years": key_years,
        "advice": advice,
    }


def _generate_mock_structured(
    chart: BaziChart, chart_data: dict, current_dayun: dict, current_year: int
) -> dict:
    """生成 Mock 模式下的结构化字段（current_dayun_analysis, yearly_forecast 等）。

    基于规则引擎和流年数据，生成结构化的未来运势分析，
    确保没有 AI API Key 时也能提供丰富的信息密度。
    """
    dm = chart.day_master
    ys = chart.yongshen
    ys_wx = ys.primary if isinstance(ys, dict) else (getattr(ys, "primary", ""))
    ys_ji = ys.ji_shen if isinstance(ys, dict) else (getattr(ys, "ji_shen", ""))
    pattern = ys.pattern if isinstance(ys, dict) else (getattr(ys, "pattern", ""))

    du_stem = current_dayun.get("stem", "")
    du_branch = current_dayun.get("branch", "")
    du_ten_god = current_dayun.get("ten_god", "")
    du_start = current_dayun.get("start_year", 0)
    du_end = current_dayun.get("end_year", 0)

    # 1. 当前大运深度分析
    THEME_MAP = {
        "正官": ("事业上升期", "适合在职场上稳扎稳打，争取晋升机会"),
        "七杀": ("挑战期", "机遇与压力并存，需谨慎应对，以柔克刚"),
        "正财": ("积累期", "财运稳步上升，适合发展实业和长期投资"),
        "偏财": ("机遇期", "偏财运旺宜开拓副业，但需控制风险"),
        "正印": ("学习期", "适合深造、积累资源和人脉，打好基础"),
        "偏印": ("转型期", "适合专注技术深耕和独立思考，勿随波逐流"),
        "食神": ("创意期", "才艺和创意爆发，适合发挥个人专长"),
        "伤官": ("变革期", "思路活跃，利于创新，但需注意人际关系"),
        "比肩": ("合作期", "适合合伙创业，但竞争也较为激烈"),
        "劫财": ("竞争期", "机遇多但竞争大，需注意合作伙伴和资金管理"),
    }

    theme_info = THEME_MAP.get(du_ten_god, ("稳步发展期", "稳中求进"))
    theme_name = theme_info[0]
    theme_desc = theme_info[1]

    # 判断大运基调
    if "官" in du_ten_god or "杀" in du_ten_god:
        tone = "以稳为主，在体制或管理岗深耕；外有压力，内有定力，守正出奇"
    elif "财" in du_ten_god:
        tone = "积极进取，把握财运窗口；敢于开拓市场，但须量力而行"
    elif "印" in du_ten_god:
        tone = "韬光养晦，厚积薄发；以学习和积累为主，不急于求成"
    elif "食" in du_ten_god or "伤" in du_ten_god:
        tone = "发挥才华，锐意创新；敢于突破，但注意分寸和表达方式"
    else:
        tone = "广结善缘，合作共赢；借助团队力量，避免孤军奋战"

    current_dayun_analysis = {
        "dayun_info": f"{du_stem}{du_branch}运（{du_ten_god}）{du_start}-{du_end}年",
        "overall_theme": f"{theme_name}——{theme_desc}",
        "detailed_analysis": (
            f"命主当前正处于{du_stem}{du_branch}运（{du_ten_god}运），{du_start}年至{du_end}年。"
            f"此运天干{du_stem}、地支{du_branch}，{du_ten_god}星当令，"
            f"总体基调为{tone}。"
            f"从格局来看，命主为{pattern}格局，用神取{ys_wx}，忌神为{ys_ji}。"
            f"此大运中，宜把握用神{ys_wx}旺的年份积极进取，"
            f"忌神{ys_ji}旺的年份则宜保守防守、积蓄力量。"
            f"人生如四季轮转，此运恰如{'春夏之交' if ys_wx in ('木', '火') else '秋冬之季' if ys_wx in ('金', '水') else '四季调和'}，"
            f"顺时而动方能事半功倍。"
        ),
        "quote": "《滴天髓》：\"知进退存亡而不失其正者，其唯圣人乎。\"顺时应势，方为长久之道。",
    }

    # 2. 未来流年逐年分析
    yongshen_wx = ys_wx if ys_wx else ""
    ji_shen_wx = ys_ji if ys_ji else ""
    liunian_list = get_liunian_list(current_year, count=5)

    TEN_GOD_KEY_EVENT = {
        "正官": "事业：职场晋升或权责变动，宜主动承担责任",
        "七杀": "事业：压力与机遇并存，下半年防小人，宜低调行事",
        "正财": "财运：收入稳步增长，适合做长期理财规划",
        "偏财": "财运：偏财运旺，注意投资机会，但控制风险",
        "正印": "学业/贵人：学习进修良机，长辈贵人相助",
        "偏印": "思考/规划：适合深度学习和技能提升，少说多做",
        "食神": "创意/人际：才艺发挥，人际关系顺畅，宜社交拓展",
        "伤官": "创新/注意：思路活跃利于创新，但注意言行分寸",
        "比肩": "合作/竞争：适合团队协作，注意竞争关系",
        "劫财": "财务/人际：注意合伙风险，避免冲动投资",
    }

    TEN_GOD_ADVICE = {
        "正官": "上半年稳定现有岗位，下半年关注晋升机会",
        "七杀": "以守为攻，减少不必要的人际冲突，注意合同细节",
        "正财": "开源节流，把握上半年收入增长期，年终做财务复盘",
        "偏财": "可适当关注副业机会，但投资额不超过总资产的30%",
        "正印": "上半年适合报班学习，下半年贵人运强利于社交",
        "偏印": "春季制定全年规划，专注一个领域做深度积累",
        "食神": "春季多社交拓人脉，夏季创意产出高峰期",
        "伤官": "注意春秋两季口舌是非，把创造力用在工作上而非人际上",
        "比肩": "与志同道合者组队，但保持独立判断力",
        "劫财": "谨慎合伙人关系，大额支出需多方确认",
    }

    yearly_forecast = []
    for ln in liunian_list:
        year = ln["year"]
        ganzhi = ln["ganzhi"]
        stem = ln["stem"]
        branch = ln["branch"]

        if yongshen_wx and ji_shen_wx:
            label_info = classify_liunian(ln, dm, yongshen_wx, ji_shen_wx)
        else:
            label_info = {"label": "平年", "ten_god": "", "advice": ""}

        ten_god = label_info.get("ten_god", "")
        label = label_info.get("label", "平年")
        key_event = TEN_GOD_KEY_EVENT.get(ten_god, f"平稳发展：按部就班，打好基础")
        advice = TEN_GOD_ADVICE.get(ten_god, "稳扎稳打，保持节奏")

        yearly_forecast.append({
            "year": year,
            "ganzhi": ganzhi,
            "ten_god": ten_god,
            "label": label,
            "key_event": key_event,
            "advice": advice,
        })

    # 3. 大运时间线概览
    upcoming = _get_upcoming_dayun(chart.dayun, current_year)
    dayun_timeline = []
    theme_order = ["积累期", "发展期", "收获期", "稳固期", "转型期"]
    for i, du in enumerate(upcoming[:3]):
        theme = theme_order[min(i, len(theme_order) - 1)]
        # 找关键窗口
        key_years = []
        # 每个大运的起运年和中运年是关键窗口
        sy = du.get("start_year", 0)
        ey = du.get("end_year", 0)
        if sy:
            key_years.append(str(sy))
            mid = sy + (ey - sy) // 2
            if mid != sy:
                key_years.append(str(mid))

        dayun_timeline.append({
            "dayun": f"{du['stem']}{du['branch']}运（{du['ten_god']}）{sy}-{ey}年",
            "theme": theme,
            "key_window": "、".join(key_years[:2]),
        })

    # 4. 趋吉避凶指南
    ys_health = {
        "金": "忌神金旺的年份注意呼吸系统和皮肤健康，秋冬季节减少熬夜",
        "木": "忌神木旺的春季注意肝胆和情绪管理，避免长期熬夜伤肝",
        "水": "忌神水旺的冬季注意肾脏和泌尿系统，保暖防寒，多饮温水",
        "火": "忌神火旺的夏季注意心脏和血压，控制情绪波动",
        "土": "忌神土旺的长夏季节注意脾胃消化，饮食规律，少食多餐",
    }
    health_focus = ys_health.get(ys_ji, "注意劳逸结合，定期体检，保持良好的生活习惯")

    actionable_guide = {
        "career": [
            {
                "timing": f"{current_year}-{current_year + 2}年",
                "action": f"在当前{du_ten_god}大运中，宜{'深耕专业领域' if '印' in du_ten_god else '积极开拓市场' if '财' in du_ten_god else '稳步推进事业'}",
                "reason": f"大运{du_ten_god}星主导，{'学习积累为先' if '印' in du_ten_god else '财运助事业' if '财' in du_ten_god else '宜稳中求进'}",
            },
            {
                "timing": f"用神{ys_wx}旺年",
                "action": "主动出击，把握用神流年的事业机会",
                "reason": f"用神{ys_wx}当令，天地之气助身，运势上扬",
            },
        ],
        "wealth": [
            {
                "timing": f"{current_year}-{current_year + 3}年",
                "action": "以正财为主，偏财为辅，稳健理财，避免高风险投机",
                "reason": f"大运{du_ten_god}期间，财运以{'正财稳步增长' if '财' in du_ten_god else '正财为主'}",
            },
            {
                "timing": f"忌神{ys_ji}旺年",
                "action": "提前做好财务规划，控制开支，不轻易借贷担保",
                "reason": f"忌神{ys_ji}当令，财运易有波动，保守为上",
            },
        ],
        "relationship": [
            {
                "timing": "未来3年",
                "action": "加强沟通，多换位思考；单身者多参加社交活动拓展圈层",
                "reason": "感情需要经营，命理只是参考，主动付出才是关键",
            },
        ],
        "health": [
            {
                "timing": f"忌神{ys_ji}旺年",
                "action": health_focus,
                "reason": f"忌神{ys_ji}当令，五行失衡易引发对应脏腑不适",
            },
            {
                "timing": "每年换季时节",
                "action": "注意养生调理，春养肝、夏养心、秋养肺、冬养肾",
                "reason": "《黄帝内经》：\"上工治未病\"，预防胜于治疗",
            },
        ],
    }

    return {
        "current_dayun_analysis": current_dayun_analysis,
        "yearly_forecast": yearly_forecast,
        "dayun_timeline": dayun_timeline,
        "actionable_guide": actionable_guide,
    }


def generate_mock_forecast(chart: BaziChart, chart_data: dict, current_dayun: dict = None) -> dict:
    """基于大运流年规则生成模板化未来运势预测。

    Args:
        chart: BaziChart 对象
        chart_data: 排盘数据的字典形式
        current_dayun: 指定大运（可选），不传则自动找当前大运

    Returns:
        forecast dict 包含五个维度
    """
    import datetime
    current_year = datetime.datetime.now().year
    birth_year = chart_data.get("four_pillars", {}).get("year", {}).get("stem", "")
    # 从 chart_data 计算出生年份
    birth_year = 1990  # fallback
    if chart_data.get("dayun"):
        first_du = chart_data["dayun"][0]
        sy = first_du.get("start_year", 0)
        sa = first_du.get("start_age", 0)
        if sy and sa is not None:
            birth_year = sy - sa

    if current_dayun is None:
        current_dayun = _find_current_dayun(chart.dayun, current_year)
    # 统一转 dict 方便后续取值
    if hasattr(current_dayun, "model_dump"):
        current_dayun = current_dayun.model_dump()

    forecast = {
        "career": _mock_career_forecast(chart, chart_data, current_dayun),
        "wealth": _mock_wealth_forecast(chart, chart_data, current_dayun),
        "marriage": _mock_marriage_forecast(chart, chart_data, current_dayun),
        "relationship": _mock_relationship_forecast(chart, chart_data, current_dayun),
        "health": _mock_health_forecast(chart, chart_data, current_dayun),
    }

    return forecast


# ============================================================
# AI 生成（有 API Key 时）
# ============================================================

FORECAST_SYSTEM_PROMPT = """你是精通子平派的命理师。请根据命主的八字、大运、流年数据，输出结构化的未来运势分析。

## 输出结构

### 1. 当前大运深度分析（最重要，200字以上）
- 当前处于哪步大运（干支+十神+起止年份），这步大运对命主意味着什么
- 这步大运的总体基调：是进是退、是攻是守
- 结合命主的年龄和人生阶段给出针对性建议

### 2. 未来流年逐年分析（未来5年，每年80-120字）
- 每年标注：干支、十神、用神年/忌神年
- 该年在事业/财运/婚姻/健康四个维度中最关键的1-2件事
- 具体建议（做什么、什么时候做、为什么是这个时间）

### 3. 大运时间线概览（未来3步大运，每步50字）
- 每步大运的主题（如"积累期""发展期""收获期"）
- 关键年份窗口

### 4. 趋吉避凶指南
- 基于用神/忌神的具体生活建议
- 必须包含可执行的具体行动（不是"注意健康"，而是"2028年忌神年，下半年注意脾胃，秋季减少应酬"）
- 引用典籍原文

## 重要约束
- 所有年份判断必须基于提供的精确流年数据，不要自己编造年份干支
- 用神年标注 ✅，忌神年标注 ⚠️
- summary 用日常语言写1-2句总体趋势，不要出现任何命理术语
- key_actions 是一个字典，key=年份，value=该年具体行动建议
- 建议要具体可操作，不要泛泛而谈
- **每个维度的 score 必须是 0-100 整数**：70-100=吉、40-69=平、0-39=凶。基于该维度在当前大运中的实际吉凶程度客观评分

## 每个维度的 key_years 选年规则（必须严格遵守，不同维度必须选不同的年份）

各维度 key_years 应根据该维度对应的十神流年独立选取，**禁止5个维度返回完全相同的 key_years**：

- **career（事业）**：优先选流年天干十神为「正官/七杀/正印/偏印」的年份——官杀主晋升压力与机遇，印星主资历积累
- **wealth（财富）**：优先选流年天干十神为「正财/偏财/食神/伤官」的年份——财星主进财，食伤主生财之源
- **marriage（婚姻）**：男命优先选「正财/偏财」流年（财为妻星），女命优先选「正官/七杀」流年（官杀为夫星）
- **relationship（贵人）**：优先选流年天干十神为「正印/偏印」的年份——印星主长辈师长提携
- **health（健康）**：优先选忌神五行当令的流年、或冲克日主的流年——这些年份健康需重点关注

⚠️ 硬性要求：5个维度的 key_years 集合必须有差异。如果某年同时符合多个维度，可以共用，但绝不允许5个维度的 key_years 完全相同。

## 输出格式（严格 JSON，不要包含其他内容）

{
  "career": {
    "summary": "用日常语言写1-2句总体趋势，不要出现命理术语",
    "key_years": ["2027", "2030"],
    "key_actions": {"2027": "具体行动建议", "2030": "具体行动建议"},
    "score": 85
  },
  "wealth": {
    "summary": "...",
    "key_years": ["..."],
    "key_actions": {"2028":"行动","2030":"行动"},
    "score": 60
  },
  "marriage": {
    "summary": "...",
    "key_years": ["..."],
    "key_actions": {"2026":"行动","2027":"行动"},
    "score": 70
  },
  "relationship": {
    "summary": "贵人运、合作伙伴、人际助力分析",
    "key_years": ["..."],
    "key_actions": {"2027":"广结善缘","2029":"注意合作"} ,
    "score": 55
  },
  "health": {
    "summary": "...",
    "key_years": ["..."],
    "score": 45,
    "key_actions": {"2028":"定期体检","2031":"注意饮食"} ,
  "current_dayun_analysis": {
    "dayun_info": "戊辰运（偏印）2020-2030",
    "overall_theme": "积累期——适合深耕技术...",
    "detailed_analysis": "200字以上的深度分析",
    "quote": "《XX》原文引用"
  },
  "yearly_forecast": [
    {
      "year": 2027, "ganzhi": "丁未",
      "ten_god": "比肩", "label": "用神年 ✅",
      "key_event": "事业：跳槽黄金窗口，丁火比肩帮身...",
      "advice": "上半年准备，下半年出手，往南方（火旺之地）"
    }
  ],
  "dayun_timeline": [
    {"dayun": "己巳运（正印）2030-2040", "theme": "发展期", "key_window": "2032、2035"}
  ],
  "actionable_guide": {
    "career": [{"timing": "2027下半年", "action": "...", "reason": "..."}],
    "wealth": [],
    "relationship": [],
    "health": []
  },
  "disclaimer": "命理预测仅供参考，人生掌握在自己手中。以上分析基于传统命理学推演，不构成人生决策的唯一依据。"
}"""


def _build_forecast_prompt(
    chart: BaziChart,
    chart_data: dict,
    current_dayun: dict,
    calibration_result: dict = None,
    feedbacks: list = None,
    predictions: list = None,
) -> str:
    """构建用于 AI 预测的 prompt。"""
    import datetime

    current_year = datetime.datetime.now().year

    # 计算出生年份
    birth_year = 1990
    if chart_data.get("dayun"):
        first_du = chart_data["dayun"][0]
        sy = first_du.get("start_year", 0)
        sa = first_du.get("start_age", 0)
        if sy and sa is not None:
            birth_year = sy - sa

    age = current_year - birth_year

    pillars = chart_data.get("four_pillars", {})
    day_master = chart_data.get("day_master", "")
    yongshen = chart_data.get("yongshen", {})
    wuxing_score = chart_data.get("wuxing_score", {})

    lines = ["## 命主基本信息"]
    lines.append(f"日主：{day_master}（五行{WUXING_MAP.get(day_master, '')}）")
    lines.append(f"性别：{'男' if chart.gender == 'male' else '女'}")
    lines.append(f"出生年份：{birth_year}年")
    lines.append(f"当前年龄：{age}岁（{current_year}年）")

    pos_names = {"year": "年柱", "month": "月柱", "day": "日柱", "hour": "时柱"}
    lines.append("\n## 四柱排盘")
    for pos in ["year", "month", "day", "hour"]:
        p = pillars.get(pos, {})
        stem = p.get("stem", "")
        branch = p.get("branch", "")
        stem_tg = p.get("stem_ten_god", "")
        hidden = p.get("hidden_stems", [])
        hidden_str = "、".join([f"{h.get('stem', '')}({h.get('ten_god', '')})" for h in hidden])
        nayin = p.get("nayin", "")
        lines.append(
            f"{pos_names[pos]}：{stem}{branch} "
            f"十神={stem_tg} 藏干=[{hidden_str}] 纳音={nayin}"
        )

    lines.append("\n## 用神与格局")
    ys_primary = yongshen.get("primary", "")
    ys_secondary = yongshen.get("secondary", "")
    ys_ji = yongshen.get("ji_shen", "")
    ys_pattern = yongshen.get("pattern", "")
    ys_strength = yongshen.get("ri_zhu_strength", "")
    lines.append(f"用神：{ys_primary}，喜神：{ys_secondary}，忌神：{ys_ji}")
    lines.append(f"格局：{ys_pattern}，日主强弱：{ys_strength}")

    # 十神分布统计
    tg_counts = {}
    for pos in ["year","month","day","hour"]:
        p = pillars.get(pos,{})
        for tg in [p.get("stem_ten_god",""), p.get("branch_ten_god","")]:
            if tg: tg_counts[tg] = tg_counts.get(tg,0) + 1
    if tg_counts:
        lines.append(f"十神分布：{', '.join(f'{k}{v}次' for k,v in sorted(tg_counts.items(),key=lambda x:-x[1]))}")

    # 日主天干 → 职业倾向推断
    dm_wx = WUXING_MAP.get(day_master,"")
    career_hints = {
        "金":"宜珠宝、金融、精密制造、法律。伤官旺则宜创意表达、设计。正官旺则宜管理、公务员。",
        "木":"宜教育、医疗、环保、文化传播。食神旺则宜艺术、写作。比劫旺则宜团队协作。",
        "水":"宜物流、贸易、传媒、旅游。正财旺则宜经商。七杀旺则宜军警、竞技。",
        "火":"宜能源、餐饮、互联网、演艺。正印旺则宜学术、研究。正财旺则宜销售。",
        "土":"宜地产、建筑、农业、金融中介。正印旺则宜教育、咨询。偏财旺则宜投资。",
    }
    lines.append(f"职业倾向提示：{career_hints.get(dm_wx,'根据命局自行判断')}")

    # 四柱结构简析
    stem_wx = {pos:WUXING_MAP.get(pillars.get(pos,{}).get("stem",""),"") for pos in ["year","month","day","hour"]}
    branch_wx = {pos:WUXING_MAP.get(pillars.get(pos,{}).get("branch",""),"") for pos in ["year","month","day","hour"]}
    lines.append(f"四柱五行：年{stem_wx['year']}{branch_wx['year']} 月{stem_wx['month']}{branch_wx['month']} 日{stem_wx['day']}（日主）{branch_wx['day']} 时{stem_wx['hour']}{branch_wx['hour']}")

    lines.append("\n## 五行力量")
    wl = WUXING_MAP
    ws = wuxing_score
    if ws:
        lines.append(
            f"金={ws.get('jin', 0):.1f}%，木={ws.get('mu', 0):.1f}%，"
            f"水={ws.get('shui', 0):.1f}%，火={ws.get('huo', 0):.1f}%，"
            f"土={ws.get('tu', 0):.1f}%"
        )

    # 大运信息
    lines.append("\n## 大运流年")
    lines.append(_build_dayun_summary(chart.dayun, current_dayun, birth_year))
    # 约束：年份范围（指定大运 ∩ 当前年及以后）
    du_start = current_dayun.get("start_year", current_year)
    du_end = current_dayun.get("end_year", current_year + 10)
    effective_start = max(du_start, current_year)
    lines.append(f"\n**重要约束：当前分析的大运范围是{du_start}-{du_end}年。"
                 f"现在是{current_year}年，断未来只能给{effective_start}年及之后的建议。"
                 f"key_years和key_actions中的年份必须在{effective_start}-{du_end}之间，不得出现过去的年份。**")

    # 流年数据（精确干支 + 用神判断）——只取所选大运范围内的年份
    yongshen_wx = ys_primary if ys_primary else ""
    ji_shen_wx = ys_ji if ys_ji else ""
    du_years = list(range(effective_start, du_end + 1))
    # 60甲子循环：公元4年=甲子
    GAN_C = ["甲","乙","丙","丁","戊","己","庚","辛","壬","癸"]
    ZHI_C = ["子","丑","寅","卯","辰","巳","午","未","申","酉","戌","亥"]
    liunian_list = []
    for y in du_years:
        idx = (y - 4) % 60
        gz = GAN_C[idx % 10] + ZHI_C[idx % 12]
        liunian_list.append({"year": y, "ganzhi": gz})
    # 补充干支的五行和十神
    for ln in liunian_list:
        ln["wuxing"] = WUXING_MAP.get(ln["ganzhi"][0], "")
        if yongshen_wx and ji_shen_wx:
            label_info = classify_liunian(ln, day_master, yongshen_wx, ji_shen_wx)
        else:
            label_info = {"label": "-", "ten_god": "", "advice": "用神未定"}
        ln["label"] = label_info['label']
        ln["ten_god"] = label_info['ten_god']
        ln["advice"] = label_info['advice']
    lines.append(f"\n## 当前大运流年（{effective_start}-{du_end}年，共{len(du_years)}年）")
    for ln in liunian_list:
        lines.append(
            f"- {ln['year']}年 {ln['ganzhi']}（{ln['wuxing']}）："
            f"{ln['label']} {ln['ten_god']} {ln['advice']}"
        )

    # 神煞
    shensha = chart_data.get("shensha", [])
    if shensha:
        ss_str = "、".join([f"{s.get('name', '')}({s.get('position', '')})" for s in shensha])
        lines.append(f"\n## 神煞\n{ss_str}")

    # 用户反馈信息（断前事环节收集的反馈）
    if feedbacks:
        pred_map = {p["id"]: p for p in (predictions or [])}
        lines.append("\n## 用户个人背景（务必在预测中参考）")
        lines.append("以下是用户在断前事环节提供的个人补充信息，你的预测必须与这些信息保持一致：")
        for fb in feedbacks:
            note = fb.get("note", "")
            if note:
                pred = pred_map.get(fb.get("prediction_id"), {})
                cat = pred.get("category", "") if pred else ""
                lines.append(f"- 【{cat}】用户说：{note}")

        lines.append("\n融合规则：")
        lines.append("1. 婚姻预测必须结合用户对父母婚姻的反馈")
        lines.append("2. 事业预测必须结合用户对学历/能力的反馈")
        lines.append("3. 如果用户反馈与命理推断矛盾，以用户实际情况为准并解释偏差原因")

    # 修正信息
    if calibration_result:
        lines.append(f"\n## 命盘校准信息\n")
        lines.append(f"校准结果：{json.dumps(calibration_result, ensure_ascii=False)}")

    prompt = "\n".join(lines)
    # 婚姻维度按性别区分目标十神
    marriage_rule = "男命看正财/偏财流年（财为妻星）" if chart.gender == "male" else "女命看正官/七杀流年（官杀为夫星）"
    prompt += f"""

请根据以上排盘数据，为命主预测未来运势。
命主当前{age}岁，正处于{current_dayun.get('stem', '')}{current_dayun.get('branch', '')}（{current_dayun.get('ten_god', '')}）大运中。
请严格按照五个维度（career/wealth/marriage/relationship/health）输出 JSON 格式的预测结果。

## 各维度 key_years 选年规则（必须差异化，禁止5个维度返回相同年份）

根据上述流年列表中每年的十神标注，为每个维度独立选取 key_years：

- career（事业）：选「正官/七杀/正印/偏印」流年——官杀主事业晋升，印星主资历
- wealth（财富）：选「正财/偏财/食神/伤官」流年——财星主进财，食伤主生财
- marriage（婚姻）：{marriage_rule}
- relationship（贵人）：选「正印/偏印」流年——印星主长辈师长提携
- health（健康）：选忌神流年或冲克日主流年——这些年份需重点关注健康

⚠️ 硬性要求：5个维度的 key_years 必须有差异，不允许完全相同。若该大运范围内某十神流年不足，可用大运交接年补足，但各维度补的年份也要不同。
"""
    return prompt


def _parse_forecast_json(response: str) -> dict | None:
    """从 AI 响应中解析 forecast JSON。"""
    try:
        data = json.loads(response)
        if isinstance(data, dict) and "career" in data:
            return data
    except json.JSONDecodeError:
        pass

    # 尝试提取 JSON 对象
    match = re.search(r"\{[\s\S]*\"career\"[\s\S]*\}", response)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return None


async def generate_ai_forecast(
    chart: BaziChart,
    chart_data: dict,
    calibration_result: dict = None,
    feedbacks: list = None,
    predictions: list = None,
    dayun_start_age: int = None,
) -> dict | None:
    """调用 DeepSeek API 生成未来运势预测。

    Args:
        chart: BaziChart 对象
        chart_data: 排盘数据的字典形式
        calibration_result: 修正结果（可选）
        feedbacks: 用户反馈列表（可选）
        predictions: 断前事推断列表（可选）
        dayun_start_age: 指定大运的起始年龄（可选），不传则用当前大运

    Returns:
        forecast dict 或 None（AI 调用失败时）
    """
    import datetime
    current_year = datetime.datetime.now().year
    # 优先用指定大运，否则用当前大运
    current_dayun = None
    if dayun_start_age:
        for d in chart.dayun:
            sa = d.start_age if hasattr(d, 'start_age') else d.get('start_age')
            if sa == dayun_start_age:
                if hasattr(d, 'model_dump'):
                    current_dayun = d.model_dump()
                elif isinstance(d, dict):
                    current_dayun = d
                else:
                    # SimpleNamespace 等对象 → dict
                    current_dayun = {
                        "stem": getattr(d, "stem", ""), "branch": getattr(d, "branch", ""),
                        "ten_god": getattr(d, "ten_god", ""),
                        "start_age": getattr(d, "start_age", 0), "end_age": getattr(d, "end_age", 0),
                        "start_year": getattr(d, "start_year", 0), "end_year": getattr(d, "end_year", 0),
                    }
                break
    if not current_dayun:
        current_dayun = _find_current_dayun(chart.dayun, current_year)

    prompt = _build_forecast_prompt(
        chart, chart_data, current_dayun,
        calibration_result=calibration_result,
        feedbacks=feedbacks,
        predictions=predictions,
    )

    content = await call_deepseek(
        prompt=prompt,
        system_prompt=FORECAST_SYSTEM_PROMPT,
        timeout=90,
        model="deepseek-chat",
        temperature=0.6,
        max_tokens=3000,
    )

    if not content or content.startswith("[API_"):
        return None

    result = _parse_forecast_json(content)
    return result


# ============================================================
# 主函数
# ============================================================

async def generate_forecast(
    chart: BaziChart,
    chart_data: dict,
    calibration_result: dict = None,
    feedbacks: list = None,
    predictions: list = None,
    dayun_start_age: int = None,
) -> dict:
    """生成未来运势预测（AI+Mock 双模式）。

    优先使用 AI 生成（需要 DEEPSEEK_API_KEY 且 AI 返回有效结果），
    否则回退到规则引擎 Mock 模式。

    Args:
        chart: BaziChart 对象
        chart_data: 排盘数据的字典形式（从 chart.model_dump() 获取）
        calibration_result: 修正结果（可选），用于校准后的预测
        feedbacks: 用户反馈列表（可选），用于个性化预测
        predictions: 断前事推断列表（可选），用于反馈关联

    Returns:
        {
            "forecast": {
                "career": {"summary": "...", "key_years": ["2027", "2030"], "advice": "..."},
                "wealth": {...},
                "marriage": {...},
                "health": {...},
                "current_dayun_analysis": {...},   # 新增
                "yearly_forecast": [...],           # 新增
                "dayun_timeline": [...],            # 新增
                "actionable_guide": {...}           # 新增
            },
            "current_dayun": {"stem": "戊", "branch": "辰", ...},
            "method": "ai_deepseek" | "mock_template",
            "disclaimer": "命理预测仅供参考，人生掌握在自己手中。..."
        }
    """
    import datetime
    current_year = datetime.datetime.now().year

    # 找到当前大运（或指定大运）
    current_dayun = None
    if dayun_start_age:
        current_dayun = next((d for d in chart.dayun if hasattr(d, 'start_age') and d.start_age == dayun_start_age or 
                              (isinstance(d, dict) and d.get('start_age') == dayun_start_age)), None)
    if not current_dayun:
        current_dayun = _find_current_dayun(chart.dayun, current_year)
    # 统一转 dict，避免后续 .get() 调用出错（支持 pydantic 对象、SimpleNamespace、dict）
    if hasattr(current_dayun, "model_dump"):
        current_dayun = current_dayun.model_dump()
    elif not isinstance(current_dayun, dict) and current_dayun is not None:
        # SimpleNamespace 等对象 → dict
        current_dayun = {
            "stem": getattr(current_dayun, "stem", ""),
            "branch": getattr(current_dayun, "branch", ""),
            "ten_god": getattr(current_dayun, "ten_god", ""),
            "start_age": getattr(current_dayun, "start_age", 0),
            "end_age": getattr(current_dayun, "end_age", 0),
            "start_year": getattr(current_dayun, "start_year", 0),
            "end_year": getattr(current_dayun, "end_year", 0),
        }

    disclaimer = (
        "命理预测仅供参考，人生掌握在自己手中。"
        "以上分析基于传统命理学推演，不构成人生决策的唯一依据。"
        "每个人的命运都掌握在自己手中，积极进取、努力奋斗才是改变命运的根本之道。"
    )

    # 尝试 AI 生成
    if os.getenv("DEEPSEEK_API_KEY"):
        ai_result = await generate_ai_forecast(
            chart, chart_data,
            calibration_result=calibration_result,
            feedbacks=feedbacks,
            predictions=predictions,
            dayun_start_age=dayun_start_age,
        )
        if ai_result:
            # 确保四个维度都存在
            required_dims = ["career", "wealth", "marriage", "health"]
            if all(dim in ai_result for dim in required_dims):
                # 提取并验证各维度
                required_dims = ["career", "wealth", "marriage", "relationship", "health"]
                forecast = {}
                for dim in required_dims:
                    entry = ai_result.get(dim, {})
                    raw_years = entry.get("key_years", [])
                    raw_actions = entry.get("key_actions", {})
                    # 过滤：必须 ≥当前年 且 在所选大运范围内
                    du_sy = current_dayun.get("start_year", current_year) if isinstance(current_dayun, dict) else getattr(current_dayun, 'start_year', current_year)
                    du_ey = current_dayun.get("end_year", current_year+10) if isinstance(current_dayun, dict) else getattr(current_dayun, 'end_year', current_year+10)
                    es = max(du_sy, current_year)
                    # 容错：AI 可能返回 "2027年" 或 "丁未2027" 等格式，提取数字
                    import re as _re
                    def _extract_year(y):
                        if isinstance(y, int):
                            return y
                        m = _re.search(r'\d{4}', str(y))
                        return int(m.group()) if m else None
                    key_years = []
                    for y in raw_years:
                        ey = _extract_year(y)
                        if ey is not None and ey >= es and ey <= du_ey:
                            key_years.append(str(ey))
                    key_actions = {}
                    for k, v in raw_actions.items():
                        ek = _extract_year(k)
                        if ek is not None and ek >= es and ek <= du_ey:
                            key_actions[str(ek)] = v
                    forecast[dim] = {
                        "summary": entry.get("summary", "暂无数据"),
                        "key_years": key_years,
                        "key_actions": key_actions,
                        "score": entry.get("score", 50),
                    }

                # 提取新增结构化字段
                forecast["current_dayun_analysis"] = ai_result.get("current_dayun_analysis", {})
                forecast["yearly_forecast"] = ai_result.get("yearly_forecast", [])
                forecast["dayun_timeline"] = ai_result.get("dayun_timeline", [])
                forecast["actionable_guide"] = ai_result.get("actionable_guide", {})

                return {
                    "forecast": forecast,
                    "current_dayun": current_dayun,
                    "method": "ai_deepseek",
                    "disclaimer": ai_result.get("disclaimer", disclaimer),
                }

    # 回退到 Mock 模板
    # current_dayun 统一转 dict 传给 mock
    du_for_mock = current_dayun
    if hasattr(du_for_mock, "model_dump"):
        du_for_mock = du_for_mock.model_dump()
    mock_forecast = generate_mock_forecast(chart, chart_data, du_for_mock)

    # 生成 Mock 的结构化字段
    mock_structured = _generate_mock_structured(chart, chart_data, current_dayun, current_year)
    mock_forecast["current_dayun_analysis"] = mock_structured["current_dayun_analysis"]
    mock_forecast["yearly_forecast"] = mock_structured["yearly_forecast"]
    mock_forecast["dayun_timeline"] = mock_structured["dayun_timeline"]
    mock_forecast["actionable_guide"] = mock_structured["actionable_guide"]

    # Mock 路径也要过滤年份范围（所选大运 ∩ ≥当前年）
    du_sy = current_dayun.get("start_year", current_year) if isinstance(current_dayun, dict) else (current_dayun.start_year if hasattr(current_dayun, 'start_year') else current_year)
    du_ey = current_dayun.get("end_year", current_year+10) if isinstance(current_dayun, dict) else (current_dayun.end_year if hasattr(current_dayun, 'end_year') else current_year+10)
    es = max(du_sy, current_year)
    import re as _re2
    def _extract_year2(y):
        if isinstance(y, int):
            return y
        m = _re2.search(r'\d{4}', str(y))
        return int(m.group()) if m else None
    for dim in ["career", "wealth", "marriage", "relationship", "health"]:
        entry = mock_forecast.get(dim, {})
        raw_years = entry.get("key_years", [])
        raw_actions = entry.get("key_actions", {})
        filtered_years = []
        for y in raw_years:
            ey = _extract_year2(y)
            if ey is not None and ey >= es and ey <= du_ey:
                filtered_years.append(str(ey))
        mock_forecast[dim]["key_years"] = filtered_years
        filtered_actions = {}
        for k, v in raw_actions.items():
            ek = _extract_year2(k)
            if ek is not None and ek >= es and ek <= du_ey:
                filtered_actions[str(ek)] = v
        mock_forecast[dim]["key_actions"] = filtered_actions

    return {
        "forecast": mock_forecast,
        "current_dayun": current_dayun,
        "method": "mock_template",
        "disclaimer": disclaimer,
    }
