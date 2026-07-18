"""流年流月计算模块测试"""

import pytest
from services.liunian import (
    get_liunian,
    get_liunian_list,
    get_liuyue,
    get_liuyue_list,
    classify_liunian,
)


class TestGetLiunian:
    """流年干支计算测试"""

    def test_jiazi_base_year(self):
        """公元4年为甲子年（干支纪年起算点）"""
        result = get_liunian(4)
        assert result["stem"] == "甲"
        assert result["branch"] == "子"
        assert result["ganzhi"] == "甲子"
        assert result["wuxing"] == "木"

    def test_1984_jiazi(self):
        """1984年是甲子年（近代基准年，1984-4=1980≡0 mod 60）"""
        result = get_liunian(1984)
        assert result["ganzhi"] == "甲子"
        assert result["wuxing"] == "木"

    def test_2025_yisi(self):
        """2025年应为乙巳年"""
        result = get_liunian(2025)
        assert result["ganzhi"] == "乙巳"
        assert result["stem"] == "乙"
        assert result["branch"] == "巳"
        assert result["wuxing"] == "木"

    def test_2027_dingwei(self):
        """2027年应为丁未年"""
        result = get_liunian(2027)
        assert result["ganzhi"] == "丁未"
        assert result["wuxing"] == "火"

    def test_2030_gengxu(self):
        """2030年应为庚戌年"""
        result = get_liunian(2030)
        assert result["ganzhi"] == "庚戌"
        assert result["wuxing"] == "金"


class TestGetLiunianList:
    """流年列表测试"""

    def test_eight_years_from_2025(self):
        """2025年起连续8年列表"""
        result = get_liunian_list(2025, count=8)
        assert len(result) == 8
        ganzhi_list = [r["ganzhi"] for r in result]
        assert ganzhi_list == ["乙巳", "丙午", "丁未", "戊申", "己酉", "庚戌", "辛亥", "壬子"]
        # 验证年份递增
        assert result[0]["year"] == 2025
        assert result[7]["year"] == 2032


class TestGetLiuyue:
    """流月干支计算测试"""

    def test_2027_month1_wuyin(self):
        """2027年（丁年）正月应为壬寅（丁壬壬位顺行流）"""
        result = get_liuyue(2027, 1)
        assert result["ganzhi"] == "壬寅"
        assert result["wuxing"] == "水"
        assert result["month"] == 1

    def test_2027_month5_bingwu(self):
        """2027年五月（午月）应为丙午"""
        result = get_liuyue(2027, 5)
        assert result["ganzhi"] == "丙午"
        assert result["wuxing"] == "火"

    def test_2027_month12_guichou(self):
        """2027年十二月（丑月）应为癸丑"""
        result = get_liuyue(2027, 12)
        assert result["ganzhi"] == "癸丑"
        assert result["wuxing"] == "水"

    def test_2025_month1_wuyin(self):
        """2025年（乙年）正月应为戊寅（乙庚之岁戊为头）"""
        result = get_liuyue(2025, 1)
        assert result["ganzhi"] == "戊寅"
        assert result["wuxing"] == "土"

    def test_invalid_month_raises(self):
        """无效月份应抛出 ValueError"""
        with pytest.raises(ValueError, match="1-12"):
            get_liuyue(2027, 0)
        with pytest.raises(ValueError, match="1-12"):
            get_liuyue(2027, 13)


class TestGetLiuyueList:
    """全年流月列表测试"""

    def test_12_months(self):
        """应返回12个月"""
        result = get_liuyue_list(2027)
        assert len(result) == 12
        # 月份应递增
        assert [r["month"] for r in result] == list(range(1, 13))

    def test_yuezhi_order(self):
        """十二地支顺序：寅卯辰巳午未申酉戌亥子丑"""
        result = get_liuyue_list(2027)
        branches = [r["branch"] for r in result]
        assert branches == ["寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥", "子", "丑"]


class TestClassifyLiunian:
    """流年分类判断测试"""

    # 命主参数：日主庚（金），用神土，忌神火
    # 丁未年：天干丁=火（忌神），地支未=土（用神）→ 天干优先 → 忌神年
    # 戊申年：天干戊=土（用神）→ 用神年
    # 甲辰年：天干甲=木（平），地支辰=土（用神）→ 用神年
    # 己酉年：天干己=土（用神）→ 用神年
    # 壬子年：天干壬=水（平），地支子=水（平）→ 平年

    DM = "庚"       # 日主庚金
    YS = "土"       # 用神土
    JS = "火"       # 忌神火

    def test_yongshen_year_from_stem(self):
        """天干直接为用神 → 用神年（戊申年，天干戊=土=用神）"""
        ln = get_liunian(2028)  # 戊申
        result = classify_liunian(ln, self.DM, self.YS, self.JS)
        assert result["is_yongshen_year"] is True
        assert result["is_ji_shen_year"] is False
        assert result["label"] == "用神年✅"
        assert result["ten_god"] == "偏印"  # 戊(土)生庚(金)，同阴阳→偏印
        assert "用神土" in result["advice"]

    def test_yongshen_year_from_branch(self):
        """地支为用神 → 用神年（甲辰年，地支辰=土=用神，天干甲=木=平）"""
        ln = get_liunian(2024)  # 甲辰
        result = classify_liunian(ln, self.DM, self.YS, self.JS)
        assert result["is_yongshen_year"] is True
        assert result["is_ji_shen_year"] is False
        assert result["label"] == "用神年✅"

    def test_ji_shen_year_stem_priority(self):
        """干支同时涉及用神和忌神，天干优先 → 忌神年"""
        # 丁未年：天干丁=火=忌神，地支未=土=用神 → 天干忌神 → 忌神年
        ln = get_liunian(2027)  # 丁未
        result = classify_liunian(ln, self.DM, self.YS, self.JS)
        assert result["is_yongshen_year"] is False
        assert result["is_ji_shen_year"] is True
        assert result["label"] == "忌神年⚠️"
        assert result["ten_god"] == "正官"  # 丁(火)克庚(金)，阴阳不同→正官
        assert "忌神火" in result["advice"]

    def test_ping_nian(self):
        """干支均非用神非忌神 → 平年（壬子年，壬=水=平，子=水=平）"""
        ln = get_liunian(2032)  # 壬子
        result = classify_liunian(ln, self.DM, self.YS, self.JS)
        assert result["is_yongshen_year"] is False
        assert result["is_ji_shen_year"] is False
        assert result["label"] == "平年"
        assert result["ten_god"] == "食神"  # 庚(金)生壬(水)，同阴阳→食神

    def test_all_ten_gods_present(self):
        """验证十神字段不为空"""
        ln = get_liunian(2025)  # 乙巳
        result = classify_liunian(ln, self.DM, self.YS, self.JS)
        assert result["ten_god"] != ""
        assert isinstance(result["ten_god"], str)
