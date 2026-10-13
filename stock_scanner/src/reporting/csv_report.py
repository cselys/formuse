"""
CSV reporting for stock_scanner V1.2.
Saves comprehensive flat records including V1.2 candidate score, entry quality, and market regime.
"""

import os
import pandas as pd
from datetime import datetime


def save_csv_report(results: list[dict], output_dir: str = "data/reports", scan_date: str = None) -> str:
    """
    Save scan results to CSV file by scan date.
    """
    os.makedirs(output_dir, exist_ok=True)
    if not scan_date:
        scan_date = datetime.now().strftime("%Y-%m-%d")

    rows = []
    for r in results:
        daily = r.get('daily', {})
        weekly = r.get('weekly', {})
        rs = r.get('relative_strength', {})
        scores = r.get('trend_score_breakdown', {})
        cand_breakdown = r.get('candidate_score_breakdown', {})
        diagnostic = r.get('weekly_diagnostics', {})

        row = {
            'date': scan_date,
            'scanner_version': r.get('scanner_version', '1.2'),
            'symbol': r.get('symbol'),
            'category': r.get('category'),
            'state': r.get('state'),
            'candidate_score': r.get('candidate_score'),
            'trend_score': r.get('trend_score'),
            'entry_quality': r.get('entry_quality', r.get('setup_quality')),
            'bottom_score': r.get('bottom_score'),
            'reversal_score': r.get('reversal_score'),
            'market_regime': r.get('market_regime'),
            'weekly_score': scores.get('weekly_trend', 0),
            'daily_score': scores.get('daily_trend', 0),
            'momentum_score': scores.get('momentum', 0),
            'relative_strength_score': scores.get('relative_strength', 0),
            'volume_score': scores.get('volume', 0),
            'structure_score': scores.get('structure', 0),
            'cand_trend_component': cand_breakdown.get('trend_component', 0),
            'cand_entry_component': cand_breakdown.get('entry_quality_component', 0),
            'cand_rs_component': cand_breakdown.get('relative_strength_component', 0),
            'cand_state_component': cand_breakdown.get('state_quality_component', 0),
            'daily_close': daily.get('close'),
            'weekly_close': weekly.get('close'),
            'daily_rsi': daily.get('rsi'),
            'weekly_rsi': weekly.get('rsi'),
            'daily_ema20': daily.get('ema20'),
            'daily_ema50': daily.get('ema50'),
            'daily_ema200': daily.get('ema200'),
            'weekly_ema20': weekly.get('ema20'),
            'weekly_ema40': weekly.get('ema40'),
            'relative_strength_20d': rs.get('rs_20d'),
            'relative_strength_60d': rs.get('rs_60d'),
            'volume_ratio': daily.get('volume_ratio'),
            'atr_pct': daily.get('atr_pct'),
            'distance_ema20': daily.get('distance_ema20'),
            'distance_ema50': daily.get('distance_ema50'),
            'distance_ema200': daily.get('distance_ema200'),
            'data_date': r.get('data_date'),
            'data_status': r.get('data_status'),
            'weekly_data_status': diagnostic.get('status'),
            'weekly_data_week_end': diagnostic.get('data_week_end'),
            'weekly_change_pct': diagnostic.get('weekly_change_pct'),
            'weekly_direction': diagnostic.get('weekly_direction'),
            'daily_direction': diagnostic.get('daily_direction'),
            'daily_weekly_alignment': diagnostic.get('alignment'),
            'weekly_rsi_change': diagnostic.get('rsi_change'),
            'weekly_macd_hist_change': diagnostic.get('macd_hist_change'),
        }
        rows.append(row)

    df_csv = pd.DataFrame(rows)
    filename = f"{scan_date}.csv"
    filepath = os.path.join(output_dir, filename)
    df_csv.to_csv(filepath, index=False)
    return filepath
