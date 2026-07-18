"""五行计算模块"""

import json
import os
from models import WuxingScore

_data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
with open(os.path.join(_data_dir, "wuxing_map.json"), "r", encoding="utf-8") as f:
    WUXING_MAP = json.load(f)

with open(os.path.join(_data_dir, "hidden_stems.json"), "r", encoding="utf-8") as f:
    HIDDEN_STEMS_MAP = json.load(f)

WUXING_KEYS = ["金", "木", "水", "火", "土"]

# 天干力量（阳干30，阴干20）
GAN_STRENGTH = {
    "甲": 30, "乙": 20, "丙": 30, "丁": 20, "戊": 30,
    "己": 20, "庚": 30, "辛": 20, "壬": 30, "癸": 20
}

# 地支本气力量
BRANCH_STRENGTH = {
    "子": 20, "丑": 16, "寅": 20, "卯": 20,
    "辰": 16, "巳": 20, "午": 20, "未": 16,
    "申": 20, "酉": 20, "戌": 16, "亥": 20
}


def get_wuxing(char: str) -> str:
    """获取字符的五行"""
    return WUXING_MAP.get(char, "")


def get_sheng(wuxing: str) -> str:
    """生我者（印星）"""
    sheng_map = {"金": "土", "木": "水", "水": "金", "火": "木", "土": "火"}
    return sheng_map.get(wuxing, "")


def get_ke(wuxing: str) -> str:
    """克我者（官杀）"""
    ke_map = {"金": "火", "木": "金", "水": "土", "火": "水", "土": "木"}
    return ke_map.get(wuxing, "")


def get_i_sheng(wuxing: str) -> str:
    """我生者（食伤）"""
    i_sheng_map = {"金": "水", "木": "火", "水": "木", "火": "土", "土": "金"}
    return i_sheng_map.get(wuxing, "")


def get_i_ke(wuxing: str) -> str:
    """我克者（财星）"""
    i_ke_map = {"金": "木", "木": "土", "水": "火", "火": "金", "土": "水"}
    return i_ke_map.get(wuxing, "")


def get_tonglei(wuxing: str) -> str:
    """同我者（比劫）"""
    return wuxing


def calculate_wuxing_score(four_pillars: dict, hidden_stems_list: list) -> WuxingScore:
    """
    计算八字中五行的相对力量

    考虑因素：
    1. 天干力量
    2. 地支本气力量
    3. 藏干力量（按权重）
    4. 月令加成（月支对同类五行加成1.5倍）
    """
    scores = {"金": 0.0, "木": 0.0, "水": 0.0, "火": 0.0, "土": 0.0}

    # 1. 天干力量
    for pos, pillar in four_pillars.items():
        wx = WUXING_MAP.get(pillar["stem"], "")
        if wx:
            scores[wx] += GAN_STRENGTH.get(pillar["stem"], 0)

    # 2. 地支本气力量
    for pos, pillar in four_pillars.items():
        wx = WUXING_MAP.get(pillar["branch"], "")
        if wx:
            scores[wx] += BRANCH_STRENGTH.get(pillar["branch"], 0)

    # 3. 藏干力量
    for hs in hidden_stems_list:
        wx = WUXING_MAP.get(hs["stem"], "")
        if wx:
            # 藏干力量 = 基础力量 * 权重
            base_strength = GAN_STRENGTH.get(hs["stem"], 20)
            scores[wx] += base_strength * hs["weight"]

    # 4. 月令加成（月支所属五行乘以1.5）
    month_branch = four_pillars["month"]["branch"]
    month_wx = WUXING_MAP.get(month_branch, "")
    if month_wx:
        scores[month_wx] *= 1.5

    # 归一化到 0-100
    total = sum(scores.values())
    if total == 0:
        return WuxingScore(jin=20.0, mu=20.0, shui=20.0, huo=20.0, tu=20.0)

    normalized = {k: round(v / total * 100, 1) for k, v in scores.items()}

    return WuxingScore(
        jin=normalized.get("金", 0),
        mu=normalized.get("木", 0),
        shui=normalized.get("水", 0),
        huo=normalized.get("火", 0),
        tu=normalized.get("土", 0)
    )
