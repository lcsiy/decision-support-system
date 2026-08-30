"""
短线交易计划生成器 — 入场价、止损、止盈、仓位。

纯计算，不做 I/O。
"""

from dataclasses import dataclass
from typing import List
from dss.config import Config


@dataclass
class EntryPlan:
    """单只股票的入场计划"""
    ts_code: str
    name: str
    suggested_entry: float
    stop_loss: float
    take_profit: float
    position_pct: float  # 占总资金的比例
    risk_reward_ratio: float


class SwingTradePlan:
    """
    买卖计划生成器。

    等额仓位分配：每只股票占总资金的比例相等（1/N）。
    止损和止盈基于配置中的百分比参数。
    """

    def __init__(self, config: Config):
        self.sl_pct = config.SWING_STOP_LOSS_PCT
        self.tp_pct = config.SWING_TAKE_PROFIT_PCT
        self.pool_size = config.SWING_POOL_SIZE

    def generate_entry_plan(
        self, ts_code: str, name: str, entry_price: float,
        num_positions: int = 3
    ) -> EntryPlan:
        """
        为单只股票生成入场计划。

        Args:
            ts_code: 股票代码
            name: 股票名称
            entry_price: 建议入场价
            num_positions: 总持仓数（用于计算仓位比例）

        Returns:
            EntryPlan
        """
        stop_loss = round(entry_price * self.sl_pct, 2)
        take_profit = round(entry_price * self.tp_pct, 2)
        position_pct = round(1.0 / num_positions * 100, 1)

        # 风险收益比
        risk = entry_price - stop_loss
        reward = take_profit - entry_price
        rr_ratio = round(reward / risk, 1) if risk > 0 else 0.0

        return EntryPlan(
            ts_code=ts_code,
            name=name,
            suggested_entry=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            position_pct=position_pct,
            risk_reward_ratio=rr_ratio,
        )

    def generate_batch_plans(
        self, picks: List[dict]
    ) -> List[EntryPlan]:
        """
        批量生成入场计划。

        Args:
            picks: [{'ts_code': str, 'name': str, 'entry_price': float}, ...]

        Returns:
            [EntryPlan, ...]
        """
        n = max(len(picks), 1)
        plans = []
        for pick in picks:
            plan = self.generate_entry_plan(
                ts_code=pick['ts_code'],
                name=pick.get('name', ''),
                entry_price=pick.get('entry_price', 0),
                num_positions=n,
            )
            plans.append(plan)
        return plans
