"""
股票过滤器 - 排除有投资门槛的A股股票

功能：
1. 过滤掉需要特殊权限的股票（科创板、创业板、北交所）
2. 保留普通投资者可以交易的主板股票
3. 支持自定义过滤规则

v9 变更: 从 data_layer/ 迁移至 dss/data_layer/，作为数据层标准组件。
"""

import logging
from typing import List, Optional, Dict, Any, Set
from dataclasses import dataclass, field

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class FilterConfig:
    """股票过滤器配置"""

    # 排除的市场前缀（代码前3位）。默认: 688(科创), 300(创业), 8(北交所)
    exclude_prefixes: List[str] = field(default_factory=lambda: ['688', '300', '8'])

    # 包含的市场前缀（如果设置，则只保留这些前缀）
    include_prefixes: List[str] = field(default_factory=lambda: ['600', '000', '001', '002', '003'])

    # 最小上市天数（排除新上市的股票），0 = 不过滤
    min_list_days: int = 30

    # 排除 ST/*ST 股票
    exclude_st: bool = True

    # 最小成交额（元），0 = 不过滤
    min_amount: float = 0.0

    # 最小市值（亿元），0 = 不过滤
    min_market_cap: float = 0.0


class StockFilter:
    """
    股票过滤器 — 提供前缀过滤、ST过滤、上市日期过滤、流动性过滤。

    使用方式:
        config = FilterConfig(exclude_prefixes=['688', '300'])
        sf = StockFilter(config)
        clean = sf.filter_by_prefix(hot_stocks_df)
    """

    def __init__(self, config: Optional[FilterConfig] = None):
        self.config = config or FilterConfig()

    # ---- 热榜股票列表过滤（用于 HotStockProvider） ----

    def filter_hot_stocks(
        self,
        stocks: List[Dict[str, Any]],
        ts_code_key: str = 'ts_code',
        name_key: str = 'name',
        st_set: Optional[Set[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        对热榜股票列表应用前缀 + ST 过滤。

        Args:
            stocks: [{'ts_code': '600036.SH', 'name': '招商银行', ...}, ...]
            ts_code_key: 代码字段名
            name_key: 名称字段名
            st_set: ST 股票代码集合，None 则不过滤 ST

        Returns:
            过滤后的股票列表
        """
        filtered: List[Dict[str, Any]] = []
        seen: Set[str] = set()

        for s in stocks:
            ts_code = str(s.get(ts_code_key, '')).strip()

            # 去重
            if ts_code in seen:
                continue

            # 前缀排除
            excluded = any(
                ts_code.startswith(p) for p in self.config.exclude_prefixes
            )
            if excluded:
                continue

            # 只保留 SH/SZ 结尾的 A 股
            if not (ts_code.endswith('.SH') or ts_code.endswith('.SZ')):
                continue

            # ST 过滤
            if self.config.exclude_st and st_set and ts_code in st_set:
                continue

            # ST 名称过滤（备用）
            if self.config.exclude_st:
                name = str(s.get(name_key, '')).strip()
                if 'ST' in name:
                    continue

            seen.add(ts_code)
            filtered.append(s)

        return filtered

    # ---- DataFrame 级别过滤 ----

    def filter_by_prefix(self, df: pd.DataFrame, ts_code_col: str = 'ts_code') -> pd.DataFrame:
        """根据股票代码前缀过滤 DataFrame"""
        if df.empty:
            return df

        df = df.copy()
        df['_prefix'] = df[ts_code_col].str[:3]

        if self.config.include_prefixes:
            df = df[df['_prefix'].isin(self.config.include_prefixes)]

        if self.config.exclude_prefixes:
            df = df[~df['_prefix'].isin(self.config.exclude_prefixes)]

        df = df.drop(columns=['_prefix'], errors='ignore')
        return df

    def filter_st_stocks(self, df: pd.DataFrame, name_col: str = 'name') -> pd.DataFrame:
        """过滤 ST/*ST 股票"""
        if df.empty or not self.config.exclude_st or name_col not in df.columns:
            return df
        return df[~df[name_col].str.contains(r'ST|\*ST', na=False)]

    def filter_by_liquidity(
        self, df: pd.DataFrame, amount_col: str = 'amount'
    ) -> pd.DataFrame:
        """
        根据成交额过滤。

        注意：Tushare Pro 的 amount 字段单位是千元。
        """
        if df.empty or self.config.min_amount <= 0 or amount_col not in df.columns:
            return df
        # 转换为元的量纲比较
        return df[df[amount_col] * 1000 >= self.config.min_amount]

    def filter_all(self, df: pd.DataFrame,
                   ts_code_col: str = 'ts_code',
                   name_col: str = 'name') -> pd.DataFrame:
        """应用所有 DataFrame 级别过滤规则"""
        if df.empty:
            return df

        df = self.filter_st_stocks(df, name_col)
        df = self.filter_by_prefix(df, ts_code_col)
        return df
