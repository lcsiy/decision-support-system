"""Debug: why did 2026-07-21 swing analysis produce zero picks?

用法: python tests/test_debug_0721.py   (手动调试脚本，非 pytest 测试)
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dss.config import Config
from dss.data_layer.tushare_client import TushareClient
from dss.decision_core.swing_screener import SwingScreener
from dss.analysis_engine.swing_trend import SwingTrendAnalyzer
from dss.analysis_engine.swing_momentum import SwingMomentumAnalyzer
from dss.analysis_engine.swing_volume import SwingVolumeAnalyzer
from dss.analysis_engine.swing_risk import SwingRiskAnalyzer
from dss.analysis_engine.swing_composite import SwingCompositeScorer
import pandas as pd

config = Config()
tc = TushareClient(config)
screener = SwingScreener(config, tc)

candidates = screener.screen(trade_date='20260721', limit=100)
print(f'\nScreener: {len(candidates)} candidates')

# Get index data
idx_df = tc.index_daily(ts_code='000001.SH', start_date=tc.days_ago_str(60), end_date='20260721')
if idx_df is not None:
    idx_df = idx_df.sort_values('trade_date')

# Analyzers
trend_a = SwingTrendAnalyzer()
momentum_a = SwingMomentumAnalyzer()
volume_a = SwingVolumeAnalyzer()
risk_a = SwingRiskAnalyzer()
composite_a = SwingCompositeScorer(config)

# Compute market env score (same logic as orchestrator)
def calc_market_score(idx_df):
    if idx_df is None or idx_df.empty or len(idx_df) < 20:
        return 50.0, "unknown", 0.0
    close = idx_df['close'].values
    s = pd.Series(close).rolling(20).mean()
    if len(s) < 2 or pd.isna(s.iloc[-1]):
        return 50.0, "unknown", 0.0
    latest_close = close[-1]
    ma20 = s.iloc[-1]
    pct = (latest_close - ma20) / ma20 * 100
    score = 50 + min(max(pct * 3, -40), 50)
    
    if pct > 3:
        sent = 'bullish'
    elif pct > 1:
        sent = 'slightly_bullish'
    elif pct > -1:
        sent = 'neutral'
    elif pct > -3:
        sent = 'slightly_bearish'
    else:
        sent = 'bearish'
    return score, sent, pct

market_env_score, mkt_sent, pct_vs_ma = calc_market_score(idx_df)
print(f'Market: score={market_env_score:.1f}, sentiment={mkt_sent}, price_vs_MA20={pct_vs_ma:.2f}%')

# Analyze candidates
scores = []
failures = 0
for c in candidates[:50]:
    try:
        df = tc.daily_with_ma(ts_code=c.ts_code, start_date=tc.days_ago_str(120), end_date='20260721')
        if df is None or df.empty or len(df) < 10:
            failures += 1
            continue
            
        trend = trend_a.analyze(df)
        momentum = momentum_a.analyze(df, idx_df)
        volume_res = volume_a.analyze(df)
        risk = risk_a.analyze(df, idx_df)
        
        comp = composite_a.compute(
            trend=trend, momentum=momentum, volume=volume_res,
            risk=risk, market_env_score=market_env_score
        )
        
        scores.append({
            'code': c.ts_code,
            'name': c.name,
            'price': c.current_price,
            'score': comp.overall_score,
            'T': comp.trend_score,
            'M': comp.momentum_score,
            'V': comp.volume_score,
            'R': comp.risk_score,
            'Mkt': comp.market_env_score,
        })
    except Exception as e:
        failures += 1

scores.sort(key=lambda x: x['score'], reverse=True)
print(f'\n=== Results ===')
print(f'Analyzed: {len(scores)}, Failed: {failures}')
if scores:
    print(f'Max score: {scores[0]["score"]:.1f}')
    print(f'Min score: {scores[-1]["score"]:.1f}')
    passing = [s for s in scores if s['score'] >= 55]
    print(f'Passing 55: {len(passing)} / {len(scores)}')
    print(f'\nTop 10:')
    for s in scores[:10]:
        print(f'  {s["code"]} {s["name"]}: {s["score"]:.1f} (T={s["T"]:.1f} M={s["M"]:.1f} V={s["V"]:.1f} R={s["R"]:.1f} Mkt={s["Mkt"]:.1f})')
    
    # Distribution
    bins = [0, 30, 40, 50, 55, 60, 70, 80, 100]
    for b in range(len(bins)-1):
        count = len([s for s in scores if bins[b] <= s['score'] < bins[b+1]])
        print(f'  [{bins[b]}-{bins[b+1]}): {count}')
