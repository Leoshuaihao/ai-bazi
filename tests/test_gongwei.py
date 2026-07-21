"""Tests for rules/gongwei.py - 宫位取象规则模块"""

import pytest
from rules.gongwei import (
    GONGWEI_RULES,
    get_gongwei_info,
    get_age_gongwei,
    map_event_to_gongwei,
    gongwei_six_kin_cross_validate,
)


class TestGongweiInfo:
    """测试四柱各自返回正确的 domain/six_kin/event_types"""

    def test_nianzhu_info(self):
        info = get_gongwei_info("年柱")
        assert info["domain"] == "祖上/童年"
        assert info["age_range"] == (1, 16)
        assert "祖父母" in info["six_kin"]
        assert "父母" in info["six_kin"]
        assert "家庭出身" in info["event_types"]
        assert "祖业" in info["event_types"]

    def test_yuezhu_info(self):
        info = get_gongwei_info("月柱")
        assert info["domain"] == "父母/门第"
        assert info["age_range"] == (17, 32)
        assert "父母" in info["six_kin"]
        assert "兄弟" in info["six_kin"]
        assert "学历" in info["event_types"]
        assert "事业起步" in info["event_types"]

    def test_rizhu_info(self):
        info = get_gongwei_info("日柱")
        assert info["domain"] == "自身/配偶"
        assert info["age_range"] == (33, 48)
        assert "自己" in info["six_kin"]
        assert "配偶" in info["six_kin"]
        assert "婚姻" in info["event_types"]
        assert "事业高峰" in info["event_types"]

    def test_shizhu_info(self):
        info = get_gongwei_info("时柱")
        assert info["domain"] == "子女/晚年"
        assert info["age_range"] == (49, 99)
        assert "子女" in info["six_kin"]
        assert "子女状况" in info["event_types"]
        assert "晚年运" in info["event_types"]

    def test_invalid_pillar_returns_empty(self):
        info = get_gongwei_info("不存在的宫位")
        assert info == {}


class TestAgeGongwei:
    """测试年龄映射到正确宫位"""

    def test_age_10_year_pillar(self):
        """age=10 → 年柱 (1-16)"""
        assert get_age_gongwei(10) == "年柱"

    def test_age_1_year_pillar(self):
        """age=1 → 年柱 (边界)"""
        assert get_age_gongwei(1) == "年柱"

    def test_age_16_year_pillar(self):
        """age=16 → 年柱 (上边界)"""
        assert get_age_gongwei(16) == "年柱"

    def test_age_17_month_pillar(self):
        """age=17 → 月柱 (下边界)"""
        assert get_age_gongwei(17) == "月柱"

    def test_age_25_month_pillar(self):
        """age=25 → 月柱"""
        assert get_age_gongwei(25) == "月柱"

    def test_age_32_month_pillar(self):
        """age=32 → 月柱 (上边界)"""
        assert get_age_gongwei(32) == "月柱"

    def test_age_33_day_pillar(self):
        """age=33 → 日柱 (下边界)"""
        assert get_age_gongwei(33) == "日柱"

    def test_age_40_day_pillar(self):
        """age=40 → 日柱"""
        assert get_age_gongwei(40) == "日柱"

    def test_age_48_day_pillar(self):
        """age=48 → 日柱 (上边界)"""
        assert get_age_gongwei(48) == "日柱"

    def test_age_49_hour_pillar(self):
        """age=49 → 时柱 (下边界)"""
        assert get_age_gongwei(49) == "时柱"

    def test_age_60_hour_pillar(self):
        """age=60 → 时柱"""
        assert get_age_gongwei(60) == "时柱"

    def test_age_99_hour_pillar(self):
        """age=99 → 时柱 (上边界)"""
        assert get_age_gongwei(99) == "时柱"

    def test_age_100_hour_pillar(self):
        """age=100 → 时柱 (超出上界，归时柱)"""
        assert get_age_gongwei(100) == "时柱"

    def test_age_0_year_pillar(self):
        """age=0 → 年柱 (低于下界，归年柱)"""
        assert get_age_gongwei(0) == "年柱"


class TestMapEventToGongwei:
    """测试事件类型映射到宫位"""

    def test_marriage_to_day_pillar(self):
        """'婚姻' → 日柱"""
        assert map_event_to_gongwei("婚姻") == "日柱"

    def test_education_to_month_pillar(self):
        """'学历' → 月柱"""
        assert map_event_to_gongwei("学历") == "月柱"

    def test_old_age_to_hour_pillar(self):
        """'晚年运' → 时柱"""
        assert map_event_to_gongwei("晚年运") == "时柱"

    def test_family_origin_to_year_pillar(self):
        """'家庭出身' → 年柱"""
        assert map_event_to_gongwei("家庭出身") == "年柱"

    def test_ancestral_estate_to_year_pillar(self):
        """'祖业' → 年柱"""
        assert map_event_to_gongwei("祖业") == "年柱"

    def test_career_start_to_month_pillar(self):
        """'事业起步' → 月柱"""
        assert map_event_to_gongwei("事业起步") == "月柱"

    def test_career_peak_to_day_pillar(self):
        """'事业高峰' → 日柱"""
        assert map_event_to_gongwei("事业高峰") == "日柱"

    def test_children_to_hour_pillar(self):
        """'子女状况' → 时柱"""
        assert map_event_to_gongwei("子女状况") == "时柱"

    def test_unknown_event_defaults_to_day(self):
        """未知事件类型默认返回日柱"""
        assert map_event_to_gongwei("未知事件") == "日柱"


class TestSixKinCrossValidate:
    """测试六亲交叉验证"""

    def test_year_pillar_grandparents(self):
        """年柱 + 祖父母 → True"""
        assert gongwei_six_kin_cross_validate("年柱", "祖父母") is True

    def test_year_pillar_parents(self):
        """年柱 + 父母 → True"""
        assert gongwei_six_kin_cross_validate("年柱", "父母") is True

    def test_day_pillar_grandparents(self):
        """日柱 + 祖父母 → False"""
        assert gongwei_six_kin_cross_validate("日柱", "祖父母") is False

    def test_day_pillar_spouse(self):
        """日柱 + 配偶 → True"""
        assert gongwei_six_kin_cross_validate("日柱", "配偶") is True

    def test_day_pillar_self(self):
        """日柱 + 自己 → True"""
        assert gongwei_six_kin_cross_validate("日柱", "自己") is True

    def test_month_pillar_siblings(self):
        """月柱 + 兄弟 → True"""
        assert gongwei_six_kin_cross_validate("月柱", "兄弟") is True

    def test_month_pillar_parents(self):
        """月柱 + 父母 → True"""
        assert gongwei_six_kin_cross_validate("月柱", "父母") is True

    def test_hour_pillar_children(self):
        """时柱 + 子女 → True"""
        assert gongwei_six_kin_cross_validate("时柱", "子女") is True

    def test_hour_pillar_parents(self):
        """时柱 + 父母 → False"""
        assert gongwei_six_kin_cross_validate("时柱", "父母") is False

    def test_invalid_pillar_returns_false(self):
        """无效宫位 → False"""
        assert gongwei_six_kin_cross_validate("不存在", "祖父母") is False

    def test_unknown_six_kin_in_valid_pillar(self):
        """有效宫位 + 不匹配的六亲 → False"""
        assert gongwei_six_kin_cross_validate("年柱", "配偶") is False


class TestGongweiRulesConsistency:
    """测试 GONGWEI_RULES 数据完整性"""

    def test_all_four_pillars_exist(self):
        """四个宫位都存在"""
        for pillar in ["年柱", "月柱", "日柱", "时柱"]:
            assert pillar in GONGWEI_RULES

    def test_all_pillars_have_required_keys(self):
        """每个宫位都有所有必需字段"""
        required = ["domain", "age_range", "six_kin", "event_types", "social_layer"]
        for pillar, rules in GONGWEI_RULES.items():
            for key in required:
                assert key in rules, f"{pillar} missing key: {key}"

    def test_age_ranges_are_contiguous_and_non_overlapping(self):
        """年龄范围连续且不重叠"""
        pillars_order = ["年柱", "月柱", "日柱", "时柱"]
        prev_hi = 0
        for pillar in pillars_order:
            lo, hi = GONGWEI_RULES[pillar]["age_range"]
            assert lo == prev_hi + 1, (
                f"{pillar} starts at {lo}, expected {prev_hi + 1}"
            )
            assert hi >= lo, f"{pillar} hi={hi} < lo={lo}"
            prev_hi = hi
        # 最后一个应覆盖到 99
        assert prev_hi == 99, f"Last pillar ends at {prev_hi}, expected 99"

    def test_six_kin_lists_are_non_empty(self):
        """每个宫位的 six_kin 列表非空"""
        for pillar, rules in GONGWEI_RULES.items():
            assert len(rules["six_kin"]) > 0, f"{pillar} six_kin is empty"

    def test_event_types_lists_are_non_empty(self):
        """每个宫位的 event_types 列表非空"""
        for pillar, rules in GONGWEI_RULES.items():
            assert len(rules["event_types"]) > 0, f"{pillar} event_types is empty"
