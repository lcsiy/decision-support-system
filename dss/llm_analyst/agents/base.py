"""
Base Agent — 参考 TradingAgents 的 BaseLLMClient + Agent 角色设计。

每个 Agent：
- 拥有独立的角色描述、专业领域和分析视角
- 可访问特定工具集（数据函数）
- 输出结构化 JSON（类似 TradingAgents 的 Pydantic schema）
- 可独立运行或作为团队一部分协作
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from dss.llm_analyst.client import swing_llm

logger = logging.getLogger(__name__)


class AgentOutputError(Exception):
    """Agent LLM 输出校验失败 — fail-fast，由编排层决定是否终止运行。

    宁可运行失败，也不静默使用默认值继续（静默默认会导致
    "LLM 判了 SELL 却被当成 HOLD"这类隐性错误）。
    """


@dataclass
class AgentResult:
    """Agent 分析结果（类似 TradingAgents 的节点输出 state update）"""
    agent_name: str
    agent_role: str
    verdict: str  # e.g. BUY / HOLD / SELL / SKIP / CONFIRM / OVERRIDE
    confidence: float  # 0.0 - 1.0
    key_findings: List[str] = field(default_factory=list)
    risk_flags: List[str] = field(default_factory=list)
    catalysts: List[str] = field(default_factory=list)
    reasoning: str = ""
    raw_output: Dict[str, Any] = field(default_factory=dict)


class BaseAgent(ABC):
    """
    抽象 Agent 基类。

    用法：
        agent = TechnicalAnalyst()
        result = agent.analyze(context)
    """

    # 子类必须定义
    name: str = "base"
    role: str = "Base Agent"
    expertise: str = "General analysis"
    perspective: str = "Neutral"

    # 输出 schema（JSON 字段描述，用于 LLM system prompt）
    output_schema: Dict[str, str] = {
        "verdict": "判定结论",
        "confidence": "置信度 0.0-1.0",
        "key_findings": "关键发现列表",
        "risk_flags": "风险标记列表",
        "catalysts": "正面催化剂列表",
        "reasoning": "详细推理过程",
    }

    # 工具集（子类可覆盖）
    tools: Dict[str, Callable] = {}

    def __init__(self, temperature: float = 0.3):
        self.temperature = temperature
        self._llm = None

    @property
    def llm(self):
        if self._llm is None:
            self._llm = swing_llm(temperature=self.temperature)
        return self._llm

    # ---- 公共接口 ----

    def analyze(self, context: Dict[str, Any]) -> AgentResult:
        """
        执行分析。

        Args:
            context: 包含 ts_code, ohlcv_data, news_data, market_env 等的字典

        Returns:
            AgentResult

        Raises:
            AgentOutputError: LLM 输出校验失败（fail-fast，不静默默认）。
            上游编排层捕获后决定终止或跳过，绝不把"校验失败"伪装成正常结果。
        """
        user_prompt = self._build_prompt(context)
        system_prompt = self._build_system()

        raw = self._call_llm(system_prompt, user_prompt)
        return self._parse_result(raw)

    # ---- 子类可覆盖 ----

    @abstractmethod
    def _build_system(self) -> str:
        """构建 system prompt — 定义角色和分析要求"""
        ...

    def _build_prompt(self, context: Dict[str, Any]) -> str:
        """构建 user prompt — 注入数据和上下文"""
        # 交易时序说明（所有 Agent 共享）
        is_live = context.get("using_realtime", False)
        if is_live:
            timing = (
                "⚠️ **交易时序**: 当前使用实时行情数据（盘中）。"
                "如有买入/卖出决策，可在今日收盘前执行。"
                "止损/止盈价格为参考线，盘中触及后由风控二次确认。"
            )
        else:
            timing = (
                "⚠️ **交易时序**: 使用收盘后日线数据。"
                "实际的买入/卖出操作将在**下一个交易日开盘**执行，"
                "届时开盘价可能与当前价格不同。分析时请注意：\n"
                "  1) 判断基于趋势方向，而非精确价格点\n"
                "  2) 隔夜可能有新闻/政策/外盘变动，留出容错空间\n"
                "  3) 信号不够强（confidence < 0.6）→ 倾向于等待\n"
                "  4) 止损/止盈是参考线，次日可能跳空越过"
            )
        parts = [timing, "", f"股票: {context.get('ts_code', 'N/A')} ({context.get('name', '')})"]

        ohlcv = context.get("ohlcv_summary", "")
        if ohlcv:
            parts.append(f"\n### 日线数据\n{ohlcv}")

        news = context.get("news_summary", "")
        if news and news != "无相关新闻":
            parts.append(f"\n### 新闻\n{news}")

        factors = context.get("quantitative_factors", {})
        if factors:
            parts.append(f"\n### 量化评分\n{json.dumps(factors, ensure_ascii=False)}")

        market = context.get("market_env", {})
        if market:
            parts.append(f"\n### 市场环境\n{json.dumps(market, ensure_ascii=False)}")

        current = context.get("current_price", 0)
        buy = context.get("buy_price", 0)
        if current and buy:
            pnl = (current - buy) / buy * 100
            parts.append(f"\n### 持仓信息\n买入价: {buy:.2f}, 当前价: {current:.2f}, 盈亏: {pnl:+.2f}%, 持仓天数: {context.get('hold_days', 0)}")

        if context.get("sell_signal"):
            parts.append(f"\n### 量化卖出信号\n{context['sell_signal']}")

        return "\n".join(parts)

    # ---- 内部方法 ----

    # 每个 Agent 的必需输出字段（verdict/confidence 由基类校验，子类追加特有字段）。
    # 缺失任一必需字段 → 校验失败 → 重试 → 仍失败则抛 AgentOutputError（fail-fast，
    # 绝不静默默认，避免"LLM 判了 SELL 却被当成 HOLD"这类静默错误）。
    required_fields: tuple = ("verdict", "confidence")

    def _call_llm(self, system: str, user: str) -> Dict[str, Any]:
        """调用 LLM 并解析 JSON — 强制 JSON 输出 + 字段校验 + 失败重试。

        参考 Claude Code 的 StructuredOutput 工具原理：
        - API 层强制 JSON（response_format=json_object，模型无法输出非 JSON 文本）
        - 字段级校验（必需字段缺失 → 抛错回传模型修正，最多重试 _MAX_LLM_RETRIES 次）
        - 校验始终不通过 → 抛 AgentOutputError 中断（fail-fast），由编排层决定是否终止运行
        """
        last_error = ""
        for attempt in range(self._MAX_LLM_RETRIES + 1):
            try:
                raw, parsed, parse_err = self._invoke_json_mode(system, user)
                if parse_err is not None:
                    raise ValueError(f"JSON 解析/校验失败: {parse_err}")

                # 必需字段校验（fail-fast：拿不到必需字段就报错，不静默给默认值）
                missing = [f for f in self.required_fields
                           if raw.get(f) in (None, "", [])]
                if missing:
                    raise ValueError(
                        f"缺少必需输出字段: {missing}（LLM 实际输出键: {sorted(raw.keys())}）"
                    )
                return raw
            except Exception as e:
                last_error = str(e)
                if attempt >= self._MAX_LLM_RETRIES:
                    break
                # 把错误回传给模型修正（同 CC StructuredOutput 的重试机制）
                user = (
                    f"{user}\n\n---\n⚠️ 上次输出校验失败，请修正后重新输出纯 JSON：\n{last_error}\n"
                    f"必须包含这些字段（键名严格一致）: {list(self.required_fields)}\n"
                    f"请只输出 JSON 对象本身，不要任何其他文字。"
                )
                logger.warning("%s 第 %d 次输出校验失败，重试: %s",
                               self.name, attempt + 1, last_error)

        raise AgentOutputError(
            f"{self.name} 输出校验失败（已重试 {self._MAX_LLM_RETRIES} 次）: {last_error}"
        )

    _MAX_LLM_RETRIES = 2

    def _invoke_json_mode(self, system: str, user: str):
        """用 response_format=json_object 强制 JSON 输出，返回 (raw, parsed, err)。

        include_raw=True 时 langchain 返回 {raw, parsed, parsing_error}：
        - raw: LLM 原始响应（含 content 与 tool_calls）
        - parsed: 解析后的 dict（None 当解析失败）
        - parsing_error: 错误信息（None 当成功）
        """
        llm = self.llm.with_structured_output(
            dict, method="json_mode", include_raw=True,
        )
        result = llm.invoke([
            SystemMessage(content=system),
            HumanMessage(content=user),
        ])
        raw_msg = result.get("raw")
        parse_err = result.get("parsing_error")

        # 从原始消息提取文本并解析 JSON（json_mode 下 content 就是 JSON 字符串）
        text = ""
        if raw_msg is not None:
            if hasattr(raw_msg, "content"):
                text = raw_msg.content or ""
            elif isinstance(raw_msg, dict):
                text = raw_msg.get("content", "")
        if isinstance(text, list):  # 某些 provider 返回 content 列表
            text = "".join(str(p.get("text", "")) for p in text if isinstance(p, dict))
        text = str(text).strip()

        # 剥 markdown fences
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:])
            if text.rstrip().endswith("```"):
                text = text.rstrip()[:-3]

        parsed = None
        err = None
        if parse_err is not None:
            err = str(parse_err)
        else:
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError as e:
                err = f"JSON 解码失败: {e}; 原始文本前 300 字符: {text[:300]}"
        return parsed, parsed, err

    # 字段名兼容映射 — LLM 输出字段名会漂移（decision/verdict、final_confidence/confidence…），
    # 且每次调用漂移方向随机（英文键/中文键/标准键混用），逐一尝试取第一个非空值，
    # 避免"LLM 判了 SELL 却被解析成默认 HOLD"的静默错误。
    _VERDICT_KEYS = ("verdict", "decision", "final_decision", "signal", "judgment",
                     "final_ruling", "ruling", "结论", "判定", "最终裁决", "最终判定", "裁决", "风控决定")
    _CONFIDENCE_KEYS = ("confidence", "final_confidence", "decision_confidence", "certainty",
                        "置信度", "信心", "信心度")
    _REASONING_KEYS = ("reasoning", "advice", "rationale", "evaluation", "analysis",
                       "conclusion", "summary", "推理", "建议", "裁决依据", "市场环境考量", "理由")
    _FINDINGS_KEYS = ("key_findings", "key_factors", "factors", "findings", "关键发现", "关键因素")
    _RISK_KEYS = ("risk_flags", "risks", "风险")
    _CATALYSTS_KEYS = ("catalysts", "positive_factors", "催化剂")

    # 二级别名 — 把 LLM 漂移的字段映射回约定字段名（写入 raw_output 供下游消费）。
    # 实测漂移来源: bull→decision/defense_attempts|defense_reasons/conclusion,
    #              bear→signal/key_signals|additional_bearish_signals|primary_signal,
    #              risk→final_decision/decision_confidence/bull_vs_bear/decision_matrix/
    #                   中文键（最终裁决/行动建议/裁决依据/牛熊论点评估）
    _RAW_ALIASES = {
        "verdict": ("decision", "final_decision", "signal", "judgment", "final_ruling",
                    "ruling", "最终裁决", "最终判定", "裁决", "风控决定", "判定", "结论"),
        "confidence": ("decision_confidence", "final_confidence", "certainty",
                       "置信度", "信心", "信心度"),
        "reasoning": ("conclusion", "summary", "analysis", "rationale",
                      "裁决依据", "市场环境考量", "理由"),
        "hold_reasons": ("defense_attempts", "defense_reasons", "bull_reasons", "持有理由"),
        "quant_signal_weakness": ("trigger_analysis", "quant_signal_weakness", "信号弱点"),
        "bearish_signals": ("key_signals", "extra_bearish_signals", "additional_bearish_signals",
                            "primary_signal", "sell_signals", "看跌信号"),
        "downside_risks": ("caveats", "risk_level", "downside_risks", "下行风险"),
        "debate_winner": ("bull_vs_bear", "winner", "牛熊论点评估", "辩论胜方"),
        "decisive_factors": ("decision_matrix", "key_factors", "decisive_factors",
                             "决定因素", "裁决因素"),
        "action": ("action_advice", "advice", "行动建议", "操作建议"),
        "trend_quality": ("trend", "trend_grade", "趋势质量"),
        "sentiment": ("sentiment_label", "mood", "情绪"),
        "consensus": ("agreement", "一致程度"),
    }

    @staticmethod
    def _first_nonempty(raw: Dict[str, Any], keys) -> Any:
        for k in keys:
            v = raw.get(k)
            if v is not None and v != "" and v != []:
                return v
        return None

    @staticmethod
    def _simplify_list_items(items) -> list:
        """LLM 列表项可能是 dict（如 defense_attempts=[{defense, counter}]、
        key_signals=[{type, detail}]）— 提取文本字段拼成字符串列表供下游展示。"""
        if not isinstance(items, list):
            return items
        out = []
        for it in items:
            if isinstance(it, dict):
                # 按优先级提取 dict 中的文本字段
                picked = None
                for k in ("defense", "type", "detail", "text", "desc", "title", "signal", "reason"):
                    if it.get(k) is not None and str(it[k]).strip():
                        picked = f"{it[k]}"
                        if k in ("defense", "type", "title", "signal") and it.get("counter"):
                            picked += f" — 反驳: {it['counter']}"
                        elif k in ("type",) and it.get("detail"):
                            picked += f": {it['detail']}"
                        break
                if picked is None:
                    picked = json.dumps(it, ensure_ascii=False)
                out.append(picked)
            else:
                out.append(str(it))
        return out

    def _normalize_raw(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """把 LLM 漂移字段拷贝回约定字段名，供下游 raw_output.get() 消费。"""
        if not isinstance(raw, dict):
            return raw
        normalized = dict(raw)
        for canonical, aliases in self._RAW_ALIASES.items():
            if normalized.get(canonical) in (None, "", []):
                for alias in aliases:
                    v = normalized.get(alias)
                    if v is not None and v != "" and v != []:
                        normalized[canonical] = v
                        break
        # 嵌套 dict 列表 → 文本列表（hold_reasons/bearish_signals 等）
        for k in ("hold_reasons", "bearish_signals", "downside_risks",
                  "decisive_factors", "key_findings", "risk_flags"):
            v = normalized.get(k)
            if isinstance(v, list):
                normalized[k] = self._simplify_list_items(v)
        return normalized

    def _parse_result(self, raw: Dict[str, Any]) -> AgentResult:
        """从 LLM 输出构建 AgentResult（兼容字段名漂移）"""
        if not isinstance(raw, dict):
            raw = {}

        # 先做二级别名规范化（decision→verdict、conclusion→reasoning 等），
        # 使 verdict/confidence/reasoning 与 raw_output 消费字段都命中。
        raw = self._normalize_raw(raw)

        verdict = self._first_nonempty(raw, self._VERDICT_KEYS) or "HOLD"
        if not isinstance(verdict, str):
            verdict = str(verdict)

        conf_raw = self._first_nonempty(raw, self._CONFIDENCE_KEYS)
        try:
            confidence = float(conf_raw) if conf_raw is not None else 0.5
        except (ValueError, TypeError):
            confidence = 0.5
        confidence = min(1.0, max(0.0, confidence))

        reasoning = self._first_nonempty(raw, self._REASONING_KEYS)
        if isinstance(reasoning, dict):
            reasoning = json.dumps(reasoning, ensure_ascii=False)
        reasoning = str(reasoning or "")
        # reasoning 缺失时用决定因素兜底（LLM 常只输出 decisive/key_factors）
        if not reasoning.strip():
            decisive = self._first_nonempty(raw, ("decisive_factors", "key_factors", "决定因素"))
            if decisive:
                if isinstance(decisive, dict):
                    decisive = json.dumps(decisive, ensure_ascii=False)
                reasoning = str(decisive)

        findings = self._first_nonempty(raw, self._FINDINGS_KEYS) or []
        if isinstance(findings, str):
            findings = [findings]
        risk_flags = self._first_nonempty(raw, self._RISK_KEYS) or []
        catalysts = self._first_nonempty(raw, self._CATALYSTS_KEYS) or []

        return AgentResult(
            agent_name=self.name,
            agent_role=self.role,
            verdict=verdict,
            confidence=confidence,
            key_findings=list(findings),
            risk_flags=list(risk_flags) if isinstance(risk_flags, list) else [str(risk_flags)],
            catalysts=list(catalysts) if isinstance(catalysts, list) else [str(catalysts)],
            reasoning=reasoning,
            raw_output=raw,
        )


def _ohlcv_summary(df, max_rows: int = 8) -> str:
    """将 OHLCV DataFrame 压缩为 LLM 可读摘要"""
    if df is None or df.empty:
        return "无日线数据"

    last = df.iloc[-1]
    recent = df.tail(max_rows)

    lines = [
        f"最新价: {last.get('close', 'N/A')} | "
        f"开盘: {last.get('open', 'N/A')} | "
        f"高: {last.get('high', 'N/A')} | "
        f"低: {last.get('low', 'N/A')}",
    ]

    if "pct_chg" in df.columns:
        lines.append(f"今日涨跌幅: {last.get('pct_chg', 'N/A')}%")

    # MA 列
    ma_cols = sorted([c for c in df.columns if c.startswith("ma")], key=lambda x: int(x[2:]) if x[2:].isdigit() else 99)
    if ma_cols:
        ma_parts = []
        clause = ""
        for i, c in enumerate(ma_cols):
            period = c[2:]
            v = last.get(c)
            if v is not None:
                try:
                    vf = float(v)
                    ma_parts.append(f"MA{period}={vf:.2f}")
                    if i > 0:
                        prev_col = ma_cols[i-1]
                        prev_v = float(last.get(prev_col, 0))
                        if prev_v > 0:
                            if vf > prev_v:
                                clause += f" MA{period}>MA{int(period)//2 if i==1 else ma_cols[i-1][2:]}"
                except (ValueError, TypeError):
                    ma_parts.append(f"MA{period}={v}")
        if ma_parts:
            lines.append(f"均线: {', '.join(ma_parts)}")
            if clause:
                lines.append(f"排列: {clause.strip()}")

    # Price vs MAs
    close = float(last.get("close", 0))
    if close > 0:
        vs_ma = []
        for c in ma_cols:
            v = last.get(c)
            if v:
                try:
                    pct = (close - float(v)) / float(v) * 100
                    vs_ma.append(f"vs{c[2:]}:{pct:+.1f}%")
                except (ValueError, TypeError):
                    pass
        if vs_ma:
            lines.append(f"价格位置: {', '.join(vs_ma)}")

    lines.append(f"\n近{len(recent)}日行情:")
    for _, r in recent.iterrows():
        d = str(r.get('trade_date', ''))
        c = r.get('close', 'N/A')
        chg = r.get('pct_chg', '')
        chg_str = f" ({chg}%)" if chg != '' and str(chg) != 'nan' else ""
        lines.append(f"  {d}: {c}{chg_str}")

    return "\n".join(lines)


def _news_summary(text: str, max_chars: int = 500) -> str:
    """截断新闻文本"""
    if not text or text.startswith("No tushare news"):
        return "无相关新闻"
    return text[:max_chars]
