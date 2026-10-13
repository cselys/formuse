"""
Performance calculation and aggregation module for Paper Validation subsystem.
Computes metrics by state, candidate score buckets, entry quality buckets, and market regime.
"""

import os
import json
import logging
import numpy as np
import pandas as pd
from typing import Dict, List, Any, Optional

logger = logging.getLogger("stock_scanner.paper.performance")


class PerformanceAnalyzer:
    """Aggregates paper signal outcomes and calculates statistical performance metrics."""

    def __init__(self, signals_dir: str = "data/paper_validation/signals", outcomes_dir: str = "data/paper_validation/outcomes"):
        self.signals_dir = signals_dir
        self.outcomes_dir = outcomes_dir

    def load_all_records(self) -> pd.DataFrame:
        """Load all signals and their corresponding outcomes into a single pandas DataFrame."""
        if not os.path.exists(self.signals_dir) or not os.path.exists(self.outcomes_dir):
            return pd.DataFrame()

        signal_files = [f for f in os.listdir(self.signals_dir) if f.startswith("signals_") and f.endswith(".json")]
        records = []

        for sig_file in signal_files:
            date_str = sig_file.replace("signals_", "").replace(".json", "")
            signals_path = os.path.join(self.signals_dir, sig_file)
            outcomes_path = os.path.join(self.outcomes_dir, f"outcome_{date_str}.json")

            if not os.path.exists(outcomes_path):
                continue

            try:
                with open(signals_path, 'r', encoding='utf-8') as f:
                    signals = json.load(f)
                with open(outcomes_path, 'r', encoding='utf-8') as f:
                    outcomes = json.load(f)

                outcome_map = {o['signal_id']: o for o in outcomes}

                for sig in signals:
                    sig_id = sig['signal_id']
                    out = outcome_map.get(sig_id, {})

                    fwd = out.get('forward_returns', {})
                    mfe = out.get('mfe', {})
                    mae = out.get('mae', {})

                    # Determine score buckets
                    c_score = sig.get('candidate_score', 0.0)
                    if c_score >= 90:
                        c_bucket = "90-100"
                    elif c_score >= 80:
                        c_bucket = "80-89"
                    elif c_score >= 70:
                        c_bucket = "70-79"
                    else:
                        c_bucket = "60-69"

                    eq = sig.get('entry_quality', 0.0)
                    if eq >= 90:
                        eq_bucket = "90-100"
                    elif eq >= 80:
                        eq_bucket = "80-89"
                    elif eq >= 70:
                        eq_bucket = "70-79"
                    else:
                        eq_bucket = "60-69"

                    row = {
                        'signal_id': sig_id,
                        'signal_date': sig.get('signal_date'),
                        'symbol': sig.get('symbol'),
                        'category': sig.get('category'),
                        'signal_type': sig.get('signal_type'),
                        'signal_tier': sig.get('signal_tier'),
                        'signal_price': sig.get('signal_price'),
                        'candidate_score': c_score,
                        'candidate_score_bucket': c_bucket,
                        'entry_quality': eq,
                        'entry_quality_bucket': eq_bucket,
                        'market_regime': sig.get('market_regime'),
                        'status': out.get('status', 'OPEN'),
                        'fwd_1d': fwd.get('1d'),
                        'fwd_3d': fwd.get('3d'),
                        'fwd_5d': fwd.get('5d'),
                        'fwd_10d': fwd.get('10d'),
                        'fwd_20d': fwd.get('20d'),
                        'mfe_5d': mfe.get('5d'),
                        'mfe_10d': mfe.get('10d'),
                        'mfe_20d': mfe.get('20d'),
                        'mae_5d': mae.get('5d'),
                        'mae_10d': mae.get('10d'),
                        'mae_20d': mae.get('20d'),
                    }
                    records.append(row)
            except Exception as e:
                logger.warning(f"Error loading records from {sig_file}: {e}")

        if not records:
            return pd.DataFrame()

        df = pd.DataFrame(records)
        df.sort_values(by=['signal_date', 'symbol', 'signal_id'], inplace=True)
        return df

    def compute_group_metrics(self, df: pd.DataFrame, group_col: str) -> List[Dict[str, Any]]:
        """Compute aggregate performance metrics grouped by a specific column."""
        if df.empty or group_col not in df.columns:
            return []

        results = []
        for name, group in df.groupby(group_col):
            signal_count = len(group)
            completed_group = group[group['status'] == 'COMPLETE']
            completed_count = len(completed_group)

            fwd_20 = group['fwd_20d'].dropna()
            win_rate_20d = float((fwd_20 > 0).mean()) * 100.0 if not fwd_20.empty else 0.0

            metrics = {
                'group': str(name),
                'signal_count': signal_count,
                'completed_count': completed_count,
                'avg_1d': float(group['fwd_1d'].mean()) if not group['fwd_1d'].isna().all() else 0.0,
                'avg_3d': float(group['fwd_3d'].mean()) if not group['fwd_3d'].isna().all() else 0.0,
                'avg_5d': float(group['fwd_5d'].mean()) if not group['fwd_5d'].isna().all() else 0.0,
                'avg_10d': float(group['fwd_10d'].mean()) if not group['fwd_10d'].isna().all() else 0.0,
                'avg_20d': float(group['fwd_20d'].mean()) if not group['fwd_20d'].isna().all() else 0.0,
                'median_20d': float(fwd_20.median()) if not fwd_20.empty else 0.0,
                'win_rate_20d': win_rate_20d,
                'p25_20d': float(np.percentile(fwd_20, 25)) if not fwd_20.empty else 0.0,
                'p75_20d': float(np.percentile(fwd_20, 75)) if not fwd_20.empty else 0.0,
                'avg_mfe_5d': float(group['mfe_5d'].mean()) if not group['mfe_5d'].isna().all() else 0.0,
                'avg_mfe_10d': float(group['mfe_10d'].mean()) if not group['mfe_10d'].isna().all() else 0.0,
                'avg_mfe_20d': float(group['mfe_20d'].mean()) if not group['mfe_20d'].isna().all() else 0.0,
                'avg_mae_5d': float(group['mae_5d'].mean()) if not group['mae_5d'].isna().all() else 0.0,
                'avg_mae_10d': float(group['mae_10d'].mean()) if not group['mae_10d'].isna().all() else 0.0,
                'avg_mae_20d': float(group['mae_20d'].mean()) if not group['mae_20d'].isna().all() else 0.0,
            }
            results.append(metrics)

        return results
