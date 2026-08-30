"""
短线交易报告格式化 — 控制台输出 + JSON导出。
"""

import json
from typing import List, Dict, Any
from datetime import datetime
from dss.decision_core.swing_pool import SellDecision


class SwingReportFormatter:
    """
    短线报告格式化器。

    提供：
    - 每日运行报告（控制台人类可读）
    - JSON 格式导出（供程序处理）
    """

    @staticmethod
    def format_daily_report(results: Dict[str, Any]) -> str:
        """
        格式化每日运行报告。

        Args:
            results: SwingOrchestrator.run_daily() 的返回值

        Returns:
            格式化的多行文本
        """
        lines = []
        date = results.get('date', datetime.now().strftime('%Y%m%d'))

        lines.append("=" * 60)
        lines.append(f"  短线交易决策报告 — {date}")
        lines.append("=" * 60)

        # 市场环境
        market = results.get('market_env', {})
        lines.append(f"\n📊 市场环境")
        lines.append(f"  上证收盘: {market.get('sh_close', 'N/A')}")
        lines.append(f"  市场情绪: {market.get('sentiment', 'N/A')}")
        lines.append(f"  市场评分: {market.get('market_score', 'N/A')}")

        # 池审查
        review = results.get('pool_review', {})
        lines.append(f"\n🔍 追踪池审查 (现有 {review.get('existing', 0)} 只)")

        sell_decisions = review.get('sell_decisions', [])
        if sell_decisions:
            for sd in sell_decisions:
                lines.append(f"  ❌ 卖出: {sd['ts_code']} {sd.get('name', '')} — {sd['detail']}")
        else:
            lines.append("  ✅ 无需卖出")

        hold_checks = review.get('hold_checks', [])
        if hold_checks:
            for hc in hold_checks:
                lines.append(f"  ➖ {hc['ts_code']}: 继续持有 (breakdown={hc.get('breakdown_score', 'N/A')})")

        # 新股推荐
        new_picks = results.get('new_picks', [])
        if new_picks:
            lines.append(f"\n🆕 选股推荐 ({len(new_picks)} 只)")
            for i, pick in enumerate(new_picks):
                lines.append(f"  {pick.get('rank', i + 1)}. {pick['ts_code']} {pick.get('name', '')}")
                lines.append(f"     综合评分: {pick.get('composite_score', 0):.1f}")
                lines.append(f"     趋势:{pick.get('trend', 0):.0f} 动量:{pick.get('momentum', 0):.0f} "
                             f"量能:{pick.get('volume', 0):.0f} 风险:{pick.get('risk', 0):.0f}")
                lines.append(f"     入场价: {pick.get('entry_price', 0):.2f}  "
                             f"止损: {pick.get('stop_loss', 0):.2f}  "
                             f"止盈: {pick.get('take_profit', 0):.2f}")
                lines.append(f"     理由: {pick.get('rationale', '')}")
        else:
            lines.append(f"\n🆕 选股推荐: 无需补仓（池已满或无可选股）")

        # 池状态
        pool_after = results.get('pool_after', [])
        lines.append(f"\n📋 当前追踪池 ({len(pool_after)}/3)")
        for code in pool_after:
            lines.append(f"  • {code}")

        # 统计
        stats = results.get('stats', {})
        if stats.get('total_trades', 0) > 0:
            lines.append(f"\n📈 历史统计")
            lines.append(f"  总交易: {stats['total_trades']}  |  "
                         f"胜率: {stats['win_rate']}%  |  "
                         f"累计盈亏: {stats['cumulative_pnl']:+.2f}%")

        lines.append("")
        lines.append("=" * 60)
        return "\n".join(lines)

    @staticmethod
    def format_pool_status(pool_entries: List, stats: Dict[str, Any]) -> str:
        """格式化追踪池状态"""
        lines = []
        lines.append("=" * 50)
        lines.append(f"  追踪池状态 ({len(pool_entries)}/3)")
        lines.append("=" * 50)

        if not pool_entries:
            lines.append("\n  追踪池为空")
        else:
            for i, entry in enumerate(pool_entries):
                lines.append(f"\n  [{i + 1}] {entry.ts_code} {entry.name}")
                lines.append(f"      买入日: {entry.buy_date}  买入价: {entry.buy_price:.2f}")
                lines.append(f"      止损: {entry.stop_loss_price:.2f}  止盈: {entry.take_profit_price:.2f}")
                lines.append(f"      持仓: {entry.hold_days}天  最高: {entry.highest_since_buy:.2f}")

        lines.append(f"\n历史统计: {stats['total_trades']}笔交易, "
                     f"胜率{stats['win_rate']}%, 累计{stats['cumulative_pnl']:+.2f}%")
        lines.append("=" * 50)
        return "\n".join(lines)

    @staticmethod
    def format_history(history: List[dict]) -> str:
        """格式化交易历史"""
        lines = []
        lines.append("=" * 60)
        lines.append(f"  交易历史 ({len(history)} 笔)")
        lines.append("=" * 60)

        if not history:
            lines.append("\n  暂无交易记录")
        else:
            for i, t in enumerate(history):
                pnl_str = f"+{t['pnl_pct']}%" if t['pnl_pct'] >= 0 else f"{t['pnl_pct']}%"
                lines.append(
                    f"  [{i + 1}] {t['ts_code']} {t.get('name', '')}  "
                    f"{t.get('buy_date', '')} → {t.get('sell_date', '')}  "
                    f"{t.get('buy_price', 0):.2f} → {t.get('sell_price', 0):.2f}  "
                    f"{pnl_str}  [{t.get('sell_reason', '')}]"
                )

        lines.append("=" * 60)
        return "\n".join(lines)

    @staticmethod
    def to_json(results: Dict[str, Any]) -> str:
        """导出为JSON"""
        return json.dumps(results, ensure_ascii=False, indent=2, default=str)
