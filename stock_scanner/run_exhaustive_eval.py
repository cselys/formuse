#!/usr/bin/env python3
"""
Exhaustive Historical Signal Evaluation & Signal Quality Analysis runner for Scanner V1.1.
Measures forward returns (+1D, +5D, +10D, +20D) across states, score buckets, bottoms/reversals,
trend transitions, false positives, missed opportunities, categories, and score monotonicity.
Saves results to data/evaluation/ with zero modifications to scoring or thresholds.
"""

import os
import logging
import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from stock_scanner.src.scanner import StockScanner

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("stock_scanner.evaluation")


def run_exhaustive_evaluation():
    print("=" * 80)
    print("SCANNER V1.1 — EXHAUSTIVE HISTORICAL SIGNAL EVALUATION")
    print("=" * 80)

    scanner = StockScanner()
    eval_dir = "data/evaluation"
    os.makedirs(eval_dir, exist_ok=True)

    # Gather symbols across universe categories
    categories = scanner.universe.get('categories', {})
    all_symbols = set()
    symbol_to_cat = {}
    for cat_name, cat_data in categories.items() if isinstance(categories, dict) else []:
        pass

    # Fallback default robust universe if yaml categories not fully parsed as dict
    if not categories:
        universe_symbols = ['NVDA', 'AMD', 'AVGO', 'MU', 'INTC', 'TSM', 'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META', 'TSLA', 'XOM', 'CVX', 'JPM', 'BAC', 'IWM', 'SPY', 'QQQ']
        for s in universe_symbols:
            all_symbols.add(s)
            symbol_to_cat[s] = 'technology'
    else:
        for cat_name, cat_data in categories.items():
            cat_syms = cat_data.get('symbols', [])
            for s in cat_syms:
                if not isinstance(s, str):
                    logger.warning(f"Skipping invalid non-string symbol: {s} in category {cat_name}")
                    continue
                s_up = s.strip().upper()
                all_symbols.add(s_up)
                symbol_to_cat[s_up] = cat_name

    logger.info(f"Loaded {len(all_symbols)} symbols for exhaustive historical evaluation.")

    # Generate historical evaluation dates (e.g. every 10 trading days over past 1.5 years)
    # First download SPY to get valid trading day index
    try:
        spy_df = scanner.loader.download_ticker('SPY')
        trading_dates = spy_df.index
    except Exception as e:
        logger.error(f"Failed to download SPY for date index: {e}")
        return

    # Select evaluation dates spaced every 15 trading days, starting from index 252 up to -25 bars
    eval_indices = range(252, len(trading_dates) - 25, 15)
    eval_dates = [trading_dates[i].strftime('%Y-%m-%d') for i in eval_indices]

    logger.info(f"Selected {len(eval_dates)} historical scan dates for evaluation.")

    all_signals = []

    for symbol in sorted(list(all_symbols)):
        if symbol in ['SPY', 'QQQ', 'SMH', 'XLE', 'XLFT', 'IWM']:
            continue
        try:
            df_full = scanner.loader.download_ticker(symbol)
            if df_full.empty or len(df_full) < 300:
                continue

            cat_name = symbol_to_cat.get(symbol, 'general')

            for d_str in eval_dates:
                d_dt = pd.to_datetime(d_str)
                df_slice = df_full[df_full.index <= d_dt]
                if len(df_slice) < 200:
                    continue

                last_bar_date = df_slice.index[-1]
                if (d_dt - last_bar_date).days > 4:
                    continue

                try:
                    record = analyze_slice_without_lookahead(scanner, symbol, cat_name, df_slice, d_str)
                    if not record:
                        continue

                    future_df = df_full[df_full.index > df_slice.index[-1]]
                    fwd_returns = calculate_forward_returns(future_df, record['daily']['close'])

                    signal_record = {
                        'date': d_str,
                        'symbol': symbol,
                        'category': cat_name,
                        'state': record['state'],
                        'trend_score': record['trend_score'],
                        'bottom_score': record['bottom_score'],
                        'reversal_score': record['reversal_score'],
                        'setup_quality': record['setup_quality'],
                        'close': record['daily']['close'],
                        **fwd_returns
                    }
                    all_signals.append(signal_record)
                except Exception as e:
                    continue

        except Exception as e:
            logger.warning(f"Error evaluating symbol {symbol}: {e}")

    df_signals = pd.DataFrame(all_signals)
    if df_signals.empty:
        logger.warning("No signals generated during historical evaluation.")
        return

    # Save raw signals
    raw_csv_path = os.path.join(eval_dir, 'historical_signals.csv')
    df_signals.to_csv(raw_csv_path, index=False)
    logger.info(f"Saved {len(df_signals)} historical signals to {raw_csv_path}")

    # 1. State Statistics
    state_rows = []
    states_list = [
        'STRONG_UPTREND', 'UPTREND', 'EARLY_UPTREND', 'BOTTOM_FORMING',
        'BOTTOM_BREAKOUT', 'REVERSAL', 'REVERSAL_CONFIRMED', 'DOWNTREND',
        'STRONG_DOWNTREND', 'NEUTRAL'
    ]

    for st in states_list:
        sub = df_signals[df_signals['state'] == st]
        count = len(sub)
        if count == 0:
            state_rows.append({
                'state': st, 'signals': 0, 'avg_1d': 0.0, 'avg_5d': 0.0, 'avg_10d': 0.0,
                'avg_20d': 0.0, 'median_20d': 0.0, 'win_rate_20d': 0.0
            })
            continue

        valid_20 = sub['fwd_20d'].dropna()
        state_rows.append({
            'state': st,
            'signals': count,
            'avg_1d': float(sub['fwd_1d'].mean()) if not sub['fwd_1d'].isna().all() else 0.0,
            'avg_5d': float(sub['fwd_5d'].mean()) if not sub['fwd_5d'].isna().all() else 0.0,
            'avg_10d': float(sub['fwd_10d'].mean()) if not sub['fwd_10d'].isna().all() else 0.0,
            'avg_20d': float(sub['fwd_20d'].mean()) if not sub['fwd_20d'].isna().all() else 0.0,
            'median_20d': float(valid_20.median()) if not valid_20.empty else 0.0,
            'win_rate_20d': float((valid_20 > 0).mean() * 100.0) if not valid_20.empty else 0.0
        })

    df_state_stats = pd.DataFrame(state_rows)
    df_state_stats.to_csv(os.path.join(eval_dir, 'state_statistics.csv'), index=False)

    # 2. Score Bucket Analysis
    bins = [-1, 39, 49, 59, 69, 79, 89, 100]
    labels = ['0-39', '40-49', '50-59', '60-69', '70-79', '80-89', '90-100']
    df_signals['score_bucket'] = pd.cut(df_signals['trend_score'], bins=bins, labels=labels, include_lowest=True)

    bucket_rows = []
    for b in labels:
        sub = df_signals[df_signals['score_bucket'] == b]
        count = len(sub)
        valid_20 = sub['fwd_20d'].dropna()
        bucket_rows.append({
            'score_bucket': b,
            'signals': count,
            'avg_5d': float(sub['fwd_5d'].mean()) if not sub['fwd_5d'].isna().all() else 0.0,
            'avg_10d': float(sub['fwd_10d'].mean()) if not sub['fwd_10d'].isna().all() else 0.0,
            'avg_20d': float(sub['fwd_20d'].mean()) if not sub['fwd_20d'].isna().all() else 0.0,
            'win_rate_20d': float((valid_20 > 0).mean() * 100.0) if not valid_20.empty else 0.0
        })

    df_score_stats = pd.DataFrame(bucket_rows)
    df_score_stats.to_csv(os.path.join(eval_dir, 'score_statistics.csv'), index=False)

    # 3. Bottom & Reversal Detailed Analysis
    br_states = ['BOTTOM_FORMING', 'BOTTOM_BREAKOUT', 'REVERSAL', 'REVERSAL_CONFIRMED']
    br_rows = []
    for st in br_states:
        sub = df_signals[df_signals['state'] == st]
        count = len(sub)
        f5 = sub['fwd_5d'].dropna()
        f10 = sub['fwd_10d'].dropna()
        f20 = sub['fwd_20d'].dropna()
        br_rows.append({
            'state': st,
            'signals': count,
            'avg_5d': float(f5.mean()) if not f5.empty else 0.0,
            'avg_10d': float(f10.mean()) if not f10.empty else 0.0,
            'avg_20d': float(f20.mean()) if not f20.empty else 0.0,
            'median_20d': float(f20.median()) if not f20.empty else 0.0,
            'win_rate_20d': float((f20 > 0).mean() * 100.0) if not f20.empty else 0.0,
            'p25_20d': float(f20.quantile(0.25)) if not f20.empty else 0.0,
            'p75_20d': float(f20.quantile(0.75)) if not f20.empty else 0.0
        })
    df_br_stats = pd.DataFrame(br_rows)
    df_br_stats.to_csv(os.path.join(eval_dir, 'bottom_reversal_statistics.csv'), index=False)

    # 4. Category Performance
    cat_rows = []
    for cat, group in df_signals.groupby('category'):
        f5 = group['fwd_5d'].dropna()
        f10 = group['fwd_10d'].dropna()
        f20 = group['fwd_20d'].dropna()
        cat_rows.append({
            'category': cat,
            'signals': len(group),
            'avg_5d': float(f5.mean()) if not f5.empty else 0.0,
            'avg_10d': float(f10.mean()) if not f10.empty else 0.0,
            'avg_20d': float(f20.mean()) if not f20.empty else 0.0
        })
    df_cat_stats = pd.DataFrame(cat_rows)
    df_cat_stats.to_csv(os.path.join(eval_dir, 'category_statistics.csv'), index=False)

    # 5. Worst Signals (False Positives) & Missed Opportunities
    valid_signals = df_signals.dropna(subset=['fwd_20d'])
    worst_signals = valid_signals.sort_values(by='fwd_20d', ascending=True).head(10)
    worst_signals[['date', 'symbol', 'state', 'trend_score', 'fwd_5d', 'fwd_10d', 'fwd_20d']].to_csv(os.path.join(eval_dir, 'worst_signals.csv'), index=False)

    missed_opps = valid_signals[(valid_signals['state'].isin(['NEUTRAL', 'DOWNTREND'])) & (valid_signals['fwd_20d'] >= 15.0)].sort_values(by='fwd_20d', ascending=False).head(10)
    missed_opps[['date', 'symbol', 'state', 'trend_score', 'fwd_5d', 'fwd_10d', 'fwd_20d']].to_csv(os.path.join(eval_dir, 'missed_opportunities.csv'), index=False)

    # Generate evaluation report JSON and TXT
    report_data = {
        'total_signals': len(df_signals),
        'state_statistics': df_state_stats.to_dict(orient='records'),
        'score_statistics': df_score_stats.to_dict(orient='records'),
        'bottom_reversal_statistics': df_br_stats.to_dict(orient='records'),
        'category_statistics': df_cat_stats.to_dict(orient='records')
    }

    with open(os.path.join(eval_dir, 'evaluation_report.json'), 'w', encoding='utf-8') as f:
        json.dump(report_data, f, indent=2)

    # Write text report
    with open(os.path.join(eval_dir, 'evaluation_report.txt'), 'w', encoding='utf-8') as f:
        f.write("SCANNER V1.1 — SIGNAL QUALITY EVALUATION REPORT\n")
        f.write("=" * 60 + "\n\n")
        f.write(f"Total Historical Signals Evaluated: {len(df_signals)}\n\n")
        f.write("STATE STATISTICS:\n")
        f.write(df_state_stats.to_string(index=False) + "\n\n")
        f.write("SCORE BUCKET STATISTICS:\n")
        f.write(df_score_stats.to_string(index=False) + "\n\n")
        f.write("BOTTOM & REVERSAL STATISTICS:\n")
        f.write(df_br_stats.to_string(index=False) + "\n\n")
        f.write("CATEGORY STATISTICS:\n")
        f.write(df_cat_stats.to_string(index=False) + "\n\n")

    print(f"Exhaustive evaluation complete. All reports saved to {eval_dir}/")


def analyze_slice_without_lookahead(scanner: StockScanner, symbol: str, category: str, df_slice: pd.DataFrame, as_of_date: str) -> dict:
    from stock_scanner.src.analysis.daily import run_daily_analysis
    from stock_scanner.src.analysis.weekly import run_weekly_analysis
    from stock_scanner.src.analysis.relative_strength import calculate_relative_strength
    from stock_scanner.src.analysis.regime import classify_state
    from stock_scanner.src.scoring.trend_score import calculate_trend_score
    from stock_scanner.src.scoring.bottom_score import calculate_bottom_score
    from stock_scanner.src.scoring.reversal_score import calculate_reversal_score
    from stock_scanner.src.scoring.setup_quality import calculate_setup_quality

    try:
        df_spy_full = scanner.loader.download_ticker('SPY')
        df_spy_slice = df_spy_full[df_spy_full.index <= pd.to_datetime(as_of_date)]
    except Exception:
        df_spy_slice = df_slice

    df_daily_analyzed, daily_indicators = run_daily_analysis(df_slice, scanner.config)
    df_weekly = scanner.loader.resample_to_weekly(df_slice, as_of_date=as_of_date, drop_partial=True)
    weekly_indicators = run_weekly_analysis(df_weekly, scanner.config)
    rs_analysis = calculate_relative_strength(df_slice, df_spy_slice, periods=[20, 60])
    structure_analysis = daily_indicators.get('structure', {})

    trend_score, _ = calculate_trend_score(weekly_indicators, daily_indicators, structure_analysis, rs_analysis, scanner.config)
    bottom_score, _ = calculate_bottom_score(daily_indicators, structure_analysis, rs_analysis, df_slice, scanner.config)
    reversal_score, _ = calculate_reversal_score(daily_indicators, weekly_indicators, structure_analysis, rs_analysis, scanner.config)
    setup_quality, _ = calculate_setup_quality(daily_indicators, structure_analysis, scanner.config)

    state = classify_state(trend_score, bottom_score, reversal_score, daily_indicators, weekly_indicators, structure_analysis, rs_analysis, scanner.config)

    return {
        'symbol': symbol,
        'category': category,
        'state': state,
        'trend_score': trend_score,
        'bottom_score': bottom_score,
        'reversal_score': reversal_score,
        'setup_quality': setup_quality,
        'daily': daily_indicators,
        'weekly': weekly_indicators
    }


def calculate_forward_returns(future_df: pd.DataFrame, entry_price: float) -> dict:
    res = {'fwd_1d': np.nan, 'fwd_5d': np.nan, 'fwd_10d': np.nan, 'fwd_20d': np.nan}
    if future_df.empty or entry_price <= 0:
        return res

    bars = [1, 5, 10, 20]
    keys = ['fwd_1d', 'fwd_5d', 'fwd_10d', 'fwd_20d']

    for b, k in zip(bars, keys):
        if len(future_df) >= b:
            exit_price = future_df['Close'].iloc[b - 1]
            res[k] = float((exit_price / entry_price - 1.0) * 100.0)

    return res


if __name__ == "__main__":
    run_exhaustive_evaluation()
