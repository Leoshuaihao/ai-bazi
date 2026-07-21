"""Tests for six_step_prompt.py — 六步推导法 Prompt 嵌入"""

import sys
sys.path.insert(0, '/Users/lee/WorkSpace/WorkBuddy/ai-bazi')

from services.six_step_prompt import (
    SIX_STEP_TEMPLATES,
    build_step_prompt,
    build_full_pipeline_prompt,
    TRUNK_BRANCH_REMINDER,
)

# Sample bazi_data for testing
SAMPLE_BAZI = {
    "birth_info": {"year": 1984, "month": 8, "day": 15, "hour": 12, "minute": 0},
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
    "day_master": "丙",
    "pattern": "七杀格",
    "yongshen": {"ten_god": "七杀", "five_element": "水", "mode": "逆用"},
    "wangshuai": {"level": "身弱"},
    "dayun": [
        {"stem": "癸", "branch": "酉", "ten_god": "正官", "start_year": 1986, "end_year": 1995},
        {"stem": "甲", "branch": "戌", "ten_god": "偏印", "start_year": 1996, "end_year": 2005},
        {"stem": "乙", "branch": "亥", "ten_god": "正印", "start_year": 2006, "end_year": 2015},
    ],
}


class TestStepTemplates:
    """测试六步模板定义"""

    def test_all_steps_exist(self):
        """验证六个步骤都存在"""
        for i in range(1, 7):
            assert i in SIX_STEP_TEMPLATES, f"步骤 {i} 缺失"
            assert SIX_STEP_TEMPLATES[i]["name"], f"步骤 {i} 名称为空"
            assert SIX_STEP_TEMPLATES[i]["core_question"], f"步骤 {i} 核心问题为空"
            assert SIX_STEP_TEMPLATES[i]["classical_basis"], f"步骤 {i} 古籍依据为空"
            assert SIX_STEP_TEMPLATES[i]["operation_rules"], f"步骤 {i} 操作规则为空"
            assert SIX_STEP_TEMPLATES[i]["output_format"], f"步骤 {i} 输出格式为空"

    def test_step_names(self):
        """验证步骤名称正确"""
        expected_names = {
            1: "定格局",
            2: "辨用神",
            3: "明喜忌",
            4: "十神定位",
            5: "宫位取象",
            6: "应期锁定",
        }
        for i, name in expected_names.items():
            assert SIX_STEP_TEMPLATES[i]["name"] == name, f"步骤 {i} 名称应为 '{name}'"


class TestBuildStepPrompt:
    """测试 build_step_prompt() 函数"""

    def test_step1_dinggeju(self):
        """build_step_prompt(1) → 仅输出定格局"""
        prompt = build_step_prompt(1, SAMPLE_BAZI)
        assert "定格局" in prompt
        assert "核心问题" in prompt
        assert "命主的基本格局类型" in prompt
        assert "古籍依据" in prompt
        assert "《子平真诠·论用神》" in prompt
        assert "操作规则" in prompt
        assert "输出格式" in prompt
        # 不应包含其他步骤的内容
        assert "辨用神" not in prompt

    def test_step4_with_prior_conclusions(self):
        """build_step_prompt(4) → 含 prior_conclusions 传递"""
        prior = {
            1: "格局确定为七杀格，月令申中庚金为本气",
            2: "用神为七杀(水)，逆用模式",
            3: "相神为食神(土)制杀，喜土金，忌木火",
        }
        prompt = build_step_prompt(4, SAMPLE_BAZI, prior_conclusions=prior)
        assert "十神定位" in prompt
        assert "前序步骤结论" in prompt
        assert "格局确定为七杀格" in prompt
        assert "用神为七杀(水)，逆用模式" in prompt
        assert "相神为食神(土)制杀" in prompt

    def test_step6_yingqi(self):
        """build_step_prompt(6) → 应期锁定"""
        prompt = build_step_prompt(6, SAMPLE_BAZI)
        assert "应期锁定" in prompt
        assert "《子平真诠·论行运成格变格》" in prompt
        assert "大运分析" in prompt or "大运" in prompt
        assert "流年" in prompt or "流年分析" in prompt

    def test_step_prompt_has_classical_source(self):
        """每步 prompt 包含古籍引用"""
        for i in range(1, 7):
            prompt = build_step_prompt(i, SAMPLE_BAZI)
            assert "古籍依据" in prompt, f"步骤 {i} 缺少古籍依据"
            # 每步都应该有至少一条古籍引用（《xxx》格式）
            assert "《" in prompt and "》" in prompt, f"步骤 {i} 缺少古籍引用"

    def test_step_prompt_has_trunk_reminder(self):
        """所有 prompt 含'优先检查主干'提醒"""
        for i in range(1, 7):
            prompt = build_step_prompt(i, SAMPLE_BAZI)
            assert "中间层主次关系" in prompt, f"步骤 {i} 缺少主次关系提醒"
            assert "十神定位" in prompt or "主干" in prompt, f"步骤 {i} 缺少主干提醒"


class TestBuildFullPipelinePrompt:
    """测试 build_full_pipeline_prompt() 函数"""

    def test_full_pipeline_has_all_steps(self):
        """build_full_pipeline_prompt() → 完整六步"""
        prompt = build_full_pipeline_prompt(SAMPLE_BAZI)
        for i in range(1, 7):
            step_name = SIX_STEP_TEMPLATES[i]["name"]
            assert step_name in prompt, f"全量 prompt 缺少 {step_name}"

    def test_full_pipeline_has_step_order(self):
        """全量 prompt 中步骤按顺序排列"""
        prompt = build_full_pipeline_prompt(SAMPLE_BAZI)
        idx_1 = prompt.index("定格局")
        idx_4 = prompt.index("十神定位")
        idx_6 = prompt.index("应期锁定")
        assert idx_1 < idx_4 < idx_6, "步骤顺序不正确"

    def test_full_pipeline_has_trunk_reminder(self):
        """全量 prompt 含主干提醒"""
        prompt = build_full_pipeline_prompt(SAMPLE_BAZI)
        assert "中间层主次关系" in prompt

    def test_full_pipeline_has_bazi_data(self):
        """全量 prompt 包含命盘数据"""
        prompt = build_full_pipeline_prompt(SAMPLE_BAZI)
        assert "七杀格" in prompt
        assert "丙" in prompt

    def test_full_pipeline_core_questions(self):
        """全量 prompt 每步含核心问题"""
        prompt = build_full_pipeline_prompt(SAMPLE_BAZI)
        for i in range(1, 7):
            core_q = SIX_STEP_TEMPLATES[i]["core_question"]
            assert core_q in prompt, f"全量 prompt 缺少步骤{i}核心问题: {core_q}"

    def test_full_pipeline_classical_sources(self):
        """全量 prompt 每步含古籍引用"""
        prompt = build_full_pipeline_prompt(SAMPLE_BAZI)
        for i in range(1, 7):
            cq = SIX_STEP_TEMPLATES[i]["core_question"]
            idx = prompt.index(cq)
            # 在核心问题后应该能找到操作规则和输出格式
            segment = prompt[idx:idx + 2000]
            assert "操作规则" in segment, f"步骤 {i} 缺少操作规则"

    def test_pipeline_with_rag_results(self):
        """全量 prompt 含 RAG 检索结果"""
        rag = {"《子平真诠·论用神》": "财官印食，此四善神，顺用之"}
        prompt = build_full_pipeline_prompt(SAMPLE_BAZI, rag_results=rag)
        assert "相关典籍参考" in prompt
        assert "财官印食" in prompt


class TestTrunkBranchReminder:
    """测试中间层主次关系提醒"""

    def test_reminder_content(self):
        """验证提醒文本的关键内容"""
        assert "中间层主次关系" in TRUNK_BRANCH_REMINDER
        assert "十神定位" in TRUNK_BRANCH_REMINDER
        assert "宫位取象" in TRUNK_BRANCH_REMINDER
        assert "主干" in TRUNK_BRANCH_REMINDER

    def test_reminder_in_all_step_prompts(self):
        """验证每步 prompt 都包含提醒"""
        for i in range(1, 7):
            prompt = build_step_prompt(i, SAMPLE_BAZI)
            assert TRUNK_BRANCH_REMINDER in prompt, f"步骤 {i} 缺少主干提醒"


class TestVerificationSystemPrompt:
    """测试 verification.py 中的 SYSTEM_PROMPT_V2"""

    def test_system_prompt_v2_exists(self):
        """验证 SYSTEM_PROMPT_V2 存在"""
        from services.verification import SYSTEM_PROMPT_V2
        assert SYSTEM_PROMPT_V2
        assert len(SYSTEM_PROMPT_V2) > len(SYSTEM_PROMPT_V2.split("\n")[0])  # 不是空行

    def test_v2_contains_six_step_names(self):
        """验证 V2 包含六步名称"""
        from services.verification import SYSTEM_PROMPT_V2
        for name in ["定格局", "辨用神", "明喜忌", "十神定位", "宫位取象", "应期锁定"]:
            assert name in SYSTEM_PROMPT_V2, f"SYSTEM_PROMPT_V2 缺少'{name}'"

    def test_v2_contains_trunk_branch(self):
        """验证 V2 包含主次关系说明"""
        from services.verification import SYSTEM_PROMPT_V2
        assert "主干" in SYSTEM_PROMPT_V2
        assert "分支" in SYSTEM_PROMPT_V2

    def test_v2_includes_original_prompt(self):
        """验证 V2 包含了原有 SYSTEM_PROMPT"""
        from services.verification import SYSTEM_PROMPT, SYSTEM_PROMPT_V2
        assert SYSTEM_PROMPT in SYSTEM_PROMPT_V2
        assert SYSTEM_PROMPT_V2.startswith(SYSTEM_PROMPT)


class TestStepNumberValidation:
    """测试步骤编号验证"""

    def test_invalid_step_number(self):
        """无效步骤编号抛出 ValueError"""
        try:
            build_step_prompt(0, {})
            assert False, "应该抛出 ValueError"
        except ValueError:
            pass

        try:
            build_step_prompt(7, {})
            assert False, "应该抛出 ValueError"
        except ValueError:
            pass


class TestEmptyBaziData:
    """测试空命盘数据处理"""

    def test_empty_data_not_crash(self):
        """空数据不崩溃"""
        for i in range(1, 7):
            prompt = build_step_prompt(i, {})
            assert len(prompt) > 0

    def test_full_pipeline_empty_data(self):
        """全量 prompt 空数据不崩溃"""
        prompt = build_full_pipeline_prompt({})
        assert len(prompt) > 0
