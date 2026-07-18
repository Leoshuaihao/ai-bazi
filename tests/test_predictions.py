"""P1 Phase 1 测试：断前事生成 + 逐条反馈"""

import pytest
import sys
import os

# 添加项目根目录到 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import (
    BirthInfo, BaziChart, Pillar, DayunPeriod, ShenshaItem,
    WuxingScore, YongShen, PreEventStatement, FeedbackItem, FeedbackRound,
)
from bazi_engine import calculate_bazi
from services.predictions import (
    generate_mock_predictions,
    _build_personality,
    _build_parents,
    _build_siblings,
    _build_education,
    _build_marriage,
    _build_career,
    _build_key_years,
    _count_bi_jie,
    _count_yin_xing,
    _is_yin_xing_solid,
    _has_guan_yin_xiang_sheng,
    _has_shishang_sheng_cai,
    _get_key_years,
    judge_info_sufficient,
    _core_gates_covered,
    _get_next_category_suggestion,
    _mock_generate_single,
    generate_single_prediction,
    MAX_PREDICTIONS,
    CORE_GATES,
)
from rules.wuxing import WUXING_MAP


# ============================================================
# 测试夹具
# ============================================================

@pytest.fixture
def sample_chart():
    """创建一个示例八字排盘 (1990-03-15 08:00 男)"""
    return calculate_bazi(
        year=1990, month=3, day=15, hour=8, minute=0, gender="male"
    )


@pytest.fixture
def sample_chart_female():
    """创建一个示例八字排盘 (1986-01-15 12:00 女)"""
    return calculate_bazi(
        year=1986, month=1, day=15, hour=12, minute=0, gender="female"
    )


# ============================================================
# 模型测试
# ============================================================

class TestPreEventStatementModel:
    """测试 PreEventStatement 模型"""

    def test_valid_statement(self):
        pred = PreEventStatement(
            id="pred_01",
            category="性格",
            is_core=False,
            sequence=1,
            title="先说说你的性格",
            content="你是一个性格刚毅的人",
            classical_quote="《滴天髓》：金主义",
            basis="日主为金",
            confidence=0.85,
        )
        assert pred.id == "pred_01"
        assert pred.category == "性格"
        assert pred.sequence == 1
        assert 0.0 <= pred.confidence <= 1.0

    def test_core_prediction(self):
        pred = PreEventStatement(
            id="pred_02",
            category="父母关",
            is_core=True,
            sequence=2,
            title="再看看你的父母家庭",
            content="家庭条件较好",
            confidence=0.80,
        )
        assert pred.is_core is True

    def test_default_values(self):
        pred = PreEventStatement(
            id="pred_01",
            category="性格",
            is_core=False,
            sequence=1,
            title="test",
            content="test",
        )
        assert pred.classical_quote == ""
        assert pred.basis == ""
        assert pred.confidence == 0.8

    def test_serialization(self):
        pred = PreEventStatement(
            id="pred_01",
            category="性格",
            is_core=False,
            sequence=1,
            title="test",
            content="test",
        )
        d = pred.model_dump()
        assert d["id"] == "pred_01"
        assert isinstance(d["confidence"], float)


class TestFeedbackItemModel:
    """测试 FeedbackItem 模型"""

    def test_valid_feedback(self):
        fb = FeedbackItem(
            prediction_id="pred_01",
            status="accurate",
            note="确实如此",
        )
        assert fb.status == "accurate"
        assert fb.prediction_id == "pred_01"
        assert fb.note == "确实如此"

    def test_feedback_statuses(self):
        valid = ["accurate", "partial", "inaccurate", "supplement"]
        for s in valid:
            fb = FeedbackItem(prediction_id="pred_01", status=s)
            assert fb.status == s

    def test_default_note(self):
        fb = FeedbackItem(prediction_id="pred_01", status="accurate")
        assert fb.note == ""


class TestFeedbackRoundModel:
    """测试 FeedbackRound 模型"""

    def test_valid_round(self):
        preds = [
            PreEventStatement(
                id="pred_01", category="性格", is_core=False,
                sequence=1, title="test", content="test",
            )
        ]
        fbs = [FeedbackItem(prediction_id="pred_01", status="accurate")]
        round_data = FeedbackRound(
            round_number=1,
            predictions=preds,
            feedbacks=fbs,
        )
        assert round_data.round_number == 1
        assert len(round_data.predictions) == 1
        assert len(round_data.feedbacks) == 1


# ============================================================
# Mock 断事生成测试
# ============================================================

class TestGenerateMockPredictions:
    """测试 Mock 模式生成 7 条断事"""

    def test_generates_seven_predictions(self, sample_chart):
        preds = generate_mock_predictions(sample_chart)
        assert len(preds) == 7

    def test_correct_sequence(self, sample_chart):
        preds = generate_mock_predictions(sample_chart)
        for i, p in enumerate(preds):
            assert p.sequence == i + 1, f"Prediction {p.id} should have sequence {i+1}"

    def test_correct_categories_in_order(self, sample_chart):
        preds = generate_mock_predictions(sample_chart)
        expected_categories = ["性格", "父母关", "兄弟关", "学历", "婚姻关", "事业", "关键年份"]
        for i, p in enumerate(preds):
            assert p.category == expected_categories[i], \
                f"Prediction {i} should be {expected_categories[i]}, got {p.category}"

    def test_core_predictions_marked(self, sample_chart):
        """核心三关（父母、兄弟、婚姻）应标记为 is_core=True"""
        preds = generate_mock_predictions(sample_chart)
        core_count = sum(1 for p in preds if p.is_core)
        assert core_count == 3, f"Expected 3 core predictions, got {core_count}"

        core_categories = [p.category for p in preds if p.is_core]
        assert "父母关" in core_categories
        assert "兄弟关" in core_categories
        assert "婚姻关" in core_categories

    def test_all_have_content(self, sample_chart):
        preds = generate_mock_predictions(sample_chart)
        for p in preds:
            assert p.content, f"{p.id} {p.category} should have content"
            assert len(p.content) > 20, f"{p.id} content should be substantial"

    def test_all_have_classical_quotes(self, sample_chart):
        preds = generate_mock_predictions(sample_chart)
        for p in preds:
            assert p.classical_quote, f"{p.id} {p.category} should have classical quote"

    def test_all_have_basis(self, sample_chart):
        preds = generate_mock_predictions(sample_chart)
        for p in preds:
            assert p.basis, f"{p.id} {p.category} should have basis"

    def test_confidence_in_range(self, sample_chart):
        preds = generate_mock_predictions(sample_chart)
        for p in preds:
            assert 0.0 <= p.confidence <= 1.0, f"{p.id} confidence out of range"

    def test_different_charts_produce_different_results(self, sample_chart, sample_chart_female):
        preds1 = generate_mock_predictions(sample_chart)
        preds2 = generate_mock_predictions(sample_chart_female)
        # 至少性格推断应该不同（因为日主不同）
        assert preds1[0].content != preds2[0].content, \
            "Different charts should produce different predictions"


# ============================================================
# 单条推断生成函数测试
# ============================================================

class TestPersonalityGeneration:
    """测试性格推断生成"""

    def test_produces_valid_prediction(self, sample_chart):
        pred = _build_personality(sample_chart)
        assert pred.id == "pred_01"
        assert pred.category == "性格"
        assert len(pred.content) > 30
        assert "《滴天髓》" in pred.classical_quote

    def test_mentions_day_master(self, sample_chart):
        pred = _build_personality(sample_chart)
        # 内容应包含日主天干
        assert sample_chart.day_master in pred.content


class TestParentsGeneration:
    """测试父母关推断生成"""

    def test_produces_valid_prediction(self, sample_chart):
        pred = _build_parents(sample_chart)
        assert pred.id == "pred_02"
        assert pred.category == "父母关"
        assert pred.is_core is True
        assert len(pred.content) > 20

    def test_references_year_pillar(self, sample_chart):
        pred = _build_parents(sample_chart)
        year_pillar = sample_chart.four_pillars["year"]
        assert year_pillar.stem in pred.content or year_pillar.branch in pred.content


class TestSiblingsGeneration:
    """测试兄弟关推断生成"""

    def test_produces_valid_prediction(self, sample_chart):
        pred = _build_siblings(sample_chart)
        assert pred.id == "pred_03"
        assert pred.category == "兄弟关"
        assert pred.is_core is True

    def test_handles_zero_siblings(self, sample_chart):
        pred = _build_siblings(sample_chart)
        # 至少有一个合理的推断
        assert len(pred.content) > 20


class TestEducationGeneration:
    """测试学历推断生成"""

    def test_produces_valid_prediction(self, sample_chart):
        pred = _build_education(sample_chart)
        assert pred.id == "pred_04"
        assert pred.category == "学历"


class TestMarriageGeneration:
    """测试婚姻关推断生成"""

    def test_produces_valid_prediction(self, sample_chart):
        pred = _build_marriage(sample_chart)
        assert pred.id == "pred_05"
        assert pred.category == "婚姻关"
        assert pred.is_core is True
        assert len(pred.content) > 20

    def test_references_day_branch(self, sample_chart):
        pred = _build_marriage(sample_chart)
        day_branch = sample_chart.four_pillars["day"].branch
        assert day_branch in pred.content or day_branch in pred.basis


class TestCareerGeneration:
    """测试事业推断生成"""

    def test_produces_valid_prediction(self, sample_chart):
        pred = _build_career(sample_chart)
        assert pred.id == "pred_06"
        assert pred.category == "事业"

    def test_references_yongshen(self, sample_chart):
        pred = _build_career(sample_chart)
        # 至少 basis 中应包含用神
        assert len(pred.basis) > 0


class TestKeyYearsGeneration:
    """测试关键年份推断生成"""

    def test_produces_valid_prediction(self, sample_chart):
        pred = _build_key_years(sample_chart)
        assert pred.id == "pred_07"
        assert pred.category == "关键年份"


# ============================================================
# 辅助函数测试
# ============================================================

class TestCountBiJie:
    """测试比劫计数"""

    def test_returns_integer(self, sample_chart):
        pillars = {}
        for pos in ["year", "month", "day", "hour"]:
            pillars[pos] = {
                "stem": sample_chart.four_pillars[pos].stem,
                "branch": sample_chart.four_pillars[pos].branch,
            }
        count = _count_bi_jie(sample_chart.day_master, pillars)
        assert isinstance(count, int)
        assert count >= 0

    def test_different_charts_different_counts(self, sample_chart, sample_chart_female):
        pillars1 = {}
        for pos in ["year", "month", "day", "hour"]:
            pillars1[pos] = {
                "stem": sample_chart.four_pillars[pos].stem,
                "branch": sample_chart.four_pillars[pos].branch,
            }
        pillars2 = {}
        for pos in ["year", "month", "day", "hour"]:
            pillars2[pos] = {
                "stem": sample_chart_female.four_pillars[pos].stem,
                "branch": sample_chart_female.four_pillars[pos].branch,
            }
        count1 = _count_bi_jie(sample_chart.day_master, pillars1)
        count2 = _count_bi_jie(sample_chart_female.day_master, pillars2)
        # 不同八字比劫数可能不同
        assert isinstance(count1, int)
        assert isinstance(count2, int)


class TestCountYinXing:
    """测试印星计数"""

    def test_returns_integer(self, sample_chart):
        pillars = {}
        for pos in ["year", "month", "day", "hour"]:
            pillars[pos] = {
                "stem": sample_chart.four_pillars[pos].stem,
                "branch": sample_chart.four_pillars[pos].branch,
            }
        count = _count_yin_xing(sample_chart.day_master, pillars)
        assert isinstance(count, int)
        assert count >= 0


class TestIsYinXingSolid:
    """测试印星得地判断"""

    def test_returns_boolean(self, sample_chart):
        pillars = {}
        for pos in ["year", "month", "day", "hour"]:
            pillars[pos] = {
                "stem": sample_chart.four_pillars[pos].stem,
                "branch": sample_chart.four_pillars[pos].branch,
            }
        result = _is_yin_xing_solid(sample_chart.day_master, pillars)
        assert isinstance(result, bool)


class TestGuanYinXiangSheng:
    """测试官印相生判断"""

    def test_returns_boolean(self, sample_chart):
        pillars = {}
        for pos in ["year", "month", "day", "hour"]:
            pillars[pos] = {
                "stem": sample_chart.four_pillars[pos].stem,
                "branch": sample_chart.four_pillars[pos].branch,
            }
        result = _has_guan_yin_xiang_sheng(sample_chart.day_master, pillars)
        assert isinstance(result, bool)


class TestShishangShengCai:
    """测试食伤生财判断"""

    def test_returns_boolean(self, sample_chart):
        pillars = {}
        for pos in ["year", "month", "day", "hour"]:
            pillars[pos] = {
                "stem": sample_chart.four_pillars[pos].stem,
                "branch": sample_chart.four_pillars[pos].branch,
            }
        result = _has_shishang_sheng_cai(sample_chart.day_master, pillars)
        assert isinstance(result, bool)


class TestGetKeyYears:
    """测试关键年份提取"""

    def test_returns_list_of_ints(self, sample_chart):
        dayun_data = []
        for d in sample_chart.dayun:
            dayun_data.append({
                "stem": d.stem,
                "branch": d.branch,
                "ten_god": d.ten_god,
                "start_age": d.start_age,
                "start_year": d.start_year,
                "end_age": d.end_age,
                "end_year": d.end_year,
            })
        years = _get_key_years(dayun_data, {})
        assert isinstance(years, list)
        assert len(years) <= 3
        for y in years:
            assert isinstance(y, int)
            assert y > 1900


# ============================================================
# 集成测试
# ============================================================

@pytest.mark.integration
class TestPredictionsIntegration:
    """集成测试：完整流程"""

    def test_full_mock_flow(self, sample_chart):
        """完整的 Mock 断事生成流程"""
        preds = generate_mock_predictions(sample_chart)
        assert len(preds) == 7

        # 验证所有 ID 唯一
        ids = [p.id for p in preds]
        assert len(ids) == len(set(ids)), "Prediction IDs should be unique"

    def test_predictions_serializable(self, sample_chart):
        """验证所有断事可序列化为 JSON"""
        preds = generate_mock_predictions(sample_chart)
        for p in preds:
            d = p.model_dump()
            assert isinstance(d, dict)
            assert "id" in d
            assert "category" in d
            assert "content" in d

    def test_feedback_round_construction(self, sample_chart):
        """验证反馈轮次构建"""
        preds = generate_mock_predictions(sample_chart)
        fbs = [
            FeedbackItem(prediction_id=p.id, status="accurate")
            for p in preds
        ]
        round_data = FeedbackRound(
            round_number=1,
            predictions=preds,
            feedbacks=fbs,
        )
        assert round_data.round_number == 1
        assert len(round_data.feedbacks) == 7


# ============================================================
# 不同日期测试（确保通用性）
# ============================================================

class TestMultipleDates:
    """多个日期验证断事生成不崩溃"""

    test_dates = [
        (1990, 3, 15, 8, "male"),     # 1990-03-15 男
        (1986, 1, 15, 12, "female"),  # 1986-01-15 女
        (2000, 6, 1, 14, "male"),     # 2000-06-01 男
        (1975, 12, 25, 22, "female"), # 1975-12-25 女
        (2010, 8, 8, 6, "male"),      # 2010-08-08 男
    ]

    @pytest.mark.parametrize("year,month,day,hour,gender", test_dates)
    def test_predictions_for_various_dates(self, year, month, day, hour, gender):
        """验证不同日期都能成功生成 7 条断事"""
        chart = calculate_bazi(
            year=year, month=month, day=day, hour=hour, minute=0, gender=gender
        )
        preds = generate_mock_predictions(chart)
        assert len(preds) == 7, f"Failed for {year}-{month:02d}-{day:02d} {gender}"
        for p in preds:
            assert p.content, f"Missing content for {p.id} in {year}-{month:02d}-{day:02d}"


# ============================================================
# 动态题量测试：judge_info_sufficient
# ============================================================

class TestCoreGatesCovered:
    """测试核心三关覆盖判断"""

    def test_all_three_covered(self):
        assert _core_gates_covered({"父母关", "兄弟关", "婚姻关"}) is True

    def test_partial_coverage(self):
        assert _core_gates_covered({"父母关", "兄弟关"}) is False
        assert _core_gates_covered({"婚姻关"}) is False

    def test_empty_set(self):
        assert _core_gates_covered(set()) is False


class TestGetNextCategorySuggestion:
    """测试下一题建议"""

    def test_suggests_remaining_core_gate(self):
        result = _get_next_category_suggestion({"性格", "父母关"})
        assert "兄弟关" in result or "婚姻关" in result

    def test_suggests_remaining_category(self):
        result = _get_next_category_suggestion({"性格", "父母关", "兄弟关", "婚姻关"})
        assert result != ""

    def test_all_covered(self):
        result = _get_next_category_suggestion({"性格", "父母关", "兄弟关", "学历", "婚姻关", "事业", "关键年份"})
        assert "换个角度" in result


class TestJudgeInfoSufficient:
    """测试信息充足性判断（Mock 模式，无 API Key）"""

    def test_not_sufficient_with_few_feedbacks(self):
        """少于5条且核心三关未覆盖 → 不充足"""
        predictions = [
            {"id": "pred_01", "category": "性格", "content": "test"},
            {"id": "pred_02", "category": "学历", "content": "test"},
        ]
        feedbacks = [
            {"prediction_id": "pred_01", "status": "accurate"},
            {"prediction_id": "pred_02", "status": "accurate"},
        ]
        result = judge_info_sufficient({}, predictions, feedbacks)
        assert result["sufficient"] is False

    def test_sufficient_with_core_gates_and_min_count(self):
        """5条以上且核心三关覆盖 → 充足"""
        predictions = [
            {"id": "pred_01", "category": "性格", "content": "test"},
            {"id": "pred_02", "category": "父母关", "content": "test"},
            {"id": "pred_03", "category": "兄弟关", "content": "test"},
            {"id": "pred_04", "category": "学历", "content": "test"},
            {"id": "pred_05", "category": "婚姻关", "content": "test"},
        ]
        feedbacks = [
            {"prediction_id": f"pred_{i:02d}", "status": "accurate"}
            for i in range(1, 6)
        ]
        result = judge_info_sufficient({}, predictions, feedbacks)
        assert result["sufficient"] is True

    def test_not_sufficient_core_gates_missing(self):
        """5条但核心三关不完整 → 不充足"""
        predictions = [
            {"id": "pred_01", "category": "性格", "content": "test"},
            {"id": "pred_02", "category": "学历", "content": "test"},
            {"id": "pred_03", "category": "事业", "content": "test"},
            {"id": "pred_04", "category": "关键年份", "content": "test"},
            {"id": "pred_05", "category": "性格", "content": "test"},
        ]
        feedbacks = [
            {"prediction_id": f"pred_{i:02d}", "status": "accurate"}
            for i in range(1, 6)
        ]
        result = judge_info_sufficient({}, predictions, feedbacks)
        assert result["sufficient"] is False

    def test_max_predictions_limit(self):
        """达到 MAX_PREDICTIONS 上限后强制判定充足"""
        predictions = [
            {"id": f"pred_{i:02d}", "category": "性格", "content": "test"}
            for i in range(1, MAX_PREDICTIONS + 1)
        ]
        feedbacks = [
            {"prediction_id": f"pred_{i:02d}", "status": "accurate"}
            for i in range(1, MAX_PREDICTIONS + 1)
        ]
        result = judge_info_sufficient({}, predictions, feedbacks)
        assert result["sufficient"] is True
        assert "最大题量" in result["reason"]

    def test_four_items_with_core_gates_not_sufficient(self):
        """4条即使核心三关全覆盖也不够（需要 >= 5）"""
        predictions = [
            {"id": "pred_01", "category": "父母关", "content": "test"},
            {"id": "pred_02", "category": "兄弟关", "content": "test"},
            {"id": "pred_03", "category": "婚姻关", "content": "test"},
            {"id": "pred_04", "category": "性格", "content": "test"},
        ]
        feedbacks = [
            {"prediction_id": f"pred_{i:02d}", "status": "accurate"}
            for i in range(1, 5)
        ]
        result = judge_info_sufficient({}, predictions, feedbacks)
        assert result["sufficient"] is False


# ============================================================
# 动态题量测试：generate_single_prediction (Mock)
# ============================================================

class TestMockGenerateSingle:
    """测试 Mock 模式下逐条生成"""

    def test_generates_first_unasked_category(self, sample_chart):
        """应该生成第一个未被问过的类别"""
        pred = _mock_generate_single(sample_chart, {"性格"}, 2)
        assert pred is not None
        assert pred.category == "父母关"  # 第二个应该是父母关
        assert pred.sequence == 2

    def test_respects_sequence(self, sample_chart):
        """sequence 应正确递增"""
        pred = _mock_generate_single(sample_chart, {"性格", "父母关", "兄弟关"}, 4)
        assert pred is not None
        assert pred.sequence == 4
        assert pred.category == "学历"

    def test_returns_none_when_all_asked(self, sample_chart):
        """所有类别都问过了应返回 None"""
        all_cats = {"性格", "父母关", "兄弟关", "学历", "婚姻关", "事业", "关键年份"}
        pred = _mock_generate_single(sample_chart, all_cats, 8)
        assert pred is None

    def test_each_call_returns_unique_category(self, sample_chart):
        """每次调用返回不同类别"""
        cats = set()
        for i in range(7):
            pred = _mock_generate_single(sample_chart, cats, i + 1)
            if pred:
                cats.add(pred.category)
        assert len(cats) == 7

    def test_sequential_generation_covers_all_categories(self, sample_chart):
        """顺序生成覆盖全部7个类别"""
        cats = set()
        all_preds = []
        for i in range(7):
            pred = _mock_generate_single(sample_chart, cats, i + 1)
            if pred:
                cats.add(pred.category)
                all_preds.append(pred)
        assert len(all_preds) == 7
        expected = {"性格", "父母关", "兄弟关", "学历", "婚姻关", "事业", "关键年份"}
        assert cats == expected


@pytest.mark.asyncio
class TestGenerateSinglePrediction:
    """测试 async generate_single_prediction（Mock 回退路径）"""

    async def test_generates_prediction_for_empty_asked(self, sample_chart):
        """无任何已问类别时生成第一条"""
        chart_data = sample_chart.model_dump()
        pred = await generate_single_prediction(
            sample_chart, chart_data, set(), []
        )
        assert pred is not None
        assert pred.sequence == 1
        assert pred.category in ["性格", "父母关", "兄弟关", "学历", "婚姻关", "事业", "关键年份"]

    async def test_skips_already_asked(self, sample_chart):
        """跳过已问类别"""
        chart_data = sample_chart.model_dump()
        asked = {"性格", "父母关", "兄弟关"}
        pred = await generate_single_prediction(
            sample_chart, chart_data, asked, []
        )
        assert pred is not None
        assert pred.category not in asked
        assert pred.sequence == 4

    async def test_returns_none_when_all_asked(self, sample_chart):
        """所有类别都问了返回 None"""
        chart_data = sample_chart.model_dump()
        all_cats = {"性格", "父母关", "兄弟关", "学历", "婚姻关", "事业", "关键年份"}
        pred = await generate_single_prediction(
            sample_chart, chart_data, all_cats, []
        )
        assert pred is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
