"""
Historical reporting and aggregation module for walk-forward validation.
Generates comprehensive reports by state, score buckets, entry quality, regime, category,
monthly/quarterly/yearly periodicity, top/worst signals, and summary JSON/TXT.
"""

import os
import json
import logging
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Dict, List, Any, Optional

logger = logging.getLogger("stock_scanner.historical.report")


class HistoricalReporter:
    """Generates detailed aggregate performance reports for walk-forward validation."""

    def __init__(self, output_dir: str = "data/evaluation/walk_forward"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def generate_all_reports(self, df_outcomes: pd.DataFrame) -> Dict[str, str]:
        """
        Generate all required walk-forward reports and summaries.
        """
        if df_outcomes.empty:
            logger.warning("No outcomes provided for report generation.")
            return {}

        df = df_outcomes.copy()
        df['signal_dt'] = pd.to_datetime(df['signal_date'])
        df['year'] = df['signal_dt'].dt.year
        df['quarter'] = df['signal_dt'].dt.to_period('Q').astype(str)
        df['month'] = df['signal_dt'].dt.to_period('M').astype(str)

        # Candidate score buckets
        def get_score_bucket(score):
            if score >= 90: return "90-100"
            elif score >= 80: return "80-89"
            elif score >= 70: return "70-79"
            else: return "60-69"

        df['candidate_score_bucket'] = df['candidate_score'].apply(get_score_bucket)
        df['entry_quality_bucket'] = df['entry_quality'].apply(get_score_bucket)

        # 1. State Report
        state_report = self._compute_group_aggregates(df, 'state')
        state_csv = os.path.join(self.output_dir, "state_report.csv")
        state_report.to_csv(state_csv, index=False)

        # 2. Score Report
        score_report = self._compute_group_aggregates(df, 'candidate_score_bucket')
        score_csv = os.path.join(self.output_dir, "score_report.csv")
        score_report.to_csv(score_csv, index=False)

        # 3. Regime Report
        regime_report = self._compute_group_aggregates(df, 'market_regime')
        regime_csv = os.path.join(self.output_dir, "regime_report.csv")
        regime_report.to_csv(regime_csv, index=False)

        # 4. Category Report
        category_report = self._compute_group_aggregates(df, 'category')
        category_csv = os.path.join(self.output_dir, "category_report.csv")
        category_report.to_csv(category_csv, index=False)

        # 5. Monthly Report (consistency across periods)
        monthly_report = self._compute_group_aggregates(df, 'month')
        monthly_csv = os.path.join(self.output_dir, "monthly_report.csv")
        monthly_report.to_csv(monthly_csv, index=False)

        # 6. Top & Worst Signals (ranked by +20D return)
        df_ranked = df.dropna(subset=['fwd_20d']).sort_values(by='fwd_20d', ascending=False)
        export_cols = ['symbol', 'signal_date', 'state', 'candidate_score', 'signal_price', 'fwd_5d', 'fwd_10d', 'fwd_20d', 'mfe_20d', 'mae_20d', 'rel_spy_20d']
        valid_cols = [c for c in export_cols if c in df_ranked.columns]

        top_signals_path = os.path.join(self.output_dir, "top_signals.csv")
        worst_signals_path = os.path.join(self.output_dir, "worst_signals.csv")

        if not df_ranked.empty:
            df_ranked.head(15)[valid_cols].to_csv(top_signals_path, index=False)
            df_ranked.tail(15).sort_values(by='fwd_20d', ascending=True)[valid_cols].to_csv(worst_signals_path, index=False)
        else:
            pd.DataFrame(columns=valid_cols).to_csv(top_signals_path, index=False)
            pd.DataFrame(columns=valid_cols).to_csv(worst_signals_path, index=False)

        # 7. Summary JSON & TXT
        summary_data = {
            "generated_at": datetime.now().isoformat(),
            "total_signals": len(df),
            "date_range": {
                "start": df['signal_date'].min(),
                "end": df['signal_date'].max()
            },
            "states": state_report.to_dict(orient='records'),
            "score_buckets": score_report.to_dict(orient='records'),
            "regimes": regime_report.to_dict(orient='records'),
            "categories": category_report.to_dict(orient='records')
        }

        summary_json = os.path.join(self.output_dir, "summary.json")
        with open(summary_json, 'w', encoding='utf-8') as f:
            json.dump(summary_data, f, indent=2)

        summary_txt = os.path.join(self.output_dir, "summary.txt")
        with open(summary_txt, 'w', encoding='utf-8') as f:
            f.write("=== HISTORICAL WALK-FORWARD VALIDATION SUMMARY (SCANNER V1.2) ===\n")
            f.write(f"Generated At: {summary_data['generated_at']}\n")
            f.write(f"Total Signals Evaluated: {summary_data['total_signals']}\n")
            f.write(f"Date Range: {summary_data['date_range']['start']} to {summary_data['date_range']['end']}\n\n")

            f.write("--- PERFORMANCE BY STATE (20D RETURN) ---\n")
            for _, r in state_report.iterrows():
                f.write(f"State: {r['group']} | Count: {r['count']} | WinRate: {r['win_rate_20d']:.1f}% | Avg20D: {r['avg_fwd_20d']*100:.2f}% | RelSPY20D: {r['avg_rel_spy_20d']*100:.2f}%\n")

            f.write("\n--- PERFORMANCE BY CANDIDATE SCORE BUCKET (20D RETURN) ---\n")
            for _, r in score_report.iterrows():
                f.write(f"Bucket: {r['group']} | Count: {r['count']} | WinRate: {r['win_rate_20d']:.1f}% | Avg20D: {r['avg_fwd_20d']*100:.2f}%\n")

        logger.info(f"Walk-forward reports successfully generated in {self.output_dir}")

        return {
            "state_report": state_csv,
            "score_report": score_csv,
            "monthly_report": monthly_csv,
            "summary_json": summary_json,
            "summary_txt": summary_txt
        }

    def _compute_group_aggregates(self, df: pd.DataFrame, group_col: str) -> pd.DataFrame:
        if df.empty or group_col not in df.columns:
            return pd.DataFrame()

        rows = []
        for name, group in df.groupby(group_col):
            count = len(group)
            fwd_20 = group['fwd_20d'].dropna()
            win_rate_20d = float((fwd_20 > 0).mean()) * 100.0 if not fwd_20.empty else 0.0

            row = {
                'group': str(name),
                'count': count,
                'avg_fwd_1d': float(group['fwd_1d'].mean()) if 'fwd_1d' in group and not group['fwd_1d'].isna().all() else 0.0,
                'avg_fwd_5d': float(group['fwd_5d'].mean()) if 'fwd_5d' in group and not group['fwd_5d'].isna().all() else 0.0,
                'avg_fwd_10d': float(group['fwd_10d'].mean()) if 'fwd_10d' in group and not group['fwd_10d'].isna().all() else 0.0,
                'avg_fwd_20d': float(group['fwd_20d'].mean()) if 'fwd_20d' in group and not group['fwd_20d'].isna().all() else 0.0,
                'avg_fwd_40d': float(group['fwd_40d'].mean()) if 'fwd_40d' in group and not group['fwd_40d'].isna().all() else 0.0,
                'avg_fwd_60d': float(group['fwd_60d'].mean()) if 'fwd_60d' in group and not group['fwd_60d'].isna().all() else 0.0,
                'median_fwd_20d': float(fwd_20.median()) if not fwd_20.empty else 0.0,
                'win_rate_20d': win_rate_20d,
                'avg_rel_spy_20d': float(group['rel_spy_20d'].mean()) if 'rel_spy_20d' in group and not group['rel_spy_20d'].isna().all() else 0.0,
                'avg_mfe_20d': float(group['mfe_20d'].mean()) if 'mfe_20d' in group and not group['mfe_20d'].isna().all() else 0.0,
                'avg_mae_20d': float(group['mae_20d'].mean()) if 'mae_20d' in group and not group['mae_20d'].isna().all() else 0.0,
            }
            rows.append(row)

        res_df = pd.DataFrame(rows)
        if not res_df.empty and 'group' in res_df.columns:
            res_df.sort_values(by='group', inplace=True)
        return res_df
