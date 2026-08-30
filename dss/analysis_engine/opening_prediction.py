"""
次日开盘预测器。

从 UltraShortTailAnalyzer._predict_next_day_open() 提取。

v8.8 模型：两维度预测（移除资金面参数），强化动量与情绪权重。

预测逻辑：
- 基概率：当日涨跌幅映射
- 动量调整：动量评分偏离50的程度 × 0.35
- 情绪调整：情绪评分偏离50的程度 × 0.25
- 尾盘趋势调整：分钟数据斜率 × 100

纯函数设计：所有数据通过参数注入。
"""

from typing import Dict, Any

import numpy as np


class OpeningPredictor:
    """
    次日开盘预测器。

    使用方式:
        predictor = OpeningPredictor()
        pred = predictor.predict(current_price, daily_change_pct,
                                 momentum_score, sentiment_score,
                                 momentum_details)
    """

    # 动量调整系数 (v8.8: 从 0.20 提升至 0.35)
    MOMENTUM_ADJ_FACTOR = 0.35
    # 情绪调整系数 (v8.8: 从 0.15 提升至 0.25)
    SENTIMENT_ADJ_FACTOR = 0.25
    # 尾盘趋势系数
    TAIL_ADJ_FACTOR = 100.0

    def predict(
        self,
        current_price: float,
        daily_change_pct: float,
        momentum_score: float,
        sentiment_score: float,
        momentum_details: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        预测次日高开概率和预期涨跌幅。

        Args:
            current_price: 当前价格
            daily_change_pct: 当日涨跌幅 (%)
            momentum_score: 技术动量评分 (0-100)
            sentiment_score: 情绪面评分 (0-100)
            momentum_details: 技术动量详情 (含 recent_trend, minute_data_available)

        Returns:
            {
                'high_open_probability': float (0-100),
                'expected_open_change_pct': float,
                'prediction_method': str,
                'components': dict,
            }
        """
        # 1. 基概率
        base_prob = self._compute_base_prob(daily_change_pct)

        # 2. 动量调整
        momentum_adj = (momentum_score - 50.0) * self.MOMENTUM_ADJ_FACTOR

        # 3. 情绪调整
        sentiment_adj = (sentiment_score - 50.0) * self.SENTIMENT_ADJ_FACTOR

        # 4. 尾盘趋势调整
        tail_adj = 0.0
        if momentum_details.get('minute_data_available', False):
            tail_adj = momentum_details.get('recent_trend', 0.0) * self.TAIL_ADJ_FACTOR

        # 5. 综合
        high_open_prob = base_prob + momentum_adj + sentiment_adj + tail_adj
        high_open_prob = float(np.clip(high_open_prob, 0, 100))

        # 6. 预期开盘涨跌幅
        expected_change = daily_change_pct * 0.3 + (high_open_prob - 50) / 10

        return {
            'high_open_probability': high_open_prob,
            'expected_open_change_pct': float(expected_change),
            'prediction_method': 'two_dimension_model_v88',
            'components': {
                'base_prob': base_prob,
                'momentum_adj': momentum_adj,
                'sentiment_adj': sentiment_adj,
                'tail_adj': tail_adj,
            },
        }

    @staticmethod
    def _compute_base_prob(daily_change_pct: float) -> float:
        """当日涨跌幅 → 基概率"""
        if daily_change_pct > 0:
            return 50.0 + daily_change_pct * 3
        else:
            return 50.0 + daily_change_pct * 2
