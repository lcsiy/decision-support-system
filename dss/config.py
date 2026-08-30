"""
决策支持系统配置模块 — 所有模块的唯一配置来源。

从 .env 文件加载环境变量，通过 Config 类提供类型安全的配置访问。
"""

import os
from pathlib import Path
from typing import List
from dotenv import load_dotenv


# 项目根目录（dss/config.py 的父目录 = dss/ 的父目录 = 项目根）
_PROJECT_ROOT = Path(__file__).parent.parent

# 加载 .env 文件
_env_path = _PROJECT_ROOT / '.env'
load_dotenv(dotenv_path=_env_path)


class Config:
    """
    系统配置 — 所有模块的唯一配置来源。

    无硬编码 fallback：关键配置缺失时 validate() 会报错。
    """

    # ---- 项目路径 ----
    PROJECT_ROOT: Path = _PROJECT_ROOT
    DATA_DIR: Path = _PROJECT_ROOT / 'data'

    # ---- Tushare ----
    TUSHARE_TOKEN: str = os.getenv('TUSHARE_TOKEN', '')

    # ---- 数据库 ----
    DB_PATH: str = os.getenv('DB_PATH', str(_PROJECT_ROOT / 'data' / 'decisions.db'))

    # ---- 并行处理 ----
    MAX_WORKERS: int = int(os.getenv('MAX_WORKERS', '20'))
    # ---- 股票过滤 ----
    EXCLUDE_MARKETS: List[str] = os.getenv('EXCLUDE_MARKETS', '688,300,8').split(',')
    INCLUDE_PREFIXES: List[str] = os.getenv('INCLUDE_PREFIXES', '600,000,001,002,003').split(',')

    # ---- 分析配置 ----
    TOP_N_STOCKS: int = int(os.getenv('TOP_N_STOCKS', '20'))
    MIN_CONFIDENCE_SCORE: float = float(os.getenv('MIN_CONFIDENCE_SCORE', '0.6'))
    ANALYSIS_DAYS_HISTORY: int = int(os.getenv('ANALYSIS_DAYS_HISTORY', '730'))

    # ---- 价格建议 ----
    STOP_LOSS_PCT: float = float(os.getenv('STOP_LOSS_PCT', '0.05'))
    TAKE_PROFIT_PCT: float = float(os.getenv('TAKE_PROFIT_PCT', '0.08'))
    MIN_RISK_REWARD_RATIO: float = float(os.getenv('MIN_RISK_REWARD_RATIO', '2.0'))
    MAX_POSITION_PCT: float = float(os.getenv('MAX_POSITION_PCT', '10.0'))

    # ---- 数据目录（新增字段） ----
    MINUTE_DATA_DIR: Path = Path(
        os.getenv('MINUTE_DATA_DIR', str(_PROJECT_ROOT / 'data' / 'minute_data'))
    )
    FEEDBACK_DIR: Path = Path(
        os.getenv('FEEDBACK_DIR', str(_PROJECT_ROOT / 'data' / 'feedback'))
    )
    REPORT_DIR: Path = Path(
        os.getenv('REPORT_DIR', str(_PROJECT_ROOT / 'data' / 'reports'))
    )

    # ---- 尾盘分析默认参数 ----
    DEFAULT_HOT_LIMIT: int = int(os.getenv('DEFAULT_HOT_LIMIT', '300'))
    DEFAULT_MIN_LIQUIDITY: float = float(os.getenv('DEFAULT_MIN_LIQUIDITY', '10000000'))
    DEFAULT_TOP_N: int = int(os.getenv('DEFAULT_TOP_N', '5'))

    # ---- 两维度权重 (v8.8) ----
    MOMENTUM_WEIGHT: float = float(os.getenv('MOMENTUM_WEIGHT', '0.60'))
    SENTIMENT_WEIGHT: float = float(os.getenv('SENTIMENT_WEIGHT', '0.40'))

    # ---- 短线交易 (Swing Trading) ----
    SWING_DATA_DIR: Path = Path(
        os.getenv('SWING_DATA_DIR', str(_PROJECT_ROOT / 'data' / 'swing'))
    )
    SWING_POOL_FILE: Path = Path(
        os.getenv('SWING_POOL_FILE', str(_PROJECT_ROOT / 'data' / 'swing' / 'swing_pool.json'))
    )
    SWING_DAILY_DIR: Path = Path(
        os.getenv('SWING_DAILY_DIR', str(_PROJECT_ROOT / 'data' / 'swing' / 'daily'))
    )

    # 交易参数
    SWING_MAX_HOLD_DAYS: int = int(os.getenv('SWING_MAX_HOLD_DAYS', '10'))
    SWING_POOL_SIZE: int = int(os.getenv('SWING_POOL_SIZE', '3'))
    SWING_STOP_LOSS_PCT: float = float(os.getenv('SWING_STOP_LOSS_PCT', '0.95'))
    SWING_TAKE_PROFIT_PCT: float = float(os.getenv('SWING_TAKE_PROFIT_PCT', '1.10'))

    # 筛选参数
    SWING_MIN_PRICE: float = float(os.getenv('SWING_MIN_PRICE', '5.0'))
    SWING_MAX_PRICE: float = float(os.getenv('SWING_MAX_PRICE', '500.0'))
    SWING_MIN_DAILY_AMOUNT: float = float(os.getenv('SWING_MIN_DAILY_AMOUNT', '50000000'))

    # 因子权重
    SWING_W_TREND: float = float(os.getenv('SWING_W_TREND', '0.30'))
    SWING_W_MOMENTUM: float = float(os.getenv('SWING_W_MOMENTUM', '0.25'))
    SWING_W_VOLUME: float = float(os.getenv('SWING_W_VOLUME', '0.20'))
    SWING_W_RISK: float = float(os.getenv('SWING_W_RISK', '0.15'))
    SWING_W_MARKET: float = float(os.getenv('SWING_W_MARKET', '0.10'))

    @classmethod
    def validate(cls) -> List[str]:
        """验证配置，返回错误列表。空列表 = 全部通过。"""
        errors = []

        if not cls.TUSHARE_TOKEN:
            errors.append(
                "TUSHARE_TOKEN 未设置。请在 .env 文件中设置 TUSHARE_TOKEN=your_token"
            )

        if cls.MIN_CONFIDENCE_SCORE < 0 or cls.MIN_CONFIDENCE_SCORE > 1:
            errors.append("MIN_CONFIDENCE_SCORE 必须在 0-1 之间")

        if cls.STOP_LOSS_PCT <= 0 or cls.STOP_LOSS_PCT > 0.5:
            errors.append("STOP_LOSS_PCT 必须在 0-0.5 之间")

        if cls.TAKE_PROFIT_PCT <= 0:
            errors.append("TAKE_PROFIT_PCT 必须大于 0")

        if cls.MIN_RISK_REWARD_RATIO < 1:
            errors.append("MIN_RISK_REWARD_RATIO 必须 >= 1")

        if abs(cls.MOMENTUM_WEIGHT + cls.SENTIMENT_WEIGHT - 1.0) > 0.001:
            errors.append(
                f"MOMENTUM_WEIGHT + SENTIMENT_WEIGHT 必须 = 1.0，"
                f"当前: {cls.MOMENTUM_WEIGHT} + {cls.SENTIMENT_WEIGHT} = "
                f"{cls.MOMENTUM_WEIGHT + cls.SENTIMENT_WEIGHT}"
            )

        return errors

    @classmethod
    def print_summary(cls) -> None:
        """打印配置摘要（不泄露完整 token）。"""
        token_display = (
            f"{cls.TUSHARE_TOKEN[:8]}...{cls.TUSHARE_TOKEN[-4:]}"
            if len(cls.TUSHARE_TOKEN) > 12
            else "***"
        )
        print("=" * 60)
        print("决策支持系统配置 v9.0")
        print("=" * 60)
        print(f"TUSHARE_TOKEN:    {token_display}")
        print(f"项目根目录:       {cls.PROJECT_ROOT}")
        print(f"数据目录:         {cls.DATA_DIR}")
        print(f"分钟数据目录:     {cls.MINUTE_DATA_DIR}")
        print(f"反馈数据目录:     {cls.FEEDBACK_DIR}")
        print(f"排除市场:         {cls.EXCLUDE_MARKETS}")
        print(f"最大线程数:       {cls.MAX_WORKERS}")
        print(f"两维度权重:       动量={cls.MOMENTUM_WEIGHT}, 情绪={cls.SENTIMENT_WEIGHT}")
        print("=" * 60)


# 创建必要目录
for _dir in [Config.DATA_DIR, Config.MINUTE_DATA_DIR,
             Config.FEEDBACK_DIR, Config.REPORT_DIR,
             Config.SWING_DATA_DIR, Config.SWING_DAILY_DIR]:
    _dir.mkdir(exist_ok=True, parents=True)
