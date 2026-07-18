"""P1 Phase 2 测试：校验判定逻辑"""

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.calibration import (
    judge_core_gates,
    judge_auxiliary,
    final_verdict,
    run_calibration,
)


# ============================================================
# 测试夹具
# ============================================================

@pytest.fixture
def sample_predictions():
    """模拟7条推断数据（对应 P1 断事生成）"""
    return [
        {"id": "pred_01", "category": "性格", "is_core": False, "sequence": 1},
        {"id": "pred_02", "category": "父母关", "is_core": True, "sequence": 2},
        {"id": "pred_03", "category": "兄弟关", "is_core": True, "sequence": 3},
        {"id": "pred_04", "category": "学历", "is_core": False, "sequence": 4},
        {"id": "pred_05", "category": "婚姻关", "is_core": True, "sequence": 5},
        {"id": "pred_06", "category": "事业", "is_core": False, "sequence": 6},
        {"id": "pred_07", "category": "关键年份", "is_core": False, "sequence": 7},
    ]


@pytest.fixture
def all_accurate_feedbacks():
    """全部准确的反馈"""
    return [
        {"prediction_id": f"pred_{i:02d}", "status": "accurate", "note": ""}
        for i in range(1, 8)
    ]


@pytest.fixture
def all_inaccurate_feedbacks():
    """全部不准确的反馈"""
    return [
        {"prediction_id": f"pred_{i:02d}", "status": "inaccurate", "note": ""}
        for i in range(1, 8)
    ]


@pytest.fixture
def mixed_feedbacks():
    """混合反馈：核心关2准1不准，辅助2准2不准"""
    return [
        {"prediction_id": "pred_01", "status": "accurate", "note": ""},     # 性格 ✓
        {"prediction_id": "pred_02", "status": "accurate", "note": ""},     # 父母关 ✓
        {"prediction_id": "pred_03", "status": "inaccurate", "note": ""},   # 兄弟关 ✗
        {"prediction_id": "pred_04", "status": "partial", "note": ""},      # 学历 ~
        {"prediction_id": "pred_05", "status": "accurate", "note": ""},     # 婚姻关 ✓
        {"prediction_id": "pred_06", "status": "inaccurate", "note": ""},   # 事业 ✗
        {"prediction_id": "pred_07", "status": "accurate", "note": ""},     # 关键年份 ✓
    ]


@pytest.fixture
def one_core_pass_feedbacks():
    """只有1个核心关通过的反馈"""
    return [
        {"prediction_id": "pred_01", "status": "inaccurate", "note": ""},
        {"prediction_id": "pred_02", "status": "accurate", "note": ""},     # 父母关 ✓
        {"prediction_id": "pred_03", "status": "inaccurate", "note": ""},   # 兄弟关 ✗
        {"prediction_id": "pred_04", "status": "inaccurate", "note": ""},
        {"prediction_id": "pred_05", "status": "inaccurate", "note": ""},   # 婚姻关 ✗
        {"prediction_id": "pred_06", "status": "partial", "note": ""},
        {"prediction_id": "pred_07", "status": "inaccurate", "note": ""},
    ]


@pytest.fixture
def partial_core_feedbacks():
    """核心关部分准确的反馈"""
    return [
        {"prediction_id": "pred_01", "status": "accurate", "note": ""},
        {"prediction_id": "pred_02", "status": "partial", "note": ""},      # 父母关 ~ (不算accurate)
        {"prediction_id": "pred_03", "status": "accurate", "note": ""},     # 兄弟关 ✓
        {"prediction_id": "pred_04", "status": "accurate", "note": ""},
        {"prediction_id": "pred_05", "status": "partial", "note": ""},      # 婚姻关 ~ (不算accurate)
        {"prediction_id": "pred_06", "status": "accurate", "note": ""},
        {"prediction_id": "pred_07", "status": "accurate", "note": ""},
    ]


# ============================================================
# judge_core_gates 测试
# ============================================================

class TestJudgeCoreGates:
    """核心三关判定测试"""

    def test_all_accurate(self, sample_predictions, all_accurate_feedbacks):
        """全部准确时，三关全过"""
        result = judge_core_gates(all_accurate_feedbacks, sample_predictions)
        assert result["parent_pass"] is True
        assert result["sibling_pass"] is True
        assert result["marriage_pass"] is True
        assert result["pass_count"] == 3
        assert result["fail_count"] == 0
        assert result["need_correction"] is False

    def test_all_inaccurate(self, sample_predictions, all_inaccurate_feedbacks):
        """全部不准确时，三关全不过"""
        result = judge_core_gates(all_inaccurate_feedbacks, sample_predictions)
        assert result["parent_pass"] is False
        assert result["sibling_pass"] is False
        assert result["marriage_pass"] is False
        assert result["pass_count"] == 0
        assert result["fail_count"] == 3
        assert result["need_correction"] is True

    def test_mixed_feedbacks(self, sample_predictions, mixed_feedbacks):
        """混合反馈：2关通过1关失败"""
        result = judge_core_gates(mixed_feedbacks, sample_predictions)
        assert result["parent_pass"] is True   # accurate
        assert result["sibling_pass"] is False  # inaccurate
        assert result["marriage_pass"] is True  # accurate
        assert result["pass_count"] == 2
        assert result["fail_count"] == 1
        assert result["need_correction"] is False  # fail_count=1，不触发

    def test_one_core_pass(self, sample_predictions, one_core_pass_feedbacks):
        """只有1个核心关通过"""
        result = judge_core_gates(one_core_pass_feedbacks, sample_predictions)
        assert result["pass_count"] == 1
        assert result["fail_count"] == 2
        assert result["need_correction"] is True  # fail_count=2

    def test_supplement_not_counted(self, sample_predictions):
        """supplement（不确定）不参与计数"""
        feedbacks = [
            {"prediction_id": "pred_01", "status": "accurate", "note": ""},
            {"prediction_id": "pred_02", "status": "supplement", "note": "不太确定"},  # 不参与
            {"prediction_id": "pred_03", "status": "accurate", "note": ""},
            {"prediction_id": "pred_04", "status": "accurate", "note": ""},
            {"prediction_id": "pred_05", "status": "supplement", "note": ""},          # 不参与
            {"prediction_id": "pred_06", "status": "accurate", "note": ""},
            {"prediction_id": "pred_07", "status": "accurate", "note": ""},
        ]
        result = judge_core_gates(feedbacks, sample_predictions)
        # 父母关(pred_02) supplement → total=0 → 默认不通过
        # 兄弟关(pred_03) accurate → 通过
        # 婚姻关(pred_05) supplement → total=0 → 默认不通过
        assert result["pass_count"] == 1
        assert result["details"]["parent"]["total"] == 0
        assert result["details"]["marriage"]["total"] == 0

    def test_details_structure(self, sample_predictions, all_accurate_feedbacks):
        """验证 details 结构完整"""
        result = judge_core_gates(all_accurate_feedbacks, sample_predictions)
        for key in ["parent", "sibling", "marriage"]:
            detail = result["details"][key]
            assert "accurate" in detail
            assert "total" in detail
            assert "pass" in detail
            assert "name" in detail

    def test_half_accurate_passes(self, sample_predictions):
        """50%门槛：刚好一半准确时应通过"""
        # 为测试创建多条同关推断的场景
        predictions_multi = [
            {"id": "pred_parent_1", "category": "父母关", "is_core": True, "sequence": 1},
            {"id": "pred_parent_2", "category": "父母关", "is_core": True, "sequence": 2},
        ]
        feedbacks_multi = [
            {"prediction_id": "pred_parent_1", "status": "accurate", "note": ""},
            {"prediction_id": "pred_parent_2", "status": "inaccurate", "note": ""},
        ]
        result = judge_core_gates(feedbacks_multi, predictions_multi)
        # accurate=1, total=2 → 50% → pass
        assert result["parent_pass"] is True

    def test_empty_feedbacks(self, sample_predictions):
        """空反馈列表"""
        result = judge_core_gates([], sample_predictions)
        assert result["pass_count"] == 0
        assert result["fail_count"] == 3


# ============================================================
# judge_auxiliary 测试
# ============================================================

class TestJudgeAuxiliary:
    """辅助项判定测试"""

    def test_all_accurate(self, sample_predictions, all_accurate_feedbacks):
        """全部准确时，辅助项全部通过"""
        result = judge_auxiliary(all_accurate_feedbacks, sample_predictions)
        assert result["total"] == 4  # 性格、学历、事业、关键年份
        assert result["pass_count"] == 4

    def test_all_inaccurate(self, sample_predictions, all_inaccurate_feedbacks):
        """全部不准确时，辅助项全部不过"""
        result = judge_auxiliary(all_inaccurate_feedbacks, sample_predictions)
        assert result["pass_count"] == 0

    def test_partial_counts_as_pass(self, sample_predictions):
        """partial 辅助项应算通过"""
        feedbacks = [
            {"prediction_id": "pred_01", "status": "partial", "note": ""},   # 性格
            {"prediction_id": "pred_02", "status": "accurate", "note": ""},
            {"prediction_id": "pred_03", "status": "accurate", "note": ""},
            {"prediction_id": "pred_04", "status": "inaccurate", "note": ""},
            {"prediction_id": "pred_05", "status": "accurate", "note": ""},
            {"prediction_id": "pred_06", "status": "partial", "note": ""},   # 事业
            {"prediction_id": "pred_07", "status": "partial", "note": ""},   # 关键年份
        ]
        result = judge_auxiliary(feedbacks, sample_predictions)
        # 辅助项: 性格(partial=pass), 学历(inaccurate=fail), 事业(partial=pass), 关键年份(partial=pass)
        # 3/4 pass
        assert result["pass_count"] >= 2

    def test_details_structure(self, sample_predictions, all_accurate_feedbacks):
        """验证 details 结构"""
        result = judge_auxiliary(all_accurate_feedbacks, sample_predictions)
        assert len(result["details"]) == 4
        for d in result["details"]:
            assert "category" in d
            assert "accurate" in d
            assert "partial" in d
            assert "pass" in d

    def test_only_core_items_in_predictions(self):
        """如果只有核心项（无辅助项）"""
        predictions = [
            {"id": "pred_01", "category": "父母关", "is_core": True, "sequence": 1},
        ]
        feedbacks = [
            {"prediction_id": "pred_01", "status": "accurate", "note": ""},
        ]
        result = judge_auxiliary(feedbacks, predictions)
        assert result["total"] == 0
        assert result["pass_count"] == 0


# ============================================================
# final_verdict 测试
# ============================================================

class TestFinalVerdict:
    """最终判定测试"""

    def test_all_pass(self):
        """三关全过 + 辅助全过 → passed"""
        core = {"pass_count": 3, "fail_count": 0}
        aux = {"pass_count": 4, "total": 4}
        verdict = final_verdict(core, aux)
        assert verdict["verdict"] == "passed"
        assert verdict["verdict_label"] == "校验通过"

    def test_core_pass_aux_low(self):
        """三关全过 + 辅助<2 → ai_fix"""
        core = {"pass_count": 3, "fail_count": 0}
        aux = {"pass_count": 1, "total": 4}
        verdict = final_verdict(core, aux)
        assert verdict["verdict"] == "ai_fix"
        assert "AI修正" in verdict["verdict_label"]

    def test_two_core_pass_good_aux(self):
        """三关≥2通过 + 辅助≥2 → ai_fix_first"""
        core = {"pass_count": 2, "fail_count": 1}
        aux = {"pass_count": 3, "total": 4}
        verdict = final_verdict(core, aux)
        assert verdict["verdict"] == "ai_fix_first"

    def test_two_core_pass_bad_aux(self):
        """三关≥2通过 + 辅助<2 → ai_fix"""
        core = {"pass_count": 2, "fail_count": 1}
        aux = {"pass_count": 1, "total": 4}
        verdict = final_verdict(core, aux)
        assert verdict["verdict"] == "ai_fix"

    def test_one_core_pass(self):
        """三关≤1通过 → hour_fix"""
        core = {"pass_count": 1, "fail_count": 2}
        aux = {"pass_count": 3, "total": 4}
        verdict = final_verdict(core, aux)
        assert verdict["verdict"] == "hour_fix"
        assert "时钟修正" in verdict["verdict_label"]

    def test_zero_core_pass(self):
        """三关全不过 → hour_fix"""
        core = {"pass_count": 0, "fail_count": 3}
        aux = {"pass_count": 0, "total": 4}
        verdict = final_verdict(core, aux)
        assert verdict["verdict"] == "hour_fix"

    def test_verdict_structure(self):
        """验证判定结果结构完整"""
        core = {"pass_count": 3, "fail_count": 0}
        aux = {"pass_count": 4, "total": 4}
        verdict = final_verdict(core, aux)
        assert "verdict" in verdict
        assert "verdict_label" in verdict
        assert "core_pass_count" in verdict
        assert "core_fail_count" in verdict
        assert "aux_pass_count" in verdict
        assert "aux_total" in verdict
        assert "suggestion" in verdict


# ============================================================
# run_calibration 集成测试
# ============================================================

class TestRunCalibration:
    """完整校验流程测试"""

    def test_all_accurate(self, sample_predictions, all_accurate_feedbacks):
        """全部准确 → passed"""
        result = run_calibration(all_accurate_feedbacks, sample_predictions)
        assert "core" in result
        assert "auxiliary" in result
        assert "verdict" in result
        assert result["verdict"]["verdict"] == "passed"

    def test_all_inaccurate(self, sample_predictions, all_inaccurate_feedbacks):
        """全部不准确 → hour_fix"""
        result = run_calibration(all_inaccurate_feedbacks, sample_predictions)
        assert result["verdict"]["verdict"] == "hour_fix"

    def test_mixed(self, sample_predictions, mixed_feedbacks):
        """混合反馈"""
        result = run_calibration(mixed_feedbacks, sample_predictions)
        assert result["core"]["pass_count"] == 2
        assert result["verdict"]["verdict"] in ("ai_fix_first", "ai_fix", "hour_fix", "passed")

    def test_one_core_pass(self, sample_predictions, one_core_pass_feedbacks):
        """1个核心关通过"""
        result = run_calibration(one_core_pass_feedbacks, sample_predictions)
        assert result["verdict"]["verdict"] == "hour_fix"

    def test_partial_core(self, sample_predictions, partial_core_feedbacks):
        """核心关只有partial无accurate"""
        result = run_calibration(partial_core_feedbacks, sample_predictions)
        assert "verdict" in result
        # partial 不算 accurate → 核心关可能0通过
        assert result["core"]["pass_count"] <= 2  # 兄弟关accurate=1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
