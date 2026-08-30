---
name: decision-support-system
description: >-
  A-share (A股) real-market trading decision support system v11.1 with LLM-enhanced
  swing trading, tail-session analysis, minute-level data collection, and feedback
  optimization. Self-contained Tushare data layer (no TradingAgents dependency);
  multi-agent debate design inspired by TradingAgents; forced structured LLM output
  with fail-fast validation (per Claude Code StructuredOutput principle).
  Use this whenever the user mentions A-share stocks, 尾盘分析, 决策系统, tail analysis,
  minute data collection, Tushare data, trading decision support, feedback loop
  optimization, stock screening, swing trading, short-term trading, or wants to run
  the DSS/dss project.
compatibility: python>=3.10, tushare, pandas, numpy, python-dotenv, langchain-openai
---

# 决策支持系统 v11.1

## 系统概述

决策支持系统是一个A股实盘交易辅助工具，v11 起**完全自包含**（数据层不再依赖 TradingAgents 项目，仅保留其多 Agent 协作设计思想参考）；v11.1 起 **LLM 输出强制结构化 + fail-fast**（参考 Claude Code 的 StructuredOutput 工具原理：`response_format=json_object` 强制 JSON + 必需字段校验 + 失败重试 + 抛错终止，宁失败不误判）。核心功能：

1. **短线交易 (LLM增强)**: 持仓≤10天（参考值），每日追踪池审查 + AI选股 + LLM卖出确认
2. **超短线尾盘分析**: 每日尾盘14:30筛选适合次日高开的股票
3. **分钟级数据采集**: 每分钟采集热榜股票实时价格
4. **反馈优化闭环**: 验证推荐表现、自动优化维度权重

## 快速开始

### 环境准备

```bash
# 全部依赖（无外部项目依赖）
pip install tushare pandas numpy python-dotenv langchain-openai langchain-core
```

### 配置

复制 `.env.example` 为 `.env`，填入：

```bash
# Tushare 数据（本 skill 自己的 token）
TUSHARE_TOKEN=your_token_here

# LLM 配置（DSS_* 优先；TRADINGAGENTS_* 兼容读取）
DSS_LLM_PROVIDER=deepseek
DSS_QUICK_THINK_LLM=deepseek-v4-flash
DSS_DEEP_THINK_LLM=deepseek-v4-flash
DEEPSEEK_API_KEY=sk-xxx
DSS_LLM_BACKEND_URL=https://api.deepseek.com
DSS_OUTPUT_LANGUAGE=Chinese

# 短线参数
SWING_POOL_SIZE=3
SWING_MAX_HOLD_DAYS=10             # 参考上限（非强制）
SWING_STOP_LOSS_PCT=0.95           # 止损参考线（非强制触发）
SWING_TAKE_PROFIT_PCT=1.10         # 止盈参考线（非强制触发）
```

### 运行

```bash
# 短线交易（每日运行）🆕 v10 核心功能
python -m dss.swing_cli run
python -m dss.swing_cli run --dry-run     # 试运行
python -m dss.swing_cli pool              # 查看追踪池
python -m dss.swing_cli history           # 交易历史

# 尾盘分析（返回前5只推荐）
python -m dss.interface_layer.tail_analysis --top 5

# 分钟数据采集（下午交易时段）
python -m dss.interface_layer.minute_collector --session afternoon

# 反馈闭环
python -m dss.optimization_engine.run_feedback_loop --mode verify-optimize
```

## 系统架构（5+1层）

```
dss/                             # Python 包
├── config.py                    # 全局配置（.env → Config）
├── swing_cli.py                 # 短线交易 CLI 入口
│
├── data_layer/                  # 数据层 — 自包含 tushare 实现（独立 token）
│   ├── tushare_vendor.py       # 🆕 v11 厂商函数层 — 全部 tushare SDK 调用
│   ├── tushare_client.py       # TushareClient — v11 委托本地 vendor
│   ├── hot_stock_provider.py   # 热榜获取 + ST/市场过滤
│   ├── minute_data_repo.py     # 分钟CSV数据读写
│   └── stock_filter.py         # 股票过滤器
│
├── analysis_engine/              # 分析引擎层
│   ├── technical_momentum.py   # 尾盘技术动量分析 (60%)
│   ├── sentiment.py            # 尾盘情绪面分析 (40%)
│   ├── opening_prediction.py   # 次日开盘预测
│   ├── overnight_risk.py       # 过夜风险评估
│   ├── swing_types.py          # 短线共享数据类型
│   ├── swing_trend.py          # 短线趋势分析 (MA排列/斜率/一致性)
│   ├── swing_momentum.py       # 短线动量分析 (多周期收益/相对强度)
│   ├── swing_volume.py         # 短线量能分析 (量比/量价配合)
│   ├── swing_risk.py           # 短线风险分析 (ATR/回撤/Beta)
│   └── swing_composite.py      # 短线综合评分 (5维度加权)
│
├── llm_analyst/                  # LLM 分析增强层 (v11.1 — 强制结构化输出 + fail-fast)
│   ├── client.py               # LLM 客户端（DSS_* 独立配置，兼容旧变量名）
│   ├── swing_analyst.py        # 批量并行 LLM 尽调 + 量化/LLM 融合
│   └── sell_advisor.py         # LLM 卖出信号二次审查（可否决）
│
├── decision_core/                # 决策核心层
│   ├── trading_plan.py         # 尾盘交易计划生成
│   ├── stock_screener.py       # 尾盘预筛选流水线
│   ├── swing_screener.py       # 短线预筛选 (全市场→ST→价格→流动性)
│   ├── swing_pool.py           # 短线追踪池状态管理 + 卖出信号
│   └── swing_plan.py           # 短线买入计划 (止损/止盈/仓位)
│
├── optimization_engine/          # 优化引擎层
│   ├── feedback_recorder.py    # 尾盘反馈记录
│   ├── feedback_verifier.py    # 尾盘反馈验证
│   ├── feedback_optimizer.py   # 尾盘权重优化
│   ├── run_feedback_loop.py    # 尾盘闭环入口
│   └── swing_recorder.py       # 🆕 短线记录 (含LLM详情+交易汇总)
│
└── interface_layer/              # 接口层（薄编排器）
    ├── tail_analysis.py        # TailAnalysisOrchestrator（尾盘）
    ├── minute_collector.py     # 分钟数据采集器
    ├── report_formatter.py     # 尾盘报告格式化
    ├── swing_orchestrator.py   # 🆕 SwingOrchestrator v10（LLM增强）
    └── swing_report.py         # 短线报告格式化
```

## 核心功能

### 1. 🆕 短线交易 (LLM增强) — v10 核心

**策略**: 持仓 ≤10 个交易日，每日评估追踪池，top3 等额选股

```bash
# 每日运行（审查池+选股补仓）
python -m dss.swing_cli run

# 试运行（不修改池状态）
python -m dss.swing_cli run --dry-run

# 查看追踪池
python -m dss.swing_cli pool

# 查看交易历史
python -m dss.swing_cli history

# 手动标记卖出
python -m dss.swing_cli sell 000001.SZ --price 12.80

# 手动标记买入
python -m dss.swing_cli buy 000002.SZ --price 18.50
```

**v10 执行流程**:

```
1. 市场环境评估      → 上证指数 MA20 位置 + 情绪判断
2. 追踪池审查        → 量化卖出信号 (5条规则)
                      → 🆕 LLM 二次确认 (可否决假跌破/技术洗盘)
3. 选股补仓          → 全市场预筛选 (ST/价格/流动性)
                      → 4维量化评分 (趋势/动量/量能/风险)
                      → 🆕 Top10 LLM 并行尽调 (技术+新闻+情绪)
                      → 🆕 融合评分排序 → Top3
4. 记录 + 报告       → 含 LLM 分析详情 + 买入价 + 评分明细
```

**四维度 + 市场评分模型**:
- **趋势 (30%)**: MA排列、价格vsMA20/MA60、趋势斜率、一致性
- **动量 (25%)**: 多周期收益、加速度、相对强度
- **量能 (20%)**: 量比、量价配合、资金流
- **风险 (15%)**: ATR、最大回撤、Beta、跳空风险
- **市场 (10%)**: 大盘情绪、指数位置

**卖出逻辑** (v11.1 — 每次运行都是全新 LLM 决策，强制结构化输出):

> 不再使用固定规则自动触发卖出。止损/止盈/持仓时长均为**参考值**，
> 最终决策由多 Agent 辩论产生。

流程:
1. **风险评估**: 计算浮亏/浮盈/均线状态/大盘风险 → 生成结构化风险上下文
2. **时间成本注入** (v11.1): 持仓超参考上限、曾浮盈现转亏、从高点回撤超浮盈1/3
   → 强卖出信号入辩论上下文（浮盈兑现优先，盈利转亏损是短线最大禁忌）
3. **多Agent辩论**: Bull Researcher（寻找持有理由）∥ Bear Researcher（寻找卖出理由）
4. **风控裁决**: Risk Manager 综合辩论结果 + 市场环境 → 最终 SELL/HOLD 决策
5. **强制结构化输出** (v11.1): 每个 Agent 声明 `required_fields`，LLM 输出经
   `response_format=json_object` 强制 JSON → 必需字段缺失即校验失败 → 错误回传模型
   重试（最多 2 次）→ 仍失败抛 `AgentOutputError` 终止本轮
6. **verdict 归一化兜底**: 兼容层按推理文本修正三方判定（中英文键别名映射 + 嵌套
   dict 提取，防历史漂移字段）
7. **数据记录**: 完整记录三方观点 + 裁决理由 + 辩论胜方

参考值（非强制触发）:
- 止损参考线: -5%（浮亏到此线会提升风险级别，但不强制卖出）
- 止盈参考线: +10%（浮盈到此线会提示，但不强制卖出）
- 持仓参考上限: 10 天（到达后会提示重新评估，但不强制卖出）

**fail-fast 设计** (v11.1): LLM 输出校验失败 → 抛错终止本轮运行（CLI 非零退出），
**绝不静默默认**（静默 HOLD 曾导致"LLM 判 SELL 却被当成继续持有"的隐性亏损）。
仅网络超时可降级，且结果显式标注"非 LLM 判定"。

### 2. 超短线尾盘分析

**使用时间**: 每个交易日 14:30-15:00
**策略**: 尾盘买入 → 次日 9:30-10:00 卖出

```bash
# 分析前5只股票
python -m dss.interface_layer.tail_analysis --top 5

# 指定热榜数量和流动性
python -m dss.interface_layer.tail_analysis --hot-limit 300 --min-liquidity 10000000
```

**两维度分析模型** (v8.8):
- **技术动量 (60%)**: 当日涨跌幅、价格位置、尾盘趋势、成交量因子、尾盘量价推断
- **情绪面 (40%)**: 热榜排名、涨跌幅情绪

### 3. 分钟数据采集

```bash
python -m dss.interface_layer.minute_collector --session morning
python -m dss.interface_layer.minute_collector --session afternoon
```

### 4. 反馈优化闭环

```bash
# 完整分析+记录
python -m dss.optimization_engine.run_feedback_loop --mode analyze

# 验证+优化
python -m dss.optimization_engine.run_feedback_loop --mode verify-optimize

# 历史统计
python -m dss.optimization_engine.run_feedback_loop --mode stats
```

## 数据记录

### 每日快照 (`data/swing/daily/YYYYMMDD_swing.json`)

```json
{
  "date": "20260717",
  "market_env": { "sentiment": "bearish", "market_score": 45.0 },
  "pool_review": {
    "sell_decisions": [
      { "ts_code": "000001.SZ", "reason": "STOP_LOSS",
        "llm_review": { "confirm_sell": true, "override_reason": "" } }
    ]
  },
  "new_picks": [
    { "ts_code": "600519.SH", "entry_price": 1700.00,
      "llm_verdict": "BUY", "llm_confidence": 0.85,
      "composite_score": 78.5 }
  ],
  "llm_sell_reviews": [...],
  "llm_buy_analyses": [...]
}
```

### 交易汇总

```python
from dss.optimization_engine.swing_recorder import SwingRecorder
from dss.config import Config

recorder = SwingRecorder(Config())
summary = recorder.generate_trade_summary("data/swing/swing_pool.json")
# => { total_trades, win_rate, avg_pnl_pct, avg_hold_days, sell_reasons, ... }
```

## 数据源

| 接口 | 用途 | 积分要求 |
|------|------|----------|
| `daily` | 日线行情 | 120 |
| `ths_hot` | 同花顺热榜 | ≤3000 |
| `stock_st` | ST 列表 | ≤2000 |
| `limit_list_d` | 涨跌停列表 | ≤2000 |
| `moneyflow` | 资金流向 | ≤2000 |
| `index_daily` | 指数行情 | 免费 |
| `stock_basic` | 股票基础信息 | 免费 |
| `trade_cal` | 交易日历 | 免费 |
| `major_news` | 新闻通讯 (LLM) | ≤2000 |
| `realtime_list` | 实时行情 | 免费 |

所有接口通过本 skill 的 `data_layer/tushare_vendor.py` 自包含实现统一访问（token 取自本项目 `.env`）。`major_news` 带全局缓存（30 次/小时限流防护，每轮运行约 9 次调用）。

## 配置参数

```bash
# 短线交易
SWING_POOL_SIZE=3             # 追踪池容量
SWING_MAX_HOLD_DAYS=10        # 持仓参考上限 (非强制)
SWING_STOP_LOSS_PCT=0.95      # 止损参考线 (非强制触发)
SWING_TAKE_PROFIT_PCT=1.10    # 止盈参考线 (非强制触发)
SWING_MIN_PRICE=5.0           # 最低股价
SWING_MAX_PRICE=500.0         # 最高股价
SWING_MIN_DAILY_AMOUNT=50000000  # 最低日成交额

# 因子权重（合计应 ≈1.0）
SWING_W_TREND=0.30
SWING_W_MOMENTUM=0.25
SWING_W_VOLUME=0.20
SWING_W_RISK=0.15
SWING_W_MARKET=0.10

# 并行处理
MAX_WORKERS=20
```

## 定时任务

```bash
# 短线交易 — 每日 14:30
30 14 * * 1-5 cd /path/to/project && python -m dss.swing_cli run

# 尾盘分析 — 14:15
15 14 * * 1-5 cd /path/to/project && python -m dss.interface_layer.tail_analysis --cron --top 5

# 反馈验证 — 次日 11:00
0 11 * * 1-5 cd /path/to/project && python -m dss.optimization_engine.run_feedback_loop --mode verify-optimize
```

## 注意事项

1. **交易时间**: 系统只在A股交易时间有效（9:30-11:30, 13:00-15:00）
2. **T+1 机制**: 当日买入次日才能卖出，需严格止损
3. **API 限制**: Tushare 接口有频率限制，批量请求已内置间隔和缓存
4. **LLM fail-fast** (v11.1): LLM 输出校验失败 → 抛错终止运行（CLI 非零退出），
   宁失败不误判；仅网络超时可降级且显式标注"非 LLM 判定"
5. **数据记录**: 所有 LLM 决策详情均持久化，供后续绩效分析
6. **投资风险**: 仅供学习研究，不构成投资建议

---

## 与 TradingAgents 的关系

| 能力 | TradingAgents | DSS v11 |
|------|--------------|---------|
| 数据访问 | tushare 厂商层 | 自包含 tushare_vendor（独立 token） |
| LLM 客户端 | 多厂商抽象 | 轻量封装（DSS_* 独立配置） |
| 多 Agent 设计 | 分析师/研究员/交易员/风控团队 | 参考其设计（买入 3 Agent、卖出 3 Agent 辩论） |
| 选股 | 单股指定 | 全市场批量 |
| 追踪池 | 无 | 核心功能 |
| 反馈优化 | 决策日志 | 结构化绩效分析 |

v11 起 DSS 在运行期**零依赖** TradingAgents 项目；仅保留其多 Agent 协作（并行分析 → 对抗辩论 → 序列裁决）的**设计思想**参考。

---

**版本**: v11.1 | **最后更新**: 2026-08-20

### v11.1 变更 — LLM 交互层重构（强制结构化输出 + fail-fast）
- **根因修复**: LLM 输出字段名随机漂移（`decision`/`signal`/`最终裁决`/`verdict` 混用）
  → 解析读空静默默认 HOLD，导致"LLM 判 SELL 却被当成继续持有"（历史盈利变亏损深层主因）
- **机制改造**（参考 Claude Code StructuredOutput 原理）:
  - `response_format=json_object` 强制 JSON 输出（API 层约束）
  - 每个 Agent 声明 `required_fields`（如 bear 必须输出 verdict/confidence/reasoning）
  - 必需字段缺失 → 校验失败 → 错误回传模型重试（最多 2 次）
  - 仍失败抛 `AgentOutputError` → 编排层中止（fail-fast，宁可运行失败不静默有误）
- **兼容层保留**: 中英文键别名映射（30+ 变体）、嵌套 dict 列表文本提取、verdict 归一化兜底
- **编排层同步**: 卖出/买入侧 `AgentOutputError` 直接上抛；网络超时降级显式标注
  "非LLM判定"；选股任一候选校验失败 → RuntimeError 中止本轮
- **盘中实时数据**: `_assess_market` 实时指数优先 + 日线回退 + `[实时/日线]` 标注；
  持仓审查盘中用实时价；修复 `index_daily` 降序取到 1993 年数据的隐藏 bug
- **短线策略**: Risk Manager 注入持仓时间成本/浮盈回撤/"盈利转亏损是最大禁忌"规则；
  ATR 评分改倒钟形（2.5-5% 最优，死水股票降分）解决"全选低波动股票"
- **实测**: 6 个 Agent 11/11 调用通过；000070 卖出审查修复前 0/5 判 SELL → 修复后 4-5/5

### v11.0 变更
- **数据层解耦**: 移除对 TradingAgents 的运行期依赖，新增自包含 `tushare_vendor.py`
- LLM 配置改 `DSS_*` 前缀（`TRADINGAGENTS_*` 兼容读取）
- 接口签名零变化，调用方无感知

### v10.3 变更（未发布为独立版本，随 v11 说明）
- **verdict 归一化**: LLM 未遵守约定取值时，按推理文本修正 Bull/Bear/Risk 判定
- Bear 推理强烈看空但输出 HOLD → 修正为 CONFIRM_SELL
- Risk Manager 输出异常（无推理）且 Bear 强看空 → 保守改为 SELL

### v10.2 变更
- **卖出逻辑重构**: 固定规则 → 每次运行全新 LLM 多 Agent 分析
- 止损/止盈/持仓时长从"强制触发"改为"参考值"
- 每只池中股票均经过 Bull vs Bear 辩论 + Risk Manager 裁决
- SwingSellSignal 从"卖出信号判定器"改为"风险评估器"

### v10.1 变更
- 多 Agent 协作架构 (TechnicalAnalyst + NewsSentimentAnalyst + SwingTrader)
- 卖出侧对抗辩论 (BullResearcher + BearResearcher + RiskManager)

### v10.0 变更
- LLM 分析增强（当时集成 TradingAgents 数据层，v11 已解耦）
