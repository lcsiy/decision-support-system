#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
超短线尾盘分析器 v9.0 — 薄编排器。

策略逻辑：尾盘14:30后买入，次日9:30-10:00卖出。

v9 重构：
- 从上帝类 (1467行) 重构为依赖注入编排器 (~200行)
- 数据获取 → dss.data_layer
- 分析引擎 → dss.analysis_engine
- 决策生成 → dss.decision_core
- 报告格式化 → dss.interface_layer.report_formatter

两维度模型 (v8.8):
- 技术动量 (60%): 含成交量因子 + 尾盘量价推断
- 情绪面 (40%): 热榜排名 + 涨跌幅情绪
"""

import os
import sys
import argparse
import traceback
import concurrent.futures
from datetime import datetime
from typing import Dict, Any, List, Optional

# 修复 Windows 控制台编码
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# 添加项目根目录到路径（兼容直接运行脚本）
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from dss.config import Config
from dss.data_layer.tushare_client import TushareClient
from dss.data_layer.hot_stock_provider import HotStockProvider
from dss.data_layer.minute_data_repo import MinuteDataRepository
from dss.data_layer.stock_filter import StockFilter, FilterConfig
from dss.analysis_engine.technical_momentum import TechnicalMomentumAnalyzer
from dss.analysis_engine.sentiment import SentimentAnalyzer
from dss.analysis_engine.opening_prediction import OpeningPredictor
from dss.analysis_engine.overnight_risk import OvernightRiskAssessor
from dss.decision_core.trading_plan import TradingPlanGenerator
from dss.decision_core.stock_screener import StockScreener
from dss.interface_layer.report_formatter import ReportFormatter


class TailAnalysisOrchestrator:
    """
    超短线尾盘分析编排器 v9.0。

    依赖注入所有分析组件，负责编排完整的分析流程：
    获取热榜 → 批量拉数据 → 大盘评估 → 逐股分析 → 排序 → 报告

    使用方式:
        config = Config()
        orchestrator = TailAnalysisOrchestrator(config)
        recommendations = orchestrator.run(top_n=5)
    """

    def __init__(self, config: Config):
        """
        Args:
            config: 系统配置对象
        """
        self.config = config

        # --- 数据层 ---
        self.client = TushareClient(config)
        self.stock_filter = StockFilter(FilterConfig(
            exclude_prefixes=['688', '300', '8'],
            exclude_st=True,
        ))
        self.hot_stocks = HotStockProvider(self.client, self.stock_filter)
        self.minute_repo = MinuteDataRepository(config.MINUTE_DATA_DIR)

        # --- 分析引擎 ---
        self.momentum = TechnicalMomentumAnalyzer()
        self.sentiment = SentimentAnalyzer()
        self.prediction = OpeningPredictor()
        self.risk_assessor = OvernightRiskAssessor()

        # --- 决策核心 ---
        self.screener = StockScreener(min_liquidity=config.DEFAULT_MIN_LIQUIDITY)
        self.trading_plan = TradingPlanGenerator()

        # --- 接口层 ---
        self.reporter = ReportFormatter()

        # --- 运行时状态 ---
        self.market_env: Optional[Dict[str, Any]] = None
        self._realtime_cache: Dict[str, Dict[str, Any]] = {}
        self._daily_cache: Dict[str, Any] = {}

    # =========================================================================
    # 主流程
    # =========================================================================

    def run(
        self,
        top_n: int = 5,
        hot_limit: int = 300,
        max_workers: int = 4,
        use_minute_data: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        执行完整的尾盘分析流程。

        Args:
            top_n: 返回前 N 名推荐
            hot_limit: 热榜获取数量
            max_workers: 并行线程数
            use_minute_data: 是否使用分钟数据

        Returns:
            推荐列表（按综合评分降序）
        """
        print("=" * 80)
        print("超短线尾盘分析器 v9.0 — 两维度精简版")
        print(f"策略：尾盘14:30后买入，次日9:30-10:00卖出")
        print(f"两维度：技术动量(60%) + 情绪面(40%)")
        print(f"分钟数据：{'启用' if use_minute_data else '禁用'}")
        print("=" * 80)

        # 1. 获取热榜
        stocks = self.hot_stocks.get_hot_stocks(limit=hot_limit)
        if not stocks:
            print("❌ 无法获取股票列表")
            return []

        print(f"\n开始分析 {len(stocks)} 只股票的超短线尾盘机会...")

        # 2. 大盘环境
        self.market_env = self.client.get_market_environment()
        if self.market_env.get('available'):
            print(f"  市场情绪: {self.market_env['market_sentiment']}, "
                  f"乘数因子: {self.market_env['market_multiplier']:.2f}")

        # 3. 批量获取数据
        print("\n📊 批量获取数据...")
        stock_codes = [s.ts_code for s in stocks]
        self._realtime_cache = self.client.batch_fetch_realtime(stock_codes)
        print(f"✅ 实时行情已缓存: {len(self._realtime_cache)} 只")

        self._daily_cache = self.client.batch_daily(
            stock_codes,
            start_date=self.client.days_ago_str(10),
            end_date=self.client.today_str(),
        )
        print(f"✅ 日线数据获取完成: {len(self._daily_cache)} 只")

        # 4. 并行分析
        recommendations = self._analyze_parallel(stocks, max_workers, use_minute_data)

        # 5. 排序截断
        recommendations.sort(key=lambda x: x.get('comprehensive_score', 0), reverse=True)
        return recommendations[:top_n]

    # =========================================================================
    # 内部：逐股分析
    # =========================================================================

    def _analyze_parallel(
        self,
        stocks: list,
        max_workers: int,
        use_minute_data: bool,
    ) -> List[Dict[str, Any]]:
        """并行分析所有股票"""
        recommendations: List[Dict[str, Any]] = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_stock = {}
            for s in stocks:
                future = executor.submit(
                    self._analyze_single, s.ts_code, s.name, s.rank, use_minute_data
                )
                future_to_stock[future] = (s.ts_code, s.name)

            for future in concurrent.futures.as_completed(future_to_stock):
                ts_code, name = future_to_stock[future]
                try:
                    result = future.result(timeout=60)
                    if result is None:
                        continue
                    if result.get('excluded', False):
                        print(f"  ✗ 排除: {name} ({ts_code}) - {result.get('exclude_reason', '')}")
                        continue

                    score = result.get('comprehensive_score', 0)
                    if score >= 60:
                        recommendations.append(result)
                        market_note = ""
                        if self.market_env and self.market_env.get('available'):
                            mult = self.market_env.get('market_multiplier', 1.0)
                            if mult != 1.0:
                                market_note = f" [大盘×{mult:.2f}]"
                        print(f"  ✅ {name} ({ts_code}): {score:.1f}{market_note}")
                    else:
                        print(f"  ✗ 评分不足: {name} ({ts_code}): {score:.1f}")

                except Exception as e:
                    print(f"  ⚠️ 分析失败: {name} ({ts_code}): {str(e)[:50]}")

        return recommendations

    def _analyze_single(
        self,
        ts_code: str,
        name: str,
        hot_rank: int,
        use_minute_data: bool,
    ) -> Optional[Dict[str, Any]]:
        """
        分析单只股票 — 串联所有分析组件。

        Returns:
            完整的分析结果 dict，或 None（跳过）/ excluded dict
        """
        print(f"\n分析: {name} ({ts_code})")

        # 1. 获取实时数据（批量缓存 → 单股回退 → 日线回退）
        realtime_data = self._realtime_cache.get(ts_code, {})
        if not realtime_data:
            # 批量获取失败时（如非交易时段），尝试单股获取
            try:
                df_q = self.client.realtime_quote(ts_code=ts_code, src='dc')
                if df_q is not None and not df_q.empty:
                    realtime_data = df_q.iloc[0].to_dict()
                    self._realtime_cache[ts_code] = realtime_data
            except Exception:
                pass

        # 日线数据回退：Tushare v10 已废弃 get_realtime_quotes，
        # 当实时数据为空时用最新日线数据提取价格
        if not realtime_data:
            daily_df = self._daily_cache.get(ts_code)
            if daily_df is not None and not daily_df.empty:
                latest = daily_df.iloc[-1]
                realtime_data = {
                    'price': float(latest.get('close', 0)),
                    'pre_close': float(latest.get('pre_close', 0)),
                    'amount': float(latest.get('amount', 0)),
                    'pct_chg': float(latest.get('pct_chg', 0)),
                    '_source': 'daily_fallback',
                }

        # 2. 预筛选
        screen_result = self.screener.screen(ts_code, realtime_data)
        if not screen_result.passed:
            print(f"  🚫 {screen_result.exclude_reason}")
            return {
                'ts_code': ts_code, 'name': name,
                'comprehensive_score': 0, 'excluded': True,
                'exclude_reason': screen_result.exclude_reason,
            }

        current_price = screen_result.current_price
        daily_change_pct = screen_result.daily_change_pct

        # 2. 获取分钟数据
        minute_df = None
        if use_minute_data:
            today = datetime.now().strftime('%Y%m%d')
            minute_df = self.minute_repo.read_recent_minutes(today, ts_code, minutes=30)

        # 3. 两维度分析
        print("  📊 两维度分析...")

        momentum_score, momentum_details = self.momentum.analyze(
            ts_code=ts_code,
            current_price=current_price,
            daily_change_pct=daily_change_pct,
            realtime_data=realtime_data,
            daily_df=self._daily_cache.get(ts_code),
            minute_df=minute_df,
            use_minute_data=use_minute_data,
        )
        min_flag = "" if momentum_details.get('minute_data_available') else " ⚠️无分钟数据"
        print(f"    技术动量: {momentum_score:.1f}{min_flag}")

        sentiment_score, sentiment_details = self.sentiment.analyze(
            ts_code=ts_code,
            name=name,
            hot_rank=hot_rank,
            daily_change_pct=daily_change_pct,
        )
        print(f"    情绪面: {sentiment_score:.1f}")

        # 4. 综合评分
        raw_score = (
            momentum_score * self.config.MOMENTUM_WEIGHT +
            sentiment_score * self.config.SENTIMENT_WEIGHT
        )
        market_multiplier = (
            self.market_env.get('market_multiplier', 1.0)
            if self.market_env else 1.0
        )
        comprehensive_score = raw_score * market_multiplier

        if market_multiplier != 1.0:
            print(f"    大盘乘数: {market_multiplier:.2f} "
                  f"(原始分{raw_score:.1f} → {comprehensive_score:.1f})")

        # 5. 预测与评估
        prediction = self.prediction.predict(
            current_price=current_price,
            daily_change_pct=daily_change_pct,
            momentum_score=momentum_score,
            sentiment_score=sentiment_score,
            momentum_details=momentum_details,
        )

        risk = self.risk_assessor.assess(
            ts_code=ts_code,
            current_price=current_price,
            daily_change_pct=daily_change_pct,
            realtime_data=realtime_data,
            momentum_details=momentum_details,
        )

        plan = self.trading_plan.generate(
            ts_code=ts_code,
            name=name,
            current_price=current_price,
            daily_change_pct=daily_change_pct,
            comprehensive_score=comprehensive_score,
            next_day_prediction=prediction,
            risk_assessment=risk,
        )

        result = {
            'ts_code': ts_code,
            'name': name,
            'current_price': current_price,
            'daily_change_pct': daily_change_pct,
            'comprehensive_score': comprehensive_score,
            'raw_score': raw_score,
            'dimension_scores': {
                'technical_momentum': momentum_score,
                'sentiment': sentiment_score,
            },
            'momentum_details': momentum_details,
            'sentiment_details': sentiment_details,
            'next_day_prediction': prediction,
            'risk_assessment': risk,
            'trading_plan': plan,
            'market_env': self.market_env,
            'excluded': False,
            'analysis_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }

        print(f"  ✅ 综合评分: {comprehensive_score:.1f}, "
              f"高开概率: {prediction['high_open_probability']:.1f}%")

        return result


# =========================================================================
# CLI 入口
# =========================================================================

def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(description='超短线尾盘分析器 v9.0')
    parser.add_argument('--top', type=int, default=5, help='返回前N名推荐股票')
    parser.add_argument('--workers', type=int, default=4, help='并行线程数')
    parser.add_argument('--min-liquidity', type=float, default=10_000_000,
                        help='最小流动性（元）')
    parser.add_argument('--hot-limit', type=int, default=300, help='热榜数量限制')
    parser.add_argument('--no-minute-data', action='store_true',
                        help='禁用分钟数据')
    parser.add_argument('--cron', action='store_true',
                        help='Cron模式：stdout仅输出紧凑JSON摘要')

    args = parser.parse_args()

    if not args.cron:
        print("=" * 80)
        print("超短线尾盘分析器 v9.0 — 两维度精简版")
        print(f"启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 80)

    # 初始化配置
    config = Config()
    errors = config.validate()
    if errors:
        for e in errors:
            print(f"❌ 配置错误: {e}")
        sys.exit(1)

    # 创建编排器（覆盖流动性参数）
    config.DEFAULT_MIN_LIQUIDITY = args.min_liquidity

    orchestrator = TailAnalysisOrchestrator(config)

    # 运行分析
    recommendations = orchestrator.run(
        top_n=args.top,
        hot_limit=args.hot_limit,
        max_workers=args.workers,
        use_minute_data=not args.no_minute_data,
    )

    # 生成报告
    report = orchestrator.reporter.format_human(
        recommendations, orchestrator.market_env
    )

    # 保存报告
    config.REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_file = config.REPORT_DIR / f"ultra_short_tail_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(report)

    # 反馈闭环
    feedback_file = None
    weights = None
    try:
        from dss.optimization_engine.feedback_recorder import FeedbackRecorder
        recorder = FeedbackRecorder(data_dir=str(config.FEEDBACK_DIR))
        feedback_file = recorder.record_recommendations(
            recommendations,
            weights={'technical_momentum': config.MOMENTUM_WEIGHT,
                     'sentiment': config.SENTIMENT_WEIGHT},
        )
    except Exception:
        pass

    # 输出
    if args.cron:
        cron_json = orchestrator.reporter.format_cron_json(
            recommendations, orchestrator.market_env,
            str(report_file), feedback_file, weights,
        )
        print(cron_json)
    else:
        print("\n" + report)
        print(f"\n报告已保存: {report_file}")
        if weights:
            print(f"\n[Feedback] 使用权重: {weights}")
        if feedback_file:
            print(f"[Feedback] 反馈数据已记录: {feedback_file}")


if __name__ == '__main__':
    main()
