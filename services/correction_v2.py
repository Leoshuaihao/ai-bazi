"""5级递进修正引擎 V2

基于典籍规则的层层递进修正。每级修正皆有明确的古典依据，修正过程可追溯。

Level 0: 验盘 — 检查时辰/排盘错误
Level 1: 用神 — 检查用神变化、真假、成败救应
Level 2: 旺衰 — 重判日主旺衰五等
Level 3: 格局切换 — 正格↔从格/化格/专旺格
Level 4: 众寡 — 取用方向纠正
Level 5: 行运 — 大运成格变格效应

原则：规则计算 + AI 解释。修正结果附带典籍引用。
"""

import os
import json
import copy
from typing import Optional

from services.deepseek_client import call_deepseek
from services.event_tracer import EventTracer
from services.reconciler import Reconciler

try:
    from services.correction.level5_dayun import Level5DayunCorrector
    _HAS_LEVEL5_CORRECTOR = True
except ImportError:
    _HAS_LEVEL5_CORRECTOR = False


class CorrectionResult:
    """修正结果"""
    def __init__(
        self,
        success: bool = False,
        level: int = -1,
        chart: dict = None,
        detail: str = "",
        source: str = "",
        accuracy_before: float = 0.0,
        accuracy_after: float = 0.0,
    ):
        self.success = success
        self.level = level
        self.chart = chart or {}
        self.detail = detail
        self.source = source
        self.accuracy_before = accuracy_before
        self.accuracy_after = accuracy_after

    def dict(self):
        return {
            "success": self.success,
            "level": self.level,
            "detail": self.detail,
            "source": self.source,
            "accuracy_before": self.accuracy_before,
            "accuracy_after": self.accuracy_after,
        }


class CorrectionEngine:
    """5级递进修正引擎"""

    LEVEL_NAMES = {
        0: "验盘修正",
        1: "用神修正",
        2: "旺衰重判",
        3: "格局切换",
        4: "众寡之势",
        5: "行运修正",
    }

    def __init__(self, chart_data: dict, user_feedback: list[dict] = None):
        self.chart = copy.deepcopy(chart_data)
        self.user_feedback = user_feedback or []
        self.history = []

    async def correct(
        self,
        reconciliation: dict,
        max_level: int = 5,
    ) -> CorrectionResult:
        """执行递进修正

        Args:
            reconciliation: 对账器输出的对账报告
            max_level: 最大修正层级（默认5）

        Returns:
            修正结果
        """
        start_level = reconciliation.get("correction_level", 0)
        start_level = max(start_level, 0)  # 防止-1
        accuracy_before = reconciliation.get("overall_accuracy", 0)
        current_accuracy = accuracy_before

        for level in range(start_level, min(max_level + 1, 6)):
            method_name = f"_level{level}"
            method = getattr(self, method_name, None)
            if not method:
                continue

            result = await method()
            self.history.append({
                "level": level,
                "name": self.LEVEL_NAMES.get(level, f"Level{level}"),
                "success": result.success,
                "detail": result.detail,
            })

            if result.success:
                # 修正后重新对账验证
                new_accuracy = await self._re_reconcile(result.chart)
                result.accuracy_after = new_accuracy

                if new_accuracy > current_accuracy + 0.1:
                    # 显著提升，修正成功
                    result.accuracy_before = accuracy_before
                    result.level = level
                    result.source = result.source or self.LEVEL_NAMES.get(level, "")
                    return result

                # 有提升但不够显著，继续下一级
                current_accuracy = max(current_accuracy, new_accuracy)

        # 所有级别都未显著改善
        return CorrectionResult(
            success=False,
            level=-1,
            detail=f"经{len(self.history)}级修正后准确率未显著提升，"
                   f"建议人工复核或确认出生时间是否准确",
        )

    async def _re_reconcile(self, chart: dict) -> float:
        """重新追踪 + 对账，返回准确率"""
        try:
            tracer = EventTracer(chart)
            report = tracer.trace_range()

            reconciler = Reconciler(report)
            result = await reconciler.reconcile(self.user_feedback)

            return result.get("overall_accuracy", 0)
        except Exception:
            return 0

    # ============================================================
    # Level 0: 验盘修正
    # ============================================================

    async def _level0(self) -> CorrectionResult:
        """检查时辰是否错误"""
        from services.correction import try_candidate_hours

        birth_info = self.chart.get("birth_info", {})
        if not birth_info:
            return CorrectionResult(success=False, detail="无出生信息")

        try:
            # 复用现有时钟修正
            result = await try_candidate_hours(
                birth_info=birth_info,
                feedbacks=self.user_feedback,
                predictions=[],  # 新的纠正流程不需要旧 predictions
            )

            if result.get("recommended_hour") is not None:
                best_hour = result["recommended_hour"]
                if best_hour != birth_info.get("hour"):
                    # 时钟修正成功
                    best_chart = result.get("best_chart", {})
                    original_shichen = result.get("original_shichen", "")
                    new_shichen = result.get("recommended", "")
                    return CorrectionResult(
                        success=True,
                        level=0,
                        chart=best_chart,
                        detail=f"时钟修正：从{original_shichen}改为{new_shichen}",
                        source="《渊海子平》·时辰校准",
                    )
        except Exception as e:
            pass

        return CorrectionResult(
            success=False,
            detail="时钟试错未找到更优结果",
        )

    # ============================================================
    # Level 1: 用神修正
    # ============================================================

    async def _level1(self) -> CorrectionResult:
        """检查用神变化、真假、成败救应

        优先使用细化子模块（1A透干会支/1B真假判别/1C救应），
        子模块不可用时回退到原有简化逻辑。
        """
        # 尝试使用细化子模块
        try:
            from services.correction.level1_yongshen import Level1YongshenCorrector
            corrector = Level1YongshenCorrector()
            result = await corrector.execute_level1(self.chart, self.user_feedback)
            if result.success:
                new_chart = copy.deepcopy(self.chart)
                new_chart["_level1_detail"] = result.detail
                new_chart["_level1_source"] = result.source
                new_chart["_level1_sub_dimension"] = result.sub_dimension
                return CorrectionResult(
                    success=True,
                    level=1,
                    chart=new_chart,
                    detail=result.detail,
                    source=result.source,
                )
        except ImportError:
            pass

        # 回退：原有简化逻辑
        from rules.pattern import (
            PATTERN_XIANGSHEN_RULES,
            JIUYING_TABLE,
        )

        pattern = self.chart.get("pattern", "")
        yongshen = self.chart.get("yongshen", {})
        yongshen_tg = yongshen.get("tiangan", yongshen.get("stem", "")) if isinstance(yongshen, dict) else ""

        # 1. 检查用神是否为假神（虚浮无根）
        if yongshen_tg:
            is_true = self._is_true_yongshen(yongshen_tg)
            if not is_true:
                # 在地支藏干中找真神
                true_stem = self._find_true_in_hidden()
                if true_stem:
                    new_chart = self._rebuild_yongshen(true_stem)
                    return CorrectionResult(
                        success=True,
                        level=1,
                        chart=new_chart,
                        detail=f"用神修正（假→真）：原用神{yongshen_tg}虚浮无根，"
                               f"在地支藏干中找到真神{true_stem}",
                        source="《滴天髓·真假》：'提纲不与真神照，暗处寻真也有真'",
                    )

        # 2. 检查成败救应
        if pattern:
            # 检查用神是否有败因
            defeat_causes = self._check_defeat(pattern)
            if defeat_causes:
                # 检查救应
                for cause in defeat_causes:
                    jiuying = JIUYING_TABLE.get(cause, {})
                    if jiuying:
                        jiuying_shen = jiuying.get("jiuying_shen", "")
                        # 检查原局是否有救应之神
                        if self._has_jiuying_in_chart(jiuying_shen):
                            # 有救应但之前可能被忽略了
                            new_chart = copy.deepcopy(self.chart)
                            new_chart.setdefault("jiuying", []).append({
                                "cause": cause,
                                "jiuying": jiuying_shen,
                                "mechanism": jiuying.get("mechanism", ""),
                            })
                            return CorrectionResult(
                                success=True,
                                level=1,
                                chart=new_chart,
                                detail=f"成败救应修正：发现用神有败因'{cause}'，"
                                       f"但原局中存在救应之神'{jiuying_shen}'",
                                source="《子平真诠·论用神成败得失》",
                            )

        return CorrectionResult(success=False, detail="用神修正未发现可改进项")

    def _is_true_yongshen(self, stem: str) -> bool:
        """检查用神是否有根（地支/藏干有同五行=有根，天干透出不算根）"""
        from rules.wuxing import WUXING_MAP, HIDDEN_STEMS_MAP
        wx = WUXING_MAP.get(stem, "")

        for pos in ["year", "month", "day", "hour"]:
            pillar = self.chart.get(pos, {})
            branch = pillar.get("branch", "")
            # 地支五行直接为根
            if WUXING_MAP.get(branch, "") == wx:
                return True
            # 地支藏干有同五行也算有根
            for hs in HIDDEN_STEMS_MAP.get(branch, []):
                hs_stem = hs.get("stem", "") if isinstance(hs, dict) else hs
                if WUXING_MAP.get(hs_stem, "") == wx:
                    return True

        return False

    def _find_true_in_hidden(self) -> Optional[str]:
        """在地支藏干中找真神"""
        from rules.wuxing import HIDDEN_STEMS_MAP
        yongshen_wx = self.chart.get("yongshen", {}).get("wuxing", "") if isinstance(self.chart.get("yongshen"), dict) else ""

        if not yongshen_wx:
            return None

        for pos in ["year", "month", "day", "hour"]:
            pillar = self.chart.get(pos, {})
            branch = pillar.get("branch", "")
            for hs in HIDDEN_STEMS_MAP.get(branch, []):
                hs_wx = hs.get("wuxing", "") if isinstance(hs, dict) else ""
                if hs_wx == yongshen_wx:
                    return hs.get("stem", "") if isinstance(hs, dict) else ""

        return None

    def _check_defeat(self, pattern: str) -> list[str]:
        """检查用神败因"""
        from rules.pattern import PATTERN_XIANGSHEN_RULES
        rules = PATTERN_XIANGSHEN_RULES.get(pattern, {})
        return rules.get("defeat_causes", [])

    def _has_jiuying_in_chart(self, jiuying_shen: str) -> bool:
        """检查原局是否有救应之神"""
        for pos in ["year", "month", "hour"]:
            pillar = self.chart.get(pos, {})
            if pillar.get("stem") == jiuying_shen:
                return True
        return False

    def _rebuild_yongshen(self, new_stem: str) -> dict:
        """用新的用神重建 chart"""
        new_chart = copy.deepcopy(self.chart)
        from rules.wuxing import WUXING_MAP
        new_chart["yongshen"] = {
            "tiangan": new_stem,
            "wuxing": WUXING_MAP.get(new_stem, ""),
            "primary": WUXING_MAP.get(new_stem, ""),
        }
        return new_chart

    # ============================================================
    # Level 2: 旺衰重判
    # ============================================================

    async def _level2(self) -> CorrectionResult:
        """重判日主旺衰"""
        from rules.yongshen import calculate_strength_detail

        day_master = self.chart.get("day_master", {}).get("stem", "")
        four_pillars = {
            pos: self.chart.get(pos, {}) for pos in ["year", "month", "day", "hour"]
        }
        hidden_stems = self.chart.get("hidden_stems", [])

        if not day_master:
            return CorrectionResult(success=False, detail="无日主信息")

        # 重新计算旺衰
        strength = calculate_strength_detail(
            day_master_stem=day_master,
            four_pillars=four_pillars,
            hidden_stems_list=hidden_stems,
        )

        current_level = strength.get("level", self.chart.get("wangshuai", ""))
        score = strength.get("score", 0)

        # 判断是否需要修正
        old_level = self.chart.get("wangshuai", "")
        if old_level and old_level != current_level:
            new_chart = copy.deepcopy(self.chart)
            new_chart["wangshuai"] = current_level
            new_chart["strength_detail"] = strength
            return CorrectionResult(
                success=True,
                level=2,
                chart=new_chart,
                detail=f"旺衰重判：{old_level} → {current_level}（评分：{score}）",
                source="《滴天髓·旺衰》",
            )

        return CorrectionResult(success=False, detail="旺衰判定一致，无需修正")

    # ============================================================
    # Level 3: 格局切换
    # ============================================================

    async def _level3(self) -> CorrectionResult:
        """检查是否该用从格/化格/专旺格"""
        from rules.pattern import _check_special_pattern, check_huaqi_ge

        # 检查从格
        special = _check_special_pattern(self.chart)
        is_congge = special.get("is_congge", False)
        cong_type = special.get("cong_type", "")

        if is_congge and self.chart.get("pattern") not in ["从弱格", "从强格", "从杀格", "从财格", "从儿格"]:
            new_chart = copy.deepcopy(self.chart)
            new_chart["pattern"] = cong_type or "从弱格"
            return CorrectionResult(
                success=True,
                level=3,
                chart=new_chart,
                detail=f"格局切换：正格 → {cong_type}（日主极弱无根，满足从格条件）",
                source="《滴天髓·从化》",
            )

        # 检查化气格
        day_master = self.chart.get("day_master", {}).get("stem", "")
        huaqi_result = check_huaqi_ge(day_master, self.chart)
        if huaqi_result.get("is_huaqi"):
            new_chart = copy.deepcopy(self.chart)
            new_chart["pattern"] = "化气格"
            return CorrectionResult(
                success=True,
                level=3,
                chart=new_chart,
                detail=f"格局切换：正格 → 化气格（{huaqi_result.get('detail', '')}）",
                source="《滴天髓·从化》",
            )

        return CorrectionResult(success=False, detail="格局类型无需切换")

    # ============================================================
    # Level 4: 众寡之势
    # ============================================================

    async def _level4(self) -> CorrectionResult:
        """检查取用方向是否与众寡之势相反"""
        from rules.wuxing import WUXING_MAP, HIDDEN_STEMS_MAP

        # 统计五行力量（含藏干、月令加倍）
        force = {"木": 0, "火": 0, "土": 0, "金": 0, "水": 0}
        month_branch = self.chart.get("month", {}).get("branch", "")

        for pos in ["year", "month", "day", "hour"]:
            pillar = self.chart.get(pos, {})
            stem_wx = WUXING_MAP.get(pillar.get("stem", ""), "")
            branch_wx = WUXING_MAP.get(pillar.get("branch", ""), "")
            is_month = (pos == "month")

            # 天干权重
            if stem_wx:
                force[stem_wx] += 2.0 if is_month else 1.5
            # 地支权重
            if branch_wx:
                force[branch_wx] += 1.5 if is_month else 1.0
            # 地支藏干权重
            for hs in HIDDEN_STEMS_MAP.get(pillar.get("branch", ""), []):
                hs_stem = hs.get("stem", "") if isinstance(hs, dict) else hs
                hs_wx = WUXING_MAP.get(hs_stem, "")
                if hs_wx:
                    force[hs_wx] += 0.8 if is_month else 0.5

        # 找最强的五行和最弱的五行
        sorted_force = sorted(force.items(), key=lambda x: x[1], reverse=True)
        strongest_wx = sorted_force[0][0]
        strongest_val = sorted_force[0][1]
        weakest_wx = sorted_force[-1][0]
        weakest_val = sorted_force[-1][1]

        # 众寡判定：如果最强比最弱大3倍以上
        if strongest_val >= weakest_val * 3 and weakest_val > 0:
            yongshen_wx = self.chart.get("yongshen", {}).get("wuxing", "")
            if yongshen_wx == weakest_wx:
                # 如果用神是最弱的五行，说明取用方向可能反了
                # "强众而敌寡者，势在去其寡" — 不应该扶弱
                new_chart = copy.deepcopy(self.chart)
                new_chart["zhonggua_note"] = {
                    "type": "去寡",
                    "strong": strongest_wx,
                    "weak": weakest_wx,
                    "rule": "势在去其寡",
                }
                return CorrectionResult(
                    success=True,
                    level=4,
                    chart=new_chart,
                    detail=f"众寡修正：全局{strongest_wx}势大（{strongest_val}），"
                           f"{weakest_wx}势孤（{weakest_val}），"
                           f"取用方向应为助{strongest_wx}之强势而非扶{weakest_wx}之弱势",
                    source="《滴天髓·众寡》：'强众而敌寡者，势在去其寡'",
                )

        return CorrectionResult(success=False, detail="众寡之势无异常")

    # ============================================================
    # Level 5: 行运修正
    # ============================================================

    async def _level5(self) -> CorrectionResult:
        """检查大运成格变格效应（四种效应完整分析）

        委托给 Level5DayunCorrector 执行运中成格/变格/破格/并存四种效应分析。
        导入失败时回退到简化版检查。
        """
        if _HAS_LEVEL5_CORRECTOR:
            try:
                corrector = Level5DayunCorrector()
                result_l5 = await corrector.execute_level5(self.chart)

                if result_l5.success:
                    new_chart = copy.deepcopy(self.chart)
                    new_chart["dayun_effects"] = result_l5.data.get("dayun_report", [])
                    new_chart["dayun_effects_detail"] = result_l5.data.get("effects", {})
                    return CorrectionResult(
                        success=True,
                        level=5,
                        chart=new_chart,
                        detail=result_l5.detail,
                        source=result_l5.source,
                    )
                return CorrectionResult(success=False, detail=result_l5.detail, source=result_l5.source)
            except Exception:
                pass  # 回退到简化版

        # 回退：简化版检查
        dayun_list = self.chart.get("dayun", [])
        effects = []

        for da in dayun_list:
            da_stem = da.get("stem", "")
            da_branch = da.get("branch", "")
            if not da_stem:
                continue

            from rules.wuxing import WUXING_MAP
            da_wx = WUXING_MAP.get(da_stem, "")
            yongshen_wx = self.chart.get("yongshen", {}).get("wuxing", "")

            if da_wx == yongshen_wx:
                effects.append({
                    "dayun": f"{da_stem}{da_branch}",
                    "effect": "运中成格",
                    "detail": f"大运补用神之气，此十年格局力量增强",
                    "start_year": da.get("start_year"),
                    "end_year": da.get("end_year"),
                })

        if effects:
            new_chart = copy.deepcopy(self.chart)
            new_chart["dayun_effects"] = effects
            return CorrectionResult(
                success=True,
                level=5,
                chart=new_chart,
                detail=f"行运修正：发现{len(effects)}个大运存在成格效应",
                source="《子平真诠·论行运成格变格》",
            )

        return CorrectionResult(success=False, detail="未发现大运成格变格效应")


async def explain_correction(result: CorrectionResult) -> str:
    """用 AI 生成修正的自然语言解释"""
    if not os.getenv("DEEPSEEK_API_KEY"):
        return result.detail

    prompt = f"""你是子平派命理师。请用口语化的中文解释以下命理修正。

修正层级：{CorrectionEngine.LEVEL_NAMES.get(result.level, f'Level{result.level}')}
修正详情：{result.detail}
典籍出处：{result.source}
准确率变化：{result.accuracy_before:.0%} → {result.accuracy_after:.0%}

要求：
1. 2-3句话，像在跟客户当面说话
2. 自然地引用典籍（不要生硬地贴原文）
3. 解释"为什么之前断不准"和"现在修正了什么"
"""

    try:
        response = await call_deepseek(prompt=prompt, temperature=0.3, max_tokens=300)
        if response and not response.startswith("[API_"):
            return response.strip()
    except Exception:
        pass

    return result.detail


# ============================================================
# 修正触发阈值量化 — CorrectionTriggerConfig
# 基于报告第3章 五级递进修正的触发条件量化
# ============================================================

class CorrectionTriggerConfig:
    """修正触发条件量化配置

    每级修正的触发条件以命理量化指标为主，取代模糊的"准确率"判断。
    不可逆原则：只能从 max(applied_levels) + 1 开始修正，不可回退。
    迭代上限：3轮修正后仍未显著提升 → INDETERMINATE。
    """

    # 每级修正的触发规则（AND逻辑：该级内所有规则必须同时满足才触发）
    TRIGGER_CONFIG = {
        "L0": {
            "name": "验盘修正",
            "description": "时辰/排盘错误检查",
            "rules": [
                {"inaccurate_rate": 0.50},          # 整体不准确率 ≥ 50%
                {"core_pass_count": 0},              # 核心三关全部未通过
            ],
        },
        "L1": {
            "name": "用神修正",
            "description": "用神变化、真假、成败救应检查",
            "rules": [
                {"yongshen_true_pass": False},       # 用神"真神得用"判定未通过
                {"inaccurate_rate_yongshen_related": 0.30},  # 用神相关推断不准确率 ≥ 30%
            ],
        },
        "L2": {
            "name": "旺衰重判",
            "description": "日主旺衰五等重新判定",
            "rules": [
                {"wangshen_related_inaccurate": True},  # 旺衰相关推断有不准确
                {"dayun_xi_ji_mismatch_rate": 0.50},     # 大运喜忌匹配不一致率 ≥ 50%
            ],
        },
        "L3": {
            "name": "格局切换",
            "description": "正格 ↔ 从格/化格/专旺格切换",
            "rules": [
                {"career_inaccurate": True},           # 事业类推断不准确
                {"day_master_extreme": True},           # 日主旺衰处于极端值（<15或>85）
            ],
        },
        "L4": {
            "name": "众寡之势",
            "description": "取用方向纠正",
            "rules": [
                {"overall_contradiction": True},        # 全局推断方向矛盾
                {"one_element_dominance": True},         # 某五行力量占绝对优势（≥60%）
            ],
        },
        "L5": {
            "name": "行运修正",
            "description": "大运成格变格效应检查",
            "rules": [
                {"dayun_contradiction": True},           # 大运推断矛盾
                {"original_confirmed": True},             # 原局已确认但运中断事不准
            ],
        },
    }

    # 最大修正迭代次数
    MAX_CORRECTION_ITERATIONS = 3

    # 不可逆原则：只能向前推进，不可回退到已应用过的层级
    IRREVERSIBLE_LEVELS = True

    def should_trigger(self, level: str, state: dict) -> dict:
        """检查该级修正是否应该触发

        Args:
            level: 修正层级 ("L0" ~ "L5")
            state: 当前状态字典，包含：
                - applied_levels: list[int] 已应用的修正层级
                - iteration: int 当前迭代次数
                - inaccurate_rate: float 整体不准确率
                - core_pass_count: int 核心三关通过数
                - yongshen_true_pass: bool 用神真神判定
                - inaccurate_rate_yongshen_related: float 用神相关不准确率
                - wangshen_related_inaccurate: bool 旺衰相关不准确
                - dayun_xi_ji_mismatch_rate: float 大运喜忌不匹配率
                - career_inaccurate: bool 事业类不准确
                - day_master_extreme: bool 日主极端旺衰
                - overall_contradiction: bool 全局矛盾
                - one_element_dominance: bool 五行一方独大
                - dayun_contradiction: bool 大运矛盾
                - original_confirmed: bool 原局确认

        Returns:
            {
                "trigger": bool,
                "reason": str,
                "level": str,
            }
        """
        config = self.TRIGGER_CONFIG.get(level)
        if not config:
            return {"trigger": False, "reason": f"未知层级: {level}", "level": level}

        # 1. 不可逆原则检查
        applied_levels = state.get("applied_levels", [])
        level_num = int(level[1])  # "L0" → 0, "L3" → 3

        if self.IRREVERSIBLE_LEVELS:
            if applied_levels:
                max_applied = max(applied_levels)
                if level_num <= max_applied:
                    return {
                        "trigger": False,
                        "reason": (
                            f"不可逆原则：{level}（层级{level_num}）已被L{max_applied}覆盖，"
                            f"只能从L{max_applied + 1}开始修正"
                        ),
                        "level": level,
                    }

        # 2. 迭代上限检查
        if state.get("iteration", 0) >= self.MAX_CORRECTION_ITERATIONS:
            return {
                "trigger": False,
                "reason": (
                    f"迭代上限：已进行{state['iteration']}次修正（上限{self.MAX_CORRECTION_ITERATIONS}次），"
                    "建议标记为INDETERMINATE并转入人工复核"
                ),
                "level": level,
                "indeterminate": True,
            }

        # 3. 条件判定（AND逻辑：该级所有规则必须全部满足）
        rules = config.get("rules", [])
        passed_rules = 0
        failed_rules = []
        for rule in rules:
            for key, threshold in rule.items():
                actual = state.get(key)
                if isinstance(threshold, bool):
                    if actual == threshold:
                        passed_rules += 1
                    else:
                        failed_rules.append(f"{key}={actual}（需要{threshold}）")
                elif isinstance(threshold, (int, float)):
                    if isinstance(actual, (int, float)) and actual >= threshold:
                        passed_rules += 1
                    else:
                        failed_rules.append(f"{key}={actual}（需要 ≥ {threshold}）")

        if passed_rules == len(rules):
            return {
                "trigger": True,
                "reason": f"所有 {len(rules)} 条规则满足，触发{config['name']}",
                "level": level,
            }
        else:
            return {
                "trigger": False,
                "reason": f"{len(failed_rules)}/{len(rules)} 条规则未满足: {'; '.join(failed_rules)}",
                "level": level,
            }

    def get_next_level(self, state: dict) -> int:
        """获取下一个应尝试的修正层级

        Args:
            state: 包含 applied_levels 的状态字典

        Returns:
            下一个层级编号（0-5），全部完成返回 -1
        """
        applied_levels = state.get("applied_levels", [])
        if not applied_levels:
            return 0
        next_level = max(applied_levels) + 1
        if next_level > 5:
            return -1  # 所有层级已完成
        return next_level

    def check_iteration_limit(self, state: dict) -> dict:
        """检查迭代上限

        Returns:
            {
                "can_continue": bool,
                "remaining": int,
                "status": "OK" | "INDETERMINATE",
            }
        """
        iteration = state.get("iteration", 0)
        remaining = self.MAX_CORRECTION_ITERATIONS - iteration
        if remaining <= 0:
            return {
                "can_continue": False,
                "remaining": 0,
                "status": "INDETERMINATE",
                "message": (
                    f"已达迭代上限({self.MAX_CORRECTION_ITERATIONS}次)，"
                    "修正未收敛，建议人工复核"
                ),
            }
        return {
            "can_continue": True,
            "remaining": remaining,
            "status": "OK",
        }


def build_correction_state(
    hexagram_report: dict = None,
    uncertainty_report: dict = None,
    feedback_stats: dict = None,
) -> dict:
    """构建修正触发状态字典

    从三份报告（六维验证/不确定参数/用户反馈统计）中提取量化指标，
    构造 should_trigger() 所需的 state 字典。

    Args:
        hexagram_report: 六维验证评分卡报告（模块2输出）
        uncertainty_report: 不确定参数预标注报告（模块1输出）
        feedback_stats: 用户反馈统计

    Returns:
        state 字典
    """
    state = {
        "applied_levels": [],
        "iteration": 0,
        "inaccurate_rate": 0.0,
        "core_pass_count": 0,
        "yongshen_true_pass": False,
        "inaccurate_rate_yongshen_related": 0.0,
        "wangshen_related_inaccurate": False,
        "dayun_xi_ji_mismatch_rate": 0.0,
        "career_inaccurate": False,
        "day_master_extreme": False,
        "overall_contradiction": False,
        "one_element_dominance": False,
        "dayun_contradiction": False,
        "original_confirmed": False,
    }

    # 从六维验证报告提取
    if hexagram_report:
        scores = hexagram_report.get("scores", [])
        if scores:
            total_max = len(scores) * 10
            total_score = sum(s.get("score", 0) for s in scores)
            state["inaccurate_rate"] = 1.0 - (total_score / max(total_max, 1))

            # 核心三角（前3维）
            for s in scores[:3]:
                if s.get("score", 0) >= 6:
                    state["core_pass_count"] += 1

            # 用神相关维度
            yongshen_scores = [
                s for s in scores
                if s.get("dimension") in ("用神验证", "格局喜忌验证")
            ]
            if yongshen_scores:
                ys_total = sum(s.get("score", 0) for s in yongshen_scores)
                ys_max = len(yongshen_scores) * 10
                state["inaccurate_rate_yongshen_related"] = 1.0 - (ys_total / max(ys_max, 1))

            # 用神真神判定
            yongshen_dim = next(
                (s for s in scores if s.get("dimension") == "用神验证"), None
            )
            if yongshen_dim and yongshen_dim.get("score", 0) >= 6:
                state["yongshen_true_pass"] = True

            # 旺衰相关
            wangshuai_dim = next(
                (s for s in scores if s.get("dimension") == "旺衰验证"), None
            )
            if wangshuai_dim and wangshuai_dim.get("score", 0) < 4:
                state["wangshen_related_inaccurate"] = True

            # 大运走向
            dayun_dim = next(
                (s for s in scores if s.get("dimension") == "大运走向验证"), None
            )
            if dayun_dim:
                state["dayun_xi_ji_mismatch_rate"] = 1.0 - (dayun_dim.get("score", 0) / 10.0)
                if dayun_dim.get("score", 0) < 3:
                    state["dayun_contradiction"] = True

        # 全局矛盾
        if hexagram_report.get("core_triangle_pass") is False:
            state["overall_contradiction"] = True

    # 从不确定参数报告提取
    if uncertainty_report:
        items = uncertainty_report.get("items", [])
        pattern_item = next(
            (i for i in items if i.get("dimension") == "pattern"), None
        )
        if pattern_item and pattern_item.get("risk_score", 0) > 0.4:
            state["career_inaccurate"] = True

        congge_item = next(
            (i for i in items if i.get("dimension") == "congge"), None
        )
        if congge_item and congge_item.get("risk_score", 0) > 0.4:
            state["day_master_extreme"] = True

        # 某五行一方独大
        wangshuai_item = next(
            (i for i in items if i.get("dimension") == "wangshuai"), None
        )
        if wangshuai_item and wangshuai_item.get("risk_score", 0) > 0.5:
            state["one_element_dominance"] = True

    # 从用户反馈统计提取
    if feedback_stats:
        state["inaccurate_rate"] = feedback_stats.get("inaccurate_rate",
                                                       state["inaccurate_rate"])
        state["original_confirmed"] = feedback_stats.get("original_confirmed", False)

    return state
