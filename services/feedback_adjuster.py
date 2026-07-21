"""V2 三段反馈环 — 用户反馈处理与自适应调整

理论依据：
- V2 报告 §4.4: 三段反馈环（不可信度评估→参数修正→问题重排）
- V2 报告 §5.3: 参数锁定（≥70%匹配率）
- V2 报告 §5.4: 回退机制与降级路径
- V2 算法 §13: 贝叶斯状态空间更新
- V2 算法 §15: U(answer) 计算规则

暴露接口：
- process_feedback_v2(session, question_id, answer, note) → FeedbackResultV2
- lock_parameters(session) → LockState
- compute_unreliability(question, answer, note) → float
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Literal
import re
import datetime as dt

from services.discrimination import (
    VerificationSessionV2, AnsweredQuestion, QuestionCategory,
    regenerate_questions,
)
from services.safety_boundary import SafeState


# ============================================================
# 数据类
# ============================================================

@dataclass
class AdjustmentResult:
    """参数修正结果。

    V2-5.4: 包含 rollback_flag、reset_mode、降级标记。
    """
    lock_state: Optional[dict] = None
    rollback_flag: bool = False
    reset_mode: Literal["full", "partial", "none"] = "none"
    confidence_interval: tuple[float, float] = (0.0, 0.0)
    degraded: bool = False
    degraded_reason: Optional[str] = None
    # 冲突层级回查
    rollback_level: Optional[int] = None
    updated_pattern: str = ""
    updated_yongshen: dict = field(default_factory=dict)


@dataclass
class FeedbackResultV2:
    """V2 反馈处理结果。

    V2-7: Phase 3 输出，消费方为 main.py → 前端。
    """
    updated_session: Optional[VerificationSessionV2] = None
    next_question: Optional[dict] = None        # QuestionV2 或 None
    adjustment: Optional[AdjustmentResult] = None
    rollback_required: bool = False
    progress: float = 0.0
    ai_scores: Optional[dict] = None
    interpreted: Optional[dict] = None


# ============================================================
# U(answer) 计算规则 (V2 算法 §15)
# ============================================================

# 语义模糊度 α 默认值 (V2-9.4)
_ALPHA_DEFAULTS: dict[str, float] = {
    "六亲存亡":   0.10,   # 二值事实，模糊度极低
    "六亲关系":   0.25,
    "大运事件":   0.30,
    "忌神流年":   0.30,
    "相神验证":   0.35,
    "旺衰体感":   0.50,   # 连续体感，模糊度高
    "格局高低":   0.45,
    "性格特征":   0.70,   # 巴纳姆效应，模糊度最高
}

# 情感负载 γ 默认值 (V2-9.4)
_GAMMA_DEFAULTS: dict[str, float] = {
    "六亲存亡":   0.90,   # 父母故去→情感冲击极大
    "六亲关系":   0.55,
    "大运事件":   0.50,
    "忌神流年":   0.55,
    "相神验证":   0.40,
    "旺衰体感":   0.30,
    "格局高低":   0.35,
    "性格特征":   0.20,   # 日常琐事→情感负载低
}

# V2-4.4: 双阈值消除策略
# U(answer) < 0.30 → 高可信度，冲突时硬排除候选
# U(answer) ∈ [0.30, 0.50) → 中等可信度，冲突时仅降权
# U(answer) ≥ 0.50 → 不可信，使用默认值 0.5 不作贝叶斯更新
_EXCLUDE_THRESHOLD = 0.30
_DOWNWEIGHT_THRESHOLD = 0.50


def compute_unreliability(
    question: Optional[object] = None,  # QuestionV2 | dict | None
    answer: Literal["yes", "no", "unclear"] = "unclear",
    note: str = "",
    ai_scores: Optional[dict] = None,
    current_year: Optional[int] = None,
) -> float:
    """V2-4.4: 计算用户回答的不可信度 U(answer)。

    U(answer) = (α + (1 - β) + γ) / 3

    α = 语义模糊度: 二值事实≈0.1，连续体感≈0.7
    β = 事件时效: 最近→1，久远→0
    γ = 情感负载: 故去≈0.9，日常≈0.2

    Returns:
        U(answer) ∈ [0.0, 1.0], 0 = 完全可信, 1 = 完全不可信
    """
    if answer == "unclear":
        return 1.0  # 记不清了，不做排除

    # 提取 category
    category = _extract_category(question)

    # α: 语义模糊度
    alpha = _compute_alpha(category, note, ai_scores)

    # β: 事件时效
    beta = _compute_beta(question, note, ai_scores, current_year)

    # γ: 情感负载
    gamma = _compute_gamma(category, note, ai_scores)

    u = (alpha + (1.0 - beta) + gamma) / 3.0
    return round(min(max(u, 0.0), 1.0), 4)


def _extract_category(question) -> str:
    """从 QuestionV2 对象或字典中提取 category。"""
    if question is None:
        return "大运事件"
    if hasattr(question, 'category'):
        return question.category
    if isinstance(question, dict):
        return question.get("category", "大运事件")
    return "大运事件"


def _compute_alpha(category: str, note: str, ai_scores: Optional[dict]) -> float:
    """α: 语义模糊度 (V2-9.4)。"""
    if ai_scores is not None and ai_scores.get("calibration_ok"):
        return ai_scores.get("semantic_ambiguity", _ALPHA_DEFAULTS.get(category, 0.40))

    alpha = _ALPHA_DEFAULTS.get(category, 0.40)

    # 根据 note 微调
    if note:
        alpha = _adjust_alpha_by_note(alpha, note)

    return round(alpha, 4)


def _adjust_alpha_by_note(alpha: float, note: str) -> float:
    """根据用户补充说明微调 α。"""
    if re.search(r'\d{4}', note):
        alpha -= 0.15
    if re.search(r'[的确确]{1,2}', note):
        alpha -= 0.10
    if re.search(r'好像|大概|可能|也许|记不', note):
        alpha += 0.15
    if re.search(r'差不多|左右', note):
        alpha += 0.10
    return min(max(alpha, 0.0), 1.0)


def _compute_beta(question, note: str, ai_scores: Optional[dict],
                  current_year: Optional[int]) -> float:
    """β: 事件时效 (V2-9.4)。"""
    if current_year is None:
        current_year = dt.datetime.now().year

    if ai_scores is not None and ai_scores.get("calibration_ok"):
        return round(ai_scores.get("event_timeliness", 0.5), 4)

    # 从 skeleton 中获取事件年份，默认 20 年前
    event_year = current_year - 20
    if question is not None:
        skeleton = getattr(question, 'skeleton', None) or {}
        if isinstance(skeleton, dict) and skeleton.get("event_year"):
            event_year = skeleton["event_year"]

    year_diff = max(0, current_year - event_year)
    beta = max(0.0, 1.0 - year_diff / 50.0)
    return round(beta, 4)


def _compute_gamma(category: str, note: str, ai_scores: Optional[dict]) -> float:
    """γ: 情感负载 (V2-9.4)。"""
    if ai_scores is not None and ai_scores.get("calibration_ok"):
        return ai_scores.get("emotional_load", _GAMMA_DEFAULTS.get(category, 0.40))

    return _GAMMA_DEFAULTS.get(category, 0.40)


# ============================================================
# 冲突检测 (V2 算法 §13.4)
# ============================================================

def _determine_conflict_level(
    category: str,
    answer: str,
) -> Optional[int]:
    """V2-4.4: 冲突层级回查规则。

    六亲冲突 → Level 3（用神喜忌）
    大运冲突 → Level 2（格局判定）
    格局冲突 → Level 0-1（时辰/排盘）

    Returns:
        回查目标 Level，无冲突时返回 None。
    """
    if answer == "unclear":
        return None

    if category == "六亲存亡":
        return 3  # 回查至 Level 3
    elif category in ("大运事件", "忌神流年"):
        return 2  # 回查至 Level 2
    elif category in ("格局高低", "相神验证"):
        return 0  # 回查至 Level 0-1
    return None


# ============================================================
# process_feedback_v2() — 核心反馈处理 (V2 报告 §4.4 + V2 算法 §13.4)
# ============================================================

def process_feedback_v2(
    session: VerificationSessionV2,
    question_id: str,
    answer: Literal["yes", "no", "unclear"],
    note: str = "",
) -> FeedbackResultV2:
    """V2-4.4: 处理单条用户反馈。

    流程：
    1. 查找问题
    2. 保存回答
    3. 计算 U(answer)
    4. 冲突检测 → rollback_level
    5. 进度计算
    6. 下一题确定
    7. 降级检查

    Args:
        session: 当前验证会话
        question_id: 被回答的问题 ID
        answer: "yes" / "no" / "unclear"
        note: 用户补充说明

    Returns:
        FeedbackResultV2
    """
    # Step 1: 查找问题
    question = _find_question(session, question_id)
    if question is None:
        return FeedbackResultV2(
            updated_session=session,
            next_question=None,
            rollback_required=False,
            progress=0.0,
        )

    # Step 2: 保存回答
    category = getattr(question, 'category', "未知")
    answered = AnsweredQuestion(
        question_id=question_id,
        category=category,
        answer=answer,
        note=note,
    )
    session.answered.append(answered)

    # Step 3: 计算 U(answer)
    u_answer = compute_unreliability(
        question=question,
        answer=answer,
        note=note,
        ai_scores=None,  # AI 打分暂时不启用
    )

    # Step 4: 冲突检测
    adjustment = None
    rollback_required = False

    if answer != "unclear" and u_answer < _EXCLUDE_THRESHOLD:
        conflict_level = _determine_conflict_level(category, answer)
        if conflict_level is not None:
            rollback_required = True
            reset_mode = "partial" if conflict_level <= 3 else "full"

            # 构建调整结果 — 硬排除
            chart_data = session.chart_data
            dm = chart_data.get("day_master", "")
            mb = chart_data.get("four_pillars", {}).get("month", {}).get("branch", "")

            adjustment = AdjustmentResult(
                lock_state=session.lock_state,
                rollback_flag=True,
                reset_mode=reset_mode,
                rollback_level=conflict_level,
                confidence_interval=(0.0, 0.5),
                degraded=False,
                updated_pattern=chart_data.get("_pattern", ""),
                updated_yongshen=chart_data.get("_yongshen", {}),
            )
            session.adjustment_history.append(adjustment)
    elif answer != "unclear" and u_answer < _DOWNWEIGHT_THRESHOLD:
        # 中等可信度区间 [0.30, 0.50)：冲突时仅降权，不硬排除
        conflict_level = _determine_conflict_level(category, answer)
        if conflict_level is not None:
            # 降权：confidence 乘以 0.5 因子
            old_conf = session.lock_state.confidence
            session.lock_state.confidence = max(0.05, old_conf * 0.5)
            session.adjustment_history.append(
                AdjustmentResult(
                    lock_state=session.lock_state,
                    rollback_flag=False,  # 不触发回查
                    reset_mode="none",
                    rollback_level=None,
                    confidence_interval=(0.3, 0.7),
                    degraded=False,
                    updated_pattern="",
                    updated_yongshen={},
                )
            )

    # Step 5: 进度计算
    progress = _compute_progress(session)

    # Step 6: 下一题
    next_q = _get_next_question(session, question, answer)

    # Step 7: 降级检查 (V2-5.4)
    if len(session.answered) >= 3 and not rollback_required:
        # 检查是否连续未收敛
        if _check_non_convergence(session):
            if adjustment is None:
                adjustment = AdjustmentResult(
                    lock_state=session.lock_state,
                    rollback_flag=False,
                    reset_mode="none",
                    confidence_interval=(0.0, 0.5),
                    degraded=True,
                    degraded_reason="连续3轮未收敛",
                )
                session.adjustment_history.append(adjustment)
            else:
                adjustment.degraded = True
                adjustment.degraded_reason = (adjustment.degraded_reason or "") + " + 连续未收敛"

    # Step 8: 更新残余歧义
    answered_count = len(session.answered)
    if answered_count <= session.question_count:
        session.residual_ambiguity = round(0.70 ** (session.question_count - answered_count), 4)
    else:
        session.residual_ambiguity = 0.0

    return FeedbackResultV2(
        updated_session=session,
        next_question=next_q.model_dump() if hasattr(next_q, 'model_dump') else next_q,
        adjustment=adjustment,
        rollback_required=rollback_required,
        progress=progress,
    )


def _find_question(session: VerificationSessionV2, question_id: str):
    """在会话问题序列中查找指定问题。"""
    for q in session.question_sequence:
        if hasattr(q, 'id') and q.id == question_id:
            return q
    return None


def _compute_progress(session: VerificationSessionV2) -> float:
    """V2-5.3: 计算验证进度（基于已回答问题数 / 总题量）。"""
    total = max(session.question_count, 1)
    answered = len(session.answered)
    return round(min(answered / total, 1.0), 2)


def _get_next_question(session: VerificationSessionV2,
                       current_question, answer: str):
    """获取下一道问题。

    根据证伪分叉结构：
    - "yes" → if_true_next
    - "no" → if_false_next
    - "unclear" → if_unclear_next
    """
    if current_question is None:
        return session.question_sequence[0] if session.question_sequence else None

    # 根据回答选择下一题
    if answer == "yes":
        next_id = getattr(current_question, 'if_true_next', None)
    elif answer == "no":
        next_id = getattr(current_question, 'if_false_next', None)
    else:
        next_id = getattr(current_question, 'if_unclear_next', None)

    if next_id:
        return _find_question(session, next_id)

    # Fallback: 取序列中的下一题
    current_idx = -1
    for i, q in enumerate(session.question_sequence):
        if hasattr(q, 'id') and q.id == getattr(current_question, 'id', ''):
            current_idx = i
            break

    if current_idx >= 0 and current_idx + 1 < len(session.question_sequence):
        return session.question_sequence[current_idx + 1]

    return None


def _check_non_convergence(session: VerificationSessionV2) -> bool:
    """检查是否连续未收敛（V2-5.4 检查 10）。"""
    if len(session.answered) < 3:
        return False

    # 简单策略：如果最后 3 题都有冲突 → 未收敛
    recent = session.answered[-3:]
    conflicts = sum(
        1 for a in recent
        if _determine_conflict_level(getattr(a, 'category', ''), a.answer) is not None
    )
    return conflicts >= 3


# ============================================================
# 参数锁定：lock_parameters() (V2 报告 §5.3 Step 3)
# ============================================================

def lock_parameters(session: VerificationSessionV2) -> dict:
    """V2-5.3: 参数锁定——当验证进度 ≥70% 时执行。

    抽取 chart_data 中的最终参数作为 LockState。

    Returns:
        LockState {
            pattern_type: str,
            wangshuai_level: str,
            yongshen_wuxing: str,
            xishen_list: list[str],
            jishen_list: list[str],
            school_weights: dict,
            confidence: float,
            lock_timestamp: str,
        }
    """
    progress = _compute_progress(session)
    chart_data = session.chart_data

    # 抽取参数
    pattern_type = chart_data.get("_pattern", "")
    if not pattern_type:
        from rules.pattern import determine_pattern_type
        dm = chart_data.get("day_master", "")
        mb = chart_data.get("four_pillars", {}).get("month", {}).get("branch", "")
        pattern_type = determine_pattern_type(dm, mb)

    wangshuai_level = chart_data.get("wangshuai_level", "中和")
    strength = chart_data.get("strength_detail", {})
    if not wangshuai_level or wangshuai_level == "中和":
        wangshuai_level = strength.get("level", "中和")

    yongshen_data = chart_data.get("_yongshen", {})
    yongshen_wuxing = yongshen_data.get("five_element", "")

    # 如果无 yongshen 数据，回填
    if not yongshen_wuxing:
        from rules.pattern import determine_yongshen
        dm = chart_data.get("day_master", "")
        mb = chart_data.get("four_pillars", {}).get("month", {}).get("branch", "")
        ys = determine_yongshen(pattern_type, dm, mb, chart_data)
        yongshen_wuxing = ys.get("five_element", "未知")
        yongshen_data = ys

    # 学派权重（默认初始值）
    school_weights = {
        "格局派": 0.40,
        "旺衰派": 0.25,
        "调候派": 0.20,
        "盲派": 0.15,
    }

    # 置信度基于进度
    confidence = min(progress + 0.1, 0.95)

    lock_state = {
        "pattern_type": pattern_type,
        "wangshuai_level": wangshuai_level,
        "yongshen_wuxing": yongshen_wuxing,
        "xishen_list": yongshen_data.get("xishen_list", []),
        "jishen_list": yongshen_data.get("jishen_list", []),
        "school_weights": school_weights,
        "confidence": round(confidence, 2),
        "lock_timestamp": dt.datetime.now().isoformat(),
    }

    # 更新 session
    session.lock_state = lock_state
    session.locked = True
    session.phase = "locked"

    return lock_state


def check_lock_ready(session: VerificationSessionV2) -> bool:
    """检查是否达到参数锁定条件（≥70% 匹配率）。

    V2-5.3: ≥70% → 框架锁定；50%-70% → 逐级修正；<50% → 系统性修正。
    """
    progress = _compute_progress(session)
    return progress >= 0.70


def build_safe_state_from_session(session: VerificationSessionV2) -> SafeState:
    """从 V2 会话构建 SafeState（用于安全边界检查前）。"""
    if session.lock_state is None:
        return SafeState()

    from services.safety_boundary import build_safe_state as _build
    return _build(session.lock_state)
