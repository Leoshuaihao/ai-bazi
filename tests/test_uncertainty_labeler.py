"""Tests for services/precheck/uncertainty_labeler.py"""

import pytest
from services.precheck.uncertainty_labeler import (
    UncertaintyItem,
    UncertaintyReport,
    _label_shichen_risk,
    _label_yongshen_risk,
    _label_wangshuai_risk,
    _label_pattern_risk,
    _label_congge_risk,
    generate_uncertainty_report,
    mock_uncertainty_report,
)


# ============================================================
# Mock data
# ============================================================

def make_mock_chart_data(hour=12, minute=0, month=1, day=1,
                         day_master="甲", with_hidden=True,
                         extra_stems=None):
    """创建 mock chart_data"""
    hidden_stems = [
        {"stem": "甲", "weight": 0.6},
        {"stem": "丙", "weight": 0.25},
        {"stem": "戊", "weight": 0.15},
    ]
    data = {
        "birth_info": {
            "hour": hour,
            "minute": minute,
            "month": month,
            "day": day,
        },
        "day_master": day_master,
        "four_pillars": {
            "year": {"stem": "壬", "branch": "寅",
                     "hidden_stems": hidden_stems if with_hidden else []},
            "month": {"stem": "癸", "branch": "卯",
                      "hidden_stems": hidden_stems if with_hidden else []},
            "day": {"stem": day_master, "branch": "辰",
                    "hidden_stems": hidden_stems if with_hidden else []},
            "hour": {"stem": "丙", "branch": "午",
                     "hidden_stems": hidden_stems if with_hidden else []},
        },
    }
    if extra_stems:
        for pos, extra in extra_stems.items():
            if pos in data["four_pillars"]:
                data["four_pillars"][pos]["stem"] = extra
    return data


def make_mock_yongshen_data(primary="火", pattern="正官格", ji_shen="水"):
    """创建 mock yongshen_data"""
    return {
        "primary": primary,
        "secondary": "木",
        "ji_shen": ji_shen,
        "pattern": pattern,
        "ri_zhu_strength": "中和",
    }


def make_mock_strength_detail(total_score=50):
    """创建 mock strength_detail"""
    return {
        "total_score": total_score,
        "deling": {"score": 12},
        "dedi": {"score": 13},
        "desheng": {"score": 14},
        "dezhu": {"score": 11},
    }


# ============================================================
# Tests
# ============================================================

class TestUncertaintyLabeler:
    """测试五维标注正常运作"""

    def test_mock_data_all_five_dimensions(self):
        """Mock数据五维标注正常"""
        chart = make_mock_chart_data()
        yongshen = make_mock_yongshen_data()
        strength = make_mock_strength_detail(50)

        report = generate_uncertainty_report(
            chart_data=chart,
            yongshen_data=yongshen,
            strength_detail=strength,
            birth_longitude=120.0,
            memory_uncertain=False,
        )

        assert isinstance(report, UncertaintyReport)
        assert len(report.items) == 5

        # All 5 dimensions present
        dims = {item.dimension for item in report.items}
        assert dims == {"shichen", "yongshen", "wangshuai", "pattern", "congge"}

    def test_all_risk_scores_in_range(self):
        """风险分在0-1范围"""
        chart = make_mock_chart_data()
        yongshen = make_mock_yongshen_data()
        strength = make_mock_strength_detail(50)

        report = generate_uncertainty_report(
            chart_data=chart,
            yongshen_data=yongshen,
            strength_detail=strength,
        )

        for item in report.items:
            assert 0.0 <= item.risk_score <= 1.0, (
                f"{item.dimension} risk_score={item.risk_score} out of range"
            )
        assert 0.0 <= report.overall_risk <= 1.0

    def test_all_five_dimensions_have_meaningful_detail(self):
        """所有5个维度都返回有意义的detail文本"""
        chart = make_mock_chart_data()
        yongshen = make_mock_yongshen_data()
        strength = make_mock_strength_detail(50)

        report = generate_uncertainty_report(
            chart_data=chart,
            yongshen_data=yongshen,
            strength_detail=strength,
        )

        for item in report.items:
            assert item.detail, f"{item.dimension} detail is empty"
            assert len(item.detail) > 0
            assert isinstance(item.detail, str)

    def test_composite_risk_is_average(self):
        """综合风险正确聚合（五个维度平均值）"""
        chart = make_mock_chart_data()
        yongshen = make_mock_yongshen_data()
        strength = make_mock_strength_detail(50)

        report = generate_uncertainty_report(
            chart_data=chart,
            yongshen_data=yongshen,
            strength_detail=strength,
        )

        expected_avg = sum(item.risk_score for item in report.items) / 5
        assert report.overall_risk == round(expected_avg, 2)

    def test_high_risk_shichen_at_twilight(self):
        """子时出生 + 西部经度 → 高风险"""
        chart = make_mock_chart_data(hour=23, minute=15)
        yongshen = make_mock_yongshen_data()
        strength = make_mock_strength_detail(50)

        report = generate_uncertainty_report(
            chart_data=chart,
            yongshen_data=yongshen,
            strength_detail=strength,
            birth_longitude=104.0,  # 成都
        )

        shichen_item = next(
            i for i in report.items if i.dimension == "shichen"
        )
        assert shichen_item.risk_score >= 0.5  # 至少中风险
        assert shichen_item.label in ("中风险", "高风险")

    def test_low_risk_noon_shanghai(self):
        """午时 + 上海经度 → 低风险"""
        chart = make_mock_chart_data(hour=12, minute=0)
        yongshen = make_mock_yongshen_data()
        strength = make_mock_strength_detail(50)

        report = generate_uncertainty_report(
            chart_data=chart,
            yongshen_data=yongshen,
            strength_detail=strength,
            birth_longitude=121.0,  # 上海
        )

        shichen_item = next(
            i for i in report.items if i.dimension == "shichen"
        )
        assert shichen_item.risk_score < 0.2

    def test_wangshuai_at_boundary(self):
        """旺衰边界探测：total_score=62 → 中风险"""
        chart = make_mock_chart_data()
        yongshen = make_mock_yongshen_data()
        strength = make_mock_strength_detail(62)

        report = generate_uncertainty_report(
            chart_data=chart,
            yongshen_data=yongshen,
            strength_detail=strength,
        )

        ws_item = next(
            i for i in report.items if i.dimension == "wangshuai"
        )
        assert ws_item.risk_score >= 0.3

    def test_wangshuai_clear(self):
        """total_score=70 → 低风险（非边界）"""
        chart = make_mock_chart_data()
        yongshen = make_mock_yongshen_data()
        strength = make_mock_strength_detail(70)

        report = generate_uncertainty_report(
            chart_data=chart,
            yongshen_data=yongshen,
            strength_detail=strength,
        )

        ws_item = next(
            i for i in report.items if i.dimension == "wangshuai"
        )
        assert ws_item.risk_score < 0.3

    def test_yongshen_multi_touchu(self):
        """月令藏干多透 → 高用神风险"""
        # Create chart with multiple hidden_stems matching pillar stems
        chart = make_mock_chart_data()
        # Set stems to match hidden_stems to trigger multi-touch
        chart["four_pillars"]["year"]["stem"] = "甲"   # matches hidden_stems[0]
        chart["four_pillars"]["hour"]["stem"] = "丙"   # matches hidden_stems[1]
        chart["four_pillars"]["month"]["stem"] = "戊"  # matches hidden_stems[2]
        yongshen = make_mock_yongshen_data()
        strength = make_mock_strength_detail(50)

        report = generate_uncertainty_report(
            chart_data=chart,
            yongshen_data=yongshen,
            strength_detail=strength,
        )

        ys_item = next(
            i for i in report.items if i.dimension == "yongshen"
        )
        assert ys_item.risk_score >= 0.3

    def test_congge_not_applicable_for_non_congge(self):
        """非从格 → congge 标注不适用"""
        chart = make_mock_chart_data()
        yongshen = make_mock_yongshen_data(pattern="正官格")
        strength = make_mock_strength_detail(50)

        report = generate_uncertainty_report(
            chart_data=chart,
            yongshen_data=yongshen,
            strength_detail=strength,
        )

        cg_item = next(
            i for i in report.items if i.dimension == "congge"
        )
        assert cg_item.risk_score == 0.0
        assert "不适用" in cg_item.detail

    def test_congge_risk_for_congge_pattern(self):
        """从格格局 → 有实际风险计算"""
        chart = make_mock_chart_data()
        # Set hidden stems to have no support for the day master
        chart["four_pillars"]["year"]["hidden_stems"] = [{"stem": "丙", "weight": 0.3}]
        chart["four_pillars"]["month"]["hidden_stems"] = [{"stem": "丁", "weight": 0.3}]
        chart["four_pillars"]["day"]["hidden_stems"] = [{"stem": "戊", "weight": 0.3}]
        chart["four_pillars"]["hour"]["hidden_stems"] = [{"stem": "己", "weight": 0.3}]
        yongshen = make_mock_yongshen_data(pattern="从弱格")
        strength = make_mock_strength_detail(10)

        report = generate_uncertainty_report(
            chart_data=chart,
            yongshen_data=yongshen,
            strength_detail=strength,
        )

        cg_item = next(
            i for i in report.items if i.dimension == "congge"
        )
        # Should have some risk since congge pattern
        assert "不适用" not in cg_item.detail

    def test_memory_uncertain_adds_risk(self):
        """memory_uncertain=True → 增加时辰风险"""
        chart = make_mock_chart_data(hour=12, minute=0)
        yongshen = make_mock_yongshen_data()
        strength = make_mock_strength_detail(50)

        report_no_memory = generate_uncertainty_report(
            chart_data=chart,
            yongshen_data=yongshen,
            strength_detail=strength,
            birth_longitude=120.0,
            memory_uncertain=False,
        )

        report_with_memory = generate_uncertainty_report(
            chart_data=chart,
            yongshen_data=yongshen,
            strength_detail=strength,
            birth_longitude=120.0,
            memory_uncertain=True,
        )

        shichen_no = next(
            i for i in report_no_memory.items if i.dimension == "shichen"
        )
        shichen_with = next(
            i for i in report_with_memory.items if i.dimension == "shichen"
        )
        assert shichen_with.risk_score > shichen_no.risk_score

    def test_yongshen_ji_and_yong_together(self):
        """用神与忌神同时透干 → 用神风险增加"""
        # 甲日主，用神为木(甲/乙), but we need a case where both
        # yongshen and jishen are visible
        chart = make_mock_chart_data(day_master="甲")
        # primary=火(jishen=水), add a 水 stem in year
        chart["four_pillars"]["year"]["stem"] = "壬"  # 壬→水
        chart["four_pillars"]["hour"]["stem"] = "丙"  # 丙→火
        yongshen = make_mock_yongshen_data(primary="火", ji_shen="水", pattern="正官格")
        strength = make_mock_strength_detail(50)

        report = generate_uncertainty_report(
            chart_data=chart,
            yongshen_data=yongshen,
            strength_detail=strength,
        )

        ys_item = next(
            i for i in report.items if i.dimension == "yongshen"
        )
        assert ys_item.risk_score >= 0.2

    def test_pattern_boundary_total_score(self):
        """total_score 在从格边界 → 格局多解风险"""
        chart = make_mock_chart_data()
        yongshen = make_mock_yongshen_data(pattern="正官格")
        strength = make_mock_strength_detail(78)  # 接近 75-85 from-strong boundary

        report = generate_uncertainty_report(
            chart_data=chart,
            yongshen_data=yongshen,
            strength_detail=strength,
        )

        pat_item = next(
            i for i in report.items if i.dimension == "pattern"
        )
        assert pat_item.risk_score >= 0.3

    def test_jieqi_proximity_adds_shichen_risk(self):
        """节气交接附近增加时辰风险"""
        # Jan 5 at 23:00 is 1 hour before 小寒 (Jan 6 00:00)
        chart = make_mock_chart_data(hour=23, minute=0, month=1, day=5)
        yongshen = make_mock_yongshen_data()
        strength = make_mock_strength_detail(50)

        report = generate_uncertainty_report(
            chart_data=chart,
            yongshen_data=yongshen,
            strength_detail=strength,
        )

        shichen_item = next(
            i for i in report.items if i.dimension == "shichen"
        )
        # Should have elevated risk from jieqi proximity (within 1 hour)
        assert shichen_item.risk_score >= 0.2

    def test_label_mapping(self):
        """label 根据 risk_score 正确映射"""
        # Low risk
        item_low = _label_shichen_risk(hour=12, minute=0, birth_longitude=120.0)
        assert item_low.label == "低风险"

        # Medium risk
        item_mid = _label_shichen_risk(hour=12, minute=0, birth_longitude=100.0)
        assert item_mid.label == "中风险"

        # High risk
        item_high = _label_shichen_risk(hour=23, minute=0, birth_longitude=104.0)
        assert item_high.label == "高风险"


class TestMockFallback:
    """测试 Mock 回退"""

    def test_mock_returns_valid_report(self):
        report = mock_uncertainty_report()
        assert isinstance(report, UncertaintyReport)
        assert len(report.items) == 5
        assert report.overall_risk == 0.3
        assert all(item.risk_score == 0.3 for item in report.items)
        assert all(item.label == "中风险" for item in report.items)
        assert len(report.suggested_questions) == 1


class TestIndividualDimensionFunctions:
    """测试各维度单独调用"""

    def test_label_shichen_risk_returns_uncertainty_item(self):
        item = _label_shichen_risk(hour=12, minute=0)
        assert isinstance(item, UncertaintyItem)
        assert item.dimension == "shichen"
        assert 0.0 <= item.risk_score <= 1.0

    def test_label_wangshuai_risk_high_at_mid(self):
        """得分在 (45,55) → 高风险"""
        item = _label_wangshuai_risk({"total_score": 50})
        assert item.risk_score >= 0.5
        assert item.label == "高风险"

    def test_label_wangshuai_risk_medium_at_boundary(self):
        """得分在 [35,45] → 中风险"""
        item = _label_wangshuai_risk({"total_score": 40})
        assert item.risk_score >= 0.4
        assert item.label == "中风险"

    def test_label_wangshuai_risk_low_at_normal(self):
        """得分在正常范围 → 低风险"""
        item = _label_wangshuai_risk({"total_score": 70})
        assert item.risk_score < 0.3
        assert item.label == "低风险"

    def test_label_congge_not_applicable(self):
        """非从格 → risk=0"""
        item = _label_congge_risk(
            "正官格", {"total_score": 50}, {"day_master": "甲", "four_pillars": {}}
        )
        assert item.risk_score == 0.0
        assert item.label == "低风险"

    def test_label_pattern_risk_normal(self):
        """正常格局 → 低风险"""
        item = _label_pattern_risk(
            "正官格",
            {"total_score": 50},
            {"day_master": "甲", "four_pillars": {
                "year": {"stem": "壬", "branch": "寅",
                         "hidden_stems": [{"stem": "甲", "weight": 0.6}]},
                "month": {"stem": "癸", "branch": "卯",
                          "hidden_stems": [{"stem": "乙", "weight": 0.6}]},
                "day": {"stem": "甲", "branch": "辰",
                        "hidden_stems": [{"stem": "戊", "weight": 0.6}]},
                "hour": {"stem": "丙", "branch": "午",
                         "hidden_stems": [{"stem": "丁", "weight": 0.6}]},
            }},
        )
        assert item.risk_score < 0.3


class TestIntegratedReport:
    """集成测试：完整报告生成"""

    def test_suggested_questions_present(self):
        chart = make_mock_chart_data()
        yongshen = make_mock_yongshen_data()
        strength = make_mock_strength_detail(50)

        report = generate_uncertainty_report(
            chart_data=chart,
            yongshen_data=yongshen,
            strength_detail=strength,
        )

        assert len(report.suggested_questions) > 0
        for q in report.suggested_questions:
            assert isinstance(q, str)
            assert len(q) > 0

    def test_default_values_work(self):
        """默认参数不报错"""
        report = generate_uncertainty_report(
            chart_data={"birth_info": {}, "four_pillars": {}, "day_master": "甲"},
            yongshen_data={"pattern": "正官格"},
        )
        assert isinstance(report, UncertaintyReport)
        assert report.overall_risk is not None
