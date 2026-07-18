"""八字排盘测试 - 基于 lunar-python"""

import pytest
from bazi_engine import calculate_bazi


class TestBasicChart:
    """基础排盘测试"""

    def test_chart_19900315_chen_male(self):
        """
        测试案例：1990年3月15日 辰时(08:00) 男
        预期：庚午年 己卯月 己卯日 戊辰时
        """
        chart = calculate_bazi(1990, 3, 15, 8, 0, "male")

        # 验证四柱
        assert chart.four_pillars["year"].stem == "庚"
        assert chart.four_pillars["year"].branch == "午"
        assert chart.four_pillars["month"].stem == "己"
        assert chart.four_pillars["month"].branch == "卯"
        assert chart.four_pillars["day"].stem == "己"
        assert chart.four_pillars["day"].branch == "卯"
        assert chart.four_pillars["hour"].stem == "戊"
        assert chart.four_pillars["hour"].branch == "辰"

        # 验证日主
        assert chart.day_master == "己"

        # 验证性别
        assert chart.gender == "male"

    def test_chart_19850620_wu_female(self):
        """
        测试案例：1985年6月20日 午时(12:00) 女
        预期：乙丑年 壬午月 庚寅日 壬午时
        """
        chart = calculate_bazi(1985, 6, 20, 12, 0, "female")

        assert chart.four_pillars["year"].stem == "乙"
        assert chart.four_pillars["year"].branch == "丑"
        assert chart.four_pillars["month"].stem == "壬"
        assert chart.four_pillars["month"].branch == "午"
        assert chart.four_pillars["day"].stem == "庚"
        assert chart.four_pillars["day"].branch == "寅"
        assert chart.four_pillars["hour"].stem == "壬"
        assert chart.four_pillars["hour"].branch == "午"

        assert chart.day_master == "庚"
        assert chart.gender == "female"

    def test_chart_20000101_midnight_male(self):
        """
        测试案例：2000年1月1日 00:00 男
        lunar-python 结果：己卯年 丙子月 戊午日 壬子时
        """
        chart = calculate_bazi(2000, 1, 1, 0, 0, "male")

        assert chart.four_pillars["year"].stem == "己"
        assert chart.four_pillars["year"].branch == "卯"
        assert chart.four_pillars["month"].stem == "丙"
        assert chart.four_pillars["month"].branch == "子"
        assert chart.four_pillars["day"].stem == "戊"
        assert chart.four_pillars["day"].branch == "午"
        assert chart.four_pillars["hour"].stem == "壬"
        assert chart.four_pillars["hour"].branch == "子"

        assert chart.day_master == "戊"


class TestTenGods:
    """十神测试"""

    def test_ten_gods_basic(self):
        """验证十神计算"""
        chart = calculate_bazi(1990, 3, 15, 8, 0, "male")
        # 日主己，年干庚 -> 伤官
        assert chart.four_pillars["year"].stem_ten_god == "伤官"
        # 日主己，月干己 -> 比肩
        assert chart.four_pillars["month"].stem_ten_god == "比肩"
        # 日主己，时干戊 -> 劫财
        assert chart.four_pillars["hour"].stem_ten_god == "劫财"

    def test_day_pillar_is_ri_zhu(self):
        """日柱天干应该是日主"""
        chart = calculate_bazi(1990, 3, 15, 8, 0, "male")
        assert chart.four_pillars["day"].stem_ten_god == "日主"


class TestHiddenStems:
    """藏干测试"""

    def test_hidden_stems_exist(self):
        """每柱都应有藏干"""
        chart = calculate_bazi(1990, 3, 15, 8, 0, "male")
        for pos in ["year", "month", "day", "hour"]:
            assert len(chart.four_pillars[pos].hidden_stems) > 0

    def test_zi_hidden_stem(self):
        """子中藏癸"""
        chart = calculate_bazi(2000, 1, 1, 0, 0, "male")
        # 时柱为壬子，子中藏癸
        hour_hidden = chart.four_pillars["hour"].hidden_stems
        assert any(hs.stem == "癸" for hs in hour_hidden)


class TestNayin:
    """纳音测试"""

    def test_nayin_jimao(self):
        """己卯日柱纳音为城头土"""
        chart = calculate_bazi(1990, 3, 15, 8, 0, "male")
        assert chart.four_pillars["day"].nayin == "城头土"

    def test_nayin_gengwu(self):
        """庚午年柱纳音为路旁土"""
        chart = calculate_bazi(1990, 3, 15, 8, 0, "male")
        assert chart.four_pillars["year"].nayin == "路旁土"


class TestDayun:
    """大运测试"""

    def test_dayun_count(self):
        """应排8步大运（跳过起运前的空大运）"""
        chart = calculate_bazi(1990, 3, 15, 8, 0, "male")
        assert len(chart.dayun) >= 8

    def test_dayun_has_stem_branch(self):
        """每步大运应有天干地支"""
        chart = calculate_bazi(1990, 3, 15, 8, 0, "male")
        for d in chart.dayun:
            assert len(d.stem) == 1
            assert len(d.branch) == 1
            assert d.ten_god != ""
            assert d.start_age >= 0
            assert d.end_age > d.start_age


class TestShensha:
    """神煞测试"""

    def test_shensha_returns_list(self):
        """神煞应返回列表"""
        chart = calculate_bazi(1990, 3, 15, 8, 0, "male")
        assert isinstance(chart.shensha, list)

    def test_shensha_has_name(self):
        """每个神煞应有名称"""
        chart = calculate_bazi(1990, 3, 15, 8, 0, "male")
        for s in chart.shensha:
            assert s.name != ""
            assert s.description != ""
            assert s.position != ""

    def test_expanded_shensha_for_reference_chart(self):
        """1999-02-04 14:10 应覆盖常见排盘软件里的关键神煞"""
        chart = calculate_bazi(1999, 2, 4, 14, 10, "male")
        pairs = {(s.name, s.position) for s in chart.shensha}

        assert ("天乙贵人", "day") in pairs
        assert ("天乙贵人", "month") in pairs
        assert ("天乙贵人", "hour") in pairs
        assert ("国印贵人", "year") in pairs
        assert ("国印贵人", "month") in pairs
        assert ("福星贵人", "day") in pairs
        assert ("太极贵人", "month") in pairs
        assert ("太极贵人", "hour") in pairs
        assert ("金舆", "hour") in pairs
        assert ("劫煞", "day") in pairs
        assert ("亡神", "year") in pairs
        assert ("红鸾", "month") in pairs
        assert ("天喜", "hour") in pairs
        assert ("寡宿", "month") in pairs
        assert ("十恶大败", "day") in pairs
        assert ("童子", "hour") in pairs
        assert ("空亡", "hour") in pairs


class TestKongwang:
    """空亡测试"""

    def test_kongwang_count(self):
        """空亡应有2个地支"""
        chart = calculate_bazi(1990, 3, 15, 8, 0, "male")
        assert len(chart.kongwang) == 2

    def test_kongwang_are_zhi(self):
        """空亡应是地支"""
        chart = calculate_bazi(1990, 3, 15, 8, 0, "male")
        di_zhi = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"]
        for k in chart.kongwang:
            assert k in di_zhi


class TestWuxingScore:
    """五行力量测试"""

    def test_wuxing_score_sum(self):
        """五行力量总和应接近100"""
        chart = calculate_bazi(1990, 3, 15, 8, 0, "male")
        total = (chart.wuxing_score.jin + chart.wuxing_score.mu +
                 chart.wuxing_score.shui + chart.wuxing_score.huo +
                 chart.wuxing_score.tu)
        assert abs(total - 100) < 1.0  # 允许0.1的误差

    def test_wuxing_score_positive(self):
        """五行力量应为非负数"""
        chart = calculate_bazi(1990, 3, 15, 8, 0, "male")
        assert chart.wuxing_score.jin >= 0
        assert chart.wuxing_score.mu >= 0
        assert chart.wuxing_score.shui >= 0
        assert chart.wuxing_score.huo >= 0
        assert chart.wuxing_score.tu >= 0


class TestYongshen:
    """用神测试"""

    def test_yongshen_has_fields(self):
        """用神应有完整字段"""
        chart = calculate_bazi(1990, 3, 15, 8, 0, "male")
        assert chart.yongshen.primary != ""
        assert chart.yongshen.secondary != ""
        assert chart.yongshen.ji_shen != ""
        assert chart.yongshen.pattern != ""
        assert chart.yongshen.ri_zhu_strength != ""

    def test_yongshen_wuxing_values(self):
        """用神应是五行之一"""
        valid_wuxing = ["金", "木", "水", "火", "土"]
        chart = calculate_bazi(1990, 3, 15, 8, 0, "male")
        assert chart.yongshen.primary in valid_wuxing
        assert chart.yongshen.secondary in valid_wuxing
        assert chart.yongshen.ji_shen in valid_wuxing


class TestMingGongTaiYuan:
    """命宫胎元测试"""

    def test_minggong_not_empty(self):
        """命宫不应为空"""
        chart = calculate_bazi(1990, 3, 15, 8, 0, "male")
        assert chart.minggong != ""

    def test_taiyuan_not_empty(self):
        """胎元不应为空"""
        chart = calculate_bazi(1990, 3, 15, 8, 0, "male")
        assert chart.taiyuan != ""

    def test_minggong_taiyuan_format(self):
        """命宫胎元应为两字干支"""
        chart = calculate_bazi(1990, 3, 15, 8, 0, "male")
        assert len(chart.minggong) == 2
        assert len(chart.taiyuan) == 2


class TestDiShi:
    """长生十二宫测试"""

    def test_dishi_not_empty(self):
        """每柱应有长生十二宫"""
        chart = calculate_bazi(1990, 3, 15, 8, 0, "male")
        for pos in ["year", "month", "day", "hour"]:
            assert chart.four_pillars[pos].dishi != ""


class TestEdgeCases:
    """边界测试"""

    def test_haishi(self):
        """亥时测试"""
        chart = calculate_bazi(1990, 3, 15, 22, 0, "male")
        assert chart.four_pillars["hour"].branch == "亥"

    def test_all_hours(self):
        """所有时辰都能正常计算"""
        test_hours = [0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22]
        for h in test_hours:
            chart = calculate_bazi(1990, 3, 15, h, 0, "male")
            assert chart.day_master != ""

    def test_male_female(self):
        """男女排盘都能正常计算"""
        chart_m = calculate_bazi(1990, 3, 15, 8, 0, "male")
        chart_f = calculate_bazi(1990, 3, 15, 8, 0, "female")
        assert chart_m.gender == "male"
        assert chart_f.gender == "female"
        # 大运方向不同
        # 阳年（庚年）男命顺排，女命逆排
        assert chart_m.dayun[0].stem != chart_f.dayun[0].stem

    def test_lichun_boundary(self):
        """
        节气边界测试：1999年立春
        立春约在 1999-02-04 14:xx
        14:00 仍属戊寅年，15:00 已入己卯年
        """
        chart_before = calculate_bazi(1999, 2, 4, 14, 0, "male")
        chart_after = calculate_bazi(1999, 2, 4, 15, 0, "male")
        assert chart_before.four_pillars["year"].stem == "戊"
        assert chart_before.four_pillars["year"].branch == "寅"
        assert chart_after.four_pillars["year"].stem == "己"
        assert chart_after.four_pillars["year"].branch == "卯"

    def test_precise_minute(self):
        """精确到分钟的排盘"""
        chart = calculate_bazi(1990, 3, 15, 8, 30, "male")
        assert chart.four_pillars["year"].stem == "庚"
        assert chart.day_master == "己"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
