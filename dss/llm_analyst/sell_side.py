"""
卖出侧多 Agent 协作 — 参考 TradingAgents 的 Research Team + Risk Management 流程。

流程: BullResearcher ∥ BearResearcher → RiskManager(裁决)
      (并行辩论)                              (序列裁决)

对抗辩论设计（与 TradingAgents 一致）:
- Bull 和 Bear 独立分析，互不知晓对方结论
- Risk Manager 接收双方报告后裁决
- 默认尊重量化信号，但可被高质量论点击败
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any

from dss.llm_analyst.agents.base import _ohlcv_summary, AgentResult, AgentOutputError
from dss.llm_analyst.agents.bull_researcher import BullResearcher
from dss.llm_analyst.agents.bear_researcher import BearResearcher
from dss.llm_analyst.agents.risk_manager import RiskManager

logger = logging.getLogger(__name__)


def review_sell_signal(
    ts_code: str,
    name: str = "",
    buy_price: float = 0,
    current_price: float = 0,
    hold_days: int = 0,
    sell_reason: str = "",
    sell_detail: str = "",
    ohlcv_df=None,
    news_text: str = "",
    market_env: Dict[str, Any] | None = None,
    hold_days_ref: int = 10,
    highest_price: float = 0,
) -> Dict[str, Any]:
    """
    对量化卖出信号进行多 Agent 对抗审查。

    流程:
      1. BullResearcher.analyze()   ─┐
      2. BearResearcher.analyze()    ─┤ 并行辩论
      3. RiskManager.adjudicate()    ─┘ 序列裁决

    Args:
        hold_days_ref: 短线持仓参考上限（时间成本注入）
        highest_price: 持仓期间最高价（浮盈回撤保护注入）

    Returns:
        { confirm_sell, override_reason, debate_winner, bull/bear/risk 详情 }
    """
    pnl_pct = (current_price - buy_price) / buy_price * 100 if buy_price > 0 else 0
    max_profit_pct = (highest_price - buy_price) / buy_price * 100 if buy_price > 0 and highest_price > 0 else pnl_pct
    pullback_from_high = (highest_price - current_price) / highest_price * 100 if highest_price > 0 else 0.0

    context = {
        "ts_code": ts_code,
        "name": name,
        "buy_price": buy_price,
        "current_price": current_price,
        "hold_days": hold_days,
        "hold_days_ref": hold_days_ref,
        "highest_price": highest_price,
        "max_profit_pct": round(max_profit_pct, 2),
        "pullback_from_high": round(pullback_from_high, 2),
        "sell_reason": sell_reason,
        "sell_detail": sell_detail,
        "ohlcv_summary": _ohlcv_summary(ohlcv_df),
        "news_summary": news_text[:500] if news_text else "无新闻",
        "market_env": market_env or {},
        "sell_signal": (
            f"触发规则: {sell_reason}\n详情: {sell_detail}\n盈亏: {pnl_pct:+.2f}%\n"
            f"持仓参考上限: {hold_days_ref} 天 | 期间最高价: {highest_price:.2f} "
            f"(最高浮盈 {max_profit_pct:+.2f}%, 从高点回撤 {pullback_from_high:.2f}%)"
        ),
    }

    # ---- 阶段1: 并行辩论 ----
    bull = BullResearcher()
    bear = BearResearcher()

    bull_result = None
    bear_result = None

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_bull = executor.submit(bull.analyze, context)
        future_bear = executor.submit(bear.analyze, context)

        for future in as_completed([future_bull, future_bear]):
            try:
                result = future.result(timeout=60)
                if future == future_bull:
                    bull_result = result
                else:
                    bear_result = result
            except AgentOutputError as e:
                # 校验失败 → fail-fast，不做静默默认（宁失败不误判）
                raise
            except Exception as e:
                logger.warning("辩论 Agent 并行异常: %s", e)

    # 容错：仅网络/超时异常可降级，且降级结果显式标注"降级"，不伪装成 LLM 判定
    if bull_result is None:
        bull_result = AgentResult(
            agent_name="bull_researcher", agent_role="多头研究员",
            verdict="ACCEPT_SELL", confidence=0.0,
            key_findings=["辩论超时，降级为默认接受卖出（非LLM判定）"],
            reasoning="辩论超时，降级结果",
        )
    if bear_result is None:
        bear_result = AgentResult(
            agent_name="bear_researcher", agent_role="空头研究员",
            verdict="CONFIRM_SELL", confidence=0.5,
            key_findings=["辩论超时，降级为默认确认卖出（非LLM判定）"],
            reasoning="辩论超时，降级结果",
        )

    # ---- verdict 归一化: LLM 可能输出非约定值，按推理文本修正 ----
    bull_result = _normalize_bull_verdict(bull_result)
    bear_result = _normalize_bear_verdict(bear_result)

    # ---- 阶段2: 风控经理裁决 ----
    risk_mgr = RiskManager()
    risk_result = risk_mgr.adjudicate(context, bull_result, bear_result)
    risk_result = _normalize_risk_verdict(risk_result, bear_result)

    # ---- 判断是否执行卖出 ----
    final_verdict = risk_result.verdict
    confirm_sell = final_verdict == "SELL"

    # ---- 结构化字段兜底提取（8/20 实测: LLM 常把论证写进 reasoning 长文，
    #      不填 hold_reasons/bearish_signals/decisive_factors 列表 → 全空）----
    bull_reasons = bull_result.raw_output.get("hold_reasons", []) or []
    if not bull_reasons:
        bull_reasons = _extract_reasoning_items(bull_result.reasoning)
    bear_signals = bear_result.raw_output.get("bearish_signals", []) or []
    if not bear_signals:
        bear_signals = _extract_reasoning_items(bear_result.reasoning)
    decisive = risk_result.raw_output.get("decisive_factors", []) or []
    if not decisive:
        decisive = _extract_reasoning_items(risk_result.reasoning)

    # ---- debate_winner: LLM 未输出时按置信度推断（8/20 实测三只全 TIE 的根因）----
    debate_winner = risk_result.raw_output.get("debate_winner", "")
    if not debate_winner or debate_winner.upper() not in ("BULL", "BEAR", "TIE"):
        debate_winner = _infer_debate_winner(bull_result, bear_result, risk_result.reasoning)

    # 如果 Bull 很强（confidence ≥ 0.8）且 Risk Manager 判了 HOLD → 否决卖出
    override_reason = ""
    if not confirm_sell and sell_reason:
        override_reason = (
            f"量化信号={sell_reason}, "
            f"辩论胜方={debate_winner}, "
            f"LLM裁决=否决卖出, "
            f"决定因素={', '.join(decisive) if decisive else '风险经理判断'}"
        )

    return {
        "confirm_sell": confirm_sell,
        "override_reason": override_reason,
        "adjusted_confidence": round(risk_result.confidence * 100, 1),
        "debate_winner": debate_winner,
        "decisive_factors": decisive,
        "bull": {
            "verdict": bull_result.verdict,
            "confidence": bull_result.confidence,
            "hold_reasons": bull_reasons,
            "reasoning": bull_result.reasoning,
        },
        "bear": {
            "verdict": bear_result.verdict,
            "confidence": bear_result.confidence,
            "bearish_signals": bear_signals,
            "downside_risks": bear_result.raw_output.get("downside_risks", []) or [],
            "reasoning": bear_result.reasoning,
        },
        "risk_manager": {
            "verdict": risk_result.verdict,
            "confidence": risk_result.confidence,
            "reasoning": risk_result.reasoning,
            "action": risk_result.raw_output.get("action", ""),
        },
    }


# ---------------------------------------------------------------------------
# 结构化字段兜底 — LLM 常把论证写进 reasoning 长文而不填结构化列表字段，
# 从文本提取列表项 + 按置信度推断辩论胜方（8/20 实测三只全 TIE、列表全空的根因）
# ---------------------------------------------------------------------------

import re


def _extract_reasoning_items(text: str, max_items: int = 6) -> list:
    """从 reasoning 长文中提取枚举条目（1) 2) 3) / ① ② / 1. 2. / - 项目符号）。

    LLM 倾向把论证写成 "1) xxx 2) yyy" 的纯文本，而不是输出结构化列表。
    此函数将这些条目拆分为列表，供 hold_reasons/bearish_signals/decisive_factors 兜底。
    """
    if not text or not text.strip():
        return []
    text = text.strip()
    items = []

    # 模式1: "1) xxx 2) yyy 3) zzz"（最常见）
    # 编号须为独立编号（前面非数字）且 ≤ 20；
    # ")" / "、" / "）" 直接算，"." 仅当后跟空白（"1. xxx" 格式）——避免 "-6.20" 被误切
    num_pat = r"(?:^|[^\d])(?:[1-9]|1[0-9]|20)(?:\)|、|）|\.(?=\s))\s*"
    if len(re.findall(num_pat, text)) >= 2:
        parts = re.split(num_pat, text)
        parts = [p.strip() for p in parts if p.strip()]
        if len(parts) >= 2:
            items = parts

    # 模式2: "① xxx ② yyy"
    if not items:
        circled = re.split(r"[①②③④⑤⑥⑦⑧⑨⑩]", text)
        circled = [p.strip() for p in circled if p.strip()]
        if len(circled) >= 2:
            items = circled

    # 模式3: "- xxx\n- yyy" 或 "• xxx"
    if not items:
        bullets = [l.strip().lstrip("-•· ").strip()
                   for l in text.split("\n")
                   if l.strip().startswith(("-", "•", "·"))]
        bullets = [b for b in bullets if b]
        if len(bullets) >= 2:
            items = bullets

    # 模式4: 无枚举 → 按句号/分号切分长文本为要点
    if not items and len(text) > 60:
        sentences = [s.strip() for s in re.split(r"[。；;]", text) if len(s.strip()) > 8]
        if len(sentences) >= 2:
            items = sentences

    return [str(i)[:120] for i in items[:max_items]]


def _infer_debate_winner(bull_result, bear_result, risk_reasoning: str = "") -> str:
    """LLM 未输出 debate_winner 时，按双方置信度 + 风控推理文本推断胜方。

    8/20 实测: 三只持仓 debate_winner 全部默认 TIE，即使 Bear 明显更强
    （如 000070: Bear 0.85 vs Bull 0.62，风控文本也明说"空头论点更强"）。
    规则:
      1) 风控推理文本明确提到"空头/多头...更强/更有说服力" → 直接取
      2) 置信度差 ≥ 0.15 → 高置信方胜
      3) 否则 TIE
    """
    # 1) 文本线索（最高优先级——风控文本是 LLM 的真实判断）
    if risk_reasoning:
        r = risk_reasoning
        if any(k in r for k in ("空头论点更强", "空头论据更", "空头更有说服力",
                                "空头研究员论点更强", "支持卖出", "尊重止损纪律",
                                "空头明显", "空头获胜", "bear 论点更强",
                                "止损纪律应优先执行", "应执行卖出", "落袋离场",
                                "空头趋势未改", "止损纪律优先")):
            return "BEAR"
        if any(k in r for k in ("多头论点更强", "多头论据更", "多头更有说服力",
                                "支持持有", "bull 论点更强", "多头明显",
                                "不应卖出", "继续持有理由充分")):
            return "BULL"

    # 2) 置信度推断
    diff = (bear_result.confidence or 0) - (bull_result.confidence or 0)
    if diff >= 0.15:
        return "BEAR"
    if diff <= -0.15:
        return "BULL"

    # 3) verdict 辅助：Bear 确认卖出且 Bull 未强持有
    if (bear_result.verdict == "CONFIRM_SELL" and bull_result.verdict != "HOLD"):
        return "BEAR"
    if (bull_result.verdict == "HOLD" and bear_result.verdict == "FALSE_ALARM"):
        return "BULL"

    return "TIE"


# ---------------------------------------------------------------------------
# verdict 归一化 — LLM 有时不遵守约定的取值，按推理文本修正
# ---------------------------------------------------------------------------

_SELL_KEYWORDS = ("卖出", "确认", "sell", "confirm", "空头", "看跌", "趋势反转",
                  "止损", "下跌", "breakdown", "bearish")


def _normalize_bull_verdict(result: AgentResult) -> AgentResult:
    """多头研究员: 约定值 {HOLD, ACCEPT_SELL}。推理明确认输 → ACCEPT_SELL。"""
    if result.verdict in ("HOLD", "ACCEPT_SELL"):
        return result
    text = (result.reasoning or "").lower()
    if any(kw in text for kw in ("accept", "卖出", "无持有理由", "无法反驳")):
        result.verdict = "ACCEPT_SELL"
    else:
        result.verdict = "HOLD"
    return result


def _normalize_bear_verdict(result: AgentResult) -> AgentResult:
    """空头研究员: 约定值 {CONFIRM_SELL, FALSE_ALARM}。推理强烈看空但输出 HOLD → 修正。"""
    if result.verdict in ("CONFIRM_SELL", "FALSE_ALARM"):
        return result
    text = (result.reasoning or "").lower()
    # 推理文本明显看空 → 修正为 CONFIRM_SELL
    if any(kw in text for kw in ("卖出", "确认", "看跌", "空头排列", "sell", "confirm",
                                  "趋势恶化", "下跌加速", "突破均线")):
        result.verdict = "CONFIRM_SELL"
        logger.info("Bear verdict 归一化: %r → CONFIRM_SELL", result.verdict)
    else:
        result.verdict = "FALSE_ALARM"
    return result


def _normalize_risk_verdict(result: AgentResult, bear_result: AgentResult) -> AgentResult:
    """风控经理: 约定值 {SELL, HOLD}。

    防御规则: 如果 Bear 强烈看空 (CONFIRM_SELL + confidence≥0.7) 且风控裁决
    缺少 reasoning/决定因素（疑似输出异常），尊重 Bear 改为 SELL。
    """
    if result.verdict not in ("SELL", "HOLD"):
        result.verdict = "SELL" if result.verdict in ("sell", "SELL") else "HOLD"

    # 输出异常检测: 高置信但无任何推理支撑
    bear_strong = (
        bear_result.verdict == "CONFIRM_SELL"
        and bear_result.confidence >= 0.7
    )
    decisive = result.raw_output.get("decisive_factors") or result.raw_output.get("key_factors")
    risk_hollow = not (result.reasoning or "").strip() and not decisive
    if bear_strong and risk_hollow:
        logger.warning(
            "Risk Manager 裁决异常(无推理)且 Bear 强看空 → 保守改为 SELL"
        )
        result.verdict = "SELL"
        result.confidence = max(result.confidence, bear_result.confidence)
        result.reasoning = (
            "风控裁决输出异常，尊重空头研究员强看空结论(CONFIRM_SELL "
            f"{bear_result.confidence:.0%})，保守执行卖出。"
        )
    return result
