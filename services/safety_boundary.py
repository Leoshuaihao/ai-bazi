"""V2 安全边界模块 — 信息隔离、时间边界、污染防御

理论依据：
- V2 报告 §2.4: 不可逆原则——断前事与断未来在数据和逻辑上严格隔离
- V2 报告 §5.4: 信息隔离（校验环境与预测环境物理分离）、时间边界检查、污染防御
- V2 报告 §5.4: 字段白名单校验、来源追溯审计

依赖：无规则层调用（纯安全校验模块）。
输入: SafeState (dataclass), Prediction (dataclass)
输出: ValidationResult (dataclass)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Literal
from datetime import datetime


# ============================================================
# 数据类
# ============================================================

@dataclass
class SafeState:
    """安全状态——仅包含抽象参数，绝不含命主事实信息。

    V2-5.4: LockState 经白名单过滤后生成 SafeState。
    """
    pattern_type: str = ""            # 格局类型
    wangshuai_level: str = ""         # 旺衰等级
    yongshen_wuxing: str = ""         # 用神五行
    xishen_list: list = field(default_factory=list)  # 喜神列表
    jishen_list: list = field(default_factory=list)  # 忌神列表
    school_weights: dict = field(default_factory=dict)  # 学派权重向量
    confidence: float = 0.0           # 整体置信度


@dataclass
class Prediction:
    """断未来预测——接受安全边界校验。

    V2-5.4: 每个预测附带 source_trail（追溯链）。
    """
    content: str                      # 预测文本
    time_range: tuple[int, int] = field(default_factory=lambda: (0, 0))  # 预测时间范围 (start_year, end_year)
    category: str = ""                # 预测类别
    confidence: float = 0.0
    source_trail: list[str] = field(default_factory=list)  # 追溯链
    # 注意：Prediction 不得包含任何命主事实信息
    _suspicious_fields: list[str] = field(default_factory=list, repr=False)


@dataclass
class ValidationResult:
    """安全校验结果。

    V2-5.4: 替代旧版 bool 返回，包含拒绝原因和泄漏字段。
    """
    is_valid: bool
    rejection_reason: Optional[str] = None  # INFO_LEAK | SCHOOL_VECTOR_ZERO | SAFE_STATE_EMPTY | TIME_BOUNDARY_EXCEEDED
    leaked_fields: list[str] = field(default_factory=list)
    source_trail: list[str] = field(default_factory=list)

    REASONS = {
        "INFO_LEAK": "预测包含用户事实信息，拒绝。",
        "SCHOOL_VECTOR_ZERO": "学派权重向量未初始化（全零），拒绝。",
        "SAFE_STATE_EMPTY": "SafeState 中存在空字段，拒绝。",
        "TIME_BOUNDARY_EXCEEDED": "预测时间范围超出许可边界，拒绝。",
    }

    def __bool__(self) -> bool:
        return self.is_valid


# ============================================================
# LockState → SafeState 转换
# ============================================================

def build_safe_state(lock_state: dict | SafeState) -> SafeState:
    """V2-5.4: 从 LockState 构建 SafeState（白名单过滤）。

    仅保留：格局类型、旺衰等级、用神五行、喜忌分类、学派权重。
    绝不含命主的具体事实信息。

    Args:
        lock_state: 锁定参数字典 或 已有 SafeState

    Returns:
        SafeState: 白名单过滤后的安全状态
    """
    if isinstance(lock_state, SafeState):
        return lock_state

    if isinstance(lock_state, dict):
        return SafeState(
            pattern_type=lock_state.get("pattern_type", ""),
            wangshuai_level=lock_state.get("wangshuai_level", ""),
            yongshen_wuxing=lock_state.get("yongshen_wuxing", ""),
            xishen_list=list(lock_state.get("xishen_list", [])),
            jishen_list=list(lock_state.get("jishen_list", [])),
            school_weights=dict(lock_state.get("school_weights", {})),
            confidence=float(lock_state.get("confidence", 0.0)),
        )

    # 降级：返回空 SafeState（将被 validate_prediction 拒绝）
    return SafeState()


# ============================================================
# 安全校验：validate_prediction()
# ============================================================

def validate_prediction(
    prediction: Prediction,
    safe_state: SafeState,
) -> ValidationResult:
    """V2-5.4: 安全边界校验——多维度检查预测请求是否合法。

    检查顺序：
    1. SafeState 完整性 → SAFE_STATE_EMPTY
    2. 学派权重 → SCHOOL_VECTOR_ZERO
    3. 信息泄漏 → INFO_LEAK
    4. 时间边界 → TIME_BOUNDARY_EXCEEDED

    Args:
        prediction: 预测请求（含 content、time_range、source_trail）
        safe_state: 白名单过滤后的安全参数

    Returns:
        ValidationResult: is_valid + rejection_reason + leaked_fields + source_trail
    """
    # === 检查 1: SafeState 完整性 ===
    # V2-5.4: SafeState 中任何关键字段为空时拒绝
    empty_check = _check_safe_state_completeness(safe_state)
    if not empty_check.is_valid:
        return empty_check

    # === 检查 2: 学派权重 ===
    # V2-5.4: 学派权重向量未初始化（全零）时拒绝
    weight_check = _check_school_weights(safe_state)
    if not weight_check.is_valid:
        return weight_check

    # === 检查 3: 信息泄漏 ===
    # V2-5.4: 字段白名单校验——预测中不得包含命主事实信息
    leak_check = _check_info_leak(prediction)
    if not leak_check.is_valid:
        return leak_check

    # === 检查 4: 时间边界 ===
    # V2-5.4: 预测时间范围必须 > 当前日期
    time_check = _check_time_boundary(prediction)
    if not time_check.is_valid:
        return time_check

    # === 全部通过 ===
    return ValidationResult(
        is_valid=True,
        source_trail=prediction.source_trail + ["safety_boundary:validated"],
    )


# ============================================================
# 内部检查函数
# ============================================================

# SafeState 必须非空的关键字段
_REQUIRED_SAFE_STATE_FIELDS = [
    "pattern_type",
    "wangshuai_level",
    "yongshen_wuxing",
]


def _check_safe_state_completeness(safe_state: SafeState) -> ValidationResult:
    """检查 13: SafeState 中关键字段为空时拒绝。"""
    for field_name in _REQUIRED_SAFE_STATE_FIELDS:
        value = getattr(safe_state, field_name, "")
        if not value or (isinstance(value, str) and not value.strip()):
            return ValidationResult(
                is_valid=False,
                rejection_reason="SAFE_STATE_EMPTY",
                leaked_fields=[field_name],
                source_trail=["safety_boundary:failed:SAFE_STATE_EMPTY"],
            )
    return ValidationResult(is_valid=True)


def _check_school_weights(safe_state: SafeState) -> ValidationResult:
    """检查 14: 学派权重向量全零时拒绝。"""
    weights = safe_state.school_weights
    if not isinstance(weights, dict) or len(weights) == 0:
        return ValidationResult(
            is_valid=False,
            rejection_reason="SCHOOL_VECTOR_ZERO",
            source_trail=["safety_boundary:failed:SCHOOL_VECTOR_ZERO"],
        )

    # 如果有键值，检查是否全部为零
    all_zero = all(v == 0.0 or v == 0 for v in weights.values())
    if all_zero:
        return ValidationResult(
            is_valid=False,
            rejection_reason="SCHOOL_VECTOR_ZERO",
            source_trail=["safety_boundary:failed:SCHOOL_VECTOR_ZERO"],
        )

    return ValidationResult(is_valid=True)


def _check_info_leak(prediction: Prediction) -> ValidationResult:
    """检查 11: 预测中是否包含命主事实信息。

    通过关键词扫描检测可能的泄漏。
    """
    # 敏感事实关键词（可能出现在预测中表示泄漏）
    _FACT_SIGNALS = [
        "父亲已故", "母亲已故", "父亲在", "母亲在", "父亲健在", "母亲健在",
        "父母离异", "用户反馈", "命主说", "根据你的反馈",
        "你之前说过", "上次你提到",
    ]

    leaked = []
    content_lower = prediction.content.lower() if prediction.content else ""

    for signal in _FACT_SIGNALS:
        if signal.lower() in content_lower:
            leaked.append(signal)

    if leaked:
        return ValidationResult(
            is_valid=False,
            rejection_reason="INFO_LEAK",
            leaked_fields=leaked,
            source_trail=["safety_boundary:failed:INFO_LEAK"],
        )

    # 额外检查 suspicious_fields
    if prediction._suspicious_fields:
        return ValidationResult(
            is_valid=False,
            rejection_reason="INFO_LEAK",
            leaked_fields=prediction._suspicious_fields,
            source_trail=["safety_boundary:failed:INFO_LEAK"],
        )

    return ValidationResult(is_valid=True)


def _check_time_boundary(prediction: Prediction) -> ValidationResult:
    """检查 12: 预测时间范围必须 > 当前日期。

    V2-5.4: 若预测中出现 < 当前日期的"未来"推断，标记为时间边界穿越。
    """
    current_year = datetime.now().year
    start_year, end_year = prediction.time_range

    if start_year > 0 and start_year < current_year:
        return ValidationResult(
            is_valid=False,
            rejection_reason="TIME_BOUNDARY_EXCEEDED",
            source_trail=[f"safety_boundary:failed:TIME_BOUNDARY_EXCEEDED "
                          f"(prediction start={start_year} < current={current_year})"],
        )

    return ValidationResult(is_valid=True)


# ============================================================
# 便捷函数
# ============================================================

def quick_validate(
    prediction_content: str,
    safe_state: SafeState,
    time_range: tuple[int, int] = (0, 0),
    category: str = "general",
    confidence: float = 0.0,
) -> ValidationResult:
    """快捷校验：一行代码完成预测安全性检查。

    Args:
        prediction_content: 预测文本
        safe_state: 安全状态
        time_range: (开始年, 结束年)
        category: 预测类别
        confidence: 置信度

    Returns:
        ValidationResult
    """
    pred = Prediction(
        content=prediction_content,
        time_range=time_range,
        category=category,
        confidence=confidence,
        source_trail=["quick_validate"],
    )
    return validate_prediction(pred, safe_state)
