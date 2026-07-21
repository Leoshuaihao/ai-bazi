"""Tests for CorrectionTriggerConfig — 修正触发阈值量化"""

import sys
sys.path.insert(0, '/Users/lee/WorkSpace/WorkBuddy/ai-bazi')

from services.correction_v2 import CorrectionTriggerConfig, build_correction_state


class TestCorrectionTriggerConfig:
    """测试修正触发配置"""

    def setup_method(self):
        self.config = CorrectionTriggerConfig()

    # ============================================================
    # L0 测试
    # ============================================================

    def test_L0_trigger_true(self):
        """L0: inaccurate_rate=0.6 + core_pass=0 → trigger=True"""
        state = {
            "applied_levels": [],
            "iteration": 0,
            "inaccurate_rate": 0.6,
            "core_pass_count": 0,
        }
        result = self.config.should_trigger("L0", state)
        assert result["trigger"] is True
        assert "验盘修正" in result["reason"]

    def test_L0_trigger_false(self):
        """L0: inaccurate_rate=0.4 + core_pass=2 → trigger=False"""
        state = {
            "applied_levels": [],
            "iteration": 0,
            "inaccurate_rate": 0.4,
            "core_pass_count": 2,
        }
        result = self.config.should_trigger("L0", state)
        assert result["trigger"] is False

    def test_L0_trigger_false_low_inaccurate(self):
        """L0: inaccurate_rate=0.3 + core_pass=0 → trigger=False（inaccurate_rate不足）"""
        state = {
            "applied_levels": [],
            "iteration": 0,
            "inaccurate_rate": 0.3,
            "core_pass_count": 0,
        }
        result = self.config.should_trigger("L0", state)
        assert result["trigger"] is False

    # ============================================================
    # 不可逆原则测试
    # ============================================================

    def test_irreversible_already_applied_L1(self):
        """不可逆：applied=[0,1]，尝试L1 → trigger=False"""
        state = {
            "applied_levels": [0, 1],
            "iteration": 0,
            "yongshen_true_pass": False,
            "inaccurate_rate_yongshen_related": 0.35,
        }
        result = self.config.should_trigger("L1", state)
        assert result["trigger"] is False
        assert "不可逆原则" in result["reason"]

    def test_irreversible_already_applied_L0(self):
        """不可逆：applied=[0]，尝试L0 → trigger=False"""
        state = {
            "applied_levels": [0],
            "iteration": 0,
            "inaccurate_rate": 0.6,
            "core_pass_count": 0,
        }
        result = self.config.should_trigger("L0", state)
        assert result["trigger"] is False
        assert "不可逆原则" in result["reason"]

    def test_irreversible_can_proceed_to_next(self):
        """不可逆：applied=[0]，尝试L1（下一个层级）→ 应该可以触发"""
        state = {
            "applied_levels": [0],
            "iteration": 0,
            "yongshen_true_pass": False,
            "inaccurate_rate_yongshen_related": 0.35,
        }
        result = self.config.should_trigger("L1", state)
        # 不可逆原则不应该阻止 L1（因为L1 > max_applied=0）
        assert "不可逆原则" not in result.get("reason", "")
        assert result["trigger"] is True  # 条件都满足

    # ============================================================
    # 迭代上限测试
    # ============================================================

    def test_iteration_limit_exceeded(self):
        """迭代上限：iteration=3 → trigger=False + INDETERMINATE"""
        state = {
            "applied_levels": [],
            "iteration": 3,
            "inaccurate_rate": 0.6,
            "core_pass_count": 0,
        }
        result = self.config.should_trigger("L0", state)
        assert result["trigger"] is False
        assert result.get("indeterminate") is True
        assert "迭代上限" in result["reason"]

    def test_iteration_limit_not_exceeded(self):
        """迭代上限：iteration=2 → 可以继续"""
        state = {
            "applied_levels": [],
            "iteration": 2,
            "inaccurate_rate": 0.6,
            "core_pass_count": 0,
        }
        result = self.config.should_trigger("L0", state)
        assert result["trigger"] is True

    def test_iteration_limit_boundary(self):
        """迭代上限边界：iteration=3（恰好等于MAX_CORRECTION_ITERATIONS）→ INDETERMINATE"""
        state = {
            "applied_levels": [],
            "iteration": 3,
            "career_inaccurate": True,
            "day_master_extreme": True,
        }
        result = self.config.should_trigger("L3", state)
        assert result["trigger"] is False
        assert result.get("indeterminate") is True

    # ============================================================
    # L3 测试
    # ============================================================

    def test_L3_trigger_true(self):
        """L3: career_inaccurate=True + day_master_extreme=True → trigger=True"""
        state = {
            "applied_levels": [],
            "iteration": 0,
            "career_inaccurate": True,
            "day_master_extreme": True,
        }
        result = self.config.should_trigger("L3", state)
        assert result["trigger"] is True
        assert "格局切换" in result["reason"]

    def test_L3_trigger_false_partial(self):
        """L3: career_inaccurate=True + day_master_extreme=False → trigger=False"""
        state = {
            "applied_levels": [],
            "iteration": 0,
            "career_inaccurate": True,
            "day_master_extreme": False,
        }
        result = self.config.should_trigger("L3", state)
        assert result["trigger"] is False

    def test_L3_trigger_false_both(self):
        """L3: career_inaccurate=False + day_master_extreme=False → trigger=False"""
        state = {
            "applied_levels": [],
            "iteration": 0,
            "career_inaccurate": False,
            "day_master_extreme": False,
        }
        result = self.config.should_trigger("L3", state)
        assert result["trigger"] is False

    # ============================================================
    # L1 测试
    # ============================================================

    def test_L1_trigger_true(self):
        """L1: yongshen_true_pass=False + inaccurate_rate_yongshen_related=0.35 → trigger=True"""
        state = {
            "applied_levels": [],
            "iteration": 0,
            "yongshen_true_pass": False,
            "inaccurate_rate_yongshen_related": 0.35,
        }
        result = self.config.should_trigger("L1", state)
        assert result["trigger"] is True

    def test_L1_trigger_false_yongshen_pass(self):
        """L1: yongshen_true_pass=True + inaccurate_rate_yongshen_related=0.35 → trigger=False"""
        state = {
            "applied_levels": [],
            "iteration": 0,
            "yongshen_true_pass": True,
            "inaccurate_rate_yongshen_related": 0.35,
        }
        result = self.config.should_trigger("L1", state)
        assert result["trigger"] is False

    # ============================================================
    # L2 测试
    # ============================================================

    def test_L2_trigger_true(self):
        """L2: wangshen_related_inaccurate=True + dayun_xi_ji_mismatch_rate=0.6 → trigger=True"""
        state = {
            "applied_levels": [],
            "iteration": 0,
            "wangshen_related_inaccurate": True,
            "dayun_xi_ji_mismatch_rate": 0.6,
        }
        result = self.config.should_trigger("L2", state)
        assert result["trigger"] is True

    def test_L2_trigger_false(self):
        """L2: wangshen_related_inaccurate=False → trigger=False"""
        state = {
            "applied_levels": [],
            "iteration": 0,
            "wangshen_related_inaccurate": False,
            "dayun_xi_ji_mismatch_rate": 0.6,
        }
        result = self.config.should_trigger("L2", state)
        assert result["trigger"] is False

    # ============================================================
    # get_next_level 测试
    # ============================================================

    def test_get_next_level_empty(self):
        """get_next_level: 空 applied_levels → 0"""
        state = {"applied_levels": []}
        assert self.config.get_next_level(state) == 0

    def test_get_next_level_0(self):
        """get_next_level: applied=[0] → 1"""
        state = {"applied_levels": [0]}
        assert self.config.get_next_level(state) == 1

    def test_get_next_level_all_done(self):
        """get_next_level: applied=[0,1,2,3,4,5] → -1"""
        state = {"applied_levels": [0, 1, 2, 3, 4, 5]}
        assert self.config.get_next_level(state) == -1

    def test_get_next_level_partial(self):
        """get_next_level: applied=[0,1,2] → 3"""
        state = {"applied_levels": [0, 1, 2]}
        assert self.config.get_next_level(state) == 3

    # ============================================================
    # check_iteration_limit 测试
    # ============================================================

    def test_check_iteration_limit_ok(self):
        """check_iteration_limit: iteration=0 → OK"""
        state = {"iteration": 0}
        result = self.config.check_iteration_limit(state)
        assert result["can_continue"] is True
        assert result["remaining"] == 3
        assert result["status"] == "OK"

    def test_check_iteration_limit_indeterminate(self):
        """check_iteration_limit: iteration=3 → INDETERMINATE"""
        state = {"iteration": 3}
        result = self.config.check_iteration_limit(state)
        assert result["can_continue"] is False
        assert result["status"] == "INDETERMINATE"

    def test_check_iteration_limit_remaining(self):
        """check_iteration_limit: iteration=1 → remaining=2"""
        state = {"iteration": 1}
        result = self.config.check_iteration_limit(state)
        assert result["remaining"] == 2

    # ============================================================
    # L4/L5 测试
    # ============================================================

    def test_L4_trigger_true(self):
        """L4: overall_contradiction=True + one_element_dominance=True → trigger=True"""
        state = {
            "applied_levels": [],
            "iteration": 0,
            "overall_contradiction": True,
            "one_element_dominance": True,
        }
        result = self.config.should_trigger("L4", state)
        assert result["trigger"] is True

    def test_L5_trigger_true(self):
        """L5: dayun_contradiction=True + original_confirmed=True → trigger=True"""
        state = {
            "applied_levels": [],
            "iteration": 0,
            "dayun_contradiction": True,
            "original_confirmed": True,
        }
        result = self.config.should_trigger("L5", state)
        assert result["trigger"] is True

    # ============================================================
    # 综合场景：不可逆+迭代
    # ============================================================

    def test_combined_irreversible_and_iteration(self):
        """综合：applied=[0,1,2]，iteration=2 → L3应触发，L0/L1/L2应不可逆阻止"""
        state = {
            "applied_levels": [0, 1, 2],
            "iteration": 2,
            "inaccurate_rate": 0.6,
            "core_pass_count": 0,
            "career_inaccurate": True,
            "day_master_extreme": True,
        }
        # L0/L1/L2 被不可逆阻止
        assert self.config.should_trigger("L0", state)["trigger"] is False
        assert self.config.should_trigger("L1", state)["trigger"] is False
        assert self.config.should_trigger("L2", state)["trigger"] is False
        # L3 应该可以触发
        assert self.config.should_trigger("L3", state)["trigger"] is True

    def test_unknown_level(self):
        """未知层级返回 False"""
        state = {
            "applied_levels": [],
            "iteration": 0,
        }
        result = self.config.should_trigger("L99", state)
        assert result["trigger"] is False
        assert "未知层级" in result["reason"]


class TestBuildCorrectionState:
    """测试 build_correction_state() 函数"""

    def test_empty_inputs(self):
        """空输入返回默认 state"""
        state = build_correction_state()
        assert state["applied_levels"] == []
        assert state["iteration"] == 0
        assert state["inaccurate_rate"] == 0.0

    def test_from_hexagram_report(self):
        """从六维验证报告构建 state"""
        report = {
            "scores": [
                {"dimension": "旺衰验证", "score": 8},
                {"dimension": "格局喜忌验证", "score": 7},
                {"dimension": "用神验证", "score": 9},
                {"dimension": "大运走向验证", "score": 2},
                {"dimension": "六亲验证", "score": 5},
                {"dimension": "性格验证", "score": 6},
            ],
            "core_triangle_pass": True,
        }
        state = build_correction_state(hexagram_report=report)
        # 核心三角通过数
        assert state["core_pass_count"] == 3
        # 用神验证通过 → yongshen_true_pass=True
        assert state["yongshen_true_pass"] is True
        # 大运走向低分 → dayun_contradiction=True
        assert state["dayun_contradiction"] is True

    def test_from_hexagram_with_core_triangle_fail(self):
        """核心三角失败 → overall_contradiction=True"""
        report = {
            "scores": [
                {"dimension": "旺衰验证", "score": 3},
                {"dimension": "格局喜忌验证", "score": 2},
                {"dimension": "用神验证", "score": 4},
            ],
            "core_triangle_pass": False,
        }
        state = build_correction_state(hexagram_report=report)
        assert state["overall_contradiction"] is True
        assert state["core_pass_count"] == 0

    def test_from_uncertainty_report(self):
        """从不确定参数报告构建 state"""
        report = {
            "items": [
                {"dimension": "pattern", "risk_score": 0.5},
                {"dimension": "congge", "risk_score": 0.6},
                {"dimension": "wangshuai", "risk_score": 0.6},
            ]
        }
        state = build_correction_state(uncertainty_report=report)
        assert state["career_inaccurate"] is True    # pattern risk > 0.4
        assert state["day_master_extreme"] is True   # congge risk > 0.4
        assert state["one_element_dominance"] is True  # wangshuai risk > 0.5

    def test_from_feedback_stats(self):
        """从用户反馈统计构建 state"""
        stats = {"inaccurate_rate": 0.55, "original_confirmed": True}
        state = build_correction_state(feedback_stats=stats)
        assert state["inaccurate_rate"] == 0.55
        assert state["original_confirmed"] is True

    def test_combined_all_sources(self):
        """三份报告合并构建"""
        hexagram = {
            "scores": [
                {"dimension": "旺衰验证", "score": 2},
                {"dimension": "格局喜忌验证", "score": 3},
                {"dimension": "用神验证", "score": 2},
                {"dimension": "大运走向验证", "score": 1},
            ],
            "core_triangle_pass": False,
        }
        uncertainty = {
            "items": [
                {"dimension": "pattern", "risk_score": 0.7},
                {"dimension": "congge", "risk_score": 0.5},
                {"dimension": "wangshuai", "risk_score": 0.7},
            ]
        }
        feedback = {"inaccurate_rate": 0.60, "original_confirmed": True}

        state = build_correction_state(
            hexagram_report=hexagram,
            uncertainty_report=uncertainty,
            feedback_stats=feedback,
        )

        assert state["overall_contradiction"] is True
        assert state["career_inaccurate"] is True
        assert state["day_master_extreme"] is True
        assert state["one_element_dominance"] is True
        assert state["inaccurate_rate"] == 0.60
        assert state["original_confirmed"] is True


class TestTriggerConfigStructure:
    """测试 TRIGGER_CONFIG 结构完整性"""

    def test_all_levels_exist(self):
        """验证 L0-L5 全部存在"""
        config = CorrectionTriggerConfig()
        for level in ["L0", "L1", "L2", "L3", "L4", "L5"]:
            assert level in config.TRIGGER_CONFIG, f"缺少 {level}"

    def test_all_levels_have_rules(self):
        """验证每级至少有2条规则"""
        config = CorrectionTriggerConfig()
        for level, cfg in config.TRIGGER_CONFIG.items():
            assert len(cfg["rules"]) >= 2, f"{level} 规则不足2条"

    def test_all_levels_have_name(self):
        """验证每级有名称"""
        config = CorrectionTriggerConfig()
        for level, cfg in config.TRIGGER_CONFIG.items():
            assert cfg["name"], f"{level} 名称为空"
            assert cfg["description"], f"{level} 描述为空"

    def test_max_iteration_value(self):
        """验证 MAX_CORRECTION_ITERATIONS = 3"""
        config = CorrectionTriggerConfig()
        assert config.MAX_CORRECTION_ITERATIONS == 3
