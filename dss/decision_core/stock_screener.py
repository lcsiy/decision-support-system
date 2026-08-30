"""
股票预筛选器。

从 UltraShortTailAnalyzer.analyze_stock_comprehensive() 中提取分析前过滤流水线。

筛选步骤：
1. 价格有效性 — 必须有有效的当前价
2. 流动性检查 — 成交额 >= 最小流动性要求
3. 涨跌停检查 — 涨停/准跌停排除
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional

from dss.analysis_engine.technical_momentum import TechnicalMomentumAnalyzer


@dataclass
class ScreenResult:
    """筛选结果"""
    passed: bool
    exclude_reason: str = ""
    current_price: float = 0.0
    pre_close: float = 0.0
    daily_change_pct: float = 0.0
    amount: float = 0.0


class StockScreener:
    """
    股票预筛选器。

    使用方式:
        screener = StockScreener(min_liquidity=10_000_000)
        result = screener.screen(ts_code, realtime_data)
        if result.passed:
            # proceed to analysis
    """

    def __init__(self, min_liquidity: float = 10_000_000):
        """
        Args:
            min_liquidity: 最小流动性要求（成交额，元）
        """
        self.min_liquidity = min_liquidity

    def screen(
        self,
        ts_code: str,
        realtime_data: Dict[str, Any],
    ) -> ScreenResult:
        """
        执行预筛选。

        Args:
            ts_code: 股票代码
            realtime_data: 实时行情 dict

        Returns:
            ScreenResult
        """
        # 1. 提取价格
        current_price, pre_close = self._extract_price(realtime_data)
        if current_price <= 0:
            return ScreenResult(
                passed=False,
                exclude_reason='无法获取价格',
                current_price=0.0,
                pre_close=pre_close,
            )

        # 2. 计算涨跌幅
        daily_change_pct = 0.0
        if pre_close > 0:
            daily_change_pct = (current_price - pre_close) / pre_close * 100

        # 3. 流动性检查
        amount = self._extract_amount(realtime_data)
        if 0 < amount < self.min_liquidity:
            return ScreenResult(
                passed=False,
                exclude_reason='流动性不足',
                current_price=current_price,
                pre_close=pre_close,
                daily_change_pct=daily_change_pct,
                amount=amount,
            )

        # 4. 涨跌停检查
        limit = TechnicalMomentumAnalyzer.check_limit_status(current_price, pre_close)
        if limit['is_limit_up']:
            return ScreenResult(
                passed=False,
                exclude_reason='涨停',
                current_price=current_price,
                pre_close=pre_close,
                daily_change_pct=daily_change_pct,
                amount=amount,
            )
        if limit['is_near_limit_down']:
            return ScreenResult(
                passed=False,
                exclude_reason=f"准跌停 ({limit['change_pct']:.1f}%)",
                current_price=current_price,
                pre_close=pre_close,
                daily_change_pct=daily_change_pct,
                amount=amount,
            )

        return ScreenResult(
            passed=True,
            current_price=current_price,
            pre_close=pre_close,
            daily_change_pct=daily_change_pct,
            amount=amount,
        )

    # ---- 工具方法 ----

    @staticmethod
    def _extract_price(realtime_data: Dict[str, Any]) -> tuple:
        """提取当前价和前收盘价"""
        current_price = 0.0
        pre_close = 0.0

        if realtime_data is None:
            return current_price, pre_close

        for field in ['price', 'current', 'close', 'last', 'trade', '最新价']:
            if field in realtime_data:
                try:
                    val = float(realtime_data[field])
                    if val > 0:
                        current_price = val
                        break
                except (ValueError, TypeError):
                    continue

        for field in ['pre_close', 'prev_close', 'yest_close', '昨收']:
            if field in realtime_data:
                try:
                    val = float(realtime_data[field])
                    if val > 0:
                        pre_close = val
                        break
                except (ValueError, TypeError):
                    continue

        return current_price, pre_close

    @staticmethod
    def _extract_amount(realtime_data: Dict[str, Any]) -> float:
        """提取成交额"""
        for field in ['amount', '成交额']:
            if field in realtime_data:
                try:
                    val = float(realtime_data[field])
                    if val > 0:
                        return val
                except (ValueError, TypeError):
                    pass
        return 0.0
