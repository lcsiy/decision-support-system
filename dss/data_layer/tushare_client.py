#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tushare 数据客户端 v11.0 — DSS 数据层统一入口。

v11 变更 (解耦):
- 不再依赖 TradingAgents 项目；数据获取全部由本 skill 自包含实现
  (dss.data_layer.tushare_vendor)，token 取自本项目 .env 的 TUSHARE_TOKEN
- 保留 DSS 特有的实时行情 / 分钟数据方法
- 接口签名与 v10 完全一致 (调用方零改动)

积分要求：所有接口 ≤ 6000 积分
"""

import sys
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Set, Tuple

import pandas as pd

from dss.config import Config
from dss.data_layer.tushare_vendor import (
    get_tushare_daily_df,
    get_tushare_batch_daily,
    get_tushare_ths_hot,
    get_tushare_st_list,
    get_tushare_limit_list,
    get_tushare_moneyflow,
    get_tushare_index_daily,
    get_tushare_trade_cal,
    get_tushare_stock_basic,
    _to_ts_code,
)

# 修复 Windows 控制台编码（emoji 在 GBK 下会崩溃）
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


class TushareClient:
    """
    Tushare 数据客户端 v11 — 自包含实现（tushare_vendor 模块）。

    使用方式 (与 v9/v10 完全兼容):
        config = Config()
        client = TushareClient(config)
        df = client.ths_hot(trade_date='20260101')
    """

    def __init__(self, config: Config):
        """
        Args:
            config: 系统配置对象 (保留用于未来非 tushare 配置项)
        """
        token = config.TUSHARE_TOKEN
        if not token:
            raise ValueError(
                "TUSHARE_TOKEN 未设置。请在 .env 文件中设置 TUSHARE_TOKEN=your_token"
            )
        self._config = config
        self._api_calls = 0

    # =====================================================================
    # 股票基础信息
    # =====================================================================

    def stock_basic(self, list_status: str = 'L') -> Optional[pd.DataFrame]:
        """获取股票基础信息列表 (自包含实现)"""
        df = get_tushare_stock_basic(list_status=list_status)
        self._api_calls += 1
        return df if not df.empty else None

    def stock_st(self, trade_date: str = None) -> Optional[pd.DataFrame]:
        """获取 ST 股票列表"""
        if trade_date is None:
            trade_date = datetime.now().strftime('%Y%m%d')
        st_set = get_tushare_st_list(trade_date)
        self._api_calls += 1
        if not st_set:
            return None
        # Return as DataFrame for backward compatibility
        return pd.DataFrame({"ts_code": sorted(st_set)})

    # =====================================================================
    # 行情数据
    # =====================================================================

    def daily(self, ts_code: str = None, trade_date: str = None,
              start_date: str = None, end_date: str = None,
              limit: int = None) -> Optional[pd.DataFrame]:
        """获取日线行情"""
        # 全市场查询（无 ts_code）→ 直接调 tushare SDK
        if ts_code is None and trade_date is not None:
            try:
                import tushare as ts
                token = self._config.TUSHARE_TOKEN
                ts.set_token(token)
                pro = ts.pro_api()
                df = pro.daily(trade_date=trade_date, limit=limit or 6000)
                self._api_calls += 1
                return df
            except Exception as e:
                print(f"  [SDK] daily(all) 失败: {e}")
                return None

        code = _to_ts_code(ts_code) if ts_code else None
        if code is None:
            return None
        df = get_tushare_daily_df(code, start_date, end_date, with_ma=False)
        self._api_calls += 1
        return df if not df.empty else None

    def get_realtime_quotes(self, codes: List[str]) -> Optional[pd.DataFrame]:
        """
        获取实时行情数据（分钟级采集专用）。

        tushare 虽标记 get_realtime_quotes 为 deprecated，但接口仍可用。
        这是分钟数据采集器的核心数据源，暂无替代接口。

        Args:
            codes: 股票代码列表 (e.g. ['000001', '000002'])——不含后缀

        Returns:
            DataFrame 或 None
        """
        try:
            import tushare as ts
            token = self._config.TUSHARE_TOKEN
            ts.set_token(token)
            df = ts.get_realtime_quotes(codes)
            self._api_calls += 1
            if df is not None and not df.empty:
                return df
        except Exception as e:
            print(f"  [realtime] get_realtime_quotes 失败: {e}")
        return None

    # =====================================================================
    # 资金流向
    # =====================================================================

    def moneyflow(self, ts_code: str, trade_date: str = None,
                  start_date: str = None, end_date: str = None,
                  limit: int = None) -> Optional[pd.DataFrame]:
        """获取个股资金流向"""
        code = _to_ts_code(ts_code) if ts_code else ts_code
        df = get_tushare_moneyflow(code, start_date, end_date)
        self._api_calls += 1
        return df if not df.empty else None

    def moneyflow_mkt_dc(self, trade_date: str = None) -> Optional[pd.DataFrame]:
        """获取大盘资金流向 (DC) — 暂保留直接调用 (接口低频)"""
        if trade_date is None:
            trade_date = datetime.now().strftime('%Y%m%d')
        try:
            import tushare as ts
            token = self._config.TUSHARE_TOKEN
            ts.set_token(token)
            pro = ts.pro_api()
            df = pro.moneyflow_mkt_dc(trade_date=trade_date)
            self._api_calls += 1
            return df
        except Exception as e:
            print(f"  [SDK] moneyflow_mkt_dc 失败: {e}")
            return None

    # =====================================================================
    # 热榜 / 情绪 / 涨跌停
    # =====================================================================

    def ths_hot(self, trade_date: str = None, market: str = '热股') -> Optional[pd.DataFrame]:
        """获取同花顺热榜数据 (自包含实现)"""
        df = get_tushare_ths_hot(trade_date, market)
        self._api_calls += 1
        return df if not df.empty else None

    def limit_list_d(self, trade_date: str = None, limit: int = None) -> Optional[pd.DataFrame]:
        """获取涨跌停列表 (自包含实现)"""
        df = get_tushare_limit_list(trade_date)
        self._api_calls += 1
        return df if not df.empty else None

    # =====================================================================
    # 指数数据
    # =====================================================================

    def index_daily(self, ts_code: str = None, trade_date: str = None,
                    start_date: str = None, end_date: str = None,
                    limit: int = None) -> Optional[pd.DataFrame]:
        """获取指数日线行情 (自包含实现)。

        注意: tushare 返回降序（最新在前），此处统一按 trade_date 升序排序，
        保证调用方用 iloc[-1] 取到的是最新一天（曾因此取到 1993 年数据）。
        """
        code = ts_code or '000001.SH'
        df = get_tushare_index_daily(code, start_date=start_date, end_date=end_date, trade_date=trade_date)
        if df is not None and not df.empty and 'trade_date' in df.columns:
            df = df.sort_values('trade_date').reset_index(drop=True)
        self._api_calls += 1
        return df if not df.empty else None

    _INDEX_REALTIME_CODES = {
        'sh000001': '上证指数',
        'sz399001': '深证成指',
        'sz399006': '创业板指',
    }

    def get_intraday_index(self, codes: List[str] = None) -> Optional[pd.DataFrame]:
        """盘中实时指数行情（与分钟采集器同通道，get_realtime_quotes）。

        指数代码需带交易所前缀: sh000001 / sz399001 / sz399006。
        失败返回 None，不抛异常。
        """
        codes = codes or list(self._INDEX_REALTIME_CODES.keys())
        return self.get_realtime_quotes(codes)

    def get_intraday_index_change(self, code: str = 'sh000001') -> Tuple[Optional[float], Optional[float]]:
        """返回 (实时点位, 当日涨跌幅%)；失败返回 (None, None)。"""
        try:
            df = self.get_realtime_quotes([code])
            if df is None or df.empty:
                return None, None
            row = df.iloc[0]
            price = self.safe_float(row, ['price', 'current', 'close', 'last', 'trade', '最新价'])
            pre_close = self.safe_float(row, ['pre_close', 'prev_close', 'yest_close', '昨收'])
            if price <= 0 or pre_close <= 0:
                return None, None
            change_pct = (price - pre_close) / pre_close * 100
            return price, change_pct
        except Exception:
            return None, None

    # =====================================================================
    # 批量获取
    # =====================================================================

    def batch_daily(self, ts_codes: List[str], start_date: str = None,
                    end_date: str = None) -> Dict[str, pd.DataFrame]:
        """批量获取日线数据 (自包含实现)"""
        tushare_codes = [_to_ts_code(c) for c in ts_codes]
        results = get_tushare_batch_daily(tushare_codes, start_date, end_date)
        self._api_calls += len(tushare_codes)
        return results

    def batch_moneyflow(self, ts_codes: List[str], days: int = 30) -> Dict[str, pd.DataFrame]:
        """批量获取资金流向数据"""
        results: Dict[str, pd.DataFrame] = {}
        if days:
            end_date = datetime.now().strftime('%Y%m%d')
            start_date = (datetime.now() - timedelta(days=days)).strftime('%Y%m%d')
        else:
            end_date = None
            start_date = None
        for code in ts_codes:
            tsc = _to_ts_code(code)
            df = get_tushare_moneyflow(tsc, start_date, end_date)
            self._api_calls += 1
            if not df.empty:
                results[code] = df
        return results

    # =====================================================================
    # v9 辅助方法 (保留, DSS 特有逻辑)
    # =====================================================================

    def get_st_set(self, trade_date: str = None) -> Set[str]:
        """获取当日 ST 股票集合"""
        return get_tushare_st_list(trade_date)

    def batch_fetch_realtime(self, stock_codes: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        批量获取实时行情数据（分批调用，每批最多 500 只避免 HTTP 431）。

        tushare 虽标记 get_realtime_quotes 为 deprecated，但接口仍可用。
        调用方 swing_screener 优先使用实时数据，fallback 到日线。
        """
        if not stock_codes:
            return {}

        results: Dict[str, Dict[str, Any]] = {}
        batch_size = 500  # 避免请求 URL 过长导致 HTTP 431

        for i in range(0, len(stock_codes), batch_size):
            batch = stock_codes[i:i + batch_size]
            codes_short = [c.replace('.SH', '').replace('.SZ', '') for c in batch]
            try:
                df = self.get_realtime_quotes(codes_short)
                if df is None or df.empty:
                    continue
                for sc in batch:
                    short = sc.replace('.SH', '').replace('.SZ', '')
                    rows = df[df['code'] == short]
                    if not rows.empty:
                        results[sc] = rows.iloc[0].to_dict()
            except Exception:
                continue

        return results

    def get_market_environment(self) -> Dict[str, Any]:
        """获取大盘环境评估 (自包含实现)"""
        env: Dict[str, Any] = {
            'available': False,
            'sh_index_change': 0.0,
            'sz_index_change': 0.0,
            'market_sentiment': 'neutral',
            'market_multiplier': 1.0,
        }

        def _is_trading_session() -> bool:
            """A 股交易时段 9:30-11:30, 13:00-15:00。"""
            now = datetime.now()
            if now.weekday() >= 5:
                return False
            t = now.hour * 60 + now.minute
            return (9*60+30 <= t <= 11*60+30) or (13*60 <= t <= 15*60)

        def _get_index_change_daily(code: str) -> Tuple[float, str]:
            df = get_tushare_index_daily(code, end_date=datetime.now().strftime('%Y%m%d'))
            used_date = ""
            if not df.empty:
                used_date = str(df.iloc[-1].get('trade_date', ''))
            if df.empty:
                prev = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')
                df = get_tushare_index_daily(code, trade_date=prev)
                if not df.empty:
                    used_date = str(df.iloc[-1].get('trade_date', ''))
            if not df.empty:
                for col in df.columns:
                    cl = col.lower()
                    if 'pct' in cl or 'chg' in cl:
                        return float(df.iloc[-1][col]), used_date
            return 0.0, used_date

        try:
            data_source = 'daily'
            used_trade_date = ''

            # 盘中 → 优先实时指数（get_realtime_quotes 同通道，已验证可用）
            if _is_trading_session():
                sh_price, sh_chg = self.get_intraday_index_change('sh000001')
                if sh_price is not None:
                    data_source = 'realtime'
                    used_trade_date = datetime.now().strftime('%Y%m%d')
                    env['sh_index_change'] = round(sh_chg or 0.0, 2)
                    env['sz_index_change'] = round(self.get_intraday_index_change('sz399001')[1] or 0.0, 2)
                    env['available'] = True

            if not env['available']:
                env['sh_index_change'], used_sh = _get_index_change_daily('000001.SH')
                env['sz_index_change'], _ = _get_index_change_daily('399001.SZ')
                env['available'] = True
                used_trade_date = used_sh

            env['data_source'] = data_source
            env['used_trade_date'] = used_trade_date
            mc = env['sh_index_change']

            if mc > 1.0:
                env['market_sentiment'] = 'bullish'
                env['market_multiplier'] = 1.05
            elif mc > 0.3:
                env['market_sentiment'] = 'slightly_bullish'
                env['market_multiplier'] = 1.02
            elif mc > -0.5:
                env['market_sentiment'] = 'neutral'
                env['market_multiplier'] = 1.0
            elif mc > -2.0:
                env['market_sentiment'] = 'slightly_bearish'
                env['market_multiplier'] = 0.95
            else:
                env['market_sentiment'] = 'bearish'
                env['market_multiplier'] = 0.88
        except Exception as e:
            print(f"  ⚠️ 大盘环境获取失败: {e}")

        return env

    @staticmethod
    def _detect_code_column(df: pd.DataFrame) -> Optional[str]:
        """检测 DataFrame 中的股票代码列名"""
        for col in df.columns:
            cl = col.lower()
            if 'code' in cl or 'ts_code' in cl or '代码' in col:
                return col
        return None

    # =====================================================================
    # 工具方法
    # =====================================================================

    @property
    def api_calls(self) -> int:
        return self._api_calls

    @staticmethod
    def days_ago_str(days: int) -> str:
        return (datetime.now() - timedelta(days=days)).strftime('%Y%m%d')

    @staticmethod
    def today_str() -> str:
        return datetime.now().strftime('%Y%m%d')

    @staticmethod
    def extract_price(realtime_data: Dict[str, Any]) -> Tuple[float, float]:
        """从实时行情数据提取当前价和前收盘价"""
        current_price = 0.0
        pre_close = 0.0
        if realtime_data is None:
            return current_price, pre_close
        for field in ['price', 'current', 'close', 'last', 'trade', '最新价']:
            if field in realtime_data:
                try:
                    val = float(realtime_data[field])
                    if val > 0:
                        current_price = val
                        break
                except (ValueError, TypeError):
                    continue
        for field in ['pre_close', 'prev_close', 'yest_close', '昨收']:
            if field in realtime_data:
                try:
                    val = float(realtime_data[field])
                    if val > 0:
                        pre_close = val
                        break
                except (ValueError, TypeError):
                    continue
        return current_price, pre_close

    @staticmethod
    def safe_float(row: Dict[str, Any], fields: List[str]) -> float:
        """安全提取浮点数"""
        for f in fields:
            val = row.get(f, 0)
            if val is None:
                continue
            try:
                return float(val)
            except (ValueError, TypeError):
                pass
        return 0.0

    # ---- 短线交易辅助方法 ----

    def daily_with_ma(
        self, ts_code: str, start_date: str = None, end_date: str = None,
        ma_periods: list = None,
    ) -> pd.DataFrame:
        """获取日K线+均线 (自包含实现)"""
        if ma_periods is None:
            ma_periods = [5, 10, 20, 60]
        if start_date is None:
            start_date = self.days_ago_str(120)
        if end_date is None:
            end_date = self.today_str()
        code = _to_ts_code(ts_code)
        df = get_tushare_daily_df(code, start_date, end_date, with_ma=True, ma_periods=tuple(ma_periods))
        self._api_calls += 1
        return df

    def batch_daily_with_ma(
        self, ts_codes: List[str], start_date: str = None, end_date: str = None,
        ma_periods: list = None,
    ) -> Dict[str, pd.DataFrame]:
        """批量获取日K线+均线 (自包含实现)"""
        if ma_periods is None:
            ma_periods = [5, 10, 20, 60]
        tushare_codes = [_to_ts_code(c) for c in ts_codes]
        results = get_tushare_batch_daily(
            tushare_codes, start_date, end_date,
            with_ma=True, ma_periods=tuple(ma_periods),
        )
        self._api_calls += len(ts_codes)
        return results

    def trade_cal(self, exchange: str = 'SSE', start_date: str = None,
                  end_date: str = None) -> Dict[str, bool]:
        """获取交易日历 (自包含实现)"""
        return get_tushare_trade_cal(exchange, start_date, end_date)
