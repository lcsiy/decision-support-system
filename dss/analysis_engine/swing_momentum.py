"""
短线动量分析器 — 多周期收益和相对强度评估。

纯函数设计：接收 DataFrame 和指数 DataFrame，返回 MomentumResult。
"""

import numpy as np
import pandas as pd
from dss.analysis_engine.swing_types import MomentumResult


class SwingMomentumAnalyzer:
    """
    动量分析器：评估股票的多周期价格动量。

    6个子因子：
    - 1日/3日/5日/10日收益
    - 收益加速度 (5日-10日)
    - 相对强度 (vs 指数)
    """

    def analyze(self, df: pd.DataFrame, index_df: pd.DataFrame = None) -> MomentumResult:
        """
        执行动量分析。

        Args:
            df: 日K线 DataFrame
            index_df: 指数日K线 DataFrame（可选，用于计算相对强度）

        Returns:
            MomentumResult 含各因子 0-100 评分
        """
        if df is None or df.empty or len(df) < 10:
            return MomentumResult()

        close = df['close'].values
        preclose = df.get('pre_close', pd.Series(close))

        ret_1d = self._period_return(df, 1)
        ret_3d = self._period_return(df, 3)
        ret_5d = self._period_return(df, 5)
        ret_10d = self._period_return(df, 10)
        acceleration = self._acceleration(ret_5d, ret_10d)
        rs = self._relative_strength(df, index_df)

        composite = (
            ret_1d * 0.10 +
            ret_3d * 0.15 +
            ret_5d * 0.25 +
            ret_10d * 0.20 +
            acceleration * 0.15 +
            rs * 0.15
        )

        return MomentumResult(
            ret_1d=ret_1d,
            ret_3d=ret_3d,
            ret_5d=ret_5d,
            ret_10d=ret_10d,
            ret_acceleration=acceleration,
            relative_strength=rs,
            composite=round(composite, 1),
            detail={
                'ret_values': {'1d': ret_1d, '3d': ret_3d, '5d': ret_5d, '10d': ret_10d},
            }
        )

    def _period_return(self, df: pd.DataFrame, period: int) -> float:
        """计算周期收益并转为 0-100 评分"""
        if len(df) <= period:
            return 50.0

        current = df['close'].iloc[-1]
        prev = df['close'].iloc[-(period + 1)]

        if prev <= 0:
            return 50.0

        ret_pct = (current - prev) / prev * 100

        # 收益转评分: 0%→50分, +5%→85分, +10%→100分, -5%→20分
        if ret_pct >= 0:
            score = 50 + min(ret_pct * 7, 50)
        else:
            score = 50 + max(ret_pct * 6, -30)

        return round(min(100, max(0, score)), 1)

    def _acceleration(self, ret_5d: float, ret_10d: float) -> float:
        """收益加速度：短期是否在加速超越长期"""
        # ret 值本身是0-100评分，不是原始收益率
        # 5日评分 > 10日评分 → 动量在加速
        raw = (ret_5d - 50) - (ret_10d - 50)  # 差值
        score = 50 + raw * 0.8
        return min(100, max(0, score))

    def _relative_strength(self, df: pd.DataFrame, index_df: pd.DataFrame = None) -> float:
        """相对强度 vs 指数"""
        if index_df is None or index_df.empty:
            return 50.0

        try:
            stock_ret5 = self._raw_return(df, 5)
            index_ret5 = self._raw_return(index_df, 5)
            diff = stock_ret5 - index_ret5
            # 差值转评分: 0%→50, +3%→80, +5%→100, -3%→20
            if diff >= 0:
                score = 50 + min(diff * 10, 50)
            else:
                score = 50 + max(diff * 10, -30)
            return min(100, max(0, score))
        except Exception:
            return 50.0

    def _raw_return(self, df: pd.DataFrame, period: int) -> float:
        """计算原始收益率 (%)"""
        if len(df) <= period:
            return 0.0
        current = df['close'].iloc[-1]
        prev = df['close'].iloc[-(period + 1)]
        if prev <= 0:
            return 0.0
        return (current - prev) / prev * 100
