"""
短线趋势分析器 — 基于均线排列和趋势强度的多因子评分。

纯函数设计：接收 DataFrame，返回 TrendResult。
"""

import numpy as np
import pandas as pd
from typing import Tuple
from dss.analysis_engine.swing_types import TrendResult


class SwingTrendAnalyzer:
    """
    趋势分析器：评估股票的中短期趋势质量。

    5个子因子：
    - MA排列评分：MA5 > MA10 > MA20 > MA60 多头排列程度
    - 价格vsMA20：价格相对20日均线的偏离度
    - 价格vsMA60：价格相对60日均线的偏离度
    - 趋势斜率：20日收盘价的线性回归斜率
    - 趋势一致性：近10日阳线比例
    """

    def analyze(self, df: pd.DataFrame) -> TrendResult:
        """
        执行趋势分析。

        Args:
            df: 日K线 DataFrame，需含 close 列和 ma5/ma10/ma20/ma60 列

        Returns:
            TrendResult 含各因子 0-100 评分
        """
        if df is None or df.empty or len(df) < 10:
            return TrendResult()

        close = df['close'].values
        latest_close = close[-1]

        ma_scores = self._ma_alignment(df)
        price_ma20 = self._price_vs_ma(df, 'ma20', latest_close)
        price_ma60 = self._price_vs_ma(df, 'ma60', latest_close)
        slope = self._trend_slope(df)
        consistency = self._trend_consistency(df)

        composite = (
            ma_scores['score'] * 0.30 +
            price_ma20 * 0.20 +
            price_ma60 * 0.15 +
            slope * 0.20 +
            consistency * 0.15
        )

        return TrendResult(
            ma_alignment_score=ma_scores['score'],
            price_vs_ma20=price_ma20,
            price_vs_ma60=price_ma60,
            trend_slope_20=slope,
            trend_consistency=consistency,
            composite=round(composite, 1),
            detail={
                'ma_values': ma_scores['ma_values'],
                'alignment_count': ma_scores['alignment_count'],
                'close': float(latest_close),
            }
        )

    def _ma_alignment(self, df: pd.DataFrame) -> dict:
        """评估MA多头排列程度"""
        latest = df.iloc[-1]
        mas = {}
        score = 50.0
        count = 0

        ma_order = ['ma5', 'ma10', 'ma20', 'ma60']
        for m in ma_order:
            if m in df.columns and pd.notna(latest.get(m)):
                mas[m] = float(latest[m])

        if len(mas) >= 3:
            # 计算多头排列对数
            pairs = 0
            total_pairs = len(mas) - 1
            keys = list(mas.keys())
            for i in range(len(keys) - 1):
                if mas[keys[i]] > mas[keys[i + 1]]:
                    pairs += 1
            count = pairs
            if total_pairs > 0:
                score = (pairs / total_pairs) * 100

        return {'score': score, 'ma_values': mas, 'alignment_count': count}

    def _price_vs_ma(self, df: pd.DataFrame, ma_col: str, close: float) -> float:
        """价格相对均线位置评分"""
        if ma_col not in df.columns:
            return 50.0
        latest_ma = df[ma_col].iloc[-1]
        if pd.isna(latest_ma) or latest_ma <= 0:
            return 50.0

        pct = (close - latest_ma) / latest_ma * 100
        # 价格在MA上方5%以内最佳(80-100)，上方5-15%良好(60-80)，下方打折扣
        if 0 <= pct <= 5:
            score = 80 + pct * 4
        elif 5 < pct <= 15:
            score = 80 - (pct - 5) * 2
        elif -5 <= pct < 0:
            score = 50 + pct * 6
        elif pct < -5:
            score = max(10, 50 + pct * 4)
        else:
            score = max(10, 80 - (pct - 5) * 1.5)

        return min(100, max(0, score))

    def _trend_slope(self, df: pd.DataFrame) -> float:
        """20日趋势斜率评分"""
        if len(df) < 20:
            return 50.0

        recent = df['close'].values[-20:]
        x = np.arange(len(recent))
        try:
            slope, _ = np.polyfit(x, recent, 1)
        except Exception:
            return 50.0

        avg_price = np.mean(recent)
        if avg_price <= 0:
            return 50.0

        normalized = (slope / avg_price) * 1000  # 标准化斜率
        # 0-0.5 为温和上升(60-80)，>0.5 为强势(80-100)，负值为弱
        if normalized > 0:
            score = 50 + min(normalized * 60, 50)
        else:
            score = 50 + max(normalized * 80, -40)
        return min(100, max(0, score))

    def _trend_consistency(self, df: pd.DataFrame) -> float:
        """近10日阳线比例评分"""
        recent = df.tail(10)
        if len(recent) < 5:
            return 50.0

        up_days = (recent['close'].values > recent['open'].values).sum()
        ratio = up_days / len(recent)
        return ratio * 100
