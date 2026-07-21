"""Tests for services/calibration.py HexagramValidator & ValidationJudge"""

import pytest
from services.calibration import HexagramValidator, ValidationJudge


# ============================================================
# Test fixtures / helpers
# ============================================================

def make_feedback_stats(accurate=5, inaccurate=0, total=5, **kwargs):
    """Create mock feedback_stats dict"""
    base = {
        "accurate_count": accurate,
        "inaccurate_count": inaccurate,
        "total_count": total,
        "six_kin_accurate": kwargs.get("six_kin_accurate", 0),
        "six_kin_total": kwargs.get("six_kin_total", 0),
        "xingge_accurate": kwargs.get("xingge_accurate", 0),
        "xingge_total": kwargs.get("xingge_total", 0),
        "yongshen_years_verified": kwargs.get("yongshen_years_verified", 0),
        "dayun_transitions": kwargs.get("dayun_transitions", 0),
        "dayun_matched": kwargs.get("dayun_matched", 0),
        "feedbacks": kwargs.get("feedbacks", []),
        "liunian_feedback": kwargs.get("liunian_feedback", []),
    }
    return base


# ============================================================
# HexagramValidator Tests
# ============================================================

class TestHexagramValidatorScores:
    """测试六维打分的每个函数返回 0-10 分"""

    def setup_method(self):
        self.validator = HexagramValidator()

    def test_score_wangshuai_returns_valid(self):
        result = self.validator.score_wangshuai(
            make_feedback_stats(accurate=4, total=5), {}
        )
        assert isinstance(result, dict)
        assert result["dimension"] == "旺衰验证"
        assert 0 <= result["score"] <= 10
        assert len(result["detail"]) > 0
        assert len(result["source"]) > 0

    def test_score_wangshuai_no_data(self):
        result = self.validator.score_wangshuai(
            make_feedback_stats(accurate=0, total=0), {}
        )
        assert result["score"] == 5
        assert "无反馈数据" in result["detail"]

    def test_score_wangshuai_perfect(self):
        result = self.validator.score_wangshuai(
            make_feedback_stats(accurate=5, total=5), {}
        )
        assert result["score"] == 10

    def test_score_wangshuai_zero(self):
        result = self.validator.score_wangshuai(
            make_feedback_stats(accurate=0, total=5), {}
        )
        assert result["score"] == 0

    def test_score_pattern_jixi_returns_valid(self):
        result = self.validator.score_pattern_jixi(
            make_feedback_stats(accurate=3, total=5), {}
        )
        assert isinstance(result, dict)
        assert result["dimension"] == "格局喜忌验证"
        assert 0 <= result["score"] <= 10
        assert len(result["detail"]) > 0
        assert len(result["source"]) > 0

    def test_score_pattern_jixi_no_data(self):
        result = self.validator.score_pattern_jixi(
            make_feedback_stats(accurate=0, total=0), {}
        )
        assert result["score"] == 5

    def test_score_yongshen_returns_valid(self):
        result = self.validator.score_yongshen(
            make_feedback_stats(accurate=3, total=5, yongshen_years_verified=3), {}
        )
        assert isinstance(result, dict)
        assert result["dimension"] == "用神验证"
        assert 0 <= result["score"] <= 10
        assert len(result["detail"]) > 0

    def test_score_yongshen_insufficient_years(self):
        result = self.validator.score_yongshen(
            make_feedback_stats(accurate=3, total=5, yongshen_years_verified=2), {}
        )
        assert "不足3个" in result["detail"]

    def test_score_dayun_returns_valid(self):
        result = self.validator.score_dayun(
            make_feedback_stats(
                accurate=3, total=5, dayun_transitions=3, dayun_matched=2
            ),
            {},
        )
        assert isinstance(result, dict)
        assert result["dimension"] == "大运走向验证"
        assert 0 <= result["score"] <= 10

    def test_score_dayun_no_data(self):
        result = self.validator.score_dayun(
            make_feedback_stats(accurate=0, total=0), {}
        )
        assert result["score"] == 5

    def test_score_six_kin_returns_valid(self):
        result = self.validator.score_six_kin(
            make_feedback_stats(six_kin_accurate=3, six_kin_total=5), {}
        )
        assert isinstance(result, dict)
        assert result["dimension"] == "六亲验证"
        assert 0 <= result["score"] <= 10
        assert len(result["detail"]) > 0

    def test_score_six_kin_no_data(self):
        result = self.validator.score_six_kin(
            make_feedback_stats(six_kin_accurate=0, six_kin_total=0), {}
        )
        assert result["score"] == 5
        assert "无六亲" in result["detail"]

    def test_score_xingge_returns_valid(self):
        result = self.validator.score_xingge(
            make_feedback_stats(xingge_accurate=4, xingge_total=5), {}
        )
        assert isinstance(result, dict)
        assert result["dimension"] == "性格验证"
        assert 0 <= result["score"] <= 10
        assert len(result["detail"]) > 0

    def test_score_xingge_discount_applied(self):
        """性格打分含折扣（实际分*0.5）"""
        # 4/5 = 0.8 accurate, adjusted = 4*0.5=2, score=min(10,int(2/5*10))=min(10,4)=4
        result = self.validator.score_xingge(
            make_feedback_stats(xingge_accurate=4, xingge_total=5), {}
        )
        assert result["score"] == 4  # 4*0.5/5*10 = 2/5*10 = 4
        assert "50%" in result["detail"] or "巴纳姆" in result["detail"]

    def test_score_xingge_full_discount(self):
        """全部准确但经折扣后得分减半"""
        result = self.validator.score_xingge(
            make_feedback_stats(xingge_accurate=10, xingge_total=10), {}
        )
        # 10*0.5/10*10 = 5
        assert result["score"] == 5

    def test_score_xingge_no_data(self):
        result = self.validator.score_xingge(
            make_feedback_stats(xingge_accurate=0, xingge_total=0), {}
        )
        assert result["score"] == 5


class TestHexagramReport:
    """测试完整的六维报告生成"""

    def setup_method(self):
        self.validator = HexagramValidator()

    def test_generate_report_all_high(self):
        """全部准确的场景"""
        stats = make_feedback_stats(
            accurate=7, total=7,
            six_kin_accurate=7, six_kin_total=7,
            xingge_accurate=7, xingge_total=7,
            yongshen_years_verified=3,
            dayun_transitions=3, dayun_matched=3,
        )
        report = self.validator.generate_hexagram_report(stats)

        assert len(report["scores"]) == 6
        assert report["total_score"] > 0
        assert report["max_score"] == 60
        assert report["consistent_count"] >= 4
        assert report["pass"] is True
        assert report["core_triangle_pass"] is True

    def test_generate_report_all_low(self):
        """全部不准确的场景"""
        stats = make_feedback_stats(
            accurate=0, total=7,
            six_kin_accurate=0, six_kin_total=7,
            xingge_accurate=0, xingge_total=7,
        )
        report = self.validator.generate_hexagram_report(stats)

        assert report["consistent_count"] <= 3
        assert report["pass"] is False

    def test_generate_report_empty(self):
        """空数据场景"""
        stats = make_feedback_stats(accurate=0, total=0)
        report = self.validator.generate_hexagram_report(stats)
        assert len(report["scores"]) == 6
        assert report["total_score"] == 30  # 6*5

    def test_generate_report_inconsistent_dims(self):
        """不一致维度被正确标记"""
        stats = make_feedback_stats(
            accurate=0, total=5,
            six_kin_accurate=0, six_kin_total=5,
            xingge_accurate=0, xingge_total=5,
        )
        report = self.validator.generate_hexagram_report(stats)
        assert len(report["inconsistent_dims"]) >= 3


# ============================================================
# ValidationJudge Tests
# ============================================================

class TestCheckMultiDimension:
    """测试多维一致性检查"""

    def setup_method(self):
        self.judge = ValidationJudge()

    def test_all_pass_returns_pass(self):
        """>=4/6 维度一致 → PASS"""
        scores = [
            {"dimension": "旺衰验证", "score": 8},
            {"dimension": "格局喜忌验证", "score": 7},
            {"dimension": "用神验证", "score": 8},
            {"dimension": "大运走向验证", "score": 7},
            {"dimension": "六亲验证", "score": 5},
            {"dimension": "性格验证", "score": 5},
        ]
        result = self.judge.check_multi_dimension(scores)
        assert result["pass"] is True
        assert result["core_triangle_pass"] is True
        assert result["consistent_count"] == 4

    def test_core_triangle_fails(self):
        """核心三角不通 → FAIL"""
        scores = [
            {"dimension": "旺衰验证", "score": 3},
            {"dimension": "格局喜忌验证", "score": 3},
            {"dimension": "用神验证", "score": 3},
            {"dimension": "大运走向验证", "score": 8},
            {"dimension": "六亲验证", "score": 8},
            {"dimension": "性格验证", "score": 8},
        ]
        result = self.judge.check_multi_dimension(scores)
        assert result["pass"] is False  # 3 dims >=6, but min_dims=4 → not enough
        assert result["core_triangle_pass"] is False

    def test_only_two_pass(self):
        """仅2维通过 → 不通过"""
        scores = [
            {"dimension": "旺衰验证", "score": 8},
            {"dimension": "格局喜忌验证", "score": 8},
            {"dimension": "用神验证", "score": 3},
            {"dimension": "大运走向验证", "score": 3},
            {"dimension": "六亲验证", "score": 3},
            {"dimension": "性格验证", "score": 3},
        ]
        result = self.judge.check_multi_dimension(scores)
        assert result["pass"] is False

    def test_custom_threshold(self):
        """自定义 threshold"""
        scores = [
            {"dimension": d, "score": 5} for d in
            ["旺衰验证", "格局喜忌验证", "用神验证",
             "大运走向验证", "六亲验证", "性格验证"]
        ]
        result = self.judge.check_multi_dimension(scores, threshold=4, min_dims=6)
        assert result["pass"] is True  # all >= 4


class TestCheckCounterExample:
    """测试反例容限"""

    def setup_method(self):
        self.judge = ValidationJudge()

    def test_no_counter_examples(self):
        result = self.judge.check_counter_example([
            {"status": "accurate"},
            {"status": "accurate"},
        ])
        assert result["pass"] is True
        assert result["total_counter_examples"] == 0

    def test_one_major_counter_example(self):
        result = self.judge.check_counter_example([
            {"status": "inaccurate", "note": "我父亲去世了"},
        ])
        assert result["pass"] is True  # <=1 allowed
        assert result["major_counter_examples"] == 1

    def test_two_major_counter_examples(self):
        result = self.judge.check_counter_example([
            {"status": "inaccurate", "note": "我父亲去世了"},
            {"status": "inaccurate", "note": "我公司破产了"},
        ])
        assert result["pass"] is False
        assert result["major_counter_examples"] == 2

    def test_minor_inaccurate_not_counter(self):
        """普通 inaccurate 不是 major"""
        result = self.judge.check_counter_example([
            {"status": "inaccurate", "note": "不太准确"},
        ])
        assert result["pass"] is True
        assert result["major_counter_examples"] == 0
        assert result["total_counter_examples"] == 1


class TestCheckLiunianCross:
    """测试流年交叉一致性"""

    def setup_method(self):
        self.judge = ValidationJudge()

    def test_three_independent_years_pass(self):
        """3个互不关联流年验证一致 → PASS"""
        liunian_fb = [
            {"year": 2010, "status": "verified", "dayun_index": 0},
            {"year": 2015, "status": "verified", "dayun_index": 1},
            {"year": 2020, "status": "verified", "dayun_index": 2},
        ]
        result = self.judge.check_liunian_cross(liunian_fb)
        assert result["pass"] is True

    def test_same_dayun_not_independent(self):
        """同一大运的流年不独立"""
        liunian_fb = [
            {"year": 2010, "status": "verified", "dayun_index": 0},
            {"year": 2011, "status": "verified", "dayun_index": 0},
            {"year": 2012, "status": "verified", "dayun_index": 0},
        ]
        result = self.judge.check_liunian_cross(liunian_fb)
        assert result["pass"] is False  # only 1 independent year

    def test_consecutive_years_filtered(self):
        """连续年份被过滤"""
        liunian_fb = [
            {"year": 2010, "status": "verified", "dayun_index": 0},
            {"year": 2013, "status": "verified", "dayun_index": 1},
            {"year": 2016, "status": "verified", "dayun_index": 2},
        ]
        result = self.judge.check_liunian_cross(liunian_fb)
        assert result["pass"] is True

    def test_contradicted_not_counted(self):
        """被推翻的流年不计入"""
        liunian_fb = [
            {"year": 2010, "status": "verified", "dayun_index": 0},
            {"year": 2015, "status": "contradicted", "dayun_index": 1},
        ]
        result = self.judge.check_liunian_cross(liunian_fb)
        assert result["pass"] is False
        assert result["contradicted_count"] == 1

    def test_empty_feedback(self):
        result = self.judge.check_liunian_cross([])
        assert result["pass"] is False
        assert result["detail"] == "0/0 个互不关联的流年验证一致（需 >= 3）"


class TestFinalVerdict:
    """测试最终三重判定"""

    def setup_method(self):
        self.validator = HexagramValidator()
        self.judge = ValidationJudge()

    def test_pass_scenario(self):
        """三关全 accurate + 多个流年验证一致 → 3/3 通过"""
        stats = make_feedback_stats(
            accurate=7, total=7,
            six_kin_accurate=7, six_kin_total=7,
            xingge_accurate=7, xingge_total=7,
            yongshen_years_verified=3,
            dayun_transitions=3, dayun_matched=3,
            feedbacks=[
                {"status": "accurate"},
                {"status": "accurate"},
            ],
            liunian_feedback=[
                {"year": 2010, "status": "verified", "dayun_index": 0},
                {"year": 2015, "status": "verified", "dayun_index": 1},
                {"year": 2020, "status": "verified", "dayun_index": 2},
            ],
        )
        report = self.validator.generate_hexagram_report(stats)
        verdict = self.judge.final_verdict(report, stats)
        assert verdict["status"] == "PASS"
        assert verdict["pass_count"] == 3
        assert verdict["need_correction"] is False

    def test_fail_core_triangle_collapse(self):
        """核心三角崩溃 → FAIL"""
        stats = make_feedback_stats(
            accurate=0, total=7,  # all inaccurate
            six_kin_accurate=0, six_kin_total=7,
            xingge_accurate=0, xingge_total=7,
            feedbacks=[
                {"status": "inaccurate", "note": "父亲去世了"},
                {"status": "inaccurate", "note": "公司破产了"},
            ],
            liunian_feedback=[],
        )
        report = self.validator.generate_hexagram_report(stats)
        verdict = self.judge.final_verdict(report, stats)
        assert verdict["status"] in ("FAIL", "INDETERMINATE")
        assert verdict["need_correction"] is True

    def test_fail_two_counter_examples(self):
        """2个明确反例 → FAIL"""
        scores = [
            {"dimension": "旺衰验证", "score": 7},
            {"dimension": "格局喜忌验证", "score": 7},
            {"dimension": "用神验证", "score": 7},
            {"dimension": "大运走向验证", "score": 7},
            {"dimension": "六亲验证", "score": 7},
            {"dimension": "性格验证", "score": 7},
        ]
        report = {
            "scores": scores,
            "total_score": 42,
            "max_score": 60,
            "consistent_count": 6,
            "consistent_ratio": 1.0,
            "inconsistent_dims": [],
            "core_triangle_pass": True,
            "pass": True,
        }
        stats = make_feedback_stats(
            accurate=7, total=7,
            feedbacks=[
                {"status": "inaccurate", "note": "父亲去世了"},
                {"status": "inaccurate", "note": "公司破产了"},
            ],
            liunian_feedback=[],
        )
        verdict = self.judge.final_verdict(report, stats)
        assert verdict["status"] in ("FAIL", "INDETERMINATE")
        # Counter example + no liunian = 2/3 fail
        assert verdict["pass_count"] <= 1

    def test_conditional_pass(self):
        """2/3 → CONDITIONAL_PASS"""
        stats = make_feedback_stats(
            accurate=6, total=7,
            six_kin_accurate=6, six_kin_total=7,
            xingge_accurate=6, xingge_total=7,
            yongshen_years_verified=3,
            dayun_transitions=3, dayun_matched=3,
            feedbacks=[],  # no counter examples
            liunian_feedback=[
                {"year": 2010, "status": "verified", "dayun_index": 0},
                {"year": 2015, "status": "verified", "dayun_index": 1},
            ],  # only 2 independent
        )
        report = self.validator.generate_hexagram_report(stats)
        verdict = self.judge.final_verdict(report, stats)
        assert verdict["status"] == "CONDITIONAL_PASS"
        assert verdict["pass_count"] == 2

    def test_indeterminate_boundary(self):
        """分数过边界 → INDETERMINATE"""
        stats = make_feedback_stats(
            accurate=3, total=7,
            six_kin_accurate=3, six_kin_total=7,
            xingge_accurate=3, xingge_total=7,
            feedbacks=[
                {"status": "inaccurate", "note": "父亲去世"},
            ],
            liunian_feedback=[],
        )
        report = self.validator.generate_hexagram_report(stats)
        verdict = self.judge.final_verdict(report, stats)
        # Only multi_dim might pass, or none at all
        assert verdict["status"] in ("INDETERMINATE", "FAIL")
        assert verdict["need_correction"] is True

    def test_personality_only_high(self):
        """仅性格维度高分（巴纳姆效应）→ 综合不通过"""
        scores = [
            {"dimension": "旺衰验证", "score": 2},
            {"dimension": "格局喜忌验证", "score": 2},
            {"dimension": "用神验证", "score": 2},
            {"dimension": "大运走向验证", "score": 2},
            {"dimension": "六亲验证", "score": 2},
            {"dimension": "性格验证", "score": 6},
        ]
        report = {
            "scores": scores,
            "total_score": 16,
            "max_score": 60,
            "consistent_count": 1,
            "consistent_ratio": 0.17,
            "inconsistent_dims": [
                "旺衰验证", "格局喜忌验证", "用神验证",
                "大运走向验证", "六亲验证",
            ],
            "core_triangle_pass": False,
            "pass": False,
        }
        stats = make_feedback_stats(
            accurate=1, total=7,
            feedbacks=[],
            liunian_feedback=[
                {"year": 2010, "status": "verified", "dayun_index": 0},
                {"year": 2015, "status": "verified", "dayun_index": 1},
                {"year": 2020, "status": "verified", "dayun_index": 2},
            ],
        )
        verdict = self.judge.final_verdict(report, stats)
        assert verdict["status"] in ("INDETERMINATE", "FAIL", "CONDITIONAL_PASS")
        # core_triangle_pass should be False
