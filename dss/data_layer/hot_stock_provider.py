"""
热榜股票提供器 — 获取同花顺热榜并过滤。

从 ultra_short_tail_analysis.py 和 simplified_minute_collector.py 中
提取并去重，提供统一的热榜获取 + 过滤逻辑。

核心能力：
- 智能交易日回溯（最多10天）
- ST 过滤、688/300 排除、去重
- 热度排序与截断
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Set

from dss.data_layer.tushare_client import TushareClient
from dss.data_layer.stock_filter import StockFilter


@dataclass
class HotStock:
    """热榜股票数据对象"""
    ts_code: str
    name: str
    hot: float = 0.0
    rank: int = 0


# 备用股票列表（热榜数据不可用时使用）
FALLBACK_STOCKS: List[Dict[str, str]] = [
    {'ts_code': '600036.SH', 'name': '招商银行', 'hot': 0, 'rank': 1},
    {'ts_code': '000858.SZ', 'name': '五粮液', 'hot': 0, 'rank': 2},
    {'ts_code': '000333.SZ', 'name': '美的集团', 'hot': 0, 'rank': 3},
]


class HotStockProvider:
    """
    热榜股票提供器。

    使用方式:
        client = TushareClient(config)
        provider = HotStockProvider(client, StockFilter())
        stocks = provider.get_hot_stocks(limit=300)
    """

    def __init__(self, client: TushareClient, stock_filter: Optional[StockFilter] = None):
        """
        Args:
            client: Tushare API 客户端
            stock_filter: 股票过滤器，None 则使用默认配置
        """
        self._client = client
        self._filter = stock_filter or StockFilter()
        self._st_set: Set[str] = set()
        self._last_fetch_date: Optional[str] = None

    # ---- 公共接口 ----

    def get_hot_stocks(
        self,
        limit: int = 300,
        filter_st: bool = True,
        max_backtrack_days: int = 10,
    ) -> List[HotStock]:
        """
        获取并过滤热榜股票。

        智能交易日回溯：从今天开始，最多回溯 max_backtrack_days 天，
        自动找到最近一个有热榜数据的交易日。

        Args:
            limit: 最大返回数量
            filter_st: 是否过滤 ST 股票
            max_backtrack_days: 最大回溯天数

        Returns:
            HotStock 列表（按热度降序，带排名）
        """
        # 1. 加载 ST 集合
        if filter_st:
            self._st_set = self._client.get_st_set()

        # 2. 智能回溯获取热榜
        df_hot, found_date = self._fetch_hot_with_backtrack(max_backtrack_days)

        if df_hot is None:
            return self._fallback_stocks()

        self._last_fetch_date = found_date

        # 3. 解析列名
        ts_code_col, name_col, hot_col = self._detect_columns(df_hot)

        # 4. 构建 HotStock 列表并过滤
        stocks = self._parse_and_filter(
            df_hot, ts_code_col, name_col, hot_col, limit
        )

        return stocks

    def get_stock_codes(self, stocks: List[HotStock]) -> List[str]:
        """从 HotStock 列表中提取 ts_code 列表"""
        return [s.ts_code for s in stocks]

    @property
    def last_fetch_date(self) -> Optional[str]:
        """最近一次成功获取热榜的交易日 (YYYYMMDD)"""
        return self._last_fetch_date

    # ---- 内部实现 ----

    def _fetch_hot_with_backtrack(self, max_days: int):
        """
        智能回溯获取热榜数据。

        Returns:
            (DataFrame, found_date_str) 或 (None, None)
        """
        today = datetime.now()

        for days_back in range(max_days):
            check_date = (today - timedelta(days=days_back)).strftime('%Y%m%d')

            label = (
                '今天' if days_back == 0 else
                '昨天' if days_back == 1 else
                f'回溯{days_back}天'
            )
            print(f"🔍 获取热榜数据: {check_date} ({label})...")

            df = self._client.ths_hot(trade_date=check_date, market='热股')

            if df is not None and not df.empty:
                print(f"✅ 使用热榜: {check_date} ({label})")
                return df, check_date

            weekday = (today - timedelta(days=days_back)).weekday()
            weekday_names = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
            print(f"  ⚠️ {check_date} ({weekday_names[weekday]}) 无热榜数据")

        print("⚠️ 回溯无热榜数据，使用备用列表")
        return None, None

    @staticmethod
    def _detect_columns(df):
        """检测热榜 DataFrame 的列名（兼容中英文）"""
        ts_code_col = None
        name_col = None
        hot_col = None

        for col in df.columns:
            cl = col.lower()
            if ts_code_col is None and ('ts_code' in cl or 'code' in cl or '代码' in col):
                ts_code_col = col
            elif name_col is None and ('name' in cl or '名称' in col or 'ts_name' in cl):
                name_col = col
            elif hot_col is None and ('hot' in cl or '热度' in col):
                hot_col = col

        # 回退：按位置
        if ts_code_col is None or name_col is None:
            cols = list(df.columns)
            if len(cols) >= 2:
                ts_code_col = ts_code_col or cols[0]
                name_col = name_col or cols[1]
                hot_col = hot_col or (cols[2] if len(cols) > 2 else None)

        return ts_code_col, name_col, hot_col

    def _parse_and_filter(
        self, df, ts_code_col: str, name_col: str, hot_col: Optional[str], limit: int
    ) -> List[HotStock]:
        """解析 DataFrame 并应用过滤规则"""
        # 按热度排序并去重
        if hot_col:
            df = df.sort_values(hot_col, ascending=False)
        df = df.drop_duplicates(ts_code_col)

        # 先转为 dict 列表以便 StockFilter 处理
        raw_stocks: List[Dict[str, str]] = []
        for _, row in df.iterrows():
            raw_stocks.append({
                'ts_code': str(row[ts_code_col]).strip(),
                'name': str(row[name_col]).strip(),
                'hot': str(row[hot_col]) if hot_col else '0',
            })

        # 使用 StockFilter 过滤
        filtered = self._filter.filter_hot_stocks(
            raw_stocks,
            ts_code_key='ts_code',
            name_key='name',
            st_set=self._st_set if self._filter.config.exclude_st else None,
        )

        # 截断并构建 HotStock
        filtered = filtered[:limit]
        result = []
        for i, s in enumerate(filtered):
            hot_val = float(s.get('hot', 0))
            result.append(HotStock(
                ts_code=s['ts_code'],
                name=s['name'],
                hot=hot_val,
                rank=i + 1,
            ))

        st_filtered = len(raw_stocks) - len(filtered)
        print(f"热榜股票获取完成: {len(result)} 只（过滤 {st_filtered} 只）")
        return result

    @staticmethod
    def _fallback_stocks() -> List[HotStock]:
        """备用股票列表"""
        return [
            HotStock(ts_code=s['ts_code'], name=s['name'], hot=s['hot'], rank=s['rank'])
            for s in FALLBACK_STOCKS
        ]
