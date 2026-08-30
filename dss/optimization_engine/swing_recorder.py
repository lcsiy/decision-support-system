"""
短线交易数据记录器 v10 — 持久化每日分析快照和交易记录。

v10 增强:
- 记录 LLM 分析决策详情 (llm_reviews, llm_sell_confirmation)
- 添加交易汇总函数 generate_trade_summary()
- 兼容旧格式的读取

文件输出：
- data/swing/daily/YYYYMMDD_swing.json  — 每日分析快照
- 交易历史由 SwingPool.execute_sell() 写入 swing_pool.json
"""

import json
import os
from datetime import datetime
from typing import List, Dict, Any, Optional
from dss.config import Config


class SwingRecorder:
    """
    短线交易数据记录器 v10。

    记录内容：
    - 每日市场环境
    - 池审查结果（卖出判定详情 + LLM 确认记录）
    - 新股推荐（排名、各项评分、入场计划 + LLM 分析记录）
    - 池变更后状态
    """

    def __init__(self, config: Config):
        self.daily_dir = str(config.SWING_DAILY_DIR)
        os.makedirs(self.daily_dir, exist_ok=True)

    def record_daily_analysis(
        self,
        trade_date: str,
        market_env: Dict[str, Any],
        pool_review: Dict[str, Any],
        new_picks: List[Dict[str, Any]],
        pool_after: List[str],
        llm_sell_reviews: List[Dict[str, Any]] | None = None,
        llm_buy_analyses: List[Dict[str, Any]] | None = None,
    ) -> str:
        """
        记录每日分析快照。

        Args:
            trade_date: 交易日期 YYYYMMDD
            market_env: 市场环境数据
            pool_review: {'existing': int, 'sell_decisions': [...], 'hold_checks': [...]}
            new_picks: 新选股票列表 (含 entry_price, composite_score 等)
            pool_after: 更新后池中的 ts_code 列表
            llm_sell_reviews: LLM 对卖出信号的审查结果 (v10 新增)
            llm_buy_analyses: LLM 对买入候选的分析结果 (v10 新增)

        Returns:
            保存的文件路径
        """
        record = {
            'date': trade_date,
            'generated_at': datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
            'market_env': market_env,
            'pool_review': pool_review,
            'new_picks': new_picks,
            'pool_after': pool_after,
        }

        # v10: LLM 增强字段
        if llm_sell_reviews:
            record['llm_sell_reviews'] = llm_sell_reviews
        if llm_buy_analyses:
            record['llm_buy_analyses'] = llm_buy_analyses

        filepath = os.path.join(self.daily_dir, f'{trade_date}_swing.json')
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(record, f, ensure_ascii=False, indent=2)

        print(f"📝 每日分析已记录: {filepath}")
        return filepath

    def load_daily_analysis(self, trade_date: str) -> Optional[Dict]:
        """加载指定日期的分析记录"""
        filepath = os.path.join(self.daily_dir, f'{trade_date}_swing.json')
        if not os.path.exists(filepath):
            return None
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)

    def list_analysis_dates(self) -> List[str]:
        """列出所有已记录的日期"""
        dates = []
        if not os.path.exists(self.daily_dir):
            return dates
        for filename in os.listdir(self.daily_dir):
            if filename.endswith('_swing.json'):
                dates.append(filename.replace('_swing.json', ''))
        return sorted(dates)

    # ---- v10 新增: 交易汇总 ----

    def generate_trade_summary(self, pool_file: str) -> Dict[str, Any]:
        """从池文件生成交易绩效汇总。

        供后续优化分析器使用。
        """
        if not os.path.exists(pool_file):
            return {"error": "pool file not found"}

        with open(pool_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        history = data.get('trade_history', [])
        if not history:
            return {"total_trades": 0, "message": "无交易记录"}

        wins = [t for t in history if t['pnl_pct'] > 0]
        losses = [t for t in history if t['pnl_pct'] <= 0]

        avg_pnl = sum(t['pnl_pct'] for t in history) / len(history)
        avg_hold = sum(t.get('hold_days', 0) for t in history) / len(history)

        reasons = {}
        for t in history:
            r = t.get('sell_reason', 'UNKNOWN')
            reasons[r] = reasons.get(r, 0) + 1

        return {
            "total_trades": len(history),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(history) * 100, 1) if history else 0,
            "avg_pnl_pct": round(avg_pnl, 2),
            "avg_hold_days": round(avg_hold, 1),
            "total_pnl_pct": round(sum(t['pnl_pct'] for t in history), 2),
            "avg_buy_score": round(sum(t.get('buy_composite_score', 0) for t in history) / len(history), 1) if history else 0,
            "sell_reasons": reasons,
            "first_trade": history[0].get('buy_date', ''),
            "last_trade": history[-1].get('sell_date', ''),
        }
