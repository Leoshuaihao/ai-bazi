"""断前事生成模块 - 模拟大师"先断过去让命主验证，建立信任后再进入修正闭环"

支持两种模式：
1. Mock 模板（无 API Key 时）：基于规则引擎推导
2. AI 生成（有 DEEPSEEK_API_KEY 时）：调用 DeepSeek API

生成顺序严格遵循"过三关"规则：
  性格(1) → 父母关(2) → 兄弟关(3) → 学历(4) → 婚姻关(5) → 事业(6) → 关键年份(7)
"""

import os
import re
import json

from models import BaziChart, PreEventStatement
from rules.wuxing import WUXING_MAP, HIDDEN_STEMS_MAP, get_sheng, get_ke, get_i_sheng, get_i_ke
from services.deepseek_client import call_deepseek


# ============================================================
# 五行关系辅助
# ============================================================

# 六冲
CLASH_PAIRS = {
    "子": "午", "午": "子",
    "丑": "未", "未": "丑",
    "寅": "申", "申": "寅",
    "卯": "酉", "酉": "卯",
    "辰": "戌", "戌": "辰",
    "巳": "亥", "亥": "巳",
}


def _get_stem_wuxing(stem: str) -> str:
    """获取天干五行"""
    return WUXING_MAP.get(stem, "")


def _calc_ten_god_chars(day_master_stem: str, other_stem: str) -> str:
    """计算十神（返回中文名）"""
    dm_wx = WUXING_MAP.get(day_master_stem, "")
    ot_wx = WUXING_MAP.get(other_stem, "")
    if not dm_wx or not ot_wx:
        return ""
    # 阴阳
    YINYANG = {"甲": 1, "乙": 0, "丙": 1, "丁": 0, "戊": 1,
               "己": 0, "庚": 1, "辛": 0, "壬": 1, "癸": 0}
    same_yy = YINYANG.get(day_master_stem, -1) == YINYANG.get(other_stem, -1)
    if dm_wx == ot_wx:
        return "比肩" if same_yy else "劫财"
    if get_sheng(dm_wx) == ot_wx:
        return "偏印" if same_yy else "正印"
    if get_i_sheng(dm_wx) == ot_wx:
        return "食神" if same_yy else "伤官"
    if get_i_ke(dm_wx) == ot_wx:
        return "偏财" if same_yy else "正财"
    if get_ke(dm_wx) == ot_wx:
        return "七杀" if same_yy else "正官"
    return ""


def _count_bi_jie(day_master_stem: str, four_pillars: dict) -> int:
    """统计比劫数量（天干+地支藏干）"""
    dm_wx = WUXING_MAP.get(day_master_stem, "")
    count = 0
    for pos in ["year", "month", "hour"]:  # 跳过日柱本身
        pillar = four_pillars[pos]
        stem = pillar.get("stem", "")
        stem_wx = WUXING_MAP.get(stem, "")
        if stem_wx == dm_wx:
            count += 1
        # 地支藏干
        branch = pillar.get("branch", "")
        for hs in HIDDEN_STEMS_MAP.get(branch, []):
            hs_wx = WUXING_MAP.get(hs.get("stem", ""), "")
            if hs_wx == dm_wx:
                count += 0.5
    return int(count)


def _count_yin_xing(day_master_stem: str, four_pillars: dict) -> int:
    """统计印星出现次数"""
    dm_wx = WUXING_MAP.get(day_master_stem, "")
    yin_wx = get_sheng(dm_wx)
    count = 0
    for pos in ["year", "month", "day", "hour"]:
        pillar = four_pillars[pos]
        stem = pillar.get("stem", "")
        if WUXING_MAP.get(stem, "") == yin_wx:
            count += 1
        branch = pillar.get("branch", "")
        for hs in HIDDEN_STEMS_MAP.get(branch, []):
            if WUXING_MAP.get(hs.get("stem", ""), "") == yin_wx:
                count += 0.5
    return int(count)


def _is_yin_xing_solid(day_master_stem: str, four_pillars: dict) -> bool:
    """判断印星是否得地（月支为印星五行或有强根）"""
    dm_wx = WUXING_MAP.get(day_master_stem, "")
    yin_wx = get_sheng(dm_wx)
    month_branch = four_pillars.get("month", {}).get("branch", "")
    if WUXING_MAP.get(month_branch, "") == yin_wx:
        return True
    # 检查是否有印星天干透出
    for pos in ["year", "month", "hour"]:
        stem = four_pillars.get(pos, {}).get("stem", "")
        if WUXING_MAP.get(stem, "") == yin_wx:
            return True
    return False


def _has_guan_yin_xiang_sheng(day_master_stem: str, four_pillars: dict) -> bool:
    """判断是否有官印相生格局（事业倾向体制内）"""
    dm_wx = WUXING_MAP.get(day_master_stem, "")
    guan_wx = get_ke(dm_wx)      # 官杀五行
    yin_wx = get_sheng(dm_wx)    # 印星五行
    has_guan = False
    has_yin = False
    for pos in ["year", "month", "hour"]:
        stem = four_pillars.get(pos, {}).get("stem", "")
        stem_wx = WUXING_MAP.get(stem, "")
        if stem_wx == guan_wx:
            has_guan = True
        if stem_wx == yin_wx:
            has_yin = True
    return has_guan and has_yin


def _has_shishang_sheng_cai(day_master_stem: str, four_pillars: dict) -> bool:
    """判断是否有食伤生财格局（事业倾向技术/创业）"""
    dm_wx = WUXING_MAP.get(day_master_stem, "")
    shishang_wx = get_i_sheng(dm_wx)  # 食伤五行
    cai_wx = get_i_ke(dm_wx)          # 财星五行
    has_shishang = False
    has_cai = False
    for pos in ["year", "month", "hour"]:
        stem = four_pillars.get(pos, {}).get("stem", "")
        stem_wx = WUXING_MAP.get(stem, "")
        if stem_wx == shishang_wx:
            has_shishang = True
        if stem_wx == cai_wx:
            has_cai = True
    return has_shishang and has_cai


def _get_key_years(dayun: list, four_pillars: dict) -> list[int]:
    """获取关键年份（大运交接年 + 冲日支的年份）"""
    years = set()
    # 大运交接年份
    for i in range(len(dayun)):
        d = dayun[i]
        if hasattr(d, 'start_year'):
            years.add(d.start_year)
        elif isinstance(d, dict):
            years.add(d.get("start_year", 0))
        if i > 0 and i < len(dayun):
            prev = dayun[i - 1]
            prev_end = prev.end_year if hasattr(prev, 'end_year') else prev.get("end_year", 0)
            curr_start = d.start_year if hasattr(d, 'start_year') else d.get("start_year", 0)
            if prev_end and curr_start and prev_end != curr_start:
                years.add(prev_end)
        if len(years) >= 3:
            break
    return sorted([y for y in years if y > 0])[:3]


# ============================================================
# Mock 模板生成（无 API Key 时使用）
# ============================================================

# 日主五行 → 性格画像
PERSONALITY_MAP = {
    "金": {
        "base": "刚毅果断，重情义守信用，做事有原则不轻易妥协。性格中带有一份锐气，遇事不拖泥带水，但也容易因过于直接而得罪人。",
        "quote": "《滴天髓》：金主义，其性刚，其情烈。金旺者，骨架挺直，面容方正，刚强果决，重义气。",
    },
    "木": {
        "base": "仁慈温和，有同情心和包容心，善于与人相处。性格中有坚韧不拔的一面，做事脚踏实地，但有时过于固执己见。",
        "quote": "《滴天髓》：木主仁，其性直，其情和。木旺者，形貌清秀，骨骼修长，仁慈恻隐，温和质朴。",
    },
    "水": {
        "base": "聪明灵活，思维敏捷，适应能力强。善于变通，懂得审时度势，但也容易心思过于活络，缺乏定力。",
        "quote": "《滴天髓》：水主智，其性聪，其情善。水旺者，面色黑润，说话流利，足智多谋，学识过人。",
    },
    "火": {
        "base": "热情主动，精力充沛，有领导力和感染力。做事雷厉风行，待人真诚大方，但有时也容易急躁冲动，缺乏耐心。",
        "quote": "《滴天髓》：火主礼，其性急，其情恭。火旺者，头小脚长，面色红润，做事光明磊落，急中生智。",
    },
    "土": {
        "base": "诚信稳重，踏实可靠，为人敦厚。做事有耐心和毅力，不浮躁不急进，但有时也过于保守，缺乏变通。",
        "quote": "《滴天髓》：土主信，其性重，其情厚。土旺者，腰圆面阔，面色黄润，诚实厚重，不喜浮华。",
    },
}


def _build_personality(chart: BaziChart) -> PreEventStatement:
    """根据日主五行生成性格推断"""
    dm = chart.day_master
    dm_wx = WUXING_MAP.get(dm, "土")
    info = PERSONALITY_MAP.get(dm_wx, PERSONALITY_MAP["土"])

    # 日支对性格的影响
    day_branch = chart.four_pillars["day"].branch
    branch_wx = WUXING_MAP.get(day_branch, "")
    if branch_wx == get_ke(dm_wx):
        extra = "日坐官杀，性格中多了一份自律和责任感，做事有分寸。"
    elif branch_wx == get_i_ke(dm_wx):
        extra = "日坐财星，务实重实际，对物质生活有一定追求。"
    elif branch_wx == get_sheng(dm_wx):
        extra = "日坐印星，内心有依靠，性格稳重有内涵。"
    elif branch_wx == dm_wx:
        extra = "日坐比肩，自我意识强，独立自主。"
    else:
        extra = "日坐食伤，富有创造力和表现欲。"
    content = f"你的日主为{dm}（五行属{dm_wx}），{info['base']}{extra}"

    return PreEventStatement(
        id="pred_01",
        category="性格",
        is_core=False,
        sequence=1,
        title="先说说你的性格",
        content=content,
        classical_quote=info["quote"],
        basis=f"日主{dm}为{dm_wx}，日支{day_branch}为{branch_wx}",
        confidence=0.85,
    )


def _build_parents(chart: BaziChart) -> PreEventStatement:
    """根据年柱生成父母关推断"""
    year_pillar = chart.four_pillars["year"]
    year_stem = year_pillar.stem
    year_branch = year_pillar.branch

    ten_god = _calc_ten_god_chars(chart.day_master, year_stem)

    if ten_god in ("正财", "偏财", "正印", "偏印"):
        family = "家庭条件较好，父母对你较为关爱，成长环境相对稳定"
        quote = "《子平真诠》：年为祖上，月为父母。年柱财印得位，主出身殷实。"
        basis_detail = f"年干{year_stem}为{ten_god}"
    elif ten_god in ("正官", "七杀"):
        family = "家教较为严格，父母对你期望较高，从小受到较多管束"
        quote = "《渊海子平》：年上官杀，祖上威严，家教森严。"
        basis_detail = f"年干{year_stem}为{ten_god}"
    else:
        family = "家境普通，父母多为勤劳朴实之人，你从小比较独立"
        quote = "《子平真诠》：年上比劫，祖业平常，多靠自身奋斗。"
        basis_detail = f"年干{year_stem}为{ten_god}"

    # Check 年支六冲
    clash_branch = CLASH_PAIRS.get(year_branch, "")
    if clash_branch:
        family += f"。注意年支{year_branch}与{clash_branch}相冲，父母之间或与祖上关系可能有些波折"

    content = f"从年柱{year_stem}{year_branch}来看，{family}。"

    return PreEventStatement(
        id="pred_02",
        category="父母关",
        is_core=True,
        sequence=2,
        title="再看看你的父母家庭",
        content=content,
        classical_quote=quote,
        basis=basis_detail,
        confidence=0.80,
    )


def _build_siblings(chart: BaziChart) -> PreEventStatement:
    """根据比劫数量生成兄弟关推断"""
    pillars_raw = {}
    for pos in ["year", "month", "day", "hour"]:
        pillars_raw[pos] = {
            "stem": chart.four_pillars[pos].stem,
            "branch": chart.four_pillars[pos].branch,
        }

    count = _count_bi_jie(chart.day_master, pillars_raw)

    if count >= 3:
        content = f"你的八字中比劫较旺（出现约{count}次），兄弟姐妹较多，或者朋友众多如同手足。兄弟朋友对你的影响较大，是命局中的重要力量。"
        quote = "《渊海子平》：比肩多者，兄弟众多，朋友遍天下。"
        conf = 0.82
    elif count >= 1:
        content = f"你的八字中比劫力量适中（出现约{count}次），可能有一两个手足，或者有几位知心好友情同手足。"
        quote = "《子平真诠》：比肩一二，手足不多，然情深义重。"
        conf = 0.80
    else:
        content = "你的八字中比劫不显，可能是独生子女，或者与兄弟姐妹缘分较薄。你在成长过程中较为独立，很多事情靠自己。"
        quote = "《渊海子平》：无比劫者，独子之命，或手足缘薄。"
        conf = 0.78

    return PreEventStatement(
        id="pred_03",
        category="兄弟关",
        is_core=True,
        sequence=3,
        title="说说你的兄弟姐妹",
        content=content,
        classical_quote=quote,
        basis=f"比劫出现约{count}次",
        confidence=conf,
    )


def _build_education(chart: BaziChart) -> PreEventStatement:
    """根据印星+文昌生成学历推断"""
    pillars_raw = {}
    for pos in ["year", "month", "day", "hour"]:
        pillars_raw[pos] = {
            "stem": chart.four_pillars[pos].stem,
            "branch": chart.four_pillars[pos].branch,
        }

    yin_count = _count_yin_xing(chart.day_master, pillars_raw)
    yin_solid = _is_yin_xing_solid(chart.day_master, pillars_raw)

    dm_wx = WUXING_MAP.get(chart.day_master, "")

    if yin_solid and yin_count >= 2:
        content = f"你的八字中印星得力（出现约{yin_count}次），主学业顺利，学历较高。印星代表学习和吸收能力，印星得地说明你具备较好的学习天赋和考运。"
        quote = "《子平真诠》：印绶者，生我者也。印星得地，主文章出众，科甲有望。"
        conf = 0.85
    elif yin_count >= 1:
        content = f"你的八字中有印星出现（约{yin_count}次），学业有一定基础，但需要后天努力才能取得较好学历。考试运一般，需要稳扎稳打。"
        quote = "《滴天髓》：印绶得用，学业有成，但需勤勉方可致功。"
        conf = 0.78
    else:
        content = "你的八字中印星不显，学业方面可能不是你的强项。不过你可能有其他方面的天赋，比如动手能力或社交能力更为突出。"
        quote = "《渊海子平》：印星不显，不以科举见长，或从技艺成名。"
        conf = 0.75

    return PreEventStatement(
        id="pred_04",
        category="学历",
        is_core=False,
        sequence=4,
        title="看看你的学历如何",
        content=content,
        classical_quote=quote,
        basis=f"印星出现约{yin_count}次，印星得地={'是' if yin_solid else '否'}",
        confidence=conf,
    )


def _build_marriage(chart: BaziChart) -> PreEventStatement:
    """根据日支十神生成婚姻关推断"""
    day_pillar = chart.four_pillars["day"]
    day_branch = day_pillar.branch
    day_stem = chart.day_master

    # 日支与日干的关系
    branch_wx = WUXING_MAP.get(day_branch, "")
    dm_wx = WUXING_MAP.get(day_stem, "")

    # 日支的十神（相对于日主）
    # 日支藏干本气的十神
    branch_hidden = HIDDEN_STEMS_MAP.get(day_branch, [])
    main_stem_ten = ""
    if branch_hidden:
        main_stem = branch_hidden[0].get("stem", "")
        main_stem_ten = _calc_ten_god_chars(day_stem, main_stem)

    # Check for clash with day branch
    clash_branch = CLASH_PAIRS.get(day_branch, "")
    is_clashed = False
    for pos in ["year", "month", "hour"]:
        if chart.four_pillars[pos].branch == clash_branch:
            is_clashed = True
            break

    if branch_wx == get_ke(dm_wx):
        spouse = "日坐官杀，配偶比较能干，可能在事业上有一定成就，对你要求也比较高"
        quote = "《渊海子平》：日坐官星，夫星得位，配偶贤能。女命日坐正官，主嫁贵夫。"
    elif branch_wx == get_i_ke(dm_wx):
        spouse = "日坐财星，配偶务实能干，家庭经济状况与配偶关系密切。对方可能是务实稳重之人"
        quote = "《子平真诠》：日坐财星，妻财得力。男命日坐正财，主娶贤妻。"
    elif branch_wx == get_sheng(dm_wx):
        spouse = "日坐印星，配偶对你比较体贴照顾，婚后生活较为安定，对方在精神上给你很多支持"
        quote = "《渊海子平》：日坐印绶，配偶敦厚，婚姻多靠长辈促成。"
    elif branch_wx == dm_wx:
        spouse = "日坐比劫，配偶与你性格相似，两人既是伴侣又像朋友。但也容易因个性相近而产生摩擦"
        quote = "《渊海子平》：日坐比肩，夫妻同行，然亦有争竞之象。"
    else:
        spouse = "日坐食伤，配偶可能比较有才华或艺术气息，但也容易因为沟通方式不同而产生小摩擦"
        quote = "《滴天髓》：日坐食伤，配偶灵秀，然或有言辞之争。"

    if is_clashed:
        spouse += "。注意日支受冲，感情生活中可能会有一些波动，需要双方多沟通包容"
        quote += " 日支被冲，婚姻宜晚，或以忍让为要。"

    content = f"你的日支为{day_branch}，{spouse}。"

    return PreEventStatement(
        id="pred_05",
        category="婚姻关",
        is_core=True,
        sequence=5,
        title="再说说你的婚姻感情",
        content=content,
        classical_quote=quote,
        basis=f"日支{day_branch}五行{branch_wx}" + (f"，日支与{clash_branch}相冲" if is_clashed else ""),
        confidence=0.80,
    )


def _build_career(chart: BaziChart) -> PreEventStatement:
    """根据用神+官杀/食伤生成事业推断"""
    pillars_raw = {}
    for pos in ["year", "month", "day", "hour"]:
        pillars_raw[pos] = {
            "stem": chart.four_pillars[pos].stem,
            "branch": chart.four_pillars[pos].branch,
        }

    has_guan_yin = _has_guan_yin_xiang_sheng(chart.day_master, pillars_raw)
    has_shishang_cai = _has_shishang_sheng_cai(chart.day_master, pillars_raw)
    yongshen_wx = chart.yongshen.primary

    dm_wx = WUXING_MAP.get(chart.day_master, "")

    if has_guan_yin:
        career = "官印相生，适合在体制内、大型企业或管理岗位发展。你做事有章法、讲规矩，适合需要稳定性和组织能力的工作"
        quote = "《子平真诠》：官印相生，功名顺遂，宜于公门或管理之职。"
    elif has_shishang_cai:
        career = "食伤生财，有技术和创意天赋，适合做技术、设计、创业或自由职业。你不喜欢被条条框框约束，靠自己本事吃饭"
        quote = "《滴天髓》：食伤生财，富贵自天来，技艺兴家，宜于商途。"
    elif yongshen_wx == get_ke(dm_wx):
        career = f"用神为官杀（{yongshen_wx}），适合纪律性强、有竞争性的工作，如管理、军警、法律等领域"
        quote = "《子平真诠》：用官杀者，宜于威严之职，执法、管理之业。"
    elif yongshen_wx == get_i_ke(dm_wx):
        career = f"用神为财星（{yongshen_wx}），适合与金钱、商务、贸易相关的职业，有较好的商业头脑"
        quote = "《渊海子平》：用财者，利商贸，宜实业经营。"
    elif yongshen_wx == get_i_sheng(dm_wx):
        career = f"用神为食伤（{yongshen_wx}），适合创意、技术、表达类工作，如设计、编程、写作、教育等"
        quote = "《滴天髓》：用食伤者，技艺超群，以才智取胜。"
    else:
        career = f"用神为印星（{yongshen_wx}），适合文职、教育、研究类工作。你有耐心和钻研精神，适合需要积累和深耕的领域"
        quote = "《子平真诠》：用印者，文职可居，宜教育、文化之业。"

    content = f"从你的八字格局来看，{career}。"

    return PreEventStatement(
        id="pred_06",
        category="事业",
        is_core=False,
        sequence=6,
        title="说说你的事业发展方向",
        content=content,
        classical_quote=quote,
        basis=f"用神为{yongshen_wx}" + ("，官印相生" if has_guan_yin else "") + ("，食伤生财" if has_shishang_cai else ""),
        confidence=0.82,
    )


def _build_key_years(chart: BaziChart) -> PreEventStatement:
    """根据大运交接年生成关键年份推断"""
    dayun_data = []
    for d in chart.dayun:
        dayun_data.append({
            "stem": d.stem,
            "branch": d.branch,
            "ten_god": d.ten_god,
            "start_age": d.start_age,
            "start_year": d.start_year,
            "end_age": d.end_age,
            "end_year": d.end_year,
        })

    key_years = _get_key_years(dayun_data, {})
    day_branch = chart.four_pillars["day"].branch
    clash_branch = CLASH_PAIRS.get(day_branch, "")

    if key_years:
        years_str = "、".join([str(y) + "年" for y in key_years[:3]])
        content = f"从你的大运走势来看，{years_str}是你人生的重要转折点。这些年份是大运交接的关键时刻，可能会有工作变动、搬家、感情变化等重要事件。"
        quote = "《子平真诠》：大运者，十年一变，交运之年尤为紧要。新旧交替，吉凶立判。"
        basis = f"大运交接年：{years_str}"
    elif clash_branch:
        # 找出与日支相冲的大运年份
        content = f"注意日支{day_branch}与{clash_branch}相冲的年份，以及大运交接的年份，这些时间点是你人生的重要转折期。"
        quote = "《渊海子平》：大运与日柱相冲之年，为人生变动之关键。"
        basis = f"日支{day_branch}与{clash_branch}相冲"
    else:
        # 取当前大运的开始年份
        current_year = None
        for d in dayun_data:
            if d["start_age"] <= 30 <= d["end_age"]:
                current_year = d["start_year"]
                break
        if current_year:
            content = f"{current_year}年前后是你的一个大运转换期，可能会在事业或生活上有重要变化。此外，每隔十年的交接年份也值得留意。"
            quote = "《子平真诠》：运交之时，人生转折之机也。"
            basis = f"当前大运起始年{current_year}"
        else:
            content = "你的人生转折点多与大运交接年份相关。建议关注每个大运开始和结束的年份，这些时期往往有重要的人生变化。"
            quote = "《渊海子平》：十年一运，运至则事起。"
            basis = "大运交接规则"

    return PreEventStatement(
        id="pred_07",
        category="关键年份",
        is_core=False,
        sequence=7,
        title="最后说一下你的人生关键年份",
        content=content,
        classical_quote=quote,
        basis=basis,
        confidence=0.78,
    )


def generate_mock_predictions(chart: BaziChart) -> list[PreEventStatement]:
    """基于规则引擎生成 7 条断事

    顺序严格遵循"过三关"规则：
      性格(1) → 父母关(2) → 兄弟关(3) → 学历(4) → 婚姻关(5) → 事业(6) → 关键年份(7)
    """
    predictions = [
        _build_personality(chart),       # 1. 性格
        _build_parents(chart),           # 2. 父母关（核心）
        _build_siblings(chart),          # 3. 兄弟关（核心）
        _build_education(chart),         # 4. 学历
        _build_marriage(chart),          # 5. 婚姻关（核心）
        _build_career(chart),            # 6. 事业
        _build_key_years(chart),         # 7. 关键年份
    ]
    return predictions


# ============================================================
# AI 生成（有 API Key 时）
# ============================================================

PREDICTION_SYSTEM_PROMPT = """你是一位严格遵循子平派体系的命理师，拥有30年实战经验。

你的任务是：根据八字排盘数据，为命主生成7条"断前事"推断。这是大师"过三关"的标准流程——先断过去让命主验证，建立信任后再深入分析。

严格要求：
1. 严格按照"过三关"规则排序：
   性格(1) → 父母关(2) → 兄弟关(3) → 学历(4) → 婚姻关(5) → 事业(6) → 关键年份(7)
2. 每条推断必须具体、可验证（不是泛泛而谈的套话）
3. 必须引用《滴天髓》《子平真诠》《渊海子平》《穷通宝鉴》等典籍原文
4. 推断内容要让人有"对，我就是这样的人"的认同感
5. 核心三关（父母、兄弟、婚姻）的推断要更加详细
6. 使用自然、亲切的语气，如同面谈

输出格式（严格JSON数组，不要包含任何其他内容）：
[
  {
    "id": "pred_01",
    "category": "性格",
    "is_core": false,
    "sequence": 1,
    "title": "先说说你的性格",
    "content": "推断内容（2-3句话）",
    "classical_quote": "《X书》：引用原文",
    "basis": "命理依据简述",
    "confidence": 0.85
  },
  ...
]"""


def _build_chart_summary(chart_data: dict) -> str:
    """构建排盘摘要供 AI 使用"""
    pillars = chart_data.get("four_pillars", {})
    day_master = chart_data.get("day_master", "")
    yongshen = chart_data.get("yongshen", {})
    dayun = chart_data.get("dayun", [])

    lines = ["## 排盘数据"]
    current_age = chart_data.get("current_age", 0)
    current_year = chart_data.get("current_year", 0)
    # 年龄信息，约束AI推断时间节点
    if current_age > 0:
        lines.append(f"命主当前年龄：{current_age}岁（{current_year}年），请在近过去时间范围内推断")
        lines.append(f"重要约束：你推断的所有事件必须是十年内已经发生的事，不要推断未来。")
        lines.append(f"例如：27岁的人，说'25岁左右有过变动'是合理的，说'中年后'是不合理的。")
        birth_year = chart_data.get("birth_year", 0)
        if birth_year:
            kaoyear = birth_year + 18
            lines.append(f"硬性约束：命主出生于{birth_year}年，高考/升学大约在{kaoyear}年前后。所有涉及时间的推断必须基于命主实际出生年计算，禁止使用训练数据中的默认年份（如'2014年高考'等）。")
    lines.append(f"日主：{day_master}（五行{WUXING_MAP.get(day_master, '')}）")

    pos_names = {"year": "年柱", "month": "月柱", "day": "日柱", "hour": "时柱"}
    for pos in ["year", "month", "day", "hour"]:
        p = pillars.get(pos, {})
        stem = p.get("stem", "")
        branch = p.get("branch", "")
        stem_tg = p.get("stem_ten_god", "")
        hidden = p.get("hidden_stems", [])
        hidden_str = "、".join([f"{h.get('stem','')}({h.get('ten_god','')})" for h in hidden])
        lines.append(f"{pos_names[pos]}：{stem}{branch} 天干十神={stem_tg} 藏干=[{hidden_str}] 纳音={p.get('nayin','')}")

    # 用神
    ys_primary = yongshen.get("primary", "")
    ys_pattern = yongshen.get("pattern", "")
    lines.append(f"用神：{ys_primary}，格局：{ys_pattern}")

    # 大运摘要
    lines.append("大运：")
    for d in dayun[:6]:
        lines.append(f"  {d.get('stem','')}{d.get('branch','')}({d.get('ten_god','')})"
                     f" {d.get('start_age','')}-{d.get('end_age','')}岁"
                     f" ({d.get('start_year','')}-{d.get('end_year','')})")

    # 神煞
    shensha = chart_data.get("shensha", [])
    if shensha:
        ss_str = "、".join([f"{s.get('name','')}({s.get('position','')})" for s in shensha])
        lines.append(f"神煞：{ss_str}")

    return "\n".join(lines)


def _parse_predictions_json(response: str) -> list[dict]:
    """从 AI 响应中解析 predictions JSON 数组"""
    # 尝试直接解析
    try:
        data = json.loads(response)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass

    # 尝试提取 JSON 数组
    match = re.search(r"\[.*\]", response, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return []


async def generate_ai_predictions(
    chart: BaziChart, chart_data: dict
) -> list[PreEventStatement]:
    """调用 DeepSeek API 生成 7 条断事

    Args:
        chart: BaziChart 对象
        chart_data: 排盘数据的字典形式（从 chart.model_dump() 获取）

    Returns:
        7 条 PreEventStatement
    """
    summary = _build_chart_summary(chart_data)
    prompt = f"""{summary}

请根据以上排盘数据，为命主生成7条断前事推断。
严格按照"过三关"规则：性格→父母关→兄弟关→学历→婚姻关→事业→关键年份。
每条推断要具体、可验证，必须引用典籍原文。

⚠️ 关键约束：命主的年龄已在排盘数据中标注。所有推断必须是"已经发生的事"，时间节点必须在命主当前年龄之前。例如27岁的人，推断"25岁左右有过工作变动"是合理的，推断"中年后如何"是荒谬的。关键年份推断选择"过去已发生的年份"，不要预测未来。
"""

    content = await call_deepseek(
        prompt=prompt,
        system_prompt=PREDICTION_SYSTEM_PROMPT,
        timeout=60,
        model="deepseek-chat",
        temperature=0.7,
        max_tokens=3000,
    )

    if not content or content.startswith("[API_"):
        return []

    # 解析 AI 返回的 JSON
    items = _parse_predictions_json(content)
    if not items or len(items) < 7:
        return []

    predictions = []
    for item in items[:7]:
        pred = PreEventStatement(
            id=item.get("id", f"pred_{item.get('sequence', 0):02d}"),
            category=item.get("category", ""),
            is_core=item.get("is_core", False),
            sequence=item.get("sequence", 0),
            title=item.get("title", ""),
            content=item.get("content", ""),
            classical_quote=item.get("classical_quote", ""),
            basis=item.get("basis", ""),
            confidence=float(item.get("confidence", 0.8)),
        )
        predictions.append(pred)

    return predictions


# ============================================================
# 主函数
# ============================================================

async def generate_predictions(
    chart: BaziChart, chart_data: dict
) -> list[PreEventStatement]:
    """生成 7 条断前事推断（AI+Mock 双模式）

    优先使用 AI 生成（需要 DEEPSEEK_API_KEY 且 AI 返回有效结果），
    否则回退到规则引擎 Mock 模式。
    """
    if os.getenv("DEEPSEEK_API_KEY"):
        ai_results = await generate_ai_predictions(chart, chart_data)
        if ai_results and len(ai_results) == 7:
            return ai_results

    # 回退到 Mock 模板
    return generate_mock_predictions(chart)


# ============================================================
# 动态题量：AI 判断信息是否充足 + 逐条生成
# ============================================================

MAX_PREDICTIONS = 10  # 上限保护：最多问 10 条
CORE_GATES = {"父母关", "兄弟关", "婚姻关"}  # 核心三关

# Mock 构造函数的顺序
MOCK_BUILDER_ORDER = [
    ("性格", _build_personality),
    ("父母关", _build_parents),
    ("兄弟关", _build_siblings),
    ("学历", _build_education),
    ("婚姻关", _build_marriage),
    ("事业", _build_career),
    ("关键年份", _build_key_years),
]

JUDGE_SUFFICIENT_PROMPT = """你是一位命理师。系统已经向用户提出了以下断事问题，用户给出了反馈。

已问的问题和反馈：
{predictions_with_feedback}

请判断：根据目前的反馈情况，信息是否已经足够进行命盘校准和未来预测？

判断标准：
- 核心三关（父母、兄弟、婚姻）是否都已涉及且用户给出了明确反馈？
- 用户的反馈是否足够一致（没有大量矛盾）？
- 再继续问下去，获取新信息的边际收益是否已经很低？

如果信息充足，返回JSON：{{"sufficient": true, "reason": "已覆盖核心三关且用户反馈一致"}}
如果还需要继续，返回JSON：{{"sufficient": false, "suggestion": "下一题可以从XX角度问"}}

只返回JSON，不要包含其他内容。"""


def _core_gates_covered(asked_categories: set) -> bool:
    """检查核心三关（父母、兄弟、婚姻）是否都已涉及"""
    return CORE_GATES.issubset(asked_categories)


def _get_next_category_suggestion(asked_categories: set) -> str:
    """根据已问类别，建议下一题方向"""
    all_categories = ["性格", "父母关", "兄弟关", "学历", "婚姻关", "事业", "关键年份"]
    remaining = [c for c in all_categories if c not in asked_categories]
    if not remaining:
        return "建议换个角度深入询问"
    # 优先建议核心三关
    core_remaining = [c for c in remaining if c in CORE_GATES]
    if core_remaining:
        return f"建议下一题涉及{core_remaining[0]}"
    return f"建议下一题涉及{remaining[0]}"


def judge_info_sufficient(
    chart_data: dict,
    asked_predictions: list[dict],
    feedbacks: list[dict],
) -> dict:
    """判断当前信息是否足够进行命盘校准

    双模式：
    - 无 API Key：如果已问 >= 5 条且核心三关已覆盖 → sufficient=True
    - 有 API Key：至少3条后调用 DeepSeek AI 判断

    Args:
        chart_data: 排盘数据（预留）
        asked_predictions: 已经问过的推断列表
        feedbacks: 用户反馈列表

    Returns:
        {"sufficient": bool, "reason": str, "next_suggestion": str}
    """
    asked_count = len(asked_predictions)
    asked_categories = {p.get("category", "") for p in asked_predictions}

    # 上限保护
    if asked_count >= MAX_PREDICTIONS:
        return {
            "sufficient": True,
            "reason": f"已达到最大题量（{MAX_PREDICTIONS}条），信息已充足",
            "next_suggestion": "可以进入校准分析了",
        }

    # 无 API Key 时使用 Mock 逻辑
    if not os.getenv("DEEPSEEK_API_KEY"):
        if asked_count >= 5 and _core_gates_covered(asked_categories):
            return {
                "sufficient": True,
                "reason": "已覆盖核心三关且达到最小题量",
                "next_suggestion": "可以进入下一步了",
            }
        return {
            "sufficient": False,
            "reason": "还需继续收集信息",
            "next_suggestion": _get_next_category_suggestion(asked_categories),
        }

    # 有 API Key 时：至少问 3 条再让 AI 判断
    if asked_count < 3:
        return {
            "sufficient": False,
            "reason": "题量不足（至少3条后才触发AI判断）",
            "next_suggestion": _get_next_category_suggestion(asked_categories),
        }

    # 同步方式调用 AI（在主函数中用 run_ai_judge 处理）
    # 这里返回一个标记，让调用方知道需要异步处理
    return {
        "sufficient": False,
        "reason": "需要AI判断",
        "next_suggestion": "",
        "_needs_ai": True,
    }


async def run_ai_judge_sufficient(
    asked_predictions: list[dict],
    feedbacks: list[dict],
) -> dict:
    """异步调用 AI 判断信息是否充足"""
    # 构建问题+反馈文本
    lines = []
    for pred in asked_predictions:
        pid = pred.get("id", "")
        category = pred.get("category", "")
        content = pred.get("content", "")
        fb = next((f for f in feedbacks if f.get("prediction_id") == pid), None)
        fb_status = fb.get("status", "未反馈") if fb else "未反馈"
        fb_note = fb.get("note", "") if fb else ""

        line = f"- [{category}] {content}\n  用户反馈：{fb_status}"
        if fb_note:
            line += f"（{fb_note}）"
        lines.append(line)

    predictions_text = "\n".join(lines)
    prompt = JUDGE_SUFFICIENT_PROMPT.format(predictions_with_feedback=predictions_text)

    try:
        content = await call_deepseek(
            prompt=prompt,
            system_prompt="你是一位经验丰富的命理师。只返回JSON格式的判断结果。",
            timeout=30,
            model="deepseek-chat",
            temperature=0.3,
            max_tokens=300,
        )

        if content and not content.startswith("[API_"):
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if match:
                result = json.loads(match.group(0))
                return {
                    "sufficient": bool(result.get("sufficient", False)),
                    "reason": result.get("reason", ""),
                    "next_suggestion": result.get("suggestion", ""),
                }
    except Exception:
        pass

    # AI 调用失败，回退到 Mock 逻辑
    asked_count = len(asked_predictions)
    asked_categories = {p.get("category", "") for p in asked_predictions}
    if asked_count >= 5 and _core_gates_covered(asked_categories):
        return {
            "sufficient": True,
            "reason": "已覆盖核心三关（AI判断回退）",
            "next_suggestion": "可以进入下一步了",
        }
    return {
        "sufficient": False,
        "reason": "还需继续收集信息（AI判断回退）",
        "next_suggestion": _get_next_category_suggestion(asked_categories),
    }


async def generate_single_prediction(
    chart: BaziChart,
    chart_data: dict,
    asked_categories: set,
    feedbacks: list[dict],
) -> PreEventStatement | None:
    """动态生成下一条推断（AI+Mock 双模式）

    根据已问类别和用户反馈，动态生成一条新的推断。

    Args:
        chart: BaziChart 对象
        chart_data: 排盘数据字典
        asked_categories: 已经问过的类别集合
        feedbacks: 用户反馈列表

    Returns:
        下一条 PreEventStatement，如果无法生成返回 None
    """
    seq = len(asked_categories) + 1

    # 优先 AI 生成
    if os.getenv("DEEPSEEK_API_KEY"):
        ai_pred = await _ai_generate_single(chart, chart_data, asked_categories, feedbacks, seq)
        if ai_pred:
            return ai_pred

    # 回退到 Mock：从剩余类别中选下一个
    return _mock_generate_single(chart, asked_categories, seq)


async def _ai_generate_single(
    chart: BaziChart,
    chart_data: dict,
    asked_categories: set,
    feedbacks: list[dict],
    seq: int,
) -> PreEventStatement | None:
    """使用 AI 生成单条推断"""
    summary = _build_chart_summary(chart_data)

    asked_lines = []
    for cat in sorted(asked_categories):
        asked_lines.append(f"- 已问：{cat}")
    asked_info = "\n".join(asked_lines) if asked_lines else "（尚无）"

    fb_lines = []
    for fb in feedbacks:
        pid = fb.get("prediction_id", "")
        fb_lines.append(
            f"- {pid}: {fb.get('status', '')}"
            + (f"（{fb.get('note', '')}）" if fb.get("note") else "")
        )
    fb_info = "\n".join(fb_lines) if fb_lines else "（尚无反馈）"

    prompt = f"""{summary}

已知用户已经回答了以下类别的问题：
{asked_info}

用户对已有问题的反馈：
{fb_info}

请生成第{seq}条断前事推断。要求：
1. 选择上述"已问"中没有涉及的新类别，优先核心三关（父母关、兄弟关、婚姻关）
2. 如果前面的推断中用户反馈某个方向不准，请换一个角度
3. 推断必须具体、可验证，引用典籍原文（《滴天髓》《子平真诠》《渊海子平》《穷通宝鉴》）
4. 每条推断2-3句话

输出格式（严格JSON，不要包含任何其他内容）：
[{{
  "id": "pred_{seq:02d}",
  "category": "分类",
  "is_core": false,
  "sequence": {seq},
  "title": "标题",
  "content": "推断内容",
  "classical_quote": "《X书》：引用原文",
  "basis": "命理依据简述",
  "confidence": 0.85
}}]"""

    try:
        content = await call_deepseek(
            prompt=prompt,
            system_prompt="你是一位严格遵循子平派体系的命理师，拥有30年实战经验。只返回JSON格式的单条推断。",
            timeout=30,
            model="deepseek-chat",
            temperature=0.7,
            max_tokens=800,
        )

        if content and not content.startswith("[API_"):
            items = _parse_predictions_json(content)
            if items:
                item = items[0] if isinstance(items, list) else items
                cat = item.get("category", "")
                return PreEventStatement(
                    id=item.get("id", f"pred_{seq:02d}"),
                    category=cat,
                    is_core=cat in CORE_GATES,
                    sequence=seq,
                    title=item.get("title", ""),
                    content=item.get("content", ""),
                    classical_quote=item.get("classical_quote", ""),
                    basis=item.get("basis", ""),
                    confidence=float(item.get("confidence", 0.8)),
                )
    except Exception:
        pass

    return None


def _mock_generate_single(
    chart: BaziChart,
    asked_categories: set,
    seq: int,
) -> PreEventStatement | None:
    """从 Mock 模板中按顺序选取下一条未被问过的推断"""
    for category, builder in MOCK_BUILDER_ORDER:
        if category not in asked_categories:
            pred = builder(chart)
            pred.id = f"pred_{seq:02d}"
            pred.sequence = seq
            return pred

    # 所有类别都问过了（理论上不应到达这里）
    return None
