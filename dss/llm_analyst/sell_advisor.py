"""LLM 卖出顾问 — 对量化卖出信号进行 AI 二次确认。

在定量规则触发卖出信号后，调用 LLM 判断是否真的应该卖出。
LLM 可以否决量化信号（如技术性洗盘 vs 真正的破位）。
"""

import json
import logging
from typing import Dict, Any

from dss.llm_analyst.client import swing_llm, ask_json

logger = logging.getLogger(__name__)

_SELL_SYSTEM = """你是一个A股短线卖出顾问。已触发了定量卖出规则，你需要判断是否应该执行卖出。

输出JSON:
{
  "confirm_sell": true/false,
  "override_reason": "如果否决卖出，说明原因",
  "adjusted_confidence": 0.0-100.0
}"""


def review_sell_signal(
    ts_code: str,
    name: str,
    buy_price: float,
    current_price: float,
    hold_days: int,
    sell_reason: str,
    sell_detail: str,
    ohlcv_summary: str,
    news_text: str = "",
) -> Dict[str, Any]:
    """LLM 二次审查量化卖出信号。

    Returns:
        Dict with confirm_sell, override_reason, adjusted_confidence.
        On LLM failure, defaults to confirm_sell=True (defer to quantitative rule).
    """
    pnl_pct = (current_price - buy_price) / buy_price * 100

    prompt = f"""股票: {ts_code} ({name})
买入价: {buy_price:.2f}, 当前价: {current_price:.2f}
持仓天数: {hold_days}, 盈亏: {pnl_pct:+.2f}%

触发规则: {sell_reason}
详情: {sell_detail}

=== 日线摘要 ===
{ohlcv_summary[:1000]}

=== 新闻 ===
{news_text[:500] if news_text else "无新闻"}

请判断是否确认卖出。如果这是技术性洗盘或假跌破，可以否决。"""

    try:
        llm = swing_llm(temperature=0.2)
        result = ask_json(llm, _SELL_SYSTEM, prompt)

        # Ensure defaults
        result.setdefault("confirm_sell", True)
        result.setdefault("override_reason", "")
        result.setdefault("adjusted_confidence", 80.0)

        return result
    except Exception as e:
        logger.warning("LLM sell review failed for %s: %s", ts_code, e)
        return {
            "confirm_sell": True,
            "override_reason": f"LLM调用失败，默认执行卖出: {e}",
            "adjusted_confidence": 80.0,
        }
