"""测试：用神辅助字段 (auxiliary)"""

import pytest
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import YongShen
from rules.yongshen import determine_yongshen, _determine_yongshen_detail


class TestAuxiliaryYongshen:
    """用神辅用神 (auxiliary) 字段的单元测试"""

    def test_yongshen_model_has_auxiliary_field(self):
        """YongShen 模型应包含 auxiliary 字段，默认空字符串"""
        ys = YongShen(
            primary="木", secondary="火", ji_shen="水",
            pattern="正格-身弱", ri_zhu_strength="偏弱"
        )
        assert hasattr(ys, "auxiliary")
        assert ys.auxiliary == ""

    def test_auxiliary_not_duplicate_primary(self):
        """辅用神不可与主用神重复"""
        ys = YongShen(
            primary="木", secondary="火", ji_shen="水",
            auxiliary="金", pattern="正格-身弱", ri_zhu_strength="偏弱"
        )
        vals = {ys.primary, ys.auxiliary}
        assert len(vals) == 2, f"主用神({ys.primary})与辅用神({ys.auxiliary})重复"

    def test_determine_yongshen_returns_auxiliary(self):
        """determine_yongshen 返回的 YongShen 应包含 auxiliary 字段"""
        pillars = {
            "year": {"stem": "庚", "branch": "午"},
            "month": {"stem": "己", "branch": "卯"},
            "day": {"stem": "丁", "branch": "卯"},
            "hour": {"stem": "戊", "branch": "辰"},
        }
        result = determine_yongshen("丁", pillars, [], {})
        assert hasattr(result, "auxiliary")
        assert isinstance(result.auxiliary, str)

    def test_auxiliary_persists_through_model_dump(self):
        """auxiliary 字段应出现在 model_dump 输出中"""
        ys = YongShen(
            primary="木", secondary="火", ji_shen="水",
            auxiliary="金", pattern="正格-身弱", ri_zhu_strength="偏弱"
        )
        d = ys.model_dump()
        assert "auxiliary" in d
        assert d["auxiliary"] == "金"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
