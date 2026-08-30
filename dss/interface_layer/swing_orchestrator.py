"""
短线交易主编排器 v10 — 依赖注入 → 市场评估 → 池审查 → 选股 → LLM尽调 → 记录 → 报告

v10 增强:
- Top10 候选股经量化打分后，由 LLM 进行二次尽调
- 卖出信号触发后，由 LLM 进行二次确认（可否决）
- 记录 LLM 分析过程数据

核心入口: SwingOrchestrator.run_daily()
"""

import sys
import time
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Optional
from typing import List, Dict, Any, Optional
import pandas as pd

from dss.config import Config
from dss.data_layer.tushare_client import TushareClient
from dss.analysis_engine.swing_trend import SwingTrendAnalyzer
from dss.analysis_engine.swing_momentum import SwingMomentumAnalyzer
from dss.analysis_engine.swing_volume import SwingVolumeAnalyzer
from dss.analysis_engine.swing_risk import SwingRiskAnalyzer
from dss.analysis_engine.swing_composite import SwingCompositeScorer
from dss.analysis_engine.swing_types import CompositeResult
from dss.decision_core.swing_screener import SwingScreener
from dss.decision_core.swing_pool import SwingPool, SwingSellSignal, PoolEntry, SellDecision
from dss.decision_core.swing_plan import SwingTradePlan
from dss.optimization_engine.swing_recorder import SwingRecorder
from dss.interface_layer.swing_report import SwingReportFormatter
from dss.llm_analyst.buy_side import analyze_batch_buy
from dss.llm_analyst.sell_side import review_sell_signal as review_sell_multi_agent
from dss.data_layer.tushare_vendor import get_tushare_news, _to_ts_code


class SwingOrchestrator:
    """
    短线交易主编排器。

    通过构造函数注入所有依赖，run_daily() 执行完整的日度工作流。
    """

    def __init__(
        self,
        config: Config,
        tushare: TushareClient,
        screener: SwingScreener,
        trend_analyzer: SwingTrendAnalyzer,
        momentum_analyzer: SwingMomentumAnalyzer,
        volume_analyzer: SwingVolumeAnalyzer,
        risk_analyzer: SwingRiskAnalyzer,
        composite_scorer: SwingCompositeScorer,
        pool: SwingPool,
        sell_signal: SwingSellSignal,
        trade_plan: SwingTradePlan,
        recorder: SwingRecorder,
        formatter: SwingReportFormatter,
    ):
        self.config = config
        self.tushare = tushare
        self.screener = screener
        self.trend_analyzer = trend_analyzer
        self.momentum_analyzer = momentum_analyzer
        self.volume_analyzer = volume_analyzer
        self.risk_analyzer = risk_analyzer
        self.composite_scorer = composite_scorer
        self.pool = pool
        self.sell_signal = sell_signal
        self.trade_plan = trade_plan
        self.recorder = recorder
        self.formatter = formatter

    def run_daily(self, trade_date: str = None, dry_run: bool = False) -> Dict[str, Any]:
        """
        执行每日短线交易流程。

        流程:
        1. 评估市场环境
        2. 审查追踪池（卖出判定）
        3. 选股补仓（如果池 < 3）
        4. 更新池状态
        5. 记录数据
        6. 输出报告

        Args:
            trade_date: 交易日期 YYYYMMDD，默认今天
            dry_run: True 时不实际修改池状态

        Returns:
            完整结果字典
        """
        if trade_date is None:
            trade_date = datetime.now().strftime('%Y%m%d')

        print(f"\n{'=' * 60}")
        print(f"  短线交易决策分析 — {trade_date}")
        print(f"{'=' * 60}")

        # 1. 市场环境评估
        market_env = self._assess_market()
        src_label = market_env.get('data_source', 'daily')
        used_date = market_env.get('used_trade_date', '')
        tag = f"[实时 {used_date}]" if src_label == 'realtime' else f"[日线 {used_date}]"
        print(f"📊 市场评分: {market_env['market_score']:.0f} ({market_env['sentiment']}) {tag}")

        # 2. 审查追踪池
        pool_review = self._review_pool(trade_date, market_env, dry_run)

        # 3. 选股补仓（v10.2: 只有 LLM 判定 BUY 的才入池）
        slots = self.pool.get_available_slots()
        new_picks = []
        if slots > 0:
            print(f"\n🔍 需要补仓 {slots} 只...")
            new_picks = self._find_new_picks(slots, trade_date, market_env)
            if not new_picks:
                print(f"   (无 BUY 判定候选，{slots} 个空位暂不填补)")
        else:
            print("✅ 追踪池已满，跳过选股")

        # 4. 更新池状态（非 dry-run）— 只入 BUY 判定的股票
        if not dry_run:
            for pick in new_picks:
                self.pool.add_to_pool(
                    ts_code=pick['ts_code'],
                    name=pick.get('name', ''),
                    buy_date=trade_date,
                    buy_price=pick['entry_price'],
                    composite_score=pick.get('composite_score', 0),
                    factors=pick.get('factors', {}),
                )

        # 5. 记录数据 (v10: 含 LLM 分析详情)
        pool_after = [e.ts_code for e in self.pool.get_active_pool()]
        if not dry_run:
            llm_sell_reviews = [
                {"ts_code": s.get("ts_code"), "reason": s.get("reason"),
                 "llm_review": s.get("llm_review", {})}
                for s in pool_review.get('sell_decisions', []) if s.get('llm_review')
            ]
            # 记录所有 LLM 分析过的候选股判定（含非 BUY），便于后续审查
            llm_buy_analyses = [
                {"ts_code": c.get("ts_code"),
                 "llm_verdict": c.get("llm_verdict"),
                 "llm_confidence": c.get("llm_confidence"),
                 "llm_reasoning": (c.get("llm_reasoning") or "")[:200]}
                for c in getattr(self, '_last_llm_analyzed', [])
            ]
            self.recorder.record_daily_analysis(
                trade_date=trade_date,
                market_env=market_env,
                pool_review=pool_review,
                new_picks=new_picks,
                pool_after=pool_after,
                llm_sell_reviews=llm_sell_reviews or None,
                llm_buy_analyses=llm_buy_analyses or None,
            )

        # 6. 汇总结果
        stats = self.pool.get_summary_stats()
        results = {
            'date': trade_date,
            'market_env': market_env,
            'pool_review': pool_review,
            'new_picks': new_picks,
            'pool_after': pool_after,
            'stats': stats,
            'dry_run': dry_run,
        }

        # 输出报告
        report = self.formatter.format_daily_report(results)
        print(report)

        return results

    # ------------------------------------------------------------------
    # 私有方法
    # ------------------------------------------------------------------

    @staticmethod
    def _is_trading_hours() -> bool:
        """判断当前是否在 A 股交易时段 (9:30-11:30, 13:00-15:00)。"""
        from datetime import datetime
        now = datetime.now()
        if now.weekday() >= 5:  # 周末
            return False
        t = now.hour * 60 + now.minute
        return (9*60+30 <= t <= 11*60+30) or (13*60 <= t <= 15*60)

    def _assess_market(self) -> Dict[str, Any]:
        """评估市场环境 — 盘中实时指数优先，非盘时/失败回退日线。

        返回字段（下游零破坏，只增不改）:
            data_source: 'realtime' | 'daily' — 当日数据来源
            is_intraday: bool — 是否盘中
            used_trade_date: str — 实际采用的行情日期 YYYYMMDD
        """
        try:
            # 盘中 → 优先实时指数（get_realtime_quotes 同通道，已验证可用）
            if self._is_trading_hours():
                sh_price, sh_chg = self.tushare.get_intraday_index_change('sh000001')
                if sh_price is not None and sh_chg is not None:
                    res = self._score_market(
                        sh_close=sh_price,
                        sh_change=sh_chg,
                        used_date=datetime.now().strftime('%Y%m%d'),
                        data_source='realtime',
                    )
                    if res:
                        return res

            # 非盘中 / 实时失败 → 回退日线（原逻辑）
            idx_df = self.tushare.index_daily(
                ts_code='000001.SH',
                start_date=self.tushare.days_ago_str(60),
                end_date=self.tushare.today_str(),
            )
            if idx_df is not None and not idx_df.empty:
                idx_df = idx_df.sort_values('trade_date')
                used_date = str(idx_df['trade_date'].iloc[-1])
                close = idx_df['close'].values
                sh_close = float(close[-1])
                sh_change = 0.0
                if 'pct_chg' in idx_df.columns:
                    sh_change = float(idx_df['pct_chg'].iloc[-1])
                elif len(close) >= 2:
                    sh_change = (close[-1] - close[-2]) / close[-2] * 100
                res = self._score_market(
                    sh_close=sh_close,
                    sh_change=sh_change,
                    used_date=used_date,
                    data_source='daily',
                )
                if res:
                    return res
        except Exception as e:
            print(f"⚠️ 市场评估失败: {e}")

        return {'sh_close': 0, 'sh_ma20': 0, 'sh_change_pct': 0,
                'sentiment': 'unknown', 'market_score': 50.0,
                'turnaround': {'active': False},
                'data_source': 'daily', 'is_intraday': False, 'used_trade_date': ''}

    def _score_market(self, sh_close: float, sh_change: float,
                      used_date: str, data_source: str) -> Optional[Dict[str, Any]]:
        """由 (现价/涨跌幅, MA20 日线基准) 计算市场评分与情绪。

        MA20 始终用日线回看计算（基准不随盘中跳动），仅现价与涨跌幅可来自实时。
        """
        try:
            idx_df = self.tushare.index_daily(
                ts_code='000001.SH',
                start_date=self.tushare.days_ago_str(60),
                end_date=self.tushare.today_str(),
            )
            if idx_df is None or idx_df.empty:
                return None
            idx_df = idx_df.sort_values('trade_date')
            ma20 = float(idx_df['close'].rolling(20).mean().iloc[-1])
            if pd.isna(ma20):
                ma20 = sh_close

            price_vs_ma = (sh_close - ma20) / ma20 * 100
            market_score = 50 + min(price_vs_ma * 5, 50)

            if price_vs_ma > 3:
                base_sentiment = 'bullish'
            elif price_vs_ma > 1:
                base_sentiment = 'slightly_bullish'
            elif price_vs_ma > -1:
                base_sentiment = 'neutral'
            elif price_vs_ma > -3:
                base_sentiment = 'slightly_bearish'
            else:
                base_sentiment = 'bearish'

            # 转向信号检测（用日线收盘序列 + 当日涨跌）
            turnaround = self._detect_turnaround(
                idx_df, idx_df['close'].values, sh_change, price_vs_ma)

            sentiment = base_sentiment
            adjusted_score = market_score
            if turnaround['active']:
                if base_sentiment in ('bearish', 'slightly_bearish'):
                    sentiment = 'slightly_bearish' if base_sentiment == 'bearish' else 'neutral'
                adjusted_score = min(100, market_score + turnaround['score_boost'])

            return {
                'sh_close': sh_close,
                'sh_ma20': round(ma20, 2),
                'sh_change_pct': round(sh_change, 2),
                'sentiment': sentiment,
                'market_score': round(adjusted_score, 1),
                'base_sentiment': base_sentiment,
                'turnaround': turnaround,
                'data_source': data_source,
                'is_intraday': data_source == 'realtime',
                'used_trade_date': used_date,
            }
        except Exception as e:
            print(f"⚠️ 市场评分计算失败: {e}")
            return None

    @staticmethod
    def _detect_turnaround(idx_df, close_values, today_change, price_vs_ma):
        """检测市场转向信号。

        多维度判断下跌趋势是否正在反转:
        1. 单日涨幅: >1.5% 强反弹, >0.8% 普通反弹
        2. 连续涨幅: 最近2-3天是否持续上涨
        3. 短期均线: 5日线是否拐头向上
        4. 成交量: 反弹是否放量
        5. 价格位置: 是否从极度超卖状态反弹
        """
        signals = []
        score_boost = 0

        n = len(close_values)

        # 1. 单日涨幅
        if today_change > 2.0:
            signals.append(f'强反弹(+{today_change:.1f}%)')
            score_boost += 15
        elif today_change > 1.0:
            signals.append(f'反弹(+{today_change:.1f}%)')
            score_boost += 8
        elif today_change > 0.5:
            signals.append(f'温和上涨(+{today_change:.1f}%)')
            score_boost += 4

        # 2. 连续上涨（最近3天中至少2天上涨）
        if n >= 4:
            recent = close_values[-4:]
            up_days = sum(1 for i in range(1, len(recent)) if recent[i] > recent[i-1])
            if up_days >= 3:
                signals.append('连续3日上涨')
                score_boost += 10
            elif up_days >= 2:
                signals.append('近3日2涨')
                score_boost += 5

        # 3. 短期趋势改善（5日均线拐头）
        if n >= 6:
            ma5_recent = sum(close_values[-5:]) / 5
            ma5_prev = sum(close_values[-6:-1]) / 5
            if ma5_recent > ma5_prev * 1.005:
                signals.append('MA5拐头向上')
                score_boost += 8

        # 4. 从极端位置反弹（超卖反弹）
        if price_vs_ma < -5:
            signals.append(f'从深度超卖反弹(偏离MA20 {price_vs_ma:.1f}%)')
            score_boost += 10

        # 5. 量能配合（如果有volume数据）
        if 'vol' in idx_df.columns and n >= 2:
            try:
                today_vol = float(idx_df['vol'].iloc[-1])
                avg_vol_5 = float(idx_df['vol'].iloc[-6:-1].mean()) if n >= 6 else today_vol
                if avg_vol_5 > 0 and today_vol > avg_vol_5 * 1.3:
                    signals.append('放量反弹')
                    score_boost += 5
            except (ValueError, TypeError, IndexError):
                pass

        active = len(signals) >= 2 or (today_change > 1.5 and len(signals) >= 1)

        return {
            'active': active,
            'signals': signals,
            'score_boost': score_boost,
        }

    def _review_pool(
        self, trade_date: str, market_env: dict, dry_run: bool
    ) -> Dict[str, Any]:
        """审查追踪池 — 每只股票进行多Agent协作分析，做出新鲜卖出/持有决策。

        不再依赖固定止损/止盈/时间规则。每次分析都是全新的 LLM 决策。
        量化风险指标只作为参考上下文注入 Agent 辩论。
        """
        active = self.pool.get_active_pool()
        sell_decisions = []
        hold_checks = []

        if not active:
            print("📋 追踪池为空，跳过审查")
            return {'existing': 0, 'sell_decisions': [], 'hold_checks': []}

        print(f"\n📋 审查追踪池 ({len(active)} 只持仓)...")

        for entry in active:
            print(f"\n  🔍 {entry.ts_code} {entry.name} (买入价:{entry.buy_price}, 持有{entry.hold_days}天)")

            df = self.tushare.daily_with_ma(
                ts_code=entry.ts_code,
                start_date=self.tushare.days_ago_str(120),
                end_date=trade_date,
            )

            if df is None or df.empty:
                print(f"    ⚠️ 无数据，跳过")
                continue

            # 盘中 → 用实时价审查持仓（决策基于当日盘面，而非昨日收盘）
            close = float(df['close'].iloc[-1])
            price_src = "日线"
            if self._is_trading_hours():
                rt_df = self.tushare.get_realtime_quotes(
                    [entry.ts_code.replace('.SH', '').replace('.SZ', '').replace('.BJ', '')]
                )
                if rt_df is not None and not rt_df.empty:
                    rt_price = self.tushare.safe_float(rt_df.iloc[0].to_dict(),
                                                        ['price', 'current', 'close', 'last', 'trade', '最新价'])
                    if rt_price > 0:
                        close = rt_price
                        price_src = "实时"
            pnl = (close - entry.buy_price) / entry.buy_price * 100
            print(f"    当前价: {close:.2f} [{price_src}]  盈亏: {pnl:+.2f}%")

            # 风险评估（仅作参考上下文，不做决策）
            risk_ctx = self.sell_signal.assess(entry, df, market_env)
            print(f"    风险: {risk_ctx['risk_level']}  MA: {risk_ctx['ma_status']}  市场: {risk_ctx['market_risk']}")

            # 量化移动止盈/时间保护（注入辩论上下文，不做强制决策）
            highest = getattr(entry, 'highest_since_buy', 0) or 0
            max_profit_pct = (highest - entry.buy_price) / entry.buy_price * 100 if entry.buy_price > 0 else 0
            pullback = (highest - close) / highest * 100 if highest > 0 else 0
            trailing_signals = []
            # 浮盈保护: 最高浮盈 ≥ 5% 且从高点回撤 ≥ 1/3 浮盈 → 强烈卖出信号
            if max_profit_pct >= 5 and pullback >= max_profit_pct / 3:
                trailing_signals.append(
                    f"📉 移动止盈警示: 最高浮盈 {max_profit_pct:.1f}% 已回吐 {pullback:.1f}% "
                    f"(超过浮盈的1/3)，短线应落袋"
                )
            # 盈利转亏损禁忌: 曾浮盈 ≥ 3% 现回到成本线以下
            if max_profit_pct >= 3 and pnl < 0:
                trailing_signals.append(
                    f"🚨 盈利转亏损: 曾浮盈 {max_profit_pct:.1f}% 现在浮亏 {pnl:.1f}%，"
                    f"短线最大禁忌，应立即评估卖出"
                )
            # 时间成本: 超参考上限且无显著浮盈
            if entry.hold_days >= self.sell_signal.max_hold_ref and pnl < 5:
                trailing_signals.append(
                    f"⏰ 持仓 {entry.hold_days} 天超过参考上限 {self.sell_signal.max_hold_ref} 天，"
                    f"资金占用成本高且无显著收益，倾向卖出"
                )

            # 多Agent对抗辩论 — 每次都是全新的完整分析
            try:
                llm_review = review_sell_multi_agent(
                    ts_code=entry.ts_code,
                    name=entry.name,
                    buy_price=entry.buy_price,
                    current_price=close,
                    hold_days=entry.hold_days,
                    sell_reason="FRESH_ANALYSIS",  # 不再是固定的触发规则
                    sell_detail=(
                        f"盈亏: {pnl:+.2f}% | "
                        f"风险级别: {risk_ctx['risk_level']} | "
                        f"均线: {risk_ctx['ma_status']} | "
                        f"价格vs均线: {risk_ctx['price_vs_ma']} | "
                        f"最高价: {highest:.2f} (浮盈 {max_profit_pct:.1f}%, "
                        f"回撤 {pullback:.1f}%) | "
                        f"{'; '.join(risk_ctx.get('warnings', []))} | "
                        f"{'; '.join(trailing_signals)}"
                    ),
                    ohlcv_df=df,
                    news_text="",
                    market_env=market_env,
                    hold_days_ref=self.sell_signal.max_hold_ref,
                    highest_price=highest,
                )
            except Exception as e:
                llm_review = {"confirm_sell": False, "override_reason": f"分析异常: {e}"}

            if llm_review.get("confirm_sell", False):
                # LLM 确认卖出
                reason = llm_review.get("debate_winner", "LLM")
                sell_decisions.append({
                    'ts_code': entry.ts_code,
                    'name': entry.name,
                    'reason': f'LLM_{reason}',
                    'detail': f'辩论胜方={reason}, 因素={llm_review.get("decisive_factors", [])}',
                    'exit_price': close,
                    'llm_review': llm_review,
                    'pnl_pct': round(pnl, 2),
                    'hold_days': entry.hold_days,
                })
                if not dry_run:
                    self.pool.execute_sell(
                        ts_code=entry.ts_code,
                        exit_price=close,
                        reason=f'LLM_{reason}',
                        trade_date=trade_date,
                        confidence=llm_review.get("adjusted_confidence", 80.0),
                    )
                print(f"    ✅ 决策: 卖出 ({reason})")
            else:
                # LLM 决定继续持有
                hold_checks.append({
                    'ts_code': entry.ts_code,
                    'close': close,
                    'pnl_pct': round(pnl, 2),
                    'risk_level': risk_ctx['risk_level'],
                    'llm_review': llm_review,
                })
                if not dry_run:
                    self.pool.log_daily_snapshot(
                        ts_code=entry.ts_code,
                        date=trade_date,
                        close=close,
                        pct_chg=float(df.get('pct_chg', pd.Series([0])).iloc[-1]) if 'pct_chg' in df.columns else 0,
                        sell_check={
                            'decision': 'HOLD',
                            'risk_level': risk_ctx['risk_level'],
                            'llm_debate_winner': llm_review.get("debate_winner", ""),
                        },
                    )
                print(f"    ❌ 决策: 继续持有")

        return {
            'existing': len(active),
            'sell_decisions': sell_decisions,
            'hold_checks': hold_checks,
        }

    def _find_new_picks(self, slots: int, trade_date: str, market_env: dict = None) -> List[Dict[str, Any]]:
        """选股补仓"""
        # 预筛选
        candidates = self.screener.screen(trade_date=trade_date, limit=100)
        if not candidates:
            return []

        # 获取指数数据（用于相对强度计算）
        try:
            idx_df = self.tushare.index_daily(
                ts_code='000001.SH',
                start_date=self.tushare.days_ago_str(60),
                end_date=trade_date,
            )
            if idx_df is not None:
                idx_df = idx_df.sort_values('trade_date')
        except Exception:
            idx_df = None

        # 分析每只候选股
        print(f"分析 {len(candidates)} 只候选股...")
        analyzed = self._analyze_candidates(candidates, idx_df, trade_date)

        # 按综合评分排序
        analyzed.sort(key=lambda x: x.get('composite_score', 0), reverse=True)

        # v10.1: Top10 进行多 Agent 协作尽调
        top_n_for_llm = min(len(analyzed), 10)
        if top_n_for_llm >= 3:
            print(f"\n🤖 多Agent协作尽调 top{top_n_for_llm} 候选股...")
            candidates_for_llm = []
            for c in analyzed[:top_n_for_llm]:
                news_text = ""
                try:
                    news_text = get_tushare_news(
                        ticker=c['ts_code'].replace('.SH', '.SS'),
                        start_date=(datetime.strptime(trade_date, '%Y%m%d') - timedelta(days=7)).strftime('%Y-%m-%d'),
                        end_date=datetime.strptime(trade_date, '%Y%m%d').strftime('%Y-%m-%d'),
                    )
                except Exception:
                    pass
                candidates_for_llm.append({
                    "ts_code": c['ts_code'],
                    "name": c.get('name', ''),
                    "ohlcv_df": c.get('ohlcv_df'),
                    "news_text": news_text,
                    "composite_score": c.get('composite_score', 0),
                    "factors": c.get('factors', {}),
                    "using_realtime": self._is_trading_hours(),
                    "market_env": {
                        "sentiment": (market_env or {}).get("sentiment", ""),
                        "market_score": (market_env or {}).get("market_score", 50),
                        "sh_change_pct": (market_env or {}).get("sh_change_pct", 0),
                    },
                })
            llm_results = analyze_batch_buy(candidates_for_llm, max_workers=3)
            # Debug: show verdict distribution
            verdicts = {}
            for r in llm_results:
                v = r.get('trader', {}).get('verdict', '?')
                verdicts[v] = verdicts.get(v, 0) + 1
            print(f"   LLM 判定分布: {verdicts}")

            # fail-fast: 任一候选 LLM 输出校验失败 → 中止本轮选股并报错。
            # 宁可运行失败，也不让"分析失败"混入 BUY 判定（静默有误）。
            failed = [r for r in llm_results if r.get('llm_failed')]
            if failed:
                fail_codes = [r['ts_code'] for r in failed]
                fail_msgs = [r.get('llm_failure', '') for r in failed]
                raise RuntimeError(
                    f"LLM 输出校验失败，中止选股: {fail_codes} | {fail_msgs[0] if fail_msgs else ''}"
                )
            # Merge LLM results back
            llm_map = {r['ts_code']: r for r in llm_results}
            for c in analyzed[:top_n_for_llm]:
                lr = llm_map.get(c['ts_code'], {})
                trader = lr.get('trader', {})
                c['llm_verdict'] = trader.get('verdict', '')
                c['llm_confidence'] = trader.get('confidence', 0)
                c['llm_reasoning'] = trader.get('reasoning', '')
                c['llm_consensus'] = trader.get('consensus', '')
                c['llm_combined_score'] = lr.get('combined_score', c.get('composite_score', 0))
                c['llm_full_result'] = lr  # 保存完整的多Agent分析结果
                if trader.get('verdict') == 'BUY':
                    c['composite_score'] = lr.get('combined_score', c.get('composite_score', 0))

            # Re-sort after LLM boost
            analyzed.sort(key=lambda x: x.get('composite_score', 0), reverse=True)

        # v10.2: 只选 LLM 判定 BUY 的股票入池（HOLD/SKIP 不入）
        buy_candidates = [c for c in analyzed if c.get('llm_verdict') == 'BUY']
        if not buy_candidates:
            print(f"\n⚠️ 无候选股通过 LLM 多Agent 买入判定，本轮不新增持仓")
            return []

        # 缓存所有 LLM 分析过的候选股（含非 BUY），供记录
        self._last_llm_analyzed = [
            c for c in analyzed if c.get("llm_verdict")
        ]

        top = buy_candidates[:slots]
        print(f"\n   LLM 判定: {len(buy_candidates)} 只 BUY, 选取前 {len(top)} 只")

        # 生成入场计划
        for i, pick in enumerate(top):
            pick['rank'] = i + 1
            pick['stop_loss'] = round(pick['entry_price'] * self.config.SWING_STOP_LOSS_PCT, 2)
            pick['take_profit'] = round(pick['entry_price'] * self.config.SWING_TAKE_PROFIT_PCT, 2)

        return top

    def _analyze_candidates(
        self, candidates, idx_df, trade_date: str
    ) -> List[Dict[str, Any]]:
        """并行分析候选股"""
        results = []

        # 限制数量避免API过载
        to_analyze = candidates[:60]

        with ThreadPoolExecutor(max_workers=self.config.MAX_WORKERS) as executor:
            futures = {
                executor.submit(self._analyze_single, c, idx_df, trade_date): c
                for c in to_analyze
            }

            for future in as_completed(futures):
                try:
                    result = future.result(timeout=30)
                    if result is not None:
                        results.append(result)
                except Exception as e:
                    pass

        return results

    def _analyze_single(
        self, candidate, idx_df, trade_date: str
    ) -> Optional[Dict[str, Any]]:
        """分析单只股票"""
        ts_code = candidate.ts_code

        try:
            # 获取日K线+均线
            df = self.tushare.daily_with_ma(
                ts_code=ts_code,
                start_date=self.tushare.days_ago_str(120),
                end_date=trade_date,
            )
            if df is None or df.empty or len(df) < 10:
                return None

            # 四个维度分析
            trend = self.trend_analyzer.analyze(df)
            momentum = self.momentum_analyzer.analyze(df, idx_df)
            volume = self.volume_analyzer.analyze(df)
            risk = self.risk_analyzer.analyze(df, idx_df)

            # 市场评分
            market_score = self._market_score_from_index(idx_df)

            # 综合评分
            composite = self.composite_scorer.compute(
                trend=trend, momentum=momentum, volume=volume,
                risk=risk, market_env_score=market_score,
            )

            if composite.overall_score < 55:
                return None

            return {
                'ts_code': ts_code,
                'name': candidate.name,
                'entry_price': candidate.current_price,
                'composite_score': composite.overall_score,
                'trend': composite.trend_score,
                'momentum': composite.momentum_score,
                'volume': composite.volume_score,
                'risk': composite.risk_score,
                'market_env': composite.market_env_score,
                'rationale': composite.rationale,
                'factors': {
                    'trend': composite.trend_score,
                    'momentum': composite.momentum_score,
                    'volume': composite.volume_score,
                    'risk': composite.risk_score,
                    'market_env': composite.market_env_score,
                },
            }
        except Exception as e:
            return None

    @staticmethod
    def _market_score_from_index(idx_df) -> float:
        """从指数DataFrame计算市场评分"""
        if idx_df is None or idx_df.empty or len(idx_df) < 20:
            return 50.0

        close = idx_df['close'].values
        ma20_series = pd.Series(close).rolling(20).mean()
        if len(ma20_series) < 2 or pd.isna(ma20_series.iloc[-1]):
            return 50.0

        latest_close = close[-1]
        ma20 = ma20_series.iloc[-1]
        pct = (latest_close - ma20) / ma20 * 100
        score = 50 + min(max(pct * 3, -40), 50)
        return min(100, max(0, score))
