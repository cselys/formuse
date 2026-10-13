"""
Historical Signal Evaluation and Forward Return Analysis module for stock_scanner.
Evaluates scanner states and score buckets across historical dates against forward returns (+1D, +5D, +10D, +20D).
Strictly enforces no lookahead bias.
"""

import os
import logging
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from typing import TYPE_CHECKING, Optional, List, Dict, Any
if TYPE_CHECKING:
    from stock_scanner.src.scanner import StockScanner

logger = logging.getLogger("stock_scanner.historical_eval")


class HistoricalEvaluator:
    """Performs historical signal evaluation and forward return analysis."""

    def __init__(self, scanner: "StockScanner"):
        self.scanner = scanner

    def evaluate_historical_dates(self, symbols: list[str], dates: list[str]) -> dict:
        """
        Evaluate scanner signals on specific historical dates using only data up to each date,
        then calculate forward returns (+1D, +5D, +10D, +20D).
        """
        all_signals = []

        for symbol in symbols:
            try:
                # Download full history once for symbol
                df_full = self.scanner.loader.download_ticker(symbol)
                from stock_scanner.src.data.market_calendar import session_dates, uses_completed_weeks
                if uses_completed_weeks(self.scanner.config):
                    df_full = df_full.set_axis(session_dates(df_full))
                if df_full.empty or len(df_full) < 100:
                    continue

                for d_str in dates:
                    d_dt = pd.to_datetime(d_str)
                    # Slice data up to d_dt (no lookahead)
                    df_slice = df_full[df_full.index <= d_dt]
                    if len(df_slice) < 60:
                        continue

                    # Ensure the slice ends on or very close to d_str (within 5 calendar days)
                    last_bar_date = df_slice.index[-1]
                    if (d_dt - last_bar_date).days > 5:
                        continue

                    # Run analysis on df_slice
                    try:
                        record = self._analyze_slice_for_symbol(symbol, df_slice, d_str)
                        if not record:
                            continue

                        # Calculate forward returns from d_str
                        future_df = df_full[df_full.index > df_slice.index[-1]]
                        fwd_returns = self._calculate_forward_returns(future_df, record['daily']['close'])

                        signal_record = {
                            'date': d_str,
                            'symbol': symbol,
                            'category': record['category'],
                            'state': record['state'],
                            'trend_score': record['trend_score'],
                            'bottom_score': record['bottom_score'],
                            'reversal_score': record['reversal_score'],
                            'setup_quality': record['setup_quality'],
                            **fwd_returns
                        }
                        all_signals.append(signal_record)

                    except Exception as e:
                        logger.debug(f"Error evaluating {symbol} on {d_str}: {e}")

            except Exception as e:
                logger.warning(f"Failed historical evaluation for {symbol}: {e}")

        df_signals = pd.DataFrame(all_signals)
        return self._aggregate_statistics(df_signals)

    def _analyze_slice_for_symbol(self, symbol: str, df_slice: pd.DataFrame, as_of_date: str) -> Optional[dict]:
        """Run scanner analysis on a sliced dataframe without lookahead."""
        from stock_scanner.src.analysis.daily import run_daily_analysis
        from stock_scanner.src.analysis.weekly import run_weekly_analysis
        from stock_scanner.src.analysis.relative_strength import calculate_relative_strength
        from stock_scanner.src.analysis.regime import classify_state
        from stock_scanner.src.scoring.trend_score import calculate_trend_score
        from stock_scanner.src.scoring.bottom_score import calculate_bottom_score
        from stock_scanner.src.scoring.reversal_score import calculate_reversal_score
        from stock_scanner.src.scoring.setup_quality import calculate_setup_quality

        # Download SPY slice for benchmark
        try:
            df_spy_full = self.scanner.loader.download_ticker('SPY')
            from stock_scanner.src.data.market_calendar import session_dates, uses_completed_weeks
            if uses_completed_weeks(self.scanner.config):
                df_spy_full = df_spy_full.set_axis(session_dates(df_spy_full))
            df_spy_slice = df_spy_full[df_spy_full.index <= pd.to_datetime(as_of_date)]
        except Exception:
            df_spy_slice = df_slice

        try:
            df_daily_analyzed, daily_indicators = run_daily_analysis(df_slice, self.scanner.config)
            from stock_scanner.src.data.market_calendar import completed_weekly, uses_completed_weeks
            df_weekly = (completed_weekly(df_slice, as_of_date) if uses_completed_weeks(self.scanner.config)
                         else self.scanner.loader.resample_to_weekly(df_slice, as_of_date=as_of_date, drop_partial=True))
            weekly_indicators = run_weekly_analysis(df_weekly, self.scanner.config)
            rs_analysis = calculate_relative_strength(df_slice, df_spy_slice, periods=[20, 60])
            structure_analysis = daily_indicators.get('structure', {})

            trend_score, trend_breakdown = calculate_trend_score(weekly_indicators, daily_indicators, structure_analysis, rs_analysis, self.scanner.config)
            bottom_score, _ = calculate_bottom_score(daily_indicators, structure_analysis, rs_analysis, df_slice, self.scanner.config)
            reversal_score, _ = calculate_reversal_score(daily_indicators, weekly_indicators, structure_analysis, rs_analysis, self.scanner.config)
            setup_quality, setup_details = calculate_setup_quality(daily_indicators, structure_analysis, self.scanner.config)

            state = classify_state(trend_score, bottom_score, reversal_score, daily_indicators, weekly_indicators, structure_analysis, rs_analysis, self.scanner.config)

            return {
                'symbol': symbol,
                'category': 'evaluated',
                'state': state,
                'trend_score': trend_score,
                'bottom_score': bottom_score,
                'reversal_score': reversal_score,
                'setup_quality': setup_quality,
                'daily': daily_indicators,
                'weekly': weekly_indicators
            }
        except Exception as e:
            return None

    def _calculate_forward_returns(self, future_df: pd.DataFrame, entry_price: float) -> dict:
        """Calculate forward returns (+1D, +5D, +10D, +20D)."""
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

    def _aggregate_statistics(self, df_signals: pd.DataFrame) -> dict:
        """Aggregate statistics by state and score buckets."""
        if df_signals.empty:
            return {'signals_count': 0, 'states': {}, 'score_buckets': {}}

        state_stats = {}
        for state, group in df_signals.groupby('state'):
            state_stats[state] = {
                'count': len(group),
                'avg_fwd_5d': float(group['fwd_5d'].mean()) if not group['fwd_5d'].isna().all() else 0.0,
                'avg_fwd_10d': float(group['fwd_10d'].mean()) if not group['fwd_10d'].isna().all() else 0.0,
                'avg_fwd_20d': float(group['fwd_20d'].mean()) if not group['fwd_20d'].isna().all() else 0.0,
                'win_rate_5d': float((group['fwd_5d'] > 0).mean() * 100.0) if not group['fwd_5d'].isna().all() else 0.0
            }

        # Score buckets
        bins = [0, 50, 60, 70, 80, 90, 100]
        labels = ['0-49', '50-59', '60-69', '70-79', '80-89', '90-100']
        df_signals['score_bucket'] = pd.cut(df_signals['trend_score'], bins=bins, labels=labels, include_lowest=True)

        bucket_stats = {}
        for bucket, group in df_signals.groupby('score_bucket', observed=False):
            if len(group) > 0:
                bucket_stats[str(bucket)] = {
                    'count': len(group),
                    'avg_fwd_10d': float(group['fwd_10d'].mean()) if not group['fwd_10d'].isna().all() else 0.0,
                    'win_rate_10d': float((group['fwd_10d'] > 0).mean() * 100.0) if not group['fwd_10d'].isna().all() else 0.0
                }

        return {
            'signals_count': len(df_signals),
            'states': state_stats,
            'score_buckets': bucket_stats,
            'raw_signals': df_signals
        }
