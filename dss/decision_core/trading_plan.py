"""
交易计划生成器。

从 UltraShortTailAnalyzer._generate_trading_plan() 提取。

基于综合评分、高开概率和风险等级生成操作建议。
"""

from typing import Dict, Any


class TradingPlanGenerator:
    """
    交易计划生成器。

    使用方式:
        generator = TradingPlanGenerator()
        plan = generator.generate(current_price, comprehensive_score,
                                  prediction, risk_assessment)
    """

    # 建议阈值
    STRONG_BUY_SCORE = 75
    STRONG_BUY_PROB = 70
    BUY_SCORE = 65
    BUY_PROB = 60
    CAUTIOUS_SCORE = 55
    CAUTIOUS_PROB = 55

    # 止损比例
    STOP_LOSS_LOW_RISK = 2.0
    STOP_LOSS_DEFAULT = 3.0

    def generate(
        self,
        ts_code: str,
        name: str,
        current_price: float,
        daily_change_pct: float,
        comprehensive_score: float,
        next_day_prediction: Dict[str, Any],
        risk_assessment: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        生成交易计划。

        Args:
            ts_code: 股票代码
            name: 股票名称
            current_price: 当前价格
            daily_change_pct: 当日涨跌幅
            comprehensive_score: 综合评分 (0-100)
            next_day_prediction: 次日预测 dict
            risk_assessment: 风险评估 dict

        Returns:
            交易计划 dict
        """
        high_open_prob = next_day_prediction.get('high_open_probability', 50)
        risk_level = risk_assessment.get('risk_level', 'medium')

        # 建议等级
        if comprehensive_score >= self.STRONG_BUY_SCORE and high_open_prob >= self.STRONG_BUY_PROB:
            recommendation = '强烈建议'
            confidence = '高'
            position_pct = '15-20%'
        elif comprehensive_score >= self.BUY_SCORE and high_open_prob >= self.BUY_PROB:
            recommendation = '建议'
            confidence = '中高'
            position_pct = '10-15%'
        elif comprehensive_score >= self.CAUTIOUS_SCORE and high_open_prob >= self.CAUTIOUS_PROB:
            recommendation = '谨慎建议'
            confidence = '中'
            position_pct = '5-10%'
        else:
            recommendation = '不建议'
            confidence = '低'
            position_pct = '0%'

        # 止损
        stop_loss_pct = (
            self.STOP_LOSS_LOW_RISK if risk_level == 'low'
            else self.STOP_LOSS_DEFAULT
        )
        stop_loss_price = current_price * (1 - stop_loss_pct / 100)

        return {
            'recommendation': recommendation,
            'confidence': confidence,
            'buy_price': f"{current_price:.2f}",
            'buy_time': '14:30-15:00',
            'sell_time': '次日9:30-10:00',
            'position_pct': position_pct,
            'stop_loss_pct': f"-{stop_loss_pct}%",
            'stop_loss_price': f"{stop_loss_price:.2f}",
            'high_open_probability': f"{high_open_prob:.1f}%",
            'risk_level': risk_level,
        }
