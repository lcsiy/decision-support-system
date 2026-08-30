"""
买入侧多 Agent 协作 — 参考 TradingAgents 的 Analyst Team → Trader 流程。

流程: TechnicalAnalyst ∥ NewsSentimentAnalyst → SwingTrader(综合决策)
      (并行分析)                                    (序列合成)

不同于简单的单次 LLM 调用，这里实现了：
- 并行独立分析（2个Agent同时工作，互不干扰）
- 结构化中间输出（每个Agent产出带置信度的判定）
- 序列合成决策（Trader接收两个独立报告做最终判断）
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, List

from dss.llm_analyst.agents.base import _ohlcv_summary, _news_summary
from dss.llm_analyst.agents.technical import TechnicalAnalyst
from dss.llm_analyst.agents.news_analyst import NewsSentimentAnalyst
from dss.llm_analyst.agents.swing_trader import SwingTrader

logger = logging.getLogger(__name__)


def analyze_candidate(
    ts_code: str,
    name: str = "",
    ohlcv_df=None,
    news_text: str = "",
    quantitative_score: float = 50,
    quantitative_factors: Dict[str, float] | None = None,
    market_env: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    对单个候选股执行完整的多 Agent 买入分析。

    流程:
      1. TechnicalAnalyst.analyze()   ─┐
      2. NewsSentimentAnalyst.analyze() ─┤ 并行
      3. SwingTrader.synthesize()       ─┘ 序列（接收两个报告）

    Returns:
        包含所有Agent结果和最终决策的完整字典。
    """
    # 判断是否在交易时段
    from datetime import datetime
    now = datetime.now()
    trading_hours = now.weekday() < 5 and (
        (9*60+30 <= now.hour*60+now.minute <= 11*60+30) or
        (13*60 <= now.hour*60+now.minute <= 15*60)
    )

    context = {
        "ts_code": ts_code,
        "name": name,
        "ohlcv_summary": _ohlcv_summary(ohlcv_df),
        "news_summary": _news_summary(news_text),
        "quantitative_score": quantitative_score,
        "quantitative_factors": quantitative_factors or {},
        "market_env": market_env or {},
        "using_realtime": trading_hours,
    }

    # ---- 阶段1: 并行分析 ----
    technical = TechnicalAnalyst()
    news_agent = NewsSentimentAnalyst()

    tech_result = None
    news_result = None

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_tech = executor.submit(technical.analyze, context)
        future_news = executor.submit(news_agent.analyze, context)

        for future in as_completed([future_tech, future_news]):
            try:
                result = future.result(timeout=60)
                if future == future_tech:
                    tech_result = result
                else:
                    news_result = result
            except AgentOutputError:
                # 输出校验失败 → fail-fast，不做静默默认（宁失败不误判）
                raise
            except Exception as e:
                logger.warning("Agent 并行分析异常: %s", e)

    # 容错：仅网络/超时异常可降级，且显式标注"降级"；输出校验失败（AgentOutputError）
    # 直接上抛 —— 宁让该候选分析失败，也不把默认 HOLD 伪装成 LLM 判定。
    from dss.llm_analyst.agents.base import AgentResult, AgentOutputError
    if tech_result is None:
        tech_result = AgentResult(
            agent_name="technical_analyst", agent_role="技术分析师",
            verdict="HOLD", confidence=0.0,
            key_findings=[f"分析超时或失败（降级，非LLM判定）"],
            reasoning="分析超时，降级结果",
        )
    if news_result is None:
        news_result = AgentResult(
            agent_name="news_sentiment_analyst", agent_role="新闻情绪分析师",
            verdict="NEUTRAL", confidence=0.0,
            key_findings=["分析超时或失败（降级，非LLM判定）"],
            reasoning="分析超时，降级结果",
        )

    # ---- 阶段2: 交易员合成决策 ----
    trader = SwingTrader()
    trader_result = trader.synthesize(context, tech_result, news_result)

    # ---- 计算融合评分 ----
    combined_score = _compute_buy_score(
        quantitative_score, trader_result, tech_result, news_result,
    )

    return {
        "ts_code": ts_code,
        "quantitative_score": quantitative_score,
        "combined_score": combined_score,
        "technical": {
            "verdict": tech_result.verdict,
            "confidence": tech_result.confidence,
            "trend_quality": tech_result.raw_output.get("trend_quality", ""),
            "key_findings": tech_result.key_findings,
            "risk_flags": tech_result.risk_flags,
        },
        "news_sentiment": {
            "verdict": news_result.verdict,
            "confidence": news_result.confidence,
            "sentiment": news_result.raw_output.get("sentiment", ""),
            "key_findings": news_result.key_findings,
            "catalysts": news_result.catalysts,
        },
        "trader": {
            "verdict": trader_result.verdict,
            "confidence": trader_result.confidence,
            "consensus": trader_result.raw_output.get("consensus", ""),
            "reasoning": trader_result.reasoning,
            "risk_flags": trader_result.risk_flags,
            "catalysts": trader_result.catalysts,
        },
    }


def analyze_batch_buy(
    candidates: List[Dict[str, Any]],
    max_workers: int = 3,
) -> List[Dict[str, Any]]:
    """
    并行分析一批候选股。

    每只股票内部是 3 Agent 协作（Technician + News → Trader），
    股票之间是并行处理。
    """
    results = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for c in candidates:
            future = executor.submit(
                analyze_candidate,
                c.get("ts_code", ""),
                c.get("name", ""),
                c.get("ohlcv_df"),
                c.get("news_text", ""),
                c.get("composite_score", 50),
                c.get("factors", {}),
                c.get("market_env", {}),
            )
            futures[future] = c

        for future in as_completed(futures):
            try:
                result = future.result(timeout=120)
                results.append(result)
            except AgentOutputError as e:
                # 输出校验失败 → 显式标记 FAILED（不伪装成 SKIP），
                # 由编排层决定中止或跳过；绝不让"分析失败"混入正常判定
                c = futures[future]
                logger.error("候选 %s LLM 输出校验失败: %s", c.get("ts_code"), e)
                results.append({
                    "ts_code": c.get("ts_code", ""),
                    "combined_score": c.get("composite_score", 50),
                    "llm_failed": True,
                    "llm_failure": str(e),
                    "trader": {"verdict": "FAILED", "reasoning": str(e)},
                })
            except Exception as e:
                c = futures[future]
                results.append({
                    "ts_code": c.get("ts_code", ""),
                    "combined_score": c.get("composite_score", 50),
                    "llm_failed": True,
                    "llm_failure": f"分析异常: {e}",
                    "trader": {"verdict": "FAILED", "reasoning": f"分析异常: {e}"},
                })

    # 按融合评分排序
    results.sort(key=lambda x: x.get("combined_score", 0), reverse=True)
    return results


def _compute_buy_score(
    quant_score: float,
    trader: object,
    tech: object,
    news: object,
) -> float:
    """融合量化评分和多 Agent 结果计算最终评分。"""
    modifier = 1.0

    # Trader 判定影响
    verdict = getattr(trader, "verdict", "HOLD")
    confidence = getattr(trader, "confidence", 0.5)
    if verdict == "BUY":
        modifier = 1.1 + confidence * 0.15
    elif verdict == "SKIP":
        modifier = 0.4
    elif verdict == "HOLD":
        modifier = 0.9 + confidence * 0.1

    # 技术趋势质量加成
    trend_quality = tech.raw_output.get("trend_quality", "") if hasattr(tech, "raw_output") else ""
    if trend_quality == "STRONG":
        modifier += 0.05
    elif trend_quality == "BEARISH":
        modifier -= 0.1

    # 新闻情绪加成
    sentiment = news.raw_output.get("sentiment", "") if hasattr(news, "raw_output") else ""
    if sentiment == "POSITIVE":
        modifier += 0.03

    score = quant_score * modifier + confidence * 5
    return round(min(100, max(0, score)), 1)
