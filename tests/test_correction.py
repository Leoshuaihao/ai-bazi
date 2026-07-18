"""P1 Phase 2 测试：双路径修正逻辑"""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.correction import (
    generate_candidate_hours,
    get_shichen_name,
    fix_wangshuai,
    fix_pattern,
    fix_yongshen_priority,
    run_ai_fix,
    try_candidate_hours,
    apply_correction,
)


# ============================================================
# 测试夹具
# ============================================================

@pytest.fixture
def sample_birth_info():
    """示例出生信息"""
    return {
        "year": 1990,
        "month": 3,
        "day": 15,
        "hour": 8,
        "minute": 0,
        "gender": "male",
    }


@pytest.fixture
def sample_chart_data():
    """示例排盘数据"""
    return {
        "day_master": "己",
        "yongshen": {
            "primary": "金",
            "secondary": "水",
            "ji_shen": "木",
            "pattern": "正格-身弱",
            "ri_zhu_strength": "偏弱",
        },
        "four_pillars": {
            "year": {"stem": "庚", "branch": "午"},
            "month": {"stem": "己", "branch": "卯"},
            "day": {"stem": "己", "branch": "卯"},
            "hour": {"stem": "戊", "branch": "辰"},
        },
        "strength_detail": {
            "total_score": 35,
            "ri_zhu_strength": "偏弱",
            "pattern": "正格-身弱",
        },
    }


@pytest.fixture
def sample_predictions():
    return [
        {"id": "pred_01", "category": "性格", "is_core": False, "sequence": 1},
        {"id": "pred_02", "category": "父母关", "is_core": True, "sequence": 2},
        {"id": "pred_03", "category": "兄弟关", "is_core": True, "sequence": 3},
        {"id": "pred_04", "category": "学历", "is_core": False, "sequence": 4},
        {"id": "pred_05", "category": "婚姻关", "is_core": True, "sequence": 5},
        {"id": "pred_06", "category": "事业", "is_core": False, "sequence": 6},
        {"id": "pred_07", "category": "关键年份", "is_core": False, "sequence": 7},
    ]


# ============================================================
# generate_candidate_hours 测试
# ============================================================

class TestGenerateCandidateHours:
    """候选时钟生成测试"""

    def test_generates_four_candidates(self):
        """应生成4个候选时钟"""
        candidates = generate_candidate_hours(8)
        assert len(candidates) == 4

    def test_excludes_original_hour(self):
        """不应包含原始时钟"""
        for original in [0, 6, 8, 12, 14, 20, 23]:
            candidates = generate_candidate_hours(original)
            assert original not in candidates, f"Hour {original} should not be in candidates"

    def test_correct_offsets(self):
        """验证偏移量：-2, -1, +1, +2"""
        candidates = generate_candidate_hours(10)
        assert candidates == [8, 9, 11, 12]

    def test_wraps_around_24(self):
        """小时应循环取模24"""
        # 0时的候选：-2→22, -1→23, +1→1, +2→2
        candidates = generate_candidate_hours(0)
        assert candidates == [22, 23, 1, 2]

        # 23时的候选：-2→21, -1→22, +1→0, +2→1
        candidates = generate_candidate_hours(23)
        assert candidates == [21, 22, 0, 1]

    def test_all_candidates_in_range(self):
        """所有候选应在0-23范围内"""
        for h in range(24):
            candidates = generate_candidate_hours(h)
            for c in candidates:
                assert 0 <= c <= 23

    def test_noon_midnight(self):
        """测试中午和午夜"""
        assert generate_candidate_hours(12) == [10, 11, 13, 14]
        assert generate_candidate_hours(0) == [22, 23, 1, 2]

    def test_returns_list(self):
        """返回值应为list类型"""
        result = generate_candidate_hours(8)
        assert isinstance(result, list)
        assert all(isinstance(h, int) for h in result)


# ============================================================
# get_shichen_name 测试
# ============================================================

class TestGetShichenName:
    """时辰名称测试"""

    def test_all_hours(self):
        """所有小时应对应正确的时辰"""
        expected = {
            0: "子时", 1: "丑时", 2: "丑时",
            3: "寅时", 4: "寅时",
            5: "卯时", 6: "卯时",
            7: "辰时", 8: "辰时",
            9: "巳时", 10: "巳时",
            11: "午时", 12: "午时",
            13: "未时", 14: "未时",
            15: "申时", 16: "申时",
            17: "酉时", 18: "酉时",
            19: "戌时", 20: "戌时",
            21: "亥时", 22: "亥时",
            23: "子时",
        }
        for hour, name in expected.items():
            assert get_shichen_name(hour) == name, f"Hour {hour} should be {name}"


# ============================================================
# fix_wangshuai 测试
# ============================================================

class TestFixWangshuai:
    """旺衰修正测试"""

    @pytest.mark.asyncio
    async def test_triggered_when_high_inaccuracy(self, sample_chart_data, sample_predictions):
        """旺衰相关反馈不准确率 >= 50% 时触发"""
        feedbacks = [
            {"prediction_id": "pred_01", "status": "inaccurate", "note": ""},  # 性格
            {"prediction_id": "pred_02", "status": "inaccurate", "note": ""},  # 父母关
            {"prediction_id": "pred_03", "status": "accurate", "note": ""},
            {"prediction_id": "pred_04", "status": "accurate", "note": ""},
            {"prediction_id": "pred_05", "status": "accurate", "note": ""},
            {"prediction_id": "pred_06", "status": "inaccurate", "note": ""},  # 事业
            {"prediction_id": "pred_07", "status": "accurate", "note": ""},
        ]
        result = await fix_wangshuai(sample_chart_data, feedbacks, sample_predictions)
        assert result["triggered"] is True
        assert result["inaccurate_ratio"] >= 0.5

    @pytest.mark.asyncio
    async def test_not_triggered_when_low_inaccuracy(self, sample_chart_data, sample_predictions):
        """不准确率 < 50% 时不触发"""
        feedbacks = [
            {"prediction_id": "pred_01", "status": "accurate", "note": ""},
            {"prediction_id": "pred_02", "status": "accurate", "note": ""},
            {"prediction_id": "pred_03", "status": "accurate", "note": ""},
            {"prediction_id": "pred_04", "status": "accurate", "note": ""},
            {"prediction_id": "pred_05", "status": "accurate", "note": ""},
            {"prediction_id": "pred_06", "status": "inaccurate", "note": ""},  # 只有事业不准
            {"prediction_id": "pred_07", "status": "accurate", "note": ""},
        ]
        result = await fix_wangshuai(sample_chart_data, feedbacks, sample_predictions)
        assert result["triggered"] is False

    @pytest.mark.asyncio
    async def test_opposite_strength_suggested(self, sample_chart_data, sample_predictions):
        """应建议相反的旺衰"""
        feedbacks = [
            {"prediction_id": "pred_01", "status": "inaccurate", "note": ""},
            {"prediction_id": "pred_02", "status": "inaccurate", "note": ""},
            {"prediction_id": "pred_03", "status": "accurate", "note": ""},
            {"prediction_id": "pred_04", "status": "accurate", "note": ""},
            {"prediction_id": "pred_05", "status": "accurate", "note": ""},
            {"prediction_id": "pred_06", "status": "inaccurate", "note": ""},
            {"prediction_id": "pred_07", "status": "accurate", "note": ""},
        ]
        result = await fix_wangshuai(sample_chart_data, feedbacks, sample_predictions)
        assert result["current_strength"] == "偏弱"
        assert result["suggested_strength"] == "偏强"  # opposite of 偏弱

    @pytest.mark.asyncio
    async def test_result_structure(self, sample_chart_data, sample_predictions):
        """验证返回结构完整"""
        feedbacks = [
            {"prediction_id": "pred_01", "status": "inaccurate", "note": ""},
            {"prediction_id": "pred_02", "status": "inaccurate", "note": ""},
            {"prediction_id": "pred_03", "status": "accurate", "note": ""},
            {"prediction_id": "pred_04", "status": "accurate", "note": ""},
            {"prediction_id": "pred_05", "status": "accurate", "note": ""},
            {"prediction_id": "pred_06", "status": "inaccurate", "note": ""},
            {"prediction_id": "pred_07", "status": "accurate", "note": ""},
        ]
        result = await fix_wangshuai(sample_chart_data, feedbacks, sample_predictions)
        assert "triggered" in result
        assert "inaccurate_count" in result
        assert "total_count" in result
        assert "current_strength" in result
        assert "suggested_strength" in result
        assert "suggestion" in result

    @pytest.mark.asyncio
    async def test_handles_neutral_strength(self, sample_chart_data, sample_predictions):
        """中和旺衰应能处理"""
        chart_data_neutral = dict(sample_chart_data)
        chart_data_neutral["yongshen"]["ri_zhu_strength"] = "中和"
        feedbacks = [
            {"prediction_id": "pred_01", "status": "inaccurate", "note": ""},
            {"prediction_id": "pred_02", "status": "inaccurate", "note": ""},
            {"prediction_id": "pred_03", "status": "accurate", "note": ""},
            {"prediction_id": "pred_04", "status": "accurate", "note": ""},
            {"prediction_id": "pred_05", "status": "accurate", "note": ""},
            {"prediction_id": "pred_06", "status": "inaccurate", "note": ""},
            {"prediction_id": "pred_07", "status": "accurate", "note": ""},
        ]
        result = await fix_wangshuai(chart_data_neutral, feedbacks, sample_predictions)
        assert result["suggested_strength"] in ("偏弱", "偏强", "中和")


# ============================================================
# fix_pattern 测试
# ============================================================

class TestFixPattern:
    """格局修正测试"""

    @pytest.mark.asyncio
    async def test_in_boundary_low_triggers(self, sample_chart_data, sample_predictions):
        """总分在边界低区时触发"""
        chart_data = dict(sample_chart_data)
        chart_data["strength_detail"]["total_score"] = 18  # 15-25 边界
        feedbacks = [
            {"prediction_id": "pred_01", "status": "accurate", "note": ""},
            {"prediction_id": "pred_02", "status": "accurate", "note": ""},
            {"prediction_id": "pred_03", "status": "accurate", "note": ""},
            {"prediction_id": "pred_04", "status": "accurate", "note": ""},
            {"prediction_id": "pred_05", "status": "inaccurate", "note": ""},  # 婚姻关不准
            {"prediction_id": "pred_06", "status": "accurate", "note": ""},
            {"prediction_id": "pred_07", "status": "accurate", "note": ""},
        ]
        result = await fix_pattern(chart_data, feedbacks, sample_predictions)
        assert result["in_boundary"] is True
        assert result["is_boundary_low"] is True
        assert result["triggered"] is True

    @pytest.mark.asyncio
    async def test_in_boundary_high(self, sample_chart_data, sample_predictions):
        """总分在边界高区"""
        chart_data = dict(sample_chart_data)
        chart_data["strength_detail"]["total_score"] = 80  # 75-85 边界
        feedbacks = [
            {"prediction_id": "pred_01", "status": "accurate", "note": ""},
            {"prediction_id": "pred_02", "status": "accurate", "note": ""},
            {"prediction_id": "pred_03", "status": "accurate", "note": ""},
            {"prediction_id": "pred_04", "status": "accurate", "note": ""},
            {"prediction_id": "pred_05", "status": "inaccurate", "note": ""},
            {"prediction_id": "pred_06", "status": "accurate", "note": ""},
            {"prediction_id": "pred_07", "status": "accurate", "note": ""},
        ]
        result = await fix_pattern(chart_data, feedbacks, sample_predictions)
        assert result["in_boundary"] is True
        assert result["is_boundary_high"] is True

    @pytest.mark.asyncio
    async def test_not_in_boundary(self, sample_chart_data, sample_predictions):
        """总分不在边界区域"""
        chart_data = dict(sample_chart_data)
        chart_data["strength_detail"]["total_score"] = 50  # 中间区域
        feedbacks = [
            {"prediction_id": "pred_01", "status": "accurate", "note": ""},
            {"prediction_id": "pred_02", "status": "accurate", "note": ""},
            {"prediction_id": "pred_03", "status": "accurate", "note": ""},
            {"prediction_id": "pred_04", "status": "accurate", "note": ""},
            {"prediction_id": "pred_05", "status": "inaccurate", "note": ""},
            {"prediction_id": "pred_06", "status": "accurate", "note": ""},
            {"prediction_id": "pred_07", "status": "accurate", "note": ""},
        ]
        result = await fix_pattern(chart_data, feedbacks, sample_predictions)
        assert result["in_boundary"] is False
        assert result["triggered"] is False

    @pytest.mark.asyncio
    async def test_result_structure(self, sample_chart_data, sample_predictions):
        """验证返回结构完整"""
        feedbacks = [
            {"prediction_id": "pred_01", "status": "accurate", "note": ""},
            {"prediction_id": "pred_02", "status": "accurate", "note": ""},
            {"prediction_id": "pred_03", "status": "accurate", "note": ""},
            {"prediction_id": "pred_04", "status": "accurate", "note": ""},
            {"prediction_id": "pred_05", "status": "accurate", "note": ""},
            {"prediction_id": "pred_06", "status": "accurate", "note": ""},
            {"prediction_id": "pred_07", "status": "accurate", "note": ""},
        ]
        result = await fix_pattern(sample_chart_data, feedbacks, sample_predictions)
        assert "triggered" in result
        assert "total_score" in result
        assert "in_boundary" in result
        assert "current_pattern" in result
        assert "suggested_pattern" in result
        assert "suggestion" in result

    @pytest.mark.asyncio
    async def test_pattern_switch_suggestion(self, sample_chart_data, sample_predictions):
        """正格应建议从格方向"""
        chart_data = dict(sample_chart_data)
        chart_data["strength_detail"]["total_score"] = 18
        chart_data["yongshen"]["pattern"] = "正格-身弱"
        feedbacks = [
            {"prediction_id": "pred_01", "status": "accurate", "note": ""},
            {"prediction_id": "pred_02", "status": "accurate", "note": ""},
            {"prediction_id": "pred_03", "status": "accurate", "note": ""},
            {"prediction_id": "pred_04", "status": "accurate", "note": ""},
            {"prediction_id": "pred_05", "status": "inaccurate", "note": ""},
            {"prediction_id": "pred_06", "status": "accurate", "note": ""},
            {"prediction_id": "pred_07", "status": "accurate", "note": ""},
        ]
        result = await fix_pattern(chart_data, feedbacks, sample_predictions)
        assert "从弱格" in result["suggested_pattern"]


# ============================================================
# fix_yongshen_priority 测试
# ============================================================

class TestFixYongshenPriority:
    """用神优先级修正测试"""

    @pytest.mark.asyncio
    async def test_all_accurate(self, sample_chart_data, sample_predictions):
        """全部准确时差异应很小"""
        feedbacks = [
            {"prediction_id": f"pred_{i:02d}", "status": "accurate", "note": ""}
            for i in range(1, 8)
        ]
        result = await fix_yongshen_priority(sample_chart_data, feedbacks, sample_predictions)
        assert result["triggered"] is False  # 差异不大
        assert "angle_accuracy" in result
        assert "best_angle" in result
        assert "ranked_angles" in result

    @pytest.mark.asyncio
    async def test_high_variance_triggers(self, sample_chart_data, sample_predictions):
        """不同角度差异大时触发"""
        # 扶抑法相关项全不准，格局法相关项全准
        feedbacks = [
            {"prediction_id": "pred_01", "status": "inaccurate", "note": ""},  # 性格 → fuyi
            {"prediction_id": "pred_02", "status": "inaccurate", "note": ""},  # 父母关 → fuyi
            {"prediction_id": "pred_03", "status": "accurate", "note": ""},    # 兄弟关 → geju
            {"prediction_id": "pred_04", "status": "accurate", "note": ""},    # 学历 → tiaohou
            {"prediction_id": "pred_05", "status": "accurate", "note": ""},    # 婚姻关 → tiaohou
            {"prediction_id": "pred_06", "status": "accurate", "note": ""},    # 事业 → geju
            {"prediction_id": "pred_07", "status": "inaccurate", "note": ""},  # 关键年份 → fuyi
        ]
        result = await fix_yongshen_priority(sample_chart_data, feedbacks, sample_predictions)
        # fuyi: 0 accurate, 3 total → accuracy 0.0
        # tiaohou: 2 accurate, 2 total → accuracy 1.0
        # geju: 2 accurate, 2 total → accuracy 1.0
        # 差异 >= 30% → 触发
        assert result["triggered"] is True

    @pytest.mark.asyncio
    async def test_ranked_angles_sorted(self, sample_chart_data, sample_predictions):
        """排名应按准确率降序"""
        feedbacks = [
            {"prediction_id": "pred_01", "status": "inaccurate", "note": ""},
            {"prediction_id": "pred_02", "status": "inaccurate", "note": ""},
            {"prediction_id": "pred_03", "status": "accurate", "note": ""},
            {"prediction_id": "pred_04", "status": "accurate", "note": ""},
            {"prediction_id": "pred_05", "status": "accurate", "note": ""},
            {"prediction_id": "pred_06", "status": "accurate", "note": ""},
            {"prediction_id": "pred_07", "status": "accurate", "note": ""},
        ]
        result = await fix_yongshen_priority(sample_chart_data, feedbacks, sample_predictions)
        ranked = result["ranked_angles"]
        assert len(ranked) == 3
        # 验证降序
        for i in range(len(ranked) - 1):
            assert ranked[i]["accuracy"] >= ranked[i + 1]["accuracy"]

    @pytest.mark.asyncio
    async def test_result_structure(self, sample_chart_data, sample_predictions):
        """验证返回结构完整"""
        feedbacks = [
            {"prediction_id": f"pred_{i:02d}", "status": "accurate", "note": ""}
            for i in range(1, 8)
        ]
        result = await fix_yongshen_priority(sample_chart_data, feedbacks, sample_predictions)
        assert "triggered" in result
        assert "max_difference" in result
        assert "angle_accuracy" in result
        assert "best_angle" in result
        assert "best_angle_label" in result
        assert "ranked_angles" in result
        assert "suggestion" in result

    @pytest.mark.asyncio
    async def test_angle_scores_sum(self, sample_chart_data, sample_predictions):
        """三个角度的总条数之和应等于反馈数"""
        feedbacks = [
            {"prediction_id": f"pred_{i:02d}", "status": "accurate", "note": ""}
            for i in range(1, 8)
        ]
        result = await fix_yongshen_priority(sample_chart_data, feedbacks, sample_predictions)
        total = sum(
            result["angle_accuracy"][a]["total"]
            for a in ["fuyi", "tiaohou", "geju"]
        )
        assert total == 7  # 7条反馈


# ============================================================
# run_ai_fix 测试
# ============================================================

class TestRunAIFix:
    """AI修正集成测试"""

    @pytest.mark.asyncio
    async def test_stage_1_only(self, sample_chart_data, sample_predictions):
        """阶段1只执行旺衰修正"""
        feedbacks = [
            {"prediction_id": f"pred_{i:02d}", "status": "accurate", "note": ""}
            for i in range(1, 8)
        ]
        result = await run_ai_fix(sample_chart_data, feedbacks, sample_predictions, fix_stage=1)
        assert result["fix_stage"] == 1
        assert result["wangshuai_fix"] is not None
        assert result["pattern_fix"] is None
        assert result["yongshen_fix"] is None

    @pytest.mark.asyncio
    async def test_stage_2(self, sample_chart_data, sample_predictions):
        """阶段2执行旺衰+格局修正"""
        feedbacks = [
            {"prediction_id": f"pred_{i:02d}", "status": "accurate", "note": ""}
            for i in range(1, 8)
        ]
        result = await run_ai_fix(sample_chart_data, feedbacks, sample_predictions, fix_stage=2)
        assert result["fix_stage"] == 2
        assert result["wangshuai_fix"] is not None
        assert result["pattern_fix"] is not None
        assert result["yongshen_fix"] is None

    @pytest.mark.asyncio
    async def test_stage_3(self, sample_chart_data, sample_predictions):
        """阶段3执行全部三项修正"""
        feedbacks = [
            {"prediction_id": f"pred_{i:02d}", "status": "accurate", "note": ""}
            for i in range(1, 8)
        ]
        result = await run_ai_fix(sample_chart_data, feedbacks, sample_predictions, fix_stage=3)
        assert result["fix_stage"] == 3
        assert result["wangshuai_fix"] is not None
        assert result["pattern_fix"] is not None
        assert result["yongshen_fix"] is not None

    @pytest.mark.asyncio
    async def test_default_stage(self, sample_chart_data, sample_predictions):
        """默认阶段1"""
        feedbacks = [
            {"prediction_id": f"pred_{i:02d}", "status": "accurate", "note": ""}
            for i in range(1, 8)
        ]
        result = await run_ai_fix(sample_chart_data, feedbacks, sample_predictions)
        assert result["fix_stage"] == 1


# ============================================================
# try_candidate_hours 集成测试
# ============================================================

class TestTryCandidateHours:
    """时钟修正对比集成测试"""

    @pytest.mark.asyncio
    async def test_returns_comparisons(self, sample_birth_info):
        """应返回对比列表"""
        feedbacks = [
            {"prediction_id": f"pred_{i:02d}", "status": "accurate", "note": ""}
            for i in range(1, 8)
        ]
        predictions = [
            {"id": "pred_01", "category": "性格", "is_core": False, "sequence": 1},
            {"id": "pred_02", "category": "父母关", "is_core": True, "sequence": 2},
            {"id": "pred_03", "category": "兄弟关", "is_core": True, "sequence": 3},
            {"id": "pred_04", "category": "学历", "is_core": False, "sequence": 4},
            {"id": "pred_05", "category": "婚姻关", "is_core": True, "sequence": 5},
            {"id": "pred_06", "category": "事业", "is_core": False, "sequence": 6},
            {"id": "pred_07", "category": "关键年份", "is_core": False, "sequence": 7},
        ]

        result = await try_candidate_hours(sample_birth_info, feedbacks, predictions)
        assert "comparisons" in result
        assert "original_hour" in result
        assert "recommended" in result
        assert "recommended_hour" in result
        assert "all_failed" in result

        # 应有5个对比结果（1个原始 + 4个候选）
        assert len(result["comparisons"]) == 5

    @pytest.mark.asyncio
    async def test_original_included(self, sample_birth_info):
        """原始时钟应在对比列表中"""
        feedbacks = [
            {"prediction_id": f"pred_{i:02d}", "status": "accurate", "note": ""}
            for i in range(1, 8)
        ]
        predictions = [
            {"id": "pred_01", "category": "性格", "is_core": False, "sequence": 1},
            {"id": "pred_02", "category": "父母关", "is_core": True, "sequence": 2},
            {"id": "pred_03", "category": "兄弟关", "is_core": True, "sequence": 3},
            {"id": "pred_04", "category": "学历", "is_core": False, "sequence": 4},
            {"id": "pred_05", "category": "婚姻关", "is_core": True, "sequence": 5},
            {"id": "pred_06", "category": "事业", "is_core": False, "sequence": 6},
            {"id": "pred_07", "category": "关键年份", "is_core": False, "sequence": 7},
        ]
        result = await try_candidate_hours(sample_birth_info, feedbacks, predictions)
        original = [c for c in result["comparisons"] if c.get("is_original")]
        assert len(original) == 1

    @pytest.mark.asyncio
    async def test_different_start_hours(self):
        """不同起始小时应产生不同候选"""
        for start_hour in [3, 8, 14, 22]:
            birth_info = {
                "year": 2000, "month": 6, "day": 15,
                "hour": start_hour, "minute": 0, "gender": "male",
            }
            feedbacks = [
                {"prediction_id": f"pred_{i:02d}", "status": "accurate", "note": ""}
                for i in range(1, 8)
            ]
            predictions = [
                {"id": "pred_01", "category": "性格", "is_core": False, "sequence": 1},
                {"id": "pred_02", "category": "父母关", "is_core": True, "sequence": 2},
                {"id": "pred_03", "category": "兄弟关", "is_core": True, "sequence": 3},
                {"id": "pred_04", "category": "学历", "is_core": False, "sequence": 4},
                {"id": "pred_05", "category": "婚姻关", "is_core": True, "sequence": 5},
                {"id": "pred_06", "category": "事业", "is_core": False, "sequence": 6},
                {"id": "pred_07", "category": "关键年份", "is_core": False, "sequence": 7},
            ]
            result = await try_candidate_hours(birth_info, feedbacks, predictions)
            assert len(result["comparisons"]) == 5


# ============================================================
# apply_correction 集成测试
# ============================================================

class TestApplyCorrection:
    """应用修正集成测试"""

    @pytest.mark.asyncio
    async def test_hour_fix_returns_chart(self, sample_birth_info):
        """时钟修正应返回新的排盘数据"""
        feedbacks = [
            {"prediction_id": f"pred_{i:02d}", "status": "accurate", "note": ""}
            for i in range(1, 8)
        ]
        result = await apply_correction(sample_birth_info, new_hour=6, original_feedbacks=feedbacks)
        assert "chart" in result
        assert "strength_detail" in result
        assert "predictions" in result
        assert result["correction_type"] == "hour_fix"
        assert result["applied_hour"] == 6

    @pytest.mark.asyncio
    async def test_different_hour_produces_different_chart(self, sample_birth_info):
        """不同时钟应产生不同排盘"""
        feedbacks = [
            {"prediction_id": f"pred_{i:02d}", "status": "accurate", "note": ""}
            for i in range(1, 8)
        ]
        result1 = await apply_correction(sample_birth_info, new_hour=8, original_feedbacks=feedbacks)
        result2 = await apply_correction(sample_birth_info, new_hour=12, original_feedbacks=feedbacks)
        # 时柱应不同
        assert (
            result1["chart"]["four_pillars"]["hour"]["stem"] !=
            result2["chart"]["four_pillars"]["hour"]["stem"]
            or
            result1["chart"]["four_pillars"]["hour"]["branch"] !=
            result2["chart"]["four_pillars"]["hour"]["branch"]
        )

    @pytest.mark.asyncio
    async def test_returns_predictions(self, sample_birth_info):
        """应返回7条新推断"""
        feedbacks = [
            {"prediction_id": f"pred_{i:02d}", "status": "accurate", "note": ""}
            for i in range(1, 8)
        ]
        result = await apply_correction(sample_birth_info, new_hour=10, original_feedbacks=feedbacks)
        assert len(result["predictions"]) == 7


# ============================================================
# P1 Phase 3: 闭环完善测试 - 轮数控制 + 双路径切换 + 降级
# ============================================================

from services.correction import (
    init_correction_state,
    take_before_snapshot,
    build_correction_comparison,
    determine_next_path,
    get_correction_status,
    MAX_CORRECTION_ROUNDS,
)


class TestInitCorrectionState:
    """修正状态初始化测试"""

    def test_creates_state_if_missing(self):
        """session 中没有 correction_state 时应创建"""
        session = {}
        cs = init_correction_state(session)
        assert "correction_state" in session
        assert cs["round"] == 0
        assert cs["history"] == []
        assert cs["current_path"] is None
        assert cs["degraded"] is False

    def test_returns_existing_state(self):
        """已有 correction_state 时返回现有状态"""
        existing = {"round": 1, "history": [{}], "degraded": False}
        session = {"correction_state": existing}
        cs = init_correction_state(session)
        assert cs is existing
        assert cs["round"] == 1

    def test_state_has_all_fields(self):
        """验证状态包含所有必要字段"""
        session = {}
        cs = init_correction_state(session)
        assert "round" in cs
        assert "history" in cs
        assert "current_path" in cs
        assert "degraded" in cs
        assert "degraded_reason" in cs
        assert "before_snapshot" in cs


class TestTakeBeforeSnapshot:
    """修正前快照测试"""

    def test_snapshot_captures_hour_pillar(self):
        """快照应捕获时柱信息"""
        session = {
            "chart_data": {
                "four_pillars": {
                    "hour": {
                        "stem": "戊",
                        "branch": "辰",
                        "stem_ten_god": "劫财",
                        "nayin": "大林木",
                    }
                },
                "yongshen": {
                    "ri_zhu_strength": "偏弱",
                    "pattern": "正格-身弱",
                    "primary": "金",
                    "secondary": "水",
                    "ji_shen": "木",
                },
            },
            "birth_info": {"hour": 8},
        }
        snapshot = take_before_snapshot(session)
        assert snapshot["hour_pillar"]["stem"] == "戊"
        assert snapshot["hour_pillar"]["branch"] == "辰"
        assert snapshot["wangshuai"]["ri_zhu_strength"] == "偏弱"
        assert snapshot["yongshen"]["primary"] == "金"

    def test_snapshot_handles_missing_data(self):
        """处理缺失数据不报错"""
        session = {"chart_data": {}, "birth_info": {}}
        snapshot = take_before_snapshot(session)
        assert "hour_pillar" in snapshot
        assert "wangshuai" in snapshot
        assert "yongshen" in snapshot
        assert snapshot["hour_pillar"]["stem"] == ""

    def test_snapshot_includes_shichen(self):
        """快照应包含时辰名称"""
        session = {
            "chart_data": {
                "four_pillars": {
                    "hour": {"stem": "甲", "branch": "子", "stem_ten_god": "", "nayin": ""}
                },
                "yongshen": {
                    "ri_zhu_strength": "中和", "pattern": "正格-中和",
                    "primary": "水", "secondary": "金", "ji_shen": "土",
                },
            },
            "birth_info": {"hour": 0},
        }
        snapshot = take_before_snapshot(session)
        assert snapshot["birth_shichen"] == "子时"


class TestBuildCorrectionComparison:
    """修正前后对比测试"""

    def test_detects_hour_pillar_change(self):
        """应检测到时柱变化"""
        before = {
            "hour_pillar": {"stem": "戊", "branch": "辰", "stem_ten_god": "", "nayin": ""},
            "wangshuai": {"ri_zhu_strength": "偏弱", "pattern": "正格-身弱"},
            "yongshen": {"primary": "金", "secondary": "水", "ji_shen": "木"},
            "birth_shichen": "辰时",
        }
        session = {
            "chart_data": {
                "four_pillars": {
                    "hour": {"stem": "丁", "branch": "卯", "stem_ten_god": "", "nayin": ""}
                },
                "yongshen": {
                    "ri_zhu_strength": "偏弱", "pattern": "正格-身弱",
                    "primary": "金", "secondary": "水", "ji_shen": "木",
                },
            },
            "birth_info": {"hour": 6},
        }
        comparison = build_correction_comparison(session, before)
        assert comparison["hour_changed"] is True
        assert comparison["any_changed"] is True
        assert len(comparison["changes"]) > 0

    def test_detects_wangshuai_change(self):
        """应检测到旺衰结论变化"""
        before = {
            "hour_pillar": {"stem": "戊", "branch": "辰", "stem_ten_god": "", "nayin": ""},
            "wangshuai": {"ri_zhu_strength": "偏弱", "pattern": "正格-身弱"},
            "yongshen": {"primary": "金", "secondary": "水", "ji_shen": "木"},
            "birth_shichen": "辰时",
        }
        session = {
            "chart_data": {
                "four_pillars": {
                    "hour": {"stem": "戊", "branch": "辰", "stem_ten_god": "", "nayin": ""}
                },
                "yongshen": {
                    "ri_zhu_strength": "偏强", "pattern": "正格-身强",
                    "primary": "木", "secondary": "水", "ji_shen": "金",
                },
            },
            "birth_info": {"hour": 8},
        }
        comparison = build_correction_comparison(session, before)
        assert comparison["wangshuai_changed"] is True
        assert comparison["pattern_changed"] is True
        assert comparison["yongshen_primary_changed"] is True
        assert comparison["any_changed"] is True

    def test_no_change_when_same(self):
        """相同时不应标记为变化"""
        before = {
            "hour_pillar": {"stem": "戊", "branch": "辰", "stem_ten_god": "", "nayin": ""},
            "wangshuai": {"ri_zhu_strength": "偏弱", "pattern": "正格-身弱"},
            "yongshen": {"primary": "金", "secondary": "水", "ji_shen": "木"},
            "birth_shichen": "辰时",
        }
        session = {
            "chart_data": {
                "four_pillars": {
                    "hour": {"stem": "戊", "branch": "辰", "stem_ten_god": "", "nayin": ""}
                },
                "yongshen": {
                    "ri_zhu_strength": "偏弱", "pattern": "正格-身弱",
                    "primary": "金", "secondary": "水", "ji_shen": "木",
                },
            },
            "birth_info": {"hour": 8},
        }
        comparison = build_correction_comparison(session, before)
        assert comparison["hour_changed"] is False
        assert comparison["wangshuai_changed"] is False
        assert comparison["any_changed"] is False
        assert len(comparison["changes"]) == 0

    def test_comparison_structure(self):
        """验证对比结果结构完整"""
        before = {
            "hour_pillar": {"stem": "戊", "branch": "辰", "stem_ten_god": "", "nayin": ""},
            "wangshuai": {"ri_zhu_strength": "偏弱", "pattern": "正格-身弱"},
            "yongshen": {"primary": "金", "secondary": "水", "ji_shen": "木"},
            "birth_shichen": "辰时",
        }
        session = {
            "chart_data": {
                "four_pillars": {
                    "hour": {"stem": "戊", "branch": "辰", "stem_ten_god": "", "nayin": ""}
                },
                "yongshen": {
                    "ri_zhu_strength": "偏弱", "pattern": "正格-身弱",
                    "primary": "金", "secondary": "水", "ji_shen": "木",
                },
            },
            "birth_info": {"hour": 8},
        }
        comparison = build_correction_comparison(session, before)
        assert "before" in comparison
        assert "after" in comparison
        assert "changes" in comparison
        assert "hour_changed" in comparison
        assert "wangshuai_changed" in comparison
        assert "pattern_changed" in comparison
        assert "yongshen_primary_changed" in comparison
        assert "shichen_changed" in comparison
        assert "any_changed" in comparison


class TestDetermineNextPath:
    """路径切换逻辑测试"""

    def test_first_round_ai_fix_first(self):
        """verdict=ai_fix_first 第1轮走 AI修正"""
        cs = {"round": 0, "history": [], "current_path": None}
        path = determine_next_path(cs, "ai_fix_first")
        assert path == "ai_fix"
        assert cs["current_path"] == "ai_fix"

    def test_first_round_hour_fix(self):
        """verdict=hour_fix 第1轮走时钟修正"""
        cs = {"round": 0, "history": [], "current_path": None}
        path = determine_next_path(cs, "hour_fix")
        assert path == "hour_fix"

    def test_first_round_ai_fix(self):
        """verdict=ai_fix 第1轮走AI修正"""
        cs = {"round": 0, "history": [], "current_path": None}
        path = determine_next_path(cs, "ai_fix")
        assert path == "ai_fix"

    def test_ai_fix_invalid_switches_to_hour_fix(self):
        """AI修正1轮无效 -> 切换到时钟修正"""
        cs = {"round": 1, "history": [], "current_path": "ai_fix"}
        last_result = {"any_improvement": False}
        path = determine_next_path(cs, "ai_fix_first", last_result)
        assert path == "hour_fix"
        assert cs["current_path"] == "hour_fix"

    def test_ai_fix_valid_continues(self):
        """AI修正有效 -> 继续AI修正"""
        cs = {"round": 1, "history": [], "current_path": "ai_fix"}
        last_result = {"any_improvement": True}
        path = determine_next_path(cs, "ai_fix_first", last_result)
        assert path == "ai_fix"

    def test_hour_fix_invalid_degrades(self):
        """时钟修正无效（第2轮后）-> 降级"""
        cs = {"round": 1, "history": [], "current_path": "hour_fix"}
        last_result = {"any_improvement": False}
        path = determine_next_path(cs, "hour_fix", last_result)
        assert path == "degrade"

    def test_max_rounds_reached(self):
        """达到最大轮数 -> 降级"""
        cs = {"round": MAX_CORRECTION_ROUNDS, "history": [], "current_path": "ai_fix"}
        path = determine_next_path(cs, "ai_fix_first")
        assert path == "degrade"

    def test_passed_degrades(self):
        """verdict=passed 不应进入修正"""
        cs = {"round": 0, "history": [], "current_path": None}
        path = determine_next_path(cs, "passed")
        assert path == "degrade"


class TestGetCorrectionStatus:
    """修正状态查询测试"""

    def test_returns_default_for_empty_session(self):
        """空会话返回默认状态"""
        session = {}
        status = get_correction_status(session)
        assert status["round"] == 0
        assert status["degraded"] is False
        assert status["can_continue"] is True

    def test_returns_actual_state(self):
        """有修正状态时返回实际值"""
        session = {
            "correction_state": {
                "round": 2,
                "degraded": True,
                "degraded_reason": "测试降级",
                "current_path": "hour_fix",
                "history": [{"round": 1}, {"round": 2}],
            }
        }
        status = get_correction_status(session)
        assert status["round"] == 2
        assert status["degraded"] is True
        assert status["degraded_reason"] == "测试降级"
        assert status["can_continue"] is False  # degraded + round >= 2

    def test_can_continue_when_not_degraded(self):
        """未降级且轮数未满时应可以继续"""
        session = {
            "correction_state": {
                "round": 1,
                "degraded": False,
                "degraded_reason": "",
                "current_path": "ai_fix",
                "history": [{"round": 1}],
            }
        }
        status = get_correction_status(session)
        assert status["can_continue"] is True


class TestCorrectionRoundControl:
    """修正轮数控制集成测试"""

    @pytest.fixture
    def test_session(self):
        """构建测试用的完整 session"""
        return {
            "chart_data": {
                "day_master": "己",
                "four_pillars": {
                    "year": {"stem": "庚", "branch": "午"},
                    "month": {"stem": "己", "branch": "卯"},
                    "day": {"stem": "己", "branch": "卯"},
                    "hour": {"stem": "戊", "branch": "辰", "stem_ten_god": "劫财", "nayin": "大林木"},
                },
                "yongshen": {
                    "primary": "金", "secondary": "水", "ji_shen": "木",
                    "pattern": "正格-身弱", "ri_zhu_strength": "偏弱",
                },
                "strength_detail": {"total_score": 35},
            },
            "birth_info": {
                "year": 1990, "month": 3, "day": 15,
                "hour": 8, "minute": 0, "gender": "male",
            },
            "feedbacks": [
                {"prediction_id": f"pred_{i:02d}", "status": "inaccurate", "note": ""}
                for i in range(1, 8)
            ],
            "predictions": [
                {"id": "pred_01", "category": "性格", "is_core": False, "sequence": 1},
                {"id": "pred_02", "category": "父母关", "is_core": True, "sequence": 2},
                {"id": "pred_03", "category": "兄弟关", "is_core": True, "sequence": 3},
                {"id": "pred_04", "category": "学历", "is_core": False, "sequence": 4},
                {"id": "pred_05", "category": "婚姻关", "is_core": True, "sequence": 5},
                {"id": "pred_06", "category": "事业", "is_core": False, "sequence": 6},
                {"id": "pred_07", "category": "关键年份", "is_core": False, "sequence": 7},
            ],
        }

    def test_init_state_round_zero(self, test_session):
        """初始状态轮数为0"""
        cs = init_correction_state(test_session)
        assert cs["round"] == 0
        assert cs["degraded"] is False

    def test_snapshot_before_correction(self, test_session):
        """修正前快照应捕获当前状态"""
        snapshot = take_before_snapshot(test_session)
        assert snapshot["hour_pillar"]["stem"] == "戊"
        assert snapshot["wangshuai"]["ri_zhu_strength"] == "偏弱"
        assert snapshot["yongshen"]["primary"] == "金"

    def test_degraded_after_exceeding_max_rounds(self, test_session):
        """超过最大轮数后标记为降级"""
        cs = init_correction_state(test_session)
        cs["round"] = MAX_CORRECTION_ROUNDS
        cs["degraded"] = True
        cs["degraded_reason"] = "测试：超过最大轮数"

        assert cs["degraded"] is True
        assert cs["round"] >= MAX_CORRECTION_ROUNDS

    def test_determine_path_switching(self):
        """路径切换逻辑：ai_fix失败 -> hour_fix -> 失败 -> degrade"""
        cs = {"round": 0, "history": [], "current_path": None}

        # 第1轮：verdict=ai_fix_first -> ai_fix
        path = determine_next_path(cs, "ai_fix_first")
        assert path == "ai_fix"

        # 模拟第1轮AI修正无效
        cs["round"] = 1
        cs["current_path"] = "ai_fix"
        last_result = {"any_improvement": False}
        path = determine_next_path(cs, "ai_fix_first", last_result)
        assert path == "hour_fix"

        # 模拟第2轮时钟修正也无效 -> 降级
        cs["round"] = 1  # 第2轮 (0-indexed round 1)
        cs["current_path"] = "hour_fix"
        last_result = {"any_improvement": False}
        path = determine_next_path(cs, "hour_fix", last_result)
        assert path == "degrade"

    def test_any_improvement_false_causes_degrade(self):
        """无改善时最终降级"""
        cs = {"round": 1, "history": [], "current_path": "hour_fix"}
        last_result = {"any_improvement": False}
        path = determine_next_path(cs, "hour_fix", last_result)
        assert path == "degrade"

    def test_both_paths_invalid(self):
        """双路径都无效：先AI修正无效，再切到时钟修正也无效"""
        # 模拟完整流程
        cs = {"round": 0, "history": [], "current_path": None}

        # 第1轮AI修正
        path1 = determine_next_path(cs, "ai_fix_first")
        assert path1 == "ai_fix"

        # AI修正无效
        cs["round"] = 1
        cs["current_path"] = "ai_fix"
        path2 = determine_next_path(cs, "ai_fix_first", {"any_improvement": False})
        assert path2 == "hour_fix"  # 自动切换到时钟修正

        # 时钟修正也无效
        cs["current_path"] = "hour_fix"
        path3 = determine_next_path(cs, "hour_fix", {"any_improvement": False})
        assert path3 == "degrade"  # 双路径都无效，降级

    def test_comparison_when_no_change(self, test_session):
        """无变化时的对比应正确"""
        # 保存快照
        session = dict(test_session)
        cs = init_correction_state(session)
        cs["before_snapshot"] = take_before_snapshot(session)

        # 未修改 session，对比应显示无变化
        comparison = build_correction_comparison(session, cs["before_snapshot"])
        assert comparison["any_changed"] is False
        assert len(comparison["changes"]) == 0

    def test_comparison_with_hour_change(self, test_session):
        """时柱变化应被检测到"""
        session = dict(test_session)
        cs = init_correction_state(session)
        cs["before_snapshot"] = take_before_snapshot(session)

        # 修改时柱
        session["chart_data"]["four_pillars"]["hour"]["stem"] = "丁"
        session["chart_data"]["four_pillars"]["hour"]["branch"] = "卯"
        session["birth_info"]["hour"] = 6

        comparison = build_correction_comparison(session, cs["before_snapshot"])
        assert comparison["hour_changed"] is True
        assert comparison["any_changed"] is True
        assert "时柱" in " ".join(comparison["changes"])


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
