"""
报告格式化器。

从 UltraShortTailAnalyzer.generate_report() 和 _print_cron_summary() 提取。

提供两种输出格式：
1. 人类可读格式 — 完整的文本报告
2. Cron JSON 格式 — 紧凑 JSON 摘要（避免 LLM token 超限）
"""

import json
from datetime import datetime
from typing import Dict, Any, List, Optional


class ReportFormatter:
    """
    报告格式化器。

    使用方式:
        fmt = ReportFormatter()
        report_text = fmt.format_human(recommendations, market_env)
        cron_json = fmt.format_cron_json(recommendations, market_env, report_file)
    """

    VERSION = "9.0"

    def format_human(
        self,
        recommendations: List[Dict[str, Any]],
        market_env: Optional[Dict[str, Any]] = None,
    ) -> str:
        """生成人类可读的文本报告"""
        if not recommendations:
            return "未找到符合条件的超短线尾盘交易机会。"

        lines = []
        lines.append("=" * 80)
        lines.append("🚀 超短线尾盘分析报告 v9.0 — 两维度精简版")
        lines.append("=" * 80)
        lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("分析范围: 热榜前300股票（排除科创板/创业板/ST）")
        lines.append("两维度: 技术动量(60%,含成交量因子+尾盘量价推断) + 情绪面(40%)")

        # 大盘环境
        if market_env and market_env.get('available'):
            sentiment = market_env.get('market_sentiment', 'neutral')
            mult = market_env.get('market_multiplier', 1.0)
            sh_chg = market_env.get('sh_index_change', 0)
            emoji = {
                'bullish': '🟢', 'slightly_bullish': '🟡',
                'neutral': '⚪', 'slightly_bearish': '🟠', 'bearish': '🔴',
            }.get(sentiment, '⚪')
            lines.append(f"大盘环境: {emoji} 上证 {sh_chg:+.2f}% | 乘数因子 ×{mult:.2f}")

        lines.append("=" * 80)
        lines.append(f"\n📊 总体结果:")
        lines.append(f"推荐股票数: {len(recommendations)} 只")
        if recommendations:
            lines.append(f"最高评分: {recommendations[0].get('comprehensive_score', 0):.1f}/100")

        lines.append(f"\n💡 详细推荐:")
        for i, rec in enumerate(recommendations, 1):
            self._format_single_stock(lines, i, rec)

        # 大盘备注
        if market_env and market_env.get('available'):
            mult = market_env.get('market_multiplier', 1.0)
            if mult < 1.0:
                discount = (1 - mult) * 100
                lines.append(f"\n⚠️ 大盘预警: 市场偏弱，综合评分已自动打折 {discount:.0f}%，建议减仓或观望。")
            elif mult > 1.0:
                lines.append(f"\n✅ 大盘提示: 市场偏强，尾盘策略胜率较高。")

        # 操作建议
        lines.append(f"\n🎯 操作建议:")
        if recommendations:
            top = recommendations[0]
            plan = top.get('trading_plan', {})
            lines.append(
                f"首选: {top.get('name')}，尾盘14:30后买入，"
                f"仓位{plan.get('position_pct', 'N/A')}，"
                f"止损{plan.get('stop_loss_pct', 'N/A')}，"
                f"次日9:30-10:00卖出。"
            )

        lines.append(f"\n⚠️ 风险提示:")
        lines.append("1. 超短线策略风险极高，当日买入次日才能卖出（T+1）")
        lines.append("2. 次日开盘可能跳空低开，需严格执行止损")
        lines.append("3. 建议单只股票仓位不超过总资金的20%")
        lines.append("4. 本报告仅供学习研究，不构成投资建议")

        return "\n".join(lines)

    def format_cron_json(
        self,
        recommendations: List[Dict[str, Any]],
        market_env: Optional[Dict[str, Any]] = None,
        report_file: str = "",
        feedback_file: Optional[str] = None,
        weights: Optional[Dict[str, float]] = None,
    ) -> str:
        """生成 Cron 模式的紧凑 JSON 摘要"""
        summary: Dict[str, Any] = {
            "v": self.VERSION,
            "ts": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "count": len(recommendations),
        }

        if market_env and market_env.get('available'):
            summary["market"] = {
                "sh_chg_pct": round(market_env.get('sh_index_change', 0), 2),
                "sentiment": market_env.get('market_sentiment', 'neutral'),
                "multiplier": round(market_env.get('market_multiplier', 1.0), 2),
            }

        picks = []
        for rec in recommendations:
            plan = rec.get('trading_plan', {})
            dims = rec.get('dimension_scores', {})
            pred = rec.get('next_day_prediction', {})
            picks.append({
                "name": rec.get('name', ''),
                "code": rec.get('ts_code', ''),
                "price": round(rec.get('current_price', 0), 2),
                "chg_pct": round(rec.get('daily_change_pct', 0), 2),
                "score": round(rec.get('comprehensive_score', 0), 1),
                "tm": round(dims.get('technical_momentum', 0), 1),
                "se": round(dims.get('sentiment', 0), 1),
                "hop": round(pred.get('high_open_probability', 0), 1),
                "exp_chg": round(pred.get('expected_open_change_pct', 0), 2),
                "risk": rec.get('risk_assessment', {}).get('risk_level', 'N/A'),
                "action": plan.get('recommendation', 'N/A'),
                "position": plan.get('position_pct', 'N/A'),
                "stop_loss": plan.get('stop_loss_pct', 'N/A'),
            })
        summary["picks"] = picks

        if weights:
            summary["weights"] = {k: round(v, 4) for k, v in weights.items()}

        summary["report_file"] = report_file
        if feedback_file:
            summary["feedback_file"] = feedback_file

        return json.dumps(summary, ensure_ascii=False, indent=2)

    # ---- 内部 ----

    def _format_single_stock(self, lines: List[str], i: int, rec: Dict[str, Any]) -> None:
        """格式化单只股票的详细信息"""
        ts_code = rec.get('ts_code', '')
        name = rec.get('name', '')
        score = rec.get('comprehensive_score', 0)
        raw_score = rec.get('raw_score', score)
        price = rec.get('current_price', 0)
        change = rec.get('daily_change_pct', 0)

        lines.append(f"\n{i}. 【{name}】({ts_code})")
        lines.append(f"   💰 当前价格: {price:.2f}元 ({'+' if change >= 0 else ''}{change:.2f}%)")
        score_note = f" (原始{raw_score:.1f})" if abs(raw_score - score) > 0.5 else ""
        lines.append(f"   📈 综合评分: {score:.1f}/100{score_note}")

        # 两维度
        dims = rec.get('dimension_scores', {})
        lines.append("   🎯 两维度评分:")
        lines.append(f"     - 技术动量: {dims.get('technical_momentum', 0):.1f}/100 (60%)")
        lines.append(f"     - 情绪面: {dims.get('sentiment', 0):.1f}/100 (40%)")

        # 技术动量子项
        md = rec.get('momentum_details', {})
        lines.append("   📊 技术动量子项:")
        lines.append(f"     - 价格位置: {md.get('price_position', 0)*100:.0f}%")
        lines.append(f"     - 成交量趋势: {md.get('volume_trend', 'N/A')} "
                     f"(相对5日均量 {md.get('relative_volume_vs_5d', 0):.2f}x)")
        lines.append(f"     - 成交量评分: {md.get('volume_score', 50):.0f}")
        if md.get('minute_data_available'):
            lines.append(f"     - 尾盘趋势: {md.get('recent_trend', 0)*100:.3f}%/min")
        else:
            lines.append("     - ⚠️ 无分钟数据，趋势子项已降权")
        tail_sig = md.get('tail_volume_price_signal', 0)
        lines.append(f"     - 尾盘量价推断: {tail_sig:.2f} "
                     f"({'流入' if tail_sig > 0 else '流出/中性'})")

        # 预测
        pred = rec.get('next_day_prediction', {})
        lines.append("   🔮 次日开盘预测:")
        lines.append(f"     - 高开概率: {pred.get('high_open_probability', 0):.1f}%")
        lines.append(f"     - 预期涨跌幅: {pred.get('expected_open_change_pct', 0):.2f}%")

        # 风险
        risk = rec.get('risk_assessment', {})
        lines.append(f"   ⚠️ 风险评估: {risk.get('risk_level', 'N/A')} "
                     f"(评分: {risk.get('risk_score', 0):.0f}/100)")

        # 交易计划
        plan = rec.get('trading_plan', {})
        lines.append(f"   🎯 交易建议: {plan.get('recommendation', 'N/A')}")
        lines.append(f"   📊 置信度: {plan.get('confidence', 'N/A')}")
        lines.append(f"   💰 买入价: {plan.get('buy_price', 'N/A')}元")
        lines.append(f"   ⏰ 买入时间: {plan.get('buy_time', 'N/A')}")
        lines.append(f"   ⏰ 卖出时间: {plan.get('sell_time', 'N/A')}")
        lines.append(f"   📈 仓位: {plan.get('position_pct', 'N/A')}")
        lines.append(f"   🛑 止损: {plan.get('stop_loss_pct', 'N/A')} "
                     f"({plan.get('stop_loss_price', 'N/A')}元)")
