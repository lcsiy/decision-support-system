"""
情绪面分析器 — 40% 权重。

从 UltraShortTailAnalyzer._analyze_sentiment() 提取。

分析维度：
1. 热榜排名得分 (70%) — 排名越靠前市场关注度越高
2. 涨跌幅情绪 (30%) — 当日涨跌幅反映的市场情绪

纯函数设计：所有数据通过参数注入。
"""

from typing import Dict, Tuple

import numpy as np


class SentimentAnalyzer:
    """
    情绪面分析器 (40% 权重)。

    使用方式:
        analyzer = SentimentAnalyzer()
        score, details = analyzer.analyze(ts_code, name, hot_rank, daily_change_pct)
    """

    # 热榜排名得分权重
    RANK_WEIGHT = 0.70
    # 涨跌幅情绪权重
    CHANGE_WEIGHT = 0.30

    def analyze(
        self,
        ts_code: str,
        name: str,
        hot_rank: int,
        daily_change_pct: float,
    ) -> Tuple[float, Dict]:
        """
        执行情绪面分析。

        Args:
            ts_code: 股票代码
            name: 股票名称
            hot_rank: 热榜排名 (1-based, 0 = 不在热榜)
            daily_change_pct: 当日涨跌幅 (%)

        Returns:
            (score: float 0-100, details: dict)
        """
        details = {
            'hot_rank': hot_rank,
            'rank_score': 50.0,
            'change_sentiment': 'neutral',
            'data_available': hot_rank > 0,
        }

        # 1. 热榜排名得分
        rank_score = self._compute_rank_score(hot_rank)
        details['rank_score'] = rank_score

        # 2. 涨跌幅情绪
        change_bonus, change_sentiment = self._compute_change_sentiment(daily_change_pct)
        details['change_sentiment'] = change_sentiment

        # 3. 加权
        score = rank_score * self.RANK_WEIGHT + (50.0 + change_bonus) * self.CHANGE_WEIGHT
        score = float(np.clip(score, 0, 100))

        return score, details

    @staticmethod
    def _compute_rank_score(hot_rank: int) -> float:
        """
        热榜排名 → 得分映射。

        排名 1-10:   100 → 91 (线性递减)
        排名 11-50:  90 → 70
        排名 51-100: 70 → 50
        排名 101+:   50 → 30 (最低30)
        不在热榜:    50 (中性)
        """
        if hot_rank <= 0:
            return 50.0

        if hot_rank <= 10:
            return 100.0 - (hot_rank - 1) * 1.0
        elif hot_rank <= 50:
            return 90.0 - (hot_rank - 10) * 0.5
        elif hot_rank <= 100:
            return 70.0 - (hot_rank - 50) * 0.4
        else:
            return max(30.0, 50.0 - (hot_rank - 100) * 0.1)

    @staticmethod
    def _compute_change_sentiment(daily_change_pct: float) -> Tuple[float, str]:
        """
        涨跌幅 → 情绪调整。

        Returns:
            (bonus: float, sentiment_label: str)
        """
        if daily_change_pct > 3:
            return 10.0, 'positive'
        elif daily_change_pct > 0:
            return 5.0, 'slightly_positive'
        elif daily_change_pct > -3:
            return 0.0, 'neutral'
        elif daily_change_pct > -5:
            return -5.0, 'slightly_negative'
        else:
            return -10.0, 'negative'
