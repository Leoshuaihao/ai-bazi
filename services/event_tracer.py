"""事件追溯器 — 基于格局框架 + 大运流年反推过去事件

核心流程：
1. 输入：已排好的八字命盘（含格局、用神、喜忌、旺衰、大运）
2. 遍历目标年份范围
3. 对每年：定位大运 → 计算流年干支 → 刑冲合害分析 → 事件规则匹配 → 生成预期事件
4. 输出：追溯报告（含逐年事件列表、关键年份标记）

有 DeepSeek API Key 时 AI 润色为自然语言，无 Key 时模板降级。
"""

import json
import os
from datetime import datetime
from typing import Optional

from rules.interaction_analyzer import analyze_liunian_interactions
from rules.event_rules import EVENT_RULES, compute_confidence
from services.deepseek_client import call_deepseek
from rules.wuxing import WUXING_MAP, get_sheng, get_ke

# 流年干支计算（复用 liunian.py 中的函数）
from services.liunian import _get_year_ganzhi


class EventTracer:
    """事件追溯器"""

    def __init__(self, chart_data: dict):
        self.chart = chart_data
        self.day_master = chart_data.get("day_master", {}).get("stem", "")
        self.day_master_wx = WUXING_MAP.get(self.day_master, "")

        # 格局框架
        self.pattern = chart_data.get("pattern", "")          # 格局类型（正官格等）
        self.yongshen = chart_data.get("yongshen", {})         # 用神信息
        self.yongshen_wx = self._extract_yongshen_wuxing()     # 用神五行
        self.jishen_wx_list = self._extract_jishen_wuxing()    # 忌神五行列表
        self.dayun_list = chart_data.get("dayun", [])          # 大运列表

        # 四柱
        self.four_pillars = self._extract_four_pillars()

        # 用神在地支的根
        self.yongshen_roots = self._find_yongshen_roots()

        # 出生年份
        self.birth_year = chart_data.get("birth_info", {}).get("year", 2000)

        # 旺衰等级
        self.wangshuai = chart_data.get("wangshuai", "中和")

        # 十神映射：四柱天干 → 十神
        self.ten_god_map = self._build_ten_god_map()

    def _build_ten_god_map(self) -> dict:
        """构建四柱天干→十神映射"""
        tg_map = {}
        dm_char = self.day_master
        for pillar in self.four_pillars:
            stem = pillar.get("stem", "")
            if stem:
                from rules.interaction_analyzer import _calc_ten_god_for_stem
                tg_map[stem] = _calc_ten_god_for_stem(stem, dm_char)
        return tg_map

    def _extract_yongshen_wuxing(self) -> str:
        """提取用神五行"""
        ys = self.yongshen
        if isinstance(ys, dict):
            return ys.get("wuxing", ys.get("primary", ""))
        return str(ys) if ys else ""

    def _extract_jishen_wuxing(self) -> list[str]:
        """提取忌神五行列表"""
        ys = self.yongshen
        if isinstance(ys, dict):
            jis = ys.get("jishen", ys.get("ji_shen", []))
            if isinstance(jis, str):
                return [jis] if jis else []
            if isinstance(jis, list):
                return jis
        return []

    def _extract_four_pillars(self) -> list[dict]:
        """提取四柱为列表 [年, 月, 日, 时]"""
        pillars = []
        for pos in ["year", "month", "day", "hour"]:
            pillar = self.chart.get(pos, {})
            if pillar:
                pillars.append({
                    "stem": pillar.get("stem", ""),
                    "branch": pillar.get("branch", ""),
                })
        return pillars

    def _find_yongshen_roots(self) -> list[str]:
        """查找用神在地支中的根"""
        roots = []
        if not self.yongshen_wx:
            return roots
        for pillar in self.four_pillars:
            branch = pillar.get("branch", "")
            if WUXING_MAP.get(branch, "") == self.yongshen_wx:
                roots.append(branch)
        return roots

    def trace_year(self, year: int) -> dict:
        """追溯单一年份的预期事件

        Returns:
            {
                "year": int,
                "age": int,
                "dayun": dict,
                "liunian_ganzhi": str,
                "events": [{"rule_id": str, "event_type": str, "detail": str, "confidence": float, ...}],
                "combined_score": float,
                "is_key_year": bool,
            }
        """
        age = year - self.birth_year
        if age < 0:
            return None

        # 1. 定位该年所在大运
        dayun = self._find_dayun(year)

        # 2. 计算流年干支
        liunian_stem, liunian_branch = _get_year_ganzhi(year)
        liunian_ganzhi = liunian_stem + liunian_branch

        # 3. 刑冲合害分析
        interactions = analyze_liunian_interactions(
            liunian_stem=liunian_stem,
            liunian_branch=liunian_branch,
            chart_pillars=self.four_pillars,
            yongshen_wuxing=self.yongshen_wx,
            jishen_wuxing_list=self.jishen_wx_list,
            day_master_wuxing=self.day_master_wx,
            day_master_stem=self.day_master,
            yongshen_root_branches=self.yongshen_roots,
            wangshuai=self.wangshuai,
            dayun_ganzhi=dayun.get("ganzhi", ""),
            ten_god_map=self.ten_god_map,
        )

        # 4. 事件规则匹配（去重）
        seen_rules = set()
        events = []
        for rule_id in interactions["triggered_rules"]:
            if rule_id in seen_rules:
                continue
            seen_rules.add(rule_id)
            rule = EVENT_RULES.get(rule_id)
            if rule:
                confidence = compute_confidence(rule)
                events.append({
                    "rule_id": rule_id,
                    "category": rule["category"],
                    "interaction_type": rule["interaction_type"],
                    "event_type": rule["event_type"],
                    "event_detail": rule["event_detail"],
                    "confidence": confidence,
                    "classical_source": rule["classical_source"],
                })

        # 5. 特殊事件补充：大运交接年
        is_key_year = False
        if dayun and dayun.get("is_transition"):
            key_rule = EVENT_RULES.get("F1_dayun_transition")
            if key_rule:
                events.append({
                    "rule_id": "F1_dayun_transition",
                    "category": key_rule["category"],
                    "interaction_type": key_rule["interaction_type"],
                    "event_type": key_rule["event_type"],
                    "event_detail": key_rule["event_detail"],
                    "confidence": compute_confidence(key_rule),
                    "classical_source": key_rule["classical_source"],
                })
            is_key_year = True

        # 关键年份标记
        if interactions["is_yongshen_year"] or interactions["is_jishen_year"]:
            is_key_year = True
        if abs(interactions["combined_score"]) >= 2.0:
            is_key_year = True

        return {
            "year": year,
            "age": age,
            "dayun": dayun,
            "liunian_ganzhi": liunian_ganzhi,
            "liunian_stem": liunian_stem,
            "liunian_branch": liunian_branch,
            "events": events,
            "interactions": interactions,
            "combined_score": interactions["combined_score"],
            "is_key_year": is_key_year,
        }

    def trace_range(
        self,
        start_year: int = None,
        end_year: int = None,
        min_age: int = 15,
    ) -> dict:
        """追溯一个时间段的所有事件

        Args:
            start_year: 起始年份（默认出生+min_age）
            end_year: 结束年份（默认今年-1）
            min_age: 最小虚岁（太小的年份不追溯）

        Returns:
            完整追溯报告
        """
        if start_year is None:
            start_year = self.birth_year + min_age
        if end_year is None:
            end_year = datetime.now().year - 1

        years = []
        key_years = []

        for year in range(start_year, end_year + 1):
            year_result = self.trace_year(year)
            if year_result:
                years.append(year_result)
                if year_result["is_key_year"]:
                    key_years.append(year)

        # 找出大运交接年作为额外关键年份
        for da in self.dayun_list:
            transition_year = da.get("start_year")
            if transition_year and start_year <= transition_year <= end_year:
                if transition_year not in key_years:
                    key_years.append(transition_year)

        key_years.sort()

        return {
            "birth_info": {
                "year": self.birth_year,
                "day_master": self.day_master,
                "day_master_wuxing": self.day_master_wx,
            },
            "framework": {
                "pattern": self.pattern,
                "yongshen": self.yongshen,
                "yongshen_wuxing": self.yongshen_wx,
                "jishen_wuxing": self.jishen_wx_list,
            },
            "years": years,
            "key_years": key_years,
            "total_years": len(years),
        }

    def _find_dayun(self, year: int) -> dict:
        """定位某年所在的大运"""
        for da in self.dayun_list:
            start_year = da.get("start_year", 0)
            end_year = da.get("end_year", 0)
            if start_year <= year <= end_year:
                return {
                    "stem": da.get("stem", ""),
                    "branch": da.get("branch", ""),
                    "ganzhi": da.get("stem", "") + da.get("branch", ""),
                    "ten_god": da.get("ten_god", ""),
                    "start_year": start_year,
                    "end_year": end_year,
                    "is_transition": year == start_year,
                }
        return {}

    async def generate_natural_description(self, year_result: dict) -> str:
        """生成年份事件的自然语言描述

        有 AI 时用 AI 润色，无 AI 时用模板拼接
        """
        if not year_result or not year_result.get("events"):
            return f"{year_result['year']}年（{year_result['age']}岁），流年{year_result['liunian_ganzhi']}，无特别显著事件。"

        # 尝试 AI 润色
        if os.getenv("DEEPSEEK_API_KEY"):
            return await self._ai_describe(year_result)

        # 模板降级
        return self._template_describe(year_result)

    async def _ai_describe(self, year_result: dict) -> str:
        """用 AI 润色事件为自然语言"""
        prompt = f"""你是子平派命理师。将以下结构化命理事件翻译成用户友好的中文描述。

日主五行：{self.day_master_wx}
格局：{self.pattern}
用神五行：{self.yongshen_wx}
年份：{year_result['year']}年（{year_result['age']}岁）
流年干支：{year_result['liunian_ganzhi']}
大运：{year_result.get('dayun', {}).get('ganzhi', '')}

该年触发了以下事件：
{json.dumps([{
    '类型': e['event_type'],
    '详情': e['event_detail'],
    '触发规则': e['rule_id'],
    '典籍出处': e['classical_source'],
    '置信度': e['confidence'],
} for e in year_result['events']], ensure_ascii=False, indent=2)}

综合吉凶分数：{year_result['combined_score']}（正=吉，负=凶）

要求：
1. 用流畅的中文描述该年的整体运势和具体事件
2. 2-4句话即可，不要过长
3. 不要列出规则ID和置信度
4. 语气自然，像真人在说话，不要机械罗列
"""

        try:
            response = await call_deepseek(
                prompt=prompt,
                temperature=0.3,
                max_tokens=500,
            )
            if response and not response.startswith("[API_"):
                return response.strip()
        except Exception:
            pass

        return self._template_describe(year_result)

    def _template_describe(self, year_result: dict) -> str:
        """模板拼接事件描述（无 AI 降级）"""
        events = year_result["events"]
        dayun_ganzhi = year_result.get("dayun", {}).get("ganzhi", "")

        lines = [f"{year_result['year']}年（{year_result['age']}岁），"
                 f"流年{year_result['liunian_ganzhi']}，"
                 f"大运{dayun_ganzhi}。"]

        for e in events:
            lines.append(f"• {e['event_type']}方面：{e['event_detail']}。")

        # 附加吉凶总结
        score = year_result["combined_score"]
        if score >= 2:
            lines.append("整体来看，该年是较好的年份。")
        elif score <= -2:
            lines.append("整体来看，该年压力较大。")
        elif score > 0:
            lines.append("整体来看，该年偏吉。")
        elif score < 0:
            lines.append("整体来看，该年偏凶。")
        else:
            lines.append("整体来看，该年平稳。")

        return "\n".join(lines)


async def build_trace_report(chart_data: dict, start_year: int = None, end_year: int = None) -> dict:
    """快捷函数：构建完整追溯报告"""
    tracer = EventTracer(chart_data)
    report = tracer.trace_range(start_year=start_year, end_year=end_year)
    return report
