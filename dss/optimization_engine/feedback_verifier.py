#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
反馈验证器 - Feedback Verifier

功能：
1. 在次日11:00执行，读取昨日推荐股票记录
2. 读取当日9:30-11:00的分钟级数据
3. 检查每只推荐股票在此时间窗口内的最高价
4. 计算盈亏：max_profit = (最高价 - 买入价) / 买入价
5. 生成验证报告

验证窗口：次日9:30-11:00（上午交易前1.5小时）
盈利判断：期间最高价是否超过昨日买入价
"""

import json
import os
import sys
import io
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
import pandas as pd
import numpy as np


def _to_native(obj):
    """递归将numpy类型转换为Python原生类型，确保JSON可序列化"""
    if isinstance(obj, (np.integer,)):
        return int(obj)
    elif isinstance(obj, (np.floating,)):
        return float(obj)
    elif isinstance(obj, (np.bool_,)):
        return bool(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, dict):
        return {str(k): _to_native(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [_to_native(v) for v in obj]
    return obj


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


class FeedbackVerifier:
    """反馈验证器 - 验证昨日推荐的次日表现"""
    
    def __init__(self, data_dir: str = None, minute_data_dir: str = None):
        """
        初始化验证器
        
        Args:
            data_dir: feedback数据目录
            minute_data_dir: 分钟数据目录
        """
        if data_dir is None:
            # __file__ = .../dss/optimization_engine/feedback_verifier.py
            # project_root = 上两级目录 = decision-support-system/
            script_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(os.path.dirname(script_dir))
            data_dir = os.path.join(project_root, 'data', 'feedback')
        
        if minute_data_dir is None:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(os.path.dirname(script_dir))
            # 分钟数据存储在 data/minute_data/
            minute_data_dir = os.path.join(project_root, 'data', 'minute_data')
        
        self.data_dir = data_dir
        self.minute_data_dir = minute_data_dir
        os.makedirs(self.data_dir, exist_ok=True)
    
    def verify_yesterday_recommendations(
        self,
        reference_date: str = None,
        verification_date: str = None
    ) -> Dict[str, Any]:
        """
        验证昨日推荐的次日表现
        
        Args:
            reference_date: 参考日期（推荐日期），None则自动取最近
            verification_date: 验证日期，None则为今天
            
        Returns:
            dict: 验证结果
        """
        if verification_date is None:
            verification_date = datetime.now().strftime('%Y%m%d')
        
        # 加载推荐记录
        if reference_date is None:
            reference_date = self._find_yesterday_date(verification_date)
        
        if reference_date is None:
            print("[Feedback] 未找到昨日推荐记录")
            return self._empty_result(verification_date, "未找到昨日推荐记录")
        
        from .feedback_recorder import FeedbackRecorder
        recorder = FeedbackRecorder(data_dir=self.data_dir)
        rec_data = recorder.load_recommendations(reference_date)
        
        if rec_data is None:
            print(f"[Feedback] 无法加载 {reference_date} 的推荐数据")
            return self._empty_result(verification_date, f"无法加载 {reference_date} 的推荐数据")
        
        recommendations = rec_data.get('recommendations', [])
        
        if not recommendations:
            print(f"[Feedback] {reference_date} 无推荐股票")
            return self._empty_result(verification_date, f"{reference_date} 无推荐股票")
        
        print(f"\n{'='*80}")
        print(f"[Feedback] 验证 {reference_date} 推荐在 {verification_date} 的表现")
        print(f"   推荐股票数: {len(recommendations)}")
        print(f"   验证时间窗口: 09:30-11:00")
        print(f"{'='*80}")
        
        # 验证每只股票
        results = []
        for rec in recommendations:
            ts_code = rec.get('ts_code', '')
            name = rec.get('name', '')
            buy_price = rec.get('buy_price', 0)
            
            if isinstance(buy_price, str):
                try:
                    buy_price = float(buy_price)
                except (ValueError, TypeError):
                    buy_price = 0
            
            if buy_price <= 0:
                print(f"  [!] {name} ({ts_code}): 买入价无效，跳过")
                continue
            
            # 读取分钟数据
            minute_data = self._load_minute_data(ts_code, verification_date)
            
            if minute_data is None or minute_data.empty:
                print(f"  [!] {name} ({ts_code}): 无分钟数据")
                results.append({
                    'ts_code': ts_code, 'name': name, 'buy_price': buy_price,
                    'max_price_930_1100': None, 'max_profit_pct': None,
                    'is_profitable': None, 'status': 'no_data',
                    'comprehensive_score': rec.get('comprehensive_score', 0),
                    'dimension_scores': rec.get('dimension_scores', {}),
                    'high_open_probability': rec.get('prediction', {}).get('high_open_probability', 50)
                })
                continue
            
            # 过滤9:30-11:00的时间窗口
            window_data = self._filter_time_window(minute_data, '09:30', '11:00')
            
            if window_data.empty:
                print(f"  [!] {name} ({ts_code}): 时间窗口内无数据")
                results.append({
                    'ts_code': ts_code, 'name': name, 'buy_price': buy_price,
                    'max_price_930_1100': None, 'max_profit_pct': None,
                    'is_profitable': None, 'status': 'no_window_data',
                    'comprehensive_score': rec.get('comprehensive_score', 0),
                    'dimension_scores': rec.get('dimension_scores', {}),
                    'high_open_probability': rec.get('prediction', {}).get('high_open_probability', 50)
                })
                continue
            
            # 计算最高价和盈利
            max_price = window_data['price'].max()
            open_price = window_data['price'].iloc[0] if len(window_data) > 0 else buy_price
            
            max_profit_pct = (max_price - buy_price) / buy_price * 100
            open_gap = (open_price - buy_price) / buy_price * 100
            
            is_profitable = bool(max_profit_pct > 0)
            
            result = {
                'ts_code': ts_code,
                'name': name,
                'buy_price': float(buy_price),
                'open_price': float(open_price),
                'open_gap_pct': float(round(open_gap, 3)),
                'max_price_930_1100': float(max_price),
                'max_profit_pct': float(round(max_profit_pct, 3)),
                'is_profitable': is_profitable,
                'data_points': len(window_data),
                'status': 'verified',
                'comprehensive_score': rec.get('comprehensive_score', 0),
                'dimension_scores': rec.get('dimension_scores', {}),
                'capital_details': rec.get('capital_details', {}),
                'momentum_details': rec.get('momentum_details', {}),
                'sentiment_details': rec.get('sentiment_details', {}),
                'high_open_probability': rec.get('prediction', {}).get('high_open_probability', 50),
                'expected_open_change_pct': rec.get('prediction', {}).get('expected_open_change_pct', 0),
                'daily_change_pct': rec.get('daily_change_pct', 0)
            }
            
            results.append(result)
            
            status_icon = '+' if is_profitable else '-'
            print(f"  [{status_icon}] {name} ({ts_code}): "
                  f"买入价={buy_price:.2f}, 窗口最高={max_price:.2f}, "
                  f"盈利率={max_profit_pct:+.2f}%")
        
        # 生成汇总
        verified = [r for r in results if r.get('status') == 'verified']
        profitable = [r for r in verified if r.get('is_profitable', False)]
        loss = [r for r in verified if not r.get('is_profitable', True)]
        
        summary = {
            'reference_date': reference_date,
            'verification_date': verification_date,
            'total_recommended': int(len(recommendations)),
            'total_verified': int(len(verified)),
            'no_data': int(len(results) - len(verified)),
            'profitable_count': int(len(profitable)),
            'loss_count': int(len(loss)),
            'win_rate': float(round(len(profitable) / len(verified), 4)) if verified else 0.0,
            'avg_profit_pct': float(round(np.mean([r['max_profit_pct'] for r in profitable]), 3)) if profitable else 0.0,
            'avg_loss_pct': float(round(np.mean([r['max_profit_pct'] for r in loss]), 3)) if loss else 0.0,
            'max_single_profit_pct': float(round(max([r['max_profit_pct'] for r in verified]), 3)) if verified else 0.0,
            'max_single_loss_pct': float(round(min([r['max_profit_pct'] for r in verified]), 3)) if verified else 0.0,
            'overall_net_pct': float(round(sum([r['max_profit_pct'] for r in verified]), 3)) if verified else 0.0,
            'weights': rec_data.get('weights', {})
        }
        
        # 构建完整验证报告
        verification_report = {
            'summary': summary,
            'results': results
        }
        
        # 保存验证结果（转换numpy类型为Python原生类型）
        file_path = os.path.join(self.data_dir, f"{reference_date}_verification.json")
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(_to_native(verification_report), f, ensure_ascii=False, indent=2)
        
        print(f"\n[Feedback] 验证报告已保存: {file_path}")
        
        # 打印汇总
        self._print_summary(summary)
        
        return verification_report
    
    def _load_minute_data(self, ts_code: str, date_str: str) -> Optional[pd.DataFrame]:
        """加载指定股票指定日期的分钟数据"""
        file_code = ts_code.replace('.', '_')
        file_name = f"{date_str}_{file_code}.csv"
        file_path = os.path.join(self.minute_data_dir, file_name)
        
        if not os.path.exists(file_path):
            # 尝试前一天
            prev_date = (datetime.strptime(date_str, '%Y%m%d') - timedelta(days=1)).strftime('%Y%m%d')
            file_name = f"{prev_date}_{file_code}.csv"
            file_path = os.path.join(self.minute_data_dir, file_name)
            
            if not os.path.exists(file_path):
                return None
        
        try:
            df = pd.read_csv(file_path)
            if 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'])
            return df
        except Exception as e:
            print(f"  [!] 读取分钟数据失败 {ts_code}: {e}")
            return None
    
    def _filter_time_window(self, df: pd.DataFrame, 
                           start_time: str, end_time: str) -> pd.DataFrame:
        """过滤时间窗口内的数据
        
        v8.5.1 修复：从数据中推断日期，而非使用datetime.now()。
        解决验证器在11:00执行时回退加载昨日数据，时间窗口日期不匹配的问题。
        """
        if 'timestamp' not in df.columns:
            if 'time' in df.columns:
                df = df.copy()
                today = datetime.now().strftime('%Y-%m-%d')
                df['timestamp'] = pd.to_datetime(
                    today + ' ' + df['time'].astype(str),
                    errors='coerce'
                )
            else:
                return df
        
        # 从数据中推断实际日期（而非datetime.now()）
        if 'timestamp' in df.columns and len(df) > 0:
            sample_ts = df['timestamp'].iloc[0]
            if hasattr(sample_ts, 'strftime'):
                data_date = sample_ts.strftime('%Y-%m-%d')
            else:
                data_date = str(sample_ts)[:10]
        else:
            data_date = datetime.now().strftime('%Y-%m-%d')
        
        start_dt = pd.to_datetime(f"{data_date} {start_time}:00")
        end_dt = pd.to_datetime(f"{data_date} {end_time}:00")
        
        mask = (df['timestamp'] >= start_dt) & (df['timestamp'] <= end_dt)
        return df[mask]
    
    def _find_yesterday_date(self, today_str: str) -> Optional[str]:
        """查找最近的交易日推荐记录"""
        files = [f for f in os.listdir(self.data_dir) 
                if f.endswith('_recommendations.json') and not f.startswith('optimized')]
        
        if not files:
            return None
        
        dates = []
        for f in files:
            date_str = f.split('_')[0]
            if date_str != today_str and len(date_str) == 8:
                dates.append(date_str)
        
        dates.sort(reverse=True)
        return dates[0] if dates else None
    
    def _empty_result(self, date: str, reason: str) -> Dict[str, Any]:
        """生成空结果"""
        return {
            'summary': {
                'reference_date': None,
                'verification_date': date,
                'total_recommended': 0,
                'total_verified': 0,
                'no_data': 0,
                'profitable_count': 0,
                'loss_count': 0,
                'win_rate': 0,
                'error': reason
            },
            'results': []
        }
    
    def _print_summary(self, summary: Dict[str, Any]):
        """打印验证汇总"""
        print(f"\n{'='*80}")
        print(f"[Feedback] 验证汇总")
        print(f"{'='*80}")
        print(f"   推荐日期: {summary.get('reference_date', 'N/A')}")
        print(f"   验证日期: {summary.get('verification_date', 'N/A')}")
        print(f"   验证成功: {summary.get('total_verified', 0)}/{summary.get('total_recommended', 0)}")
        print(f"   盈利股票: {summary.get('profitable_count', 0)} 只  (胜率: {summary.get('win_rate', 0)*100:.1f}%)")
        print(f"   亏损股票: {summary.get('loss_count', 0)} 只")
        print(f"   平均盈利: {summary.get('avg_profit_pct', 0):+.2f}%")
        print(f"   平均亏损: {summary.get('avg_loss_pct', 0):+.2f}%")
        print(f"   最大盈利: {summary.get('max_single_profit_pct', 0):+.2f}%")
        print(f"   最大亏损: {summary.get('max_single_loss_pct', 0):+.2f}%")
        print(f"   总净收益: {summary.get('overall_net_pct', 0):+.2f}%")
        print(f"{'='*80}")
    
    def load_all_verification_history(self) -> List[Dict[str, Any]]:
        """加载所有历史验证结果"""
        history = []
        
        files = [f for f in os.listdir(self.data_dir) 
                if f.endswith('_verification.json')]
        
        for f in files:
            file_path = os.path.join(self.data_dir, f)
            try:
                with open(file_path, 'r', encoding='utf-8') as fp:
                    data = json.load(fp)
                    history.append(data)
            except Exception as e:
                print(f"[Feedback] 读取 {f} 失败: {e}")
        
        history.sort(key=lambda x: x.get('summary', {}).get('reference_date', ''), reverse=True)
        return history


# =========================================================================
# 便捷函数
# =========================================================================

def verify_yesterday(
    data_dir: str = None,
    minute_data_dir: str = None,
    reference_date: str = None
) -> Dict[str, Any]:
    """便捷函数：验证昨日推荐"""
    verifier = FeedbackVerifier(data_dir=data_dir, minute_data_dir=minute_data_dir)
    return verifier.verify_yesterday_recommendations(reference_date=reference_date)
