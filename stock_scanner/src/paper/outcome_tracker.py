"""
Outcome tracker module for Paper Validation subsystem.
Automatically tracks subsequent market performance, forward returns (+1D to +20D),
MFE, MAE, and completion status using trading days.
"""

import os
import json
import logging
import pandas as pd
from datetime import datetime
from typing import Dict, List, Any, Optional

from stock_scanner.src.data.yfinance_loader import YFinanceLoader

logger = logging.getLogger("stock_scanner.paper.tracker")


class OutcomeTracker:
    """Tracks and updates outcomes for recorded paper signals."""

    def __init__(self, signals_dir: str = "data/paper_validation/signals", outcomes_dir: str = "data/paper_validation/outcomes", loader: Optional[YFinanceLoader] = None):
        self.signals_dir = signals_dir
        self.outcomes_dir = outcomes_dir
        self.loader = loader or YFinanceLoader()

    def update_all_outcomes(self) -> Dict[str, Any]:
        """
        Scan all signal files, fetch subsequent price data for each signal,
        calculate forward returns, MFE, and MAE, and update outcome records.
        """
        if not os.path.exists(self.signals_dir):
            logger.warning(f"Signals directory {self.signals_dir} not found.")
            return {"updated_count": 0}

        signal_files = [f for f in os.listdir(self.signals_dir) if f.startswith("signals_") and f.endswith(".json")]
        total_updated = 0

        for sig_file in signal_files:
            date_str = sig_file.replace("signals_", "").replace(".json", "")
            signals_path = os.path.join(self.signals_dir, sig_file)
            outcomes_path = os.path.join(self.outcomes_dir, f"outcome_{date_str}.json")

            if not os.path.exists(outcomes_path):
                logger.warning(f"Outcome file {outcomes_path} not found for signal file {sig_file}.")
                continue

            with open(signals_path, 'r', encoding='utf-8') as f:
                signals = json.load(f)

            with open(outcomes_path, 'r', encoding='utf-8') as f:
                outcomes = json.load(f)

            outcome_map = {o['signal_id']: o for o in outcomes}
            updated = False

            # Cache symbol price data to avoid redundant downloads
            symbol_data_cache = {}

            for sig in signals:
                signal_id = sig['signal_id']
                symbol = sig['symbol']
                signal_price = sig['signal_price']
                signal_date = sig['signal_date']

                if signal_id not in outcome_map:
                    continue

                outcome = outcome_map[signal_id]

                # If already complete and no new bars needed, we could skip, but re-running is idempotent
                if symbol not in symbol_data_cache:
                    try:
                        df_full = self.loader.download_ticker(symbol)
                        symbol_data_cache[symbol] = df_full
                    except Exception as e:
                        logger.warning(f"Could not download price data for {symbol}: {e}")
                        continue

                df_full = symbol_data_cache[symbol]
                if df_full is None or df_full.empty:
                    continue

                # Filter strictly future data (strictly after signal_date)
                signal_dt = pd.to_datetime(signal_date)
                future_df = df_full[df_full.index > signal_dt]

                if future_df.empty:
                    continue

                # Calculate forward returns using trading days
                # 1D, 3D, 5D, 10D, 20D indices corresponding to future_df.iloc[0], [2], [4], [9], [19]
                fwd_returns = {
                    "1d": float((future_df.iloc[0]['Close'] / signal_price) - 1.0) if len(future_df) >= 1 else None,
                    "3d": float((future_df.iloc[2]['Close'] / signal_price) - 1.0) if len(future_df) >= 3 else None,
                    "5d": float((future_df.iloc[4]['Close'] / signal_price) - 1.0) if len(future_df) >= 5 else None,
                    "10d": float((future_df.iloc[9]['Close'] / signal_price) - 1.0) if len(future_df) >= 10 else None,
                    "20d": float((future_df.iloc[19]['Close'] / signal_price) - 1.0) if len(future_df) >= 20 else None,
                }

                # Calculate MFE and MAE over 5d, 10d, 20d using High/Low
                mfe = {}
                mae = {}
                future_prices = {}

                windows = {"5d": 5, "10d": 10, "20d": 20}
                for w_name, w_len in windows.items():
                    if len(future_df) >= w_len:
                        sub = future_df.iloc[:w_len]
                        max_high = float(sub['High'].max())
                        min_low = float(sub['Low'].min())
                        mfe[w_name] = float((max_high / signal_price) - 1.0)
                        mae[w_name] = float((min_low / signal_price) - 1.0)
                        future_prices[w_name] = float(sub.iloc[-1]['Close'])
                    else:
                        mfe[w_name] = None
                        mae[w_name] = None

                # Determine status
                if len(future_df) >= 20:
                    status = "COMPLETE"
                elif len(future_df) > 0:
                    status = "PARTIAL"
                else:
                    status = "OPEN"

                outcome['forward_returns'] = fwd_returns
                outcome['mfe'] = mfe
                outcome['mae'] = mae
                outcome['future_prices'] = future_prices
                outcome['status'] = status
                outcome['updated_at'] = datetime.now().isoformat()
                updated = True
                total_updated += 1

            if updated:
                with open(outcomes_path, 'w', encoding='utf-8') as f:
                    json.dump(outcomes, f, indent=2)
                logger.info(f"Updated outcomes for date {date_str}")

        logger.info(f"Successfully updated {total_updated} paper signal outcomes.")
        return {"updated_count": total_updated}
