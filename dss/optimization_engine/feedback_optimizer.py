#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
反馈优化器 - Feedback Optimizer

功能：
1. 基于历史验证数据，分析各维度评分与实际盈利的相关性
2. 使用皮尔逊相关系数驱动权重调整
3. 渐进式学习率，避免权重剧烈波动
4. 单维度权重安全边界：[0.10, 0.60]
5. 权重归一化确保总和 = 1.0

优化触发条件：最少5个样本才开始优化
"""

import json
import os
import sys
import io
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
import numpy as np

# 修复Windows控制台编码问题（安全处理stdout管道场景）
if sys.platform == 'win32':
    try:
        if hasattr(sys.stdout, 'reconfigure') and not sys.stdout.closed:
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        try:
            if hasattr(sys.stdout, 'buffer') and sys.stdout.buffer:
                import io as _io
                old_stdout = sys.stdout
                sys.stdout = _io.TextIOWrapper(
                    sys.stdout.buffer.detach(), encoding='utf-8', errors='replace', line_buffering=True
                )
        except Exception:
            pass


class FeedbackOptimizer:
    """反馈优化器 - 基于历史盈亏反馈优化分析参数"""
    
    def __init__(self, data_dir: str = None):
        """
        初始化优化器
        
        Args:
            data_dir: feedback数据目录
        """
        if data_dir is None:
            # __file__ = .../dss/optimization_engine/feedback_optimizer.py
            # project_root = 上两级目录 = decision-support-system/
            script_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(os.path.dirname(script_dir))
            data_dir = os.path.join(project_root, 'data', 'feedback')
        
        self.data_dir = data_dir
        os.makedirs(self.data_dir, exist_ok=True)
        
        # 优化参数
        self.learning_rate = 0.10    # 学习率
        self.min_samples = 5         # 最少样本数
        self.weight_bounds = (0.10, 0.60)  # 权重边界
        
        # 默认权重（v8.8: 两维度）
        self.default_weights = {
            'technical_momentum': 0.60,
            'sentiment': 0.40
        }
    
    def optimize_weights(
        self, 
        current_weights: Dict[str, float] = None,
        history_limit: int = 30
    ) -> Dict[str, Any]:
        """
        优化维度权重
        
        基于历史盈亏反馈，调整各维度的权重。
        相关性越高的维度，权重越应该增加。
        
        Args:
            current_weights: 当前权重，None则使用默认
            history_limit: 使用最近N条验证记录
            
        Returns:
            dict: 优化结果，包含新权重和分析数据
        """
        if current_weights is None:
            current_weights = self.default_weights.copy()
        
        # 加载历史验证数据
        from .feedback_verifier import FeedbackVerifier
        verifier = FeedbackVerifier(data_dir=self.data_dir)
        history = verifier.load_all_verification_history()
        
        if not history:
            print("[Feedback] 无历史验证数据，使用默认权重")
            return {
                'optimized_weights': current_weights.copy(),
                'original_weights': current_weights.copy(),
                'adjustments': {},
                'correlations': {},
                'sample_count': 0,
                'optimization_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'status': 'no_data'
            }
        
        # 收集样本数据
        samples = self._collect_samples(history, limit=history_limit)
        
        if len(samples) < self.min_samples:
            print(f"[Feedback] 样本数不足 ({len(samples)}/{self.min_samples})，保持当前权重")
            return {
                'optimized_weights': current_weights.copy(),
                'original_weights': current_weights.copy(),
                'adjustments': {},
                'correlations': {},
                'sample_count': len(samples),
                'optimization_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'status': 'insufficient_samples'
            }
        
        print(f"\n[Feedback] 基于 {len(samples)} 条历史记录优化权重")
        print(f"{'='*60}")
        
        # 计算各维度评分与盈利的相关性
        dimensions = list(current_weights.keys())
        correlations = {}
        
        for dim in dimensions:
            corr = self._calculate_dimension_correlation(samples, dim)
            correlations[dim] = corr
            print(f"   维度 '{dim}': 相关性 = {corr:+.4f}")
        
        # 计算调整量
        avg_corr = np.mean(list(correlations.values()))
        adjustments = {}
        new_weights = {}
        
        for dim in dimensions:
            corr_diff = correlations[dim] - avg_corr
            adjustment = self.learning_rate * corr_diff * current_weights[dim]
            
            # 负相关惩罚加倍
            if correlations[dim] < 0:
                adjustment = adjustment * 1.5
            
            new_weight = current_weights[dim] + adjustment
            adjustments[dim] = round(adjustment, 6)
            new_weights[dim] = new_weight
        
        # 边界约束
        for dim in dimensions:
            new_weights[dim] = np.clip(
                new_weights[dim], 
                self.weight_bounds[0], 
                self.weight_bounds[1]
            )
        
        # 归一化
        total = sum(new_weights.values())
        if total > 0:
            for dim in dimensions:
                new_weights[dim] = round(new_weights[dim] / total, 4)
        
        # 构建优化结果
        optimization_result = {
            'optimized_weights': new_weights,
            'original_weights': current_weights,
            'adjustments': adjustments,
            'correlations': {k: round(v, 4) for k, v in correlations.items()},
            'sample_count': len(samples),
            'learning_rate': self.learning_rate,
            'optimization_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'status': 'optimized'
        }
        
        # 保存优化后的参数
        self._save_optimized_params(optimization_result)
        
        # 打印优化结果
        print(f"\n[Feedback] 权重优化结果:")
        print(f"{'维度':<25} {'原权重':>8} {'新权重':>8} {'调整':>10} {'相关性':>10}")
        print(f"{'-'*65}")
        for dim in dimensions:
            print(f"  {dim:<23} {current_weights[dim]:>8.4f} {new_weights[dim]:>8.4f} "
                  f"{adjustments[dim]:>+10.4f} {correlations[dim]:>+10.4f}")
        print(f"{'-'*65}")
        print(f"  总计{'':19} {sum(current_weights.values()):>8.4f} {sum(new_weights.values()):>8.4f}")
        
        self._print_optimization_insight(new_weights, correlations, current_weights)
        
        return optimization_result
    
    def _collect_samples(
        self, 
        history: List[Dict[str, Any]], 
        limit: int = 30
    ) -> List[Dict[str, Any]]:
        """从历史验证数据收集样本"""
        samples = []
        
        for report in history[:limit]:
            for result in report.get('results', []):
                if result.get('status') != 'verified':
                    continue
                if result.get('max_profit_pct') is None:
                    continue
                
                dim_scores = result.get('dimension_scores', {})
                if not dim_scores:
                    continue
                
                sample = {
                    'ts_code': result.get('ts_code', ''),
                    'name': result.get('name', ''),
                    'profit_pct': result.get('max_profit_pct', 0),
                    'comprehensive_score': result.get('comprehensive_score', 0),
                    'momentum_score': dim_scores.get('technical_momentum', 50),
                    'sentiment_score': dim_scores.get('sentiment', 50),
                }
                samples.append(sample)
        
        return samples
    
    def _calculate_dimension_correlation(
        self, 
        samples: List[Dict[str, Any]], 
        dim: str
    ) -> float:
        """计算某维度评分与盈利的皮尔逊相关系数"""
        score_key_map = {
            'technical_momentum': 'momentum_score',
            'sentiment': 'sentiment_score'
        }
        
        score_key = score_key_map.get(dim)
        if score_key is None:
            return 0.0
        
        scores = np.array([s[score_key] for s in samples])
        profits = np.array([s['profit_pct'] for s in samples])
        
        valid_mask = ~(np.isnan(scores) | np.isnan(profits))
        scores = scores[valid_mask]
        profits = profits[valid_mask]
        
        if len(scores) < 3:
            return 0.0
        
        try:
            corr = np.corrcoef(scores, profits)[0, 1]
            if np.isnan(corr):
                return 0.0
            return float(corr)
        except Exception:
            return 0.0
    
    def _save_optimized_params(self, result: Dict[str, Any]):
        """保存优化参数到文件"""
        file_path = os.path.join(self.data_dir, 'optimized_params.json')
        
        params = {
            'weights': result['optimized_weights'],
            'correlations': result['correlations'],
            'sample_count': result['sample_count'],
            'last_optimized': result['optimization_time'],
            'original_weights': result['original_weights']
        }
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(params, f, ensure_ascii=False, indent=2)
        
        print(f"\n[Feedback] 优化参数已保存: {file_path}")
    
    def load_optimized_params(self) -> Optional[Dict[str, Any]]:
        """加载优化后的参数"""
        file_path = os.path.join(self.data_dir, 'optimized_params.json')
        
        if not os.path.exists(file_path):
            return None
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                params = json.load(f)
            return params
        except Exception as e:
            print(f"[Feedback] 加载优化参数失败: {e}")
            return None
    
    def _print_optimization_insight(
        self, 
        new_weights: Dict[str, float], 
        correlations: Dict[str, float],
        old_weights: Dict[str, float]
    ):
        """打印优化洞察"""
        print(f"\n[Feedback] 优化洞察:")
        
        best_dim = max(new_weights, key=new_weights.get)
        worst_dim = min(new_weights, key=new_weights.get)
        
        print(f"   最强预测维度: {best_dim} (权重 {new_weights[best_dim]:.2%})")
        print(f"   最弱预测维度: {worst_dim} (权重 {new_weights[worst_dim]:.2%})")
        
        max_change = max(abs(new_weights[d] - old_weights[d]) for d in new_weights)
        if max_change > 0.05:
            print(f"   [!] 权重变化显著 (最大 {max_change:.2%})，系统正在自适应调整")
        elif max_change > 0.02:
            print(f"   [~] 权重微调中 (最大 {max_change:.2%})")
        else:
            print(f"   [OK] 权重基本稳定")
        
        avg_corr = np.mean(list(correlations.values()))
        if avg_corr > 0.3:
            print(f"   [+] 整体预测能力较强 (平均相关性 {avg_corr:+.3f})")
        elif avg_corr > 0.1:
            print(f"   [~] 整体预测能力一般 (平均相关性 {avg_corr:+.3f})")
        else:
            print(f"   [-] 整体预测能力较弱 (平均相关性 {avg_corr:+.3f})，需要更多数据")
    
    def get_current_optimal_weights(self) -> Dict[str, float]:
        """获取当前最优权重（优先使用优化后的，否则用默认）"""
        params = self.load_optimized_params()
        if params and 'weights' in params:
            return params['weights']
        return self.default_weights.copy()


# =========================================================================
# 便捷函数
# =========================================================================

def optimize_analysis_weights(
    current_weights: Dict[str, float] = None,
    data_dir: str = None
) -> Dict[str, Any]:
    """便捷函数：优化分析权重"""
    optimizer = FeedbackOptimizer(data_dir=data_dir)
    return optimizer.optimize_weights(current_weights=current_weights)


def get_optimal_weights(data_dir: str = None) -> Dict[str, float]:
    """便捷函数：获取最优权重"""
    optimizer = FeedbackOptimizer(data_dir=data_dir)
    return optimizer.get_current_optimal_weights()
