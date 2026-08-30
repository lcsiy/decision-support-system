#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
反馈闭环运行器 - Feedback Loop Runner

完整的反馈闭环流程：
1. 运行超短线尾盘分析 → 自动记录推荐结果（买入价+各项评分）
2. [次日11:00] 验证推荐表现（用9:30-11:00分钟数据）
3. 基于盈亏反馈 → 使用皮尔逊相关性优化三维度权重

使用方式：
# 完整流程（运行分析 + 记录反馈）
python -m dss.optimization_engine.run_feedback_loop --mode analyze

# 仅验证（次日11:00执行）
python -m dss.optimization_engine.run_feedback_loop --mode verify

# 验证 + 优化（默认模式）
python -m dss.optimization_engine.run_feedback_loop --mode verify-optimize

# 仅优化（基于已有历史数据）
python -m dss.optimization_engine.run_feedback_loop --mode optimize

# 查看历史统计
python -m dss.optimization_engine.run_feedback_loop --mode stats
"""

import sys
import os
import json
import argparse
import traceback
from datetime import datetime, timedelta
from typing import Dict, Any, List

# 修复Windows控制台编码问题（安全处理stdout管道场景）
if sys.platform == 'win32':
    try:
        if hasattr(sys.stdout, 'reconfigure') and not sys.stdout.closed and sys.stdout.isatty():
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# 添加项目根目录到Python路径
_sys_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(os.path.dirname(_sys_dir))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from dss.optimization_engine.feedback_recorder import FeedbackRecorder
from dss.optimization_engine.feedback_verifier import FeedbackVerifier
from dss.optimization_engine.feedback_optimizer import FeedbackOptimizer, get_optimal_weights


def run_analysis_and_record(
    top_n: int = 5,
    hot_limit: int = 300,
    min_liquidity: float = 10000000,
    use_minute_data: bool = True,
    use_optimized_weights: bool = True
) -> Dict[str, Any]:
    """
    运行尾盘分析并记录反馈数据
    """
    print("=" * 80)
    print("[Feedback Loop] 运行分析并记录")
    print(f"   时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)
    
    # 加载优化权重
    weights = None
    if use_optimized_weights:
        optimizer = FeedbackOptimizer()
        weights = optimizer.get_current_optimal_weights()
        optim_params = optimizer.load_optimized_params()
        if optim_params:
            print(f"[Feedback] 使用优化权重: {weights}")
            print(f"   优化日期: {optim_params.get('last_optimized', 'N/A')}")
            print(f"   样本数: {optim_params.get('sample_count', 0)}")
        else:
            print(f"[Feedback] 无优化参数，使用默认权重: {weights}")
    
    # 导入并运行超短线尾盘分析器 (v9.0 编排器)
    from dss.config import Config
    from dss.interface_layer.tail_analysis import TailAnalysisOrchestrator

    config = Config()
    orchestrator = TailAnalysisOrchestrator(config)

    # 覆盖 min_liquidity
    config.DEFAULT_MIN_LIQUIDITY = min_liquidity

    recommendations = orchestrator.run(
        top_n=top_n,
        hot_limit=hot_limit,
        use_minute_data=use_minute_data,
    )

    # 生成报告
    report = orchestrator.reporter.format_human(
        recommendations, orchestrator.market_env
    )
    print("\n" + report)
    
    # 如果使用了优化权重，计算优化后的综合评分
    if weights:
        for rec in recommendations:
            dim_scores = rec.get('dimension_scores', {})
            optimized_score = (
                dim_scores.get('technical_momentum', 0) * weights.get('technical_momentum', 0.60) +
                dim_scores.get('sentiment', 0) * weights.get('sentiment', 0.40)
            )
            rec['comprehensive_score_optimized'] = optimized_score
            print(f"  [Feedback] {rec['name']}: 原始评分={rec['comprehensive_score']:.1f}, "
                  f"优化评分={optimized_score:.1f}")
    
    # 记录反馈数据
    recorder = FeedbackRecorder()
    file_path = recorder.record_recommendations(
        recommendations,
        weights=weights or {
            'technical_momentum': 0.60,
            'sentiment': 0.40,
        }
    )
    
    print(f"\n[Feedback Loop] 分析完成，推荐记录: {file_path}")
    
    return {
        'status': 'success',
        'recommendations_count': len(recommendations),
        'feedback_file': file_path,
        'weights_used': weights
    }


def run_verification(reference_date: str = None) -> Dict[str, Any]:
    """运行验证（次日11:00执行）"""
    print("=" * 80)
    print("[Feedback Loop] 验证昨日推荐表现")
    print(f"   时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)
    
    verifier = FeedbackVerifier()
    result = verifier.verify_yesterday_recommendations(reference_date=reference_date)
    return result


def run_verify_and_optimize(reference_date: str = None) -> Dict[str, Any]:
    """验证并优化（完整的次日流程）"""
    # 1. 验证
    verification = run_verification(reference_date=reference_date)
    
    # 2. 优化
    print(f"\n{'='*80}")
    print(f"[Feedback Loop] 基于验证结果优化参数")
    print(f"{'='*80}")
    
    optimizer = FeedbackOptimizer()
    optimization = optimizer.optimize_weights()
    
    result = {
        'status': 'success',
        'verification': verification,
        'optimization': optimization,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    
    _print_feedback_summary(verification, optimization)
    return result


def run_stats() -> Dict[str, Any]:
    """查看历史统计"""
    print("=" * 80)
    print("[Feedback Loop] 历史统计")
    print(f"   时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)
    
    verifier = FeedbackVerifier()
    history = verifier.load_all_verification_history()
    
    if not history:
        print("\n[Feedback] 无历史验证数据")
        return {'status': 'no_data'}
    
    total_recommended = 0
    total_verified = 0
    total_profitable = 0
    all_profits = []
    
    for report in history:
        summary = report.get('summary', {})
        total_recommended += summary.get('total_recommended', 0)
        total_verified += summary.get('total_verified', 0)
        total_profitable += summary.get('profitable_count', 0)
        
        for r in report.get('results', []):
            if r.get('max_profit_pct') is not None:
                all_profits.append(r['max_profit_pct'])
    
    print(f"\n[Feedback] 累计统计 (共 {len(history)} 天):")
    print(f"{'='*60}")
    print(f"   累计推荐: {total_recommended} 只")
    print(f"   累计验证: {total_verified} 只")
    print(f"   累计盈利: {total_profitable} 只")
    
    if total_verified > 0:
        win_rate = total_profitable / total_verified * 100
        print(f"   总胜率: {win_rate:.1f}%")
    
    if all_profits:
        avg_profit = sum(all_profits) / len(all_profits)
        print(f"   平均收益: {avg_profit:+.2f}%")
        print(f"   最大收益: {max(all_profits):+.2f}%")
        print(f"   最大亏损: {min(all_profits):+.2f}%")
    
    # 每日详情
    print(f"\n[Feedback] 每日详情:")
    for report in history[:10]:
        s = report.get('summary', {})
        ref_date = s.get('reference_date', 'N/A')
        win_rate = s.get('win_rate', 0) * 100
        verified = s.get('total_verified', 0)
        profitable = s.get('profitable_count', 0)
        net = s.get('overall_net_pct', 0)
        
        icon = '+' if net > 0 else '-'
        print(f"   [{icon}] {ref_date}: {profitable}/{verified} 盈利, "
              f"胜率={win_rate:.0f}%, 净收益={net:+.2f}%")
    
    # 查看优化参数
    optimizer = FeedbackOptimizer()
    optim_params = optimizer.load_optimized_params()
    if optim_params:
        print(f"\n[Feedback] 当前优化权重:")
        weights = optim_params.get('weights', {})
        for dim, w in weights.items():
            print(f"   {dim}: {w:.2%}")
        print(f"   优化日期: {optim_params.get('last_optimized', 'N/A')}")
        print(f"   样本数: {optim_params.get('sample_count', 0)}")
    
    return {
        'status': 'success',
        'total_days': len(history),
        'total_recommended': total_recommended,
        'total_verified': total_verified,
        'total_profitable': total_profitable,
        'avg_profit': sum(all_profits) / len(all_profits) if all_profits else 0
    }


def _print_feedback_summary(verification: Dict[str, Any], optimization: Dict[str, Any]):
    """打印反馈闭环综合报告"""
    print(f"\n{'='*80}")
    print(f"[Feedback Loop] 反馈闭环综合报告")
    print(f"{'='*80}")
    
    v_summary = verification.get('summary', {})
    o_weights = optimization.get('optimized_weights', {})
    o_corrs = optimization.get('correlations', {})
    o_orig = optimization.get('original_weights', {})
    
    print(f"\n   验证结果:")
    print(f"   胜率: {v_summary.get('win_rate', 0)*100:.1f}%")
    print(f"   盈利: {v_summary.get('profitable_count', 0)}/{v_summary.get('total_verified', 0)}")
    print(f"   净收益: {v_summary.get('overall_net_pct', 0):+.3f}%")
    
    print(f"\n   权重优化:")
    print(f"   维度          原权重  ->  新权重    相关性")
    print(f"   {'-'*45}")
    for dim in o_weights:
        orig = o_orig.get(dim, 0)
        new = o_weights.get(dim, 0)
        corr = o_corrs.get(dim, 0)
        arrow = '>>' if new > orig else '<<' if new < orig else '=='
        print(f"   {dim:<14} {orig:.2%}  {arrow}  {new:.2%}   {corr:+.4f}")
    
    print(f"\n   样本数: {optimization.get('sample_count', 0)}")
    print(f"   状态: {optimization.get('status', 'N/A')}")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='反馈闭环运行器 - 超短线尾盘分析反馈优化系统'
    )
    parser.add_argument(
        '--mode', 
        type=str, 
        default='verify-optimize',
        choices=['analyze', 'verify', 'verify-optimize', 'optimize', 'stats'],
        help='运行模式'
    )
    parser.add_argument('--top', type=int, default=5, help='返回前N名股票')
    parser.add_argument('--hot-limit', type=int, default=300, help='热榜数量限制')
    parser.add_argument('--min-liquidity', type=float, default=10000000, help='最小流动性')
    parser.add_argument('--no-optimized-weights', action='store_true', help='不使用优化权重')
    parser.add_argument('--reference-date', type=str, default=None, help='参考日期 YYYYMMDD')
    parser.add_argument('--no-minute-data', action='store_true', help='禁用分钟数据')
    
    args = parser.parse_args()
    
    print("=" * 80)
    print("[Feedback Loop] 反馈闭环系统 v1.0")
    print(f"   运行模式: {args.mode}")
    print(f"   时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)
    
    try:
        if args.mode == 'analyze':
            result = run_analysis_and_record(
                top_n=args.top,
                hot_limit=args.hot_limit,
                min_liquidity=args.min_liquidity,
                use_minute_data=not args.no_minute_data,
                use_optimized_weights=not args.no_optimized_weights
            )
            
        elif args.mode == 'verify':
            result = run_verification(reference_date=args.reference_date)
            
        elif args.mode == 'verify-optimize':
            result = run_verify_and_optimize(reference_date=args.reference_date)
            
        elif args.mode == 'optimize':
            optimizer = FeedbackOptimizer()
            result = optimizer.optimize_weights()
            
        elif args.mode == 'stats':
            result = run_stats()
            
        print(f"\n[Feedback Loop] 完成: {result.get('status', 'unknown')}")
            
    except Exception as e:
        print(f"\n[Feedback Loop] 执行失败: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
