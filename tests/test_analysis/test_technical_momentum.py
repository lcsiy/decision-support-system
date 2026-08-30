"""
Tests for dss.analysis_engine.technical_momentum — deterministic scoring logic.
"""
import pytest
import pandas as pd
import numpy as np
from dss.analysis_engine.technical_momentum import TechnicalMomentumAnalyzer


class TestCheckLimitStatus:
    """涨跌停状态检查 — 纯函数，无外部依赖"""

    def test_normal(self):
        result = TechnicalMomentumAnalyzer.check_limit_status(10.0, 10.0)
        assert result['is_limit_up'] is False
        assert result['is_limit_down'] is False
        assert result['is_near_limit_down'] is False
        assert result['change_pct'] == 0.0

    def test_limit_up(self):
        result = TechnicalMomentumAnalyzer.check_limit_status(11.0, 10.0)
        assert result['is_limit_up'] is True
        assert result['change_pct'] == pytest.approx(10.0)

    def test_limit_down(self):
        result = TechnicalMomentumAnalyzer.check_limit_status(9.0, 10.0)
        assert result['is_limit_down'] is True
        assert result['change_pct'] == pytest.approx(-10.0)

    def test_near_limit_down(self):
        result = TechnicalMomentumAnalyzer.check_limit_status(9.25, 10.0)
        assert result['is_limit_down'] is False
        assert result['is_near_limit_down'] is True

    def test_zero_pre_close(self):
        result = TechnicalMomentumAnalyzer.check_limit_status(10.0, 0.0)
        assert result['is_limit_up'] is False


class TestVolumeScore:
    """成交量因子评分 — 量价配合逻辑"""

    def test_volume_surge_up(self):
        """放量上涨 → 85分以上"""
        analyzer = TechnicalMomentumAnalyzer()
        details = {'volume_trend': 'significant_surge', 'relative_volume_vs_5d': 2.0}
        score = analyzer._compute_volume_score(details, daily_change_pct=3.0)
        assert score >= 85, f"Expected >=85, got {score}"

    def test_shrink_up_low(self):
        """缩量上涨 → 45分"""
        analyzer = TechnicalMomentumAnalyzer()
        details = {'volume_trend': 'shrinking', 'relative_volume_vs_5d': 0.6}
        score = analyzer._compute_volume_score(details, daily_change_pct=2.0)
        assert score == 45, f"Expected 45, got {score}"

    def test_volume_surge_down_low(self):
        """放量下跌 → 低分"""
        analyzer = TechnicalMomentumAnalyzer()
        details = {'volume_trend': 'extreme_surge', 'relative_volume_vs_5d': 2.5}
        score = analyzer._compute_volume_score(details, daily_change_pct=-4.0)
        assert score <= 25, f"Expected <=25, got {score}"

    def test_shrink_down_ok(self):
        """缩量下跌 → 50分（抛压减轻）"""
        analyzer = TechnicalMomentumAnalyzer()
        details = {'volume_trend': 'shrinking', 'relative_volume_vs_5d': 0.5}
        score = analyzer._compute_volume_score(details, daily_change_pct=-2.0)
        assert score == 50, f"Expected 50, got {score}"


class TestMomentumAnalyze:
    """技术动量完整分析 — 验证输出格式和范围"""

    def test_basic_analyze_no_minute(self):
        """无分钟数据时的基本分析"""
        analyzer = TechnicalMomentumAnalyzer()
        score, details = analyzer.analyze(
            ts_code='600036.SH',
            current_price=32.5,
            daily_change_pct=2.0,
            realtime_data={'open': 31.8, 'high': 33.0, 'low': 31.5},
            daily_df=None,
            minute_df=None,
            use_minute_data=False,
        )
        assert 0 <= score <= 100, f"Score should be 0-100, got {score}"
        assert details['minute_data_available'] is False
        assert 'price_position' in details
        assert 0 <= details['price_position'] <= 1

    def test_score_in_range(self):
        """极端负涨跌幅时分数是否仍在0-100范围内"""
        analyzer = TechnicalMomentumAnalyzer()
        score, _ = analyzer.analyze(
            ts_code='000001.SZ',
            current_price=10.0,
            daily_change_pct=-8.0,
            realtime_data={'open': 10.8, 'high': 10.9, 'low': 9.5},
            daily_df=None,
            minute_df=None,
            use_minute_data=False,
        )
        assert 0 <= score <= 100
