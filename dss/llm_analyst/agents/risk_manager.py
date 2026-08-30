"""
Risk Manager Agent — 参考 TradingAgents 的 Risk Management 团队 + Portfolio Manager。

角色: 在牛熊研究员辩论后，综合双方论点做出最终卖出决策。
这是卖出侧决策链的终点 —— 类似 TradingAgents 中 Risk Management 辩论后 Portfolio Manager 的最终审批。
"""

import json

from dss.llm_analyst.agents.base import BaseAgent, AgentResult


class RiskManager(BaseAgent):
    """风控经理 — 裁决牛熊辩论，做出最终卖出决策。

    TradingAgents 对应: Aggressive/Conservative/Neutral Debator + Portfolio Manager
    在DSS中简化为一个 Agent，综合 Bull/Bear 双方论点做最终裁决。
    """

    # 必需输出字段（缺失 → 校验失败 → 重试 → 抛 AgentOutputError 中断）
    required_fields = ("verdict", "confidence", "reasoning")

    name = "risk_manager"
    role = "风控经理"
    expertise = (
        "风险收益比评估、牛熊论点质量判断、持仓风险管理、"
        "市场系统性风险评估、止损纪律执行监督"
    )
    perspective = (
        "你是最终裁决者。你会收到多头研究员和空头研究员的辩论报告。"
        "你的任务不是重复他们的分析，而是：\n"
        "1) 评判谁的论点更有说服力（不是谁更极端）\n"
        "2) 结合市场整体环境判断风险级别\n"
        "3) 在'宁可错过也不冒险'和'不要过度交易'之间平衡\n"
        "4) 短线资金效率：这是短线交易，持仓时间是有成本的，浮盈兑现优先\n"
        "你的默认立场是尊重量化信号，但可以被高质量的相反论点说服。"
        "在熊市中你更倾向于支持卖出，在牛市中你更倾向于给予更多容忍。"
    )

    output_schema = {
        "verdict": "SELL / HOLD — 最终卖出决策",
        "confidence": "0.0-1.0",
        "debate_winner": "BULL / BEAR / TIE — 谁的论点更强",
        "decisive_factors": ["决定性因素"],
        "action": "具体操作建议",
        "reasoning": "详细裁决推理（必须引用双方具体论点）",
    }

    def _build_system(self) -> str:
        return f"""# 角色: {self.role}

## 专业领域
{self.expertise}

## 分析视角
{self.perspective}

## 裁决框架

### 判断谁的论点更强
| 标准 | 权重 |
|------|------|
| 论点的数据支撑程度 | ⭐⭐⭐⭐⭐ |
| 是否有明确的反驳证据 | ⭐⭐⭐⭐ |
| 论点的逻辑一致性 | ⭐⭐⭐ |
| 与市场环境的契合度 | ⭐⭐⭐ |
| 极端程度（越极端越不可信） | ⭐⭐ |

### 卖出决策矩阵
| 量化信号 | Bull 论点 | Bear 论点 | 市场环境 | 最终决策 |
|---------|----------|----------|---------|---------|
| STOP_LOSS | 强(≥0.7) | 弱(<0.6) | 牛市 | HOLD — 给予机会 |
| STOP_LOSS | 弱 | 强 | 熊市 | SELL — 立即执行 |
| STOP_LOSS | 弱 | 弱 | 任何 | SELL — 尊重止损纪律 |
| TAKE_PROFIT | 强 | 强 | 牛市 | HOLD — 可能还有空间 |
| TAKE_PROFIT | 弱 | 强 | 熊市 | SELL — 锁定利润 |
| MA_BREAKDOWN | 强 | 弱 | 牛市 | HOLD — 可能是洗盘 |
| MA_BREAKDOWN | 弱 | 强 | 熊市 | SELL — 趋势破位 |

### 短线资金效率原则（重点 — 短线交易的核心纪律）
- **浮盈兑现优先**: 一旦有显著浮盈（>5%），从最高点回撤超过 1/3 时 → 倾向 SELL 锁定利润，不要等利润全部回吐
- **持仓时间成本**: 持仓天数超过参考上限（sell_detail 中有 hold_days_ref）时，资金被占用 = 持续的机会成本 → 倾向 SELL，除非 Bull 能给出"立即加速上涨"的强证据（confidence ≥ 0.8）
- **盈利转亏损是最大禁忌**: 曾经浮盈超过 3% 的持仓若现在回到成本线附近或浮亏 → 强烈倾向 SELL（这是短线最典型的失败模式，必须避免）
- 持仓 < 参考期且浮盈 → 可以继续持有（给趋势发展空间），但每天必须评估

### 风控优先原则
- 在熊市中，风控优先于收益追求
- 持仓浮亏 >5% 时，除非有极强的持有理由（Bull confidence ≥ 0.8），否则 SELL
- 连续两天触发卖出信号 → SELL，不再容忍

## 输出要求
输出严格的 JSON 格式。必须引用多头和空头研究员的具体的、有说服力的论点。
"""

    def adjudicate(
        self,
        context: dict,
        bull_result: AgentResult,
        bear_result: AgentResult,
    ) -> AgentResult:
        """裁决牛熊辩论，做出最终卖出决策。"""
        trigger_reason = context.get("sell_reason", "UNKNOWN")
        trigger_detail = context.get("sell_detail", "")

        # LLM 列表字段可能是 dict 列表/嵌套结构 — 统一转字符串
        def _fmt(items) -> str:
            if not items:
                return "无"
            if isinstance(items, str):
                return items
            parts_out = []
            for it in items:
                if isinstance(it, dict):
                    parts_out.append(json.dumps(it, ensure_ascii=False))
                else:
                    parts_out.append(str(it))
            return ", ".join(parts_out)

        parts = [
            f"股票: {context.get('ts_code', 'N/A')} ({context.get('name', '')})",
            f"买入价: {context.get('buy_price', 'N/A'):.2f}" if context.get("buy_price") else "",
            f"当前价: {context.get('current_price', 'N/A'):.2f}" if context.get("current_price") else "",
            f"持仓天数: {context.get('hold_days', 0)} / 参考上限 {context.get('hold_days_ref', 10)} 天",
            f"期间最高价: {context.get('highest_price', 0):.2f} "
            f"(最高浮盈 {context.get('max_profit_pct', 0):+.2f}%, "
            f"从高点回撤 {context.get('pullback_from_high', 0):.2f}%)",
            "",
            f"=== 触发信号 ===",
            f"规则: {trigger_reason}",
            f"详情: {trigger_detail}",
            "",
            "=== 多头研究员（BULL）辩护 ===",
            f"判定: {bull_result.verdict}  置信度: {bull_result.confidence:.2f}",
            f"持有理由: {_fmt(bull_result.raw_output.get('hold_reasons'))}",
            f"量化信号弱点: {_fmt(bull_result.raw_output.get('quant_signal_weakness'))}",
            f"推理: {bull_result.reasoning}",
            "",
            "=== 空头研究员（BEAR）验证 ===",
            f"判定: {bear_result.verdict}  置信度: {bear_result.confidence:.2f}",
            f"看跌信号: {_fmt(bear_result.raw_output.get('bearish_signals'))}",
            f"下行风险: {_fmt(bear_result.raw_output.get('downside_risks'))}",
            f"推理: {bear_result.reasoning}",
        ]

        market = context.get("market_env", {})
        if market:
            parts += [
                "",
                "=== 市场环境 ===",
                f"情绪: {market.get('sentiment', 'N/A')}",
                f"市场评分: {market.get('market_score', 'N/A')}",
            ]

        parts.append("\n请综合牛熊辩论，做出最终卖出裁决（SELL/HOLD）。")

        user_prompt = "\n".join(parts)

        # fail-fast: 输出校验失败（AgentOutputError）直接上抛，
        # 不静默降级为"默认 SELL"——宁让本次审查失败，也不把默认值伪装成 LLM 裁决。
        raw = self._call_llm(self._build_system(), user_prompt)
        return self._parse_result(raw)


RISK_MANAGER_TEMPERATURE = 0.2  # 风控需要最冷静
