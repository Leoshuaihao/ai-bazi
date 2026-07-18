"""神煞计算模块.

神煞流派很多，本模块采用常见排盘软件的固定查表口径：
- 贵人类多以日干为主，太极/金舆兼查年干与日干。
- 桃花、驿马、华盖、将星、劫煞、亡神、灾煞兼查年支与日支。
- 红鸾、天喜、孤辰、寡宿以年支查。
- 天德、月德以月支查，目标可能是天干也可能是地支。
"""

from models import ShenshaItem

POSITIONS = ("year", "month", "day", "hour")
POSITION_LABELS = {"year": "年柱", "month": "月柱", "day": "日柱", "hour": "时柱"}

TIAN_GAN = ["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸"]
DI_ZHI = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"]

DAY_STEM_BRANCH_RULES = {
    "天乙贵人": {
        "甲": ["丑", "未"], "戊": ["丑", "未"], "庚": ["丑", "未"],
        "乙": ["子", "申"], "己": ["子", "申"],
        "丙": ["亥", "酉"], "丁": ["亥", "酉"],
        "壬": ["卯", "巳"], "癸": ["卯", "巳"],
        "辛": ["午", "寅"],
    },
    "文昌": {
        "甲": ["巳"], "乙": ["午"], "丙": ["申"], "丁": ["酉"],
        "戊": ["申"], "己": ["酉"], "庚": ["亥"], "辛": ["子"],
        "壬": ["寅"], "癸": ["卯"],
    },
    "国印贵人": {
        "甲": ["戌"], "乙": ["亥"], "丙": ["丑"], "丁": ["寅"],
        "戊": ["丑"], "己": ["寅"], "庚": ["辰"], "辛": ["巳"],
        "壬": ["未"], "癸": ["申"],
    },
    "福星贵人": {
        "甲": ["寅", "子"], "丙": ["寅", "子"],
        "乙": ["丑", "卯"], "癸": ["丑", "卯"],
        "戊": ["申"], "己": ["未"], "丁": ["亥"],
        "庚": ["午"], "辛": ["巳"], "壬": ["辰"],
    },
    "天厨贵人": {
        "甲": ["巳"], "乙": ["午"], "丙": ["巳"], "丁": ["午"],
        "戊": ["申"], "己": ["酉"], "庚": ["亥"], "辛": ["子"],
        "壬": ["寅"], "癸": ["卯"],
    },
    "禄神": {
        "甲": ["寅"], "乙": ["卯"], "丙": ["巳"], "丁": ["午"],
        "戊": ["巳"], "己": ["午"], "庚": ["申"], "辛": ["酉"],
        "壬": ["亥"], "癸": ["子"],
    },
    "羊刃": {
        "甲": ["卯"], "乙": ["寅"], "丙": ["午"], "丁": ["巳"],
        "戊": ["午"], "己": ["巳"], "庚": ["酉"], "辛": ["申"],
        "壬": ["子"], "癸": ["亥"],
    },
    "红艳": {
        "甲": ["午"], "乙": ["午"], "丙": ["寅"], "丁": ["未"],
        "戊": ["辰"], "己": ["辰"], "庚": ["戌"], "辛": ["酉"],
        "壬": ["子"], "癸": ["申"],
    },
    "流霞": {
        "甲": ["酉"], "乙": ["戌"], "丙": ["未"], "丁": ["申"],
        "戊": ["巳"], "己": ["午"], "庚": ["辰"], "辛": ["卯"],
        "壬": ["亥"], "癸": ["寅"],
    },
}

STEM_BRANCH_RULES_BY_YEAR_OR_DAY = {
    "天乙贵人": DAY_STEM_BRANCH_RULES["天乙贵人"],
    "国印贵人": DAY_STEM_BRANCH_RULES["国印贵人"],
    "太极贵人": {
        "甲": ["子", "午"], "乙": ["子", "午"],
        "丙": ["卯", "酉"], "丁": ["卯", "酉"],
        "戊": ["辰", "戌", "丑", "未"], "己": ["辰", "戌", "丑", "未"],
        "庚": ["寅", "亥"], "辛": ["寅", "亥"],
        "壬": ["巳", "申"], "癸": ["巳", "申"],
    },
    "金舆": {
        "甲": ["辰"], "乙": ["巳"], "丙": ["未"], "戊": ["未"],
        "丁": ["申"], "己": ["申"], "庚": ["戌"], "辛": ["亥"],
        "壬": ["丑"], "癸": ["寅"],
    },
}

TRINE_BRANCH_RULES = {
    "桃花": {"申子辰": "酉", "寅午戌": "卯", "亥卯未": "子", "巳酉丑": "午"},
    "驿马": {"申子辰": "寅", "寅午戌": "申", "亥卯未": "巳", "巳酉丑": "亥"},
    "华盖": {"申子辰": "辰", "寅午戌": "戌", "亥卯未": "未", "巳酉丑": "丑"},
    "将星": {"申子辰": "子", "寅午戌": "午", "亥卯未": "卯", "巳酉丑": "酉"},
    "劫煞": {"申子辰": "巳", "寅午戌": "亥", "亥卯未": "申", "巳酉丑": "寅"},
    "亡神": {"申子辰": "亥", "寅午戌": "巳", "亥卯未": "寅", "巳酉丑": "申"},
    "灾煞": {"申子辰": "午", "寅午戌": "子", "亥卯未": "酉", "巳酉丑": "卯"},
}

YEAR_BRANCH_RULES = {
    "红鸾": {"子": "卯", "丑": "寅", "寅": "丑", "卯": "子", "辰": "亥", "巳": "戌",
             "午": "酉", "未": "申", "申": "未", "酉": "午", "戌": "巳", "亥": "辰"},
    "天喜": {"子": "酉", "丑": "申", "寅": "未", "卯": "午", "辰": "巳", "巳": "辰",
             "午": "卯", "未": "寅", "申": "丑", "酉": "子", "戌": "亥", "亥": "戌"},
    "孤辰": {"子": "寅", "丑": "寅", "寅": "巳", "卯": "巳", "辰": "巳",
             "巳": "申", "午": "申", "未": "申", "申": "亥", "酉": "亥", "戌": "亥", "亥": "寅"},
    "寡宿": {"子": "戌", "丑": "戌", "寅": "丑", "卯": "丑", "辰": "丑",
             "巳": "辰", "午": "辰", "未": "辰", "申": "未", "酉": "未", "戌": "未", "亥": "戌"},
}

MONTH_RULES = {
    "天德": {"寅": "丙", "卯": "申", "辰": "壬", "巳": "辛", "午": "亥", "未": "甲",
             "申": "癸", "酉": "寅", "戌": "丙", "亥": "乙", "子": "巳", "丑": "庚"},
    "月德": {"寅": "丙", "卯": "甲", "辰": "壬", "巳": "庚", "午": "丙", "未": "甲",
             "申": "壬", "酉": "庚", "戌": "丙", "亥": "甲", "子": "壬", "丑": "庚"},
    "天医": {"寅": "丑", "卯": "寅", "辰": "卯", "巳": "辰", "午": "巳", "未": "午",
             "申": "未", "酉": "申", "戌": "酉", "亥": "戌", "子": "亥", "丑": "子"},
}

DAY_PILLAR_RULES = {
    "十恶大败": {"甲辰", "乙巳", "丙申", "丁亥", "戊戌", "己丑", "庚辰", "辛巳", "壬申", "癸亥"},
    "魁罡": {"庚辰", "庚戌", "壬辰", "戊戌"},
    "阴阳差错": {"丙子", "丁丑", "戊寅", "辛卯", "壬辰", "癸巳", "丙午", "丁未", "戊申", "辛酉", "壬戌", "癸亥"},
    "孤鸾": {"甲寅", "乙巳", "丙午", "丁巳", "戊申", "戊午", "辛亥", "壬子"},
}

DAY_PILLAR_DESCRIPTIONS = {
    "十恶大败": "日柱落十恶大败日，主钱财聚散、成败反复，需结合格局喜忌判断",
    "魁罡": "日柱为魁罡，主刚强果断、气势偏烈，宜看是否得用",
    "阴阳差错": "日柱为阴阳差错，常用于参考婚恋、人际错位之象",
    "孤鸾": "日柱为孤鸾，常用于参考婚恋孤克之象",
}

SHENSHA_COPY = {
    "天乙贵人": "逢凶化吉、贵人相助",
    "文昌": "聪明好学、文书才艺",
    "国印贵人": "印信权柄、守信掌章",
    "福星贵人": "福气助力、衣食有靠",
    "天厨贵人": "食禄口福、享用之象",
    "禄神": "禄位根气、衣禄来源",
    "羊刃": "刚烈有力、需防过激",
    "红艳": "情缘魅力、外缘显眼",
    "流霞": "血光口舌之象，需结合全局",
    "太极贵人": "悟性灵感、玄学缘分",
    "金舆": "车舆享用、配偶助力",
    "桃花": "人缘情缘、审美社交",
    "驿马": "奔波变动、迁移出行",
    "华盖": "聪慧孤高、才艺宗教",
    "将星": "主见掌控、组织号令",
    "劫煞": "突发竞争、损夺波折",
    "亡神": "心机思虑、暗耗变动",
    "灾煞": "灾阻惊扰、需防冲突",
    "红鸾": "婚恋喜庆、人缘动象",
    "天喜": "喜庆人缘、婚恋助缘",
    "孤辰": "孤独独立、六亲缘薄之象",
    "寡宿": "孤独寡合、情感冷清之象",
    "天德": "仁慈积德、逢凶化吉",
    "月德": "阴德庇佑、化险为夷",
    "天医": "医药健康、修复调养",
    "童子": "童子简法命中，主敏感早慧，需谨慎参考",
    "空亡": "旬空所在，主虚、缺、落空之象",
}


def _target_type(target: str) -> str:
    if target in TIAN_GAN:
        return "stem"
    if target in DI_ZHI:
        return "branch"
    return ""


def _pillar_label(pos: str) -> str:
    return POSITION_LABELS.get(pos, pos)


def _append(results: list[ShenshaItem], seen: set[tuple[str, str]], name: str, position: str, description: str) -> None:
    key = (name, position)
    if key in seen:
        return
    seen.add(key)
    results.append(ShenshaItem(name=name, description=description, position=position))


def _match_branches(branches: dict[str, str], targets: list[str]) -> list[tuple[str, str]]:
    return [(pos, branch) for pos, branch in branches.items() if branch in targets]


def _match_target(stems: dict[str, str], branches: dict[str, str], target: str) -> list[tuple[str, str]]:
    kind = _target_type(target)
    if kind == "stem":
        return [(pos, stem) for pos, stem in stems.items() if stem == target]
    if kind == "branch":
        return [(pos, branch) for pos, branch in branches.items() if branch == target]
    return []


def _trine_target(source_branch: str, rule: dict[str, str]) -> str:
    for group, target in rule.items():
        if source_branch in group:
            return target
    return ""


def _stem_targets(stem: str, rules: dict[str, list[str]]) -> list[str]:
    return rules.get(stem, [])


def _day_xunkong(day_stem: str, day_branch: str) -> list[str]:
    day_gz = f"{day_stem}{day_branch}"
    stems = TIAN_GAN
    branches = DI_ZHI
    for start in range(0, 60, 10):
        cycle = [f"{stems[(start + i) % 10]}{branches[(start + i) % 12]}" for i in range(10)]
        if day_gz in cycle:
            used = {branches[(start + i) % 12] for i in range(10)}
            return [branch for branch in branches if branch not in used]
    return []


def _add_stem_branch_rules(
    results: list[ShenshaItem],
    seen: set[tuple[str, str]],
    stems: dict[str, str],
    branches: dict[str, str],
    basis_pos: str,
    rules_by_name: dict[str, dict[str, list[str]]],
) -> None:
    basis_stem = stems[basis_pos]
    for name, rule in rules_by_name.items():
        targets = _stem_targets(basis_stem, rule)
        for pos, branch in _match_branches(branches, targets):
            desc = f"{_pillar_label(basis_pos)}天干{basis_stem}见{branch}为{name}，{SHENSHA_COPY.get(name, '')}"
            _append(results, seen, name, pos, desc)


def _add_trine_rules(
    results: list[ShenshaItem],
    seen: set[tuple[str, str]],
    branches: dict[str, str],
    basis_pos: str,
) -> None:
    basis_branch = branches[basis_pos]
    for name, rule in TRINE_BRANCH_RULES.items():
        target = _trine_target(basis_branch, rule)
        if not target:
            continue
        for pos, branch in _match_branches(branches, [target]):
            if name == "桃花" and basis_pos == "day" and pos == "day":
                continue
            desc = f"{_pillar_label(basis_pos)}地支{basis_branch}取{target}为{name}，{SHENSHA_COPY.get(name, '')}"
            _append(results, seen, name, pos, desc)


def _add_year_branch_rules(results: list[ShenshaItem], seen: set[tuple[str, str]], branches: dict[str, str]) -> None:
    year_branch = branches["year"]
    for name, rule in YEAR_BRANCH_RULES.items():
        target = rule.get(year_branch, "")
        for pos, branch in _match_branches(branches, [target]):
            desc = f"年支{year_branch}取{target}为{name}，{SHENSHA_COPY.get(name, '')}"
            _append(results, seen, name, pos, desc)


def _add_month_rules(
    results: list[ShenshaItem],
    seen: set[tuple[str, str]],
    stems: dict[str, str],
    branches: dict[str, str],
) -> None:
    month_branch = branches["month"]
    for name, rule in MONTH_RULES.items():
        target = rule.get(month_branch, "")
        for pos, value in _match_target(stems, branches, target):
            desc = f"月支{month_branch}见{value}为{name}，{SHENSHA_COPY.get(name, '')}"
            _append(results, seen, name, pos, desc)


def _add_day_pillar_rules(
    results: list[ShenshaItem],
    seen: set[tuple[str, str]],
    day_stem: str,
    day_branch: str,
) -> None:
    day_gz = f"{day_stem}{day_branch}"
    for name, days in DAY_PILLAR_RULES.items():
        if day_gz in days:
            _append(results, seen, name, "day", DAY_PILLAR_DESCRIPTIONS[name])


def _add_tongzi(results: list[ShenshaItem], seen: set[tuple[str, str]], branches: dict[str, str]) -> None:
    month_branch = branches["month"]
    if month_branch in {"寅", "卯", "辰", "申", "酉", "戌"}:
        targets = {"寅", "子"}
        season = "春秋"
    else:
        targets = {"卯", "未", "辰"}
        season = "冬夏"
    for pos in ("day", "hour"):
        branch = branches[pos]
        if branch in targets:
            desc = f"童子简法：{season}月见{branch}为童子，{SHENSHA_COPY['童子']}"
            _append(results, seen, "童子", pos, desc)


def _add_xunkong(
    results: list[ShenshaItem],
    seen: set[tuple[str, str]],
    day_stem: str,
    day_branch: str,
    branches: dict[str, str],
) -> None:
    targets = _day_xunkong(day_stem, day_branch)
    for pos, branch in _match_branches(branches, targets):
        desc = f"日柱{day_stem}{day_branch}旬空在{'、'.join(targets)}，{_pillar_label(pos)}见{branch}为空亡"
        _append(results, seen, "空亡", pos, desc)


def calculate_shensha(four_pillars: dict) -> list[ShenshaItem]:
    """
    计算常用神煞。

    four_pillars: {"year": Pillar, "month": Pillar, "day": Pillar, "hour": Pillar}
    """
    branches = {pos: four_pillars[pos].branch for pos in POSITIONS}
    stems = {pos: four_pillars[pos].stem for pos in POSITIONS}
    day_stem = stems["day"]
    day_branch = branches["day"]

    results: list[ShenshaItem] = []
    seen: set[tuple[str, str]] = set()

    _add_stem_branch_rules(results, seen, stems, branches, "day", DAY_STEM_BRANCH_RULES)
    _add_stem_branch_rules(results, seen, stems, branches, "year", STEM_BRANCH_RULES_BY_YEAR_OR_DAY)
    _add_stem_branch_rules(results, seen, stems, branches, "day", STEM_BRANCH_RULES_BY_YEAR_OR_DAY)
    _add_trine_rules(results, seen, branches, "year")
    _add_trine_rules(results, seen, branches, "day")
    _add_year_branch_rules(results, seen, branches)
    _add_month_rules(results, seen, stems, branches)
    _add_day_pillar_rules(results, seen, day_stem, day_branch)
    _add_tongzi(results, seen, branches)
    _add_xunkong(results, seen, day_stem, day_branch, branches)

    return results
