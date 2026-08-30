"""
技术动量分析器 — 60% 权重。

从 UltraShortTailAnalyzer 中提取，包含：
- 日线量价分析（成交量因子、量价配合）
- 分钟数据趋势分析（尾盘30分钟线性斜率）
- 尾盘量价推断信号（放量上涨/下跌判断）
- 涨跌停状态检查

纯函数设计：所有数据通过参数注入，不依赖全局状态或文件IO。
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any

import numpy as np
import pandas as pd


class TechnicalMomentumAnalyzer:
    """
    技术动量分析器 (60% 权重)。

    分析维度：
    1. 当日涨跌幅得分 (30%) — 追涨不追跌
    2. 价格位置得分 (20%) — 日内位置
    3. 尾盘趋势得分 (20%) — 基于分钟数据的线性回归斜率
    4. 成交量因子得分 (30%) — 量价配合 + 相对5日均量
    5. 尾盘量价推断信号 (±10分) — 放量上涨/下跌

    使用方式:
        analyzer = TechnicalMomentumAnalyzer()
        score, details = analyzer.analyze(
            ts_code, current_price, daily_change_pct,
            realtime_data, daily_df, minute_df
        )
    """

    # 子项权重（有分钟数据时）
    WEIGHT_CHANGE = 0.30    # 当日涨跌幅
    WEIGHT_POSITION = 0.20  # 价格位置
    WEIGHT_TREND = 0.20     # 尾盘趋势
    WEIGHT_VOLUME = 0.30    # 成交量因子

    # 子项权重（无分钟数据时 — 趋势降权，成交量加权重）
    WEIGHT_CHANGE_NO_MIN = 0.30
    WEIGHT_POSITION_NO_MIN = 0.25
    WEIGHT_TREND_NO_MIN = 0.10
    WEIGHT_VOLUME_NO_MIN = 0.35

    # 尾盘量价推断信号调整范围
    TAIL_SIGNAL_MULTIPLIER = 10.0

    def analyze(
        self,
        ts_code: str,
        current_price: float,
        daily_change_pct: float,
        realtime_data: Optional[Dict[str, Any]] = None,
        daily_df: Optional[pd.DataFrame] = None,
        minute_df: Optional[pd.DataFrame] = None,
        use_minute_data: bool = True,
    ) -> Tuple[float, Dict[str, Any]]:
        """
        执行技术动量分析。

        Args:
            ts_code: 股票代码
            current_price: 当前价格
            daily_change_pct: 当日涨跌幅 (%)
            realtime_data: 实时行情 dict (含 open, high, low 等)
            daily_df: 日线 DataFrame (至少6行，含 vol 列)
            minute_df: 分钟数据 DataFrame (含 timestamp, price, volume 列)
            use_minute_data: 是否使用分钟数据

        Returns:
            (score: float 0-100, details: dict)
        """
        details: Dict[str, Any] = {
            'daily_change_pct': daily_change_pct,
            'recent_trend': 0.0,
            'recent_volume_ratio': 0.0,
            'price_position': 0.5,
            'relative_volume_vs_5d': 0.0,
            'volume_trend': 'normal',
            'volume_score': 50.0,
            'minute_data_available': False,
            'tail_volume_price_signal': 0.0,
        }

        # 1. 提取 OHLC 并计算价格位置
        open_price, high_price, low_price = self._extract_ohlc(realtime_data)
        if high_price > low_price:
            details['price_position'] = float(np.clip(
                (current_price - low_price) / (high_price - low_price), 0, 1
            ))

        # 2. 相对5日均量
        if daily_df is not None and not daily_df.empty:
            self._compute_relative_volume(daily_df, details)

        # 3. 分钟数据趋势分析
        if use_minute_data and minute_df is not None and len(minute_df) >= 3:
            trend_result = self._analyze_minute_trend(minute_df, current_price)
            if trend_result['available']:
                details['recent_trend'] = trend_result['recent_trend']
                details['recent_volume_ratio'] = trend_result['recent_volume_ratio']
                details['minute_data_available'] = True

        # 4. 子项评分
        change_score = 50.0 + daily_change_pct * 10
        position_score = details['price_position'] * 100

        if details['minute_data_available']:
            trend_score = 50.0 + details['recent_trend'] * 1000
            trend_score = float(np.clip(trend_score, 0, 100))
        else:
            trend_score = 50.0

        volume_score = self._compute_volume_score(details, daily_change_pct)
        details['volume_score'] = volume_score

        # 5. 加权计算
        if details['minute_data_available']:
            score = (
                change_score * self.WEIGHT_CHANGE +
                position_score * self.WEIGHT_POSITION +
                trend_score * self.WEIGHT_TREND +
                volume_score * self.WEIGHT_VOLUME
            )
        else:
            score = (
                change_score * self.WEIGHT_CHANGE_NO_MIN +
                position_score * self.WEIGHT_POSITION_NO_MIN +
                trend_score * self.WEIGHT_TREND_NO_MIN +
                volume_score * self.WEIGHT_VOLUME_NO_MIN
            )

        # 6. 尾盘量价推断信号调整
        if use_minute_data and minute_df is not None:
            tail_signal = self._analyze_tail_volume_price(ts_code, current_price, minute_df)
            details['tail_volume_price_signal'] = tail_signal
            score += tail_signal * self.TAIL_SIGNAL_MULTIPLIER

        score = float(np.clip(score, 0, 100))
        return score, details

    # ---- 子分析 ----

    @staticmethod
    def _extract_ohlc(realtime_data: Optional[Dict[str, Any]]) -> Tuple[float, float, float]:
        """从实时数据提取 OHLC"""
        open_price = 0.0
        high_price = 0.0
        low_price = 0.0

        if realtime_data is None:
            return open_price, high_price, low_price

        for f in ['open', '开盘价']:
            try:
                open_price = float(realtime_data.get(f, 0))
                break
            except (ValueError, TypeError):
                pass
        for f in ['high', '最高价']:
            try:
                high_price = float(realtime_data.get(f, 0))
                break
            except (ValueError, TypeError):
                pass
        for f in ['low', '最低价']:
            try:
                low_price = float(realtime_data.get(f, 0))
                break
            except (ValueError, TypeError):
                pass

        return open_price, high_price, low_price

    @staticmethod
    def _compute_relative_volume(daily_df: pd.DataFrame, details: Dict[str, Any]) -> None:
        """计算相对5日均量"""
        try:
            vol_col = None
            for col in daily_df.columns:
                if 'vol' in col.lower() or '成交量' in col:
                    vol_col = col
                    break

            if vol_col and len(daily_df) >= 6:
                vols = daily_df[vol_col].tail(6).values
                today_vol = float(vols[-1])
                avg_5d_vol = float(np.mean(vols[:-1]))

                if avg_5d_vol > 0:
                    rel_vol = today_vol / avg_5d_vol
                    details['relative_volume_vs_5d'] = rel_vol

                    if rel_vol > 2.0:
                        details['volume_trend'] = 'extreme_surge'
                    elif rel_vol > 1.5:
                        details['volume_trend'] = 'significant_surge'
                    elif rel_vol > 1.2:
                        details['volume_trend'] = 'moderate_surge'
                    elif rel_vol > 0.8:
                        details['volume_trend'] = 'normal'
                    elif rel_vol > 0.5:
                        details['volume_trend'] = 'shrinking'
                    else:
                        details['volume_trend'] = 'extreme_shrinking'
        except Exception:
            pass

    @staticmethod
    def _analyze_minute_trend(
        minute_df: pd.DataFrame, current_price: float
    ) -> Dict[str, Any]:
        """分析分钟数据趋势（最近30分钟线性回归斜率）"""
        result = {'available': False, 'recent_trend': 0.0, 'recent_volume_ratio': 0.0}

        try:
            if len(minute_df) < 3:
                return result

            prices = minute_df['price'].values if 'price' in minute_df.columns else minute_df.iloc[:, 1].values

            if len(prices) > 1 and np.std(prices) > 0:
                x = np.arange(len(prices))
                slope, _ = np.polyfit(x, prices, 1)
                result['recent_trend'] = float(slope / current_price)
                result['available'] = True

            total_vol = minute_df['volume'].sum() if 'volume' in minute_df.columns else 0
            if total_vol > 0:
                result['recent_volume_ratio'] = float(total_vol / max(total_vol, 1))

        except Exception:
            pass

        return result

    @staticmethod
    def _analyze_tail_volume_price(
        ts_code: str, current_price: float, minute_df: pd.DataFrame
    ) -> float:
        """
        尾盘量价推断信号。

        从分钟数据的量价关系推断尾盘资金行为：
        - 尾盘放量上涨 → 资金积极进场 (+)
        - 尾盘放量下跌 → 恐慌抛售 (-)
        - 缩量 → 中性 (0)

        Returns:
            float: [-1, +1] 信号强度
        """
        try:
            if len(minute_df) < 5:
                return 0.0

            # 取尾盘部分（后30%）
            tail_size = max(int(len(minute_df) * 0.3), 5)
            tail_df = minute_df.tail(tail_size)

            if len(tail_df) < 3:
                return 0.0

            tail_prices = tail_df['price'].values if 'price' in tail_df.columns else tail_df.iloc[:, 1].values

            if len(tail_prices) < 2:
                return 0.0

            tail_return = float((tail_prices[-1] - tail_prices[0]) / tail_prices[0])

            tail_vol = tail_df['volume'].sum() if 'volume' in tail_df.columns else 0
            total_vol = minute_df['volume'].sum() if 'volume' in minute_df.columns else 1
            if total_vol <= 0:
                return 0.0

            vol_ratio = tail_vol / total_vol
            is_volume_surge = vol_ratio > 0.15

            if is_volume_surge and tail_return > 0.002:
                return min(1.0, tail_return * 200)
            elif is_volume_surge and tail_return < -0.002:
                return max(-1.0, tail_return * 200)
            elif tail_return > 0.001:
                return 0.3
            elif tail_return < -0.001:
                return -0.3
            else:
                return 0.0

        except Exception:
            return 0.0

    @staticmethod
    def _compute_volume_score(details: Dict[str, Any], daily_change_pct: float) -> float:
        """
        成交量因子评分 — 量价配合逻辑。

        - 放量上涨 → 85-100 (最佳)
        - 缩量上涨 → 45 (动能不足)
        - 放量下跌 → 15-25 (最差)
        - 缩量下跌 → 50 (抛压减轻)
        """
        score = 50.0
        vol_trend = details.get('volume_trend', 'normal')
        rel_vol = details.get('relative_volume_vs_5d', 1.0)
        is_up = daily_change_pct > 0
        is_down = daily_change_pct < 0

        if is_up and vol_trend in ('significant_surge', 'extreme_surge'):
            score = 85 + min(rel_vol - 1.5, 1.5) * 10
        elif is_up and vol_trend == 'moderate_surge':
            score = 70
        elif is_up and vol_trend == 'normal':
            score = 60
        elif is_up and vol_trend in ('shrinking', 'extreme_shrinking'):
            score = 45
        elif is_down and vol_trend in ('significant_surge', 'extreme_surge'):
            score = 15 + min(rel_vol - 1.5, 1.5) * 5
        elif is_down and vol_trend == 'moderate_surge':
            score = 30
        elif is_down and vol_trend == 'normal':
            score = 42
        elif is_down and vol_trend in ('shrinking', 'extreme_shrinking'):
            score = 50
        else:
            if vol_trend in ('significant_surge', 'extreme_surge'):
                score = 55
            elif vol_trend in ('shrinking', 'extreme_shrinking'):
                score = 48
            else:
                score = 50

        return float(np.clip(score, 0, 100))

    # ---- 静态工具方法 ----

    @staticmethod
    def check_limit_status(current_price: float, pre_close: float) -> Dict[str, Any]:
        """
        检查涨跌停状态。

        Returns:
            {'is_limit_up': bool, 'is_limit_down': bool,
             'is_near_limit_down': bool, 'change_pct': float}
        """
        if pre_close <= 0:
            return {
                'is_limit_up': False, 'is_limit_down': False,
                'is_near_limit_down': False, 'change_pct': 0.0,
            }

        change_pct = (current_price - pre_close) / pre_close * 100

        return {
            'is_limit_up': change_pct >= 9.5,
            'is_limit_down': change_pct <= -9.5,
            'is_near_limit_down': change_pct <= -7.0,
            'change_pct': float(change_pct),
        }

    @staticmethod
    def safe_float(row: Dict[str, Any], fields: List[str]) -> float:
        """安全提取浮点数（兼容多语言列名）"""
        for f in fields:
            val = row.get(f, 0)
            if val is None:
                continue
            try:
                return float(val)
            except (ValueError, TypeError):
                pass
        return 0.0
