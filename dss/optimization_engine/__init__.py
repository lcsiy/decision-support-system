"""
优化引擎层 - 反馈优化闭环 v9.0

反馈闭环流程：
1. 尾盘分析后记录推荐股票、买入价、各项评分
2. 次日用分钟数据验证昨日推荐的实际表现
3. 基于盈亏反馈使用皮尔逊相关性优化维度权重
"""

from dss.optimization_engine.feedback_recorder import FeedbackRecorder, record_analysis_results
from dss.optimization_engine.feedback_verifier import FeedbackVerifier
from dss.optimization_engine.feedback_optimizer import FeedbackOptimizer, get_optimal_weights

__all__ = [
    'FeedbackRecorder',
    'record_analysis_results',
    'FeedbackVerifier',
    'FeedbackOptimizer',
    'get_optimal_weights',
]
