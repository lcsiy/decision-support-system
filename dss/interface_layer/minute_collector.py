#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分钟数据采集器 v9.0 — 重构版。

v9 变更:
- 移除硬编码 Token → 使用 TushareClient(config)
- 移除重复的热榜逻辑 → 使用 HotStockProvider
- 移除手动 CSV I/O → 使用 MinuteDataRepository
- 移除手动流动性过滤 → 使用 StockFilter

功能：
1. 获取热榜股票（今日空则智能回溯）
2. 每分钟批量获取所有股票实时价格
3. 保存到CSV文件（通过 MinuteDataRepository）
4. 支持按交易时间段或指定分钟数运行
"""

import sys
import os
import time
import argparse
import traceback
from datetime import datetime, timedelta
from typing import List, Dict

# 修复 Windows 控制台编码
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# 添加项目根目录到路径
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from dss.config import Config
from dss.data_layer.tushare_client import TushareClient
from dss.data_layer.hot_stock_provider import HotStockProvider, HotStock
from dss.data_layer.minute_data_repo import MinuteDataRepository
from dss.data_layer.stock_filter import StockFilter, FilterConfig


class MinuteCollector:
    """
    分钟数据采集器 v9.0。

    使用注入的 TushareClient、HotStockProvider 和 MinuteDataRepository，
    不再直接调用 tushare 或硬编码 token。

    使用方式:
        config = Config()
        collector = MinuteCollector(config)
        collector.run_for_session('afternoon')
    """

    def __init__(self, config: Config):
        """
        Args:
            config: 系统配置对象
        """
        self.config = config

        # 数据层
        self.client = TushareClient(config)
        self.stock_filter = StockFilter(FilterConfig(
            exclude_prefixes=['688', '300', '8'],
            exclude_st=False,  # 采集阶段不过滤 ST，仅排除市场
        ))
        self.hot_stocks = HotStockProvider(self.client, self.stock_filter)
        self.minute_repo = MinuteDataRepository(config.MINUTE_DATA_DIR)

        # 状态
        self.stock_list: List[HotStock] = []
        self.is_running = False
        self.total_updates = 0
        self.successful_updates = 0

        # 验证白名单
        self._watchlist: List[Dict[str, str]] = []

        print("=" * 80)
        print("分钟数据采集器 v9.0")
        print(f"数据目录: {config.MINUTE_DATA_DIR}")
        print("=" * 80)

    # =====================================================================
    # 公共接口
    # =====================================================================

    def refresh_stock_list(self, limit: int = 300) -> bool:
        """
        刷新股票列表（热榜 + 验证白名单）。

        Returns:
            True 表示刷新成功
        """
        print("刷新股票列表...")

        # 加载验证白名单
        self._watchlist = self.minute_repo.load_verification_watchlist()
        if self._watchlist:
            print(f"📋 验证白名单: {len(self._watchlist)} 只股票（强制采集）")
            for ws in self._watchlist:
                print(f"   📌 {ws['name']} ({ws['ts_code']})")

        # 获取热榜
        stocks = self.hot_stocks.get_hot_stocks(limit=limit, filter_st=False)
        if not stocks:
            print("❌ 无法获取股票列表")
            return False

        # 合并白名单（去重）
        existing_codes = {s.ts_code for s in stocks}
        for ws in self._watchlist:
            if ws['ts_code'] not in existing_codes:
                stocks.append(HotStock(
                    ts_code=ws['ts_code'],
                    name=ws['name'],
                    hot=0,
                    rank=len(stocks) + 1,
                ))
                existing_codes.add(ws['ts_code'])

        self.stock_list = stocks
        print(f"股票列表刷新完成: {len(self.stock_list)} 只")
        self._print_top_stocks(20)
        return True

    def run_for_minutes(self, minutes: int = 120) -> None:
        """
        运行指定分钟数的数据采集。

        Args:
            minutes: 运行分钟数
        """
        print(f"开始运行数据采集，时长: {minutes} 分钟")
        print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        if not self.refresh_stock_list():
            print("❌ 股票列表初始化失败")
            return

        self.is_running = True
        end_time = datetime.now() + timedelta(minutes=minutes)
        update_interval = 60

        try:
            while self.is_running and datetime.now() < end_time:
                current_time = datetime.now()
                print(f"\n[{current_time.strftime('%H:%M:%S')}] "
                      f"第 {self.total_updates + 1} 次更新...")

                success = self._update_and_save()
                if not success:
                    print("⚠️ 本轮更新失败")

                wait_seconds = (current_time + timedelta(seconds=update_interval)
                                - datetime.now()).total_seconds()
                if wait_seconds > 0:
                    print(f"等待 {wait_seconds:.1f} 秒后下次更新...")
                    time.sleep(wait_seconds)
                else:
                    print("⚠️ 更新耗时过长，立即开始下一次更新")

        except KeyboardInterrupt:
            print("\n用户中断，停止数据采集")
        except Exception as e:
            print(f"❌ 数据采集异常: {e}")
            traceback.print_exc()
        finally:
            self.is_running = False
            self._print_summary()

    def run_for_session(self, session: str = 'afternoon') -> None:
        """
        按交易时间段运行。

        Args:
            session: 'morning' (9:30-11:30) 或 'afternoon' (13:00-15:00)
        """
        now = datetime.now()

        if session == 'morning':
            start_h, start_m, end_h, end_m = 9, 30, 11, 30
        elif session == 'afternoon':
            start_h, start_m, end_h, end_m = 13, 0, 15, 0
        else:
            print(f"❌ 未知的交易时间段: {session}")
            return

        # 等待开盘
        target_start = now.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
        if now < target_start:
            wait = (target_start - now).total_seconds()
            print(f"等待 {wait:.0f} 秒直到 {start_h:02d}:{start_m:02d}...")
            time.sleep(wait)

        # 计算剩余分钟数
        target_end = now.replace(hour=end_h, minute=end_m, second=0, microsecond=0)
        if datetime.now() > target_end:
            print(f"❌ {session} 交易时间已结束")
            return

        minutes_left = max(1, int((target_end - datetime.now()).total_seconds() / 60))
        print(f"{session} 交易时间段: {start_h:02d}:{start_m:02d}-{end_h:02d}:{end_m:02d}")
        print(f"剩余时间: {minutes_left} 分钟")

        self.run_for_minutes(minutes_left)

    # =====================================================================
    # 内部
    # =====================================================================

    def _update_and_save(self) -> bool:
        """更新分钟数据并保存"""
        if not self.stock_list:
            print("⚠️ 股票列表为空")
            return False

        codes = [s.ts_code for s in self.stock_list]
        print(f"批量获取 {len(codes)} 只股票的实时数据...")

        try:
            # 逐个获取（tushare get_realtime_quotes 批量限制）
            codes_short = [c.replace('.SH', '').replace('.SZ', '') for c in codes]
            df = self.client.get_realtime_quotes(codes_short)

            if df is None or df.empty:
                print("❌ 批量获取返回空数据")
                return False

            print(f"✅ 成功获取 {len(df)} 条实时数据")

            if 'time' in df.columns:
                unique_times = df['time'].unique()
                if len(unique_times) > 0:
                    print(f"数据时间: {unique_times[:3]}"
                          f"{'...' if len(unique_times) > 3 else ''}")

            success_count = 0
            now = datetime.now()
            today = now.strftime('%Y%m%d')

            for stock in self.stock_list:
                try:
                    code_short = stock.ts_code.replace('.SH', '').replace('.SZ', '')
                    stock_rows = df[df['code'] == code_short]

                    if stock_rows.empty:
                        continue

                    row = stock_rows.iloc[0]
                    price = float(row.get('price', 0))
                    volume = int(float(row.get('volume', 0)))

                    if price <= 0 or volume <= 0:
                        continue

                    time_str = str(row.get('time', '')) or now.strftime('%H:%M:%S')

                    record = {
                        'timestamp': now.strftime('%Y-%m-%d %H:%M:%S'),
                        'price': price,
                        'open': float(row.get('open', 0)),
                        'pre_close': float(row.get('pre_close', 0)),
                        'high': float(row.get('high', 0)),
                        'low': float(row.get('low', 0)),
                        'volume': volume,
                        'amount': float(row.get('amount', 0)),
                        'changepercent': float(row.get('changepercent', 0)),
                        'time': time_str,
                    }

                    self.minute_repo.append_snapshot(today, stock.ts_code, record)
                    success_count += 1

                except Exception as e:
                    print(f"  ❌ 处理 {stock.ts_code} 数据失败: {e}")

            print(f"分钟数据更新完成: {success_count}/{len(self.stock_list)} 成功")
            self.total_updates += 1
            self.successful_updates += success_count

            return success_count > 0

        except Exception as e:
            print(f"❌ 更新分钟数据异常: {e}")
            traceback.print_exc()
            return False

    def _print_top_stocks(self, n: int = 20) -> None:
        """打印前 N 只股票"""
        print("股票列表前20:")
        for i, s in enumerate(self.stock_list[:n], 1):
            print(f"  {i:2d}. {s.name} ({s.ts_code})")
        if len(self.stock_list) > n:
            print(f"  ... 共 {len(self.stock_list)} 只")

    def _print_summary(self) -> None:
        """打印采集摘要"""
        print(f"\n数据采集结束")
        print(f"总更新次数: {self.total_updates}")
        print(f"成功数据点: {self.successful_updates}")


# =========================================================================
# CLI 入口
# =========================================================================

def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(description='分钟数据采集器 v9.0')
    parser.add_argument('--session', type=str, choices=['morning', 'afternoon'],
                        help='交易时间段: morning(9:30-11:30) / afternoon(13:00-15:00)')
    parser.add_argument('--minutes', type=int, default=120,
                        help='运行分钟数（默认120）')
    parser.add_argument('--limit', type=int, default=300,
                        help='股票数量限制（默认300）')

    args = parser.parse_args()

    print("=" * 80)
    print("分钟数据采集器 v9.0")
    print(f"启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"股票限制: {args.limit} 只")
    print("=" * 80)

    config = Config()
    errors = config.validate()
    if errors:
        for e in errors:
            print(f"❌ 配置错误: {e}")
        sys.exit(1)

    collector = MinuteCollector(config)

    try:
        if args.session:
            collector.run_for_session(args.session)
        else:
            collector.run_for_minutes(args.minutes)
    except KeyboardInterrupt:
        print("\n程序被用户中断")
    except Exception as e:
        print(f"❌ 主程序异常: {e}")
        traceback.print_exc()


if __name__ == '__main__':
    main()
