"""Level 1 用神修正 - 三个子维度细化

1A 透干会支变化：《子平真诠·论用神变化》"透干不同则用神变，会局成功则用神亦变"
1B 真假判别：《滴天髓·真假》"真神得用生平贵，用假终为碌碌人"
1C 救应失效：《子平真诠·论用神成败得失》"救应被伤，两番损伤，其败更甚"
"""

import sys
sys.path.insert(0, '/Users/lee/WorkSpace/WorkBuddy/ai-bazi')

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CorrectionResult:
    """修正结果"""
    success: bool = False
    level: int = 1
    sub_dimension: str = ""
    detail: str = ""
    source: str = ""
    data: dict = field(default_factory=dict)


class Level1YongshenCorrector:
    """Level 1 用神修正器：1A 透干会支 + 1B 真假 + 1C 救应"""

    # ============================================================
    # 1A: 透干会支变化
    # ============================================================

    async def fix_1a_tougan_huizhi(self, chart_data: dict, user_feedback: dict = None) -> dict:
        """遍历月令藏干组合，枚举 ≤3 种有效候选格局

        《子平真诠·论用神变化》：
        "透干不同则用神变，会局成功则用神亦变"

        Args:
            chart_data: 排盘数据
            user_feedback: 用户反馈（可选，用于过滤候选）

        Returns:
            {
                "sub_dimension": "1A-透干会支变化",
                "candidates": [...],
                "recommendation": str,
                "classical_source": str,
            }
        """
        from rules.pattern import (
            detect_ganzhi_touchu, detect_zhi_heju,
            get_month_stems, _calc_ten_god, _TG_TO_PATTERN
        )
        from rules.pattern import WUXING_MAP

        fp = chart_data.get("four_pillars", {})
        dm_stem = chart_data.get("day_master", "")
        if not dm_stem:
            dm_stem = _extract_dm_stem(chart_data)

        month_branch = fp.get("month", {}).get("branch", "")
        month_stems = get_month_stems(month_branch)
        candidates = []

        # 1. 本气格局（基准）
        if month_stems:
            main_tg = _calc_ten_god(dm_stem, month_stems[0])
            main_pattern = _TG_TO_PATTERN.get(main_tg, "")
            if main_pattern:
                candidates.append({
                    "pattern": main_pattern,
                    "source": "月令本气",
                    "confidence": 0.60,
                    "detail": (
                        f"月令本气{month_stems[0]}→"
                        f"十神{main_tg}→格局{main_pattern}"
                    ),
                })

        # 2. 透干变化：中气/余气在天干透出
        touchu = detect_ganzhi_touchu(chart_data)
        touched_stem = touchu.get("touched_stem", "")
        touched_level = touchu.get("level", "")
        if touched_level in ("中气", "余气") and touchu.get("is_strong"):
            touched_tg = touchu.get("touched_ten_god", "")
            touched_pattern = _TG_TO_PATTERN.get(touched_tg, "")
            if touched_pattern and (
                not candidates or touched_pattern != candidates[0]["pattern"]
            ):
                confidence = 0.40 if touched_level == "中气" else 0.25
                candidates.append({
                    "pattern": touched_pattern,
                    "source": f"月令{touched_level}透干（{touched_stem}）",
                    "confidence": confidence,
                    "detail": (
                        f"月令{touched_level}{touched_stem}强透→"
                        f"十神{touched_tg}→格局{touched_pattern}"
                    ),
                })

        # 3. 会局变化：三合三会局可能改变用神
        heju = detect_zhi_heju(chart_data, month_branch)
        if heju.get("pending"):
            hua_wx = heju.get("hua_wuxing", "")
            heju_type = heju.get("type", "")
            # 根据化神五行推断格局方向
            if hua_wx:
                candidates.append({
                    "pattern": f"化{hua_wx}格" if heju_type else f"{heju_type}成格",
                    "source": f"月支参与{heju_type}化{hua_wx}",
                    "confidence": 0.30,
                    "detail": f"月支{month_branch}参与{heju_type}成化{hua_wx}",
                })

        # 过滤：最多保留 3 个有效候选（confidence ≥ 0.20）
        candidates = [c for c in candidates if c["confidence"] >= 0.20]
        candidates.sort(key=lambda x: x["confidence"], reverse=True)
        candidates = candidates[:3]

        return {
            "sub_dimension": "1A-透干会支变化",
            "candidates": candidates,
            "recommendation": candidates[0]["pattern"] if candidates else "",
            "classical_source": (
                "《子平真诠·论用神变化》："
                "'透干不同则用神变，会局成功则用神亦变'"
            ),
        }

    # ============================================================
    # 1B: 真假判别
    # ============================================================

    async def fix_1b_zhengjia(self, chart_data: dict) -> dict:
        """四状态判定：真神得用/假神得局/真神暗藏/用神不显

        《滴天髓·真假》：
        "令上寻真聚得真，假神休要乱真神"
        "真神失势，假神得局，法当以真为假，以假为真"

        Returns:
            {
                "sub_dimension": "1B-真假判别",
                "is_zhen": bool,
                "conclusion": str,
                "detail": str,
                "has_root": bool,
                "is_touched": bool,
                "is_hurt": bool,
                "classical_source": str,
            }
        """
        from rules.pattern import (
            _check_shen_status, _check_yongshen_chong, _check_yongshen_be_he
        )
        from rules.pattern import PATTERN_XIANGSHEN_RULES

        pattern = chart_data.get("pattern", "")
        yongshen = chart_data.get("yongshen", {})
        if isinstance(yongshen, dict):
            yongshen_tg = yongshen.get("ten_god",
                          yongshen.get("tiangan",
                          yongshen.get("primary", "")))
        else:
            yongshen_tg = ""

        if not yongshen_tg:
            rules = PATTERN_XIANGSHEN_RULES.get(pattern, {})
            yongshen_tg = rules.get("yongshen", "")

        if not yongshen_tg:
            return {
                "sub_dimension": "1B-真假判别",
                "is_zhen": False,
                "conclusion": "用神不显",
                "detail": "无法确定用神十神，无法判断真假",
                "has_root": False,
                "is_touched": False,
                "is_hurt": False,
                "classical_source": "《滴天髓·真假》",
            }

        # 检查用神状态
        exists, has_root, touches = _check_shen_status(yongshen_tg, chart_data)

        # 检查用神是否被伤
        is_hurt = False
        hurt_detail = ""

        # 用神被冲？
        if _check_yongshen_chong(pattern, chart_data):
            is_hurt = True
            hurt_detail += "月令被冲，用神之根受损；"

        # 用神被合？
        dm_stem = chart_data.get("day_master", "")
        if not dm_stem:
            dm_stem = _extract_dm_stem(chart_data)
        if _check_yongshen_be_he(pattern, dm_stem, chart_data):
            is_hurt = True
            hurt_detail += "用神被天干所合，失其用；"

        # 判定结论
        if has_root and touches and not is_hurt:
            conclusion = "真神得用"
            is_zhen = True
            detail = f"用神{yongshen_tg}透干有根且无损，真神也"
        elif has_root and touches and is_hurt:
            conclusion = "真神受损"
            is_zhen = False
            detail = f"用神{yongshen_tg}透干有根但被伤：{hurt_detail}"
        elif touches and not has_root:
            conclusion = "假神得局"
            is_zhen = False
            detail = f"用神{yongshen_tg}透干但无根，虚浮之假神"
        elif has_root and not touches:
            conclusion = "真神暗藏"
            is_zhen = False
            detail = f"用神{yongshen_tg}有根但未透干，真神不显"
        else:
            conclusion = "用神不显"
            is_zhen = False
            detail = f"用神{yongshen_tg}既未透干也无根"

        return {
            "sub_dimension": "1B-真假判别",
            "is_zhen": is_zhen,
            "conclusion": conclusion,
            "detail": detail,
            "has_root": has_root,
            "is_touched": touches,
            "is_hurt": is_hurt,
            "classical_source": (
                "《滴天髓·真假》：'真神得用生平贵，用假终为碌碌人'"
            ),
        }

    # ============================================================
    # 1C: 救应失效检测
    # ============================================================

    async def fix_1c_jiuying(self, chart_data: dict) -> dict:
        """救应被伤检测："两番损伤，其败更甚"

        《子平真诠·论用神成败得失》：
        "救应被伤，两番损伤，其败更甚"

        Returns:
            {
                "sub_dimension": "1C-救应检查",
                "status": str,
                "detail": str,
                "jiuying_hurt": bool,
                "classical_source": str,
            }
        """
        from rules.pattern import (
            PATTERN_XIANGSHEN_RULES, JIUYING_TABLE,
            check_chengbai, check_jiuying_v2
        )

        pattern = chart_data.get("pattern", "")
        yongshen = chart_data.get("yongshen", {})
        xiangshen = chart_data.get("confirmed_xiangshen", {})

        rules = PATTERN_XIANGSHEN_RULES.get(pattern, {})

        # 1. 成败检测
        chengbai = check_chengbai(
            pattern,
            yongshen if yongshen else {"ten_god": rules.get("yongshen", "")},
            xiangshen if xiangshen else {},
            chart_data,
        )

        if not chengbai.get("is_defeated"):
            return {
                "sub_dimension": "1C-救应检查",
                "status": "成格无败",
                "detail": "用神无败因，救应无需触发",
                "jiuying_hurt": False,
                "classical_source": "《子平真诠·论用神成败得失》",
            }

        # 2. 救应检测
        defeat_causes = chengbai.get("defeat_causes", [])
        jiuying = check_jiuying_v2(pattern, defeat_causes, chart_data)

        if not jiuying.get("has_jiuying"):
            return {
                "sub_dimension": "1C-救应检查",
                "status": "败格无救",
                "detail": (
                    f"用神有败因'{'、'.join(defeat_causes)}'"
                    "且无救应之神——败格"
                ),
                "defeat_causes": defeat_causes,
                "jiuying_hurt": False,
                "classical_source": "《子平真诠·论用神成败得失》",
            }

        # 3. 检查救应是否被伤
        jiuying_shen = jiuying.get("jiuying_shen", "")
        jiuying_hurt_detail = self._check_jiuying_hurt(jiuying_shen, chart_data)

        if jiuying_hurt_detail:
            return {
                "sub_dimension": "1C-救应检查",
                "status": "救应被伤",
                "detail": (
                    f"用神有败因'{'、'.join(defeat_causes)}'，"
                    f"虽有{jiuying_shen}救应，"
                    f"但{jiuying_hurt_detail}——"
                    "两番损伤，其败更甚"
                ),
                "defeat_causes": defeat_causes,
                "jiuying_shen": jiuying_shen,
                "jiuying_level": jiuying.get("jiuying_level", ""),
                "jiuying_hurt": True,
                "classical_source": (
                    "《子平真诠·论用神成败得失》："
                    "'救应被伤，两番损伤，其败更甚'"
                ),
            }

        return {
            "sub_dimension": "1C-救应检查",
            "status": "救应得力",
            "detail": (
                f"用神有败因'{'、'.join(defeat_causes)}'，"
                f"但有{jiuying_shen}({jiuying.get('jiuying_level', '')})救应"
                "——有救不为败"
            ),
            "defeat_causes": defeat_causes,
            "jiuying_shen": jiuying_shen,
            "jiuying_level": jiuying.get("jiuying_level", ""),
            "jiuying_hurt": False,
            "classical_source": "《子平真诠·论用神成败得失》",
        }

    def _check_jiuying_hurt(self, jiuying_shen: str, chart_data: dict) -> str:
        """检查救应之神是否被伤（被克/被合/无根）

        Returns:
            空字符串 = 未受伤，非空字符串 = 被伤原因
        """
        from rules.pattern import _check_shen_status, WUXING_MAP

        if not jiuying_shen:
            return ""

        exists, has_root, touches = _check_shen_status(jiuying_shen, chart_data)

        if not exists:
            return "救应之神不存于局中"

        if not has_root and not touches:
            return "救应之神既不透干也无根，力量全无"

        if not has_root:
            return "救应之神无根，其力不足"

        # 检查救应是否被克：救应五行被克制五行在天干有力
        dm_stem = _extract_dm_stem(chart_data)
        jiuying_wx = _resolve_wx_from_ten_god(dm_stem, jiuying_shen, chart_data)

        if jiuying_wx:
            ke_wx = _get_ke_wx(jiuying_wx)
            if ke_wx:
                fp = chart_data.get("four_pillars", {})
                for pos in ["year", "month", "hour"]:
                    stem = fp.get(pos, {}).get("stem", "")
                    if stem and WUXING_MAP.get(stem, "") == ke_wx:
                        from rules.pattern import _calc_ten_god
                        tg = _calc_ten_god(dm_stem, stem)
                        return f"救应之神被{ke_wx}（{tg}）克制"

        return ""

    # ============================================================
    # 综合 Level 1 修正
    # ============================================================

    async def execute_level1(
        self, chart_data: dict, user_feedback: dict = None,
        deepseek_client=None
    ) -> CorrectionResult:
        """顺序执行 1A→1B→1C，第一个成功即返回

        优先级：1A（透干会支）→ 1B（真假判别）→ 1C（救应检测）
        """
        # 1A: 透干会支变化
        result_1a = await self.fix_1a_tougan_huizhi(chart_data, user_feedback)
        if result_1a.get("candidates") and len(result_1a["candidates"]) > 1:
            return CorrectionResult(
                success=True,
                level=1,
                sub_dimension="1A-透干会支变化",
                detail=(
                    f"发现{len(result_1a['candidates'])}种候选格局："
                    f"{', '.join(c['pattern'] for c in result_1a['candidates'])}"
                ),
                source=result_1a["classical_source"],
                data=result_1a,
            )

        # 1B: 真假判别
        result_1b = await self.fix_1b_zhengjia(chart_data)
        if not result_1b.get("is_zhen"):
            return CorrectionResult(
                success=True,
                level=1,
                sub_dimension="1B-真假判别",
                detail=(
                    f"用神判定为'{result_1b['conclusion']}'："
                    f"{result_1b['detail']}"
                ),
                source=result_1b["classical_source"],
                data=result_1b,
            )

        # 1C: 救应检测
        result_1c = await self.fix_1c_jiuying(chart_data)
        if result_1c.get("status") in ("救应被伤", "败格无救"):
            return CorrectionResult(
                success=True,
                level=1,
                sub_dimension="1C-救应检查",
                detail=result_1c["detail"],
                source=result_1c["classical_source"],
                data=result_1c,
            )

        return CorrectionResult(
            success=False,
            level=1,
            sub_dimension="Level1",
            detail="用神修正三个子维度均未发现改进项",
            source="《子平真诠》《滴天髓》",
        )


# ============================================================
# 辅助函数
# ============================================================

def _extract_dm_stem(chart_data: dict) -> str:
    """提取日主天干"""
    dm = chart_data.get("day_master", "")
    return dm[-1] if dm else "甲"


def _resolve_wx_from_ten_god(dm_stem: str, ten_god: str, chart_data: dict) -> str:
    """从十神名反推五行"""
    from rules.pattern import _resolve_five_element
    return _resolve_five_element(dm_stem, ten_god, "")


def _get_ke_wx(wx: str) -> str:
    """获取克制某五行的五行"""
    ke_map = {"木": "金", "金": "火", "火": "水", "水": "土", "土": "木"}
    return ke_map.get(wx, "")


# ============================================================
# Mock 模式（无 DeepSeek 时使用）
# ============================================================

async def execute_level1_mock(chart_data: dict, user_feedback: dict = None) -> CorrectionResult:
    """Mock 模式：不调用 AI，仅用规则引擎"""
    corrector = Level1YongshenCorrector()
    return await corrector.execute_level1(chart_data, user_feedback, None)
