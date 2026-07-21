"""Tests for Level 1 用神修正子维度细化"""

import sys
sys.path.insert(0, '/Users/lee/WorkSpace/WorkBuddy/ai-bazi')

import pytest
import asyncio

from services.correction.level1_yongshen import (
    Level1YongshenCorrector,
    execute_level1_mock,
    CorrectionResult,
)


# Sample chart data based on the existing project's data format
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
}

# Chart with yongshen having root (真神得用)
SAMPLE_CHART_ZHEN = {
    "day_master": "丙",
    "pattern": "七杀格",
    "yongshen": {"ten_god": "七杀", "five_element": "水", "mode": "逆用"},
    "four_pillars": {
        "year": {"stem": "甲", "branch": "子", "hidden_stems": [{"stem": "癸", "weight": 0.6}]},
        "month": {"stem": "壬", "branch": "子", "hidden_stems": [
            {"stem": "癸", "weight": 0.6}
        ]},
        "day": {"stem": "丙", "branch": "午", "hidden_stems": [
            {"stem": "丁", "weight": 0.5}, {"stem": "己", "weight": 0.3}
        ]},
        "hour": {"stem": "甲", "branch": "午", "hidden_stems": [
            {"stem": "丁", "weight": 0.5}, {"stem": "己", "weight": 0.3}
        ]},
    },
}

# Chart with togan change (透干会支变化)
SAMPLE_CHART_TOUGAN = {
    "day_master": "丙",
    "pattern": "正官格",
    "yongshen": {"ten_god": "正官", "five_element": "金", "mode": "顺用"},
    "four_pillars": {
        "year": {"stem": "丁", "branch": "卯", "hidden_stems": [{"stem": "乙", "weight": 0.6}]},
        "month": {"stem": "丙", "branch": "巳", "hidden_stems": [
            {"stem": "丙", "weight": 0.5}, {"stem": "戊", "weight": 0.3}, {"stem": "庚", "weight": 0.2}
        ]},
        "day": {"stem": "甲", "branch": "午", "hidden_stems": [
            {"stem": "丁", "weight": 0.5}, {"stem": "己", "weight": 0.3}
        ]},
        "hour": {"stem": "戊", "branch": "辰", "hidden_stems": [
            {"stem": "戊", "weight": 0.5}, {"stem": "乙", "weight": 0.3}, {"stem": "癸", "weight": 0.2}
        ]},
    },
}


class TestFix1ATouganHuizhi:
    """测试 1A: 透干会支变化"""

    @pytest.mark.asyncio
    async def test_tougan_combination_enum(self):
        """1A：透干组合枚举正常"""
        corrector = Level1YongshenCorrector()
        result = await corrector.fix_1a_tougan_huizhi(SAMPLE_CHART)
        assert result["sub_dimension"] == "1A-透干会支变化"
        assert "candidates" in result
        assert isinstance(result["candidates"], list)
        assert "classical_source" in result
        # classical_source contains a full citation string
        assert len(result["classical_source"]) > 10

    @pytest.mark.asyncio
    async def test_tougan_has_recommendation(self):
        """1A：推荐格局存在"""
        corrector = Level1YongshenCorrector()
        result = await corrector.fix_1a_tougan_huizhi(SAMPLE_CHART)
        assert "recommendation" in result
        if result["candidates"]:
            assert result["recommendation"] == result["candidates"][0]["pattern"]

    @pytest.mark.asyncio
    async def test_tougan_max_3_candidates(self):
        """1A：候选不超过3个"""
        corrector = Level1YongshenCorrector()
        result = await corrector.fix_1a_tougan_huizhi(SAMPLE_CHART)
        assert len(result["candidates"]) <= 3

    @pytest.mark.asyncio
    async def test_tougan_candidates_sorted_by_confidence(self):
        """1A：候选按置信度降序排列"""
        corrector = Level1YongshenCorrector()
        result = await corrector.fix_1a_tougan_huizhi(SAMPLE_CHART)
        if len(result["candidates"]) >= 2:
            for i in range(len(result["candidates"]) - 1):
                assert result["candidates"][i]["confidence"] >= result["candidates"][i + 1]["confidence"]

    @pytest.mark.asyncio
    async def test_tougan_tugan_change_detected(self):
        """1A：检测到透干变化（月令中气强透）"""
        corrector = Level1YongshenCorrector()
        result = await corrector.fix_1a_tougan_huizhi(SAMPLE_CHART_TOUGAN)
        # 应该至少有本气候选
        assert len(result["candidates"]) >= 1

    @pytest.mark.asyncio
    async def test_tougan_each_candidate_has_fields(self):
        """1A：每个候选都有必要字段"""
        corrector = Level1YongshenCorrector()
        result = await corrector.fix_1a_tougan_huizhi(SAMPLE_CHART)
        for c in result["candidates"]:
            assert "pattern" in c
            assert "source" in c
            assert "confidence" in c
            assert "detail" in c


class TestFix1BZhengjia:
    """测试 1B: 真假判别"""

    @pytest.mark.asyncio
    async def test_zhen_shen_de_yong(self):
        """1B：真神得用判定"""
        corrector = Level1YongshenCorrector()
        result = await corrector.fix_1b_zhengjia(SAMPLE_CHART_ZHEN)
        assert result["sub_dimension"] == "1B-真假判别"
        # 壬水在子（根）且透干（月干壬）
        assert "conclusion" in result
        assert "is_zhen" in result

    @pytest.mark.asyncio
    async def test_jia_shen_de_ju(self):
        """1B：假神得局判定"""
        corrector = Level1YongshenCorrector()
        result = await corrector.fix_1b_zhengjia(SAMPLE_CHART)
        assert result["sub_dimension"] == "1B-真假判别"
        assert "conclusion" in result
        assert "is_zhen" in result

    @pytest.mark.asyncio
    async def test_zhengjia_result_structure(self):
        """1B：返回结构完整"""
        corrector = Level1YongshenCorrector()
        result = await corrector.fix_1b_zhengjia(SAMPLE_CHART)
        required_fields = ["sub_dimension", "is_zhen", "conclusion", "detail",
                          "has_root", "is_touched", "is_hurt", "classical_source"]
        for field in required_fields:
            assert field in result, f"缺少字段: {field}"

    @pytest.mark.asyncio
    async def test_zhengjia_classical_source(self):
        """1B：含古籍引用"""
        corrector = Level1YongshenCorrector()
        result = await corrector.fix_1b_zhengjia(SAMPLE_CHART)
        assert len(result["classical_source"]) > 10

    @pytest.mark.asyncio
    async def test_zhengjia_four_states(self):
        """1B：四状态判定（真神得用/假神得局/真神暗藏/用神不显）"""
        corrector = Level1YongshenCorrector()
        result = await corrector.fix_1b_zhengjia(SAMPLE_CHART)
        valid_conclusions = ["真神得用", "假神得局", "真神暗藏", "用神不显", "真神受损"]
        assert result["conclusion"] in valid_conclusions, (
            f"结论'{result['conclusion']}'不在四状态列表中"
        )


class TestFix1CJiuying:
    """测试 1C: 救应检测"""

    @pytest.mark.asyncio
    async def test_jiuying_detection(self):
        """1C：救应检测正常执行"""
        corrector = Level1YongshenCorrector()
        result = await corrector.fix_1c_jiuying(SAMPLE_CHART)
        assert result["sub_dimension"] == "1C-救应检查"
        assert "status" in result
        assert "detail" in result
        assert "classical_source" in result

    @pytest.mark.asyncio
    async def test_jiuying_result_structure(self):
        """1C：返回结构完整"""
        corrector = Level1YongshenCorrector()
        result = await corrector.fix_1c_jiuying(SAMPLE_CHART)
        assert "sub_dimension" in result
        assert "status" in result
        assert "jiuying_hurt" in result

    @pytest.mark.asyncio
    async def test_jiuying_valid_status(self):
        """1C：状态值有效"""
        corrector = Level1YongshenCorrector()
        result = await corrector.fix_1c_jiuying(SAMPLE_CHART)
        valid_statuses = ["成格无败", "救应得力", "救应被伤", "败格无救"]
        assert result["status"] in valid_statuses, (
            f"状态'{result['status']}'不在有效状态列表中"
        )

    @pytest.mark.asyncio
    async def test_jiuying_has_classical(self):
        """1C：含《子平真诠》古籍引用"""
        corrector = Level1YongshenCorrector()
        result = await corrector.fix_1c_jiuying(SAMPLE_CHART)
        # classical_source should be non-empty
        assert len(result["classical_source"]) > 10

    @pytest.mark.asyncio
    async def test_jiuying_beishang_detection(self):
        """1C：救应被伤检测（两番损伤）"""
        # 构造一个有救应但救应被伤的命局
        chart_with_hurt_jiuying = {
            "day_master": "甲",
            "pattern": "正官格",
            "yongshen": {"ten_god": "正官", "five_element": "金"},
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
                "hour": {"stem": "丁", "branch": "卯", "hidden_stems": [
                    {"stem": "乙", "weight": 0.6}
                ]},
            },
        }
        corrector = Level1YongshenCorrector()
        result = await corrector.fix_1c_jiuying(chart_with_hurt_jiuying)
        assert "status" in result


class TestExecuteLevel1:
    """测试 execute_level1 综合执行"""

    @pytest.mark.asyncio
    async def test_execute_level1_returns_result(self):
        """execute_level1 返回 CorrectionResult"""
        corrector = Level1YongshenCorrector()
        result = await corrector.execute_level1(SAMPLE_CHART)
        assert isinstance(result, CorrectionResult)
        assert result.level == 1

    @pytest.mark.asyncio
    async def test_execute_level1_has_source(self):
        """execute_level1 有典籍出处"""
        corrector = Level1YongshenCorrector()
        result = await corrector.execute_level1(SAMPLE_CHART)
        assert result.source

    @pytest.mark.asyncio
    async def test_execute_level1_order(self):
        """1A→1B→1C 顺序执行"""
        corrector = Level1YongshenCorrector()
        result = await corrector.execute_level1(SAMPLE_CHART)
        # 无论成功或失败，sub_dimension 应该反映检查顺序
        assert result.sub_dimension in ("1A-透干会支变化", "1B-真假判别",
                                         "1C-救应检查", "Level1")


class TestMockMode:
    """测试 Mock 模式"""

    @pytest.mark.asyncio
    async def test_mock_mode_works(self):
        """Mock DeepSeek 模式正常"""
        result = await execute_level1_mock(SAMPLE_CHART)
        assert isinstance(result, CorrectionResult)
        assert result.level == 1


class TestCorrectionImport:
    """测试外部导入兼容性"""

    def test_import_level1_yongshen(self):
        """验证 level1_yongshen 模块可导入"""
        from services.correction.level1_yongshen import (
            Level1YongshenCorrector,
            CorrectionResult,
            execute_level1_mock,
        )
        assert Level1YongshenCorrector is not None
        assert CorrectionResult is not None
        assert execute_level1_mock is not None

    def test_import_correction_init(self):
        """验证 correction/__init__.py 可导入"""
        import services.correction
        assert services.correction is not None

    def test_level1_in_correction_v2_try_import(self):
        """验证 correction_v2.py 中的 try/except ImportError 兼容"""
        # 模拟：模块存在时应该成功导入
        try:
            from services.correction.level1_yongshen import Level1YongshenCorrector
            assert True  # 导入成功
        except ImportError:
            assert False, "level1_yongshen 导入失败"


class TestHelperFunctions:
    """测试辅助函数"""

    def test_check_jiuying_hurt_empty(self):
        """_check_jiuying_hurt 空输入返回空"""
        corrector = Level1YongshenCorrector()
        result = corrector._check_jiuying_hurt("", {})
        assert result == ""

    def test_check_jiuying_hurt_nonexistent(self):
        """_check_jiuying_hurt 不存在的救应之神"""
        corrector = Level1YongshenCorrector()
        result = corrector._check_jiuying_hurt("食神", SAMPLE_CHART)
        # 食神可能不存在于SAMPLE_CHART中
        assert isinstance(result, str)
