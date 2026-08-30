"""
分钟数据仓库 — 分钟级CSV数据的统一读写抽象。

从 ultra_short_tail_analysis.py 和 simplified_minute_collector.py 中
提取所有 CSV 文件 I/O 逻辑，统一路径解析和读写规则。

文件命名规范: {YYYYMMDD}_{ts_code_with_underscore}.csv
示例: 20260103_600036_SH.csv
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any

import pandas as pd


class MinuteDataRepository:
    """
    分钟数据仓库 — 读写分钟级 CSV 数据。

    使用方式:
        repo = MinuteDataRepository(Path("data/minute_data"))
        df = repo.read("20260103", "600036.SH")
        repo.append_snapshot("20260103", "600036.SH", record_dict)
    """

    def __init__(self, data_dir: Path):
        """
        Args:
            data_dir: 分钟数据存储目录
        """
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)

    # ---- 公共读接口 ----

    def read(self, date_str: str, ts_code: str) -> Optional[pd.DataFrame]:
        """
        读取指定日期和股票的分钟数据。

        Args:
            date_str: 日期字符串 (YYYYMMDD)
            ts_code: 股票代码 (e.g. 600036.SH)

        Returns:
            DataFrame 或 None（文件不存在或读取失败）
        """
        file_path = self._resolve_path(date_str, ts_code)
        if file_path is None:
            return None

        try:
            df = pd.read_csv(file_path)
            if 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'])
            return df
        except Exception:
            return None

    def read_recent_minutes(self, date_str: str, ts_code: str,
                            minutes: int = 30) -> Optional[pd.DataFrame]:
        """
        读取最近 N 分钟的分钟数据。

        Args:
            date_str: 日期字符串
            ts_code: 股票代码
            minutes: 最近 N 分钟

        Returns:
            过滤后的 DataFrame 或 None
        """
        df = self.read(date_str, ts_code)
        if df is None or len(df) < 3:
            return None

        if 'timestamp' in df.columns:
            start_time = datetime.now() - timedelta(minutes=minutes)
            tail = df[df['timestamp'] >= start_time]
            if len(tail) >= 3:
                return tail

        # 回退：最后 30% 的数据
        return df.tail(int(len(df) * 0.3))

    # ---- 公共写接口 ----

    def append_snapshot(self, date_str: str, ts_code: str, record: Dict[str, Any]) -> bool:
        """
        追加一条分钟数据记录到 CSV 文件。

        Args:
            date_str: 日期字符串
            ts_code: 股票代码
            record: 单条分钟数据记录 (dict)

        Returns:
            True 表示写入成功
        """
        file_path = self._file_path(date_str, ts_code)
        new_row = pd.DataFrame([record])

        try:
            if file_path.exists():
                existing = pd.read_csv(file_path)
                # 跳过重复时间戳
                if 'timestamp' in existing.columns:
                    ts = record.get('timestamp', '')
                    if ts and ts in existing['timestamp'].values:
                        return False
                combined = pd.concat([existing, new_row], ignore_index=True)
            else:
                combined = new_row

            combined.to_csv(file_path, index=False, encoding='utf-8')
            return True
        except Exception:
            return False

    # ---- 验证白名单 ----

    def load_verification_watchlist(
        self, watchlist_path: Optional[Path] = None
    ) -> List[Dict[str, str]]:
        """
        加载次日验证白名单（来自 feedback_recorder）。

        Args:
            watchlist_path: watchlist JSON 文件路径，None 则自动推断

        Returns:
            需要强制采集的股票列表 [{'ts_code': ..., 'name': ...}, ...]
        """
        if watchlist_path is None:
            # 自动推断路径: data/feedback/verification_watchlist.json
            watchlist_path = self._data_dir.parent / 'feedback' / 'verification_watchlist.json'

        if not watchlist_path.exists():
            return []

        try:
            with open(watchlist_path, 'r', encoding='utf-8') as f:
                watchlist = json.load(f)

            target_date = watchlist.get('target_date', '')
            today = datetime.now().strftime('%Y%m%d')

            if target_date != today:
                return []

            stocks = watchlist.get('stocks', [])
            return [
                {'ts_code': s['ts_code'], 'name': s['name']}
                for s in stocks
            ]
        except Exception:
            return []

    # ---- 文件操作 ----

    def list_files(self, date_str: str) -> List[Path]:
        """列出指定日期的所有分钟数据文件"""
        pattern = f"{date_str}_*.csv"
        return sorted(self._data_dir.glob(pattern))

    def file_exists(self, date_str: str, ts_code: str) -> bool:
        """检查分钟数据文件是否存在"""
        return self._file_path(date_str, ts_code).exists()

    # ---- 内部方法 ----

    def _file_path(self, date_str: str, ts_code: str) -> Path:
        """构建文件路径"""
        code_safe = ts_code.replace('.', '_')
        return self._data_dir / f"{date_str}_{code_safe}.csv"

    def _resolve_path(self, date_str: str, ts_code: str) -> Optional[Path]:
        """解析文件路径"""
        file_path = self._file_path(date_str, ts_code)
        if file_path.exists():
            return file_path
        return None

    @property
    def data_dir(self) -> Path:
        """数据目录路径"""
        return self._data_dir
