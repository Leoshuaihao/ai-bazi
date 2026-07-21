"""Level 5 行运修正 - 大运成格变格深度分析

四种行运效应：
- 运中成格：原局格局之不足，得运而补足
- 运中变格：大运改变格局性质（运过即止）
- 运中破格：大运破坏原局格局优势
- 运中并存：多格局特征并存（天干吉地支凶或反之）

《子平真诠·论行运成格变格》：
"大运行运，有行运而格局不变者，有行运而格局遂变者。"
徐乐吾评注："运中之成，不过十年风光，运过即止"
"""

import sys
sys.path.insert(0, '/Users/lee/WorkSpace/WorkBuddy/ai-bazi')

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CorrectionResult:
    """修正结果"""
    success: bool = False
    level: int = 5
    detail: str = ""
    source: str = ""
    data: dict = field(default_factory=dict)


# ============================================================
# 格局大运需求表：每种格局需要的/避免的大运效应
# ============================================================

PATTERN_DAYUN_REQUIREMENTS = {
    "正官格": {
        "needs": ["财星", "印星"],
        "avoids": ["伤官", "七杀"],
        "cheng_conditions": [
            ("财星到位", "原局缺财星，大运行财运则财生官，格局成"),
            ("印星到位", "原局缺印星，大运行印运则印护官，格局成"),
        ],
        "bai_conditions": [
            ("伤官到位", "大运行伤官运 → 伤官克官，破格"),
            ("七杀到位", "大运行七杀运 → 官杀混杂，变格"),
        ],
    },
    "七杀格": {
        "needs": ["食神", "印星"],
        "avoids": ["财星"],
        "cheng_conditions": [
            ("食神到位", "原局杀无制，大运逢食神 → 食神制杀，成格"),
            ("印星到位", "原局无印，大运逢印 → 印化七杀，成格"),
        ],
        "bai_conditions": [
            ("财星到位", "大运行财运 → 财星党杀，破格"),
        ],
    },
    "正财格": {
        "needs": ["食神", "正官"],
        "avoids": ["比肩", "劫财"],
        "cheng_conditions": [
            ("食神到位", "原局缺食神生财，大运逢食神则格局成"),
            ("正官到位", "原局缺官护财，大运逢正官则护财有方"),
        ],
        "bai_conditions": [
            ("比劫到位", "大运行比劫运 → 比劫夺财，破格"),
        ],
    },
    "偏财格": {
        "needs": ["食神", "正官"],
        "avoids": ["比肩", "劫财"],
        "cheng_conditions": [
            ("食神到位", "原局缺食神生财，大运逢食神则格局成"),
            ("正官到位", "原局缺官护财，大运逢正官则护财有方"),
        ],
        "bai_conditions": [
            ("比劫到位", "大运行比劫运 → 比劫夺财，破格"),
        ],
    },
    "正印格": {
        "needs": ["正官", "七杀"],
        "avoids": ["正财", "偏财"],
        "cheng_conditions": [
            ("官杀到位", "原局缺官杀生印，大运行官杀则格局成"),
        ],
        "bai_conditions": [
            ("财星到位", "大运行财运 → 财星破印，破格"),
        ],
    },
    "偏印格": {
        "needs": ["偏财"],
        "avoids": ["食神"],
        "cheng_conditions": [
            ("财星到位", "原局缺财制偏印，大运逢财则格局成"),
        ],
        "bai_conditions": [
            ("食神到位", "大运行食神运 → 枭神夺食，破格"),
        ],
    },
    "食神格": {
        "needs": ["比肩", "正财"],
        "avoids": ["偏印"],
        "cheng_conditions": [
            ("比劫到位", "原局缺比劫生食神，大运逢比劫则格局成"),
            ("财星到位", "原局缺财，大运逢财则食神生财"),
        ],
        "bai_conditions": [
            ("偏印到位", "大运行偏印运 → 枭神夺食，破格"),
        ],
    },
    "伤官格": {
        "needs": ["正印", "偏财"],
        "avoids": ["正官"],
        "cheng_conditions": [
            ("印星到位", "原局缺印制伤官，大运逢印则格局成"),
            ("财星到位", "原局缺财泄伤官，大运逢财则格局成"),
        ],
        "bai_conditions": [
            ("正官到位", "大运行正官运 → 伤官见官，破格"),
        ],
    },
    "建禄格": {
        "needs": ["正官", "食神"],
        "avoids": [],
        "cheng_conditions": [
            ("官杀到位", "原局缺官杀制禄，大运逢官杀则格局成"),
            ("食神到位", "原局缺食神泄秀，大运逢食神则格局成"),
        ],
        "bai_conditions": [],
    },
    "月刃格": {
        "needs": ["七杀", "正官"],
        "avoids": [],
        "cheng_conditions": [
            ("官杀到位", "原局缺官杀制刃，大运逢官杀则格局成"),
        ],
        "bai_conditions": [
            ("冲刃", "大运地支冲月令阳刃 → 冲刃破格"),
        ],
    },
    "从弱格": {
        "needs": ["七杀", "正财", "食神"],
        "avoids": ["正印", "偏印", "比肩"],
        "cheng_conditions": [
            ("顺势到位", "大运走被从之五行 → 顺势得力"),
        ],
        "bai_conditions": [
            ("印比到位", "大运行印比运 → 扶身破从，破格"),
        ],
    },
    "专旺格": {
        "needs": ["食神", "正印"],
        "avoids": ["正官", "七杀"],
        "cheng_conditions": [
            ("泄秀到位", "大运走食伤运 → 泄秀成格"),
        ],
        "bai_conditions": [
            ("官杀到位", "大运行官杀运 → 官杀犯旺，破格"),
        ],
    },
    "化气格": {
        "needs": ["食神", "正财"],
        "avoids": ["正官", "七杀"],
        "cheng_conditions": [
            ("化神到位", "大运走化神五行运 → 化气得力"),
        ],
        "bai_conditions": [
            ("克破到位", "大运走克化神五行运 → 化气被破"),
        ],
    },
}

# 六冲对
_OPPOSITES = {
    "子": "午", "午": "子", "丑": "未", "未": "丑",
    "寅": "申", "申": "寅", "卯": "酉", "酉": "卯",
    "辰": "戌", "戌": "辰", "巳": "亥", "亥": "巳",
}

# 十神到天干五行的粗略映射（用于判断大运天干十神）
# 基于日主为"甲"的简化映射，实际使用 _calc_ten_god
_DAYUN_TEN_GOD_KEYWORDS = {
    "正官运": "正官", "七杀运": "七杀", "偏财运": "偏财",
    "正财运": "正财", "正印运": "正印", "偏印运": "偏印",
    "食神运": "食神", "伤官运": "伤官",
    "比肩运": "比肩", "劫财运": "劫财",
}


class Level5DayunCorrector:
    """四种行运效应检测器"""

    # ============================================================
    # 1. 运中成格
    # ============================================================

    async def detect_dayun_chengge(self, chart_data: dict, dayun: dict) -> dict:
        """检测运中成格：当前大运是否补足原局格局不足

        原局格局有不足（缺关键用神/喜神），当前大运补足。

        Args:
            chart_data: 排盘数据
            dayun: 单步大运数据

        Returns:
            检测结果
        """
        pattern = chart_data.get("pattern", "")
        reqs = PATTERN_DAYUN_REQUIREMENTS.get(pattern, {})
        cheng_conditions = reqs.get("cheng_conditions", [])
        results = []

        da_stem = dayun.get("stem", "")
        da_branch = dayun.get("branch", "")
        da_ten_god = dayun.get("ten_god", "")

        for cond_desc, explanation in cheng_conditions:
            if self._dayun_matches_condition(da_ten_god, da_branch, cond_desc, chart_data):
                if self._chart_lacks(chart_data, cond_desc, pattern):
                    results.append({
                        "dayun": f"{da_stem}{da_branch}",
                        "start_year": dayun.get("start_year"),
                        "end_year": dayun.get("end_year"),
                        "effect": "运中成格",
                        "detail": explanation,
                        "is_temporary": True,
                        "note": "运过即止",
                    })

        return {
            "effect_type": "运中成格",
            "detected": len(results) > 0,
            "matches": results,
            "classical_source": (
                "《子平真诠·论行运成格变格》："
                "'运中成格，可以补原局之不足'"
            ),
        }

    # ============================================================
    # 2. 运中变格
    # ============================================================

    async def detect_dayun_biange(self, chart_data: dict, dayun: dict) -> dict:
        """检测运中变格：大运是否改变了格局性质

        例：
        - 原局官格清纯，行杀运则官杀混杂 → 变格
        - 原局伤官格，行官运则伤官见官 → 变格（祸）
        """
        pattern = chart_data.get("pattern", "")
        reqs = PATTERN_DAYUN_REQUIREMENTS.get(pattern, {})
        bai_conditions = reqs.get("bai_conditions", [])
        results = []

        da_stem = dayun.get("stem", "")
        da_branch = dayun.get("branch", "")
        da_ten_god = dayun.get("ten_god", "")

        for cond_desc, explanation in bai_conditions:
            if self._dayun_matches_condition(da_ten_god, da_branch, cond_desc, chart_data):
                results.append({
                    "dayun": f"{da_stem}{da_branch}",
                    "start_year": dayun.get("start_year"),
                    "end_year": dayun.get("end_year"),
                    "effect": "运中变格",
                    "detail": explanation,
                    "warning": "此大运为临时变化，运过即止",
                    "is_temporary": True,
                    "note": "运过即止",
                })

        return {
            "effect_type": "运中变格",
            "detected": len(results) > 0,
            "matches": results,
            "classical_source": (
                "《子平真诠·论行运成格变格》："
                "'有行运而格局遂变者，变化之大，不可以常理测者'"
            ),
        }

    # ============================================================
    # 3. 运中破格
    # ============================================================

    async def detect_dayun_poge(self, chart_data: dict, dayun: dict) -> dict:
        """检测运中破格：大运是否破坏原局格局优势

        根据 PATTERN_DAYUN_RULES 判断大运十神是否为格局忌神。
        额外检查：大运地支是否冲月令。
        """
        from rules.pattern import PATTERN_DAYUN_RULES

        pattern = chart_data.get("pattern", "")
        da_stem = dayun.get("stem", "")
        da_branch = dayun.get("branch", "")
        da_ten_god = dayun.get("ten_god", "")
        results = []

        # 1. 检查大运十神是否为格局忌神
        xiji = PATTERN_DAYUN_RULES.get(pattern, {"xi": [], "ji": []})
        ji_dayun = set(xiji.get("ji", []))

        da_ten_god_yun = f"{da_ten_god}运" if da_ten_god else ""
        if da_ten_god_yun in ji_dayun:
            results.append({
                "dayun": f"{da_stem}{da_branch}",
                "start_year": dayun.get("start_year"),
                "end_year": dayun.get("end_year"),
                "effect": "运中破格",
                "detail": (
                    f"大运{da_ten_god}为该格局忌神运，"
                    "可能破坏原局优势"
                ),
                "severity": "high",
                "note": "运过即止",
            })

        # 2. 检查大运地支是否冲月令
        fp = chart_data.get("four_pillars", {})
        month_branch = fp.get("month", {}).get("branch", "")
        if da_branch == _OPPOSITES.get(month_branch, ""):
            results.append({
                "dayun": f"{da_stem}{da_branch}",
                "start_year": dayun.get("start_year"),
                "end_year": dayun.get("end_year"),
                "effect": "运中破格（地支冲月令）",
                "detail": (
                    f"大运地支{da_branch}冲月令{month_branch}，"
                    "格局根基动摇"
                ),
                "severity": "critical",
                "note": "运过即止",
            })

        return {
            "effect_type": "运中破格",
            "detected": len(results) > 0,
            "matches": results,
            "classical_source": (
                "《子平真诠》第22章：'月令逢冲则气受损'"
            ),
        }

    # ============================================================
    # 4. 运中并存
    # ============================================================

    async def detect_dayun_bingcun(self, chart_data: dict, dayun: dict) -> dict:
        """检测运中并存：天干和地支分别判断，可能天干吉地支凶或反之

        大运天干主前五年，地支主后五年。
        面前五年吉后五年凶的情况，称为"运中并存"。
        """
        pattern = chart_data.get("pattern", "")
        reqs = PATTERN_DAYUN_REQUIREMENTS.get(pattern, {})
        needs = reqs.get("needs", [])
        avoids = reqs.get("avoids", [])

        da_stem = dayun.get("stem", "")
        da_branch = dayun.get("branch", "")
        da_ten_god = dayun.get("ten_god", "")

        # 简化判断：检查da_ten_god是否在needs中（天干吉）
        stem_good = any(
            need in da_ten_god for need in needs
        ) if da_ten_god and needs else False

        # 检查地支是否在avoids中（地支凶）
        branch_bad = any(
            avoid in da_ten_god for avoid in avoids
        ) if da_ten_god and avoids else False

        # 更精确：天干和地支可能对同一十神有不同影响
        # 这里用简化版：如果天干和地支分别对应不同十神，才检查并存

        results = []
        if stem_good and branch_bad:
            results.append({
                "dayun": f"{da_stem}{da_branch}",
                "start_year": dayun.get("start_year"),
                "end_year": dayun.get("end_year"),
                "effect": "运中并存",
                "detail": (
                    f"天干{da_stem}({da_ten_god})有成格之效，"
                    "但地支有破格之嫌"
                ),
                "suggestion": (
                    "此运前五年（天干主事）好，"
                    "后五年（地支主事）差"
                ),
                "note": "运过即止",
            })

        return {
            "effect_type": "运中并存",
            "detected": len(results) > 0,
            "matches": results,
            "classical_source": (
                "《子平真诠·论行运》：'大运前五年看天干，后五年看地支'"
            ),
        }

    # ============================================================
    # 综合 Level 5 执行
    # ============================================================

    async def execute_level5(
        self, chart_data: dict, user_feedback: dict = None,
        deepseek_client=None
    ) -> CorrectionResult:
        """综合 Level 5 四种效应分析：天干地支分别分析

        Args:
            chart_data: 排盘数据
            user_feedback: 用户反馈（可选）
            deepseek_client: DeepSeek 客户端（可选）

        Returns:
            CorrectionResult
        """
        dayun_list = chart_data.get("dayun", [])

        if not dayun_list:
            return CorrectionResult(
                success=False,
                level=5,
                detail="无大运数据，无法执行行运修正",
                source="《子平真诠·论行运成格变格》",
            )

        all_effects = {
            "chengge": [],
            "biange": [],
            "poge": [],
            "bingcun": [],
        }

        for da in dayun_list:
            # 成格检测
            cg = await self.detect_dayun_chengge(chart_data, da)
            if cg["detected"]:
                all_effects["chengge"].extend(cg["matches"])

            # 变格检测
            bg = await self.detect_dayun_biange(chart_data, da)
            if bg["detected"]:
                all_effects["biange"].extend(bg["matches"])

            # 破格检测
            pg = await self.detect_dayun_poge(chart_data, da)
            if pg["detected"]:
                all_effects["poge"].extend(pg["matches"])

            # 并存检测
            bc = await self.detect_dayun_bingcun(chart_data, da)
            if bc["detected"]:
                all_effects["bingcun"].extend(bc["matches"])

        # 汇总
        total_effects = (
            len(all_effects["chengge"]) +
            len(all_effects["biange"]) +
            len(all_effects["poge"]) +
            len(all_effects["bingcun"])
        )

        if total_effects > 0:
            # 按年份排序（扁平化所有效应用于展示）
            flat_effects = []
            for etype, effects in all_effects.items():
                for e in effects:
                    flat_effects.append(e)
            flat_effects.sort(key=lambda x: x.get("start_year", 0))

            detail_parts = []
            if all_effects["chengge"]:
                detail_parts.append(
                    f"运中成格{len(all_effects['chengge'])}处"
                )
            if all_effects["biange"]:
                detail_parts.append(
                    f"运中变格{len(all_effects['biange'])}处"
                )
            if all_effects["poge"]:
                detail_parts.append(
                    f"运中破格{len(all_effects['poge'])}处"
                )
            if all_effects["bingcun"]:
                detail_parts.append(
                    f"运中并存{len(all_effects['bingcun'])}处"
                )

            return CorrectionResult(
                success=True,
                level=5,
                detail=(
                    f"行运修正：发现{total_effects}个大运效应"
                    f"（{'、'.join(detail_parts)}）"
                ),
                source=(
                    "《子平真诠·论行运成格变格》："
                    "'运中之成，不过十年风光，运过即止'"
                ),
                data={
                    "effects": all_effects,
                    "dayun_report": flat_effects,
                    "total_effects": total_effects,
                },
            )

        return CorrectionResult(
            success=False,
            level=5,
            detail="未发现大运成格变格破格并存效应",
            source="《子平真诠·论行运成格变格》",
            data={"effects": all_effects},
        )

    # ============================================================
    # 辅助方法
    # ============================================================

    def _dayun_matches_condition(
        self, ten_god: str, branch: str, cond_desc: str, chart_data: dict
    ) -> bool:
        """判断大运是否匹配某个条件描述"""
        cond_lower = cond_desc.lower()

        # 检查十神运
        if "财星到位" in cond_desc:
            return ten_god in ("正财", "偏财")
        elif "印星到位" in cond_desc:
            return ten_god in ("正印", "偏印")
        elif "食神到位" in cond_desc:
            return ten_god == "食神"
        elif "伤官到位" in cond_desc:
            return ten_god == "伤官"
        elif "正官到位" in cond_desc:
            return ten_god == "正官"
        elif "七杀到位" in cond_desc:
            return ten_god == "七杀"
        elif "比劫到位" in cond_desc:
            return ten_god in ("比肩", "劫财")
        elif "官杀到位" in cond_desc:
            return ten_god in ("正官", "七杀")
        elif "偏印到位" in cond_desc:
            return ten_god == "偏印"
        elif "顺势到位" in cond_desc:
            pattern = chart_data.get("pattern", "")
            if pattern == "从弱格":
                return ten_god in ("七杀", "正财", "偏财", "食神", "伤官")
            elif pattern == "专旺格":
                return ten_god in ("比肩", "劫财", "正印", "偏印", "食神")
            elif pattern == "化气格":
                return ten_god != "正官" and ten_god != "七杀"
        elif "泄秀到位" in cond_desc:
            return ten_god in ("食神", "伤官")
        elif "冲刃" in cond_desc:
            fp = chart_data.get("four_pillars", {})
            month_branch = fp.get("month", {}).get("branch", "")
            return branch == _OPPOSITES.get(month_branch, "")

        return False

    def _chart_lacks(
        self, chart_data: dict, cond_desc: str, pattern: str
    ) -> bool:
        """检查原局是否真的缺少该需求（避免对已经具备的要素重复标记）"""
        from rules.pattern import _check_shen_status

        # 将条件描述映射到十神
        ten_god_map = {
            "财星到位": ("正财", "偏财"),
            "印星到位": ("正印", "偏印"),
            "食神到位": ("食神",),
            "伤官到位": ("伤官",),
            "正官到位": ("正官",),
            "七杀到位": ("七杀",),
            "比劫到位": ("比肩", "劫财"),
            "官杀到位": ("正官", "七杀"),
            "偏印到位": ("偏印",),
            "顺势到位": (),
            "泄秀到位": ("食神", "伤官"),
            "化神到位": (),
        }

        ten_gods = ten_god_map.get(cond_desc, ())
        if not ten_gods:
            return True  # 不明确时保守标记为缺

        for tg in ten_gods:
            exists, has_root, touches = _check_shen_status(tg, chart_data)
            if exists:
                return False  # 原局中存在

        return True  # 确实缺少

    def _stem_helps_pattern(self, stem: str, needs: list) -> bool:
        """检查天干是否有助于格局"""
        # 简化实现
        return any(need in stem for need in needs) if stem else False

    def _branch_hurts_pattern(
        self, branch: str, avoids: list, pattern: str
    ) -> bool:
        """检查地支是否不利于格局"""
        # 简化实现
        return any(avoid in branch for avoid in avoids) if branch else False


# ============================================================
# Mock 模式
# ============================================================

async def execute_level5_mock(
    chart_data: dict, user_feedback: dict = None
) -> CorrectionResult:
    """Mock 模式：不调用 AI，仅用规则引擎"""
    corrector = Level5DayunCorrector()
    return await corrector.execute_level5(chart_data, user_feedback, None)
