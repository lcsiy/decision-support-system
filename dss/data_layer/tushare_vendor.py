#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tushare 数据厂商层 — DSS 自包含实现（v11 解耦）。

v11 变更:
- 不再委托 TradingAgents 的厂商层 (tradingagents.dataflows.tushare)
- 全部 tushare 调用由本 skill 直接实现，token 取自本项目 .env 的 TUSHARE_TOKEN
- 保留 major_news 全局缓存（30 次/小时限流防护，每轮运行约 9 次调用）
- 函数签名与 v10 委托层保持一致 → TushareClient 调用方零改动

积分要求: 所有接口 ≤ 6000 积分
"""

import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd
import tushare as ts
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# token / 客户端
# ---------------------------------------------------------------------------

# 项目根目录（本文件位于 dss/data_layer/ 下 → 项目根 = 三级父目录）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(dotenv_path=_PROJECT_ROOT / '.env')


def _get_token() -> str:
    """返回 tushare token（本项目 .env 或环境变量）。"""
    return os.environ.get("TUSHARE_TOKEN", "").strip()


def _get_pro():
    """返回配置好的 tushare pro 客户端；token 缺失时抛 ValueError。"""
    token = _get_token()
    if not token:
        raise ValueError(
            "TUSHARE_TOKEN 未设置。请在 .env 文件中设置 TUSHARE_TOKEN=your_token"
        )
    return ts.pro_api(token)


# tushare 按 token+IP 限频（免费档约 200 次/分钟）。批量拉取时可设置
# TUSHARE_INTER_CALL_SLEEP 进行粗粒度节流。
_TUSHARE_INTER_CALL_SLEEP = float(os.environ.get("TUSHARE_INTER_CALL_SLEEP", "0.0"))


def _maybe_sleep():
    """粗粒度调用间隔 — 见模块 docstring。"""
    if _TUSHARE_INTER_CALL_SLEEP > 0:
        time.sleep(_TUSHARE_INTER_CALL_SLEEP)


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def _to_ts_code(symbol: str) -> str:
    """Yahoo 风格代码 → tushare 格式。

    Yahoo 用 ``600519.SS`` 表示上交所；tushare 用 ``600519.SH``。
    深交所 (``.SZ``) 与北交所 (``.BJ``) 两种格式一致。
    """
    symbol = symbol.upper().strip()
    if symbol.endswith(".SS"):
        return symbol.replace(".SS", ".SH")
    return symbol


def _ymd(date_str: str) -> str:
    """``2024-05-10`` → ``20240510``。"""
    return date_str.replace("-", "")


def _today_ymd() -> str:
    """今天日期 → ``YYYYMMDD``。"""
    return date.today().strftime("%Y%m%d")


# ---------------------------------------------------------------------------
# 行情数据
# ---------------------------------------------------------------------------

def get_tushare_daily_df(
    ts_code: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    with_ma: bool = False,
    ma_periods: Tuple[int, ...] = (5, 10, 20, 60),
) -> "pd.DataFrame":
    """日线 OHLCV DataFrame，可选附加 MA 列。

    ``ts_code`` 为 tushare 格式 (``600519.SH``)；调用方需先用 ``_to_ts_code()``
    从 Yahoo 风格 (``.SS`` → ``.SH``) 转换。

    失败时返回空 DataFrame，不抛异常。
    """
    pro = _get_pro()
    kwargs: dict = {"ts_code": ts_code}
    if start_date:
        kwargs["start_date"] = _ymd(start_date)
    if end_date:
        kwargs["end_date"] = _ymd(end_date)
    try:
        df = pro.daily(**kwargs)
        if df is None or df.empty:
            return pd.DataFrame()
        df = df.sort_values("trade_date").reset_index(drop=True)
        if with_ma and "close" in df.columns:
            for p in ma_periods:
                df[f"ma{p}"] = df["close"].rolling(window=p).mean()
        return df
    except Exception:
        return pd.DataFrame()


def get_tushare_batch_daily(
    ts_codes: list,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    with_ma: bool = False,
    ma_periods: Tuple[int, ...] = (5, 10, 20, 60),
) -> dict:
    """批量日线 OHLCV → ``{ts_code: DataFrame}``。"""
    results: dict = {}
    for i, code in enumerate(ts_codes):
        if i % 20 == 0:
            _maybe_sleep()
        df = get_tushare_daily_df(code, start_date, end_date, with_ma, ma_periods)
        if not df.empty:
            results[code] = df
    return results


def get_tushare_index_daily(
    ts_code: str = "000001.SH",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    trade_date: Optional[str] = None,
) -> "pd.DataFrame":
    """指数日线行情 (free API)。

    注意: tushare 返回降序（最新在前），此处统一按 trade_date 升序排序，
    保证调用方用 iloc[-1] 取到的是最新一天（曾因此取到 1993 年数据）。
    """
    pro = _get_pro()
    kwargs: dict = {"ts_code": ts_code}
    if trade_date:
        kwargs["trade_date"] = _ymd(trade_date)
    if start_date:
        kwargs["start_date"] = _ymd(start_date)
    if end_date:
        kwargs["end_date"] = _ymd(end_date)
    try:
        df = pro.index_daily(**kwargs)
        if df is not None and not df.empty and 'trade_date' in df.columns:
            df = df.sort_values('trade_date').reset_index(drop=True)
        return df if df is not None else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# 资金流向
# ---------------------------------------------------------------------------

def get_tushare_moneyflow(
    ts_code: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> "pd.DataFrame":
    """个股资金流向 (2000-point API)。"""
    pro = _get_pro()
    kwargs: dict = {"ts_code": ts_code}
    if start_date:
        kwargs["start_date"] = _ymd(start_date)
    if end_date:
        kwargs["end_date"] = _ymd(end_date)
    try:
        df = pro.moneyflow(**kwargs)
        return df if df is not None else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# 热榜 / ST / 涨跌停
# ---------------------------------------------------------------------------

def get_tushare_ths_hot(
    trade_date: Optional[str] = None,
    market: str = "热股",
) -> "pd.DataFrame":
    """同花顺 App 热榜 (3000-point API)。"""
    tdate = _today_ymd() if trade_date is None else _ymd(trade_date)
    pro = _get_pro()
    try:
        df = pro.ths_hot(trade_date=tdate, market=market, is_new="Y")
        return df if df is not None else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def get_tushare_st_list(trade_date: Optional[str] = None) -> set:
    """ST 股票 ts_code 集合 (2000-point API)。"""
    tdate = _today_ymd() if trade_date is None else _ymd(trade_date)
    pro = _get_pro()
    st_set: set = set()
    try:
        df = pro.stock_st(trade_date=tdate)
        if df is not None and not df.empty and "ts_code" in df.columns:
            for code in df["ts_code"]:
                st_set.add(str(code).strip())
    except Exception:
        pass
    return st_set


def get_tushare_limit_list(trade_date: Optional[str] = None) -> "pd.DataFrame":
    """涨跌停列表 (2000-point API)。"""
    tdate = _today_ymd() if trade_date is None else _ymd(trade_date)
    pro = _get_pro()
    try:
        df = pro.limit_list_d(trade_date=tdate)
        return df if df is not None else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# 基础信息
# ---------------------------------------------------------------------------

def get_tushare_stock_basic(
    list_status: str = "L",
    fields: str = "ts_code,name,industry,list_date",
) -> "pd.DataFrame":
    """全市场股票基础信息 (free API)。"""
    pro = _get_pro()
    try:
        df = pro.stock_basic(list_status=list_status, fields=fields, exchange="")
        return df if df is not None else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def get_tushare_trade_cal(
    exchange: str = "SSE",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> dict:
    """交易日历 → ``{cal_date: is_open}`` (free API)。"""
    pro = _get_pro()
    kwargs: dict = {"exchange": exchange}
    if start_date:
        kwargs["start_date"] = _ymd(start_date)
    if end_date:
        kwargs["end_date"] = _ymd(end_date)
    try:
        df = pro.trade_cal(**kwargs)
        if df is None or df.empty:
            return {}
        return {
            str(row.get("cal_date", "")): bool(row.get("is_open", 0))
            for _, row in df.iterrows()
        }
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# 新闻 (major_news, 2000-point API)
# ---------------------------------------------------------------------------
# ``news`` 短讯接口需 5000+ 积分，本档位不可用；``major_news`` 长文接口 2000+
# 积分可用，默认返回 title/pub_time/src，``content`` 需显式指定。
#
# major_news 有 30 次/小时限流。旧逻辑按股票 × 来源循环会烧掉几十次调用，
# 现在全量一次抓取（9 个来源）→ 全局缓存 → 本地按股票/关键词过滤。

_NEWS_CACHE: dict = {}


def _fetch_news_cache(start_date: str, end_date: str) -> "pd.DataFrame":
    """按日期区间抓取 major_news 一次，跨股票复用全局缓存。"""
    cache_key = f"{_ymd(start_date)}-{_ymd(end_date)}"
    if cache_key in _NEWS_CACHE:
        return _NEWS_CACHE[cache_key]

    pro = _get_pro()
    frames = []
    for src in ["财联社", "华尔街见闻", "新浪财经", "第一财经", "中证网",
                "新华网", "凤凰财经", "同花顺", "财新网"]:
        try:
            _maybe_sleep()
            df = pro.major_news(
                src=src,
                start_date=_ymd(start_date),
                end_date=_ymd(end_date),
                fields="title,pub_time,src,content",
            )
            if df is not None and not df.empty:
                frames.append(df)
        except Exception:
            continue

    result = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    result = result.drop_duplicates(subset=["title"]).reset_index(drop=True)
    _NEWS_CACHE[cache_key] = result
    return result


def get_tushare_news(
    ticker: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    """获取个股相关新闻 — 批量优化，使用全局缓存的资讯流。"""
    if end_date is None:
        end_date = date.today().strftime("%Y-%m-%d")
    if start_date is None:
        start_date = (date.today() - timedelta(days=7)).strftime("%Y-%m-%d")

    ts_code = _to_ts_code(ticker)
    code_numeric = ts_code.split(".")[0] if "." in ts_code else ts_code

    # 解析股票名称（免费接口，一次调用）
    stock_name = ""
    try:
        pro = _get_pro()
        info = pro.stock_basic(ts_code=ts_code, fields="name")
        if info is not None and not info.empty:
            stock_name = str(info.iloc[0].get("name", ""))
    except Exception:
        pass

    df = _fetch_news_cache(start_date, end_date)
    if df.empty:
        return f"No tushare news found for {ts_code} between {start_date} and {end_date}"

    search_terms = [t for t in [ticker, ts_code, stock_name, code_numeric] if t]
    all_articles = []
    for _, row in df.iterrows():
        title = str(row.get("title", ""))
        content = str(row.get("content", ""))
        combined = title + content
        if any(term in combined for term in search_terms if term):
            all_articles.append({
                "title": title,
                "content": content[:500] if content else "",
                "time": str(row.get("pub_time", "")),
                "source": str(row.get("src", "")),
            })
            if len(all_articles) >= 20:
                break

    if not all_articles:
        return f"No tushare news found for {ts_code} between {start_date} and {end_date}"

    label = f"# News for {ts_code}"
    if stock_name:
        label += f" ({stock_name})"
    label += f" from {start_date} to {end_date}\n"
    label += f"# Total articles: {len(all_articles)}\n"
    label += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (via tushare)\n\n"

    lines = []
    for a in all_articles:
        lines.append(f"### {a['title']} (source: {a['source']}, {a['time']})")
        if a["content"]:
            lines.append(a["content"])
        lines.append("")

    return label + "\n".join(lines)
