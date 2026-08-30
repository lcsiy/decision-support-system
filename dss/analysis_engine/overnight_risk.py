"""
过夜风险评估器。

从 UltraShortTailAnalyzer._assess_overnight_risk() 提取。

v8.8：移除资金面风险因子，新增尾盘量价背离风险 + 流动性风险 + 量价背离风险。

风险因子：
1. 涨跌幅风险 — 涨跌幅过大增加不确定性
2. 尾盘量价风险 — 尾盘放量下跌 = 高风险
3. 流动性风险 — 成交额 < 5000万 = 高风险
4. 量价背离风险 — 缩量拉升 = 诱多风险

纯函数设计：所有数据通过参数注入。
"""

from typing import Dict, Any

import numpy as np


class OvernightRiskAssessor:
    """
    过夜风险评估器。

    使用方式:
        assessor = OvernightRiskAssessor()
        risk = assessor.assess(ts_code, current_price, daily_change_pct,
                               realtime_data, momentum_details)
    """

    # 风险等级阈值
    HIGH_RISK_THRESHOLD = 70
    MEDIUM_RISK_THRESHOLD = 50

    # 风险因子权重
    RISK_LARGE_CHANGE = 15      # 涨跌幅 > 5%
    RISK_MODERATE_CHANGE = 8    # 涨跌幅 > 3%
    RISK_TAIL_DUMP = 15         # 尾盘放量下跌
    RISK_TAIL_WEAK = 5          # 尾盘偏弱
    RISK_TAIL_STRONG = -5       # 尾盘放量上涨（降低风险）
    RISK_LOW_LIQUIDITY = 10     # 成交额 < 5000万
    RISK_DIVERGENCE = 8         # 缩量拉升（诱多）

    LOW_LIQUIDITY_THRESHOLD = 50_000_000  # 5000万

    def assess(
        self,
        ts_code: str,
        current_price: float,
        daily_change_pct: float,
        realtime_data: Dict[str, Any],
        momentum_details: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        评估过夜持有风险。

        Args:
            ts_code: 股票代码
            current_price: 当前价格
            daily_change_pct: 当日涨跌幅 (%)
            realtime_data: 实时行情 dict (含 amount/成交额)
            momentum_details: 技术动量详情

        Returns:
            {
                'risk_score': float (0-100, 越高越危险),
                'risk_level': 'low' | 'medium' | 'high',
                'factors': dict (各因子bool),
            }
        """
        risk_score = 50.0

        # 1. 涨跌幅风险
        if abs(daily_change_pct) > 5:
            risk_score += self.RISK_LARGE_CHANGE
        elif abs(daily_change_pct) > 3:
            risk_score += self.RISK_MODERATE_CHANGE

        # 2. 尾盘量价风险
        tail_signal = momentum_details.get('tail_volume_price_signal', 0.0)
        tail_risk = tail_signal < 0
        if tail_signal < -0.3:
            risk_score += self.RISK_TAIL_DUMP
        elif tail_signal < 0:
            risk_score += self.RISK_TAIL_WEAK
        elif tail_signal > 0.3:
            risk_score += self.RISK_TAIL_STRONG

        # 3. 流动性风险
        liquidity_risk = False
        if realtime_data:
            amount = 0.0
            for f in ['amount', '成交额']:
                if f in realtime_data:
                    try:
                        amount = float(realtime_data[f])
                        break
                    except (ValueError, TypeError):
                        pass
            if 0 < amount < self.LOW_LIQUIDITY_THRESHOLD:
                risk_score += self.RISK_LOW_LIQUIDITY
                liquidity_risk = True

        # 4. 量价背离风险
        vol_trend = momentum_details.get('volume_trend', 'normal')
        divergence_risk = (
            daily_change_pct > 2 and
            vol_trend in ('shrinking', 'extreme_shrinking')
        )
        if divergence_risk:
            risk_score += self.RISK_DIVERGENCE

        # 5. 限制范围并判定等级
        risk_score = float(np.clip(risk_score, 0, 100))

        if risk_score >= self.HIGH_RISK_THRESHOLD:
            risk_level = 'high'
        elif risk_score >= self.MEDIUM_RISK_THRESHOLD:
            risk_level = 'medium'
        else:
            risk_level = 'low'

        return {
            'risk_score': risk_score,
            'risk_level': risk_level,
            'factors': {
                'daily_change_risk': abs(daily_change_pct) > 3,
                'tail_volume_price_risk': tail_risk,
                'liquidity_risk': liquidity_risk,
                'volume_price_divergence': divergence_risk,
            },
        }
