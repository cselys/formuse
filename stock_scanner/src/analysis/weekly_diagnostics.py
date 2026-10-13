"""Descriptive weekly diagnostics, independent of scoring formulas."""
import math

import pandas as pd

from stock_scanner.src.analysis.weekly import run_weekly_analysis
from stock_scanner.src.indicators.structure import analyze_market_structure


def direction(indicators, slow='ema40'):
    values = [indicators.get(k) for k in ('close', 'ema20', slow, 'ema20_slope')]
    if any(v is None or not math.isfinite(v) for v in values):
        return 'INSUFFICIENT_DATA'
    close, fast, slow_value, slope = values
    if min(close, fast, slow_value) <= 0:
        return 'INSUFFICIENT_DATA'
    if close > fast > slow_value and slope > 0:
        return 'UP'
    if close < fast < slow_value and slope < 0:
        return 'DOWN'
    return 'MIXED'


def weekly_relative_strength(stock, benchmark, week_end):
    result = {}
    for n in (4, 12):
        start = pd.Timestamp(week_end) - pd.Timedelta(weeks=n)
        end = pd.Timestamp(week_end)
        value = None
        if benchmark is not None and all(t in stock.index and t in benchmark.index for t in (start, end)):
            s0, s1 = stock.loc[start, 'Close'], stock.loc[end, 'Close']
            b0, b1 = benchmark.loc[start, 'Close'], benchmark.loc[end, 'Close']
            if min(s0, s1, b0, b1) > 0:
                value = float(100 * (s1 / s0 - b1 / b0))
        result[f'rs_{n}w'] = value
    return result


def weekly_diagnostics(weekly, daily_indicators, config, context, market=None, category=None):
    end = pd.Timestamp(context['week_end'])
    previous_end = end - pd.Timedelta(weeks=1)
    available = not weekly.empty and weekly.index[-1] == end
    minimum = max(config['indicators']['weekly']['ema_periods']) + 3
    expected = pd.date_range(end=end, periods=minimum, freq='W-FRI')
    ready = available and expected.isin(weekly.index).all()
    values = run_weekly_analysis(weekly, config) if ready else {}
    previous = run_weekly_analysis(weekly.iloc[:-1], config) if ready else {}
    weekly_direction = direction(values) if ready else 'INSUFFICIENT_DATA'
    daily_direction = direction(daily_indicators, 'ema50')
    alignment = {
        ('UP', 'UP'): 'ALIGNED_UP', ('DOWN', 'DOWN'): 'ALIGNED_DOWN',
        ('UP', 'DOWN'): 'PULLBACK_IN_WEEKLY_UPTREND',
        ('DOWN', 'UP'): 'RECOVERY_IN_WEEKLY_DOWNTREND',
    }.get((weekly_direction, daily_direction), 'MIXED')
    if 'INSUFFICIENT_DATA' in (weekly_direction, daily_direction):
        alignment = 'INSUFFICIENT_DATA'
    change = None
    if available and previous_end in weekly.index:
        change = float((weekly.loc[end, 'Close'] / weekly.loc[previous_end, 'Close'] - 1) * 100)
    structure = analyze_market_structure(weekly) if ready else {}
    # Compare against 20 PRIOR bars (the legacy daily helper excludes one).
    if ready:
        prior = weekly.iloc[-21:-1]
        structure['recent_breakout'] = bool(weekly.Close.iloc[-1] > prior.High.max())
        structure['recent_breakdown'] = bool(weekly.Close.iloc[-1] < prior.Low.min())
    return {
        'week_end': context['week_end'], 'last_session': context['last_session'],
        'data_week_end': str(weekly.index[-1].date()) if not weekly.empty else None,
        'status': 'STALE_OR_MISSING' if not available else ('OK' if ready else 'INSUFFICIENT_HISTORY'),
        'weekly_change_pct': change,
        'weekly_close': float(weekly.Close.iloc[-1]) if available else None,
        'weekly_direction': weekly_direction, 'daily_direction': daily_direction,
        'alignment': alignment, 'indicators': values,
        'rsi_change': values['rsi'] - previous['rsi'] if ready else None,
        'macd_hist_change': values['macd_hist'] - previous['macd_hist'] if ready else None,
        'structure': structure,
        'relative_strength_market': weekly_relative_strength(weekly, market, end),
        'relative_strength_category': weekly_relative_strength(weekly, category, end),
    }
