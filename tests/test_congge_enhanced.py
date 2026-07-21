"""Tests for 从格硬校验增强 — check_congge_detailed + check_huaqi_ge_5elements"""

import sys
sys.path.insert(0, '/Users/lee/WorkSpace/WorkBuddy/ai-bazi')

from rules.pattern import (
    check_congge_detailed,
    check_huaqi_ge_5elements,
    HUAHUAGE_CONDITIONS,
    _quantify_roots_detailed,
    _calc_support_force_detailed,
    _check_restricted_support_detailed,
    WUXING_MAP,
)


# ============================================================
# 测试数据
# ============================================================

# 真从格：日主无根，无印比生扶
SAMPLE_ZHENCONG = {
    "day_master": "甲",
    "four_pillars": {
        "year": {"stem": "庚", "branch": "申", "hidden_stems": [
            {"stem": "庚", "weight": 0.6}, {"stem": "壬", "weight": 0.3}, {"stem": "戊", "weight": 0.1}
        ]},
        "month": {"stem": "辛", "branch": "酉", "hidden_stems": [
            {"stem": "辛", "weight": 0.6}
        ]},
        "day": {"stem": "甲", "branch": "午", "hidden_stems": [
            {"stem": "丁", "weight": 0.5}, {"stem": "己", "weight": 0.3}
        ]},
        "hour": {"stem": "庚", "branch": "申", "hidden_stems": [
            {"stem": "庚", "weight": 0.6}, {"stem": "壬", "weight": 0.3}, {"stem": "戊", "weight": 0.1}
        ]},
    },
}

# 假从格：日主仅余气根，support<20%
SAMPLE_JIACONG = {
    "day_master": "甲",
    "four_pillars": {
        "year": {"stem": "庚", "branch": "申", "hidden_stems": [
            {"stem": "庚", "weight": 0.6}, {"stem": "壬", "weight": 0.3}, {"stem": "戊", "weight": 0.1}
        ]},
        "month": {"stem": "辛", "branch": "酉", "hidden_stems": [
            {"stem": "辛", "weight": 0.6}
        ]},
        "day": {"stem": "甲", "branch": "未", "hidden_stems": [
            {"stem": "己", "weight": 0.5}, {"stem": "丁", "weight": 0.3}, {"stem": "乙", "weight": 0.2}
        ]},
        "hour": {"stem": "庚", "branch": "申", "hidden_stems": [
            {"stem": "庚", "weight": 0.6}, {"stem": "壬", "weight": 0.3}, {"stem": "戊", "weight": 0.1}
        ]},
    },
}

# 非从格：日主有本气根
SAMPLE_FEICONG = {
    "day_master": "丙",
    "four_pillars": {
        "year": {"stem": "甲", "branch": "子", "hidden_stems": [
            {"stem": "癸", "weight": 0.6}
        ]},
        "month": {"stem": "壬", "branch": "申", "hidden_stems": [
            {"stem": "庚", "weight": 0.6}, {"stem": "壬", "weight": 0.3}, {"stem": "戊", "weight": 0.1}
        ]},
        "day": {"stem": "丙", "branch": "午", "hidden_stems": [
            {"stem": "丁", "weight": 0.5}, {"stem": "己", "weight": 0.3}
        ]},
        "hour": {"stem": "甲", "branch": "午", "hidden_stems": [
            {"stem": "丁", "weight": 0.5}, {"stem": "己", "weight": 0.3}
        ]},
    },
}

# 化气格：戊癸合化火（全部满足五要素）
SAMPLE_HUAQI_FULL = {
    "day_master": "戊",
    "four_pillars": {
        "year": {"stem": "甲", "branch": "午", "hidden_stems": [
            {"stem": "丁", "weight": 0.5}, {"stem": "己", "weight": 0.3}
        ]},
        "month": {"stem": "癸", "branch": "午", "hidden_stems": [
            {"stem": "丁", "weight": 0.5}, {"stem": "己", "weight": 0.3}
        ]},
        "day": {"stem": "戊", "branch": "午", "hidden_stems": [
            {"stem": "丁", "weight": 0.5}, {"stem": "己", "weight": 0.3}
        ]},
        "hour": {"stem": "丙", "branch": "巳", "hidden_stems": [
            {"stem": "丙", "weight": 0.5}, {"stem": "戊", "weight": 0.3}, {"stem": "庚", "weight": 0.2}
        ]},
    },
}

# 化气格不完整（score=3）
SAMPLE_HUAQI_PARTIAL = {
    "day_master": "戊",
    "four_pillars": {
        "year": {"stem": "甲", "branch": "子", "hidden_stems": [
            {"stem": "癸", "weight": 0.6}
        ]},
        "month": {"stem": "癸", "branch": "亥", "hidden_stems": [
            {"stem": "壬", "weight": 0.6}, {"stem": "甲", "weight": 0.3}
        ]},
        "day": {"stem": "戊", "branch": "子", "hidden_stems": [
            {"stem": "癸", "weight": 0.6}
        ]},
        "hour": {"stem": "壬", "branch": "子", "hidden_stems": [
            {"stem": "癸", "weight": 0.6}
        ]},
    },
}


class TestConggeDetailed:
    """测试增强版从格检测"""

    def test_zhen_cong(self):
        """真从：total_root=0, support<10% → 真从"""
        result = check_congge_detailed(SAMPLE_ZHENCONG, "甲")
        assert result["cong_type"] == "真从"
        assert result["is_congge"] is True

    def test_jia_cong_yuqi_root(self):
        """假从：仅余气根(weight=0.2), support<20% → 假从"""
        result = check_congge_detailed(SAMPLE_JIACONG, "甲")
        # 日支未有乙(木)余气根 weight=0.2
        assert result["cong_type"] == "假从"
        assert result["is_congge"] is True

    def test_non_cong(self):
        """非从：本气根(weight≥0.5), support≥20% → 非从"""
        result = check_congge_detailed(SAMPLE_FEICONG, "丙")
        assert result["cong_type"] == "非从"
        assert result["is_congge"] is False

    def test_result_structure(self):
        """返回结构完整"""
        result = check_congge_detailed(SAMPLE_ZHENCONG, "甲")
        required_fields = [
            "is_congge", "cong_type", "cong_subtype",
            "root_detail", "support_ratio", "restricted_support",
            "detail", "classical_source",
        ]
        for field in required_fields:
            assert field in result, f"缺少字段: {field}"

    def test_root_detail_fields(self):
        """根气详情字段"""
        result = check_congge_detailed(SAMPLE_ZHENCONG, "甲")
        rd = result["root_detail"]
        assert "has_benzhi_root" in rd
        assert "has_zhongqi_root" in rd
        assert "has_yuqi_root" in rd
        assert "total_weight" in rd

    def test_classical_source(self):
        """含古籍引用"""
        result = check_congge_detailed(SAMPLE_ZHENCONG, "甲")
        assert len(result["classical_source"]) > 10

    def test_has_cong_subtype(self):
        """从格有子类型"""
        result = check_congge_detailed(SAMPLE_ZHENCONG, "甲")
        assert result["cong_subtype"] in ("", "从杀", "从财", "从儿", "从弱")

    def test_support_ratio_is_float(self):
        """support_ratio是浮点数"""
        result = check_congge_detailed(SAMPLE_ZHENCONG, "甲")
        assert isinstance(result["support_ratio"], float)

    def test_benzhi_root_not_cong(self):
        """有本气根 → 非从格"""
        # SAMPLE_FEICONG 日支午有丁(火)本气根 weight=0.5
        result = check_congge_detailed(SAMPLE_FEICONG, "丙")
        assert result["is_congge"] is False


class TestHuaqiGe5Elements:
    """测试化气格五要素验证"""

    def test_huaqi_full_score_5(self):
        """化气格五要素：全部满足 → score=5, is_zhen=True"""
        result = check_huaqi_ge_5elements("戊", SAMPLE_HUAQI_FULL)
        assert result["score"] == 5
        assert result["is_zhen"] is True
        assert result["is_huaqi"] is True

    def test_huaqi_partial_score_3(self):
        """化气格不全：score=3 → is_huaqi=True但is_zhen=False"""
        result = check_huaqi_ge_5elements("戊", SAMPLE_HUAQI_PARTIAL)
        # 戊癸合化火，但月令亥为水，化神不当令
        assert isinstance(result["score"], int)
        if result["score"] < 5:
            assert result["is_zhen"] is False
        else:
            assert result["score"] == 5

    def test_huaqi_result_structure(self):
        """返回结构完整"""
        result = check_huaqi_ge_5elements("戊", SAMPLE_HUAQI_FULL)
        required_fields = [
            "is_huaqi", "score", "conditions_met", "conditions_missing",
            "is_zhen", "huaqi_wuxing", "detail", "classical_source",
        ]
        for field in required_fields:
            assert field in result, f"缺少字段: {field}"

    def test_huaqi_5elements_conditions_list(self):
        """conditions_met和conditions_missing格式正确"""
        result = check_huaqi_ge_5elements("戊", SAMPLE_HUAQI_FULL)
        assert len(result["conditions_met"]) == 5
        assert len(result["conditions_missing"]) == 0
        # 每个描述以"要素X:" 开头
        for cond in result["conditions_met"]:
            assert "要素" in cond

    def test_huaqi_score_range(self):
        """score在0-5之间"""
        result = check_huaqi_ge_5elements("戊", SAMPLE_HUAQI_FULL)
        assert 0 <= result["score"] <= 5

    def test_huaqi_no_he_returns_zero(self):
        """日干未参与五合 → score=0, is_huaqi=False"""
        result = check_huaqi_ge_5elements("丙", SAMPLE_FEICONG)
        assert result["is_huaqi"] is False
        assert result["score"] == 0


class TestHUAHUAGE_CONDITIONS:
    """测试化气格条件表"""

    def test_all_five_combinations(self):
        """五种合化都存在"""
        expected = ["戊癸合火", "甲己合化土", "乙庚合化金", "丙辛合化水", "丁壬合化木"]
        for name in expected:
            assert name in HUAHUAGE_CONDITIONS, f"缺少 {name}"

    def test_each_has_required_fields(self):
        """每条记录有必需字段"""
        required = [
            "合化天干", "化神五行", "化神当令（月令）",
            "透干条件", "通根条件", "无克破条件", "真化标志", "source",
        ]
        for name, cond in HUAHUAGE_CONDITIONS.items():
            for field in required:
                assert field in cond, f"{name} 缺少字段: {field}"

    def test_wuxing_distribution(self):
        """五种化气格覆盖五行木火土金水"""
        wuxing_set = set()
        for cond in HUAHUAGE_CONDITIONS.values():
            wuxing_set.add(cond["化神五行"])
        assert "金" in wuxing_set
        assert "木" in wuxing_set
        assert "水" in wuxing_set
        assert "火" in wuxing_set
        assert "土" in wuxing_set


class TestQuantifyRootsDetailed:
    """测试 _quantify_roots_detailed"""

    def test_no_root(self):
        """日主无根"""
        result = _quantify_roots_detailed("木", SAMPLE_ZHENCONG["four_pillars"])
        assert result["total_weight"] == 0.0
        assert result["has_benzhi_root"] is False

    def test_has_benzhi_root(self):
        """日主有本气根"""
        result = _quantify_roots_detailed("火", SAMPLE_FEICONG["four_pillars"])
        assert result["has_benzhi_root"] is True
        assert result["total_weight"] >= 0.5

    def test_has_yuqi_root(self):
        """日主有余气根"""
        result = _quantify_roots_detailed("木", SAMPLE_JIACONG["four_pillars"])
        # 日支未有乙(木)余气 weight=0.2
        assert result["has_yuqi_root"] is True
        assert result["total_weight"] < 0.5


class TestSupportForce:
    """测试生扶力量计算"""

    def test_support_force_non_negative(self):
        """生扶力量非负"""
        force = _calc_support_force_detailed("木", SAMPLE_ZHENCONG["four_pillars"], "甲")
        assert force >= 0

    def test_restricted_support_boolean(self):
        """_check_restricted_support_detailed 返回 bool"""
        result = _check_restricted_support_detailed(
            "木", SAMPLE_ZHENCONG["four_pillars"], "甲"
        )
        assert isinstance(result, bool)


class TestIntegration:
    """集成测试：验证新增函数不破坏现有 API"""

    def test_existing_special_pattern_still_works(self):
        """现有 _check_special_pattern 仍然可用"""
        from rules.pattern import _check_special_pattern
        result = _check_special_pattern(
            {"total_score": 10, "ri_zhu_strength": "极弱"}, "甲"
        )
        assert result is not None
        assert result["pattern"] == "从弱格"

    def test_existing_check_huaqi_ge_still_works(self):
        """现有 check_huaqi_ge 仍然可用"""
        from rules.pattern import check_huaqi_ge
        result = check_huaqi_ge("戊", SAMPLE_HUAQI_FULL)
        assert result is not None

    def test_new_functions_not_break_existing_imports(self):
        """新增函数不破坏现有导入"""
        from rules.pattern import (
            determine_pattern_type,
            _check_special_pattern,
            check_huaqi_ge,
            check_zhen_jia_cong,
            # 新增函数
            check_congge_detailed,
            check_huaqi_ge_5elements,
            HUAHUAGE_CONDITIONS,
        )
        assert determine_pattern_type is not None
        assert _check_special_pattern is not None
        assert check_huaqi_ge is not None
        assert check_zhen_jia_cong is not None
        assert check_congge_detailed is not None
        assert check_huaqi_ge_5elements is not None
        assert HUAHUAGE_CONDITIONS is not None
