"""逐步验证收敛模块 V4 — LLM 100% 介入

V4核心: LLM驱动全流程对话, 不可用时降级到V3静态模式
"""

import os
import json
import uuid
import asyncio
from datetime import datetime

from rules.pattern import (
    determine_pattern_type,
    detect_ganzhi_touchu,
    detect_zhi_heju,
    resolve_pending_heju,
    judge_wangshuai_level,
    check_purity,
    _TG_TO_PATTERN,
    _resolve_five_element,
    _calc_ten_god,
    WUXING_MAP,
    # 格局派重构
    PATTERN_XIANGSHEN_RULES,
    JIUYING_TABLE,
    XIANGSHEN_DIMENSIONS,
    determine_yongshen,
    generate_xiangshen_candidates,
    check_chengbai,
    check_jiuying_v2,
    get_tiaohou_weight,
    get_fuyi_weight,
    judge_pattern_quality_v2,
    _get_xiangshen_question,
)
from services.deepseek_client import call_deepseek
from services.user_data import save_verification_session as _save_db_session
from services.user_data import load_verification_session as _load_db_session

# ============================================================
# SmartPredictionSelector 集成 — 用区分度评分驱动题目选取
# ============================================================

# 十神 → SmartPredictionSelector 类别映射
_TEN_GOD_TO_SMART_CATEGORY = {
    "正官": "事业",
    "七杀": "事业",
    "正财": "事业",
    "偏财": "事业",
    "正印": "学历",
    "偏印": "学历",
    "食神": "性格",
    "伤官": "性格",
    "比肩": "兄弟关",
    "劫财": "兄弟关",
}

# 诊断步骤 → SmartPredictionSelector 类别映射
_DIAG_STEP_TO_SMART_CATEGORY = {
    "D1": "关键年份",   # 月令被冲 → 人生突变年份
    "D2": "性格",       # 月令被合 → 双重性格
    "D3": "性格",       # 中气格局 → 性格特征不同
    "D4": "事业",       # 用神救应 → 潜力发挥
    "D5": "父母关",     # 时辰校验 → 与父母信息相关
}


def _smart_rerank_candidates(candidates, uncertainty, asked_list=None):
    """用 SmartPredictionSelector 对相神候选重新排序。

    在原有 confidence 排序基础上，叠加区分度评分作为加权因子，
    使得高区分度的候选优先被验证。

    不修改 SmartPredictionSelector 的评分逻辑，仅调用。
    """
    if not candidates:
        return candidates
    try:
        from services.predictions import SmartPredictionSelector
        selector = SmartPredictionSelector()
    except Exception:
        return candidates

    asked_set = set(asked_list or [])
    history = {
        "asked_counts": {},
        "supplement_streak": 0,
    }
    for c in candidates:
        tg = c.get("ten_god", "")
        if tg in asked_set:
            history["asked_counts"][_TEN_GOD_TO_SMART_CATEGORY.get(tg, "性格")] = \
                history["asked_counts"].get(_TEN_GOD_TO_SMART_CATEGORY.get(tg, "性格"), 0) + 1

    # 为每个候选计算区分度得分
    for c in candidates:
        tg = c.get("ten_god", "")
        category = _TEN_GOD_TO_SMART_CATEGORY.get(tg, "性格")
        score_info = selector.calculate_discrimination_score(
            {"category": category},
            uncertainty=uncertainty or {},
            history=history,
        )
        c["_smart_score"] = score_info["total"]

    # 综合排序：confidence (0-99) 权重 0.6 + smart_score (0-10)*10 权重 0.4
    candidates.sort(
        key=lambda x: x.get("confidence", 50) * 0.6 + x.get("_smart_score", 5) * 10 * 0.4,
        reverse=True,
    )
    return candidates


def _smart_rank_diag_steps(applicable_steps, uncertainty):
    """用 SmartPredictionSelector 对适用的诊断步骤重新排序。

    applicable_steps: list of step numbers (1-5) that are applicable
    Returns: reordered list of step numbers
    """
    if not applicable_steps or len(applicable_steps) <= 1:
        return applicable_steps
    try:
        from services.predictions import SmartPredictionSelector
        selector = SmartPredictionSelector()
    except Exception:
        return applicable_steps

    scored = []
    for step_num in applicable_steps:
        step_key = f"D{step_num}"
        category = _DIAG_STEP_TO_SMART_CATEGORY.get(step_key, "性格")
        score_info = selector.calculate_discrimination_score(
            {"category": category},
            uncertainty=uncertainty or {},
        )
        scored.append((step_num, score_info["total"]))

    scored.sort(key=lambda x: x[1], reverse=True)
    return [s[0] for s in scored]

# ============================================================
# LLM 系统提示词
# ============================================================

SYSTEM_PROMPT = """你是一位严格遵循《子平真诠》格局派体系的子平派命理师。

核心概念（格局派正统）：
- 用神 = 月令定格之物 = 格局本身（直接确定，不竞争）
- 相神 = 辅佐用神成格之物（顺用生护、逆用制化）
- 财官印食为四善神（财含正财偏财），顺用之（保护性使用：生之、护之）
- 杀伤枭刃为四恶神，逆用之（控制性使用：制之、化之）
- 调候法/扶抑法/通关法降级为加权因子，不独立生成候选

顺用配对（善神 → 相神角色）：
- 正官格 → 财生官(生用) + 印护官(护用)
- 正财格/偏财格 → 食伤生财(生用) + 官护财(护用)
- 正印格 → 官杀生印(生用) + 比劫护印(护用)
- 食神格 → 比劫生食(生用) + 财护食(泄用)

逆用配对（恶神 → 相神角色）：
- 七杀格 → 食神制杀(制用) + 印化杀(化用)
- 伤官格 → 印制伤官(制用) + 财泄伤官(泄用)
- 偏印格 → 财制偏印(制用)
- 月刃格 → 官杀制刃(制用)

相神六种角色：
- 生用：相神生用神（如财生官）
- 护用：相神保护用神不受克（如印护官）
- 制用：相神制约忌神（如食神制杀）
- 化用：相神转化凶神（如印化杀）
- 泄用：相神疏导旺气（如食伤泄秀）
- 顺势：相神顺应旺势（如从格顺势）

判断流程（不可颠倒）：
1. 月令定格 → 2. 用神确定 → 3. L1格局特征验证 → 4. 相神验证 → 5. 成败救应 → 6. 格局高低

成败救应：
- 成格：用神有力无破，相神配置齐全
- 败格：用神被克/混/合，需看是否有救应之神
- 救应：制忌之神存在且有力（透干有根=上等，透干无根=中等，暗藏=下等）

常见败因（按格局）：
- 正官格：伤官克官、官杀混杂、官星被合
- 正财格/偏财格：比劫夺财
- 正印格：财星破印
- 食神格：枭神夺食
- 七杀格：杀无制、财星党杀、制杀太过
- 伤官格：伤官无制、伤官见官（伤官伤尽不见官星则为贵格）
- 偏印格：枭神夺食、偏印无制
- 月刃格：阳刃无制、冲刃
- 建禄格：建禄无制
- 从弱格：印比扶身破从
- 专旺格：官杀犯旺

格局高低评判（有情×有力）：
- 有情：用神得生得助，有相神辅佐（如官格有财生印护）
- 有力：用神通根得地，气贯生旺（得月令+透干+有根气）
- 有情有力 = 上格，有情无力 = 中格，无情有力 = 中下格，无情无力 = 下格

用神变化：
- 月令本气不透→取中气余气定格（透干优先）
- 月令被冲→重新审视定格之物是否被破坏，另寻透干之物为用
- 透干变化：月令藏干透出不同则用神不同

天干五合对格局的影响：
- 甲己合土、乙庚合金、丙辛合水、丁壬合木、戊癸合火
- 用神被合（非日主自合）→败格，看合化后能否成新格
- 忌神被合→救应成格
- 日主自合财官→不为合去，不影响格局
- 合一留一→格局反清

重要典籍指引：
- 《子平真诠·论用神》：用神专求月令、顺用逆用规则
- 《子平真诠·论用神成败得失》：成败救应的完整论述
- 《子平真诠·论用神格局高低》：有情有力的评判框架
- 《子平真诠·论用神变化》：月令被合被冲后的格局变化
- 《穷通宝鉴》：调候用神（降级为加权因子）

规则:
1. 每条问题基于命盘数据和典籍理论
2. 用生活化语言，用户可能不理解命理术语
3. 用户有复杂真实情况，不要强迫选不合适选项
4. 用户持续否定时重新审视月令是否被冲/合/压制
5. 保持自然对话感"""


# 动态构建 V2 prompt：优先使用 six_step_prompt 结构化模板
_FALLBACK_V2_APPENDIX = """

## 六步推导框架

本系统采用《子平真诠》格局派六步推导法进行命盘分析：

1. **定格局** — 以月令提纲定格局类型（正格八格/从格/专旺/化气）
2. **辨用神** — 确定用神（=月令定格之物），判断顺用/逆用/顺势模式
3. **明喜忌** — 确定相神配置、喜忌五行、大运喜忌方向，检查成败救应
4. **十神定位** — 统计天干十神分布、地支根气、生克制化链条（主干，优先检查）
5. **宫位取象** — 年/月/日/时四柱对应的人事领域（分支，依赖前四步）
6. **应期锁定** — 大运成格变格效应 + 流年关键节点 + 应期推断

### 中间层主次关系

主干（优先检查）：**十神定位 + 生克制化** — 这是推导的核心，决定命局的主要趋势
分支（不过度纠缠）：**宫位取象 + 刑冲合害** — 在主干明确后展开，不纠缠分支细节

### 推导约束

- 用神专求月令，不可跨格局大类翻转
- 宫位取象必须以十神为根基，不可脱离十神单独宫位推事
- 大运效应标注"运过即止"
- 性格推断注意防范巴纳姆效应"""

try:
    from .six_step_prompt import build_full_pipeline_prompt
    _v2_prompt = build_full_pipeline_prompt({})
    SYSTEM_PROMPT_V2 = SYSTEM_PROMPT + "\n\n" + _v2_prompt
except ImportError:
    SYSTEM_PROMPT_V2 = SYSTEM_PROMPT + _FALLBACK_V2_APPENDIX


def _has_llm():
    return bool(os.getenv("DEEPSEEK_API_KEY"))


async def _llm_ask(system: str, prompt: str, max_tokens: int = 300) -> str | None:
    """调用 LLM，失败返回 None"""
    try:
        content = await call_deepseek(prompt=prompt, system_prompt=system,
                                       timeout=12, temperature=0.5, max_tokens=max_tokens)
        if content and not content.startswith("[API_"):
            return content
    except Exception:
        pass
    return None


# ============================================================
# L1 格局特征问题（V3升级：区分旺衰两版）
# ============================================================
PATTERN_L1_QUESTIONS = {
    "正官格": {
        "strong": {"question": "你工作中是否更倾向于在规则和秩序下发挥，不太喜欢冒险和自由发挥？",
                   "explanation": "正官格身旺者重视规则带来的安全感和成就。",
                   "pattern_feature": "官星当令，为人正直守法，重名节讲信用"},
        "weak": {"question": "你是否在工作中感到规则和制度对你有较大的约束，想突破又常常被拉回来？",
                 "explanation": "正官格身弱者容易被外界制度压制，需要身旺方能承载官贵。",
                 "pattern_feature": "官星当令但日主偏弱，制度感强但承载吃力"},
    },
    "七杀格": {
        "strong": {"question": "你人生中是否经历过较大的压力或挑战，但事后回头看，那些压力反而促成了你的成长？",
                   "explanation": "七杀格身旺者把压力当跳板，愈挫愈勇。",
                   "pattern_feature": "七杀当令身旺，有魄力敢担当，经历磨难后成长"},
        "weak": {"question": "你是否长期承受比较大的压力或制约，感觉自己被压得比较紧，很多事想做但力不从心？",
                 "explanation": "七杀格身弱者杀星攻身，需要印星化杀或食神制杀来缓解。",
                 "pattern_feature": "七杀当令但日主偏弱，杀旺攻身，需制化方显其功"},
    },
    "正财格": {
        "strong": {"question": "你对机会特别是赚钱机会的嗅觉是否敏锐，做事务实注重结果？",
                   "explanation": "正财格身旺者能驾驭财富，务实稳重。",
                   "pattern_feature": "财星当令身旺，务实稳重，善于理财和把握机会"},
        "weak": {"question": "你是否对赚钱机会很在意，但常常感觉自己抓不住、或者机会来了又错过了？",
                 "explanation": "正财格身弱者财多身弱，能看见但难抓住。",
                 "pattern_feature": "财星当令但日主偏弱，财多身弱，需比劫分财或印星扶持"},
    },
    "偏财格": {
        "strong": {"question": "你是否属于那种直觉很强、做事不拘一格、善于抓住稍纵即逝机会的类型？",
                   "explanation": "偏财格身旺者灵活善变，善于抓住商业机会。",
                   "pattern_feature": "偏财当令身旺，灵活变通，善抓机会"},
        "weak": {"question": "你是否经常有一些好想法或看到好机会，但落地执行的时候却总是差一口气？",
                 "explanation": "偏财格身弱者想法多变但执行力跟不上。",
                 "pattern_feature": "偏财当令但日主偏弱，机会多而承载难"},
    },
    "正印格": {
        "strong": {"question": "你是否从小就受长辈喜爱，学习能力较强，愿意花时间深入钻研一件事？",
                   "explanation": "正印格身旺者贵人运好，学有所成。",
                   "pattern_feature": "印星当令身旺，爱学习有贵人，性格温和良善"},
        "weak": {"question": "你是否渴望有好的引路人来指点自己，但总觉得遇到的人帮助力度不够、或者一直没有遇到对的人？",
                 "explanation": "正印格身弱者需要印生扶但印星无力，求学之路多波折。",
                 "pattern_feature": "印星当令但日主偏弱，贵人助力有但不够"},
    },
    "偏印格": {
        "strong": {"question": "你是否对某些特定领域有超乎常人的钻研精神，但容易沉浸在自己的世界里？",
                   "explanation": "偏印格身旺者偏才突出，思维独特。",
                   "pattern_feature": "偏印当令身旺，思维独特，偏才突出"},
        "weak": {"question": "你是否对某个领域有深入兴趣，但感觉外界不太理解你、或者你的想法很难得到认可？",
                 "explanation": "偏印格身弱者才华有但被埋没的感觉较强。",
                 "pattern_feature": "偏印当令但日主偏弱，独特才华难被认可"},
    },
    "食神格": {
        "strong": {"question": "你的才华创意在生活或工作中是否占据了重要位置，常有人夸你有才华？",
                   "explanation": "食神格身旺者创造力和艺术感自然流露。",
                   "pattern_feature": "食神当令身旺，有才华创造力，性格温和乐观"},
        "weak": {"question": "你是否内心其实有很多才华和想法，但总觉得表达出来或者把它们变成实际的东西比较困难？",
                 "explanation": "食神格身弱者才华内秀但输出困难。",
                 "pattern_feature": "食神当令但日主偏弱，才华内秀而输出不足"},
    },
    "伤官格": {
        "strong": {"question": "你是否属于想法很多、不喜被约束、常有出人意料的好点子的人？",
                   "explanation": "伤官格身旺者思维敏捷，锋芒毕露。",
                   "pattern_feature": "伤官当令身旺，聪明敏捷，创造力强但有时锋芒太露"},
        "weak": {"question": "你是否有很多想法但常常被人否定或环境不允许你做出来，导致内心比较压抑？",
                 "explanation": "伤官格身弱者才华被压，容易愤世嫉俗。",
                 "pattern_feature": "伤官当令但日主偏弱，想法多而施展难"},
    },
    "从弱格": {
        "strong": {"question": "你是否感觉自己的人生很多时候是被环境推着走，但反而顺势而为的时候结果更好？",
                   "explanation": "从弱格的人不宜独立抗衡，顺势而为反而能有不错的成就。",
                   "pattern_feature": "日主极弱，顺势从格，忌印比扶身"},
        "weak": {"question": "你是否感觉自己的人生很多时候是被环境推着走，但反而顺势而为的时候结果更好？",
                 "explanation": "从弱格本身为极弱，只有顺势版本。若身弱不从则需重新审视格局。",
                 "pattern_feature": "日主极弱，顺势从格；若不从则破格"},
    },
    "专旺格": {
        "strong": {"question": "你是否有一种强烈的自我意识和主见，做事情喜欢掌控全局而非被人安排？",
                   "explanation": "专旺格的人气势强盛，有领导力和主导欲，宜食伤泄秀。",
                   "pattern_feature": "日主极旺，气势强盛，宜泄不宜克"},
        "weak": {"question": "你是否有一种强烈的自我意识和主见，做事情喜欢掌控全局而非被人安排？",
                 "explanation": "专旺格本身为极旺，只有顺势版本。若有官杀犯旺则破格。",
                 "pattern_feature": "日主极旺，气势强盛；官杀犯旺则破格"},
    },
    "建禄格": {
        "strong": {"question": "你是否从小就有较强的自主意识和独立性，做事喜欢靠自己，不太依赖别人？",
                   "explanation": "建禄格身旺者自我意识强，独立自主，需官杀制或食伤泄方能成器。",
                   "pattern_feature": "月令为禄，日主乘旺，自主性强"},
        "weak": {"question": "你是否虽然独立性较强，但常常感觉一个人扛着很累，希望有好的机会或帮手来配合？",
                 "explanation": "建禄格身弱者虽自立但力有不逮，需印星扶身。",
                 "pattern_feature": "月令为禄但日主偏弱，自立而力不足"},
    },
    "月刃格": {
        "strong": {"question": "你是否性格刚强果断，做事有冲劲不怕竞争，但有时也会因为太刚而与人起冲突？",
                   "explanation": "月刃格身旺者刚强好胜，需官杀制刃方成大器。",
                   "pattern_feature": "月令为刃，刚强好胜，需制化方显其功"},
        "weak": {"question": "你是否性格中有刚硬的一面，但常常感觉压力和挫折让你难以充分发挥自己的能力？",
                 "explanation": "月刃格身弱者刚中带弱，需制刃且扶身。",
                 "pattern_feature": "月令为刃但日主偏弱，刚中有弱"},
    },
}


def _get_l1_question(pattern: str, wangshuai_level: str) -> dict:
    """根据旺衰选择L1问题版本"""
    entry = PATTERN_L1_QUESTIONS.get(pattern, PATTERN_L1_QUESTIONS.get("正官格", {}))
    is_strong = wangshuai_level in ("极旺", "身旺", "中和")
    if isinstance(entry, dict) and "strong" in entry:
        return entry["strong"] if is_strong else entry["weak"]
    return entry  # 兼容旧格式

# 诊断问题模板
DIAGNOSIS_QUESTIONS = {
    "D1_chong": "你是否觉得自己性格或人生方向发生过比较突然的转变？",
    "D2_he": "你是否在不同环境或人生阶段下，会表现出完全不同的性格特质？",
    "D4_jiuying": "你是否觉得自己有些潜力被某些因素限制住了，没有完全发挥出来？",
    "D5_time": "前面几个方向似乎都不太符合。你的出生时间是准确的吗？",
}

# 品质问题模板
QUALITY_QUESTIONS = {
    "youqing": {
        "食神": "在压力大的时候，你是否有某种宣泄或舒缓的方式——比如创作、运动，或者其他让你释放的渠道——来帮你把压力转化为动力？",
        "伤官": "在压力大的时候，你是否有某种宣泄或舒缓的方式——比如创作、运动，或者其他让你释放的渠道——来帮你把压力转化为动力？",
        "正印": "你是否容易得到长辈或老师的欣赏和帮助，让你在困难时有人指点？",
        "偏印": "你是否容易得到长辈或老师的欣赏和帮助，让你在困难时有人指点？",
        "比肩": "你是否经常能得到朋友或同事的实质性帮助？",
        "劫财": "你是否经常能得到朋友或同事的实质性帮助？",
        "正财": "你是否有稳定的财源或资源渠道来支撑你的发展？",
        "偏财": "你是否有稳定的财源或资源渠道来支撑你的发展？",
        "正官": "你是否有权威人士或制度在背后支持你的发展？",
        "七杀": "你是否有权威人士或制度在背后支持你的发展？",
    },
    "youli": {
        "食神": "你的才华或创造力是否在实际生活或工作中产生了比较实在的、别人能看到的成果——而不是只停留在想法或爱好层面？",
        "伤官": "你的才华或创造力是否在实际生活或工作中产生了比较实在的、别人能看到的成果——而不是只停留在想法或爱好层面？",
        "正印": "你的学习和积累是否转化为了实际的能力提升或职业发展？",
        "偏印": "你的学习和积累是否转化为了实际的能力提升或职业发展？",
        "比肩": "你的朋友或同伴对你的人生产生了实质性的积极影响吗？",
        "劫财": "你的朋友或同伴对你的人生产生了实质性的积极影响吗？",
        "正财": "你的理财能力是否给你带来了相当的财富积累？",
        "偏财": "你的理财能力是否给你带来了相当的财富积累？",
        "正官": "规则和秩序是否真正让你在事业上获得了进步？",
        "七杀": "规则和秩序是否真正让你在事业上获得了进步？",
    },
}


# ============================================================
# 会话管理
# ============================================================

_verification_sessions = {}
_SESSION_TTL_SECONDS = 1800


def _cleanup_expired_sessions():
    now = datetime.now().timestamp()
    expired = [sid for sid, s in _verification_sessions.items()
               if now - s.get("_created_at", 0) > _SESSION_TTL_SECONDS]
    for sid in expired:
        del _verification_sessions[sid]


_ANSWER_NORMALIZE = {
    "很像": "accurate", "有点出入": "partial", "完全不像": "inaccurate",
    "是的": "accurate", "不太确定": "partial", "不是": "inaccurate",
    "是": "accurate", "带头推动": "accurate", "偏向创作": "inaccurate",
    "不太好说": "partial", "务实重结果": "accurate", "重学习修养": "inaccurate",
    "有道理，让我补充": "accurate", "不对，换个方向": "inaccurate",
    "准确": "accurate", "不准": "inaccurate",
    "说说具体的": "custom",   # V4: 自由文本入口
}

# confidence 调整默认值（V3 静态模式用）
_DELTA_DEFAULTS = {
    "accurate": 15,
    "partial": 3,
    "inaccurate": -20,
}

# guardrail: LLM 建议的单轮 confidence 增量上限
_LLM_DELTA_MAX = 25


def _get_delta(session, answer, defaults=None):
    """获取 confidence 调整值

    混合框架核心：优先使用 LLM 建议的 delta（有 guardrail），
    否则用 defaults 中的固定值。

    - session: 验证会话（从中取出 _llm_delta 并消费）
    - answer: 归一化后的回答 (accurate/partial/inaccurate)
    - defaults: 自定义默认值字典，None 时用 _DELTA_DEFAULTS
    """
    llm_delta = session.pop("_llm_delta", None)
    if llm_delta is not None:
        try:
            return max(-_LLM_DELTA_MAX, min(_LLM_DELTA_MAX, int(llm_delta)))
        except (ValueError, TypeError):
            pass
    d = defaults or _DELTA_DEFAULTS
    return d.get(answer, 0)


def _get_quality_question(qtype: str, tg: str) -> str:
    return QUALITY_QUESTIONS.get(qtype, {}).get(tg,
           "请描述这个方面在你生活中的体现。")


# ============================================================
# init_verification (V3)
# ============================================================

def init_verification(chart_data: dict, user_id: str = None, uncertainty: dict = None) -> dict:
    _cleanup_expired_sessions()
    session_id = str(uuid.uuid4())

    dm_stem = _extract_dm_stem(chart_data)
    month_branch = _extract_month_branch(chart_data)
    strength_detail = chart_data.get("strength_detail") or {}

    # Step 1: 月令定格局
    pattern = determine_pattern_type(dm_stem, month_branch)
    step_results = {
        "pattern": pattern,
        "pattern_source": "月令本气",
    }

    # Step 2: 透干会支检查
    touchu = detect_ganzhi_touchu(chart_data)
    heju = detect_zhi_heju(chart_data, month_branch)

    step_results["gan_touchu"] = touchu
    step_results["zhi_heju"] = heju
    step_results["pending_change"] = {"is_pending": False, "candidate_pattern": None,
                                       "resolved": False, "resolved_to": None}

    if touchu["level"] in ("中气", "余气") and touchu["is_strong"]:
        new_pattern = _TG_TO_PATTERN.get(touchu["touched_ten_god"], "")
        if new_pattern and new_pattern != pattern:
            step_results["pattern"] = new_pattern
            step_results["pattern_source"] = "天干透出"

    if heju["pending"]:
        heju_pattern = _resolve_heju_pattern(dm_stem, heju["hua_wuxing"])
        if heju_pattern:
            step_results["pending_change"] = {
                "is_pending": True,
                "candidate_pattern": heju_pattern,
                "resolved": False,
                "resolved_to": None,
            }

    # Step 3: 旺衰五等
    wangshuai = judge_wangshuai_level(chart_data, strength_detail)
    step_results["wangshuai"] = wangshuai

    # Resolve pending heju
    if step_results["pending_change"]["is_pending"]:
        step_results = resolve_pending_heju(step_results, wangshuai["level"])

    # Step 4 (新增): 确定用神（=月令定格之物，直接确定，不竞争）
    final_pattern = step_results["pattern"]
    yongshen = determine_yongshen(final_pattern, dm_stem, month_branch, chart_data)
    step_results["yongshen"] = yongshen

    # Step 5 (新增): 生成相神候选（按顺用/逆用规则）
    xiangshen_candidates = generate_xiangshen_candidates(final_pattern, dm_stem, chart_data)
    step_results["xiangshen_candidates"] = xiangshen_candidates

    # L1 question (旺衰自适应)
    final_pattern = step_results["pattern"]
    l1 = _get_l1_question(final_pattern, wangshuai["level"])

    first_question = {
        "round": 1, "layer": "L1",
        "question": l1["question"],
        "explanation": l1.get("explanation", ""),
        "pattern_feature": l1.get("pattern_feature", ""),
        "target_pattern": final_pattern,
        "options": ["很像", "有点出入", "完全不像"],
    }

    session = {
        "session_id": session_id,
        "user_id": user_id,
        "chart_data": chart_data,
        "pattern": final_pattern,
        "step_results": step_results,
        "round": 1,
        "stage": "pattern",
        "sub_stage": "L1",
        "l1_answer": None,
        "confidence": abs(wangshuai["level"] == "极旺" and 25 or
                          wangshuai["level"] == "身旺" and 30 or
                          wangshuai["level"] == "中和" and 20 or
                          wangshuai["level"] == "身弱" and 25 or 20),
        "quality": None,
        "purity": "纯",  # 默认纯，仅在纯杂检查后可能改为"杂"
        "quality_youqing": None,
        "quality_youli": None,
        "diagnosis_count": 0,
        "diagnosis_sub_stage": 1,
        "diagnosis_path": [],
        # 格局派重构：用神/相神/成败救应
        "yongshen": yongshen,  # 用神 = 月令定格之物（直接确定）
        "xiangshen_candidates": xiangshen_candidates,  # 相神候选列表
        "confirmed_xiangshen": None,  # 验证后确认的相神
        "chengbai_result": None,  # 成败检测结果
        "jiuying_result": None,  # 救应检测结果
        "chengbai_status": None,  # 成格/败格有救/败格无救
        "history": [],
        "current_question": first_question,
        "_created_at": datetime.now().timestamp(),
        # SmartPredictionSelector 集成：存储不确定性报告供后续选题使用
        "uncertainty": uncertainty,
    }

    # 不确定性驱动的初始置信度调整
    if uncertainty:
        overall_risk = uncertainty.get("overall_risk", 0.0)
        if overall_risk > 0.6:
            session["confidence"] = max(10, session["confidence"] - 10)
        elif overall_risk > 0.3:
            session["confidence"] = max(15, session["confidence"] - 5)

    _verification_sessions[session_id] = session

    if user_id:
        try:
            asyncio.ensure_future(_save_db_session(session))
        except Exception:
            pass

    return {
        "session_id": session_id,
        "stage": "pattern",
        "sub_stage": "L1",
        "question": first_question,
        "step_results": {
            "pattern": final_pattern,
            "pattern_source": step_results["pattern_source"],
            "gan_touchu": touchu,
            "wangshuai_level": wangshuai["level"],
        },
    }


def _resolve_heju_pattern(dm_stem, hua_wx):
    """根据化神五行和日主天干推断合化后的格局"""
    tg = _resolve_five_element(dm_stem, "比肩", "")
    return None  # 简化处理：由 AI 生成问题时间接处理


# ============================================================
# process_verification (V3)
# ============================================================

async def process_verification(session_id: str, answer: str, note: str = "") -> dict:
    answer = _ANSWER_NORMALIZE.get(answer, answer)

    _cleanup_expired_sessions()
    session = _verification_sessions.get(session_id)
    if not session:
        return {"error": "会话不存在或已过期"}

    cq = session.get("current_question", {})

    session["history"].append({
        "round": session["round"],
        "stage": session.get("stage"),
        "sub_stage": session.get("sub_stage"),
        "question": cq.get("question", ""),
        "answer": answer,
        "note": note,
    })

    # === 混合框架：静态管流程，LLM 管内容 ===

    # 1. LLM 解读自由文本（如有）→ 得到 mapped_answer + delta
    if _has_llm() and note:
        llm_result = await _llm_interpret(session, answer, note)
        if llm_result:
            answer = llm_result.get("mapped_answer", answer)
            session["_llm_delta"] = llm_result.get("delta", 0)
            if llm_result.get("extracted_facts"):
                session.setdefault("_llm_facts", []).extend(llm_result["extracted_facts"])
        else:
            # LLM 解读失败 → 降级为 partial（中间值，不偏不倚）
            answer = "partial"

    # 2. 静态 handler 执行（流程控制 — 永远执行）
    #    confidence 调整、收敛检查、阶段推进都在这里
    sub = session.get("sub_stage", "L1")
    result = await _dispatch_static(session, sub, answer)

    # 3. 清理 LLM 临时数据（delta 已被 handler 消费）
    session.pop("_llm_delta", None)

    # 4. LLM 增强问题内容（只改文本，不控制流程）
    if _has_llm() and result and not result.get("locked"):
        question = result.get("question")
        if question and not question.get("llm_generated"):
            enhanced = await _llm_enhance_question(session, result)
            if enhanced:
                result["question"] = enhanced
                session["current_question"] = enhanced

    return result


async def _llm_interpret(session, answer, note):
    """LLM 解读用户自由文本回答 — 返回 mapped_answer + delta

    混合框架：LLM 只负责解读，不控制流程。
    delta 是对当前被验证对象（格局/相神）的信心调整建议。
    """
    facts = session.get("_llm_facts", [])
    history = _format_chat_history(session)
    pattern = session.get("pattern", "")
    wangshuai = session.get("step_results", {}).get("wangshuai", {})
    cq = session.get("current_question", {})
    sub = session.get("sub_stage", "L1")
    yongshen = session.get("yongshen", {})

    # 相神阶段传入候选列表
    candidates_info = ""
    if sub.startswith("xs_"):
        cands = session.get("xiangshen_candidates", [])
        target = cq.get("target_xiangshen", "")
        candidates_info = "\n".join([
            f"- {c['ten_god']}({c['five_element']}): confidence={c['confidence']}, way={c.get('gong_way','')}"
            + (" ← 当前验证" if c['ten_god'] == target else "")
            for c in cands[:5]
        ])

    ys_info = f"用神={yongshen.get('ten_god','')}({yongshen.get('five_element','')}), 模式={yongshen.get('mode','')}" if yongshen else ""

    # 动态典籍检索（与 _llm_enhance_question 共享同一逻辑）
    classical = _get_classical_reference(session, sub)

    candidates_line = f"当前相神候选:\n{candidates_info}" if candidates_info else ""
    prompt = f"""用户八字: {pattern}格, 旺衰={wangshuai.get('level','?')}
{f"用神: {ys_info}" if ys_info else ""}
当前阶段: {sub}
{candidates_line}

典籍参考:
{classical}

对话历史:
{history}

你刚才问的问题: {cq.get('question','')}
用户回答: {answer}
用户补充说明: {note}

已知事实: {', '.join(facts) if facts else '无'}

请基于典籍理论解读用户回答，输出JSON(不要markdown标记):
{{"mapped_answer":"accurate|partial|inaccurate","delta":-25到25的整数,"extracted_facts":[""],"internal":"你的命理分析"}}

delta含义:
- 正数=用户回答支持当前方向（+25=强烈支持, +15=支持, +5=微弱支持）
- 负数=用户回答否定当前方向（-25=强烈否定, -15=否定, -5=微弱否定）
- 0=不确定或中立

注意: delta是对当前被验证的相神/格局的信心调整值。"""
    content = await _llm_ask(SYSTEM_PROMPT, prompt, 250)
    if not content:
        return None
    try:
        result = json.loads(content)
        try:
            result["delta"] = int(result.get("delta", 0))
        except (ValueError, TypeError):
            result["delta"] = 0
        return result
    except Exception:
        return {"mapped_answer": answer, "delta": 0, "extracted_facts": [note]}


async def _llm_enhance_question(session, result):
    """LLM 增强问题内容 — 只生成文本，不控制流程

    混合框架：静态 handler 已经生成了问题和推进了阶段，
    LLM 在此基础上改写问题文本和选项，使其更自然。
    LLM 永远不返回 action，不决定何时推进。
    """
    question = result.get("question", {})
    if not question:
        return None

    sub = session.get("sub_stage", "L1")

    # 某些阶段不增强（末轮/时辰校验等用静态即可）
    if sub in ("diag_D5", "quality_2"):
        return None

    history = _format_chat_history(session)
    sr = session.get("step_results", {})
    wangshuai = sr.get("wangshuai", {})
    pattern = session.get("pattern", "")
    classical = _get_classical_reference(session, sub)
    yongshen = session.get("yongshen", {})

    # 相神阶段传入候选列表
    candidates_info = ""
    if sub.startswith("xs_"):
        cands = session.get("xiangshen_candidates", [])
        target = question.get("target_xiangshen", "")
        candidates_info = "\n".join([
            f"- {c['ten_god']}({c['five_element']}): confidence={c['confidence']}, way={c.get('gong_way','')}"
            + (" ← 当前验证" if c['ten_god'] == target else "")
            for c in cands[:5]
        ])

    static_question = question.get("question", "")
    static_options = question.get("options", [])

    candidates_line = f"当前候选:\n{candidates_info}" if candidates_info else ""
    prompt = f"""你正在验证一个八字命盘。

命盘: {pattern}格, 日主{session['chart_data'].get('day_master','')}, 旺衰={wangshuai.get('level','?')}(方向={wangshuai.get('yongshen_direction','')})
透干: {sr.get('gan_touchu',{})}

典籍参考:
{classical}

对话历史:
{history}

当前阶段: {sub}
{candidates_line}

静态模板问题: {static_question}
静态模板选项: {static_options}

请基于以上信息，用生活化语言改写问题（不含命理术语），让用户更容易理解。
输出JSON(不要markdown标记):
{{"question":"你的问题","options":["选项1","选项2","选项3"],"explanation":"简短解释"}}

规则:
- 问题必须用生活化语言，不含命理术语
- 选项应该是用户容易理解的日常表达
- 可以增加"说说具体的"作为自由文本入口选项
- 保持自然对话感"""
    content = await _llm_ask(SYSTEM_PROMPT, prompt, 300)
    if not content:
        return None
    try:
        llm = json.loads(content)
        enhanced = dict(question)
        enhanced["question"] = llm.get("question", static_question)
        enhanced["options"] = llm.get("options", static_options)
        enhanced["explanation"] = llm.get("explanation", question.get("explanation", ""))
        enhanced["llm_generated"] = True
        return enhanced
    except Exception:
        return None


def _clean_classical_text(text: str) -> str:
    """清理典籍文本中的噪音：DB元数据、现代摘要、多余空行"""
    import re
    # 去掉 "## 核心要点" 及之后的所有内容（现代摘要，非古籍原文，AI会误引）
    text = re.sub(r'\n## 核心要点.*', '', text, flags=re.DOTALL)
    # 去掉 DB 元数据尾注
    text = re.sub(r'\n---\n版本：.*', '', text, flags=re.DOTALL)
    text = re.sub(r'\n录入日期：.*', '', text)
    text = re.sub(r'\n用途：RAG检索.*', '', text)
    # 压缩连续空行
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _get_classical_reference(session, stage: str = "pattern") -> str:
    """使用项目 RAG 检索器（FTS5 全文检索 281 章典籍）"""
    from services.rag_retriever import retrieve_by_stage

    pattern = session.get("pattern", "")
    chart = session.get("chart_data", {})
    sr = session.get("step_results", {})

    # 将验证阶段映射到 RAG 阶段（格局派重构后）
    rag_stage = "pattern"
    if stage.startswith("xs_"):
        # 相神验证阶段 → 检索相神/顺用/逆用相关典籍
        rag_stage = "xiangshen"
    elif stage.startswith("jiuying_") or stage == "chengbai":
        # 成败救应阶段 → 检索成败/救应相关典籍
        rag_stage = "chengbai"
    elif stage.startswith("quality_"):
        # 格局高低阶段 → 检索有情/有力相关典籍
        rag_stage = "quality"

    dm = chart.get("day_master", "")
    dm_wx = _get_wuxing(dm)
    month_branch = sr.get("wangshuai", {}).get("level", "") or \
                   chart.get("four_pillars", {}).get("month", {}).get("branch", "")

    try:
        keywords = [pattern.replace("格", "")]
        if stage.startswith("xs_"):
            keywords.extend(["相神", "顺用", "逆用", "用神", "辅佐", "成格"])
        elif stage.startswith("jiuying_") or stage == "chengbai":
            keywords.extend(["成败", "救应", "破格", "败因"])
            # 增加具体败因关键词
            defeat_causes = session.get("defeat_causes", [])
            if defeat_causes:
                keywords.extend(defeat_causes)
        elif stage.startswith("quality_"):
            keywords.extend(["有情", "有力", "生扶", "通根", "格局高低"])

        results = retrieve_by_stage(
            stage=rag_stage,
            keywords=keywords,
            ri_zhu_wuxing=dm_wx,
            month_branch=month_branch,
            top_k=5,
        )
        if results:
            lines = []
            for r in results[:4]:
                src = r.get("source", "?")
                ch = r.get("chapter", "?")
                txt = r.get("text", r.get("excerpt", ""))
                txt = _clean_classical_text(txt)
                lines.append(f"《{src}·{ch}》：{txt}")
            return "\n".join(lines)
    except Exception:
        pass

    return "（典籍数据不可用）"


def _get_wuxing(dm):
    mapping = {"甲": "木", "乙": "木", "丙": "火", "丁": "火", "戊": "土",
               "己": "土", "庚": "金", "辛": "金", "壬": "水", "癸": "水"}
    return mapping.get(dm[-1] if dm else "", "")


def _format_chat_history(session):
    lines = []
    for h in session.get("history", [])[-6:]:
        role = "命理师" if h.get("role") == "ai" else "用户"
        q = h.get("question", "")[:60]
        a = h.get("answer", "")
        note = h.get("note", "")
        line = f"{role}: {q} → {a}"
        if note:
            line += f" (补充: {note})"
        lines.append(line)
    return "\n".join(lines)


async def _dispatch_static(session, sub, answer):
    """V3 静态 handler — 当 LLM 不可用时降级到此"""
    if sub == "L1":
        return await _handle_L1(session, answer)
    elif sub == "purity":
        return await _handle_purity(session, answer)
    elif sub.startswith("xs_"):
        # 格局派重构：相神验证
        return await _handle_xiangshen(session, answer)
    elif sub.startswith("jiuying_") or sub == "chengbai":
        # 格局派重构：成败救应
        return await _handle_chengbai(session, answer)
    elif sub.startswith("quality_"):
        # 格局派重构：格局高低
        return await _handle_quality(session, answer)
    elif sub.startswith("diag_"):
        return await _handle_diagnosis(session, answer)
    else:
        return {"error": f"未知子阶段: {sub}"}


# ============================================================
# L1 Handler
# ============================================================

async def _handle_L1(session, answer):
    session["l1_answer"] = "High" if answer == "accurate" else ("Medium" if answer == "partial" else "Low")

    # 混合框架：优先用 LLM delta，否则固定值
    delta = _get_delta(session, answer)
    if delta != 0:
        session["confidence"] = max(1, min(99, session["confidence"] + delta))

    session["diagnosis_path"].append({"step": "L1", "action": f"格局特征验证-{session['pattern']}",
                                       "answer": session["l1_answer"]})

    if session["l1_answer"] == "Low":
        # 纯杂检查
        purity = check_purity(session["pattern"], session["chart_data"])
        session["purity_result"] = purity
        if purity["is_mixed"]:
            session["sub_stage"] = "purity"
            session["round"] += 1
            q = {
                "round": session["round"], "layer": f"L{session['round']}",
                "question": f"你是否感觉自己性格中有矛盾的两面——{purity['mix_stems'][0]}和{purity['mix_stems'][1]}的特征同时存在？",
                "explanation": f"检测到{purity['mix_type']}，可能使格局特征模糊。",
                "options": ["是", "不太确定", "不是"],
            }
            session["current_question"] = q
            return {"locked": False, "stage": "pattern", "sub_stage": "purity",
                    "question": q, "purity_check": purity}
        else:
            # 不混杂 → 直接进诊断链
            return await _enter_diagnosis(session)

    # 进 Phase 2
    # Fix: L1 B(有点出入) → 先静默检查是否有混杂或待确认合局
    if session["l1_answer"] == "Medium":
        purity = check_purity(session["pattern"], session["chart_data"])
        heju = session.get("step_results", {}).get("zhi_heju", {})
        session["purity_result"] = purity
        if purity["is_mixed"] or heju.get("pending"):
            session["purity"] = "杂" if purity["is_mixed"] else "纯"
            session["diagnosis_path"].append({"step": "L1", "action": "有点出入-检测混杂/合局",
                                               "mixed": purity["is_mixed"], "heju_pending": heju.get("pending")})
        else:
            session["diagnosis_path"].append({"step": "L1", "action": "有点出入-无特殊检测"})
    # 格局派重构：L1 accurate/partial → 进入相神验证（替代旧 Phase2）
    return await _enter_xiangshen(session)


async def _handle_purity(session, answer):
    if answer == "accurate":
        session["purity"] = "杂"
        session["confidence"] = max(1, session["confidence"] * 0.7)
        return await _enter_xiangshen(session)
    else:
        session["purity"] = "纯"
        return await _enter_diagnosis(session)


# ============================================================
# 格局派重构：相神验证 → 成败救应 → 格局高低
# 替代旧 Phase2 品质判断 + Phase3 用神验证
# ============================================================

async def _enter_xiangshen(session):
    """相神验证入口：按优先级逐一验证相神候选"""
    session["stage"] = "xiangshen"
    session["sub_stage"] = "xs_1"
    session["round"] += 1

    chart = session["chart_data"]
    dm_stem = _extract_dm_stem(chart)
    month_branch = _extract_month_branch(chart)
    wangshuai = session.get("step_results", {}).get("wangshuai", {})
    wangshuai_level = wangshuai.get("level", "中和")
    pattern = session["pattern"]

    candidates = session.get("xiangshen_candidates") or generate_xiangshen_candidates(pattern, dm_stem, chart)

    # 应用调候/扶抑加权因子
    for c in candidates:
        th_weight = get_tiaohou_weight(dm_stem, month_branch, c)
        fy_weight = get_fuyi_weight(wangshuai_level, c)
        c["confidence"] = max(1, min(99, c["confidence"] + th_weight + fy_weight))

    candidates.sort(key=lambda x: x["confidence"], reverse=True)

    # SmartPredictionSelector 集成：用区分度评分对候选重新排序
    uncertainty = session.get("uncertainty")
    candidates = _smart_rerank_candidates(candidates, uncertainty, asked_list=[])

    session["xiangshen_candidates"] = candidates
    session["_xs_asked"] = []

    if not candidates:
        session["confirmed_xiangshen"] = None
        return await _enter_chengbai(session)

    top = candidates[0]
    session["_xs_asked"].append(top["ten_god"])

    q = {
        "round": session["round"], "layer": f"L{session['round']}",
        "question": top.get("question", _get_xiangshen_question(top["ten_god"], top.get("gong_way", ""))),
        "explanation": f"验证相神 {top['ten_god']}({top['five_element']}) — {top.get('gong_way', '')}",
        "options": ["是的", "不太确定", "不是"],
        "target_xiangshen": top["ten_god"],
    }
    session["current_question"] = q

    return {"locked": False, "stage": "xiangshen", "sub_stage": "xs_1",
            "question": q, "xiangshen_candidates": candidates,
            "yongshen": session.get("yongshen", {})}


async def _handle_xiangshen(session, answer):
    """相神验证问答处理"""
    candidates = session.get("xiangshen_candidates", [])
    cq = session.get("current_question", {})
    target = cq.get("target_xiangshen", "")
    sub = session.get("sub_stage", "xs_1")

    # 混合框架：目标候选用 LLM delta（有 guardrail），其他候选用固定值
    target_delta = _get_delta(session, answer)

    for c in candidates:
        is_target = c["ten_god"] == target
        if is_target:
            c["confidence"] = max(1, min(99, c["confidence"] + target_delta))
        else:
            if answer == "accurate":
                c["confidence"] = max(1, c["confidence"] - 5)
            elif answer == "inaccurate":
                c["confidence"] = min(99, c["confidence"] + 3)

    candidates.sort(key=lambda x: x["confidence"], reverse=True)

    # SmartPredictionSelector 集成：用区分度评分对候选重新排序（考虑已问过的惩罚）
    uncertainty = session.get("uncertainty")
    asked = session.get("_xs_asked", [])
    candidates = _smart_rerank_candidates(candidates, uncertainty, asked_list=asked)

    session["xiangshen_candidates"] = candidates

    # 收敛判断
    top = candidates[0] if candidates else None
    if top and top["confidence"] >= 65 and (len(candidates) < 2 or top["confidence"] - candidates[1]["confidence"] >= 20):
        session["confirmed_xiangshen"] = top
        session["diagnosis_path"].append({"step": "xiangshen", "action": "相神收敛",
                                           "result": top["ten_god"], "confidence": top["confidence"]})
        return await _enter_chengbai(session)

    # 继续问下一个候选
    asked = session.get("_xs_asked", [])
    next_xs = None
    for c in candidates:
        if c["ten_god"] not in asked:
            next_xs = c
            break

    if not next_xs or len(asked) >= 3:
        # 已问完3个候选或无新候选 → 取最高分为相神
        session["confirmed_xiangshen"] = top
        session["diagnosis_path"].append({"step": "xiangshen", "action": "相神遍历完毕",
                                           "result": top["ten_god"] if top else "无",
                                           "confidence": top["confidence"] if top else 0})
        return await _enter_chengbai(session)

    asked.append(next_xs["ten_god"])
    session["_xs_asked"] = asked
    session["sub_stage"] = f"xs_{len(asked)}"
    session["round"] += 1

    q = {
        "round": session["round"], "layer": f"L{session['round']}",
        "question": next_xs.get("question", _get_xiangshen_question(next_xs["ten_god"], next_xs.get("gong_way", ""))),
        "explanation": f"验证相神 {next_xs['ten_god']}({next_xs['five_element']}) — {next_xs.get('gong_way', '')}",
        "options": ["是的", "不太确定", "不是"],
        "target_xiangshen": next_xs["ten_god"],
    }
    session["current_question"] = q

    return {"locked": False, "stage": "xiangshen", "sub_stage": session["sub_stage"],
            "question": q, "xiangshen_candidates": candidates,
            "yongshen": session.get("yongshen", {})}


async def _enter_chengbai(session):
    """成败救应检测"""
    session["stage"] = "chengbai"
    session["round"] += 1

    pattern = session["pattern"]
    yongshen = session.get("yongshen") or {}
    xiangshen = session.get("confirmed_xiangshen") or {}
    chart_data = session["chart_data"]

    # 静态检测败因
    chengbai = check_chengbai(pattern, yongshen, xiangshen, chart_data)
    session["chengbai_result"] = chengbai

    if not chengbai["is_defeated"]:
        # 无败因 → 成格，直接进格局高低
        session["chengbai_status"] = "成格"
        session["diagnosis_path"].append({"step": "chengbai", "action": "成败检测",
                                           "result": "成格", "defeat_causes": []})
        return await _enter_quality_v2(session)

    # 有败因 → 检测救应
    jiuying = check_jiuying_v2(pattern, chengbai["defeat_causes"], chart_data)
    session["jiuying_result"] = jiuying

    if jiuying["has_jiuying"]:
        # 有救应 → 问用户验证救应特征
        causes_text = "、".join(chengbai["defeat_causes"])
        q = {
            "round": session["round"], "layer": f"L{session['round']}",
            "question": f"你的命局中有{causes_text}的隐患，但有{jiuying['jiuying_shen']}可以化解。你是否觉得在困境中总有某种力量帮你转危为安？",
            "explanation": f"救应检测：{jiuying['mechanism']}",
            "options": ["是的，确实如此", "偶尔会有", "没有这种感觉"],
        }
        session["current_question"] = q
        session["sub_stage"] = "jiuying_1"
        return {"locked": False, "stage": "chengbai", "sub_stage": "jiuying_1",
                "question": q, "chengbai_result": chengbai, "jiuying_result": jiuying}
    else:
        # 无救应 → 败格
        session["chengbai_status"] = "败格无救"
        session["diagnosis_path"].append({"step": "chengbai", "action": "成败检测",
                                           "result": "败格无救",
                                           "defeat_causes": chengbai["defeat_causes"]})
        return await _enter_quality_v2(session)


async def _handle_chengbai(session, answer):
    """成败救应问答处理"""
    jiuying = session.get("jiuying_result") or {}

    if answer == "accurate":
        session["chengbai_status"] = "败格有救"
    elif answer == "partial":
        session["chengbai_status"] = "败格有救"
        # 弱救应，降低等级
        if jiuying.get("jiuying_level") == "上等":
            jiuying["jiuying_level"] = "中等"
        elif jiuying.get("jiuying_level") == "中等":
            jiuying["jiuying_level"] = "下等"
        session["jiuying_result"] = jiuying
    else:
        session["chengbai_status"] = "败格无救"
        session["jiuying_result"]["has_jiuying"] = False

    session["diagnosis_path"].append({"step": "chengbai", "action": "救应验证",
                                       "result": session["chengbai_status"]})
    return await _enter_quality_v2(session)


async def _enter_quality_v2(session):
    """格局高低评判（在用神+成败救应之后）"""
    session["stage"] = "quality"
    session["sub_stage"] = "quality_1"
    session["round"] += 1

    pattern = session["pattern"]
    yongshen = session.get("yongshen") or {}
    xiangshen = session.get("confirmed_xiangshen") or {}
    chengbai = session.get("chengbai_result") or {}
    jiuying = session.get("jiuying_result") or {}
    chart_data = session["chart_data"]

    # 静态评判格局高低
    quality = judge_pattern_quality_v2(
        pattern, yongshen, xiangshen, chengbai, jiuying, chart_data
    )
    session["quality"] = quality

    # 问用户验证有情
    ys_tg = yongshen.get("ten_god", "")
    xs_tg = xiangshen.get("ten_god", "") if xiangshen else ys_tg
    q_text = _get_quality_question("youqing", xs_tg)
    q = {
        "round": session["round"], "layer": f"L{session['round']}",
        "question": q_text,
        "explanation": f"验证{pattern}的有情程度",
        "options": ["很像", "有点出入", "完全不像"],
    }
    session["current_question"] = q
    return {"locked": False, "stage": "quality", "sub_stage": "quality_1",
            "question": q, "static_quality": quality}


async def _handle_quality(session, answer):
    """格局高低问答处理"""
    sub = session.get("sub_stage", "quality_1")

    if sub == "quality_1":
        session["quality_youqing"] = answer == "accurate"
        # 问有力
        session["sub_stage"] = "quality_2"
        session["round"] += 1
        yongshen = session.get("yongshen", {})
        xiangshen = session.get("confirmed_xiangshen", {})
        xs_tg = xiangshen.get("ten_god", "") if xiangshen else yongshen.get("ten_god", "")
        q_text = _get_quality_question("youli", xs_tg)
        q = {
            "round": session["round"], "layer": f"L{session['round']}",
            "question": q_text,
            "explanation": f"验证{xs_tg}是否有实体力量支撑",
            "options": ["很像", "有点出入", "完全不像"],
        }
        session["current_question"] = q
        return {"locked": False, "stage": "quality", "sub_stage": "quality_2",
                "question": q}

    elif sub == "quality_2":
        session["quality_youli"] = answer == "accurate"

        # 结合静态评判 + 用户反馈，最终确定格局高低
        static_quality = session.get("quality", "中格")
        youqing = session.get("quality_youqing", False)
        youli = session.get("quality_youli", False)

        # 用户反馈微调
        if youqing and youli and static_quality in ("中格", "中下格"):
            final_quality = "上格"
        elif not youqing and not youli and static_quality in ("上格", "中格"):
            final_quality = "中下格"
        else:
            final_quality = static_quality

        session["quality"] = final_quality
        session["diagnosis_path"].append({"step": "quality", "action": "格局高低",
                                           "result": final_quality,
                                           "youqing": youqing, "youli": youli})
        return _finalize_locked_v2(session)

    return {"error": f"未知 quality 子阶段: {sub}"}


def _finalize_locked_v2(session):
    """新版输出：区分用神和相神"""
    session["stage"] = "locked"

    yongshen = session.get("yongshen") or {}
    xiangshen = session.get("confirmed_xiangshen") or {}
    chengbai = session.get("chengbai_result") or {}
    jiuying = session.get("jiuying_result") or {}

    return {
        "locked": True, "stage": "done",
        "rounds": session["round"],
        "result": {
            "pattern": session["pattern"],
            "pattern_confidence": session["confidence"],
            # 用神 = 月令定格之物
            "yong_shen": yongshen.get("ten_god", ""),
            "yong_shen_element": yongshen.get("five_element", ""),
            "yong_shen_mode": yongshen.get("mode", ""),  # 顺用/逆用
            # 相神 = 辅佐用神成格之物
            "xiang_shen": xiangshen.get("ten_god", "") if xiangshen else "",
            "xiang_shen_element": xiangshen.get("five_element", "") if xiangshen else "",
            "xiang_shen_way": xiangshen.get("gong_way", "") if xiangshen else "",
            "xiangshen_confidence": xiangshen.get("confidence", 0) if xiangshen else 0,
            # 成败救应
            "chengbai_status": session.get("chengbai_status", "成格"),
            "defeat_causes": chengbai.get("defeat_causes", []),
            "jiuying_shen": jiuying.get("jiuying_shen", ""),
            "jiuying_level": jiuying.get("jiuying_level", ""),
            # 兼容旧字段
            "five_element": yongshen.get("five_element", ""),
            "gong_way": xiangshen.get("gong_way", "") if xiangshen else "",
            "yongshen_confidence": xiangshen.get("confidence", 0) if xiangshen else 0,
            "pattern_type": "正格",
        },
        "quality": session.get("quality", "中格"),
        "purity": session.get("purity", "纯"),
        "pattern_source": session.get("step_results", {}).get("pattern_source", "月令本气"),
        "diagnosis_path": session.get("diagnosis_path", []),
        "credibility": "high" if session.get("quality") in ("上格", "中格") else "medium",
        "expansion_attempted": session.get("diagnosis_count", 0) > 0,
        "total_rounds": session["round"],
    }


# ============================================================
# 诊断链
# ============================================================

async def _enter_diagnosis(session):
    session["stage"] = "diagnosis"
    session["diagnosis_count"] = 0
    session["diagnosis_sub_stage"] = 1
    session["round"] += 1

    # SmartPredictionSelector 集成：预检查适用步骤并用区分度重新排序
    chart = session["chart_data"]
    dm_stem = _extract_dm_stem(chart)
    month_branch = _extract_month_branch(chart)
    fp = chart.get("four_pillars", {})
    uncertainty = session.get("uncertainty")

    applicable_steps = []
    # D1: 月令被冲
    if _check_month_branch_chong(fp, month_branch)["is_chong"]:
        applicable_steps.append(1)
    # D2: 月令被合
    if _check_month_branch_he(fp, month_branch)["is_he"]:
        applicable_steps.append(2)
    # D3: 中气格局
    stems = _get_month_hidden_stems(month_branch)
    if len(stems) >= 2:
        tg2 = _calc_ten_god(dm_stem, stems[1])
        alt_pattern = _TG_TO_PATTERN.get(tg2, "")
        if alt_pattern and alt_pattern != session["pattern"]:
            applicable_steps.append(3)
    # D4: 救应（总是适用）
    applicable_steps.append(4)
    # D5: 时辰（总是适用）
    applicable_steps.append(5)

    # 用 SmartPredictionSelector 重新排序（仅当有 uncertainty 数据时）
    if uncertainty and len(applicable_steps) > 1:
        applicable_steps = _smart_rank_diag_steps(applicable_steps, uncertainty)

    session["_diag_order"] = applicable_steps
    session["_diag_order_idx"] = 0

    first_step = applicable_steps[0] if applicable_steps else 1
    return await _run_diagnosis_step(session, first_step)


async def _run_diagnosis_step(session, step_num):
    session["diagnosis_sub_stage"] = step_num
    chart = session["chart_data"]
    dm_stem = _extract_dm_stem(chart)
    month_branch = _extract_month_branch(chart)
    fp = chart.get("four_pillars", {})

    # 辅助函数：从 _diag_order 中找到下一个适用步骤
    def _next_step(current):
        order = session.get("_diag_order")
        if not order:
            return current + 1
        try:
            idx = order.index(current)
            if idx + 1 < len(order):
                return order[idx + 1]
        except ValueError:
            pass
        return current + 1

    if step_num == 1:
        # D1: 月令被冲
        d1 = _check_month_branch_chong(fp, month_branch)
        if d1["is_chong"]:
            q = {"round": session["round"], "layer": f"L{session['round']}",
                 "question": DIAGNOSIS_QUESTIONS["D1_chong"],
                 "explanation": "检测月令是否被冲",
                 "options": ["是", "不太确定", "不是"],
                 "diag_step": "D1", "diag_data": d1}
            session["current_question"] = q
            session["sub_stage"] = "diag_D1"
            return {"locked": False, "stage": "diagnosis", "sub_stage": "diag_D1",
                    "question": q, "diagnosis_step": "D1"}
        else:
            session["round"] += 1
            return await _run_diagnosis_step(session, _next_step(1))

    elif step_num == 2:
        d2 = _check_month_branch_he(fp, month_branch)
        if d2["is_he"]:
            q = {"round": session["round"], "layer": f"L{session['round']}",
                 "question": DIAGNOSIS_QUESTIONS["D2_he"],
                 "explanation": "检测月令是否被合",
                 "options": ["是", "不太确定", "不是"],
                 "diag_step": "D2", "diag_data": d2}
            session["current_question"] = q
            session["sub_stage"] = "diag_D2"
            return {"locked": False, "stage": "diagnosis", "sub_stage": "diag_D2",
                    "question": q, "diagnosis_step": "D2"}
        else:
            session["round"] += 1
            return await _run_diagnosis_step(session, _next_step(2))

    elif step_num == 3:
        stems = _get_month_hidden_stems(month_branch)
        if len(stems) >= 2:
            tg2 = _calc_ten_god(dm_stem, stems[1])
            alt_pattern = _TG_TO_PATTERN.get(tg2, "")
            if alt_pattern and alt_pattern != session["pattern"]:
                l1_q = PATTERN_L1_QUESTIONS.get(alt_pattern, {})
                q_text = f"之前的方向不太符合。换个角度——{l1_q.get('question', '请描述你的特点')}"
                q = {"round": session["round"], "layer": f"L{session['round']}",
                     "question": q_text,
                     "explanation": f"尝试中气格局: {alt_pattern}",
                     "options": ["很像", "有点出入", "完全不像"],
                     "diag_step": "D3", "alt_pattern": alt_pattern}
                session["current_question"] = q
                session["sub_stage"] = "diag_D3"
                return {"locked": False, "stage": "diagnosis", "sub_stage": "diag_D3",
                        "question": q, "diagnosis_step": "D3"}
        session["round"] += 1
        return await _run_diagnosis_step(session, _next_step(3))

    elif step_num == 4:
        q = {"round": session["round"], "layer": f"L{session['round']}",
             "question": DIAGNOSIS_QUESTIONS["D4_jiuying"],
             "explanation": "检测用神救应是否到位",
             "options": ["是", "不太确定", "不是"],
             "diag_step": "D4"}
        session["current_question"] = q
        session["sub_stage"] = "diag_D4"
        return {"locked": False, "stage": "diagnosis", "sub_stage": "diag_D4",
                "question": q, "diagnosis_step": "D4"}

    elif step_num == 5:
        q = {"round": session["round"], "layer": f"L{session['round']}",
             "question": DIAGNOSIS_QUESTIONS["D5_time"],
             "explanation": "时辰校验",
             "options": ["准确", "不太确定", "不准"],
             "diag_step": "D5"}
        session["current_question"] = q
        session["sub_stage"] = "diag_D5"
        return {"locked": False, "stage": "diagnosis", "sub_stage": "diag_D5",
                "question": q, "diagnosis_step": "D5"}

    return {"error": "无效诊断步骤"}


async def _handle_diagnosis(session, answer):
    sub = session.get("sub_stage")
    step_num = session.get("diagnosis_sub_stage", 1)

    session["diagnosis_path"].append({"step": f"D{step_num}", "answer": answer})

    if answer == "accurate":
        if sub == "diag_D1":
            d1 = session.get("current_question", {}).get("diag_data", {})
            if d1.get("has_rescue"):
                session["confidence"] = max(1, session["confidence"] * 0.7)
                return await _enter_xiangshen(session)
            else:
                session["round"] += 1
                # 冲散→中气, 但之后也要静默检查救应
                session["_from_chong_san"] = True
                return await _run_diagnosis_step(session, 3)  # 冲散→中气
        elif sub == "diag_D2":
            session["round"] += 1
            session["sub_stage"] = "L1"
            session["confidence"] = 20
            return {"locked": False, "stage": "pattern", "sub_stage": "L1",
                    "question": session["current_question"], "pattern_changed": True}
        elif sub == "diag_D3":
            alt = session.get("current_question", {}).get("alt_pattern", "")
            if alt:
                session["pattern"] = alt
                session["confidence"] = 25
                session["purity"] = None
                session["quality"] = None
                # 格局派重构：重新确定用神和相神候选
                dm_stem = _extract_dm_stem(session["chart_data"])
                month_branch = _extract_month_branch(session["chart_data"])
                session["yongshen"] = determine_yongshen(alt, dm_stem, month_branch, session["chart_data"])
                session["xiangshen_candidates"] = generate_xiangshen_candidates(alt, dm_stem, session["chart_data"])
                # 冲散路径: 静默注入救应数据
                if session.get("_from_chong_san"):
                    session["_from_chong_san"] = False
                    session["diagnosis_path"].append({"step": "D4_silent", "action": "救应静默检测(跳过)"})
                return await _enter_xiangshen(session)
        elif sub == "diag_D4":
            return await _enter_xiangshen(session)
        elif sub == "diag_D5":
            session["confidence"] = max(1, session["confidence"] * 0.6)
            return await _enter_xiangshen(session)
    else:
        if sub == "diag_D5" and answer == "partial":
            return {"locked": True, "stage": "done", "result": None,
                    "message": "无法确认，请重新确认出生时间"}
        if sub == "diag_D5" and answer == "inaccurate":
            return {"locked": True, "stage": "done", "result": None,
                    "message": "请回到首页重新录入"}
        session["diagnosis_count"] = session.get("diagnosis_count", 0) + 1
        if session["diagnosis_count"] >= 3:
            session["round"] += 1
            return await _run_diagnosis_step(session, 5)  # 跳至时辰
        session["round"] += 1
        # 使用 _diag_order 中的顺序跳到下一个诊断步骤
        _order = session.get("_diag_order")
        _next = step_num + 1
        if _order:
            try:
                _idx = _order.index(step_num)
                if _idx + 1 < len(_order):
                    _next = _order[_idx + 1]
            except ValueError:
                pass
        return await _run_diagnosis_step(session, _next)

    return await _enter_xiangshen(session)


def _check_month_branch_chong(fp, month_branch):
    from rules.pattern import _OPPOSITES
    opp = _OPPOSITES.get(month_branch)
    is_chong = False
    has_rescue = False
    for pos in ["year", "day"]:
        b = fp.get(pos, {}).get("branch", "")
        if b == opp:
            is_chong = True
    return {"is_chong": is_chong, "has_rescue": has_rescue}


def _check_month_branch_he(fp, month_branch):
    from rules.pattern import _COMBINATIONS
    he_with = _COMBINATIONS.get(month_branch)
    is_he = False
    for pos in ["year", "day"]:
        b = fp.get(pos, {}).get("branch", "")
        if b == he_with:
            is_he = True
    return {"is_he": is_he}


def _get_month_hidden_stems(month_branch):
    from rules.pattern import get_month_stems
    return get_month_stems(month_branch)


# ============================================================
# 辅助函数
# ============================================================

def _extract_dm_stem(chart_data):
    dm = chart_data.get("day_master", "")
    return dm[-1] if dm else "甲"


def _extract_month_branch(chart_data):
    return chart_data.get("four_pillars", {}).get("month", {}).get("branch", "子")


def get_session(session_id):
    _cleanup_expired_sessions()
    return _verification_sessions.get(session_id)


async def get_session_async(session_id):
    _cleanup_expired_sessions()
    s = _verification_sessions.get(session_id)
    if s:
        return s
    s = await _load_db_session(session_id)
    if s:
        _verification_sessions[session_id] = s
    return s
