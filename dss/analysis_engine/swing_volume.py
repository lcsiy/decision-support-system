"""
短线上能分析器 — 成交量比率和量价关系评估。

纯函数设计：接收 DataFrame，返回 VolumeResult。
"""

import numpy as np
import pandas as pd
from dss.analysis_engine.swing_types import VolumeResult


class SwingVolumeAnalyzer:
    """
    量能分析器：评估成交量的活跃度和量价配合情况。

    4个子因子：
    - 5日量比：当日成交量 vs 5日均量
    - 20日量比：当日成交量 vs 20日均量
    - 量价配合：10日量价相关系数
    - 资金流比率：当日成交额 vs 5日均额
    """

    def analyze(self, df: pd.DataFrame) -> VolumeResult:
        """
        执行量能分析。

        Args:
            df: 日K线 DataFrame，需含 volume 和 amount 列

        Returns:
            VolumeResult 含各因子 0-100 评分
        """
        if df is None or df.empty or len(df) < 5:
            return VolumeResult()

        vol_5 = self._vol_ratio(df, 5)
        vol_20 = self._vol_ratio(df, 20)
        confirmation = self._vol_price_confirmation(df)
        mf_ratio = self._money_flow(df)

        composite = (
            vol_5 * 0.30 +
            vol_20 * 0.20 +
            confirmation * 0.30 +
            mf_ratio * 0.20
        )

        return VolumeResult(
            vol_ratio_5=vol_5,
            vol_ratio_20=vol_20,
            vol_price_confirmation=confirmation,
            money_flow_ratio=mf_ratio,
            composite=round(composite, 1),
            detail={
                'latest_vol': float(df['volume'].iloc[-1]) if 'volume' in df.columns else 0,
            }
        )

    def _vol_ratio(self, df: pd.DataFrame, period: int) -> float:
        """成交量比率评分"""
        vol_col = self._detect_volume_column(df)
        if vol_col is None or len(df) <= period:
            return 50.0

        latest_vol = df[vol_col].iloc[-1]
        avg_vol = df[vol_col].iloc[-(period + 1):-1].mean()

        if avg_vol <= 0 or pd.isna(avg_vol):
            return 50.0

        ratio = latest_vol / avg_vol

        # 理想区间 1.2-2.5: 放量但不极端 (80-100)
        # 正常 0.8-1.2 (50-80)
        # 缩量 <0.5 (0-30)
        # 极端放量 >4 (20)
        if 1.2 <= ratio <= 2.5:
            score = 80 + (ratio - 1.2) / 1.3 * 20
        elif 0.8 <= ratio < 1.2:
            score = 50 + (ratio - 0.8) / 0.4 * 30
        elif 0.5 <= ratio < 0.8:
            score = 20 + (ratio - 0.5) / 0.3 * 30
        elif ratio > 2.5:
            score = max(20, 100 - (ratio - 2.5) * 15)
        else:
            score = max(5, ratio / 0.5 * 20)

        return min(100, max(0, score))

    def _vol_price_confirmation(self, df: pd.DataFrame) -> float:
        """量价配合度：近10日量价相关"""
        vol_col = self._detect_volume_column(df)
        if vol_col is None or len(df) < 10:
            return 50.0

        recent = df.tail(10)
        price_changes = recent['close'].pct_change().dropna().values
        vol_values = recent[vol_col].iloc[1:].values

        if len(price_changes) < 3:
            return 50.0

        try:
            corr = np.corrcoef(price_changes, vol_values)[0, 1]
            if np.isnan(corr):
                return 50.0
            # 正相关最好: score 50-100 for corr 0-1
            # 负相关不好: score 0-50 for corr -1-0
            score = 50 + corr * 50
            return min(100, max(0, score))
        except Exception:
            return 50.0

    def _money_flow(self, df: pd.DataFrame) -> float:
        """资金流比率评分（基于成交额 amount）"""
        if 'amount' not in df.columns or len(df) < 5:
            return 50.0

        latest_amount = df['amount'].iloc[-1]
        avg_amount = df['amount'].iloc[-(6):-1].mean()

        if avg_amount <= 0 or pd.isna(avg_amount):
            return 50.0

        ratio = latest_amount / avg_amount
        # 与量比类似的评分逻辑
        if 1.0 <= ratio <= 2.5:
            score = 70 + (ratio - 1.0) / 1.5 * 30
        elif 0.7 <= ratio < 1.0:
            score = 40 + (ratio - 0.7) / 0.3 * 30
        elif ratio > 2.5:
            score = max(20, 100 - (ratio - 2.5) * 12)
        else:
            score = max(5, ratio / 0.7 * 40)
        return min(100, max(0, score))

    def _detect_volume_column(self, df: pd.DataFrame):
        """检测成交量列名"""
        for col in ['vol', 'volume', '成交量']:
            if col in df.columns:
                return col
        return None
