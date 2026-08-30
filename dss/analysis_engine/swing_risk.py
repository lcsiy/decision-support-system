"""
短线风险分析器 — 波动率、回撤、Beta 评估。

纯函数设计：接收 DataFrame，返回 RiskResult。
"""

import numpy as np
import pandas as pd
from dss.analysis_engine.swing_types import RiskResult


class SwingRiskAnalyzer:
    """
    风险分析器：评估股票的风险水平（评分越高越安全）。

    4个子因子：
    - ATR百分比：14日ATR/收盘价
    - 最大回撤：10日内峰谷回撤
    - Beta：20日 vs 指数
    - 跳空频率：近20日跳空次数
    """

    def analyze(self, df: pd.DataFrame, index_df: pd.DataFrame = None) -> RiskResult:
        """
        执行风险分析。

        Args:
            df: 日K线 DataFrame
            index_df: 指数日K线 DataFrame（可选）

        Returns:
            RiskResult 含各因子 0-100 评分（越高越安全）
        """
        if df is None or df.empty or len(df) < 14:
            return RiskResult()

        atr_score = self._atr_score(df)
        dd_score = self._max_dd_score(df)
        beta_score = self._beta_score(df, index_df)
        gap_score = self._gap_score(df)

        composite = (
            atr_score * 0.30 +
            dd_score * 0.30 +
            beta_score * 0.20 +
            gap_score * 0.20
        )

        return RiskResult(
            atr_pct_score=atr_score,
            max_dd_score=dd_score,
            beta_score=beta_score,
            gap_risk_score=gap_score,
            composite=round(composite, 1),
            detail={}
        )

    def _atr_score(self, df: pd.DataFrame) -> float:
        """ATR百分比评分 — 短线偏好"波动适中"，死水股票降分。

        短线交易需要价格有活动空间（获利靠波动），因此：
        - ATR% 2.5-5% → 最优 (80-100)   ← 有爆发力且风险可控
        - ATR% 1.5-2.5% 或 5-7% → 可接受 (50-80)
        - ATR% < 1.2% → 死水股票 (0-40) ← 无波动无短线价值，大幅降分
        - ATR% > 7% → 过度波动 (0-40)   ← 风险失控
        """
        if len(df) < 15:
            return 50.0

        high = df['high'].values
        low = df['low'].values
        close = df['close'].values

        # 计算 TR
        tr = np.zeros(len(df))
        for i in range(1, len(df)):
            tr[i] = max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i] - close[i - 1])
            )

        atr = np.mean(tr[-14:])
        latest_close = close[-1]

        if latest_close <= 0:
            return 50.0

        atr_pct = atr / latest_close * 100

        # 最优区间 [2.5, 5.0] — 倒钟形偏好
        if 2.5 <= atr_pct <= 5.0:
            # 峰值 100 在 atr=3.5，向两端线性下降
            peak = 3.5
            if atr_pct <= peak:
                score = 80 + (atr_pct - 2.5) / (peak - 2.5) * 20
            else:
                score = 100 - (atr_pct - peak) / (5.0 - peak) * 20
        elif 1.2 <= atr_pct < 2.5:
            score = 40 + (atr_pct - 1.2) / (2.5 - 1.2) * 40
        elif 5.0 < atr_pct <= 7.0:
            score = 60 - (atr_pct - 5.0) / 2.0 * 20
        elif atr_pct < 1.2:
            # 死水股票：波动太小，短线无操作价值
            score = 40 - (1.2 - atr_pct) / 1.2 * 40
        else:
            # > 7% 过度波动
            score = max(5, 40 - (atr_pct - 7.0) * 5)

        return min(100, max(0, score))

    def _max_dd_score(self, df: pd.DataFrame) -> float:
        """10日最大回撤评分：回撤越小越安全"""
        if len(df) < 10:
            return 50.0

        close = df['close'].values[-10:]
        peak = close[0]
        max_dd = 0.0

        for price in close:
            if price > peak:
                peak = price
            dd = (peak - price) / peak
            if dd > max_dd:
                max_dd = dd

        # 回撤 < 2% → 安全 (80-100)
        # 回撤 2-5% → 中等 (50-80)
        # 回撤 > 10% → 高风险 (0-30)
        max_dd_pct = max_dd * 100
        if max_dd_pct <= 2:
            score = 80 + (2 - max_dd_pct) / 2 * 20
        elif max_dd_pct <= 5:
            score = 50 + (5 - max_dd_pct) / 3 * 30
        elif max_dd_pct <= 10:
            score = 20 + (10 - max_dd_pct) / 5 * 30
        else:
            score = max(5, 20 - (max_dd_pct - 10) * 2)

        return min(100, max(0, score))

    def _beta_score(self, df: pd.DataFrame, index_df: pd.DataFrame = None) -> float:
        """Beta评分：0.8-1.2 最理想"""
        if index_df is None or index_df.empty or len(df) < 20:
            return 50.0

        try:
            stock_ret = pd.Series(df['close'].pct_change().dropna().values[-20:])
            idx_ret = pd.Series(index_df['close'].pct_change().dropna().values[-20:])

            min_len = min(len(stock_ret), len(idx_ret))
            if min_len < 5:
                return 50.0

            stock_ret = stock_ret[-min_len:]
            idx_ret = idx_ret[-min_len:]

            cov = np.cov(stock_ret, idx_ret)[0, 1]
            var = np.var(idx_ret)

            if var <= 0:
                return 50.0

            beta = cov / var

            # Beta 0.8-1.2 最优 (80-100)
            # Beta 0.5-0.8 或 1.2-2.0 可接受 (50-80)
            # Beta <0.3 或 >2.5 差 (0-30)
            if 0.8 <= beta <= 1.2:
                score = 80 + (1.0 - abs(beta - 1.0)) / 0.4 * 20
            elif (0.5 <= beta < 0.8) or (1.2 < beta <= 2.0):
                score = 50 + min(30, (1.5 - abs(beta - 1.0)) * 20)
            elif beta < 0.3 or beta > 2.5:
                score = max(5, 30 - abs(beta - 1.0) * 10)
            else:
                score = 50.0

            return min(100, max(0, score))
        except Exception:
            return 50.0

    def _gap_score(self, df: pd.DataFrame) -> float:
        """跳空频率评分：跳空越少越安全"""
        if len(df) < 5:
            return 50.0

        recent = df.tail(20)
        if 'open' not in recent.columns or 'close' not in recent.columns:
            return 50.0

        gaps = 0
        for i in range(1, len(recent)):
            prev_close = recent['close'].iloc[i - 1]
            today_open = recent['open'].iloc[i]
            if prev_close > 0:
                gap_pct = abs(today_open - prev_close) / prev_close
                if gap_pct > 0.02:  # 2%跳空
                    gaps += 1

        gap_ratio = gaps / len(recent)
        # 0次跳空 → 100，每次 -20分
        score = 100 - gap_ratio * 100
        return min(100, max(10, score))
