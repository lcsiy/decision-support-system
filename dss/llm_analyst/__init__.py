"""DSS LLM 分析师模块 v10.1 — 多 Agent 协作架构。

参考 TradingAgents 的团队设计：
- 买入侧: TechnicalAnalyst + NewsSentimentAnalyst → SwingTrader(综合)
- 卖出侧: BullResearcher ∥ BearResearcher → RiskManager(裁决)

核心设计原则:
- 每个 Agent 拥有独立角色、专业领域和分析视角
- Agent 间通过结构化输出（AgentResult）传递信息
- 并行分析 + 对抗辩论 + 序列合成
- 非阻塞：任一 Agent 失败不影响整体流程
"""

from dss.llm_analyst.client import swing_llm, ask_json
from dss.llm_analyst.agents import (
    BaseAgent, AgentResult,
    TechnicalAnalyst, NewsSentimentAnalyst, SwingTrader,
    BullResearcher, BearResearcher, RiskManager,
)
from dss.llm_analyst.buy_side import analyze_candidate, analyze_batch_buy
from dss.llm_analyst.sell_side import review_sell_signal as review_sell_multi_agent

# 向后兼容：保留旧接口
from dss.llm_analyst.swing_analyst import analyze_single, analyze_batch
from dss.llm_analyst.sell_advisor import review_sell_signal

__all__ = [
    # LLM 客户端
    "swing_llm", "ask_json",
    # Agent 基类
    "BaseAgent", "AgentResult",
    # 买入侧 Agent
    "TechnicalAnalyst", "NewsSentimentAnalyst", "SwingTrader",
    # 卖出侧 Agent
    "BullResearcher", "BearResearcher", "RiskManager",
    # 多 Agent 协作
    "analyze_candidate", "analyze_batch_buy",
    "review_sell_multi_agent",
    # 兼容旧接口
    "analyze_single", "analyze_batch", "review_sell_signal",
]
