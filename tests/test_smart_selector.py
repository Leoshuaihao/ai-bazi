"""Tests for services/predictions.py SmartPredictionSelector"""

import pytest
from services.predictions import SmartPredictionSelector


# ============================================================
# Test helpers
# ============================================================

def make_candidates():
    """Create a set of mock prediction candidates covering all categories"""
    return [
        {"id": "pred_01", "category": "性格", "content": "性格测试"},
        {"id": "pred_02", "category": "父母关", "content": "父母关测试"},
        {"id": "pred_03", "category": "兄弟关", "content": "兄弟关测试"},
        {"id": "pred_04", "category": "学历", "content": "学历测试"},
        {"id": "pred_05", "category": "婚姻关", "content": "婚姻关测试"},
        {"id": "pred_06", "category": "事业", "content": "事业测试"},
        {"id": "pred_07", "category": "关键年份", "content": "关键年份测试"},
    ]


def make_high_uncertainty():
    """Create a high-uncertainty report"""
    return {"overall_risk": 0.8}


def make_low_uncertainty():
    """Create a low-uncertainty report"""
    return {"overall_risk": 0.2}


# ============================================================
# Tests
# ============================================================

class TestCalculateDiscriminationScore:
    """测试单条预测的区分度计算"""

    def setup_method(self):
        self.selector = SmartPredictionSelector()

    def test_parents_gate_has_high_priority(self):
        """父母关得分应该是高分"""
        result = self.selector.calculate_discrimination_score(
            {"id": "pred_parents", "category": "父母关"}
        )
        assert result["category"] == "父母关"
        assert 0 <= result["total"] <= 10
        # 父母关应有较高理论分 (BASE=8, normalized: 8/10*5=4.0, +0.5 gate bonus = 4.5)
        assert result["detail"]["theory"] >= 4.0

    def test_xingge_has_low_priority(self):
        """性格推断 → 排最后"""
        result = self.selector.calculate_discrimination_score(
            {"id": "pred_xg", "category": "性格"}
        )
        assert result["category"] == "性格"
        # 性格应有最低理论分 (BASE=3, normalized: 3/10*5=1.5, no gate bonus)
        assert result["detail"]["theory"] < 3.0

    def test_high_shichen_risk_boosts_parents(self):
        """父母关 + 高风险时辰 → 排第一"""
        result_normal = self.selector.calculate_discrimination_score(
            {"id": "pred_01", "category": "父母关"},
            make_low_uncertainty(),
        )
        result_risky = self.selector.calculate_discrimination_score(
            {"id": "pred_01", "category": "父母关"},
            make_high_uncertainty(),
        )
        # 高风险时 uncertainty_coverage 应更高
        assert result_risky["detail"]["uncertainty_coverage"] >= 2.0
        assert result_risky["detail"]["uncertainty_coverage"] > result_normal["detail"]["uncertainty_coverage"]

    def test_output_structure(self):
        """返回结构完整"""
        result = self.selector.calculate_discrimination_score(
            {"id": "pred_test", "category": "事业"}
        )
        assert "category" in result
        assert "total" in result
        assert "detail" in result
        assert "theory" in result["detail"]
        assert "uncertainty_coverage" in result["detail"]
        assert "friendliness" in result["detail"]

    def test_unknown_category_has_default(self):
        """未知类别有默认分"""
        result = self.selector.calculate_discrimination_score(
            {"id": "pred_unknown", "category": "未知类别"}
        )
        assert 0 <= result["total"] <= 10
        assert result["detail"]["theory"] <= 3.0  # default 5 → normalized 2.5

    def test_all_categories_in_valid_range(self):
        """所有类别的分数在0-10范围内"""
        for cat in ["性格", "父母关", "兄弟关", "学历", "婚姻关", "事业", "关键年份"]:
            result = self.selector.calculate_discrimination_score(
                {"id": "test", "category": cat}
            )
            assert 0 <= result["total"] <= 10, f"{cat} score={result['total']} out of range"


class TestSelectTopPredictions:
    """测试批量选取"""

    def setup_method(self):
        self.selector = SmartPredictionSelector()

    def test_selects_max_count(self):
        """选出的条数 <= max_count"""
        candidates = make_candidates()
        selected = self.selector.select_top_predictions(
            candidates, max_count=5
        )
        assert len(selected) == 5

    def test_ordered_by_score(self):
        """按得分降序排列"""
        candidates = make_candidates()
        selected = self.selector.select_top_predictions(
            candidates, max_count=7
        )
        # 验证顺序：第一个不应是性格（最低分）
        assert selected[0]["category"] != "性格"

    def test_parents_ranked_first_with_high_uncertainty(self):
        """父母关 + 高风险 → 排第一"""
        candidates = make_candidates()
        selected = self.selector.select_top_predictions(
            candidates,
            uncertainty=make_high_uncertainty(),
            max_count=7,
        )
        # 父母关应在最前面
        assert selected[0]["category"] in ("父母关", "兄弟关", "婚姻关")

    def test_xingge_ranked_last(self):
        """性格推断 → 排最后或倒数（因友好度高可能高于关键年份）"""
        candidates = make_candidates()
        selected = self.selector.select_top_predictions(
            candidates, max_count=7
        )
        # 性格和关键年份应是得分最低的两个
        last_two = {selected[-1]["category"], selected[-2]["category"]}
        assert "性格" in last_two
        assert "关键年份" in last_two

    def test_dynamic_question_count_supplement_streak(self):
        """连续3条supplement → max_count降为3"""
        candidates = make_candidates()
        history = {"supplement_streak": 3}
        selected = self.selector.select_top_predictions(
            candidates,
            history=history,
            max_count=5,
        )
        assert len(selected) == 3

    def test_supplement_streak_2_does_not_reduce(self):
        """连续2条supplement → 不降题量"""
        candidates = make_candidates()
        history = {"supplement_streak": 2}
        selected = self.selector.select_top_predictions(
            candidates,
            history=history,
            max_count=5,
        )
        assert len(selected) == 5

    def test_supplement_streak_4_stays_3(self):
        """连续4条supplement → 仍为3题"""
        candidates = make_candidates()
        history = {"supplement_streak": 4}
        selected = self.selector.select_top_predictions(
            candidates,
            history=history,
            max_count=5,
        )
        assert len(selected) == 3

    def test_asked_count_penalty(self):
        """已被问过的类别得分降低"""
        candidates = make_candidates()

        # 未问过的得分
        score_without = self.selector.calculate_discrimination_score(
            {"id": "pred_parents", "category": "父母关"},
            history={},
        )

        # 问过3次的得分
        history = {"asked_counts": {"父母关": 3}}
        score_with = self.selector.calculate_discrimination_score(
            {"id": "pred_parents", "category": "父母关"},
            history=history,
        )

        # 得分应有下降（friendliness 被惩罚）
        assert score_with["detail"]["friendliness"] < score_without["detail"]["friendliness"]
        assert score_with["total"] < score_without["total"]

    def test_default_params(self):
        """默认参数不报错"""
        candidates = make_candidates()
        selected = self.selector.select_top_predictions(candidates)
        assert len(selected) <= 5  # default max_count
        assert len(selected) > 0

    def test_empty_candidates(self):
        """空候选列表"""
        selected = self.selector.select_top_predictions([])
        assert len(selected) == 0

    def test_single_candidate(self):
        """单个候选"""
        candidates = [{"id": "pred_x", "category": "事业"}]
        selected = self.selector.select_top_predictions(candidates)
        assert len(selected) == 1


class TestIntegration:
    """集成测试"""

    def test_full_flow_normal(self):
        """正常流程：7个候选 + 正常不确定性 → 选出5个"""
        selector = SmartPredictionSelector()
        candidates = make_candidates()
        uncertainty = make_low_uncertainty()  # 低风险 = 低不确定性覆盖

        selected = selector.select_top_predictions(
            candidates, uncertainty=uncertainty, max_count=5
        )

        assert len(selected) == 5
        # 性格应该不在前5中（最低分）
        categories = [s["category"] for s in selected]
        assert "性格" not in categories

    def test_full_flow_high_uncertainty(self):
        """高不确定性：7个候选 → 选出5个，核心三关排前"""
        selector = SmartPredictionSelector()
        candidates = make_candidates()
        uncertainty = make_high_uncertainty()

        selected = selector.select_top_predictions(
            candidates, uncertainty=uncertainty, max_count=5
        )

        assert len(selected) == 5
        # 核心三关应有高分
        categories = [s["category"] for s in selected]
        core_gates = [c for c in categories if c in ("父母关", "兄弟关", "婚姻关")]
        assert len(core_gates) == 3  # all three core gates should be in top 5


class TestDiscriminationConstants:
    """验证常量和基础数据"""

    def test_base_discrimination_has_all_categories(self):
        """BASE_DISCRIMINATION 包含所有类别"""
        expected = {"父母关", "兄弟关", "婚姻关", "学历", "事业", "关键年份", "性格"}
        assert set(SmartPredictionSelector.BASE_DISCRIMINATION.keys()) == expected

    def test_base_values_in_range(self):
        """所有基础分在0-10范围"""
        for cat, score in SmartPredictionSelector.BASE_DISCRIMINATION.items():
            assert 0 <= score <= 10, f"{cat} base score={score} out of range"

    def test_core_gate_bonus(self):
        """核心三关有加成"""
        for cat in ["父母关", "兄弟关", "婚姻关"]:
            assert cat in SmartPredictionSelector.CORE_GATE_BONUS
            assert SmartPredictionSelector.CORE_GATE_BONUS[cat] > 0

    def test_non_core_categories_no_bonus(self):
        """非核心类别无加成"""
        non_core = ["学历", "事业", "关键年份", "性格"]
        for cat in non_core:
            assert SmartPredictionSelector.CORE_GATE_BONUS.get(cat, 0.0) == 0.0
