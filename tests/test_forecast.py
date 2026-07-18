"""P2 断未来测试：未来运势预测逻辑"""

import pytest
import sys
import os
import datetime
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.forecast import (
    _find_current_dayun,
    _get_upcoming_dayun,
    _get_key_years_from_dayun,
    _build_dayun_summary,
    generate_mock_forecast,
    _parse_forecast_json,
    generate_forecast,
    _mock_career_forecast,
    _mock_wealth_forecast,
    _mock_marriage_forecast,
    _mock_health_forecast,
)


# ============================================================
# 测试夹具
# ============================================================

@pytest.fixture
def sample_chart():
    """构建一个测试用的 BaziChart 对象"""
    from models import (
        BaziChart, Pillar, HiddenStem,
        DayunPeriod, ShenshaItem, WuxingScore, YongShen,
    )

    pillars = {
        "year": Pillar(
            stem="甲", branch="子", stem_ten_god="食神",
            branch_ten_god="正印", hidden_stems=[
                HiddenStem(stem="癸", weight=10.0, ten_god="正印")
            ], nayin="海中金", dishi="沐浴"
        ),
        "month": Pillar(
            stem="丙", branch="寅", stem_ten_god="正官",
            branch_ten_god="比肩", hidden_stems=[
                HiddenStem(stem="甲", weight=6.0, ten_god="比肩"),
                HiddenStem(stem="丙", weight=3.0, ten_god="正官"),
                HiddenStem(stem="戊", weight=1.0, ten_god="偏财"),
            ], nayin="炉中火", dishi="临官"
        ),
        "day": Pillar(
            stem="戊", branch="辰", stem_ten_god="日主",
            branch_ten_god="比肩", hidden_stems=[
                HiddenStem(stem="戊", weight=6.0, ten_god="比肩"),
                HiddenStem(stem="乙", weight=3.0, ten_god="正官"),
                HiddenStem(stem="癸", weight=1.0, ten_god="正财"),
            ], nayin="大林木", dishi="冠带"
        ),
        "hour": Pillar(
            stem="庚", branch="申", stem_ten_god="食神",
            branch_ten_god="食神", hidden_stems=[
                HiddenStem(stem="庚", weight=6.0, ten_god="食神"),
                HiddenStem(stem="壬", weight=3.0, ten_god="偏财"),
                HiddenStem(stem="戊", weight=1.0, ten_god="比肩"),
            ], nayin="石榴木", dishi="病"
        ),
    }

    current_year = datetime.datetime.now().year
    dayun = [
        DayunPeriod(
            stem="乙", branch="丑", ten_god="正官",
            start_age=5, end_age=14,
            start_year=1995, end_year=2004,
        ),
        DayunPeriod(
            stem="甲", branch="子", ten_god="七杀",
            start_age=15, end_age=24,
            start_year=2005, end_year=2014,
        ),
        DayunPeriod(
            stem="癸", branch="亥", ten_god="正财",
            start_age=25, end_age=34,
            start_year=2015, end_year=2024,
        ),
        DayunPeriod(
            stem="壬", branch="戌", ten_god="偏财",
            start_age=35, end_age=44,
            start_year=2025, end_year=2034,
        ),
        DayunPeriod(
            stem="辛", branch="酉", ten_god="伤官",
            start_age=45, end_age=54,
            start_year=2035, end_year=2044,
        ),
        DayunPeriod(
            stem="庚", branch="申", ten_god="食神",
            start_age=55, end_age=64,
            start_year=2045, end_year=2054,
        ),
    ]

    shensha = [
        ShenshaItem(name="文昌", description="主聪明好学", position="年柱"),
        ShenshaItem(name="天乙贵人", description="主贵人扶持", position="日柱"),
    ]

    wuxing_score = WuxingScore(
        jin=15.0, mu=20.0, shui=10.0, huo=15.0, tu=40.0
    )

    yongshen = YongShen(
        primary="金",
        secondary="水",
        ji_shen="火",
        pattern="正格",
        ri_zhu_strength="身旺",
    )

    chart = BaziChart(
        four_pillars=pillars,
        day_master="戊",
        gender="male",
        dayun=dayun,
        shensha=shensha,
        kongwang=["戌", "亥"],
        wuxing_score=wuxing_score,
        yongshen=yongshen,
        minggong="丙戌",
        taiyuan="甲戌",
    )
    return chart


@pytest.fixture
def sample_chart_data():
    """构建测试用的 chart_data 字典"""
    return {
        "four_pillars": {
            "year": {
                "stem": "甲", "branch": "子", "stem_ten_god": "食神",
                "hidden_stems": [{"stem": "癸", "weight": 10.0, "ten_god": "正印"}],
                "nayin": "海中金",
            },
            "month": {
                "stem": "丙", "branch": "寅", "stem_ten_god": "正官",
                "hidden_stems": [
                    {"stem": "甲", "weight": 6.0, "ten_god": "比肩"},
                    {"stem": "丙", "weight": 3.0, "ten_god": "正官"},
                    {"stem": "戊", "weight": 1.0, "ten_god": "偏财"},
                ], "nayin": "炉中火",
            },
            "day": {
                "stem": "戊", "branch": "辰", "stem_ten_god": "日主",
                "hidden_stems": [
                    {"stem": "戊", "weight": 6.0, "ten_god": "比肩"},
                    {"stem": "乙", "weight": 3.0, "ten_god": "正官"},
                    {"stem": "癸", "weight": 1.0, "ten_god": "正财"},
                ], "nayin": "大林木",
            },
            "hour": {
                "stem": "庚", "branch": "申", "stem_ten_god": "食神",
                "hidden_stems": [
                    {"stem": "庚", "weight": 6.0, "ten_god": "食神"},
                    {"stem": "壬", "weight": 3.0, "ten_god": "偏财"},
                    {"stem": "戊", "weight": 1.0, "ten_god": "比肩"},
                ], "nayin": "石榴木",
            },
        },
        "day_master": "戊",
        "gender": "male",
        "dayun": [
            {"stem": "乙", "branch": "丑", "ten_god": "正官",
             "start_age": 5, "end_age": 14, "start_year": 1995, "end_year": 2004},
            {"stem": "甲", "branch": "子", "ten_god": "七杀",
             "start_age": 15, "end_age": 24, "start_year": 2005, "end_year": 2014},
            {"stem": "癸", "branch": "亥", "ten_god": "正财",
             "start_age": 25, "end_age": 34, "start_year": 2015, "end_year": 2024},
            {"stem": "壬", "branch": "戌", "ten_god": "偏财",
             "start_age": 35, "end_age": 44, "start_year": 2025, "end_year": 2034},
            {"stem": "辛", "branch": "酉", "ten_god": "伤官",
             "start_age": 45, "end_age": 54, "start_year": 2035, "end_year": 2044},
            {"stem": "庚", "branch": "申", "ten_god": "食神",
             "start_age": 55, "end_age": 64, "start_year": 2045, "end_year": 2054},
        ],
        "shensha": [
            {"name": "文昌", "description": "主聪明好学", "position": "年柱"},
            {"name": "天乙贵人", "description": "主贵人扶持", "position": "日柱"},
        ],
        "wuxing_score": {"jin": 15.0, "mu": 20.0, "shui": 10.0, "huo": 15.0, "tu": 40.0},
        "yongshen": {
            "primary": "金", "secondary": "水", "ji_shen": "火",
            "pattern": "正格", "ri_zhu_strength": "身旺",
        },
        "kongwang": ["戌", "亥"],
        "minggong": "丙戌",
        "taiyuan": "甲戌",
    }


# ============================================================
# 测试：_find_current_dayun
# ============================================================

class TestFindCurrentDayun:
    """测试当前大运查找"""

    def test_finds_current_dayun(self, sample_chart):
        """测试找到当前所处的大运"""
        current_year = datetime.datetime.now().year
        cd = _find_current_dayun(sample_chart.dayun, current_year)
        assert cd is not None
        assert "stem" in cd
        assert "branch" in cd
        assert "ten_god" in cd
        assert "start_year" in cd
        assert "end_year" in cd

    def test_returns_first_when_no_match(self):
        """测试无匹配大运时返回第一个"""
        dayun = [
            {"stem": "甲", "branch": "子", "ten_god": "七杀",
             "start_age": 15, "end_age": 24, "start_year": 2010, "end_year": 2019},
        ]
        cd = _find_current_dayun(dayun, 3000)  # future year with no match
        assert cd is not None
        assert cd["stem"] == "甲"

    def test_returns_empty_when_empty_dayun(self):
        """测试空大运列表返回空 dict"""
        cd = _find_current_dayun([], 2026)
        assert cd is not None
        assert cd.get("stem", "") == ""


# ============================================================
# 测试：_get_upcoming_dayun
# ============================================================

class TestGetUpcomingDayun:
    """测试未来大运获取"""

    def test_returns_upcoming_dayun(self, sample_chart):
        """测试返回未来大运列表"""
        current_year = datetime.datetime.now().year
        upcoming = _get_upcoming_dayun(sample_chart.dayun, current_year)
        assert len(upcoming) > 0
        assert len(upcoming) <= 5
        for du in upcoming:
            assert "stem" in du
            assert "branch" in du
            assert "ten_god" in du
            assert "start_year" in du

    def test_max_five_results(self, sample_chart):
        """测试最多返回5个"""
        upcoming = _get_upcoming_dayun(sample_chart.dayun, 1990)
        assert len(upcoming) <= 5


# ============================================================
# 测试：_get_key_years_from_dayun
# ============================================================

class TestGetKeyYears:
    """测试关键年份提取"""

    def test_returns_string_list(self, sample_chart):
        """测试返回字符串年份列表"""
        years = _get_key_years_from_dayun(
            sample_chart.dayun,
            sample_chart.day_master,
            sample_chart.yongshen,
        )
        assert isinstance(years, list)
        assert len(years) <= 5
        for y in years:
            assert isinstance(y, str)
            assert y.isdigit()

    def test_max_five_years(self, sample_chart):
        """测试最多返回5个年份"""
        years = _get_key_years_from_dayun(
            sample_chart.dayun,
            sample_chart.day_master,
            sample_chart.yongshen,
        )
        assert len(years) <= 5

    def test_dict_yongshen(self, sample_chart):
        """测试 yongshen 为 dict 类型的情况"""
        ys_dict = {"primary": "金", "ji_shen": "火"}
        years = _get_key_years_from_dayun(
            sample_chart.dayun,
            sample_chart.day_master,
            ys_dict,
        )
        assert isinstance(years, list)


# ============================================================
# 测试：_build_dayun_summary
# ============================================================

class TestBuildDayunSummary:
    """测试大运摘要构建"""

    def test_returns_non_empty_string(self, sample_chart):
        """测试返回非空字符串"""
        current_year = datetime.datetime.now().year
        current_dayun = _find_current_dayun(sample_chart.dayun, current_year)
        summary = _build_dayun_summary(sample_chart.dayun, current_dayun, 1990)
        assert isinstance(summary, str)
        assert len(summary) > 0
        assert "当前年龄" in summary

    def test_includes_upcoming_dayun(self, sample_chart):
        """测试包含未来大运信息"""
        current_year = datetime.datetime.now().year
        current_dayun = _find_current_dayun(sample_chart.dayun, current_year)
        summary = _build_dayun_summary(sample_chart.dayun, current_dayun, 1990)
        assert "未来大运" in summary


# ============================================================
# 测试：Mock 模板生成
# ============================================================

class TestMockForecast:
    """测试 Mock 模板未来运势预测"""

    def test_generates_all_four_dimensions(self, sample_chart, sample_chart_data):
        """测试生成四个维度的预测"""
        result = generate_mock_forecast(sample_chart, sample_chart_data)

        assert "career" in result
        assert "wealth" in result
        assert "marriage" in result
        assert "health" in result

    def test_each_dimension_has_required_fields(self, sample_chart, sample_chart_data):
        """测试每个维度包含必要字段"""
        result = generate_mock_forecast(sample_chart, sample_chart_data)

        for dim in ["career", "wealth", "marriage", "health"]:
            entry = result[dim]
            assert "summary" in entry, f"{dim} missing summary"
            assert "key_years" in entry, f"{dim} missing key_years"
            assert "advice" in entry, f"{dim} missing advice"
            assert isinstance(entry["summary"], str) and len(entry["summary"]) > 0
            assert isinstance(entry["key_years"], list)
            assert isinstance(entry["advice"], str) and len(entry["advice"]) > 0

    def test_key_years_are_future_years(self, sample_chart, sample_chart_data):
        """测试关键年份是未来年份（合理年份）"""
        result = generate_mock_forecast(sample_chart, sample_chart_data)
        current_year = datetime.datetime.now().year

        for dim in ["career", "wealth", "marriage", "health"]:
            key_years = result[dim]["key_years"]
            for y in key_years:
                year_int = int(y)
                # 年份应该在合理范围内
                assert 1950 <= year_int <= 2100, f"{dim} key year {year_int} out of range"

    def test_summary_not_empty(self, sample_chart, sample_chart_data):
        """测试摘要不为空"""
        result = generate_mock_forecast(sample_chart, sample_chart_data)
        for dim in ["career", "wealth", "marriage", "health"]:
            assert len(result[dim]["summary"]) > 10, f"{dim} summary too short"

    def test_advice_contains_classical_reference(self, sample_chart, sample_chart_data):
        """测试建议包含典籍引用"""
        result = generate_mock_forecast(sample_chart, sample_chart_data)
        # 至少有一个维度包含典籍引用
        has_ref = False
        for dim in ["career", "wealth", "marriage", "health"]:
            advice = result[dim]["advice"]
            if "滴天髓" in advice or "子平真诠" in advice or "渊海子平" in advice or "穷通宝鉴" in advice or "黄帝内经" in advice:
                has_ref = True
                break
        assert has_ref, "No classical reference found in any dimension advice"


# ============================================================
# 测试：单个 Mock 维度函数
# ============================================================

class TestMockDimensionFunctions:
    """测试单个 Mock 维度预测函数"""

    def test_career_forecast(self, sample_chart, sample_chart_data):
        """测试事业运预测"""
        current_dayun = _find_current_dayun(sample_chart.dayun)
        result = _mock_career_forecast(sample_chart, sample_chart_data, current_dayun)
        assert "summary" in result
        assert "key_years" in result
        assert "advice" in result
        assert len(result["summary"]) > 0

    def test_wealth_forecast(self, sample_chart, sample_chart_data):
        """测试财运预测"""
        current_dayun = _find_current_dayun(sample_chart.dayun)
        result = _mock_wealth_forecast(sample_chart, sample_chart_data, current_dayun)
        assert "summary" in result
        assert "key_years" in result
        assert "advice" in result

    def test_marriage_forecast(self, sample_chart, sample_chart_data):
        """测试婚姻运预测"""
        current_dayun = _find_current_dayun(sample_chart.dayun)
        result = _mock_marriage_forecast(sample_chart, sample_chart_data, current_dayun)
        assert "summary" in result
        assert "key_years" in result
        assert "advice" in result

    def test_health_forecast(self, sample_chart, sample_chart_data):
        """测试健康运预测"""
        current_dayun = _find_current_dayun(sample_chart.dayun)
        result = _mock_health_forecast(sample_chart, sample_chart_data, current_dayun)
        assert "summary" in result
        assert "key_years" in result
        assert "advice" in result


# ============================================================
# 测试：AI 解析函数
# ============================================================

class TestParseForecastJson:
    """测试 AI 返回 JSON 解析"""

    def test_parses_valid_json(self):
        """测试解析有效的 JSON"""
        valid_json = json.dumps({
            "career": {
                "summary": "事业发展顺利，有晋升机会",
                "key_years": ["2027", "2030"],
                "advice": "保持稳健，抓住机遇"
            },
            "wealth": {
                "summary": "财运稳中有升",
                "key_years": ["2028"],
                "advice": "稳健理财"
            },
            "marriage": {
                "summary": "感情稳定",
                "key_years": ["2029"],
                "advice": "多沟通"
            },
            "health": {
                "summary": "健康状况良好",
                "key_years": [],
                "advice": "保持运动"
            },
            "disclaimer": "仅供参考"
        })
        result = _parse_forecast_json(valid_json)
        assert result is not None
        assert "career" in result
        assert result["career"]["summary"] == "事业发展顺利，有晋升机会"

    def test_parses_json_with_extra_text(self):
        """测试解析包含额外文本的 JSON"""
        response = """好的，以下是预测结果：

```json
{
  "career": {
    "summary": "测试事业",
    "key_years": ["2030"],
    "advice": "测试建议"
  },
  "wealth": {
    "summary": "测试财运",
    "key_years": [],
    "advice": "测试建议"
  },
  "marriage": {
    "summary": "测试婚姻",
    "key_years": [],
    "advice": "测试建议"
  },
  "health": {
    "summary": "测试健康",
    "key_years": [],
    "advice": "测试建议"
  }
}
```

希望以上预测对您有帮助。"""
        result = _parse_forecast_json(response)
        assert result is not None
        assert "career" in result

    def test_returns_none_for_invalid(self):
        """测试无效输入返回 None"""
        result = _parse_forecast_json("这不是 JSON")
        assert result is None

    def test_returns_none_for_empty(self):
        """测试空字符串返回 None"""
        result = _parse_forecast_json("")
        assert result is None


# ============================================================
# 测试：主函数 generate_forecast
# ============================================================

class TestGenerateForecast:
    """测试 generate_forecast 主函数"""

    @pytest.mark.asyncio
    async def test_returns_mock_when_no_api_key(self, sample_chart, sample_chart_data, monkeypatch):
        """测试无 API Key 时返回 Mock 模板"""
        # 确保 DEEPSEEK_API_KEY 未设置
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

        result = await generate_forecast(sample_chart, sample_chart_data)

        assert "forecast" in result
        assert "current_dayun" in result
        assert "method" in result
        assert "disclaimer" in result
        assert result["method"] == "mock_template"

        # 验证四个维度
        forecast = result["forecast"]
        for dim in ["career", "wealth", "marriage", "health"]:
            assert dim in forecast
            assert "summary" in forecast[dim]
            assert "key_years" in forecast[dim]
            assert "advice" in forecast[dim]

    @pytest.mark.asyncio
    async def test_returns_current_dayun_info(self, sample_chart, sample_chart_data, monkeypatch):
        """测试返回当前大运信息"""
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

        result = await generate_forecast(sample_chart, sample_chart_data)

        cd = result["current_dayun"]
        assert "stem" in cd
        assert "branch" in cd
        assert "ten_god" in cd
        assert "start_year" in cd
        assert "end_year" in cd

    @pytest.mark.asyncio
    async def test_returns_disclaimer(self, sample_chart, sample_chart_data, monkeypatch):
        """测试包含免责声明"""
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

        result = await generate_forecast(sample_chart, sample_chart_data)

        assert len(result["disclaimer"]) > 0
        assert "参考" in result["disclaimer"] or "仅供参考" in result["disclaimer"]

    @pytest.mark.asyncio
    async def test_with_calibration_result(self, sample_chart, sample_chart_data, monkeypatch):
        """测试传入修正结果"""
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

        calib = {"path": "accurate", "correction_type": "ai_fix"}
        result = await generate_forecast(sample_chart, sample_chart_data, calib)

        assert "forecast" in result
        assert result["method"] == "mock_template"
