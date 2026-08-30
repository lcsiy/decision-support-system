#!/usr/bin/env python3
"""
短线交易 CLI 入口。

使用方式:
  python -m dss.swing_cli run                  # 每日运行
  python -m dss.swing_cli run --dry-run        # 试运行（不修改池）
  python -m dss.swing_cli pool                 # 查看追踪池
  python -m dss.swing_cli pool --detail        # 详细池信息
  python -m dss.swing_cli history              # 交易历史
  python -m dss.swing_cli sell CODE --price X  # 手动标记卖出
  python -m dss.swing_cli buy CODE --price X   # 手动标记买入
"""

import sys
import os
import argparse
from datetime import datetime

# 确保项目根在 sys.path 中
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from dss.config import Config
from dss.data_layer.tushare_client import TushareClient
from dss.analysis_engine.swing_trend import SwingTrendAnalyzer
from dss.analysis_engine.swing_momentum import SwingMomentumAnalyzer
from dss.analysis_engine.swing_volume import SwingVolumeAnalyzer
from dss.analysis_engine.swing_risk import SwingRiskAnalyzer
from dss.analysis_engine.swing_composite import SwingCompositeScorer
from dss.decision_core.swing_screener import SwingScreener
from dss.decision_core.swing_pool import SwingPool, SwingSellSignal
from dss.decision_core.swing_plan import SwingTradePlan
from dss.optimization_engine.swing_recorder import SwingRecorder
from dss.interface_layer.swing_orchestrator import SwingOrchestrator
from dss.interface_layer.swing_report import SwingReportFormatter


def build_orchestrator(config: Config) -> SwingOrchestrator:
    """构造编排器，注入所有依赖"""
    tushare = TushareClient(config)
    return SwingOrchestrator(
        config=config,
        tushare=tushare,
        screener=SwingScreener(config, tushare),
        trend_analyzer=SwingTrendAnalyzer(),
        momentum_analyzer=SwingMomentumAnalyzer(),
        volume_analyzer=SwingVolumeAnalyzer(),
        risk_analyzer=SwingRiskAnalyzer(),
        composite_scorer=SwingCompositeScorer(config),
        pool=SwingPool(config),
        sell_signal=SwingSellSignal(config),
        trade_plan=SwingTradePlan(config),
        recorder=SwingRecorder(config),
        formatter=SwingReportFormatter(),
    )


def cmd_run(args, orch: SwingOrchestrator):
    """执行每日运行"""
    trade_date = args.date if hasattr(args, 'date') and args.date else None
    dry_run = args.dry_run if hasattr(args, 'dry_run') else False

    results = orch.run_daily(trade_date=trade_date, dry_run=dry_run)

    if hasattr(args, 'json') and args.json:
        print(SwingReportFormatter.to_json(results))


def cmd_pool(args, orch: SwingOrchestrator):
    """查看追踪池状态"""
    pool = orch.pool
    entries = pool.get_active_pool()
    stats = pool.get_summary_stats()

    print(SwingReportFormatter.format_pool_status(entries, stats))

    if hasattr(args, 'detail') and args.detail and entries:
        print("\n--- 每日日志 ---")
        for entry in entries:
            print(f"\n[{entry.ts_code} {entry.name}]")
            for log in entry.daily_log:
                sig = log.get('signal', '')
                print(f"  {log['date']}  close={log['close']:.2f}  "
                      f"chg={log.get('pct_chg', 0):+.2f}%  [{sig}]")


def cmd_history(args, orch: SwingOrchestrator):
    """查看交易历史"""
    history = orch.pool.get_trade_history()
    print(SwingReportFormatter.format_history(history))


def cmd_sell(args, orch: SwingOrchestrator):
    """手动标记卖出"""
    price = args.price
    reason = args.reason if hasattr(args, 'reason') and args.reason else 'MANUAL'
    trade_date = datetime.now().strftime('%Y%m%d')

    orch.pool.execute_sell(
        ts_code=args.code.upper(),
        exit_price=price,
        reason=reason,
        trade_date=trade_date,
        confidence=100.0,
    )
    print(f"✅ 已手动卖出 {args.code.upper()} @ {price}")


def cmd_buy(args, orch: SwingOrchestrator):
    """手动标记买入"""
    price = args.price
    trade_date = datetime.now().strftime('%Y%m%d')

    orch.pool.add_to_pool(
        ts_code=args.code.upper(),
        name=args.code.upper(),
        buy_date=trade_date,
        buy_price=price,
    )
    print(f"✅ 已手动买入 {args.code.upper()} @ {price}")


def main():
    parser = argparse.ArgumentParser(
        prog='swing_cli',
        description='短线交易决策分析器 — 持仓≤10天，top3选股',
    )
    sub = parser.add_subparsers(dest='command', help='子命令')

    # run
    p_run = sub.add_parser('run', help='每日运行（审查池+选股补仓）')
    p_run.add_argument('--date', type=str, help='日期 YYYYMMDD（默认今天）')
    p_run.add_argument('--dry-run', action='store_true', help='试运行，不修改池')
    p_run.add_argument('--json', action='store_true', help='JSON 格式输出')
    p_run.set_defaults(func=cmd_run)

    # pool
    p_pool = sub.add_parser('pool', help='查看追踪池')
    p_pool.add_argument('--detail', action='store_true', help='显示每日日志')
    p_pool.set_defaults(func=cmd_pool)

    # history
    p_hist = sub.add_parser('history', help='查看交易历史')
    p_hist.set_defaults(func=cmd_history)

    # sell
    p_sell = sub.add_parser('sell', help='手动标记卖出')
    p_sell.add_argument('code', type=str, help='股票代码（如 000001.SZ）')
    p_sell.add_argument('--price', type=float, required=True, help='卖出价格')
    p_sell.add_argument('--reason', type=str, help='卖出原因')
    p_sell.set_defaults(func=cmd_sell)

    # buy
    p_buy = sub.add_parser('buy', help='手动标记买入')
    p_buy.add_argument('code', type=str, help='股票代码（如 000002.SZ）')
    p_buy.add_argument('--price', type=float, required=True, help='买入价格')
    p_buy.set_defaults(func=cmd_buy)

    args = parser.parse_args()

    if not hasattr(args, 'func'):
        parser.print_help()
        return

    config = Config()
    errors = config.validate()
    if errors:
        print(f"⚠️ 配置错误: {errors}")
        return

    orch = build_orchestrator(config)
    args.func(args, orch)


if __name__ == '__main__':
    main()
