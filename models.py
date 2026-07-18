"""八字排盘数据模型定义"""

from pydantic import BaseModel
from typing import Optional


class BirthInfo(BaseModel):
    """出生信息"""
    year: int
    month: int
    day: int
    hour: int       # 0-23，24小时制
    minute: int = 0  # 0-59，默认0
    gender: str      # "male" 或 "female"
    calendar_type: str = "solar"  # "solar"（阳历）或 "lunar"（农历）
    province: str = ""  # 出生省份（可选，用于真太阳时校正）
    city: str = ""      # 出生城市（可选，用于真太阳时校正）
    use_true_solar: bool = False  # 是否启用真太阳时校正


class GanZhi(BaseModel):
    """天干地支"""
    stem: str    # 天干
    branch: str  # 地支


class HiddenStem(BaseModel):
    """藏干"""
    stem: str
    weight: float
    ten_god: Optional[str] = None


class Pillar(BaseModel):
    """一柱信息"""
    stem: str
    branch: str
    stem_ten_god: str           # 天干十神
    branch_ten_god: str         # 地支十神（本气）
    hidden_stems: list[HiddenStem]  # 藏干
    nayin: str                  # 纳音
    dishi: str = ""             # 长生十二宫


class DayunPeriod(BaseModel):
    """大运一步"""
    stem: str
    branch: str
    ten_god: str
    start_age: int
    end_age: int
    start_year: int
    end_year: int


class ShenshaItem(BaseModel):
    """神煞"""
    name: str
    description: str
    position: str  # 在哪柱


class WuxingScore(BaseModel):
    """五行力量评分"""
    jin: float   # 金
    mu: float    # 木
    shui: float  # 水
    huo: float   # 火
    tu: float    # 土


class YongShen(BaseModel):
    """用神分析"""
    primary: str         # 用神五行（主用神）
    secondary: str       # 喜神五行
    ji_shen: str         # 忌神五行
    auxiliary: str = ""  # 辅用神（调候/格局所需的辅助元素）
    pattern: str         # 格局类型
    ri_zhu_strength: str # 日主强弱


class BaziChart(BaseModel):
    """完整八字排盘结果"""
    four_pillars: dict[str, Pillar]  # year, month, day, hour
    day_master: str                  # 日主（日干）
    gender: str
    dayun: list[DayunPeriod]
    shensha: list[ShenshaItem]
    kongwang: list[str]
    wuxing_score: WuxingScore
    yongshen: YongShen
    minggong: str = ""    # 命宫（如 "丙戌"）
    taiyuan: str = ""     # 胎元（如 "甲戌"）


class TrueSolarInfo(BaseModel):
    """真太阳时校正信息"""
    enabled: bool = False                # 是否启用真太阳时校正
    original_hour: int = 0               # 原始小时
    original_minute: int = 0             # 原始分钟
    corrected_hour: int = 0              # 校正后小时
    corrected_minute: int = 0            # 校正后分钟
    city: str = ""                       # 使用的城市
    longitude: float = 0.0               # 经度
    longitude_offset_minutes: float = 0  # 经度时差（分钟）
    eot_minutes: float = 0               # 均时差（分钟）
    total_offset_minutes: float = 0      # 总时差（分钟）
    description: str = ""                # 文字说明


# ============================================================
# P1 Phase 1: 断前事 + 逐条反馈
# ============================================================

class PreEventStatement(BaseModel):
    """单条断前事推断（大师先断过去让命主验证）"""
    id: str                     # "pred_01" ~ "pred_07"
    category: str               # "性格" | "父母关" | "兄弟关" | "学历" | "婚姻关" | "事业" | "关键年份"
    is_core: bool               # 是否核心三关（父母/兄弟/婚姻）
    sequence: int               # 1-7 展示顺序
    title: str                  # "先说说你的性格" 等
    content: str                # 推断内容（自然语言）
    classical_quote: str = ""   # 典籍引用
    basis: str = ""             # 命理依据
    confidence: float = 0.8     # 0.0-1.0


class FeedbackItem(BaseModel):
    """用户对单条推断的反馈"""
    prediction_id: str
    status: str                 # "accurate" | "partial" | "inaccurate" | "supplement"
    note: str = ""              # 补充说明
    session_id: str = ""        # 可选：前端会话ID，用于避免多会话 pred_01 冲突


class FeedbackRound(BaseModel):
    """一轮完整反馈"""
    round_number: int
    predictions: list[PreEventStatement]
    feedbacks: list[FeedbackItem]
