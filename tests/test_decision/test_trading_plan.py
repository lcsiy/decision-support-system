"""
Tests for dss.decision_core.trading_plan — threshold logic.
"""
import pytest
from dss.decision_core.trading_plan import TradingPlanGenerator


class TestTradingPlan:
    """交易计划生成"""

    def test_strong_buy(self):
        gen = TradingPlanGenerator()
        plan = gen.generate(
            ts_code='600036.SH', name='招商银行',
            current_price=32.5, daily_change_pct=3.0,
            comprehensive_score=80,
            next_day_prediction={'high_open_probability': 75},
            risk_assessment={'risk_level': 'low'},
        )
        assert plan['recommendation'] == '强烈建议'
        assert plan['confidence'] == '高'
        assert '15-20%' in plan['position_pct']

    def test_buy(self):
        gen = TradingPlanGenerator()
        plan = gen.generate(
            ts_code='600036.SH', name='招商银行',
            current_price=32.5, daily_change_pct=1.0,
            comprehensive_score=68,
            next_day_prediction={'high_open_probability': 62},
            risk_assessment={'risk_level': 'medium'},
        )
        assert plan['recommendation'] == '建议'

    def test_not_recommended(self):
        gen = TradingPlanGenerator()
        plan = gen.generate(
            ts_code='600036.SH', name='招商银行',
            current_price=32.5, daily_change_pct=-2.0,
            comprehensive_score=50,
            next_day_prediction={'high_open_probability': 45},
            risk_assessment={'risk_level': 'medium'},
        )
        assert plan['recommendation'] == '不建议'
        assert plan['position_pct'] == '0%'

    def test_stop_loss_high_risk(self):
        gen = TradingPlanGenerator()
        plan = gen.generate(
            ts_code='000001.SZ', name='平安银行',
            current_price=10.0, daily_change_pct=-1.0,
            comprehensive_score=60,
            next_day_prediction={'high_open_probability': 55},
            risk_assessment={'risk_level': 'high'},
        )
        assert '-3' in plan['stop_loss_pct'], f"High risk should be -3%, got {plan['stop_loss_pct']}"

    def test_stop_loss_low_risk(self):
        gen = TradingPlanGenerator()
        plan = gen.generate(
            ts_code='600036.SH', name='招商银行',
            current_price=10.0, daily_change_pct=1.0,
            comprehensive_score=70,
            next_day_prediction={'high_open_probability': 65},
            risk_assessment={'risk_level': 'low'},
        )
        assert '-2' in plan['stop_loss_pct'], f"Low risk should be -2%, got {plan['stop_loss_pct']}"
