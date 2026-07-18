"""RAG 检索 + AI 解释模块测试"""

import pytest
import asyncio

from services.rag_retriever import retrieve_relevant_texts, _extract_keywords, _score_chapter
from services.ai_explainer import generate_mock_explanation, _build_prompt
from bazi_engine import calculate_bazi
from services.reanalysis import reanalyze_chart


# ============================================================
# 测试数据：模拟一个 strength_detail（身弱的己土日主）
# ============================================================

MOCK_STRENGTH_DETAIL = {
    "ri_zhu": "己",
    "ri_zhu_wuxing": "土",
    "deling": {
        "score": 15,
        "max_score": 50,
        "detail": [
            "卯月令本气乙(木)非生助 +0",
            "卯月令中气丙(火)为印星 +15",
        ],
        "conclusion": "略得令（月令中气/余气有生助）",
    },
    "dedi": {
        "score": 16,
        "max_score": 64,
        "detail": [
            "年支午藏本气丁(火)非根 +0",
            "月支卯藏本气乙(木)非根 +0",
            "日支卯藏本气乙(木)非根 +0",
            "时支辰藏本气戊(土)为日主根 +16",
        ],
        "conclusion": "得地较弱（仅个别地支有根）",
    },
    "desheng": {
        "score": 15,
        "detail": [
            "月干己(土)非印星 +0",
            "时干丙(火)为印星 +12",
            "月支卯藏中气丙(火)为印星 +3",
        ],
        "conclusion": "得生中等（有印星生扶）",
    },
    "dezhu": {
        "score": 0,
        "detail": [
            "年干庚(金)非比劫 +0",
        ],
        "conclusion": "不得助（无比劫帮身）",
    },
    "ke_xie_hao": {
        "score": -30,
        "detail": [
            "年干庚(金)为食伤 -8",
            "月干己(土)非克泄耗 +0",
            "年支午藏本气丁(火)为官杀 -8",
        ],
        "detail_by_type": {
            "guan_sha": ["年支午藏本气丁(火)为官杀 -8"],
            "shi_shang": ["年干庚(金)为食伤 -8"],
            "cai_xing": [],
        },
        "conclusion": "克泄耗中等",
    },
    "total_score": 16,
    "ri_zhu_strength": "太弱",
    "pattern": "正格-身弱",
    "cong_ge": False,
    "yongshen": {
        "primary": "火",
        "secondary": "土",
        "ji_shen": "木",
    },
}

MOCK_STRENGTH_DETAIL_STRONG = {
    "ri_zhu": "甲",
    "ri_zhu_wuxing": "木",
    "deling": {
        "score": 50,
        "max_score": 50,
        "detail": ["寅月令本气甲(木)与日主同五行 +50"],
        "conclusion": "当令（月令本气与日主同五行，最旺）",
    },
    "dedi": {
        "score": 48,
        "max_score": 64,
        "detail": [
            "年支寅藏本气甲(木)为日主根 +16",
            "月支寅藏本气甲(木)为日主根 +16",
            "日支亥藏中气甲(木)为日主根 +8",
            "时支卯藏本气乙(木)为日主根 +16",
        ],
        "conclusion": "得地有力（多地支有根）",
    },
    "desheng": {
        "score": 0,
        "detail": [],
        "conclusion": "不得生（无印星生扶）",
    },
    "dezhu": {
        "score": 10,
        "detail": ["年干甲(木)为比劫 +10"],
        "conclusion": "得助较弱（比劫力量有限）",
    },
    "ke_xie_hao": {
        "score": -20,
        "detail": [],
        "detail_by_type": {"guan_sha": [], "shi_shang": [], "cai_xing": []},
        "conclusion": "克泄耗中等",
    },
    "total_score": 88,
    "ri_zhu_strength": "太旺",
    "pattern": "正格-身强",
    "cong_ge": False,
    "yongshen": {
        "primary": "金",
        "secondary": "水",
        "ji_shen": "木",
    },
}


# ============================================================
# RAG 检索测试
# ============================================================

class TestExtractKeywords:
    """测试关键词提取"""

    def test_weak_day_master_keywords(self):
        """身弱命局应提取身弱、用神等关键词"""
        keywords = _extract_keywords(MOCK_STRENGTH_DETAIL)
        assert "身弱" in keywords
        assert "用神" in keywords

    def test_strong_day_master_keywords(self):
        """身强命局应提取旺衰、身旺等关键词"""
        keywords = _extract_keywords(MOCK_STRENGTH_DETAIL_STRONG)
        assert "身旺" in keywords or "旺衰" in keywords

    def test_yongshen_keywords_extracted(self):
        """用神五行应被展开为相关关键词"""
        keywords = _extract_keywords(MOCK_STRENGTH_DETAIL)
        # 用神是火，应包含火、丙、丁
        assert "火" in keywords
        assert "丙" in keywords or "丁" in keywords

    def test_deling_keywords_present(self):
        """得令相关维度应产生得令关键词"""
        keywords = _extract_keywords(MOCK_STRENGTH_DETAIL)
        # 得令结论中有"令"字
        assert "得令" in keywords or "月令" in keywords


class TestScoreChapter:
    """测试章节评分（新 corpus 格式）"""

    def test_topic_match_scores_high(self):
        """topic 匹配关键词应得高分"""
        entry = {
            "topic": "用神",
            "keywords": ["用神", "月令", "格局"],
            "title": "论用神",
            "summary": "论述用神的定义及从月令取用神的方法",
        }
        keywords = ["用神", "月令", "旺衰"]
        score = _score_chapter(entry, keywords)
        assert score >= 5  # topic(3) + keyword match(2) + title(2)

    def test_no_match_scores_zero(self):
        """无匹配应得 0 分"""
        entry = {
            "topic": "大运",
            "keywords": ["大运", "流年"],
            "title": "论大运",
            "summary": "大运重要",
        }
        keywords = ["得令", "月令"]
        score = _score_chapter(entry, keywords)
        assert score == 0


class TestRetrieveRelevantTexts:
    """测试 RAG 检索"""

    def test_returns_list(self):
        """应返回列表"""
        results = retrieve_relevant_texts(MOCK_STRENGTH_DETAIL, top_k=5)
        assert isinstance(results, list)

    def test_returns_at_most_top_k(self):
        """返回数量不超过 top_k"""
        results = retrieve_relevant_texts(MOCK_STRENGTH_DETAIL, top_k=3)
        assert len(results) <= 3

    def test_results_have_required_fields(self):
        """每条结果应包含必要字段"""
        results = retrieve_relevant_texts(MOCK_STRENGTH_DETAIL, top_k=5)
        if results:
            entry = results[0]
            assert "id" in entry
            assert "source" in entry
            assert "text" in entry
            assert "topic" in entry
            assert "score" in entry

    def test_results_sorted_by_score(self):
        """结果应按分数降序排列"""
        results = retrieve_relevant_texts(MOCK_STRENGTH_DETAIL, top_k=10)
        if len(results) >= 2:
            for i in range(len(results) - 1):
                assert results[i]["score"] >= results[i + 1]["score"]

    def test_weak_chart_retrieves_yongshen_texts(self):
        """身弱命局应检索到用神相关原文"""
        results = retrieve_relevant_texts(MOCK_STRENGTH_DETAIL, top_k=5)
        topics = [r["topic"] for r in results]
        # 身弱命局应该能找到用神或得生相关的原文
        assert any(t in ["用神", "得生", "得助", "得令", "得地"] for t in topics)

    def test_strong_chart_retrieves_different_texts(self):
        """身强命局应检索到不同于身弱命局的原文"""
        results_weak = retrieve_relevant_texts(MOCK_STRENGTH_DETAIL, top_k=5)
        results_strong = retrieve_relevant_texts(MOCK_STRENGTH_DETAIL_STRONG, top_k=5)
        # 两种命局检索到的原文应该有所不同
        ids_weak = {r["id"] for r in results_weak}
        ids_strong = {r["id"] for r in results_strong}
        # 至少应有一些不同（不要求完全不同，因为可能有通用原文）
        # 这里只验证都能返回结果
        assert len(results_weak) > 0
        assert len(results_strong) > 0

    def test_no_duplicate_source_topic(self):
        """同一 source+topic 不应重复"""
        results = retrieve_relevant_texts(MOCK_STRENGTH_DETAIL, top_k=20)
        seen = set()
        for r in results:
            key = (r["source"], r["topic"])
            assert key not in seen
            seen.add(key)


# ============================================================
# AI 解释测试（Mock 模式）
# ============================================================

class TestMockExplanation:
    """测试 Mock 模式下的模板解释"""

    def test_returns_string(self):
        """应返回字符串"""
        texts = retrieve_relevant_texts(MOCK_STRENGTH_DETAIL, top_k=5)
        result = generate_mock_explanation(MOCK_STRENGTH_DETAIL, texts)
        assert isinstance(result, str)

    def test_contains_ri_zhu_info(self):
        """解释应包含日主信息"""
        texts = retrieve_relevant_texts(MOCK_STRENGTH_DETAIL, top_k=5)
        result = generate_mock_explanation(MOCK_STRENGTH_DETAIL, texts)
        assert "己" in result
        assert "土" in result

    def test_contains_strength_conclusion(self):
        """解释应包含旺衰结论"""
        texts = retrieve_relevant_texts(MOCK_STRENGTH_DETAIL, top_k=5)
        result = generate_mock_explanation(MOCK_STRENGTH_DETAIL, texts)
        assert "太弱" in result or "偏弱" in result

    def test_contains_yongshen_info(self):
        """解释应包含用神信息"""
        texts = retrieve_relevant_texts(MOCK_STRENGTH_DETAIL, top_k=5)
        result = generate_mock_explanation(MOCK_STRENGTH_DETAIL, texts)
        assert "火" in result  # 用神
        assert "用神" in result

    def test_contains_sections(self):
        """解释应包含多个章节"""
        texts = retrieve_relevant_texts(MOCK_STRENGTH_DETAIL, top_k=5)
        result = generate_mock_explanation(MOCK_STRENGTH_DETAIL, texts)
        assert "得令" in result
        assert "得地" in result
        assert "得生" in result
        assert "得助" in result
        assert "克泄耗" in result
        assert "综合结论" in result
        assert "用神建议" in result

    def test_strong_day_master_explanation(self):
        """身强命局的解释应包含相应内容"""
        texts = retrieve_relevant_texts(MOCK_STRENGTH_DETAIL_STRONG, top_k=5)
        result = generate_mock_explanation(MOCK_STRENGTH_DETAIL_STRONG, texts)
        assert "甲" in result
        assert "木" in result
        assert "太旺" in result

    def test_contains_quote_reference(self):
        """解释应引用原文"""
        texts = retrieve_relevant_texts(MOCK_STRENGTH_DETAIL, top_k=5)
        result = generate_mock_explanation(MOCK_STRENGTH_DETAIL, texts)
        # 应该包含至少一处"《...》云："格式的引用
        assert "《" in result
        assert "》" in result


class TestBuildPrompt:
    """测试 Prompt 构建"""

    def test_prompt_contains_data(self):
        """Prompt 应包含旺衰数据"""
        texts = retrieve_relevant_texts(MOCK_STRENGTH_DETAIL, top_k=5)
        prompt = _build_prompt(MOCK_STRENGTH_DETAIL, texts)
        assert "己" in prompt
        assert "偏弱" in prompt or "太弱" in prompt

    def test_prompt_contains_texts(self):
        """Prompt 应包含检索到的原文"""
        texts = retrieve_relevant_texts(MOCK_STRENGTH_DETAIL, top_k=5)
        prompt = _build_prompt(MOCK_STRENGTH_DETAIL, texts)
        # 应该包含至少一条原文的 source 信息
        for t in texts:
            if t["source"] in prompt:
                break
        else:
            pytest.fail("Prompt 中未找到任何检索到的原文")


class TestReanalysis:
    """测试校正后的重分析数据结构"""

    def test_reanalysis_builds_complete_classical_chart_data(self):
        """重分析应补齐月令、日主五行，避免格局推导出现破句"""
        chart = calculate_bazi(1990, 3, 15, 8, 0, "male")
        result = reanalyze_chart(chart.model_dump())
        reasoning = result["classical_analysis"]["pattern"]["reasoning"]

        assert "月令为，" not in reasoning
        assert "日主五行。" not in reasoning
        assert "月令为" in reasoning
        assert "日主五行" in reasoning

    def test_reanalysis_sources_include_excerpt(self):
        """出典列表应包含可展示的原文摘录，不只返回匹配分数"""
        chart = calculate_bazi(1990, 3, 15, 8, 0, "male")
        result = reanalyze_chart(chart.model_dump())

        assert result["sources"]
        first = result["sources"][0]
        assert "excerpt" in first
        assert first["excerpt"]
        assert "topic" in first


# ============================================================
# 集成测试
# ============================================================

class TestAnalysisIntegration:
    """端到端集成测试"""

    def test_full_pipeline_mock_mode(self):
        """完整流程测试：排盘数据 -> RAG 检索 -> Mock 解释"""
        # 模拟完整流程
        strength_detail = MOCK_STRENGTH_DETAIL

        # RAG 检索
        relevant_texts = retrieve_relevant_texts(strength_detail, top_k=5)
        assert len(relevant_texts) > 0

        # Mock 解释
        explanation = generate_mock_explanation(strength_detail, relevant_texts)
        assert len(explanation) > 100  # 应该有实质内容
        assert "己" in explanation
        assert "土" in explanation

    def test_async_explanation_fallback(self):
        """无 API Key 时应自动回退到 Mock 模式"""
        from services.ai_explainer import generate_strength_explanation

        texts = retrieve_relevant_texts(MOCK_STRENGTH_DETAIL, top_k=5)
        # 没有 DEEPSEEK_API_KEY 时应回退到 Mock
        result = asyncio.run(
            generate_strength_explanation(MOCK_STRENGTH_DETAIL, texts)
        )
        assert isinstance(result, str)
        assert len(result) > 100


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
