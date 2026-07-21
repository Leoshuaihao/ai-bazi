"""对账器 — 比对预期事件和用户反馈，评估框架准确性

核心职责：
1. 拿追溯报告（预期事件）+ 用户反馈（实际经历）
2. 用 AI 做语义匹配（"那年换工作了" ≈ "事业宫受冲，工作有变动"）
3. 计算框架匹配度
4. 判定修正层级
"""

import json
import os
from typing import Optional

from services.deepseek_client import call_deepseek


class Reconciler:
    """对账器"""

    def __init__(self, trace_report: dict):
        self.report = trace_report
        self.key_years = trace_report.get("key_years", [])

    async def reconcile(self, user_feedback: list[dict]) -> dict:
        """执行对账

        Args:
            user_feedback: [
                {"year": 2020, "user_desc": "那年升职了", "match": true/false/None},
                ...
            ]

        Returns:
            {
                "overall_accuracy": 0.75,
                "results": [...],
                "needs_correction": False,
                "correction_level": 0,
                "correction_detail": "",
            }
        """
        # 只对关键年份进行对账
        key_year_results = [
            y for y in self.report["years"] if y["year"] in self.key_years
        ]

        # 如果关键年份不够，取事件最多的年份补充
        supplemented_years = set()
        if len(key_year_results) < 3:
            all_sorted = sorted(
                self.report["years"],
                key=lambda y: len(y.get("events", [])),
                reverse=True,
            )
            for yr in all_sorted:
                if yr["year"] not in self.key_years:
                    key_year_results.append(yr)
                    supplemented_years.add(yr["year"])
                if len(key_year_results) >= 5:
                    break

        results = []
        total_weight = 0
        matched_weight = 0

        for year_result in key_year_results:
            year = year_result["year"]

            # 找该年的用户反馈
            feedback = next(
                (f for f in user_feedback if f.get("year") == year), None
            )

            if not feedback:
                # 用户没有该年反馈，跳过
                continue

            # 生成该年的预期事件摘要
            expected_summary = self._summarize_expected_events(year_result)

            user_desc = feedback.get("user_desc", "")
            user_match = feedback.get("match")

            # 用户明确标注了对/错
            if user_match is not None:
                match_score = 1.0 if user_match else 0.0
                match_reason = "用户确认" if user_match else "用户否认"
            elif user_desc and expected_summary:
                # 有用户描述，用 AI 做语义匹配
                match_result = await self._ai_semantic_match(
                    expected_summary, user_desc, year_result
                )
                match_score = match_result.get("confidence", 0.5)
                match_reason = match_result.get("reasoning", "")
            else:
                # 无信息
                match_score = 0.5
                match_reason = "信息不足"

            weight = max(e["confidence"] for e in year_result.get("events", [])) if year_result.get("events") else 0.5
            total_weight += weight
            matched_weight += match_score * weight

            # 真正的关键年份 vs 补充的年份
            is_real_key = year in self.key_years and year not in supplemented_years

            results.append({
                "year": year,
                "age": year_result["age"],
                "expected_summary": expected_summary,
                "user_desc": user_desc,
                "match_score": match_score,
                "match_reason": match_reason,
                "weight": weight,
                "is_key_year": is_real_key,
            })

        overall_accuracy = matched_weight / total_weight if total_weight > 0 else 0

        # 判定修正需求
        needs_correction, correction_level, correction_detail = self._evaluate(
            results, overall_accuracy
        )

        return {
            "overall_accuracy": round(overall_accuracy, 2),
            "results": results,
            "matched_weight": round(matched_weight, 2),
            "total_weight": round(total_weight, 2),
            "needs_correction": needs_correction,
            "correction_level": correction_level,
            "correction_detail": correction_detail,
        }

    def _summarize_expected_events(self, year_result: dict) -> str:
        """生成预期事件摘要"""
        if not year_result.get("events"):
            return f"{year_result['year']}年无明显预期事件"

        parts = []
        for e in year_result["events"]:
            parts.append(f"【{e['event_type']}】{e['event_detail']}")

        return "\n".join(parts)

    async def _ai_semantic_match(
        self, expected: str, user_desc: str, year_result: dict
    ) -> dict:
        """用 AI 判断预期事件和用户描述是否匹配"""
        if not os.getenv("DEEPSEEK_API_KEY"):
            # 无 AI，做简单关键词匹配
            keywords = {
                "升职": "事业", "换工作": "事业", "跳槽": "事业",
                "辞职": "事业", "裁员": "事业",
                "结婚": "婚姻", "离婚": "婚姻", "分手": "婚姻",
                "生病": "健康", "住院": "健康",
                "发财": "财运", "赚钱": "财运", "亏钱": "财运",
            }
            for kw, event_type in keywords.items():
                if kw in user_desc:
                    for e in year_result.get("events", []):
                        if e.get("event_type") == event_type:
                            return {"confidence": 0.7, "reasoning": f"关键词'{kw}'匹配事件类型'{event_type}'"}
            return {"confidence": 0.4, "reasoning": "无关键词匹配"}

        prompt = f"""判断用户描述的事件和命理预期事件是否一致。

年份：{year_result['year']}年

命理预期：
{expected}

用户描述：
{user_desc}

输出 JSON：
{{"match": true/false, "confidence": 0.0-1.0, "reasoning": "简短判断理由"}}

要求：
1. 不要逐字比对，判断说的是不是同一件事
2. "换了工作"和"事业变动"算匹配（conf=0.7-0.9）
3. "离婚"和"婚姻波动"算匹配（conf=0.8-0.95）
4. 完全不相关算不匹配（conf=0-0.2）
"""

        try:
            response = await call_deepseek(
                prompt=prompt,
                temperature=0.1,
                max_tokens=200,
            )
            if response and not response.startswith("[API_"):
                # 提取 JSON
                import re
                match = re.search(r"\{[^}]+\}", response, re.DOTALL)
                if match:
                    return json.loads(match.group())
                if "true" in response.lower():
                    return {"confidence": 0.7, "reasoning": response.strip()}
        except Exception:
            pass

        return {"confidence": 0.5, "reasoning": "AI判断失败"}

    def _evaluate(
        self, results: list, overall_accuracy: float
    ) -> tuple[bool, int, str]:
        """评估修正需求

        Returns:
            (needs_correction, correction_level, correction_detail)
        """
        if overall_accuracy >= 0.7:
            return False, -1, "框架匹配度较高，无需修正"

        if overall_accuracy < 0.2:
            return True, 0, "准确率极低（<20%），大概率出生时辰有误，建议先进行时钟修正（Level 0）"

        # 分析失败模式
        failed_years = [r for r in results if r["match_score"] < 0.5]

        if not failed_years:
            # 所有年份匹配度都在0.5-0.7之间，整体偏弱偏差
            # 更可能是旺衰判定问题而非用神问题
            return True, 2, "整体准确率偏低但各年偏差均匀，建议重新判定日主旺衰（Level 2）"

        # 检查是否关键年份全错
        key_failed = [r for r in failed_years if r["is_key_year"]]
        if len(key_failed) >= 2:
            return True, 1, "关键年份事件与实际不符，建议检查用神变化和真假用神（Level 1）"

        if overall_accuracy < 0.4:
            return True, 2, "准确率偏低（<40%），建议重新判定日主旺衰（Level 2）"

        return True, 1, "框架匹配度不足，建议从用神修正开始（Level 1）"


async def run_reconciliation(
    trace_report: dict, user_feedback: list[dict]
) -> dict:
    """快捷函数：执行完整对账"""
    reconciler = Reconciler(trace_report)
    return await reconciler.reconcile(user_feedback)
