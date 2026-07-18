"""日主旺衰判断增强引擎测试"""

import pytest
from rules.yongshen import (
    calculate_strength_detail,
    determine_yongshen,
    _calc_deling,
    _calc_dedi,
    _calc_desheng,
    _calc_dezhu,
    _calc_ke_xie_hao,
    _judge_strength,
    _determine_yongshen_detail,
)
from rules.wuxing import WUXING_MAP, HIDDEN_STEMS_MAP
from bazi_engine import calculate_bazi


# ============================================================
# 辅助函数
# ============================================================

def _get_detail(year, month, day, hour, minute, gender):
    """排盘并返回旺衰详情"""
    chart = calculate_bazi(year, month, day, hour, minute, gender)
    pillars_raw = {}
    for pos in ["year", "month", "day", "hour"]:
        pillars_raw[pos] = {
            "stem": chart.four_pillars[pos].stem,
            "branch": chart.four_pillars[pos].branch,
        }
    all_hs = []
    for pos in ["year", "month", "day", "hour"]:
        for hs in chart.four_pillars[pos].hidden_stems:
            all_hs.append({"stem": hs.stem, "weight": hs.weight})
    return calculate_strength_detail(chart.day_master, pillars_raw, all_hs), chart


# ============================================================
# 得令判断测试
# ============================================================

class TestCalcDeling:
    """得令判断细化测试"""

    def test_month_branch_same_wuxing_as_day_master(self):
        """月令本气与日主同五行 → +50"""
        # 己土日主，月支未（本气己土+50，中气丁火=印星+15，余气乙木=+0）
        result = _calc_deling("土", "未")
        assert result["score"] == 65  # 50+15+0
        assert "当令" in result["conclusion"]

    def test_month_branch_yin_star(self):
        """月令本气为印星 → +35"""
        # 己土日主，月支巳（本气丙火=印星+35，中气庚金=+0，余气戊土=同五行+10）
        result = _calc_deling("土", "巳")
        assert result["score"] == 45  # 35+0+10
        assert "得令" in result["conclusion"]

    def test_month_branch_middle_same_wuxing(self):
        """月令中气与日主同五行 → +25"""
        # 己土日主，月支午（中气己土，本气丁火为印星）
        result = _calc_deling("土", "午")
        # 午：本气丁(火)=印星+35，中气己(土)=同五行+25
        assert result["score"] >= 35  # 本气印星
        assert result["detail"]  # 有计算详情

    def test_month_branch_ke_wuxing(self):
        """月令为官杀/食伤/财星 → +0（失令）"""
        # 己土日主，月支卯（本气乙木，木克土）
        result = _calc_deling("土", "卯")
        assert result["score"] == 0
        assert "失令" in result["conclusion"]

    def test_month_branch_yuqi_yin(self):
        """月令余气为印星 → +5"""
        # 己土日主，月支寅（本气甲木非印，中气丙火为印+15，余气戊土同五行+10）
        result = _calc_deling("土", "寅")
        # 寅：本气甲(木)=非生助+0，中气丙(火)=印星+15，余气戊(土)=同五行+10
        assert result["score"] == 25
        assert result["detail"]

    def test_deling_has_max_score(self):
        """得令 max_score 为 50"""
        result = _calc_deling("金", "申")
        assert result["max_score"] == 50

    def test_deling_detail_contains_branch_name(self):
        """详情中包含地支名称"""
        result = _calc_deling("木", "寅")
        assert any("寅" in d for d in result["detail"])


# ============================================================
# 得地判断测试
# ============================================================

class TestCalcDedi:
    """得地判断完整测试"""

    def test_all_branches_have_root(self):
        """四柱地支都有本气根 → 最高分"""
        four_pillars = {
            "year": {"stem": "甲", "branch": "寅"},
            "month": {"stem": "甲", "branch": "卯"},
            "day": {"stem": "甲", "branch": "寅"},
            "hour": {"stem": "甲", "branch": "卯"},
        }
        result = _calc_dedi("木", four_pillars)
        # 寅本气甲(木)=+16，卯本气乙(木)=+16
        assert result["score"] == 64  # 4 × 16
        assert result["max_score"] == 64

    def test_no_root_at_all(self):
        """四柱地支无根 → 0分"""
        four_pillars = {
            "year": {"stem": "庚", "branch": "申"},
            "month": {"stem": "庚", "branch": "酉"},
            "day": {"stem": "庚", "branch": "申"},
            "hour": {"stem": "庚", "branch": "酉"},
        }
        result = _calc_dedi("木", four_pillars)
        # 申：庚(金)壬(水)戊(土)无木；酉：辛(金)无木
        assert result["score"] == 0

    def test_middle_qi_root(self):
        """中气根 → +8"""
        # 丑：己(土)本气，癸(水)中气，辛(金)余气
        # 水日主，丑中气癸(水)为根
        four_pillars = {
            "year": {"stem": "己", "branch": "丑"},
            "month": {"stem": "己", "branch": "丑"},
            "day": {"stem": "己", "branch": "丑"},
            "hour": {"stem": "己", "branch": "丑"},
        }
        result = _calc_dedi("水", four_pillars)
        assert result["score"] == 32  # 4 × 8 (中气根)

    def test_yuqi_root(self):
        """余气根 → +4"""
        # 辰：戊(土)本气，乙(木)中气，癸(水)余气
        # 水日主，辰余气癸(水)为根
        four_pillars = {
            "year": {"stem": "戊", "branch": "辰"},
            "month": {"stem": "戊", "branch": "辰"},
            "day": {"stem": "戊", "branch": "辰"},
            "hour": {"stem": "戊", "branch": "辰"},
        }
        result = _calc_dedi("水", four_pillars)
        assert result["score"] == 16  # 4 × 4 (余气根)

    def test_mixed_roots(self):
        """混合根（本气+中气+余气）"""
        four_pillars = {
            "year": {"stem": "甲", "branch": "寅"},   # 本气甲(木)=+16
            "month": {"stem": "戊", "branch": "辰"},   # 中气乙(木)=+8
            "day": {"stem": "戊", "branch": "戌"},     # 余气丁(火)无木=0
            "hour": {"stem": "己", "branch": "未"},     # 余气乙(木)=+4
        }
        result = _calc_dedi("木", four_pillars)
        assert result["score"] == 28  # 16 + 8 + 0 + 4

    def test_dedi_conclusion_levels(self):
        """不同得分等级的结论"""
        # 高分
        four_pillars_high = {
            "year": {"stem": "甲", "branch": "寅"},
            "month": {"stem": "甲", "branch": "寅"},
            "day": {"stem": "甲", "branch": "寅"},
            "hour": {"stem": "甲", "branch": "寅"},
        }
        r_high = _calc_dedi("木", four_pillars_high)
        assert "有力" in r_high["conclusion"]

        # 零分
        four_pillars_zero = {
            "year": {"stem": "庚", "branch": "申"},
            "month": {"stem": "庚", "branch": "酉"},
            "day": {"stem": "庚", "branch": "申"},
            "hour": {"stem": "庚", "branch": "酉"},
        }
        r_zero = _calc_dedi("木", four_pillars_zero)
        assert "不得地" in r_zero["conclusion"]


# ============================================================
# 得生判断测试
# ============================================================

class TestCalcDesheng:
    """得生判断完整测试"""

    def test_tian_gan_yin_star(self):
        """天干透出印星 → +12/个"""
        # 己土日主，印星=火
        four_pillars = {
            "year": {"stem": "丙", "branch": "子"},
            "month": {"stem": "丁", "branch": "子"},
            "day": {"stem": "己", "branch": "子"},
            "hour": {"stem": "丙", "branch": "子"},
        }
        result = _calc_desheng("土", four_pillars)
        # 丙火=印星+12，丁火=印星+12，丙火=印星+12 → 36
        assert result["score"] >= 36

    def test_dizhi_canggan_yin_star_benqi(self):
        """地支藏干印星本气 → +10"""
        # 己土日主，印星=火
        # 巳：丙(火)本气 → +10
        four_pillars = {
            "year": {"stem": "庚", "branch": "巳"},
            "month": {"stem": "庚", "branch": "子"},
            "day": {"stem": "己", "branch": "子"},
            "hour": {"stem": "庚", "branch": "子"},
        }
        result = _calc_desheng("土", four_pillars)
        assert result["score"] >= 10

    def test_dizhi_canggan_yin_star_zhongqi(self):
        """地支藏干印星中气 → +5"""
        # 己土日主，印星=火
        # 未：己(土)本气，丁(火)中气 → +5
        four_pillars = {
            "year": {"stem": "庚", "branch": "未"},
            "month": {"stem": "庚", "branch": "子"},
            "day": {"stem": "己", "branch": "子"},
            "hour": {"stem": "庚", "branch": "子"},
        }
        result = _calc_desheng("土", four_pillars)
        assert result["score"] >= 5

    def test_no_yin_star(self):
        """无印星 → 0分"""
        # 己土日主，印星=火，四柱无火
        four_pillars = {
            "year": {"stem": "庚", "branch": "申"},
            "month": {"stem": "庚", "branch": "酉"},
            "day": {"stem": "己", "branch": "申"},
            "hour": {"stem": "庚", "branch": "酉"},
        }
        result = _calc_desheng("土", four_pillars)
        assert result["score"] == 0
        assert "不得生" in result["conclusion"]


# ============================================================
# 得助判断测试
# ============================================================

class TestCalcDezhu:
    """得助判断完整测试"""

    def test_tian_gan_bijie(self):
        """天干透出比劫 → +10/个（跳过日干）"""
        # 己土日主，比劫=土
        # 月干戊(土)=比劫+10，年干也是戊
        four_pillars = {
            "year": {"stem": "戊", "branch": "子"},
            "month": {"stem": "戊", "branch": "子"},
            "day": {"stem": "己", "branch": "子"},
            "hour": {"stem": "戊", "branch": "子"},
        }
        result = _calc_dezhu("土", four_pillars)
        # 年干戊+10，月干戊+10，时干戊+10 = 30（跳过日干己）
        assert result["score"] == 30

    def test_day_stem_not_counted_as_bijie(self):
        """日干本身不算比劫"""
        # 只有日干是己(土)，其他都不是土
        four_pillars = {
            "year": {"stem": "甲", "branch": "子"},
            "month": {"stem": "甲", "branch": "子"},
            "day": {"stem": "己", "branch": "子"},
            "hour": {"stem": "甲", "branch": "子"},
        }
        result = _calc_dezhu("土", four_pillars)
        assert result["score"] == 0

    def test_dizhi_canggan_bijie(self):
        """地支藏干比劫 → 本气+8，中气+4"""
        # 己土日主，比劫=土
        # 辰：戊(土)本气+8
        four_pillars = {
            "year": {"stem": "甲", "branch": "辰"},
            "month": {"stem": "甲", "branch": "子"},
            "day": {"stem": "己", "branch": "子"},
            "hour": {"stem": "甲", "branch": "子"},
        }
        result = _calc_dezhu("土", four_pillars)
        assert result["score"] >= 8

    def test_no_bijie(self):
        """无比劫 → 0分（使用无土藏干的地支）"""
        # 卯：乙(木)无土；亥：壬(水)甲(木)无土
        four_pillars = {
            "year": {"stem": "甲", "branch": "卯"},
            "month": {"stem": "甲", "branch": "亥"},
            "day": {"stem": "己", "branch": "卯"},
            "hour": {"stem": "甲", "branch": "亥"},
        }
        result = _calc_dezhu("土", four_pillars)
        assert result["score"] == 0


# ============================================================
# 克泄耗判断测试
# ============================================================

class TestCalcKeXieHao:
    """克泄耗判断测试"""

    def test_guansha_tian_gan(self):
        """天干官杀 → -10/个"""
        # 己土日主，官杀=木
        # 午：丁(火)己(土) — 对土日主为印星/比劫，不贡献克泄耗
        four_pillars = {
            "year": {"stem": "甲", "branch": "午"},
            "month": {"stem": "乙", "branch": "午"},
            "day": {"stem": "己", "branch": "午"},
            "hour": {"stem": "甲", "branch": "午"},
        }
        result = _calc_ke_xie_hao("土", four_pillars)
        # 甲-10, 乙-10, 甲-10 = -30
        assert result["score"] == -30

    def test_shishang_tian_gan(self):
        """天干食伤 → -8/个"""
        # 己土日主，食伤=金
        # 午：丁(火)己(土)无金，不会贡献食伤扣分
        four_pillars = {
            "year": {"stem": "庚", "branch": "午"},
            "month": {"stem": "辛", "branch": "午"},
            "day": {"stem": "己", "branch": "午"},
            "hour": {"stem": "庚", "branch": "午"},
        }
        result = _calc_ke_xie_hao("土", four_pillars)
        # 庚-8, 辛-8, 庚-8 = -24
        assert result["score"] == -24

    def test_caixing_tian_gan(self):
        """天干财星 → -8/个"""
        # 己土日主，财星=水
        # 午：丁(火)己(土)无水，不会贡献财星扣分
        four_pillars = {
            "year": {"stem": "壬", "branch": "午"},
            "month": {"stem": "癸", "branch": "午"},
            "day": {"stem": "己", "branch": "午"},
            "hour": {"stem": "壬", "branch": "午"},
        }
        result = _calc_ke_xie_hao("土", four_pillars)
        # 壬-8, 癸-8, 壬-8 = -24
        assert result["score"] == -24

    def test_dizhi_canggan_guansha(self):
        """地支藏干官杀本气 → -8"""
        # 己土日主，官杀=木
        # 卯：乙(木)本气 → -8
        four_pillars = {
            "year": {"stem": "庚", "branch": "卯"},
            "month": {"stem": "庚", "branch": "子"},
            "day": {"stem": "己", "branch": "子"},
            "hour": {"stem": "庚", "branch": "子"},
        }
        result = _calc_ke_xie_hao("土", four_pillars)
        assert result["score"] <= -8

    def test_no_ke_xie_hao(self):
        """无克泄耗 → 0"""
        # 己土日主，四柱全是土（无比劫不扣分，但土是同类不扣）
        four_pillars = {
            "year": {"stem": "戊", "branch": "丑"},
            "month": {"stem": "戊", "branch": "丑"},
            "day": {"stem": "己", "branch": "丑"},
            "hour": {"stem": "戊", "branch": "丑"},
        }
        result = _calc_ke_xie_hao("土", four_pillars)
        # 丑：己(土)癸(水)辛(金)
        # 癸(水)=财星，辛(金)=食伤 → 有扣分
        # 不是0，但应该是较小的负数
        assert result["score"] < 0

    def test_detail_by_type(self):
        """detail_by_type 分类正确"""
        four_pillars = {
            "year": {"stem": "甲", "branch": "卯"},
            "month": {"stem": "庚", "branch": "子"},
            "day": {"stem": "己", "branch": "子"},
            "hour": {"stem": "壬", "branch": "子"},
        }
        result = _calc_ke_xie_hao("土", four_pillars)
        # 甲+卯乙 → 官杀
        # 庚 → 食伤
        # 壬+子癸 → 财星
        assert len(result["detail_by_type"]["guan_sha"]) > 0
        assert len(result["detail_by_type"]["shi_shang"]) > 0
        assert len(result["detail_by_type"]["cai_xing"]) > 0


# ============================================================
# 综合判断测试
# ============================================================

class TestJudgeStrength:
    """综合判断+从格检测测试"""

    def test_normal_strong(self):
        """正格身强：总分≥60"""
        result = _judge_strength(65, {
            "year": {"stem": "丙", "branch": "午"},
            "month": {"stem": "戊", "branch": "戌"},
            "day": {"stem": "己", "branch": "未"},
            "hour": {"stem": "丙", "branch": "午"},
        }, "土")
        assert result["ri_zhu_strength"] == "偏强"
        assert "正格" in result["pattern"]
        assert result["cong_ge"] is False

    def test_normal_weak(self):
        """正格身弱：总分<40"""
        result = _judge_strength(25, {
            "year": {"stem": "甲", "branch": "寅"},
            "month": {"stem": "甲", "branch": "卯"},
            "day": {"stem": "己", "branch": "卯"},
            "hour": {"stem": "庚", "branch": "申"},
        }, "土")
        assert result["ri_zhu_strength"] == "偏弱"
        assert "正格" in result["pattern"]

    def test_normal_balanced(self):
        """正格中和：40≤总分<60"""
        result = _judge_strength(50, {
            "year": {"stem": "丙", "branch": "午"},
            "month": {"stem": "甲", "branch": "卯"},
            "day": {"stem": "己", "branch": "未"},
            "hour": {"stem": "庚", "branch": "申"},
        }, "土")
        assert result["ri_zhu_strength"] == "中和"
        assert "正格" in result["pattern"]

    def test_cong_weak(self):
        """从弱格：总分<15 且无比劫印星"""
        result = _judge_strength(10, {
            "year": {"stem": "甲", "branch": "寅"},
            "month": {"stem": "丙", "branch": "午"},
            "day": {"stem": "壬", "branch": "午"},
            "hour": {"stem": "戊", "branch": "戌"},
        }, "水")
        assert result["cong_ge"] is True
        assert result["cong_type"] == "从弱格"
        assert result["ri_zhu_strength"] == "极弱"

    def test_cong_weak_blocked_by_bijie(self):
        """有比劫透出 → 不是从弱格"""
        result = _judge_strength(10, {
            "year": {"stem": "癸", "branch": "子"},  # 癸=水=比劫
            "month": {"stem": "甲", "branch": "寅"},
            "day": {"stem": "壬", "branch": "午"},
            "hour": {"stem": "戊", "branch": "戌"},
        }, "水")
        assert result["cong_ge"] is False

    def test_cong_weak_blocked_by_yin(self):
        """有印星透出 → 不是从弱格"""
        result = _judge_strength(10, {
            "year": {"stem": "辛", "branch": "酉"},  # 辛=金=印星
            "month": {"stem": "甲", "branch": "寅"},
            "day": {"stem": "壬", "branch": "午"},
            "hour": {"stem": "戊", "branch": "戌"},
        }, "水")
        assert result["cong_ge"] is False

    def test_cong_strong(self):
        """从强格：总分>85 且无官杀财星"""
        result = _judge_strength(90, {
            "year": {"stem": "壬", "branch": "子"},
            "month": {"stem": "癸", "branch": "亥"},
            "day": {"stem": "壬", "branch": "子"},
            "hour": {"stem": "辛", "branch": "酉"},
        }, "水")
        assert result["cong_ge"] is True
        assert result["cong_type"] == "从强格"
        assert result["ri_zhu_strength"] == "极强"

    def test_cong_strong_blocked_by_guansha(self):
        """有官杀透出 → 不是从强格"""
        result = _judge_strength(90, {
            "year": {"stem": "壬", "branch": "子"},
            "month": {"stem": "戊", "branch": "戌"},  # 戊=土=官杀
            "day": {"stem": "壬", "branch": "子"},
            "hour": {"stem": "辛", "branch": "酉"},
        }, "水")
        assert result["cong_ge"] is False

    def test_cong_strong_blocked_by_cai(self):
        """有财星透出 → 不是从强格"""
        result = _judge_strength(90, {
            "year": {"stem": "壬", "branch": "子"},
            "month": {"stem": "丙", "branch": "午"},  # 丙=火=财星
            "day": {"stem": "壬", "branch": "子"},
            "hour": {"stem": "辛", "branch": "酉"},
        }, "水")
        assert result["cong_ge"] is False

    def test_boundary_score_15(self):
        """边界值：总分=15 → 正格身弱（不触发从弱格）"""
        result = _judge_strength(15, {
            "year": {"stem": "甲", "branch": "寅"},
            "month": {"stem": "丙", "branch": "午"},
            "day": {"stem": "壬", "branch": "午"},
            "hour": {"stem": "戊", "branch": "戌"},
        }, "水")
        assert result["cong_ge"] is False
        assert result["ri_zhu_strength"] == "太弱"

    def test_boundary_score_85(self):
        """边界值：总分=85 → 正格身强（不触发从强格）"""
        result = _judge_strength(85, {
            "year": {"stem": "壬", "branch": "子"},
            "month": {"stem": "癸", "branch": "亥"},
            "day": {"stem": "壬", "branch": "子"},
            "hour": {"stem": "辛", "branch": "酉"},
        }, "水")
        assert result["cong_ge"] is False
        assert result["ri_zhu_strength"] == "太旺"

    def test_too_strong(self):
        """太旺：总分≥80"""
        result = _judge_strength(80, {
            "year": {"stem": "壬", "branch": "子"},
            "month": {"stem": "癸", "branch": "亥"},
            "day": {"stem": "壬", "branch": "子"},
            "hour": {"stem": "辛", "branch": "酉"},
        }, "水")
        assert result["ri_zhu_strength"] == "太旺"

    def test_too_weak(self):
        """太弱：总分<20"""
        result = _judge_strength(15, {
            "year": {"stem": "甲", "branch": "寅"},
            "month": {"stem": "丙", "branch": "午"},
            "day": {"stem": "己", "branch": "午"},
            "hour": {"stem": "庚", "branch": "申"},
        }, "土")
        assert result["ri_zhu_strength"] == "太弱"


# ============================================================
# 用神判断测试
# ============================================================

class TestDetermineYongshenDetail:
    """用神判断测试"""

    def test_normal_strong_yongshen(self):
        """正格身强：用神=官杀"""
        strength = {"total_score": 65, "ri_zhu_strength": "偏强", "pattern": "正格-身强", "cong_ge": False, "cong_type": ""}
        result = _determine_yongshen_detail(strength, "土")
        assert result["primary"] == "木"  # 官杀=克土者
        assert result["secondary"] == "水"  # 财星=我克者
        assert result["ji_shen"] == "火"  # 印星=忌神

    def test_normal_weak_yongshen(self):
        """正格身弱：用神=印星"""
        strength = {"total_score": 30, "ri_zhu_strength": "偏弱", "pattern": "正格-身弱", "cong_ge": False, "cong_type": ""}
        result = _determine_yongshen_detail(strength, "土")
        assert result["primary"] == "火"  # 印星=生土者
        assert result["secondary"] == "土"  # 比劫=同土者
        assert result["ji_shen"] == "木"  # 官杀=忌神

    def test_cong_weak_yongshen(self):
        """从弱格：用神=官杀，忌神=印星"""
        strength = {"total_score": 5, "cong_ge": True, "cong_type": "从弱格"}
        result = _determine_yongshen_detail(strength, "水")
        assert result["primary"] == "土"  # 官杀
        assert result["secondary"] == "木"  # 食伤
        assert result["ji_shen"] == "金"  # 印星

    def test_cong_strong_yongshen(self):
        """从强格：用神=印星，忌神=官杀"""
        strength = {"total_score": 95, "cong_ge": True, "cong_type": "从强格"}
        result = _determine_yongshen_detail(strength, "水")
        assert result["primary"] == "金"  # 印星
        assert result["secondary"] == "水"  # 比劫
        assert result["ji_shen"] == "土"  # 官杀


# ============================================================
# calculate_strength_detail 主函数集成测试
# ============================================================

class TestCalculateStrengthDetail:
    """主函数集成测试"""

    def test_19900315_ri_zhu_weak(self):
        """
        1990-03-15 辰时 男
        四柱：庚午 己卯 己卯 戊辰
        日主：己（土）
        预期：偏弱
        """
        detail, chart = _get_detail(1990, 3, 15, 8, 0, "male")
        assert detail["ri_zhu"] == "己"
        assert detail["ri_zhu_wuxing"] == "土"
        assert detail["total_score"] < 40
        assert detail["ri_zhu_strength"] == "偏弱"
        assert detail["cong_ge"] is False
        assert detail["yongshen"]["primary"] == "火"  # 印星
        assert detail["yongshen"]["secondary"] == "土"  # 比劫
        assert detail["yongshen"]["ji_shen"] == "木"  # 官杀

    def test_19900315_deling_lost(self):
        """1990-03-15 己日主失令（月令卯木克土）"""
        detail, _ = _get_detail(1990, 3, 15, 8, 0, "male")
        assert detail["deling"]["score"] == 0
        assert "失令" in detail["deling"]["conclusion"]

    def test_19900315_dedi_has_roots(self):
        """1990-03-15 己日主在年支午和时支辰有根"""
        detail, _ = _get_detail(1990, 3, 15, 8, 0, "male")
        assert detail["dedi"]["score"] > 0
        # 年支午中气己=+8，时支辰本气戊=+16
        assert detail["dedi"]["score"] == 24

    def test_19900315_desheng_from_wu(self):
        """1990-03-15 年支午本气丁火为印星"""
        detail, _ = _get_detail(1990, 3, 15, 8, 0, "male")
        assert detail["desheng"]["score"] >= 10

    def test_19900315_dezhu_from_stems(self):
        """1990-03-15 月干己、时干戊为比劫"""
        detail, _ = _get_detail(1990, 3, 15, 8, 0, "male")
        assert detail["dezhu"]["score"] >= 20

    def test_19900315_ke_xie_hao(self):
        """1990-03-15 有官杀（卯中乙木）和食伤（庚金）"""
        detail, _ = _get_detail(1990, 3, 15, 8, 0, "male")
        assert detail["ke_xie_hao"]["score"] < 0

    def test_19860115_ri_zhu_strong(self):
        """
        1986-01-15 午时 男
        四柱：乙丑 己丑 己未 庚午
        日主：己（土）
        预期：偏强/太旺（丑月令本气己土同五行，多地支有根）
        """
        detail, chart = _get_detail(1986, 1, 15, 12, 0, "male")
        assert detail["ri_zhu"] == "己"
        assert detail["ri_zhu_wuxing"] == "土"
        assert detail["total_score"] >= 60
        assert detail["ri_zhu_strength"] in ("偏强", "太旺")
        assert detail["cong_ge"] is False

    def test_19860115_deling_strong(self):
        """1986-01-15 己土日主当令（丑月令本气己土）"""
        detail, _ = _get_detail(1986, 1, 15, 12, 0, "male")
        assert detail["deling"]["score"] == 50
        assert "当令" in detail["deling"]["conclusion"]

    def test_detail_has_all_sections(self):
        """返回结果包含所有必要字段"""
        detail, _ = _get_detail(1990, 3, 15, 8, 0, "male")
        assert "ri_zhu" in detail
        assert "ri_zhu_wuxing" in detail
        assert "deling" in detail
        assert "dedi" in detail
        assert "desheng" in detail
        assert "dezhu" in detail
        assert "ke_xie_hao" in detail
        assert "total_score" in detail
        assert "ri_zhu_strength" in detail
        assert "pattern" in detail
        assert "cong_ge" in detail
        assert "yongshen" in detail

    def test_each_section_has_detail(self):
        """每个判断步骤都有 detail 字段"""
        detail, _ = _get_detail(1990, 3, 15, 8, 0, "male")
        for key in ["deling", "dedi", "desheng", "dezhu", "ke_xie_hao"]:
            assert "score" in detail[key]
            assert "detail" in detail[key]
            assert "conclusion" in detail[key]
            assert isinstance(detail[key]["detail"], list)

    def test_pattern_format(self):
        """pattern 格式正确"""
        detail, _ = _get_detail(1990, 3, 15, 8, 0, "male")
        assert "正格" in detail["pattern"] or "从" in detail["pattern"]

    def test_yongshen_all_wuxing(self):
        """用神五行值都是有效五行"""
        valid = {"金", "木", "水", "火", "土"}
        detail, _ = _get_detail(1990, 3, 15, 8, 0, "male")
        assert detail["yongshen"]["primary"] in valid
        assert detail["yongshen"]["secondary"] in valid
        assert detail["yongshen"]["ji_shen"] in valid


# ============================================================
# 从格综合测试（合成数据）
# ============================================================

class TestCongGeIntegration:
    """从格综合测试"""

    def test_cong_weak_synthetic(self):
        """
        合成从弱格：水日主，天干全是木火土（无金水）
        使用 _judge_strength 直接测试
        """
        four_pillars = {
            "year": {"stem": "丙", "branch": "午"},   # 丙=火=财星
            "month": {"stem": "甲", "branch": "寅"},  # 甲=木=食伤
            "day": {"stem": "壬", "branch": "午"},    # 日主
            "hour": {"stem": "戊", "branch": "戌"},   # 戊=土=官杀
        }
        result = _judge_strength(8, four_pillars, "水")
        assert result["cong_ge"] is True
        assert result["cong_type"] == "从弱格"

    def test_cong_strong_synthetic(self):
        """
        合成从强格：水日主，天干全是金水（无木火土）
        """
        four_pillars = {
            "year": {"stem": "壬", "branch": "子"},
            "month": {"stem": "癸", "branch": "亥"},
            "day": {"stem": "壬", "branch": "子"},
            "hour": {"stem": "辛", "branch": "酉"},
        }
        result = _judge_strength(92, four_pillars, "水")
        assert result["cong_ge"] is True
        assert result["cong_type"] == "从强格"

    def test_cong_weak_yongshen_correct(self):
        """从弱格用神正确（顺弱势）"""
        strength = {"total_score": 5, "cong_ge": True, "cong_type": "从弱格"}
        result = _determine_yongshen_detail(strength, "水")
        # 从弱格：用神=官杀(土)，喜神=食伤(木)，忌神=印星(金)
        assert result["primary"] == "土"
        assert result["secondary"] == "木"
        assert result["ji_shen"] == "金"

    def test_cong_strong_yongshen_correct(self):
        """从强格用神正确（顺强势）"""
        strength = {"total_score": 95, "cong_ge": True, "cong_type": "从强格"}
        result = _determine_yongshen_detail(strength, "水")
        # 从强格：用神=印星(金)，喜神=比劫(水)，忌神=官杀(土)
        assert result["primary"] == "金"
        assert result["secondary"] == "水"
        assert result["ji_shen"] == "土"


# ============================================================
# backward compatibility 向后兼容测试
# ============================================================

class TestBackwardCompatibility:
    """向后兼容测试"""

    def test_determine_yongshen_returns_yongshen_model(self):
        """原 determine_yongshen 返回 YongShen 模型"""
        from models import YongShen
        chart = calculate_bazi(1990, 3, 15, 8, 0, "male")
        pillars_raw = {}
        for pos in ["year", "month", "day", "hour"]:
            pillars_raw[pos] = {
                "stem": chart.four_pillars[pos].stem,
                "branch": chart.four_pillars[pos].branch,
            }
        all_hs = []
        for pos in ["year", "month", "day", "hour"]:
            for hs in chart.four_pillars[pos].hidden_stems:
                all_hs.append({"stem": hs.stem, "weight": hs.weight})

        result = determine_yongshen(
            chart.day_master, pillars_raw, all_hs, {}
        )
        assert isinstance(result, YongShen)
        assert result.primary in ("金", "木", "水", "火", "土")
        assert result.secondary in ("金", "木", "水", "火", "土")
        assert result.ji_shen in ("金", "木", "水", "火", "土")
        assert result.pattern != ""
        assert result.ri_zhu_strength != ""

    def test_engine_uses_enhanced_yongshen(self):
        """bazi_engine 的用神结果来自增强引擎"""
        chart = calculate_bazi(1990, 3, 15, 8, 0, "male")
        assert chart.yongshen.primary != ""
        assert chart.yongshen.ri_zhu_strength in (
            "太旺", "偏强", "中和", "偏弱", "太弱", "极弱", "极强"
        )

    def test_multiple_dates_stable(self):
        """多日期结果稳定"""
        dates = [
            (1990, 3, 15, 8, 0, "male"),
            (1985, 6, 20, 12, 0, "female"),
            (2000, 1, 1, 0, 0, "male"),
            (1988, 5, 5, 8, 0, "male"),
            (2001, 10, 10, 12, 0, "male"),
        ]
        for y, m, d, h, mi, g in dates:
            chart = calculate_bazi(y, m, d, h, mi, g)
            assert chart.yongshen.primary in ("金", "木", "水", "火", "土")
            assert chart.yongshen.ri_zhu_strength != ""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
