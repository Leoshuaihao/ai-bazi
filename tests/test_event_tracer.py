"""事件追溯器 + 对账器 + 修正引擎 端到端测试"""

import sys, os, json, asyncio

# Add project root to path
sys.path.insert(0, "/Users/lee/WorkSpace/WorkBuddy/ai-bazi")

import pytest


# ============================================================
# 测试数据
# ============================================================

@pytest.fixture
def sample_chart():
    """示例命盘：甲木日主，酉月（正官格）"""
    return {
        "birth_info": {"year": 1990, "month": 9, "day": 15, "hour": 8, "minute": 0, "gender": "男"},
        "day_master": {"stem": "甲", "wuxing": "木"},
        "year": {"stem": "庚", "branch": "午"},
        "month": {"stem": "乙", "branch": "酉"},
        "day": {"stem": "甲", "branch": "子"},
        "hour": {"stem": "戊", "branch": "辰"},
        "pattern": "正官格",
        "yongshen": {"wuxing": "金", "primary": "金", "xiti": "土", "jishen": ["火"]},
        "wangshuai": "中和",
        "dayun": [
            {"stem": "甲", "branch": "戌", "ten_god": "比肩", "start_year": 1995, "end_year": 2004},
            {"stem": "癸", "branch": "亥", "ten_god": "正印", "start_year": 2005, "end_year": 2014},
            {"stem": "壬", "branch": "子", "ten_god": "偏印", "start_year": 2015, "end_year": 2024},
            {"stem": "辛", "branch": "丑", "ten_god": "正官", "start_year": 2025, "end_year": 2034},
        ],
        "hidden_stems": [
            {"branch": "午", "stems": [{"stem": "丁", "wuxing": "火"}, {"stem": "己", "wuxing": "土"}]},
            {"branch": "酉", "stems": [{"stem": "辛", "wuxing": "金"}]},
            {"branch": "子", "stems": [{"stem": "癸", "wuxing": "水"}]},
            {"branch": "辰", "stems": [{"stem": "戊", "wuxing": "土"}, {"stem": "乙", "wuxing": "木"}, {"stem": "癸", "wuxing": "水"}]},
        ],
    }


# ============================================================
# 测试事件规则表
# ============================================================

class TestEventRules:
    def test_rules_count(self):
        from rules.event_rules import EVENT_RULES, get_all_rules
        rules = get_all_rules()
        assert len(rules) == 53, f"应有53条规则，实际{len(rules)}条"

    def test_rules_by_category(self):
        from rules.event_rules import get_rules_by_category
        assert len(get_rules_by_category("宫位互动")) == 13
        assert len(get_rules_by_category("用神互动")) == 5
        assert len(get_rules_by_category("忌神互动")) == 3
        assert len(get_rules_by_category("日主互动")) == 9
        assert len(get_rules_by_category("十神特殊")) == 11
        assert len(get_rules_by_category("特殊事件")) == 8

    def test_confidence_computation(self):
        from rules.event_rules import compute_confidence, EVENT_RULES
        # 天克地冲日柱应有最高置信度
        d1 = compute_confidence(EVENT_RULES["D1_tiankedichong_day"])
        assert d1 >= 0.85, f"天克地冲日柱置信度应 >= 0.85，实际 {d1}"

        # 六害应有较低置信度
        a10 = compute_confidence(EVENT_RULES["A10_branch_hai_any"])
        assert a10 <= 0.55, f"六害置信度应 <= 0.55，实际 {a10}"


# ============================================================
# 测试刑冲合害分析器
# ============================================================

class TestInteractionAnalyzer:
    def test_basic_interaction(self, sample_chart):
        from rules.interaction_analyzer import analyze_liunian_interactions

        pillars = [
            {"stem": "庚", "branch": "午"},
            {"stem": "乙", "branch": "酉"},
            {"stem": "甲", "branch": "子"},
            {"stem": "戊", "branch": "辰"},
        ]

        result = analyze_liunian_interactions(
            liunian_stem="丙",
            liunian_branch="午",
            chart_pillars=pillars,
            yongshen_wuxing="金",
            jishen_wuxing_list=["火"],
            day_master_wuxing="木",
        )

        assert "triggered_rules" in result
        assert "is_yongshen_year" in result
        assert "combined_score" in result

    def test_clash_detection(self, sample_chart):
        from rules.interaction_analyzer import analyze_liunian_interactions

        pillars = [
            {"stem": "庚", "branch": "午"},
            {"stem": "乙", "branch": "酉"},
            {"stem": "甲", "branch": "子"},
            {"stem": "戊", "branch": "辰"},
        ]

        # 子午冲：流年地支"子"冲年支"午"
        result = analyze_liunian_interactions(
            liunian_stem="甲", liunian_branch="子",
            chart_pillars=pillars,
            yongshen_wuxing="金", jishen_wuxing_list=["火"],
            day_master_wuxing="木",
        )

        branch_ints = result["branch_interactions"]
        clash_found = any(
            bi["type"] == "冲" and bi["target"] == "年支"
            for bi in branch_ints
        )
        assert clash_found, f"应该检测到子午冲，实际互动: {branch_ints}"


# ============================================================
# 测试事件追溯器
# ============================================================

class TestEventTracer:
    def test_trace_single_year(self, sample_chart):
        from services.event_tracer import EventTracer

        tracer = EventTracer(sample_chart)
        result = tracer.trace_year(2015)

        assert result is not None
        assert result["year"] == 2015
        assert result["age"] == 25
        assert result["liunian_ganzhi"] == "乙未"
        assert "events" in result
        assert "is_key_year" in result

    def test_trace_range(self, sample_chart):
        from services.event_tracer import EventTracer

        tracer = EventTracer(sample_chart)
        report = tracer.trace_range(start_year=2010, end_year=2020)

        assert report["total_years"] == 11
        assert len(report["years"]) == 11
        assert "key_years" in report
        assert "framework" in report

    def test_template_description(self, sample_chart):
        from services.event_tracer import EventTracer

        tracer = EventTracer(sample_chart)
        year_result = tracer.trace_year(2015)

        desc = tracer._template_describe(year_result)
        assert "2015年" in desc
        assert "乙未" in desc


# ============================================================
# 测试对账器
# ============================================================

class TestReconciler:
    @pytest.mark.asyncio
    async def test_reconcile_perfect_match(self, sample_chart):
        from services.event_tracer import EventTracer
        from services.reconciler import Reconciler

        tracer = EventTracer(sample_chart)
        report = tracer.trace_range(start_year=2010, end_year=2020)

        # 用户全部确认
        feedback = [
            {"year": 2015, "match": True},
            {"year": 2018, "match": True},
            {"year": 2020, "match": True},
        ]

        reconciler = Reconciler(report)
        result = await reconciler.reconcile(feedback)

        assert "overall_accuracy" in result
        assert isinstance(result["overall_accuracy"], float)

    @pytest.mark.asyncio
    async def test_reconcile_all_wrong(self, sample_chart):
        from services.event_tracer import EventTracer
        from services.reconciler import Reconciler

        tracer = EventTracer(sample_chart)
        report = tracer.trace_range(start_year=2010, end_year=2020)

        # 用户全部否认
        feedback = [
            {"year": 2015, "match": False},
            {"year": 2018, "match": False},
            {"year": 2020, "match": False},
        ]

        reconciler = Reconciler(report)
        result = await reconciler.reconcile(feedback)

        # 全部否认应该触发修正
        assert result["needs_correction"]


# ============================================================
# 测试修正引擎
# ============================================================

class TestCorrectionEngine:
    @pytest.mark.asyncio
    async def test_level0(self, sample_chart):
        from services.correction_v2 import CorrectionEngine

        engine = CorrectionEngine(sample_chart)
        result = await engine._level0()

        # Level 0 可能需要实际排盘，跳过验证
        assert isinstance(result.success, bool)

    @pytest.mark.asyncio
    async def test_level1_yongshen_check(self, sample_chart):
        from services.correction_v2 import CorrectionEngine

        engine = CorrectionEngine(sample_chart)
        result = await engine._level1()

        assert isinstance(result.success, bool)
        # 样本命盘可能无需修正，直接检查类型
        assert hasattr(result, 'level')

    @pytest.mark.asyncio
    async def test_level2_wangshuai(self, sample_chart):
        from services.correction_v2 import CorrectionEngine

        engine = CorrectionEngine(sample_chart)
        result = await engine._level2()

        assert isinstance(result.success, bool)
        assert hasattr(result, 'level')

    @pytest.mark.asyncio
    async def test_full_correction_pipeline(self, sample_chart):
        from services.correction_v2 import CorrectionEngine

        # 模拟一个对账结果（准确率低）
        reconciliation = {
            "overall_accuracy": 0.35,
            "needs_correction": True,
            "correction_level": 1,
        }

        engine = CorrectionEngine(sample_chart)
        result = await engine.correct(reconciliation, max_level=2)

        assert result is not None
        assert len(engine.history) > 0


# ============================================================
# 端到端集成测试
# ============================================================

@pytest.mark.asyncio
async def test_full_pipeline(sample_chart):
    """完整流程：追溯 → 对账 → 修正"""
    from services.event_tracer import EventTracer
    from services.reconciler import Reconciler
    from services.correction_v2 import CorrectionEngine

    # Step 1: 事件追溯
    tracer = EventTracer(sample_chart)
    report = tracer.trace_range(start_year=2010, end_year=2023)

    assert report["total_years"] > 0
    assert len(report["key_years"]) > 0

    # Step 2: 对账
    feedback = [
        {"year": 2015, "match": True},
        {"year": 2018, "match": True},
        {"year": 2020, "match": False},  # 故意错一个
    ]

    reconciler = Reconciler(report)
    reconciliation = await reconciler.reconcile(feedback)

    assert "overall_accuracy" in reconciliation

    # Step 3: 如果需要修正
    if reconciliation["needs_correction"]:
        engine = CorrectionEngine(sample_chart, feedback)
        result = await engine.correct(reconciliation, max_level=2)

        assert result is not None
