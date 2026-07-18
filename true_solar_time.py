"""真太阳时校正工具

基于出生地经度计算真太阳时，用于精确的八字排盘时辰校正。

核心原理：
- 北京时间基于东经 120°（东八区标准子午线）
- 城市经度与 120° 的差值决定时差：每 1° = 4 分钟
- 例：成都（东经 104°），比北京时间晚 (120-104)×4 = 64 分钟
- 均时差（Equation of Time）：±15 分钟的季节性修正
"""

import math
from datetime import datetime


# 中国省会城市及主要城市经纬度（经度，纬度）
# 共 31 个直辖市/省会 + 香港/澳门/台北
CITY_COORDINATES: dict[str, tuple[float, float]] = {
    # 直辖市
    "北京": (116.40, 39.90),
    "上海": (121.47, 31.23),
    "天津": (117.20, 39.13),
    "重庆": (106.54, 29.59),
    # 省会城市
    "石家庄": (114.48, 38.03),
    "太原": (112.53, 37.87),
    "呼和浩特": (111.65, 40.82),
    "沈阳": (123.38, 41.80),
    "长春": (125.35, 43.88),
    "哈尔滨": (126.63, 45.75),
    "南京": (118.78, 32.04),
    "杭州": (120.19, 30.26),
    "合肥": (117.27, 31.86),
    "福州": (119.30, 26.08),
    "南昌": (115.89, 28.68),
    "济南": (117.00, 36.65),
    "郑州": (113.65, 34.76),
    "武汉": (114.31, 30.52),
    "长沙": (112.94, 28.22),
    "广州": (113.23, 23.16),
    "南宁": (108.33, 22.84),
    "海口": (110.35, 20.02),
    "成都": (104.06, 30.67),
    "贵阳": (106.71, 26.57),
    "昆明": (102.73, 25.04),
    "拉萨": (91.11, 29.97),
    "西安": (108.95, 34.27),
    "兰州": (103.73, 36.03),
    "西宁": (101.74, 36.56),
    "银川": (106.27, 38.47),
    "乌鲁木齐": (87.68, 43.77),
    # 特别行政区 / 台湾
    "香港": (114.17, 22.28),
    "澳门": (113.55, 22.19),
    "台北": (121.53, 25.05),
}

# 省份到省会的映射
PROVINCE_TO_CAPITAL: dict[str, str] = {
    "北京": "北京",
    "上海": "上海",
    "天津": "天津",
    "重庆": "重庆",
    "河北": "石家庄",
    "山西": "太原",
    "内蒙古": "呼和浩特",
    "辽宁": "沈阳",
    "吉林": "长春",
    "黑龙江": "哈尔滨",
    "江苏": "南京",
    "浙江": "杭州",
    "安徽": "合肥",
    "福建": "福州",
    "江西": "南昌",
    "山东": "济南",
    "河南": "郑州",
    "湖北": "武汉",
    "湖南": "长沙",
    "广东": "广州",
    "广西": "南宁",
    "海南": "海口",
    "四川": "成都",
    "贵州": "贵阳",
    "云南": "昆明",
    "西藏": "拉萨",
    "陕西": "西安",
    "甘肃": "兰州",
    "青海": "西宁",
    "宁夏": "银川",
    "新疆": "乌鲁木齐",
    "香港": "香港",
    "澳门": "澳门",
    "台湾": "台北",
}


def get_city_coordinates(city: str) -> tuple[float, float] | None:
    """获取城市经纬度

    Args:
        city: 城市名称（如 "成都"）

    Returns:
        (经度, 纬度) 元组，找不到则返回 None
    """
    # 先直接查找城市
    coords = CITY_COORDINATES.get(city)
    if coords:
        return coords

    # 尝试省份→省会映射
    capital = PROVINCE_TO_CAPITAL.get(city)
    if capital:
        return CITY_COORDINATES.get(capital)

    return None


def _day_of_year(month: int, day: int) -> int:
    """计算一年中的第几天"""
    days_in_month = [0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return sum(days_in_month[:month]) + day


def calculate_equation_of_time(year: int, month: int, day: int) -> float:
    """计算均时差（Equation of Time）

    均时差是真太阳时与平太阳时之间的差值，主要由地球轨道偏心率
    和黄赤交角引起，范围约 -15 到 +15 分钟。

    使用简化近似公式（Spencer, 1971）。

    Args:
        year: 公历年
        month: 公历月
        day: 公历日

    Returns:
        均时差值（分钟），正值表示真太阳时比平太阳时快
    """
    day_of_year = _day_of_year(month, day)
    # 辐角 B（弧度）= 2π * (day_of_year - 1) / 365
    b = 2 * math.pi * (day_of_year - 1) / 365.0

    # Spencer 公式（分钟）
    eot = 229.18 * (
        0.000075
        + 0.001868 * math.cos(b)
        - 0.032077 * math.sin(b)
        - 0.014615 * math.cos(2 * b)
        - 0.040849 * math.sin(2 * b)
    )
    return eot


def calculate_true_solar_time(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int,
    longitude: float,
) -> tuple[int, int]:
    """计算真太阳时

    Args:
        year: 公历年
        month: 公历月
        day: 公历日
        hour: 北京时间小时（0-23）
        minute: 北京时间分钟（0-59）
        longitude: 出生地经度（东经为正）

    Returns:
        (校正后小时, 校正后分钟) 元组

    示例：
        # 成都（东经 104.06°）
        # 经度差 = 120 - 104.06 = 15.94°
        # 时差 = 15.94 × 4 = 63.76 分钟
        # 成都比北京晚约 64 分钟
        # 北京时间 08:30 → 真太阳时约 07:26
        >>> h, m = calculate_true_solar_time(1990, 6, 15, 8, 30, 104.06)
        >>> h, m
        (7, 25)
    """
    # 1. 经度时差（分钟）：北京以东经120°为基准
    BEIJING_MERIDIAN = 120.0
    longitude_offset = (BEIJING_MERIDIAN - longitude) * 4.0
    # 注意：经度小于 120 的城市，时差为正（真太阳时比北京时间晚）
    # 但计算时我们需要减去这个时差

    # 2. 均时差
    eot = calculate_equation_of_time(year, month, day)

    # 3. 总时差（分钟）
    total_offset = longitude_offset - eot

    # 4. 应用时差
    total_minutes = hour * 60 + minute - total_offset

    # 5. 规范化到 0:00 - 23:59
    total_minutes = total_minutes % (24 * 60)
    if total_minutes < 0:
        total_minutes += 24 * 60

    corrected_hour = int(total_minutes // 60)
    corrected_minute = int(total_minutes % 60)

    return corrected_hour, corrected_minute


def resolve_birthplace(
    province: str = "",
    city: str = "",
) -> tuple[float | None, str]:
    """解析出生地并获取经度

    Args:
        province: 省份名称
        city: 城市名称

    Returns:
        (经度, 城市显示名称) 元组
    """
    # 先尝试用城市名查找
    if city:
        coords = get_city_coordinates(city)
        if coords:
            return coords[0], city

    # 再尝试用省份名查找
    if province:
        coords = get_city_coordinates(province)
        if coords:
            return coords[0], province

    # 都不匹配，尝试省份→省会
    if province:
        capital = PROVINCE_TO_CAPITAL.get(province)
        if capital:
            coords = get_city_coordinates(capital)
            if coords:
                return coords[0], capital

    return None, ""


# 城市列表（供前端使用）
CITY_LIST: list[dict] = [
    {"name": city, "province": province}
    for province, capital in PROVINCE_TO_CAPITAL.items()
    for city in [capital]
]
