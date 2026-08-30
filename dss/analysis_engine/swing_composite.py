"""
短线综合评分器 — 5维度加权合成。

纯函数设计：接收各分析器结果，返回 CompositeResult。
"""

from dss.analysis_engine.swing_types import (
    TrendResult, MomentumResult, VolumeResult,
    RiskResult, CompositeResult
)
from dss.config import Config


class SwingCompositeScorer:
    """
    综合评分器：将趋势、动量、量能、风险、市场环境五个维度的评分
    按权重合成为最终 0-100 综合评分。
    """

    def __init__(self, config: Config = None):
        if config:
            self.w_trend = config.SWING_W_TREND
            self.w_momentum = config.SWING_W_MOMENTUM
            self.w_volume = config.SWING_W_VOLUME
            self.w_risk = config.SWING_W_RISK
            self.w_market = config.SWING_W_MARKET
        else:
            self.w_trend = 0.30
            self.w_momentum = 0.25
            self.w_volume = 0.20
            self.w_risk = 0.15
            self.w_market = 0.10

    def compute(
        self,
        trend: TrendResult,
        momentum: MomentumResult,
        volume: VolumeResult,
        risk: RiskResult,
        market_env_score: float = 50.0,
    ) -> CompositeResult:
        """
        合成综合评分。

        Args:
            trend: 趋势分析结果
            momentum: 动量分析结果
            volume: 量能分析结果
            risk: 风险分析结果
            market_env_score: 市场环境评分 (0-100)

        Returns:
            CompositeResult
        """
        overall = (
            trend.composite * self.w_trend +
            momentum.composite * self.w_momentum +
            volume.composite * self.w_volume +
            risk.composite * self.w_risk +
            market_env_score * self.w_market
        )

        overall = round(overall, 1)

        # 生成理由
        rationale = self._build_rationale(
            trend, momentum, volume, risk, market_env_score, overall
        )

        return CompositeResult(
            overall_score=overall,
            trend_score=trend.composite,
            momentum_score=momentum.composite,
            volume_score=volume.composite,
            risk_score=risk.composite,
            market_env_score=market_env_score,
            breakdown={
                'trend': trend.composite,
                'momentum': momentum.composite,
                'volume': volume.composite,
                'risk': risk.composite,
                'market_env': market_env_score,
            },
            rationale=rationale,
        )

    def _build_rationale(
        self,
        trend: TrendResult,
        momentum: MomentumResult,
        volume: VolumeResult,
        risk: RiskResult,
        market_env_score: float,
        overall: float,
    ) -> str:
        """生成可读的理由说明"""
        parts = []

        if trend.composite >= 70:
            parts.append(f"强势趋势({trend.composite:.0f})")
        elif trend.composite >= 60:
            parts.append(f"温和趋势({trend.composite:.0f})")
        elif trend.composite < 40:
            parts.append(f"弱势趋势({trend.composite:.0f})")

        if momentum.composite >= 70:
            parts.append(f"动量强劲({momentum.composite:.0f})")
        elif momentum.composite < 40:
            parts.append(f"动量偏弱({momentum.composite:.0f})")

        if volume.composite >= 70:
            parts.append(f"量能活跃({volume.composite:.0f})")
        elif volume.composite < 40:
            parts.append(f"量能不足({volume.composite:.0f})")

        if risk.composite >= 70:
            parts.append(f"风险较低({risk.composite:.0f})")
        elif risk.composite < 40:
            parts.append(f"风险较高({risk.composite:.0f})")

        if market_env_score >= 70:
            parts.append(f"市场偏强({market_env_score:.0f})")
        elif market_env_score < 40:
            parts.append(f"市场偏弱({market_env_score:.0f})")

        if not parts:
            return f"综合评分 {overall:.0f}，各维度中性"

        return f"综合 {overall:.0f}: " + "，".join(parts)
