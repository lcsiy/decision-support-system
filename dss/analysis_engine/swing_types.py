"""
短线交易共享数据类型。

所有分析器使用这些 dataclass 作为返回值，确保类型安全和接口一致。
"""

from dataclasses import dataclass, field
from typing import Dict, Any


@dataclass
class TrendResult:
    """趋势分析结果 (0-100 评分)"""
    ma_alignment_score: float = 50.0
    price_vs_ma20: float = 50.0
    price_vs_ma60: float = 50.0
    trend_slope_20: float = 50.0
    trend_consistency: float = 50.0
    composite: float = 50.0
    detail: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MomentumResult:
    """动量分析结果 (0-100 评分)"""
    ret_1d: float = 50.0
    ret_3d: float = 50.0
    ret_5d: float = 50.0
    ret_10d: float = 50.0
    ret_acceleration: float = 50.0
    relative_strength: float = 50.0
    composite: float = 50.0
    detail: Dict[str, Any] = field(default_factory=dict)


@dataclass
class VolumeResult:
    """量能分析结果 (0-100 评分)"""
    vol_ratio_5: float = 50.0
    vol_ratio_20: float = 50.0
    vol_price_confirmation: float = 50.0
    money_flow_ratio: float = 50.0
    composite: float = 50.0
    detail: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RiskResult:
    """风险分析结果 (0-100 评分，越高越安全)"""
    atr_pct_score: float = 50.0
    max_dd_score: float = 50.0
    beta_score: float = 50.0
    gap_risk_score: float = 50.0
    composite: float = 50.0
    detail: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CompositeResult:
    """综合评分结果"""
    overall_score: float = 50.0
    trend_score: float = 50.0
    momentum_score: float = 50.0
    volume_score: float = 50.0
    risk_score: float = 50.0
    market_env_score: float = 50.0
    breakdown: Dict[str, float] = field(default_factory=dict)
    rationale: str = ""
