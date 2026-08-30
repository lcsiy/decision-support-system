"""
Swing Trader Agent — 参考 TradingAgents 的 Trader + Portfolio Manager。

角色: 综合技术和新闻两个维度的分析，做出最终的买入决策。
这是买入侧决策链的终点 —— 类似 TradingAgents 中 Trader 接收 Analysts 报告后做决策。
"""

from dss.llm_analyst.agents.base import BaseAgent, AgentResult


class SwingTrader(BaseAgent):
    """短线交易员 — 综合多维度分析，做出最终买入决策。

    TradingAgents 对应: Trader（综合报告→决策） + Portfolio Manager（最终审批）
    在DSS中简化为一个 Agent，因为它不需要管理投资组合（追踪池负责）。
    """

    # 必需输出字段（缺失 → 校验失败 → 重试 → 抛 AgentOutputError 中断）
    required_fields = ("verdict", "confidence", "consensus")

    name = "swing_trader"
    role = "短线交易员"
    expertise = (
        "多维度信息融合决策、风险收益比评估、仓位管理、"
        "市场情绪解读、技术面与基本面交叉验证"
    )
    perspective = (
        "你是最终决策者。你会收到技术分析师和新闻情绪分析师的独立报告，"
        "你的任务不是重复他们的分析，而是："
        "1) 找出两人都看到的机会（共识=高确定性）"
        "2) 发现两人意见不一致的地方（分歧=需要判断）"
        "3) 结合市场整体环境判断最终是否买入\n"
        "你必须在熊市中更加谨慎，在牛市中更加积极。"
        "你会为每只股票给出明确的 BUY / HOLD / SKIP 判定。"
    )

    output_schema = {
        "verdict": "BUY / HOLD / SKIP — 最终买入决策",
        "confidence": "0.0-1.0",
        "consensus": "STRONG / MODERATE / WEAK / CONFLICT — 分析师一致程度",
        "key_findings": ["综合关键发现"],
        "risk_flags": ["综合风险"],
        "catalysts": ["综合正面催化剂"],
        "reasoning": "最终决策推理（必须引用两位分析师的具体发现）",
    }

    def _build_system(self) -> str:
        return f"""# 角色: {self.role}

## 专业领域
{self.expertise}

## 分析视角
{self.perspective}

## 决策框架

### 信号融合规则（轻仓短线 — 偏向捕捉拐点机会）

> 你是轻仓短线交易员。你的任务是在合理风险下捕捉机会，
> 而不是完美择时。市场不需要完美才能买入 — 只要有足够
> 的证据表明风险收益比有利就可以行动。

| 技术 | 新闻情绪 | 市场环境 | 决策 |
|------|---------|---------|------|
| BUY | BULLISH | 牛市/震荡/反弹中 | **BUY** — 标准入场 |
| BUY | BULLISH | 熊市但转向信号活跃 | **BUY** — 反弹初期轻仓 |
| BUY | BULLISH | 深度熊市无转向 | **HOLD** — 等待企稳 |
| BUY | NEUTRAL | 反弹中 | **BUY** — 技术驱动 |
| HOLD | BULLISH | 反弹中 | **BUY** — 情绪回暖可试 |
| HOLD | BULLISH | 熊市无转向 | **HOLD** — 等技术确认 |
| SKIP | 任何 | 任何 | **SKIP** — 尊重技术判断 |

### 转向信号识别（以下情况倾向给 BUY）
- 单日涨幅 >1.5% + 连续2日上涨 → 强转向，积极买入
- 单日涨幅 >1.5%（单日） → 可能是转折点，给 BUY 但 confidence ≤ 0.7
- 从 MA20 下方深度超卖反弹 → 反弹第一波，谨慎 BUY
- MA5 拐头向上 → 短期趋势改善，可以跟随
- 放量反弹 → 增量资金入场，提高 confidence

### 轻仓短线特别考量
- **仓位分散**: 你已经持有其他股票，不必担心单只风险
- **止损纪律**: BUY 后由风控系统跟踪，不需要完美买点
- **错过风险**: 在反弹初期过于保守导致空仓，同样是风险
- **隔夜风险**: 你的决策在收盘后做出、次日开盘执行。如果信号偏弱（confidence < 0.6），隔夜的不确定性可能让本该赚的交易变成亏的 → 给 HOLD

## 输出格式（严格遵守）

输出严格的 JSON。verdict 必须是三个值之一: "BUY", "HOLD", "SKIP"

示例: {{"verdict":"BUY","confidence":0.70,"consensus":"MODERATE","key_findings":["综合发现"],"risk_flags":[],"catalysts":[],"reasoning":"推理..."}}

⚠️ **关键规则**:
- verdict 只能是 "BUY"、"HOLD"、"SKIP" 之一，不能是长句子
- 如果你的推理指向买入，verdict 必须是 "BUY"
- 轻仓短线策略：在反弹/转向市场中，技术面OK就应给 BUY
- 不要因为"市场不是完美牛市"就全部判 HOLD
"""

    # 覆盖 _build_prompt 以包含上游 Agent 的结果
    def synthesize(
        self,
        context: dict,
        technical_result: AgentResult,
        news_result: AgentResult,
    ) -> AgentResult:
        """综合技术和新闻分析的结果，做出最终决策。"""
        parts = [
            f"股票: {context.get('ts_code', 'N/A')} ({context.get('name', '')})",
            "",
            "=== 技术分析师报告 ===",
            f"判定: {technical_result.verdict}  置信度: {technical_result.confidence:.2f}",
            f"趋势质量: {technical_result.raw_output.get('trend_quality', 'N/A')}",
            f"关键发现: {', '.join(technical_result.key_findings) if technical_result.key_findings else '无'}",
            f"技术风险: {', '.join(technical_result.risk_flags) if technical_result.risk_flags else '无'}",
            f"技术催化剂: {', '.join(technical_result.catalysts) if technical_result.catalysts else '无'}",
            f"推理: {technical_result.reasoning}",
            "",
            "=== 新闻情绪分析师报告 ===",
            f"判定: {news_result.verdict}  置信度: {news_result.confidence:.2f}",
            f"情绪: {news_result.raw_output.get('sentiment', 'N/A')}",
            f"关键发现: {', '.join(news_result.key_findings) if news_result.key_findings else '无'}",
            f"新闻风险: {', '.join(news_result.risk_flags) if news_result.risk_flags else '无'}",
            f"新闻催化剂: {', '.join(news_result.catalysts) if news_result.catalysts else '无'}",
            f"推理: {news_result.reasoning}",
        ]

        market = context.get("market_env", {})
        if market:
            parts += [
                "",
                "=== 市场环境 ===",
                f"情绪: {market.get('sentiment', 'N/A')}",
                f"市场评分: {market.get('market_score', 'N/A')}",
                f"上证涨跌: {market.get('sh_change_pct', 'N/A')}%",
            ]

        parts.append("\n请综合以上所有信息，给出最终买入决策（BUY/HOLD/SKIP）。")

        user_prompt = "\n".join(parts)

        # fail-fast: 输出校验失败（AgentOutputError）直接上抛，不静默降级为 HOLD
        raw = self._call_llm(self._build_system(), user_prompt)
        return self._parse_result(raw)


TRADER_TEMPERATURE = 0.25
