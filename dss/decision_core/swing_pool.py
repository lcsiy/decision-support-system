"""
短线追踪池状态管理 + 卖出信号判定。

持久化文件: data/swing/swing_pool.json
"""

import json
import os
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional
import pandas as pd
from dss.config import Config


@dataclass
class PoolEntry:
    """追踪池持仓条目"""
    ts_code: str
    name: str
    buy_date: str
    buy_price: float
    buy_composite_score: float = 0.0
    stop_loss_price: float = 0.0
    take_profit_price: float = 0.0
    highest_since_buy: float = 0.0
    hold_days: int = 0
    buy_factors: Dict[str, float] = None
    daily_log: List[Dict[str, Any]] = None

    def __post_init__(self):
        if self.buy_factors is None:
            self.buy_factors = {}
        if self.daily_log is None:
            self.daily_log = []


@dataclass
class SellDecision:
    """卖出判定结果"""
    should_sell: bool
    reason: str  # STOP_LOSS, TAKE_PROFIT, TIME_STOP, BREAKDOWN, MARKET_CRASH
    detail: str
    recommended_exit_price: float = 0.0
    confidence: float = 50.0


class SwingPool:
    """
    追踪池管理器：持仓增删改查、交易日计数、每日快照。
    所有数据持久化到 SWING_POOL_FILE。
    """

    def __init__(self, config: Config):
        self.pool_file = str(config.SWING_POOL_FILE)
        os.makedirs(os.path.dirname(self.pool_file), exist_ok=True)

    def load(self) -> dict:
        """加载完整池数据"""
        if not os.path.exists(self.pool_file):
            return self._empty_state()
        try:
            with open(self.pool_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return self._empty_state()

    def save(self, data: dict) -> None:
        """保存完整池数据"""
        data['generated_at'] = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
        with open(self.pool_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def get_active_pool(self) -> List[PoolEntry]:
        """获取当前持仓"""
        data = self.load()
        return [PoolEntry(**entry) for entry in data.get('pool', [])]

    def get_available_slots(self) -> int:
        """获取可用仓位数量"""
        data = self.load()
        return max(0, 3 - len(data.get('pool', [])))

    def add_to_pool(
        self, ts_code: str, name: str, buy_date: str, buy_price: float,
        composite_score: float = 0.0, factors: Dict[str, float] = None
    ) -> None:
        """添加股票到追踪池"""
        data = self.load()
        stop_loss = round(buy_price * 0.95, 2)
        take_profit = round(buy_price * 1.10, 2)

        entry = {
            'ts_code': ts_code,
            'name': name,
            'buy_date': buy_date,
            'buy_price': buy_price,
            'buy_composite_score': composite_score,
            'stop_loss_price': stop_loss,
            'take_profit_price': take_profit,
            'highest_since_buy': buy_price,
            'hold_days': 0,
            'buy_factors': factors or {},
            'daily_log': [{
                'date': buy_date,
                'close': buy_price,
                'pct_chg': 0.0,
                'signal': 'ENTRY',
            }]
        }
        data.setdefault('pool', []).append(entry)
        self.save(data)

    def execute_sell(
        self, ts_code: str, exit_price: float, reason: str,
        trade_date: str, confidence: float = 80.0
    ) -> None:
        """执行卖出：从池移除，记录到交易历史"""
        data = self.load()
        pool = data.get('pool', [])

        # 找到对应条目
        sold_entry = None
        new_pool = []
        for entry in pool:
            if entry['ts_code'] == ts_code:
                sold_entry = entry
            else:
                new_pool.append(entry)

        if sold_entry is None:
            print(f"⚠️ 池中找不到 {ts_code}")
            return

        data['pool'] = new_pool

        # 计算盈亏
        buy_price = sold_entry['buy_price']
        pnl_pct = round((exit_price - buy_price) / buy_price * 100, 2)
        buy_date = sold_entry['buy_date']

        trade_record = {
            'ts_code': ts_code,
            'name': sold_entry['name'],
            'buy_date': buy_date,
            'buy_price': buy_price,
            'sell_date': trade_date,
            'sell_price': exit_price,
            'sell_reason': reason,
            'sell_confidence': confidence,
            'hold_days': sold_entry.get('hold_days', 0),
            'pnl_pct': pnl_pct,
            'buy_composite_score': sold_entry.get('buy_composite_score', 0),
            'buy_factors': sold_entry.get('buy_factors', {}),
            'highest_reached': sold_entry.get('highest_since_buy', buy_price),
        }
        data.setdefault('trade_history', []).append(trade_record)
        self.save(data)
        print(f"✅ 已卖出 {ts_code} {sold_entry['name']}: {buy_price:.2f} → {exit_price:.2f} ({pnl_pct:+.2f}%) [{reason}]")

    def log_daily_snapshot(
        self, ts_code: str, date: str, close: float,
        pct_chg: float, sell_check: Dict[str, Any]
    ) -> None:
        """记录每日快照到追踪池"""
        data = self.load()
        for entry in data.get('pool', []):
            if entry['ts_code'] == ts_code:
                entry['daily_log'].append({
                    'date': date,
                    'close': close,
                    'pct_chg': round(pct_chg, 2),
                    'signal': 'HOLD',
                    'sell_check': sell_check,
                })
                # 更新最高价和持仓天数
                if close > entry.get('highest_since_buy', 0):
                    entry['highest_since_buy'] = round(close, 2)
                entry['hold_days'] = len(entry['daily_log']) - 1  # 减去ENTRY那天
                self.save(data)
                return

    def get_trade_history(self) -> List[dict]:
        """获取交易历史"""
        data = self.load()
        return data.get('trade_history', [])

    def get_summary_stats(self) -> dict:
        """获取汇总统计"""
        history = self.get_trade_history()
        if not history:
            return {'total_trades': 0, 'win_count': 0, 'win_rate': 0,
                    'avg_pnl': 0, 'cumulative_pnl': 0}

        wins = [t for t in history if t['pnl_pct'] > 0]
        pnls = [t['pnl_pct'] for t in history]

        return {
            'total_trades': len(history),
            'win_count': len(wins),
            'win_rate': round(len(wins) / len(history) * 100, 1),
            'avg_pnl': round(sum(pnls) / len(pnls), 2),
            'cumulative_pnl': round(sum(pnls), 2),
        }

    def reindex_hold_days(self) -> None:
        """根据日历重新计算池中所有股票的实际持仓天数"""
        # 简化实现：直接使用 daily_log 条目数
        data = self.load()
        for entry in data.get('pool', []):
            entry['hold_days'] = len(entry.get('daily_log', [])) - 1
        self.save(data)

    @staticmethod
    def _empty_state() -> dict:
        return {
            'version': '1.0',
            'generated_at': '',
            'pool': [],
            'trade_history': [],
        }


class SwingSellSignal:
    """
    持仓风险评估器（v10.2 改造: 不做卖出决策，只提供风险参考指标）。

    评估以下风险维度，将结果注入 LLM Agent 辩论上下文：
    1. 浮亏程度: 是否接近止损参考线（-5%）
    2. 浮盈程度: 是否接近止盈参考线（+10%）
    3. 持仓时长: 持有天数（参考值，非强制限制）
    4. 均线状态: MA排列、是否破位
    5. 大盘风险: 系统性风险级别

    所有规则输出的是**风险提示**而非**卖出指令**。
    最终决策由 RiskManager Agent 做出。
    """

    _RISK_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}

    def __init__(self, config: Config):
        self.max_hold_ref = config.SWING_MAX_HOLD_DAYS  # 参考值
        self.sl_pct = config.SWING_STOP_LOSS_PCT
        self.tp_pct = config.SWING_TAKE_PROFIT_PCT

    def _upgrade_risk(self, current: str, candidate: str) -> str:
        return candidate if self._RISK_ORDER.get(candidate, 0) > self._RISK_ORDER.get(current, 0) else current

    def assess(
        self, entry: PoolEntry, df: pd.DataFrame,
        market_env: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        评估持仓风险，返回结构化风险上下文。

        Returns:
            {
                "pnl_pct": 盈亏百分比,
                "hold_days": 持仓天数,
                "risk_level": LOW / MEDIUM / HIGH / CRITICAL,
                "warnings": ["风险提示1", "风险提示2"],
                "ma_status": "多头排列" / "空头排列" / "交叉震荡",
                "price_vs_ma": {...},
                "market_risk": "LOW" / "MEDIUM" / "HIGH",
            }
        """
        result = {
            "pnl_pct": 0.0,
            "hold_days": entry.hold_days,
            "risk_level": "LOW",
            "warnings": [],
            "ma_status": "未知",
            "price_vs_ma": {},
            "market_risk": "LOW",
            "stop_loss_ref": round(entry.buy_price * self.sl_pct, 2),
            "take_profit_ref": round(entry.buy_price * self.tp_pct, 2),
            "hold_days_ref": self.max_hold_ref,
        }

        if df is None or df.empty:
            result["risk_level"] = "MEDIUM"
            result["warnings"].append("无法获取日线数据，无法评估风险")
            return result

        latest = df.iloc[-1]
        close = float(latest['close'])
        pnl_pct = (close - entry.buy_price) / entry.buy_price * 100
        result["pnl_pct"] = round(pnl_pct, 2)

        # 1. 浮亏警告
        sl_price = entry.buy_price * self.sl_pct
        if close <= sl_price:
            result["risk_level"] = "CRITICAL"
            result["warnings"].append(
                f"⚠️ 触及止损参考线: {close:.2f} <= {sl_price:.2f} (浮亏{pnl_pct:.1f}%)"
            )
        elif close < entry.buy_price * 0.97:
            result["risk_level"] = "HIGH"
            result["warnings"].append(f"接近止损参考线: 浮亏{pnl_pct:.1f}%")

        # 2. 浮盈参考
        tp_price = entry.buy_price * self.tp_pct
        if close >= tp_price:
            result["warnings"].append(
                f"📈 达到止盈参考线: {close:.2f} >= {tp_price:.2f} (浮盈{pnl_pct:.1f}%)"
            )

        # 3. 持仓时长参考
        if entry.hold_days >= self.max_hold_ref:
            result["warnings"].append(
                f"⏰ 持仓 {entry.hold_days} 天，达到短线参考上限，建议重新评估"
            )
        elif entry.hold_days >= self.max_hold_ref * 0.7:
            result["warnings"].append(
                f"持仓 {entry.hold_days} 天，接近短线参考上限"
            )

        # 4. 均线状态
        ma_status, ma_details = self._assess_ma(df)
        result["ma_status"] = ma_status
        result["price_vs_ma"] = ma_details
        if ma_status == "空头排列":
            result["risk_level"] = self._upgrade_risk(result["risk_level"], "HIGH")
            result["warnings"].append(f"均线空头排列: {ma_details}")

        # 5. 大盘风险
        mkt = self._assess_market_risk(market_env)
        result["market_risk"] = mkt["level"]
        if mkt["level"] == "HIGH":
            result["risk_level"] = self._upgrade_risk(result["risk_level"], "HIGH")
            result["warnings"].append(f"大盘系统性风险高: {mkt['desc']}")

        return result

    def _assess_ma(self, df: pd.DataFrame) -> tuple:
        """评估均线排列状态"""
        latest = df.iloc[-1]
        close = float(latest['close'])
        details = {"close": close}
        ma_values = {}

        for c in df.columns:
            if c.startswith("ma"):
                v = latest.get(c)
                if v and not (isinstance(v, float) and v != v):
                    ma_values[c] = float(v)
                    details[c] = float(v)

        if not ma_values:
            return "未知", details

        sorted_mas = sorted(ma_values.items(), key=lambda x: int(x[0][2:]))
        periods = [int(m[0][2:]) for m in sorted_mas]
        values = [m[1] for m in sorted_mas]

        # Check if price above/below MAs
        details["above_all"] = all(close > v for v in values)
        details["below_all"] = all(close < v for v in values)

        # Check MA ordering
        is_bullish = all(values[i] >= values[i+1] for i in range(len(values)-1))
        is_bearish = all(values[i] <= values[i+1] for i in range(len(values)-1))

        if is_bullish and details.get("above_all"):
            return "多头排列", details
        elif is_bearish and details.get("below_all"):
            return "空头排列", details
        else:
            return "交叉震荡", details

    def _assess_market_risk(self, market_env: Dict[str, Any]) -> Dict[str, Any]:
        """评估大盘系统性风险"""
        sentiment = market_env.get("sentiment", "neutral")
        score = market_env.get("market_score", 50)

        if sentiment == "bearish" and score < 25:
            return {"level": "HIGH", "desc": f"极端熊市 (评分{score:.0f})"}
        elif sentiment == "bearish":
            return {"level": "MEDIUM", "desc": f"熊市 (评分{score:.0f})"}
        elif sentiment == "slightly_bearish":
            return {"level": "LOW", "desc": f"偏弱"}
        else:
            return {"level": "LOW", "desc": f"正常"}
