"""V2 鉴别力排序与问题序列编排 — 断前事核心编排层

理论依据：
- V2 报告 §4.1-4.3：D(q) = I(q) / T(q) 鉴别力函数
- V2 报告 §4.2：3 题/6 题条件选择矩阵
- V2 报告 §4.3：贪心式编排，首题六亲存亡
- V2 算法 §10：I(q) 三因子调整 + T(q) 三因子调整

暴露接口：
- init_verification_v2(chart_data, ...) → VerificationSessionV2
- generate_question_sequence(...) → tuple[list[QuestionV2], int]
- compute_discrimination(category, ...) → float
- regenerate_questions(session, adjustment) → list[QuestionV2]
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, Optional
import uuid

from services.liuqin import (
    LiuqinAssessment, LiuqinItem, QuestionV2,
    assess_liuqin,
)

# ============================================================
# 枚举与数据类
# ============================================================

class QuestionCategory(str, Enum):
    """V2-4.1 问题类别 — 按鉴别力降序排列"""
    LIUQIN_SURVIVAL = "六亲存亡"       # D(q) 最高
    DAYUN_EVENT = "大运事件"           # D(q) 中高
    LIUQIN_RELATION = "六亲关系"      # D(q) 中高
    JISHEN_YEAR = "忌神流年"           # D(q) 中高
    WANGSHUAI_SOMATIC = "旺衰体感"     # D(q) 中等
    XIANGSHEN_VERIFY = "相神验证"      # D(q) 中等
    PATTERN_QUALITY = "格局高低"       # D(q) 中低
    PERSONALITY_TRAIT = "性格特征"     # D(q) 最低


@dataclass
class AnsweredQuestion:
    """已回答的问题记录"""
    question_id: str
    category: str
    answer: Literal["yes", "no", "unclear"]
    note: str = ""


@dataclass
class VerificationSessionV2:
    """V2 验证会话。

    V2-5.3: 承载断前事→参数锁定→断未来全流程的状态。
    """
    session_id: str
    user_id: Optional[str]
    chart_data: dict
    phase: str = "verification"          # "verification" | "locked" | "forecast"
    current_question: Optional[QuestionV2] = None
    question_sequence: list = field(default_factory=list)  # list[QuestionV2]
    question_count: int = 3              # 3 or 6
    residual_ambiguity: float = 0.0
    answered: list = field(default_factory=list)  # list[AnsweredQuestion]
    locked: bool = False
    lock_state: Optional[dict] = None
    adjustment_history: list = field(default_factory=list)
    use_ai: bool = False
    classical_cache: dict = field(default_factory=dict)


# ============================================================
# 歧义空间估算 (V2 算法 §10.2)
# ============================================================

def estimate_ambiguity_space_size(
    chart_data: dict,
    uncertainty=None,  # UncertaintyReport | None
) -> int:
    """V2-1.4: 估算当前命盘歧义空间 |S|。

    基准：|S| = 4×5×4×2 = 160（用神候选×旺衰等级×格局层次×真假判定）。
    实际值受 uncertainty 参数调节。
    """
    base = 4 * 5 * 4 * 2  # = 160

    if uncertainty is None:
        return base

    # 从 UncertaintyReport.items 提取各维度风险（兼容 dict/object）
    items = getattr(uncertainty, 'items', None)
    if items is None and isinstance(uncertainty, dict):
        items = uncertainty.get('items', [])
    elif items is None:
        items = []
    # getattr 对 dict 返回 <built-in method items>，isinstance 守卫防止此情况
    if callable(items):
        items = []
    item_map = {}
    for it in items:
        if isinstance(it, dict):
            item_map[it.get('dimension', '')] = it.get('risk_score', 0)
        else:
            item_map[getattr(it, 'dimension', '')] = getattr(it, 'risk_score', 0)

    modifier = 1.0
    if item_map.get("时辰风险", 0) > 0.5:
        modifier *= 1.15
    if item_map.get("格局多解性", 0) > 0.5:
        modifier *= 1.10
    if item_map.get("用神争议度", 0) > 0.5:
        modifier *= 1.08
    if item_map.get("旺衰模糊度", 0) > 0.5:
        modifier *= 1.05

    return max(base, int(base * modifier))


# ============================================================
# D(q) 鉴别力函数 (V2 算法 §10.3-10.5)
# ============================================================

# 基准 I(q) 值 (V2-4.2)
_BASE_I: dict[QuestionCategory, float] = {
    QuestionCategory.LIUQIN_SURVIVAL:   0.30,
    QuestionCategory.DAYUN_EVENT:       0.20,
    QuestionCategory.LIUQIN_RELATION:   0.18,
    QuestionCategory.JISHEN_YEAR:       0.18,
    QuestionCategory.WANGSHUAI_SOMATIC: 0.12,
    QuestionCategory.XIANGSHEN_VERIFY:  0.10,
    QuestionCategory.PATTERN_QUALITY:   0.08,
    QuestionCategory.PERSONALITY_TRAIT: 0.08,
}

# 基准 T(q) 值 (V2-4.1)
_BASE_T: dict[QuestionCategory, float] = {
    QuestionCategory.LIUQIN_SURVIVAL:   0.05,   # 二值事实，T 极小
    QuestionCategory.DAYUN_EVENT:       0.15,   # T 中等
    QuestionCategory.LIUQIN_RELATION:   0.12,
    QuestionCategory.JISHEN_YEAR:       0.18,
    QuestionCategory.WANGSHUAI_SOMATIC: 0.25,   # T 中高
    QuestionCategory.XIANGSHEN_VERIFY:  0.22,
    QuestionCategory.PATTERN_QUALITY:   0.30,
    QuestionCategory.PERSONALITY_TRAIT: 0.50,   # T 极大
}


def compute_information_gain(
    category: QuestionCategory,
    ambiguity_space_size: int,
    chart_data: dict,
    liuqin_assessment: Optional[LiuqinAssessment] = None,
) -> float:
    """V2-4.1: 计算 I(q) — 答案能排除的歧义状态比例。

    I(q) = base_i × space_factor × alignment_factor × quality_factor
    """
    base_i = _BASE_I.get(category, 0.10)

    # 因子 1: 歧义空间缩放
    space_factor = min(1.0, 160.0 / max(ambiguity_space_size, 1))

    # 因子 2: 问题与歧义维度对齐度
    alignment = _compute_alignment(category, chart_data, liuqin_assessment)

    # 因子 3: 六亲评估质量
    quality = _liuqin_quality_factor(category, liuqin_assessment)

    i_q = base_i * space_factor * alignment * quality
    return round(min(i_q, 1.0), 4)


def compute_tolerance(
    category: QuestionCategory,
    chart_data: dict,
    user_cooperation_level: float = 0.7,
) -> float:
    """V2-4.1: 计算 T(q) — 回答可被多种解释收容的程度。

    T(q) = base_t × cooperation_adjust × time_adjust
    """
    base_t = _BASE_T.get(category, 0.20)

    # 因子 1: 用户配合度逆相关
    cooperation_adjust = 1.0 - (user_cooperation_level - 0.5) * 0.2

    # 因子 2: 时辰可靠性 (大运事件)
    time_adjust = 1.0
    hour_reliable = chart_data.get("hour_reliable", True)
    if not hour_reliable and category == QuestionCategory.DAYUN_EVENT:
        time_adjust = 1.3

    # 因子 3: 六亲存亡的情感不可逆性
    if category == QuestionCategory.LIUQIN_SURVIVAL:
        time_adjust = 0.8

    t_q = base_t * cooperation_adjust * time_adjust
    return round(min(t_q, 1.0), 4)


def compute_discrimination(
    category: QuestionCategory,
    chart_data: dict,
    ambiguity_space_size: int,
    liuqin_assessment: Optional[LiuqinAssessment] = None,
    user_cooperation_level: float = 0.7,
) -> float:
    """V2-4.1: D(q) = I(q) / T(q)

    鉴别力函数。值越大，该问题对消歧的贡献越大。
    弱鉴别力警告阈值: D(q) < 0.3 (V2-5.4)
    """
    i_q = compute_information_gain(
        category, ambiguity_space_size, chart_data, liuqin_assessment
    )
    t_q = compute_tolerance(category, chart_data, user_cooperation_level)

    if t_q < 0.001:
        t_q = 0.001

    return round(i_q / t_q, 4)


def _compute_alignment(
    category: QuestionCategory,
    chart_data: dict,
    liuqin_assessment: Optional[LiuqinAssessment],
) -> float:
    """对齐度：问题是否命中当前命盘的歧义维度。"""
    month_hidden = chart_data.get("four_pillars", {}).get("month", {}).get("hidden_stems", [])

    if category == QuestionCategory.LIUQIN_SURVIVAL:
        if liuqin_assessment:
            parent = liuqin_assessment.parents
            if parent.consistency == "contradictory":
                return 1.3
            elif parent.consistency == "tentative":
                return 1.0
            else:
                return 0.8
        return 1.0

    elif category == QuestionCategory.DAYUN_EVENT:
        if len(month_hidden) >= 3:
            return 1.15
        return 1.0

    elif category == QuestionCategory.WANGSHUAI_SOMATIC:
        strength = chart_data.get("strength_detail", {})
        score = strength.get("total_score", strength.get("score", 50))
        if 40 <= score <= 60:
            return 1.2
        return 0.85

    return 1.0


def _liuqin_quality_factor(
    category: QuestionCategory,
    assessment: Optional[LiuqinAssessment],
) -> float:
    """六亲评估质量因子：矛盾越多 → 问题鉴别力越高。"""
    if category not in (QuestionCategory.LIUQIN_SURVIVAL, QuestionCategory.LIUQIN_RELATION):
        return 1.0
    if assessment is None:
        return 1.0

    contradictions = sum(
        1 for item in [assessment.parents, assessment.siblings,
                       assessment.spouse, assessment.children]
        if item.consistency == "contradictory"
    )
    if contradictions >= 2:
        return 1.2
    elif contradictions == 1:
        return 1.1
    return 1.0


# ============================================================
# 问题序列编排 (V2 算法 §10.6)
# ============================================================

async def generate_question_sequence(
    chart_data: dict,
    liuqin_assessment: LiuqinAssessment,
    uncertainty=None,  # UncertaintyReport | None
    use_ai: bool = False,
    user_cooperation_level: float = 0.7,
) -> tuple[list, int]:
    """V2-4.1~4.3: 生成按 D(q) 降序排列的问题序列。

    编排策略（贪心式）：
    - 首题固定六亲存亡（鉴别力最高）
    - 后续动态收窄至大运应期
    - 3 题/6 题由条件选择矩阵决定

    Returns:
        (questions: list[QuestionV2], question_count: int)
    """
    # Step 1: 确定题量 (V2-4.2 条件选择矩阵)
    question_count = _determine_question_count(chart_data, uncertainty)

    # Step 2: 估算歧义空间
    space_size = estimate_ambiguity_space_size(chart_data, uncertainty)

    # Step 3: 生成候选问题池 (D(q) 排序)
    candidate_pool: list[tuple[QuestionCategory, float]] = []

    # === 必选：六亲存亡（首题固定）===
    d_liuqin = compute_discrimination(
        QuestionCategory.LIUQIN_SURVIVAL, chart_data, space_size,
        liuqin_assessment, user_cooperation_level
    )
    candidate_pool.append((QuestionCategory.LIUQIN_SURVIVAL, d_liuqin))

    # === 候选：大运事件 ===
    d_dayun = compute_discrimination(
        QuestionCategory.DAYUN_EVENT, chart_data, space_size,
        None, user_cooperation_level
    )
    candidate_pool.append((QuestionCategory.DAYUN_EVENT, d_dayun))

    # === 候选：六亲关系（若评估有矛盾） ===
    if _has_liuqin_contradictions(liuqin_assessment):
        d_liuqin_rel = compute_discrimination(
            QuestionCategory.LIUQIN_RELATION, chart_data, space_size,
            liuqin_assessment, user_cooperation_level
        )
        candidate_pool.append((QuestionCategory.LIUQIN_RELATION, d_liuqin_rel))

    # === 候选：忌神流年 ===
    d_jishen = compute_discrimination(
        QuestionCategory.JISHEN_YEAR, chart_data, space_size,
        None, user_cooperation_level
    )
    candidate_pool.append((QuestionCategory.JISHEN_YEAR, d_jishen))

    # === 候选：旺衰体感 ===
    d_wangshuai = compute_discrimination(
        QuestionCategory.WANGSHUAI_SOMATIC, chart_data, space_size,
        None, user_cooperation_level
    )
    candidate_pool.append((QuestionCategory.WANGSHUAI_SOMATIC, d_wangshuai))

    # === 可选：相神验证 + 格局高低（6 题时启用） ===
    if question_count >= 6:
        d_xiangshen = compute_discrimination(
            QuestionCategory.XIANGSHEN_VERIFY, chart_data, space_size,
            None, user_cooperation_level
        )
        candidate_pool.append((QuestionCategory.XIANGSHEN_VERIFY, d_xiangshen))

        d_pattern = compute_discrimination(
            QuestionCategory.PATTERN_QUALITY, chart_data, space_size,
            None, user_cooperation_level
        )
        candidate_pool.append((QuestionCategory.PATTERN_QUALITY, d_pattern))

    # Step 4: 按 D(q) 降序排列
    candidate_pool.sort(key=lambda x: x[1], reverse=True)

    # Step 5: 弱鉴别力检查 (V2-5.4)
    max_d = candidate_pool[0][1] if candidate_pool else 0.0
    if max_d < 0.3 and question_count > 3:
        question_count = 3

    # Step 6: 截取 top-N 生成具体 QuestionV2
    selected = candidate_pool[:question_count]
    questions: list = []
    for i, (category, dq) in enumerate(selected):
        q = await _build_question_from_category(
            category=category,
            chart_data=chart_data,
            liuqin_assessment=liuqin_assessment,
            dq_score=dq,
            index=i,
            total=question_count,
            use_ai=use_ai,
        )
        questions.append(q)

    # Step 7: 证伪式分叉结构 (V2-4.3 检查 5)
    questions = _build_fork_structure(questions)

    return questions, question_count


def _determine_question_count(
    chart_data: dict,
    uncertainty=None,
) -> int:
    """V2-4.2 条件选择矩阵。

    ┌──────────────────────────────────────┬───────┐
    │ 时辰可靠 + 月令无争议 + 用户配合度高  │ 3 题  │
    │ 时辰存疑 或 月令藏干多透              │ 6 题  │
    │ 用户配合度低 或 反馈质量预期差         │ 3 题  │
    └──────────────────────────────────────┴───────┘
    """
    hour_reliable = chart_data.get("hour_reliable", True)
    month_hidden = chart_data.get("four_pillars", {}).get("month", {}).get("hidden_stems", [])
    month_multi_tou = len(month_hidden) >= 3

    if not hour_reliable or month_multi_tou:
        return 6

    if uncertainty is not None and getattr(uncertainty, 'overall_risk', 0) >= 0.6:
        return 6

    return 3


def _has_liuqin_contradictions(assessment: LiuqinAssessment) -> bool:
    """检查六亲评估是否存在矛盾。"""
    for item in [assessment.parents, assessment.siblings,
                 assessment.spouse, assessment.children]:
        if item.consistency == "contradictory":
            return True
    return False


def _build_fork_structure(questions: list) -> list:
    """V2-4.3: 构建证伪式分叉结构。

    每个问题设置 if_true_next / if_false_next / if_unclear_next 分支。
    """
    n = len(questions)
    for i, q in enumerate(questions):
        next_idx = i + 1
        if next_idx < n:
            next_id = questions[next_idx].id
            # QuestionV2 是 dataclass，直接设置属性
            q.if_true_next = next_id
            q.if_false_next = next_id
            q.if_unclear_next = next_id
        else:
            q.if_true_next = None
            q.if_unclear_next = None
            q.if_false_next = None
    return questions


async def _build_question_from_category(
    category: QuestionCategory,
    chart_data: dict,
    liuqin_assessment: Optional[LiuqinAssessment],
    dq_score: float,
    index: int,
    total: int,
    use_ai: bool = False,
) -> QuestionV2:
    """V2-4.3: 从问题类别生成具体 QuestionV2 对象。"""
    # 生成问题骨架
    skeleton = _generate_question_skeleton(category, chart_data, liuqin_assessment)

    # 生成问题文本（模板路径，AI 路径集成已实现）
    if use_ai:
        question_text = await _try_ai_generate_question(skeleton, category, chart_data)
    else:
        question_text = _template_generate_question(skeleton, category, chart_data)

    question_id = f"q_{index+1:03d}_{category.value}"

    targets = _build_targets(category, skeleton)

    q = QuestionV2(
        id=question_id,
        category=category.value,
        question_text=question_text,
        options=["是", "不是", "记不清了"],
        dq_score=dq_score,
        targets=targets,
        skeleton=skeleton,
        classical_reference=None,
    )
    q.if_true_next = None
    q.if_false_next = None
    q.if_unclear_next = None
    return q


def _generate_question_skeleton(
    category: QuestionCategory,
    chart_data: dict,
    liuqin_assessment: Optional[LiuqinAssessment],
) -> dict:
    """生成问题骨架（含事件年份、十神上下文、大运阶段）。V2-9.3"""
    import datetime
    day_master = chart_data.get("day_master", "")
    current_year = datetime.datetime.now().year
    birth_year = chart_data.get("birth_year", chart_data.get("year", current_year - 30))
    current_age = current_year - birth_year if birth_year else 0

    skeleton = {
        "template_id": category.value,
        "category": category.value,
        "day_master": day_master,
        "birth_year": birth_year,
        "current_age": current_age,
        "targets": {},
        "event_year": None,
        "event_type": "",
        "ten_god_context": "",
        "dayun_stage": "",
        "stem": "",
    }

    if category == QuestionCategory.LIUQIN_SURVIVAL:
        skeleton["event_type"] = "父母存亡"
        skeleton["ten_god_context"] = "偏财为父+正印为母"
        skeleton["event_year"] = current_year  # 当前状态
        if liuqin_assessment:
            parent = liuqin_assessment.parents
            skeleton["six_kin_type"] = "parents"
            skeleton["consistency"] = parent.consistency
            skeleton["ten_god_dim"] = parent.ten_god_dim
            skeleton["gongwei_dim"] = parent.gongwei_dim
        skeleton["targets"]["dimension"] = "liuqin_parents"

    elif category == QuestionCategory.DAYUN_EVENT:
        # 根据年龄定位大运阶段
        skeleton["event_type"] = "大运变动"
        skeleton["ten_god_context"] = "官星+财星引动"
        if 20 <= current_age <= 40:
            skeleton["event_year"] = birth_year + 25
            skeleton["dayun_stage"] = f"{current_age-5}-{current_age+5}岁事业运"
        else:
            skeleton["event_year"] = birth_year + int(current_age * 0.6)
        skeleton["stem"] = _extract_dominant_stem(chart_data, "财|官")
        skeleton["targets"]["dimension"] = "dayun_career"
        skeleton["focus"] = "career_change"

    elif category == QuestionCategory.LIUQIN_RELATION:
        skeleton["event_type"] = "比劫兄弟"
        skeleton["ten_god_context"] = "比肩劫财"
        skeleton["event_year"] = birth_year + 15  # 青少年期
        skeleton["dayun_stage"] = "学龄运"
        if liuqin_assessment:
            skeleton["sibling_consistency"] = liuqin_assessment.siblings.consistency
        skeleton["targets"]["dimension"] = "liuqin_siblings"

    elif category == QuestionCategory.JISHEN_YEAR:
        skeleton["event_type"] = "忌神流年"
        skeleton["ten_god_context"] = "偏印透干+忌神发力"
        # 从最近几年中选忌神年份
        js_year = _find_jishen_year(chart_data, birth_year, current_year)
        skeleton["event_year"] = js_year or (current_year - 3)
        skeleton["stem"] = _extract_dominant_stem(chart_data, "偏印|七杀")
        skeleton["targets"]["dimension"] = "jishen_year"
        skeleton["focus"] = "pressure_event"

    elif category == QuestionCategory.WANGSHUAI_SOMATIC:
        skeleton["event_type"] = "日主体感"
        skeleton["ten_god_context"] = "日主旺衰"
        skeleton["targets"]["dimension"] = "wangshuai"
        skeleton["focus"] = "health_perception"

    elif category == QuestionCategory.XIANGSHEN_VERIFY:
        skeleton["event_type"] = "相神流年"
        skeleton["ten_god_context"] = "相神发力+贵人相助"
        skeleton["event_year"] = current_year - 5
        skeleton["stem"] = _extract_dominant_stem(chart_data, "食神|正印")
        skeleton["targets"]["dimension"] = "xiangshen"
        skeleton["focus"] = "help_from_others"

    elif category == QuestionCategory.PATTERN_QUALITY:
        skeleton["event_type"] = "格局高低"
        skeleton["ten_god_context"] = "有情有力"
        skeleton["targets"]["dimension"] = "pattern_quality"

    return skeleton


def _extract_dominant_stem(chart_data: dict, pattern: str = "") -> str:
    """从四柱中提取与指定十神模式匹配的显眼天干。"""
    import re
    four_pillars = chart_data.get("four_pillars", {})
    for pos in ["month", "year", "hour"]:
        pillar = four_pillars.get(pos, {})
        stem = pillar.get("stem", "")
        if stem:
            return stem
    return ""


def _find_jishen_year(chart_data: dict, birth_year: int, current_year: int) -> Optional[int]:
    """从大运流年中找一个可能的忌神年份。"""
    dayun = chart_data.get("dayun", [])
    for d in dayun[:6]:
        start = d.get("start_year", d.start_year if hasattr(d, 'start_year') else 0)
        end = d.get("end_year", d.end_year if hasattr(d, 'end_year') else 0)
        # 找十神为忌神的大运
        tg = d.get("ten_god", getattr(d, 'ten_god', ''))
        if tg in ("偏印", "七杀", "伤官") and start > 0 and start < current_year:
            return start
    # 默认返回 3 年前
    return current_year - 3


def _build_targets(category: QuestionCategory, skeleton: dict) -> dict:
    """构建问题目标维度字典。"""
    return skeleton.get("targets", {"dimension": category.value})


# ============================================================
# 问题文本生成：AI 路径 + 典籍 RAG (V2 §9.2-9.3)
# ============================================================

# 类别 → RAG 检索阶段映射
_CATEGORY_TO_STAGE: dict[QuestionCategory, str] = {
    QuestionCategory.LIUQIN_SURVIVAL:   "liuqin",
    QuestionCategory.LIUQIN_RELATION:   "liuqin",
    QuestionCategory.DAYUN_EVENT:       "dayun",
    QuestionCategory.JISHEN_YEAR:       "chengbai",
    QuestionCategory.WANGSHUAI_SOMATIC: "wangshuai",
    QuestionCategory.XIANGSHEN_VERIFY:  "yongshen",
    QuestionCategory.PATTERN_QUALITY:   "pattern",
    QuestionCategory.PERSONALITY_TRAIT: "shishen",
}

# 类别 → RAG 关键词 (V2 §9.3.3)
_CATEGORY_KW: dict[QuestionCategory, list[str]] = {
    QuestionCategory.LIUQIN_SURVIVAL:   ["六亲", "父母", "宫位"],
    QuestionCategory.LIUQIN_RELATION:   ["兄弟", "夫妻", "十神"],
    QuestionCategory.DAYUN_EVENT:       ["大运", "流年", "应期"],
    QuestionCategory.JISHEN_YEAR:       ["忌神", "败因", "救应"],
    QuestionCategory.XIANGSHEN_VERIFY:  ["相神", "顺用", "逆用"],
    QuestionCategory.PATTERN_QUALITY:   ["有情", "有力", "格局", "通根"],
    QuestionCategory.WANGSHUAI_SOMATIC: ["旺衰", "得令", "得地"],
    QuestionCategory.PERSONALITY_TRAIT: ["性情", "五行"],
}


def _build_retrieval_keywords(skeleton: dict) -> list[str]:
    """V2-9.3.3: 从问题骨架生成 RAG 检索关键词。

    策略: 事件类型拆解 + 十神上下文 + 类别关键词 + 固定书签
    """
    keywords = []

    # Layer 1: 事件类型
    event_type = skeleton.get("event_type", "")
    if event_type:
        keywords.extend(event_type.replace(" ", "").replace("+", " ").split())

    # Layer 2: 十神上下文
    ten_god_context = skeleton.get("ten_god_context", "")
    if ten_god_context:
        keywords.extend(ten_god_context.replace("+", " ").replace("为", " ").split())

    # Layer 3: 类别关键词
    category_name = skeleton.get("category", "")
    for cat, kws in _CATEGORY_KW.items():
        if cat.value == category_name or cat == category_name:
            keywords.extend(kws)
            break

    # Layer 4: 固定典籍书签
    keywords.extend(["子平真诠", "滴天髓"])

    # 去重 + 限制 12 个
    seen = set()
    result = []
    for kw in keywords:
        if kw and kw not in seen:
            seen.add(kw)
            result.append(kw)
    return result[:12]


def _fetch_classical_context(skeleton: dict) -> str:
    """V2-9.3.1: 典籍 RAG 检索 + 清洗。"""
    try:
        from services.rag_retriever import retrieve_by_keywords
        from services.verification import _clean_classical_text

        keywords = _build_retrieval_keywords(skeleton)
        if not keywords:
            return ""

        results = retrieve_by_keywords(keywords, top_k=5)
        if not results:
            return ""

        texts = []
        for item in results[:3]:
            text = item.get("text", item.get("content", ""))
            if text:
                cleaned = _clean_classical_text(text)
                if cleaned:
                    texts.append(cleaned)

        return "\n\n".join(texts[:3])

    except ImportError:
        return ""
    except Exception as e:
        # RAG 失败静默降级
        return ""


def _build_ai_question_prompt(
    skeleton: dict,
    classical_context: str,
) -> str:
    """V2-9.3.2: 构建 AI 出题 Prompt——典籍原文 + 问题骨架 + 指令。"""
    event_year = skeleton.get("event_year", "")
    dayun_stage = skeleton.get("dayun_stage", "")
    event_type = skeleton.get("event_type", "")
    ten_god = skeleton.get("ten_god_context", "")
    stem = skeleton.get("stem", "")
    category = skeleton.get("category", "")

    parts = []

    if classical_context:
        parts.append(f"## 典籍原文（必须援引关键句）\n\n{classical_context[:800]}")

    parts.append(f"""## 问题骨架

- 验证类别：{category}
- 事件类型：{event_type}
- 十神上下文：{ten_god}
- 目标年份：{event_year}年""" + (f" ({dayun_stage})" if dayun_stage else "") + (f"""
- 关键天干：{stem}透干""" if stem else ""))

    parts.append("""## 指令

请基于以上典籍原文和问题骨架，生成一个自然语言问题。
要求：
1. 必须援引典籍原文的一句话（如"《子平真诠》有云：..."）
2. 用生活化语言提问，不含"十神""格局"等命理术语
3. 将典籍概念映射为日常可验证的事件
4. 问题控制在80字以内
5. 必须包含具体年份（如"{year}年前后"）
6. 只输出问题文本，不要解释""".replace("{year}", str(event_year) if event_year else "某"))

    return "\n\n".join(parts)


async def _try_ai_generate_question(
    skeleton: dict,
    category: QuestionCategory,
    chart_data: dict,
) -> str:
    """V2-9.2 调用点 1: AI + 典籍 RAG 生成自然语言问题。

    流程:
    1. RAG 检索典籍原文 → classical_context
    2. 构建 Prompt（典籍+骨架+指令）
    3. 调用 LLM → 自然语言问题
    4. 失败降级 → 模板

    Returns:
        自然语言问题文本
    """
    # 检查 LLM 可用性
    try:
        from services.verification import _has_llm, _llm_ask, SYSTEM_PROMPT
        if not _has_llm():
            return _template_generate_question(skeleton, category, chart_data)
    except ImportError:
        return _template_generate_question(skeleton, category, chart_data)

    # Step 1: RAG 检索
    classical_context = _fetch_classical_context(skeleton)

    # Step 2: 构建 Prompt
    prompt = _build_ai_question_prompt(skeleton, classical_context)

    # Step 3: LLM 调用
    try:
        ai_system = SYSTEM_PROMPT + "\n你是一个精通《子平真诠》和《滴天髓》的命理师。用户看不到你的内部推理，只看到你生成的问题。"
        result = await _llm_ask(ai_system, prompt, 300)
        if result and len(result.strip()) >= 10 and not result.startswith("[API_"):
            return result.strip()
    except Exception:
        pass

    # Step 4: 降级 → 模板
    return _template_generate_question(skeleton, category, chart_data)


# ============================================================
# 模板降级路径 (V2-9.5)
# ============================================================

def _template_generate_question(
    skeleton: dict,
    category: QuestionCategory,
    chart_data: dict = None,
) -> str:
    """V2-9.5 模板降级: 用骨架中的事件年份和十神拼装具体问题。

    相比旧版固定模板，此版本会使用 skeleton.event_year 生成具体年份。
    """
    event_year = skeleton.get("event_year")
    dayun_stage = skeleton.get("dayun_stage", "")

    # 有具体年份时生成精确问题
    if event_year:
        year_info = f"{event_year}年"
        if dayun_stage:
            year_info += f"（{dayun_stage}）"

        if category == QuestionCategory.JISHEN_YEAR:
            stem = skeleton.get("stem", "")
            return f"《子平真诠》有云：'忌神无制则祸生。' 在{year_info}前后，您是否遇到过较大的压力或困境？（比如工作变动、人际关系紧张、健康问题等）"
        elif category == QuestionCategory.DAYUN_EVENT:
            return f"在{year_info}左右，您是否经历过比较重大的职业变动或人生转折？（如换城市、换工作、创业、结婚等）"
        elif category == QuestionCategory.XIANGSHEN_VERIFY:
            return f"《滴天髓》云：'用神得助，富贵可期。' 在{year_info}前后，您是否得到过贵人相助或意外的好机会？"
        elif category == QuestionCategory.LIUQIN_RELATION:
            return f"在{year_info}（青少年时期），您的兄弟姐妹或密友是否对您的人生有较大影响？"

    # 无具体年份用固定模板
    _FIXED_TEMPLATES: dict[QuestionCategory, str] = {
        QuestionCategory.LIUQIN_SURVIVAL:
            "您的父母是否健在？或者年轻时父母关系中是否有过重大变故（如离异、长期分离等）？",
        QuestionCategory.DAYUN_EVENT:
            "在您 20-40 岁之间，是否经历过比较重大的职业变动或人生转折？",
        QuestionCategory.LIUQIN_RELATION:
            "您与兄弟姐妹的关系是否密切？他们是否在您的人生中起过重要作用？",
        QuestionCategory.JISHEN_YEAR:
            "在过去的某些年份，您是否感到压力特别大、诸事不顺？如果是，大概是哪几年？",
        QuestionCategory.WANGSHUAI_SOMATIC:
            "总体而言，您觉得自己的体质偏强还是偏弱？是否容易生病或感到疲劳？",
        QuestionCategory.XIANGSHEN_VERIFY:
            "在您遇到困难的时候，是否总能得到他人的帮助（如贵人、长辈、朋友）？",
        QuestionCategory.PATTERN_QUALITY:
            "您觉得自己的人生是顺利偏多、波折偏多、还是比较平淡？",
        QuestionCategory.PERSONALITY_TRAIT:
            "您觉得自己的性格偏外向还是内向？",
    }
    return _FIXED_TEMPLATES.get(category, "请描述您的基本情况。")


# ============================================================
# V2 验证入口 (V2 报告 §5.3 Step 2)
# ============================================================

async def init_verification_v2(
    chart_data: dict,
    user_id: Optional[str] = None,
    uncertainty=None,
    use_ai: Optional[bool] = None,
) -> VerificationSessionV2:
    """V2 验证会话初始化。

    V2-5.3 Step 2: 排盘 → 断前事。
    内部执行：六亲评估 → 问题序列编排 → 返回会话。

    Args:
        chart_data: 排盘数据（含 four_pillars, day_master, gender, strength_detail 等）
        user_id: 用户标识
        uncertainty: UncertaintyReport 或 None
        use_ai: 是否启用 AI。None 时自动检测 _has_llm()

    Returns:
        VerificationSessionV2: 包含问题序列的完整会话
    """
    # 确定 AI 模式
    if use_ai is None:
        try:
            from services.verification import _has_llm
            use_ai = _has_llm()
        except ImportError:
            use_ai = False

    # 推断 pattern + yongshen
    from rules.pattern import determine_pattern_type, determine_yongshen
    day_master = chart_data.get("day_master", "")
    month_branch = chart_data.get("four_pillars", {}).get("month", {}).get("branch", "")
    if not month_branch:
        month_data = chart_data.get("month_pillar", {})
        month_branch = month_data.get("branch", "") if isinstance(month_data, dict) else ""

    pattern = determine_pattern_type(day_master, month_branch)
    yongshen = determine_yongshen(pattern, day_master, month_branch, chart_data)

    # 六亲双轨评估
    liuqin_assessment = assess_liuqin(chart_data, pattern, yongshen)

    # 问题序列编排
    questions, count = await generate_question_sequence(
        chart_data=chart_data,
        liuqin_assessment=liuqin_assessment,
        uncertainty=uncertainty,
        use_ai=use_ai,
    )

    # 残余歧义 (V2-4.2: 单题后留存率 0.7)
    residual = round(0.70 ** count, 4)

    session_id = str(uuid.uuid4())

    session = VerificationSessionV2(
        session_id=session_id,
        user_id=user_id,
        chart_data=chart_data,
        phase="verification",
        current_question=questions[0] if questions else None,
        question_sequence=questions,
        question_count=count,
        residual_ambiguity=residual,
        answered=[],
        locked=False,
        lock_state=None,
        adjustment_history=[],
        use_ai=use_ai,
    )

    return session


async def regenerate_questions(
    session: VerificationSessionV2,
    adjustment: dict,
) -> list:
    """V2-4.3 第三段：根据参数修正结果重排问题。

    Args:
        session: 当前验证会话
        adjustment: 参数修正结果（含更新后的状态空间信息）

    Returns:
        更新后的问题序列
    """
    # 重新评估六亲（使用调整后的参数）
    pattern = adjustment.get("updated_pattern", session.chart_data.get("_pattern", ""))
    yongshen = adjustment.get("updated_yongshen", {})

    if not pattern:
        from rules.pattern import determine_pattern_type
        dm = session.chart_data.get("day_master", "")
        mb = session.chart_data.get("four_pillars", {}).get("month", {}).get("branch", "")
        pattern = determine_pattern_type(dm, mb)

    liuqin_assessment = assess_liuqin(session.chart_data, pattern, yongshen)

    questions, count = await generate_question_sequence(
        chart_data=session.chart_data,
        liuqin_assessment=liuqin_assessment,
        uncertainty=None,
        use_ai=session.use_ai,
    )

    # 更新会话
    session.question_sequence = questions
    session.question_count = count
    session.residual_ambiguity = round(0.70 ** count, 4)
    if questions:
        session.current_question = questions[0]

    return questions
