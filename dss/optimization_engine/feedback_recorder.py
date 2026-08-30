#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
反馈记录器 - Feedback Recorder

功能：
1. 在超短线尾盘分析完成后，将推荐结果持久化保存
2. 保存每只推荐股票的买入价（分析时的当前价格）和各项评分
3. 保存当前使用的维度权重

数据格式：JSON
存储位置：../data/feedback/YYYYMMDD_recommendations.json
"""

import json
import os
import sys
import io
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

# 修复Windows控制台编码问题（安全处理stdout管道场景）
if sys.platform == 'win32':
    try:
        if hasattr(sys.stdout, 'reconfigure') and not sys.stdout.closed:
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


class FeedbackRecorder:
    """反馈记录器 - 持久化尾盘分析推荐结果"""
    
    def __init__(self, data_dir: str = None):
        """
        初始化记录器
        
        Args:
            data_dir: feedback数据目录，None则自动推断
        """
        if data_dir is None:
            # __file__ = .../dss/optimization_engine/feedback_recorder.py
            # project_root = 上两级 = decision-support-system/
            script_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(os.path.dirname(script_dir))
            data_dir = os.path.join(project_root, 'data', 'feedback')
        
        self.data_dir = data_dir
        os.makedirs(self.data_dir, exist_ok=True)
    
    def record_recommendations(
        self,
        recommendations: List[Dict[str, Any]],
        weights: Dict[str, float] = None,
        analysis_date: str = None
    ) -> str:
        """
        记录分析推荐结果
        
        Args:
            recommendations: 推荐股票列表（来自analyze_market_opportunities的返回结果）
            weights: 当前维度权重，默认使用标准权重
            analysis_date: 分析日期，None则使用当天
            
        Returns:
            str: 保存的文件路径
        """
        if weights is None:
            weights = {
                'technical_momentum': 0.60,
                'sentiment': 0.40
            }
        
        if analysis_date is None:
            analysis_date = datetime.now().strftime('%Y%m%d')
        
        # 提取关键信息
        recorded = []
        for rec in recommendations:
            if rec.get('excluded', False):
                continue
            
            # 提取买入价
            buy_price = rec.get('current_price', 0)
            if isinstance(buy_price, str):
                try:
                    buy_price = float(buy_price)
                except (ValueError, TypeError):
                    buy_price = 0
            
            # 提取各维度评分
            dim_scores = rec.get('dimension_scores', {})
            momentum_details = rec.get('momentum_details', {})
            sentiment_details = rec.get('sentiment_details', {})
            prediction = rec.get('next_day_prediction', {})
            risk = rec.get('risk_assessment', {})
            plan = rec.get('trading_plan', {})
            
            record = {
                'rank': len(recorded) + 1,
                'ts_code': rec.get('ts_code', ''),
                'name': rec.get('name', ''),
                'buy_price': buy_price,
                'daily_change_pct': rec.get('daily_change_pct', 0),
                'comprehensive_score': rec.get('comprehensive_score', 0),
                'dimension_scores': {
                    'technical_momentum': dim_scores.get('technical_momentum', 0),
                    'sentiment': dim_scores.get('sentiment', 0)
                },
                'momentum_details': {
                    'daily_change_pct': momentum_details.get('daily_change_pct', 0),
                    'price_position': momentum_details.get('price_position', 0.5),
                    'recent_trend': momentum_details.get('recent_trend', 0),
                    'minute_data_available': momentum_details.get('minute_data_available', False),
                    'tail_volume_price_signal': momentum_details.get('tail_volume_price_signal', 0.0),
                    'volume_trend': momentum_details.get('volume_trend', 'N/A')
                },
                'sentiment_details': {
                    'hot_rank': sentiment_details.get('hot_rank', 0),
                    'rank_score': sentiment_details.get('rank_score', 50),
                    'change_sentiment': sentiment_details.get('change_sentiment', 'N/A')
                },
                'prediction': {
                    'high_open_probability': prediction.get('high_open_probability', 50),
                    'expected_open_change_pct': prediction.get('expected_open_change_pct', 0)
                },
                'risk': {
                    'risk_score': risk.get('risk_score', 50),
                    'risk_level': risk.get('risk_level', 'N/A')
                },
                'trading_plan': {
                    'recommendation': plan.get('recommendation', 'N/A'),
                    'confidence': plan.get('confidence', 'N/A'),
                    'stop_loss_price': plan.get('stop_loss_price', 'N/A'),
                    'position_pct': plan.get('position_pct', 'N/A')
                },
                'analysis_time': rec.get('analysis_time', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            }
            
            recorded.append(record)
        
        # 构建完整记录
        feedback_data = {
            'date': analysis_date,
            'analysis_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'total_recommendations': len(recorded),
            'weights': weights,
            'recommendations': recorded
        }
        
        # 保存为JSON
        file_path = os.path.join(self.data_dir, f"{analysis_date}_recommendations.json")
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(feedback_data, f, ensure_ascii=False, indent=2)
        
        print(f"\n[Feedback] 反馈数据已记录: {file_path}")
        print(f"   推荐股票数: {len(recorded)}")
        if recorded:
            print(f"   最佳推荐: {recorded[0]['name']} ({recorded[0]['ts_code']})")
            print(f"   买入价: {recorded[0]['buy_price']:.2f}元")
            print(f"   综合评分: {recorded[0]['comprehensive_score']:.1f}")
        
        # 同时保存次日必采集白名单，确保验证时有分钟数据
        self._save_verification_watchlist(recorded, analysis_date)
        
        return file_path
    
    def _save_verification_watchlist(self, recorded: List[Dict], analysis_date: str):
        """
        保存次日必采集白名单
        
        将今日推荐股票写入白名单，供次日分钟数据采集器读取，
        确保反馈闭环的验证环节有分钟数据可用。
        
        Args:
            recorded: 已记录的推荐列表
            analysis_date: 分析日期（推荐日期）
        """
        watchlist_path = os.path.join(self.data_dir, 'verification_watchlist.json')
        
        # 计算次日日期
        try:
            next_date_dt = datetime.strptime(analysis_date, '%Y%m%d')
            next_date = (next_date_dt + timedelta(days=1)).strftime('%Y%m%d')
        except ValueError:
            next_date = (datetime.now() + timedelta(days=1)).strftime('%Y%m%d')
        
        watchlist = {
            'target_date': next_date,
            'source_date': analysis_date,
            'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'stocks': [
                {
                    'ts_code': r['ts_code'],
                    'name': r['name'],
                    'buy_price': r['buy_price'],
                    'rank': r['rank']
                }
                for r in recorded
            ]
        }
        
        with open(watchlist_path, 'w', encoding='utf-8') as f:
            json.dump(watchlist, f, ensure_ascii=False, indent=2)
        
        print(f"[Feedback] 次日验证白名单已保存: {watchlist_path}")
        print(f"   目标日期: {next_date}, 白名单股票: {len(watchlist['stocks'])} 只")
    
    def load_recommendations(self, date_str: str) -> Optional[Dict[str, Any]]:
        """加载指定日期的推荐记录"""
        file_path = os.path.join(self.data_dir, f"{date_str}_recommendations.json")
        
        if not os.path.exists(file_path):
            print(f"[Feedback] 未找到 {date_str} 的推荐记录: {file_path}")
            return None
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data
        except Exception as e:
            print(f"[Feedback] 加载推荐记录失败: {e}")
            return None
    
    def get_latest_recommendation_date(self) -> Optional[str]:
        """获取最近的推荐记录日期"""
        files = [f for f in os.listdir(self.data_dir) 
                if f.endswith('_recommendations.json')]
        
        if not files:
            return None
        
        dates = [f.split('_')[0] for f in files]
        dates.sort(reverse=True)
        return dates[0]


# =========================================================================
# 便捷函数 - 供外部调用
# =========================================================================

def record_analysis_results(
    recommendations: List[Dict[str, Any]],
    weights: Dict[str, float] = None,
    data_dir: str = None
) -> str:
    """
    便捷函数：记录分析结果
    
    可在 ultra_short_tail_analysis.py 中调用：
        from dss.optimization_engine.feedback_recorder import record_analysis_results
        record_analysis_results(recommendations)
    """
    recorder = FeedbackRecorder(data_dir=data_dir)
    return recorder.record_recommendations(recommendations, weights=weights)
