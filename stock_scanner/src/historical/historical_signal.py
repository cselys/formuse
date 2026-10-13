"""
Historical signal generation module for walk-forward validation.
Executes point-in-time scanning across historical dates without lookahead bias.
"""

import os
import logging
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

from stock_scanner.src.scanner import StockScanner
from stock_scanner.src.analysis.daily import run_daily_analysis
from stock_scanner.src.analysis.weekly import run_weekly_analysis
from stock_scanner.src.analysis.relative_strength import calculate_relative_strength
from stock_scanner.src.analysis.regime import classify_state, detect_market_regime
from stock_scanner.src.scoring.trend_score import calculate_trend_score
from stock_scanner.src.scoring.bottom_score import calculate_bottom_score
from stock_scanner.src.scoring.reversal_score import calculate_reversal_score
from stock_scanner.src.scoring.entry_quality import calculate_entry_quality
from stock_scanner.src.scoring.candidate_score import calculate_candidate_score
from stock_scanner.src.data.market_calendar import completed_weekly, schedule as market_schedule, uses_completed_weeks, session_dates

logger = logging.getLogger("stock_scanner.historical.signal")


class HistoricalSignalGenerator:
    """Generates historical point-in-time scanner signals across scheduled walk-forward dates."""

    def __init__(self, scanner: Optional[StockScanner] = None, output_dir: str = "data/evaluation/walk_forward"):
        self.scanner = scanner or StockScanner()
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def generate_schedule(self, start_date: str, end_date: str, frequency: str = "month_end") -> List[str]:
        """Generate a schedule of historical scan dates (default month-end trading days)."""
        start_dt = pd.to_datetime(start_date)
        end_dt = pd.to_datetime(end_date)

        # Get SPY trading calendar or date range
        try:
            spy_df = self.scanner.loader.download_ticker('SPY')
            trading_dates = session_dates(spy_df) if uses_completed_weeks(self.scanner.config) else spy_df.index
        except Exception:
            # Fallback business days
            trading_dates = pd.date_range(start=start_dt, end=end_dt, freq='B')

        schedule = []
        if frequency == "month_end":
            # Group by year-month and pick the last available trading day in each month
            df_dates = pd.DataFrame({'date': trading_dates})
            df_dates['ym'] = df_dates['date'].dt.to_period('M')
            month_ends = df_dates.groupby('ym')['date'].max().tolist()
            schedule = [d.strftime('%Y-%m-%d') for d in month_ends if start_dt <= d <= end_dt]
        elif frequency == "weekly":
            if uses_completed_weeks(self.scanner.config):
                cal = market_schedule(str(start_dt.to_period('W-FRI').start_time.date()),
                               str(end_dt.to_period('W-FRI').end_time.date()))
                week_ends = cal.groupby(cal.index.to_period('W-FRI')).tail(1).index
                weekly_dates = [d for d in week_ends if start_dt <= d <= end_dt and d in trading_dates]
            else:
                weekly_dates = [d for d in trading_dates if d.weekday() == 4 and start_dt <= d <= end_dt]
            schedule = [d.strftime('%Y-%m-%d') for d in weekly_dates]
        else:
            # Monthly or custom
            schedule = [d.strftime('%Y-%m-%d') for d in trading_dates if start_dt <= d <= end_dt and d.day >= 25]

        logger.info(f"Generated historical scan schedule with {len(schedule)} dates from {start_date} to {end_date}.")
        return sorted(schedule)

    def run_walk_forward_scan(self, start_date: str = "2025-01-01", end_date: str = "2026-07-31", frequency: str = "month_end") -> pd.DataFrame:
        """
        Run walk-forward historical scan across scheduled dates, enforcing strict point-in-time cutoffs.
        """
        schedule = self.generate_schedule(start_date, end_date, frequency)
        if not schedule:
            logger.warning("Empty scan schedule generated.")
            return pd.DataFrame()

        categories = self.scanner.universe.get('categories', {})
        symbol_to_cat = {}
        all_symbols = set()

        for cat_name, cat_data in categories.items():
            bench = cat_data.get('benchmark', 'QQQ')
            all_symbols.add(bench)
            for s in cat_data.get('symbols', []):
                s_up = s.strip().upper()
                all_symbols.add(s_up)
                symbol_to_cat[s_up] = cat_name

        for bench in self.scanner.universe.get('market_benchmarks', ['SPY', 'QQQ']):
            all_symbols.add(bench)

        logger.info(f"Downloading historical universe data for {len(all_symbols)} symbols...")
        raw_universe_data = self.scanner.loader.download_universe(list(all_symbols))
        if uses_completed_weeks(self.scanner.config):
            raw_universe_data = {symbol: df.set_axis(session_dates(df)) for symbol, df in raw_universe_data.items()}

        spy_df = raw_universe_data.get('SPY') if 'SPY' in raw_universe_data else list(raw_universe_data.values())[0]

        all_signals = []

        for d_str in schedule:
            d_dt = pd.to_datetime(d_str)
            logger.info(f"Running historical scan for date: {d_str}")

            # Slice benchmark data up to d_dt
            spy_slice = spy_df[spy_df.index <= d_dt] if spy_df is not None else None
            market_regime_info = detect_market_regime(spy_slice) if spy_slice is not None and not spy_slice.empty else {'regime': 'MARKET_NEUTRAL', 'regime_score': 50}

            for symbol, cat_name in symbol_to_cat.items():
                if symbol not in raw_universe_data:
                    continue

                df_full = raw_universe_data[symbol]
                df_slice = df_full[df_full.index <= d_dt]

                if len(df_slice) < 100:
                    continue

                # Ensure slice ends on or very close to d_str (within 5 calendar days)
                last_bar_date = df_slice.index[-1]
                if (d_dt - last_bar_date).days > 5:
                    continue

                bench_sym = categories.get(cat_name, {}).get('benchmark', 'SPY')
                df_bench_full = raw_universe_data.get(bench_sym, spy_df)
                df_bench_slice = df_bench_full[df_bench_full.index <= d_dt] if df_bench_full is not None else spy_slice

                try:
                    # 1. Daily Analysis on slice
                    df_daily_analyzed, daily_indicators = run_daily_analysis(df_slice, self.scanner.config)

                    # 2. Weekly Analysis with drop_partial=True and as_of_date cutoff
                    df_weekly = (completed_weekly(df_slice, d_str) if uses_completed_weeks(self.scanner.config)
                                 else self.scanner.loader.resample_to_weekly(df_slice, as_of_date=d_str, drop_partial=True))
                    weekly_indicators = run_weekly_analysis(df_weekly, self.scanner.config)

                    # 3. Relative Strength
                    rs_analysis = calculate_relative_strength(df_slice, df_bench_slice, periods=[20, 60])

                    # 4. Structure
                    structure_analysis = daily_indicators.get('structure', {})

                    # 5. Scores
                    trend_score, _ = calculate_trend_score(weekly_indicators, daily_indicators, structure_analysis, rs_analysis, self.scanner.config)
                    bottom_score, _ = calculate_bottom_score(daily_indicators, structure_analysis, rs_analysis, df_slice, self.scanner.config)
                    reversal_score, _ = calculate_reversal_score(daily_indicators, weekly_indicators, structure_analysis, rs_analysis, self.scanner.config)
                    entry_quality, _ = calculate_entry_quality(daily_indicators, structure_analysis, self.scanner.config)

                    # 6. State
                    state = classify_state(trend_score, bottom_score, reversal_score, daily_indicators, weekly_indicators, structure_analysis, rs_analysis, self.scanner.config)

                    # 7. Candidate Score
                    candidate_score, _ = calculate_candidate_score(trend_score, entry_quality, rs_analysis, state, self.scanner.config)

                    # Determine signal tier
                    pv_config = self.scanner.config.get('paper_validation', {})
                    act_states = pv_config.get('actionable_states', ['REVERSAL', 'EARLY_UPTREND', 'BOTTOM_BREAKOUT'])
                    watch_states = pv_config.get('watchlist_states', ['UPTREND', 'BOTTOM_FORMING', 'REVERSAL_CONFIRMED'])
                    min_score = pv_config.get('actionable_min_candidate_score', 70)

                    signal_tier = "NONE"
                    if state in act_states and candidate_score >= min_score:
                        signal_tier = "ACTIONABLE"
                    elif state in watch_states and candidate_score >= min_score:
                        signal_tier = "WATCHLIST"

                    signal_record = {
                        'signal_date': d_str,
                        'symbol': symbol,
                        'category': cat_name,
                        'state': state,
                        'signal_tier': signal_tier,
                        'price': daily_indicators['close'],
                        'trend_score': trend_score,
                        'bottom_score': bottom_score,
                        'reversal_score': reversal_score,
                        'entry_quality': entry_quality,
                        'candidate_score': candidate_score,
                        'market_regime': market_regime_info['regime'],
                        'rsi': daily_indicators['rsi'],
                        'macd': daily_indicators['macd'],
                        'volume_ratio': daily_indicators['volume_ratio'],
                        'ema20_distance': daily_indicators['distance_ema20'],
                        'ema50_distance': daily_indicators['distance_ema50'],
                        'scanner_version': self.scanner.version
                    }
                    all_signals.append(signal_record)

                except Exception as e:
                    logger.debug(f"Error generating historical signal for {symbol} on {d_str}: {e}")

        df_signals = pd.DataFrame(all_signals)
        if not df_signals.empty:
            df_signals.sort_values(by=['signal_date', 'symbol'], inplace=True)
            signals_csv = os.path.join(self.output_dir, "signals.csv")
            df_signals.to_csv(signals_csv, index=False)
            logger.info(f"Saved {len(df_signals)} historical walk-forward signals to {signals_csv}")

        return df_signals
