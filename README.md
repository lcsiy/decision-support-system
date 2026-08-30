# 决策支持系统 v11.1

## 项目概述

A股实盘交易辅助系统，提供超短线尾盘分析、短线交易追踪池、分钟级数据采集和反馈优化闭环。

v11.1 重构：LLM 交互层按 Claude Code 的 StructuredOutput 原理改造——**强制 JSON 输出 + 必需字段校验 + 失败重试 + fail-fast**，从机制上消除 LLM 输出字段漂移导致的静默误判。
v11.0 解耦：数据层与 LLM 配置不再依赖 [TradingAgents](https://github.com/TauricResearch/TradingAgents) 项目（仅保留其多 Agent 协作的**设计思想**参考），全部由本 skill 自包含实现。

## 系统架构（5+1层）

```
dss/                                # Python 包
│
├── config.py                       # 全局配置 — 所有模块唯一配置源
├── swing_cli.py                    # 短线交易 CLI 入口
│
├── data_layer/                     # 数据层 — 自包含 tushare 实现（独立 token）
│   ├── tushare_vendor.py           # 🆕 Tushare 厂商函数层 — 全部 tushare SDK 调用
│   ├── tushare_client.py          # TushareClient — v11 委托本地 vendor
│   ├── hot_stock_provider.py       # HotStockProvider — 热榜获取+回溯+过滤
│   ├── minute_data_repo.py         # MinuteDataRepository — 分钟CSV读写
│   └── stock_filter.py            # StockFilter — 前缀/ST/市场过滤
│
├── analysis_engine/                 # 分析引擎层
│   ├── technical_momentum.py       # 尾盘: 技术动量 (60%)
│   ├── sentiment.py                # 尾盘: 情绪面 (40%)
│   ├── opening_prediction.py       # 尾盘: 次日开盘预测
│   ├── overnight_risk.py           # 尾盘: 过夜风险评估
│   ├── swing_types.py              # 短线: 共享数据类型
│   ├── swing_trend.py              # 短线: 趋势分析 (MA排列/斜率/一致性)
│   ├── swing_momentum.py           # 短线: 动量分析 (多周期收益/相对强度)
│   ├── swing_volume.py             # 短线: 量能分析 (量比/量价配合)
│   ├── swing_risk.py               # 短线: 风险分析 (ATR/回撤/Beta)
│   └── swing_composite.py          # 短线: 5维度综合评分
│
├── llm_analyst/                     # LLM 分析增强层 (v11.1 — 强制结构化输出 + fail-fast)
│   ├── client.py                   # LLM 客户端（DSS_* 独立配置，兼容旧变量名）
│   ├── swing_analyst.py            # 批量并行 LLM 尽调 + 量化/LLM 融合
│   └── sell_advisor.py             # LLM 卖出信号二次审查
│
├── decision_core/                   # 决策核心层
│   ├── trading_plan.py             # 尾盘: 交易计划生成
│   ├── stock_screener.py           # 尾盘: 预筛选流水线
│   ├── swing_screener.py           # 短线: 全市场预筛选
│   ├── swing_pool.py               # 短线: 追踪池状态管理 + 卖出信号
│   └── swing_plan.py               # 短线: 买入计划
│
├── optimization_engine/             # 优化引擎层
│   ├── feedback_recorder.py        # 尾盘: 推荐记录 + 验证
│   ├── feedback_verifier.py        # 尾盘: 盈亏验证
│   ├── feedback_optimizer.py       # 尾盘: 权重优化
│   ├── run_feedback_loop.py        # 尾盘: 闭环运行器 CLI
│   └── swing_recorder.py           # 短线: 每日分析快照 + 交易汇总
│
└── interface_layer/                 # 接口层
    ├── tail_analysis.py            # TailAnalysisOrchestrator — 尾盘
    ├── minute_collector.py         # MinuteCollector — 分钟采集
    ├── report_formatter.py         # ReportFormatter — 尾盘报告
    ├── swing_orchestrator.py       # SwingOrchestrator v10 — 短线主编排器
    └── swing_report.py             # SwingReportFormatter — 短线报告
```

### 设计原则

1. **依赖注入**: 所有组件通过构造函数接收依赖，无全局状态
2. **单一入口**: `TushareClient` → `tushare_vendor` 自包含实现，零外部项目依赖
3. **纯分析函数**: `analysis_engine` 模块只做计算，不做 I/O
4. **Config 唯一源**: `dss.config.Config` 从 `.env` 加载
5. **LLM fail-fast** (v11.1): LLM 输出校验失败 → 抛错终止，绝不静默默认
   （仅网络超时可降级，且显式标注"非 LLM 判定"）

### 数据流 (v11)

```
[热榜] → HotStockProvider → [筛选] → TushareClient(自包含 vendor) → [批量数据]
                                                                          ↓
    SwingOrchestrator ←── 4维量化评分 ←── 各分析器 ←─────────────────────┘
              ↓
    Top10 → LLM 二次尽调 (并行) → 融合评分 → Top3 买入
              ↓
    追踪池审查 → 量化卖出信号 → LLM 二次确认 → 执行卖出/否决
              ↓
    SwingRecorder → [每日快照 + LLM记录 + 交易汇总]
```

---

## 快速开始

### 依赖

```bash
# DSS 全部依赖（无外部项目依赖）
pip install tushare pandas numpy python-dotenv langchain-openai langchain-core
```

### 配置

`.env` 文件需要同时配置 Tushare 和 LLM：

```bash
# 数据源
TUSHARE_TOKEN=your_tushare_token

# LLM（DSS 独立配置，DSS_* 优先；TRADINGAGENTS_* 兼容可用）
DSS_LLM_PROVIDER=deepseek
DSS_QUICK_THINK_LLM=deepseek-chat
DEEPSEEK_API_KEY=sk-xxx
DSS_LLM_BACKEND_URL=https://api.deepseek.com

# 短线交易参数
SWING_POOL_SIZE=3
SWING_MAX_HOLD_DAYS=10
```

### 使用

```bash
# 短线交易（每日运行）
python -m dss.swing_cli run

# 试运行（不修改池）
python -m dss.swing_cli run --dry-run

# 查看追踪池
python -m dss.swing_cli pool

# 查看交易历史
python -m dss.swing_cli history

# 尾盘分析
python -m dss.interface_layer.tail_analysis --top 5

# 分钟数据采集
python -m dss.interface_layer.minute_collector --session afternoon

# 反馈闭环
python -m dss.optimization_engine.run_feedback_loop --mode verify-optimize
```

---

## 核心功能

### 1. 短线交易 (v10 — LLM 增强)

**策略**: 持仓 ≤10 个交易日（参考值），追踪池 3 只等额买入

```bash
python -m dss.swing_cli run
```

**分析流程**:

```
1. 市场环境评估      → 上证指数 MA20 + 情绪判断
2. 追踪池审查        → 5 条量化卖出规则 + 🆕 LLM 二次确认
3. 全市场预筛选      → ST/涨跌停/价格/流动性过滤 → Top60
4. 4 维量化评分      → 趋势(30%)+动量(25%)+量能(20%)+风险(15%)+市场(10%)
5. 🆕 LLM 二次尽调   → Top10 并行 LLM 分析（技术面+新闻+情绪）
6. 🆕 融合评分排序   → 量化分 × LLM 判定乘数 → Top3
7. 数据记录          → 含 LLM 分析详情 + 买入价 + 评分明细
```

**卖出逻辑** (v11.1 — 每次运行全新 LLM 决策，强制结构化输出):

> 止损/止盈/持仓时长均为**参考值**，非强制触发。最终决策由多 Agent 辩论产生。

1. 风险评估: 计算浮亏/浮盈/均线/大盘 → 生成风险上下文
2. 多Agent辩论: Bull Researcher（持有理由）∥ Bear Researcher（卖出理由）
3. 风控裁决: Risk Manager 综合辩论 + 市场 → SELL/HOLD
4. 参考值: 止损-5%、止盈+10%、持仓10天 — 仅提升风险级别，不自动卖出
5. 时间成本注入: 持仓超参考上限、曾浮盈现转亏、高点回撤超1/3 → 强卖出信号入辩论上下文
6. **强制结构化输出** (v11.1): 每个 Agent 声明 `required_fields`，LLM 输出经
   `response_format=json_object` 强制 JSON → 必需字段缺失即校验失败 → 错误回传模型
   重试（最多 2 次）→ 仍失败抛 `AgentOutputError` 终止本轮（fail-fast，绝不静默默认）

**四维度 + 市场评分模型**:
- **趋势 (30%)**: MA排列、价格vsMA20/MA60、趋势斜率、一致性
- **动量 (25%)**: 多周期收益、加速度、相对强度
- **量能 (20%)**: 量比、量价配合、资金流
- **风险 (15%)**: ATR、最大回撤、Beta、跳空风险
- **市场 (10%)**: 大盘情绪、指数位置

### 2. 超短线尾盘分析

**策略**: 尾盘 14:30 后买入，次日 9:30-10:00 卖出

```bash
python -m dss.interface_layer.tail_analysis --top 5
```

**两维度模型**:
- **技术动量 (60%)**: 当日涨跌幅、价格位置、尾盘趋势、成交量因子、尾盘量价推断
- **情绪面 (40%)**: 热榜排名、涨跌幅情绪

### 3. 分钟数据采集

```bash
python -m dss.interface_layer.minute_collector --session afternoon
```

### 4. 反馈优化闭环

```bash
python -m dss.optimization_engine.run_feedback_loop --mode verify-optimize
```

---

## 数据记录

### 每日快照 (`data/swing/daily/YYYYMMDD_swing.json`)

```json
{
  "date": "20260717",
  "market_env": { "sh_close": 3900, "sentiment": "bearish", ... },
  "pool_review": {
    "existing": 2,
    "sell_decisions": [{ "ts_code": "...", "reason": "STOP_LOSS", "llm_review": {...} }],
    "hold_checks": [...]
  },
  "new_picks": [{ "ts_code": "...", "entry_price": ..., "llm_verdict": "BUY", ... }],
  "pool_after": ["000001.SZ", "600519.SH", "603986.SH"],
  "llm_sell_reviews": [...],
  "llm_buy_analyses": [...]
}
```

### 交易历史 (`data/swing/swing_pool.json`)

每条交易记录含：买入价、卖出价、盈亏%、持仓天数、买入评分、规则原因、LLM 审查结果。

### 交易汇总

```python
from dss.optimization_engine.swing_recorder import SwingRecorder
recorder = SwingRecorder(config)
summary = recorder.generate_trade_summary("data/swing/swing_pool.json")
# => { total_trades, win_rate, avg_pnl_pct, avg_hold_days, sell_reasons, ... }
```

---

## 运行测试

```bash
pip install pytest
python -m pytest tests/ -v
```

---

## 项目结构

```
decision-support-system/
├── dss/                         # 主包（见架构图）
├── tests/                       # 单元测试
├── data/swing/                  # 短线数据
│   ├── daily/                   # 每日分析快照
│   └── swing_pool.json          # 追踪池 + 交易历史
├── .env                         # 环境变量
├── .env.example                 # 配置模板
├── pyproject.toml               # 包配置 + CLI 入口
├── README.md                    # 本文档
└── SKILL.md                     # 使用说明
```

---

## 开发历程

### v11.1 (2026-08-20) — LLM 交互层重构（强制结构化输出 + fail-fast）
- **根因修复**: LLM 输出字段名随机漂移（`decision`/`signal`/`最终裁决`/`verdict` 混用），
  解析层读空后静默默认 HOLD → "LLM 判了 SELL 却被当成继续持有"（历史盈利变亏损的深层主因）
- **按 CC StructuredOutput 原理改造**: `response_format=json_object` 强制 JSON +
  每个 Agent 声明 `required_fields` 必需字段校验 + 校验失败错误回传模型重试(2次) +
  仍失败抛 `AgentOutputError` 终止（fail-fast，宁失败不误判）
- 兼容层保留: 中英文键别名映射、嵌套 dict 列表文本提取、verdict 归一化兜底
- 编排层同步: 卖出/买入侧 `AgentOutputError` 直接上抛；网络超时降级结果显式标注
  "非LLM判定"；选股任一候选校验失败 → RuntimeError 中止本轮
- 盘中实时数据: `_assess_market` 实时指数优先 + 日线回退 + `[实时/日线]` 标注；
  持仓审查盘中用实时价；修复 `index_daily` 降序取到 1993 年数据的隐藏 bug
- 短线策略: Risk Manager 注入持仓时间成本/浮盈回撤/"盈利转亏损是最大禁忌"规则；
  ATR 评分改倒钟形（2.5-5% 最优，死水股票降分）
- 实测: 6 个 Agent 11/11 调用通过，000070 卖出审查修复前 0/5 判 SELL → 修复后 4-5/5

### v11.0 (2026-08-16) — 数据层解耦
- 移除对 TradingAgents 项目的运行期依赖（原委托其 tushare 厂商层）
- 新增 `data_layer/tushare_vendor.py`: 自包含实现全部 tushare 调用（日线/MA/批量/指数/资金流/热榜/ST/涨跌停/交易日历/股票列表/新闻）
- 保留 major_news 全局缓存（30 次/小时限流防护，每轮约 9 次调用）
- LLM 配置改 `DSS_*` 前缀（`TRADINGAGENTS_*` 兼容读取）
- 接口签名零变化，调用方无感知；multi-agent 设计思想仍参考 TradingAgents

### v10.2 (2026-07-20) — 卖出逻辑重构
- 固定规则 → 每次运行全新 LLM 多 Agent 分析
- 止损/止盈/持仓时长从强制触发改为参考值
- 每只池中股票均经过 Bull vs Bear 辩论 + Risk Manager 裁决

### v10.1 (2026-07-19) — 多 Agent 协作
- 买入侧: TechnicalAnalyst + NewsSentimentAnalyst → SwingTrader
- 卖出侧: BullResearcher ∥ BearResearcher → RiskManager

### v10.0 (2026-07-19) — LLM 增强（当时集成 TradingAgents 数据层）
- 数据层统一: `TushareClient` 委托 TradingAgents 厂商层（v11.0 已解耦）
- 新增 `llm_analyst/` 模块: LLM 客户端、批量并行尽调、卖出审查
- Top10 候选股 LLM 二次尽调（技术面+新闻+情绪融合）
- 卖出信号 LLM 二次确认（可否决量化信号）
- 统一数据记录: 含 LLM 分析详情 + 交易汇总生成

### v9.0 (2026-07-03) — 架构重构
- 上帝类分解: `UltraShortTailAnalyzer` (1467行) → 12个独立模块
- 统一数据访问: 移除重复热榜逻辑、硬编码 Token
- 依赖注入架构: 所有组件通过构造函数接收依赖
- 新增 31 个单元测试

### v8.8 (2026-04) — 去噪音精简版
- 移除资金面维度，收敛为2维度
- 集成尾盘量价推断信号到技术动量

### v8.7 — 智能交易日回溯
- 热榜获取支持10日回溯

### v8.6 — 成交量因子 + 大盘乘数
- 新增成交量因子评分、大盘环境评估

### v8.5 (2026-04-29) — 反馈优化引擎
- 新增 optimization_engine 层，推荐记录→次日验证→权重优化闭环

---

## 架构演进

| 维度 | v9.0 | v10.0 | v11.0 | v11.1 |
|------|------|-------|-------|-------|
| 数据访问 | 独立 TushareClient | 委托 TradingAgents 厂商层 | 自包含 tushare_vendor（独立 token） | 同 v11.0 + 盘中实时指数 |
| 选股决策 | 纯量化 4 维评分 | 量化 + LLM 二次尽调 | 同 v10 | ATR 倒钟形（偏好活跃股） |
| 卖出决策 | 5 条固定规则 | 量化规则 + LLM 二次确认 | 同 v10 + verdict 归一化 | 强制结构化输出 + fail-fast + 时间成本注入 |
| LLM 输出 | 无 | 自由 JSON（字段漂移风险） | 别名兼容解析 | json_object 强制 + 字段校验 + 重试 + 抛错 |
| 数据记录 | 每日快照 | 每日快照 + LLM 决策详情 + 交易汇总 | 同 v10 | 同 v10 |
| 外部依赖 | 无 | tradingagents 包 | 无（仅 tushare/langchain） | 同 v11.0 |

---

**注意**: 本系统仅供学习研究使用，不构成投资建议。投资有风险，决策需谨慎。
