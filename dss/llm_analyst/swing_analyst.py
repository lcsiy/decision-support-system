"""短线 LLM 分析师 — 对量化评分 top10 进行 LLM 二次尽调。

核心流程:
    quantitative_top10 → LLMAnalyst.analyze_batch(top10) → LLM增强评分 → top3
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, List, Optional

from dss.llm_analyst.client import swing_llm, ask_json

logger = logging.getLogger(__name__)

# 每个候选股的 LLM 分析限额（上下文大小）
MAX_NEWS_CHARS = 800
MAX_OHLCV_ROWS = 10

_SYSTEM_PROMPT = """你是一个A股短线交易分析师。你的任务是对给定的候选股票进行二次尽调，
输出JSON格式的判断。你只需要输出JSON，不要输出其他内容。

JSON格式:
{
  "verdict": "BUY" | "HOLD" | "SKIP",
  "confidence": 0.0-1.0,
  "risk_flags": ["风险1", "风险2"],
  "catalysts": ["催化剂1"],
  "reasoning": "分析理由(一句话)"
}

判定规则:
- BUY: 技术面强势 + 新闻/情绪正面 + 无明显风险 → confidence ≥ 0.7
- HOLD: 信号矛盾，需要更多观察
- SKIP: 明显风险(跌停/利空新闻/量价背离)或参数不足
"""


def _summarize_ohlcv(df, ts_code: str) -> str:
    """将 OHLCV DataFrame 压缩为 LLM 可读的摘要。"""
    if df is None or df.empty:
        return f"{ts_code}: 无日线数据"

    last = df.iloc[-1]
    recent = df.tail(MAX_OHLCV_ROWS)

    lines = [
        f"股票: {ts_code}",
        f"最新价: {last.get('close', 'N/A')}, "
        f"开盘: {last.get('open', 'N/A')}, 最高: {last.get('high', 'N/A')}, 最低: {last.get('low', 'N/A')}",
    ]

    if "pct_chg" in df.columns:
        lines.append(f"今日涨跌幅: {last.get('pct_chg', 'N/A')}%")

    # MA columns
    ma_cols = [c for c in df.columns if c.startswith("ma")]
    if ma_cols:
        parts = []
        for c in ma_cols:
            v = last.get(c)
            if v is not None and not (hasattr(v, '__int__') and v != v):
                parts.append(f"{c}={float(v):.2f}")
        if parts:
            lines.append(f"均线: {', '.join(parts)}")

    lines.append(f"\n近{len(recent)}日收盘:")
    for _, r in recent.iterrows():
        d = str(r.get('trade_date', ''))
        c = r.get('close', 'N/A')
        chg = r.get('pct_chg', '')
        chg_str = f" ({chg}%)" if chg != '' else ""
        lines.append(f"  {d}: {c}{chg_str}")

    return "\n".join(lines)


def _summarize_news(news_text: str) -> str:
    """截断新闻文本。"""
    if not news_text or news_text.startswith("No tushare news"):
        return "无相关新闻"
    return news_text[:MAX_NEWS_CHARS]


def analyze_single(
    ts_code: str,
    ohlcv_df,
    news_text: str,
    quantitative_score: float,
    quantitative_factors: Dict[str, float],
) -> Dict[str, Any]:
    """对单只股票进行 LLM 分析。"""
    ohlcv_block = _summarize_ohlcv(ohlcv_df, ts_code)
    news_block = _summarize_news(news_text)

    user_prompt = f"""量化评分: {quantitative_score:.1f}/100
因子: {json.dumps(quantitative_factors, ensure_ascii=False)}

=== 日线数据 ===
{ohlcv_block}

=== 新闻 ===
{news_block}

请根据以上数据输出JSON判定。"""

    try:
        llm = swing_llm()
        result = ask_json(llm, _SYSTEM_PROMPT, user_prompt)

        # 将量化评分并入
        result["ts_code"] = ts_code
        result["quantitative_score"] = quantitative_score
        result["combined_score"] = _combined_score(quantitative_score, result)

        return result
    except Exception as e:
        logger.warning("LLM analysis failed for %s: %s", ts_code, e)
        return {
            "ts_code": ts_code,
            "verdict": "HOLD",
            "confidence": 0.0,
            "risk_flags": ["LLM分析失败"],
            "catalysts": [],
            "reasoning": f"分析异常: {e}",
            "quantitative_score": quantitative_score,
            "combined_score": quantitative_score,
        }


def analyze_batch(candidates: List[Dict[str, Any]], max_workers: int = 4) -> List[Dict[str, Any]]:
    """并行分析一批候选股（top10 → LLM二次尽调）。"""
    results = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for c in candidates:
            future = executor.submit(
                analyze_single,
                c["ts_code"],
                c.get("ohlcv_df"),
                c.get("news_text", ""),
                c.get("composite_score", 50),
                c.get("factors", {}),
            )
            futures[future] = c

        for future in as_completed(futures):
            try:
                result = future.result(timeout=60)
                results.append(result)
            except Exception as e:
                c = futures[future]
                results.append({
                    "ts_code": c["ts_code"],
                    "verdict": "SKIP",
                    "confidence": 0.0,
                    "reasoning": f"超时或异常: {e}",
                    "combined_score": c.get("composite_score", 50),
                })

    # Sort by combined score
    results.sort(key=lambda x: x.get("combined_score", 0), reverse=True)
    return results


def _combined_score(quant: float, llm_result: dict) -> float:
    """融合量化评分和 LLM 判定。

    - BUY: 量化分 * 1.1 + confidence * 10
    - HOLD: 量化分 * 1.0
    - SKIP: 量化分 * 0.5
    """
    verdict = llm_result.get("verdict", "HOLD")
    confidence = float(llm_result.get("confidence", 0.5))

    if verdict == "BUY":
        multiplier = 1.1 + confidence * 0.1
    elif verdict == "SKIP":
        multiplier = 0.5
    else:
        multiplier = 1.0

    return round(min(100, quant * multiplier + confidence * 5), 1)
