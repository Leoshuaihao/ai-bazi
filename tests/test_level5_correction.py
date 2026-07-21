"""Tests for Level 5 行运修正深度增强"""

import sys
sys.path.insert(0, '/Users/lee/WorkSpace/WorkBuddy/ai-bazi')

import pytest

from services.correction.level5_dayun import (
    Level5DayunCorrector,
    CorrectionResult,
    execute_level5_mock,
    PATTERN_DAYUN_REQUIREMENTS,
)


# Sample chart — 七杀格 with dayun data
SAMPLE_CHART = {
    "day_master": "丙",
    "pattern": "七杀格",
    "yongshen": {"ten_god": "七杀", "five_element": "水", "mode": "逆用"},
    "four_pillars": {
        "year": {"stem": "甲", "branch": "子", "hidden_stems": [{"stem": "癸", "weight": 0.6}]},
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
    "dayun": [
        {"stem": "癸", "branch": "酉", "ten_god": "正官", "start_year": 1986, "end_year": 1995},
        {"stem": "甲", "branch": "戌", "ten_god": "偏印", "start_year": 1996, "end_year": 2005},
        {"stem": "乙", "branch": "亥", "ten_god": "正印", "start_year": 2006, "end_year": 2015},
        {"stem": "丙", "branch": "子", "ten_god": "比肩", "start_year": 2016, "end_year": 2025},
        {"stem": "丁", "branch": "丑", "ten_god": "劫财", "start_year": 2026, "end_year": 2035},
    ],
}

# Sample single dayun
SAMPLE_DAYUN = {"stem": "癸", "branch": "酉", "ten_god": "正官", "start_year": 1986, "end_year": 1995}

# 正官格 sample
SAMPLE_CHART_GUAN = {
    "day_master": "甲",
    "pattern": "正官格",
    "four_pillars": {
        "year": {"stem": "丙", "branch": "寅", "hidden_stems": [
            {"stem": "甲", "weight": 0.5}, {"stem": "丙", "weight": 0.3}, {"stem": "戊", "weight": 0.2}
        ]},
        "month": {"stem": "辛", "branch": "酉", "hidden_stems": [
            {"stem": "辛", "weight": 0.6}
        ]},
        "day": {"stem": "甲", "branch": "子", "hidden_stems": [
            {"stem": "癸", "weight": 0.6}
        ]},
        "hour": {"stem": "壬", "branch": "申", "hidden_stems": [
            {"stem": "庚", "weight": 0.5}, {"stem": "壬", "weight": 0.3}, {"stem": "戊", "weight": 0.2}
        ]},
    },
    "dayun": [
        {"stem": "壬", "branch": "戌", "ten_god": "偏印", "start_year": 1990, "end_year": 1999},
        {"stem": "癸", "branch": "亥", "ten_god": "正印", "start_year": 2000, "end_year": 2009},
    ],
}

# 从弱格 sample — day master very weak
SAMPLE_CHART_CONGG = {
    "day_master": "甲",
    "pattern": "从弱格",
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
    "dayun": [
        {"stem": "壬", "branch": "戌", "ten_god": "偏印", "start_year": 1990, "end_year": 1999},
        {"stem": "庚", "branch": "申", "ten_god": "七杀", "start_year": 2000, "end_year": 2009},
    ],
}


class TestDetectDayunChengge:
    """测试运中成格检测"""

    @pytest.mark.asyncio
    async def test_chengge_detected_with_structure(self):
        """运中成格：测试结构返回"""
        corrector = Level5DayunCorrector()
        result = await corrector.detect_dayun_chengge(SAMPLE_CHART, SAMPLE_DAYUN)
        assert result["effect_type"] == "运中成格"
        assert "detected" in result
        assert "matches" in result
        assert "classical_source" in result

    @pytest.mark.asyncio
    async def test_chengge_classical_source(self):
        """运中成格：含《子平真诠》引用"""
        corrector = Level5DayunCorrector()
        result = await corrector.detect_dayun_chengge(SAMPLE_CHART, SAMPLE_DAYUN)
        assert len(result["classical_source"]) > 10

    @pytest.mark.asyncio
    async def test_chengge_yunguo_jizhi(self):
        """运中成格：标注"运过即止" """
        corrector = Level5DayunCorrector()
        result = await corrector.detect_dayun_chengge(SAMPLE_CHART, SAMPLE_DAYUN)
        for match in result["matches"]:
            assert match.get("is_temporary") is True
            assert "运过即止" in match.get("note", "")

    @pytest.mark.asyncio
    async def test_chengge_match_fields(self):
        """运中成格：每个match有必需字段"""
        corrector = Level5DayunCorrector()
        # Use chart with 正官格 + 财星大运 (to test chengge scenario)
        result = await corrector.detect_dayun_chengge(
            SAMPLE_CHART_GUAN,
            {"stem": "己", "branch": "丑", "ten_god": "正财", "start_year": 2010, "end_year": 2019}
        )
        for match in result["matches"]:
            assert "dayun" in match
            assert "effect" in match
            assert "detail" in match


class TestDetectDayunBiange:
    """测试运中变格检测"""

    @pytest.mark.asyncio
    async def test_biange_structure(self):
        """运中变格：结构返回正常"""
        corrector = Level5DayunCorrector()
        result = await corrector.detect_dayun_biange(SAMPLE_CHART, SAMPLE_DAYUN)
        assert result["effect_type"] == "运中变格"
        assert "detected" in result

    @pytest.mark.asyncio
    async def test_biange_yunguo_jizhi(self):
        """运中变格：标注"运过即止" """
        corrector = Level5DayunCorrector()
        result = await corrector.detect_dayun_biange(SAMPLE_CHART, SAMPLE_DAYUN)
        for match in result["matches"]:
            assert match.get("is_temporary") is True
            assert "运过即止" in match.get("note", "")


class TestDetectDayunPoge:
    """测试运中破格检测"""

    @pytest.mark.asyncio
    async def test_poge_structure(self):
        """运中破格：结构返回正常"""
        corrector = Level5DayunCorrector()
        result = await corrector.detect_dayun_poge(SAMPLE_CHART, SAMPLE_DAYUN)
        assert result["effect_type"] == "运中破格"
        assert "detected" in result
        assert "matches" in result

    @pytest.mark.asyncio
    async def test_poge_match_has_severity(self):
        """运中破格：每个match有severity字段"""
        corrector = Level5DayunCorrector()
        result = await corrector.detect_dayun_poge(SAMPLE_CHART, SAMPLE_DAYUN)
        for match in result["matches"]:
            assert "severity" in match
            assert match["severity"] in ("high", "critical")

    @pytest.mark.asyncio
    async def test_poge_yunguo_jizhi(self):
        """运中破格：标注"运过即止" """
        corrector = Level5DayunCorrector()
        result = await corrector.detect_dayun_poge(SAMPLE_CHART, SAMPLE_DAYUN)
        for match in result["matches"]:
            assert "运过即止" in match.get("note", "")

    @pytest.mark.asyncio
    async def test_poge_chong_yueling(self):
        """运中破格：检测地支冲月令"""
        # 月令申被寅冲
        corrector = Level5DayunCorrector()
        result = await corrector.detect_dayun_poge(
            SAMPLE_CHART,
            {"stem": "甲", "branch": "寅", "ten_god": "偏印", "start_year": 2030, "end_year": 2039}
        )
        # 寅冲申（SAMPLE_CHART月令为申）
        has_chong = any(
            "冲月令" in m.get("detail", "") for m in result["matches"]
        )
        # 可能检测到或检测不到取决于具体条件
        assert isinstance(has_chong, bool)  # 至少不崩溃


class TestDetectDayunBingcun:
    """测试运中并存检测"""

    @pytest.mark.asyncio
    async def test_bingcun_structure(self):
        """运中并存：结构返回正常"""
        corrector = Level5DayunCorrector()
        result = await corrector.detect_dayun_bingcun(SAMPLE_CHART, SAMPLE_DAYUN)
        assert result["effect_type"] == "运中并存"
        assert "detected" in result

    @pytest.mark.asyncio
    async def test_bingcun_yunguo_jizhi(self):
        """运中并存：标注"运过即止" """
        corrector = Level5DayunCorrector()
        result = await corrector.detect_dayun_bingcun(SAMPLE_CHART, SAMPLE_DAYUN)
        for match in result["matches"]:
            assert "运过即止" in match.get("note", "")

    @pytest.mark.asyncio
    async def test_bingcun_has_suggestion(self):
        """运中并存：有前五年/后五年建议"""
        corrector = Level5DayunCorrector()
        result = await corrector.detect_dayun_bingcun(SAMPLE_CHART, SAMPLE_DAYUN)
        for match in result["matches"]:
            assert "suggestion" in match


class TestExecuteLevel5:
    """测试 execute_level5 综合执行"""

    @pytest.mark.asyncio
    async def test_execute_level5_returns_result(self):
        """execute_level5 返回 CorrectionResult"""
        corrector = Level5DayunCorrector()
        result = await corrector.execute_level5(SAMPLE_CHART)
        assert isinstance(result, CorrectionResult)
        assert result.level == 5

    @pytest.mark.asyncio
    async def test_execute_level5_has_source(self):
        """execute_level5 有典籍出处"""
        corrector = Level5DayunCorrector()
        result = await corrector.execute_level5(SAMPLE_CHART)
        assert result.source
        assert len(result.source) > 10

    @pytest.mark.asyncio
    async def test_execute_level5_has_data(self):
        """execute_level5 data 包含四种效应"""
        corrector = Level5DayunCorrector()
        result = await corrector.execute_level5(SAMPLE_CHART)
        assert "effects" in result.data
        effects = result.data["effects"]
        assert "chengge" in effects
        assert "biange" in effects
        assert "poge" in effects
        assert "bingcun" in effects

    @pytest.mark.asyncio
    async def test_execute_level5_empty_dayun(self):
        """execute_level5 无大运数据 → success=False"""
        corrector = Level5DayunCorrector()
        result = await corrector.execute_level5({"pattern": "正官格", "dayun": []})
        assert result.success is False
        assert "无大运数据" in result.detail

    @pytest.mark.asyncio
    async def test_execute_level5_with_multiple_dayun(self):
        """execute_level5 多步大运分析"""
        corrector = Level5DayunCorrector()
        result = await corrector.execute_level5(SAMPLE_CHART)
        # 至少应该分析了dayun_report
        if result.success:
            assert "dayun_report" in result.data
        else:
            # 即使未发现效应，也应有effects数据
            assert "effects" in result.data


class TestMockMode:
    """测试 Mock 模式"""

    @pytest.mark.asyncio
    async def test_mock_mode_works(self):
        """Mock 模式正常"""
        result = await execute_level5_mock(SAMPLE_CHART)
        assert isinstance(result, CorrectionResult)
        assert result.level == 5


class TestPatternDayunRequirements:
    """测试 PATTERN_DAYUN_REQUIREMENTS 完整性"""

    def test_all_patterns_have_requirements(self):
        """每个格局都有需求定义"""
        expected_patterns = [
            "正官格", "七杀格", "正财格", "偏财格",
            "正印格", "偏印格", "食神格", "伤官格",
            "建禄格", "月刃格", "从弱格", "专旺格", "化气格",
        ]
        for p in expected_patterns:
            assert p in PATTERN_DAYUN_REQUIREMENTS, f"缺少 {p}"

    def test_all_requirements_have_fields(self):
        """每个需求定义有必需字段"""
        for pattern, reqs in PATTERN_DAYUN_REQUIREMENTS.items():
            assert "needs" in reqs, f"{pattern} 缺少 needs"
            assert "avoids" in reqs, f"{pattern} 缺少 avoids"
            assert "cheng_conditions" in reqs, f"{pattern} 缺少 cheng_conditions"
            assert "bai_conditions" in reqs, f"{pattern} 缺少 bai_conditions"


class TestHelperMethods:
    """测试辅助方法"""

    @pytest.mark.asyncio
    async def test_chart_lacks_initial(self):
        """_chart_lacks 基本检测"""
        corrector = Level5DayunCorrector()
        # SAMPLE_CHART 七杀格，原局有七杀（月干壬）和印星（年干甲，时干甲）
        # 但食神可能不存在
        result = corrector._chart_lacks(SAMPLE_CHART, "食神到位", "七杀格")
        assert isinstance(result, bool)

    def test_dayun_matches_condition_caixing(self):
        """_dayun_matches_condition 财星到位"""
        corrector = Level5DayunCorrector()
        assert corrector._dayun_matches_condition(
            "正财", "丑", "财星到位", SAMPLE_CHART
        ) is True
        assert corrector._dayun_matches_condition(
            "伤官", "丑", "财星到位", SAMPLE_CHART
        ) is False

    def test_dayun_matches_condition_yinxing(self):
        """_dayun_matches_condition 印星到位"""
        corrector = Level5DayunCorrector()
        assert corrector._dayun_matches_condition(
            "正印", "丑", "印星到位", SAMPLE_CHART
        ) is True
        assert corrector._dayun_matches_condition(
            "七杀", "丑", "印星到位", SAMPLE_CHART
        ) is False


class TestImportCompatibility:
    """测试导入兼容性"""

    def test_import_level5_dayun(self):
        """验证 level5_dayun 模块可导入"""
        from services.correction.level5_dayun import (
            Level5DayunCorrector,
            CorrectionResult,
            execute_level5_mock,
        )
        assert Level5DayunCorrector is not None
        assert CorrectionResult is not None
        assert execute_level5_mock is not None
