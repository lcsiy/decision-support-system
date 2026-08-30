"""
短线股票预筛选器 — 多阶段筛选流水线。

筛选顺序: ST股票 → 价格区间 → 流动性(成交额) → 涨跌停
"""

from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Set
import pandas as pd
from dss.config import Config
from dss.data_layer.tushare_client import TushareClient
from dss.data_layer.stock_filter import StockFilter, FilterConfig


@dataclass
class ScreenResult:
    """单只股票筛选结果"""
    passed: bool
    ts_code: str
    name: str = ""
    current_price: float = 0.0
    daily_change_pct: float = 0.0
    amount: float = 0.0
    exclude_reason: str = ""


class SwingScreener:
    """
    短线预筛选器：从全市场选出可分析的候选股票。

    筛选流程：
    1. 获取全市场股票基础信息
    2. ST过滤（StockFilter）
    3. 价格区间过滤
    4. 流动性过滤（每日成交额）
    5. 涨跌停过滤
    """

    def __init__(self, config: Config, tushare: TushareClient):
        self.min_price = config.SWING_MIN_PRICE
        self.max_price = config.SWING_MAX_PRICE
        self.min_amount = config.SWING_MIN_DAILY_AMOUNT
        self.tushare = tushare
        self.stock_filter = StockFilter(FilterConfig(
            exclude_prefixes=config.EXCLUDE_MARKETS,
        ))

    def screen(self, trade_date: str = None, limit: int = 200) -> List[ScreenResult]:
        """
        执行全市场预筛选。

        Args:
            trade_date: 交易日期 YYYYMMDD
            limit: 候选数量上限

        Returns:
            通过筛选的股票列表
        """
        print(f"\n{'=' * 50}")
        print("短线预筛选")
        print(f"{'=' * 50}")

        # 1. 获取全市场股票
        print("获取股票基础信息...")
        df_basic = self.tushare.stock_basic()
        if df_basic is None or df_basic.empty:
            print("❌ 无法获取股票列表")
            return []

        # 仅保留沪深A股
        df_basic = df_basic[df_basic['ts_code'].str.endswith(('.SH', '.SZ'))]
        print(f"全市场股票: {len(df_basic)} 只")

        # 2. ST过滤
        st_set = self.tushare.get_st_set(trade_date)
        df_basic = df_basic[~df_basic['ts_code'].isin(st_set)]
        # ST名称过滤
        df_basic = df_basic[~df_basic.get('name', pd.Series()).str.contains('ST', na=False)]
        # 排除创业板、科创板、北交所
        exclude = self.stock_filter.config.exclude_prefixes
        for prefix in exclude:
            df_basic = df_basic[~df_basic['ts_code'].str.startswith(prefix)]
        print(f"ST/板块过滤后: {len(df_basic)} 只")

        # 3. 获取当日行情（实时优先 → 日线兜底）
        print("获取当日行情...")
        realtime = self.tushare.batch_fetch_realtime(df_basic['ts_code'].tolist())
        using_realtime = bool(realtime)
        if realtime:
            print(f"  ✅ 实时行情: {len(realtime)} 只")
            actual_date = trade_date
        else:
            realtime, actual_date = self._fallback_daily_prices(
                df_basic['ts_code'].tolist(), trade_date
            )
            date_label = "今天" if actual_date == trade_date else actual_date
            if realtime:
                print(f"  ✅ 日线行情: {len(realtime)} 只 (日期: {date_label})")
            else:
                print("  ❌ 无法获取价格数据")
        if not realtime:
            realtime_df = pd.DataFrame()
        else:
            realtime_df = pd.DataFrame.from_dict(realtime, orient='index')

        # 4. 逐条筛选
        results = []
        for _, row in df_basic.iterrows():
            ts_code = row['ts_code']
            name = row.get('name', '')
            reason = self._check_basic(row, realtime.get(ts_code, {}))
            if reason:
                continue

            # 提取价格和金额
            rt = realtime.get(ts_code, {})
            price = self._extract_price(rt)
            amount = self._extract_amount(rt)

            results.append(ScreenResult(
                passed=True,
                ts_code=ts_code,
                name=name,
                current_price=price,
                amount=amount,
            ))

            if len(results) >= limit:
                break

        print(f"最终候选: {len(results)} 只")
        return results

    def _check_basic(self, basic_row: pd.Series,
                     realtime_data: Dict[str, Any]) -> Optional[str]:
        """检查单只股票是否通过基础筛选"""
        price = self._extract_price(realtime_data)
        amount = self._extract_amount(realtime_data)

        # 价格过滤
        if price <= 0:
            return "无价格"
        if price < self.min_price:
            return f"价格过低({price:.2f}<{self.min_price})"
        if price > self.max_price:
            return f"价格过高({price:.2f}>{self.max_price})"

        # 流动性过滤
        if 0 < amount < self.min_amount:
            return f"流动性不足({amount:.0f}<{self.min_amount:.0f})"

        # 涨跌停检查
        pre_close = self._extract_preclose(realtime_data)
        if pre_close > 0:
            change_pct = (price - pre_close) / pre_close * 100
            if change_pct >= 9.5:
                return "涨停"
            if change_pct <= -9.5:
                return "跌停"

        return None

    @staticmethod
    def _extract_price(data: Dict[str, Any]) -> float:
        """从实时数据提取价格"""
        for field in ['price', 'current', 'close', 'last', 'trade', '最新价']:
            if field in data:
                try:
                    val = float(data[field])
                    if val > 0:
                        return val
                except (ValueError, TypeError):
                    continue
        return 0.0

    @staticmethod
    def _extract_amount(data: Dict[str, Any]) -> float:
        """从实时数据提取成交额"""
        for field in ['amount', '成交额']:
            if field in data:
                try:
                    val = float(data[field])
                    if val > 0:
                        return val
                except (ValueError, TypeError):
                    continue
        return 0.0

    def _fallback_daily_prices(
        self, ts_codes: List[str], trade_date: str | None
    ) -> tuple:
        """返回 (价格字典, 实际数据日期)。

        从 ``trade_date`` 往前回溯最多 10 天，找到最近有数据的交易日。
        14:30 运行时，今天的日线可能还没入库 → 回退到昨天，但会标注入库日期。
        """
        from datetime import datetime, timedelta

        if trade_date is None:
            trade_date = datetime.now().strftime('%Y%m%d')

        for days_back in range(10):
            check_date = (datetime.strptime(trade_date, '%Y%m%d') - timedelta(days=days_back)).strftime('%Y%m%d')
            try:
                df = self.tushare.daily(trade_date=check_date)
                if df is not None and not df.empty:
                    code_set = set(ts_codes)
                    df_filtered = df[df['ts_code'].isin(code_set)]
                    results: Dict[str, Dict[str, Any]] = {}
                    for _, row in df_filtered.iterrows():
                        code = str(row.get('ts_code', ''))
                        close = float(row.get('close', 0))
                        raw_amount = float(row.get('amount', 0))
                        amount = raw_amount * 1000  # 千元 → 元
                        results[code] = {
                            'price': close,
                            'amount': amount,
                            'pre_close': float(row.get('pre_close', close)),
                            'pct_chg': float(row.get('pct_chg', 0)),
                        }
                    if results:
                        return results, check_date
            except Exception:
                continue

        return {}, trade_date

    @staticmethod
    def _extract_preclose(data: Dict[str, Any]) -> float:
        """提取前收盘价"""
        for field in ['pre_close', 'yest_close', '昨收']:
            if field in data:
                try:
                    val = float(data[field])
                    if val > 0:
                        return val
                except (ValueError, TypeError):
                    continue
        return 0.0
