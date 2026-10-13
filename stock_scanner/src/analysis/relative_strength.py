"""
Relative Strength calculations for stock_scanner.
Computes RS against market (SPY/QQQ) and category benchmarks over 20 and 60 days.
"""

import pandas as pd
import numpy as np


def calculate_relative_strength(
    df_stock: pd.DataFrame,
    df_benchmark: pd.DataFrame,
    periods: list[int] = [20, 60]
) -> dict:
    """
    Calculate relative strength: stock return - benchmark return over specified periods.
    Also returns raw returns and RS trend.
    """
    if df_stock.empty or df_benchmark.empty:
        return {
            'rs_20d': 0.0,
            'rs_60d': 0.0,
            'stock_return_20d': 0.0,
            'benchmark_return_20d': 0.0,
            'stock_return_60d': 0.0,
            'benchmark_return_60d': 0.0,
            'rs_trend': 'neutral'
        }

    # Align dates between stock and benchmark
    aligned = pd.DataFrame({
        'stock': df_stock['Close'],
        'benchmark': df_benchmark['Close']
    }).dropna()

    if len(aligned) < 60:
        # Fallback if less than 60 bars
        periods = [p for p in periods if p < len(aligned)]
        if not periods:
            return {
                'rs_20d': 0.0,
                'rs_60d': 0.0,
                'stock_return_20d': 0.0,
                'benchmark_return_20d': 0.0,
                'stock_return_60d': 0.0,
                'benchmark_return_60d': 0.0,
                'rs_trend': 'neutral'
            }

    rs_results = {}
    returns = {}

    for p in periods:
        if len(aligned) >= p + 1:
            stock_ret = (aligned['stock'].iloc[-1] / aligned['stock'].iloc[-1 - p] - 1.0) * 100.0
            bench_ret = (aligned['benchmark'].iloc[-1] / aligned['benchmark'].iloc[-1 - p] - 1.0) * 100.0
            rs_val = stock_ret - bench_ret
            rs_results[f'rs_{p}d'] = float(rs_val)
            returns[f'stock_return_{p}d'] = float(stock_ret)
            returns[f'benchmark_return_{p}d'] = float(bench_ret)
        else:
            rs_results[f'rs_{p}d'] = 0.0
            returns[f'stock_return_{p}d'] = 0.0
            returns[f'benchmark_return_{p}d'] = 0.0

    # Ensure keys exist
    for p in [20, 60]:
        if f'rs_{p}d' not in rs_results:
            rs_results[f'rs_{p}d'] = 0.0
        if f'stock_return_{p}d' not in returns:
            returns[f'stock_return_{p}d'] = 0.0
        if f'benchmark_return_{p}d' not in returns:
            returns[f'benchmark_return_{p}d'] = 0.0

    # Determine RS trend (e.g. 20d RS > 0 and higher than 60d RS or positive)
    rs_20 = rs_results['rs_20d']
    rs_60 = rs_results['rs_60d']
    if rs_20 > 0 and rs_20 >= rs_60:
        rs_trend = 'improving_strong'
    elif rs_20 > 0:
        rs_trend = 'positive'
    elif rs_20 < 0 and rs_20 > rs_60:
        rs_trend = 'recovering'
    else:
        rs_trend = 'lagging'

    return {
        'rs_20d': rs_results['rs_20d'],
        'rs_60d': rs_results['rs_60d'],
        'stock_return_20d': returns['stock_return_20d'],
        'benchmark_return_20d': returns['benchmark_return_20d'],
        'stock_return_60d': returns['stock_return_60d'],
        'benchmark_return_60d': returns['benchmark_return_60d'],
        'rs_trend': rs_trend
    }
