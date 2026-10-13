"""
Historical outcome tracking module for walk-forward validation.
Computes multi-horizon forward returns (+1D to +60D), MFE/MAE, and benchmark comparison (SPY/QQQ).
"""

import os
import logging
import pandas as pd
import numpy as np
from typing import Dict, List, Any, Optional

from stock_scanner.src.data.yfinance_loader import YFinanceLoader

logger = logging.getLogger("stock_scanner.historical.outcome")


class HistoricalOutcomeTracker:
    """Calculates forward returns, MFE/MAE, and benchmark relative performance for historical signals."""

    def __init__(self, loader: Optional[YFinanceLoader] = None, output_dir: str = "data/evaluation/walk_forward"):
        self.loader = loader or YFinanceLoader()
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def process_outcomes(self, df_signals: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate forward returns (+1D, +5D, +10D, +20D, +40D, +60D), MFE/MAE,
        and relative performance against SPY/QQQ for each historical signal.
        """
        if df_signals.empty:
            logger.warning("No signals provided for outcome processing.")
            return pd.DataFrame()

        # Cache price data for symbols and benchmarks
        symbols = df_signals['symbol'].unique().tolist()
        symbols.extend(['SPY', 'QQQ'])
        symbols = list(set(symbols))

        logger.info(f"Downloading price histories for {len(symbols)} symbols and benchmarks for outcome tracking...")
        universe_data = self.loader.download_universe(symbols)

        spy_df = universe_data.get('SPY', pd.DataFrame())
        qqq_df = universe_data.get('QQQ', pd.DataFrame())

        outcomes = []

        for idx, row in df_signals.iterrows():
            symbol = row['symbol']
            signal_date = row['signal_date']
            signal_price = row['price']

            if symbol not in universe_data:
                continue

            df_full = universe_data[symbol]
            signal_dt = pd.to_datetime(signal_date)
            future_df = df_full[df_full.index > signal_dt]

            if future_df.empty:
                continue

            # Forward horizons (trading days)
            horizons = {
                '1d': 1,
                '5d': 5,
                '10d': 10,
                '20d': 20,
                '40d': 40,
                '60d': 60
            }

            fwd_returns = {}
            mfe = {}
            mae = {}

            for h_name, h_bars in horizons.items():
                if len(future_df) >= h_bars:
                    future_close = float(future_df.iloc[h_bars - 1]['Close'])
                    fwd_returns[f'fwd_{h_name}'] = float((future_close / signal_price) - 1.0)

                    sub = future_df.iloc[:h_bars]
                    max_high = float(sub['High'].max())
                    min_low = float(sub['Low'].min())
                    mfe[f'mfe_{h_name}'] = float((max_high / signal_price) - 1.0)
                    mae[f'mae_{h_name}'] = float((min_low / signal_price) - 1.0)
                else:
                    fwd_returns[f'fwd_{h_name}'] = np.nan
                    mfe[f'mfe_{h_name}'] = np.nan
                    mae[f'mae_{h_name}'] = np.nan

            # Benchmark forward returns (SPY / QQQ)
            # For SPY benchmark relative outperformance
            spy_fwd = self._get_benchmark_raw_returns(spy_df, signal_dt, horizons)
            qqq_fwd = self._get_benchmark_raw_returns(qqq_df, signal_dt, horizons)

            relative_spy = {}
            relative_qqq = {}
            for h_name in horizons.keys():
                val = fwd_returns.get(f'fwd_{h_name}', np.nan)
                spy_val = spy_fwd.get(f'fwd_{h_name}', np.nan)
                qqq_val = qqq_fwd.get(f'fwd_{h_name}', np.nan)

                relative_spy[f'rel_spy_{h_name}'] = float(val - spy_val) if not np.isnan(val) and not np.isnan(spy_val) else np.nan
                relative_qqq[f'rel_qqq_{h_name}'] = float(val - qqq_val) if not np.isnan(val) and not np.isnan(qqq_val) else np.nan

            outcome_record = {
                'signal_date': signal_date,
                'symbol': symbol,
                'category': row['category'],
                'state': row['state'],
                'signal_tier': row['signal_tier'],
                'signal_price': signal_price,
                'candidate_score': row['candidate_score'],
                'entry_quality': row['entry_quality'],
                'market_regime': row['market_regime'],
                **fwd_returns,
                **mfe,
                **mae,
                **relative_spy,
                **relative_qqq
            }
            outcomes.append(outcome_record)

        df_outcomes = pd.DataFrame(outcomes)
        if not df_outcomes.empty:
            df_outcomes.sort_values(by=['signal_date', 'symbol'], inplace=True)
            outcomes_csv = os.path.join(self.output_dir, "outcomes.csv")
            df_outcomes.to_csv(outcomes_csv, index=False)
            logger.info(f"Saved {len(df_outcomes)} historical walk-forward outcomes to {outcomes_csv}")

        return df_outcomes

    def _get_benchmark_raw_returns(self, df_bench: pd.DataFrame, signal_dt: pd.Timestamp, horizons: Dict[str, int]) -> Dict[str, float]:
        if df_bench.empty:
            return {}
        future_bench = df_bench[df_bench.index > signal_dt]
        if future_bench.empty:
            return {}
        base_price = float(df_bench[df_bench.index <= signal_dt].iloc[-1]['Close']) if not df_bench[df_bench.index <= signal_dt].empty else float(future_bench.iloc[0]['Open'])

        res = {}
        for h_name, h_bars in horizons.items():
            if len(future_bench) >= h_bars:
                close_price = float(future_bench.iloc[h_bars - 1]['Close'])
                res[f'fwd_{h_name}'] = float((close_price / base_price) - 1.0)
            else:
                res[f'fwd_{h_name}'] = np.nan
        return res
