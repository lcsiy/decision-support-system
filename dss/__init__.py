"""
决策支持系统 (Decision Support System) v9.0

A股实盘交易辅助系统，提供超短线尾盘分析、分钟级数据采集和反馈优化闭环。

架构分层：
- data_layer:     数据层 - 统一Tushare访问、热榜获取、分钟数据管理
- analysis_engine: 分析引擎层 - 技术动量、情绪面分析、开盘预测、风险评估
- decision_core:  决策核心层 - 交易计划生成、股票筛选
- optimization_engine: 优化引擎层 - 反馈记录、验证、权重优化
- interface_layer: 接口层 - CLI编排器、报告格式化
"""

__version__ = "9.0.0"
