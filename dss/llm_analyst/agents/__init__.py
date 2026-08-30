"""DSS 多 Agent 团队 — 参考 TradingAgents 架构设计。

每个 Agent 拥有独立角色、工具访问、结构化输出。
Agent 间通过并行分析 + 对抗辩论 + 合成决策协作。
"""

from dss.llm_analyst.agents.base import BaseAgent, AgentResult
from dss.llm_analyst.agents.technical import TechnicalAnalyst
from dss.llm_analyst.agents.news_analyst import NewsSentimentAnalyst
from dss.llm_analyst.agents.swing_trader import SwingTrader
from dss.llm_analyst.agents.bull_researcher import BullResearcher
from dss.llm_analyst.agents.bear_researcher import BearResearcher
from dss.llm_analyst.agents.risk_manager import RiskManager

__all__ = [
    "BaseAgent", "AgentResult",
    "TechnicalAnalyst", "NewsSentimentAnalyst", "SwingTrader",
    "BullResearcher", "BearResearcher", "RiskManager",
]
