"""
Paper report module for Paper Validation subsystem.
Generates comprehensive daily, weekly, and monthly reports, summary JSON/text,
and top/worst signal rankings under data/paper_validation/reports/.
"""

import os
import json
import logging
import pandas as pd
from datetime import datetime
from typing import Dict, List, Any, Optional

from stock_scanner.src.paper.performance import PerformanceAnalyzer

logger = logging.getLogger("stock_scanner.paper.report")


class PaperReporter:
    """Generates performance reports and top/worst signal rankings."""

    def __init__(self, reports_dir: str = "data/paper_validation/reports", signals_dir: str = "data/paper_validation/signals", outcomes_dir: str = "data/paper_validation/outcomes", analyzer: Optional[PerformanceAnalyzer] = None):
        self.reports_dir = reports_dir
        self.analyzer = analyzer or PerformanceAnalyzer(signals_dir=signals_dir, outcomes_dir=outcomes_dir)
        os.makedirs(self.reports_dir, exist_ok=True)

    def generate_reports(self, report_type: str = "daily") -> Dict[str, str]:
        """
        Generate aggregate performance reports (CSV, JSON, TXT) and top/worst signal rankings.
        report_type can be 'daily', 'weekly', or 'monthly'.
        """
        df = self.analyzer.load_all_records()
        if df.empty:
            logger.warning("No paper records found for report generation.")
            return {}

        timestamp = datetime.now().strftime("%Y-%m-%d")

        # Group metrics
        by_state = self.analyzer.compute_group_metrics(df, 'signal_type')
        by_c_bucket = self.analyzer.compute_group_metrics(df, 'candidate_score_bucket')
        by_eq_bucket = self.analyzer.compute_group_metrics(df, 'entry_quality_bucket')
        by_regime = self.analyzer.compute_group_metrics(df, 'market_regime')

        summary_data = {
            "report_type": report_type,
            "generated_at": datetime.now().isoformat(),
            "total_signals": len(df),
            "completed_signals": int((df['status'] == 'COMPLETE').sum()),
            "by_state": by_state,
            "by_candidate_score_bucket": by_c_bucket,
            "by_entry_quality_bucket": by_eq_bucket,
            "by_market_regime": by_regime
        }

        # 1. Save summary JSON
        summary_json_path = os.path.join(self.reports_dir, f"{report_type}_summary.json")
        with open(summary_json_path, 'w', encoding='utf-8') as f:
            json.dump(summary_data, f, indent=2)

        # 2. Save summary TXT
        summary_txt_path = os.path.join(self.reports_dir, f"{report_type}_summary.txt")
        with open(summary_txt_path, 'w', encoding='utf-8') as f:
            f.write(f"=== STOCK SCANNER V1.2 PAPER VALIDATION {report_type.upper()} REPORT ===\n")
            f.write(f"Generated At: {summary_data['generated_at']}\n")
            f.write(f"Total Signals: {summary_data['total_signals']}\n")
            f.write(f"Completed Signals: {summary_data['completed_signals']}\n\n")

            f.write("--- PERFORMANCE BY STATE ---\n")
            for item in by_state:
                f.write(f"State: {item['group']} | Count: {item['signal_count']} | WinRate20D: {item['win_rate_20d']:.1f}% | Avg20D: {item['avg_20d']*100:.2f}% | AvgMFE20: {item['avg_mfe_20d']*100:.2f}%\n")

            f.write("\n--- PERFORMANCE BY CANDIDATE SCORE BUCKET ---\n")
            for item in by_c_bucket:
                f.write(f"Bucket: {item['group']} | Count: {item['signal_count']} | WinRate20D: {item['win_rate_20d']:.1f}% | Avg20D: {item['avg_20d']*100:.2f}%\n")

        # 3. Save CSV reports for states & buckets
        df_state = pd.DataFrame(by_state)
        csv_report_path = os.path.join(self.reports_dir, f"{report_type}_report.csv")
        df_state.to_csv(csv_report_path, index=False)

        # Also support default weekly_report.csv and monthly_report.csv if requested
        if report_type == "weekly":
            df_state.to_csv(os.path.join(self.reports_dir, "weekly_report.csv"), index=False)
        elif report_type == "monthly":
            df_state.to_csv(os.path.join(self.reports_dir, "monthly_report.csv"), index=False)
        else:
            df_state.to_csv(os.path.join(self.reports_dir, "daily_report.csv"), index=False)

        # 4. Top and Worst Signals rankings (ranked by +20D return)
        df_ranked = df.dropna(subset=['fwd_20d']).sort_values(by='fwd_20d', ascending=False)

        top_signals_path = os.path.join(self.reports_dir, "top_signals.csv")
        worst_signals_path = os.path.join(self.reports_dir, "worst_signals.csv")

        if not df_ranked.empty:
            cols_to_export = [
                'symbol', 'signal_date', 'signal_type', 'candidate_score', 'entry_quality',
                'signal_price', 'fwd_5d', 'fwd_10d', 'fwd_20d', 'mfe_20d', 'mae_20d'
            ]
            export_cols = [c for c in cols_to_export if c in df_ranked.columns]

            df_top = df_ranked.head(10)[export_cols]
            df_top.to_csv(top_signals_path, index=False)

            df_worst = df_ranked.tail(10).sort_values(by='fwd_20d', ascending=True)[export_cols]
            df_worst.to_csv(worst_signals_path, index=False)
        else:
            pd.DataFrame(columns=['symbol', 'signal_date', 'fwd_20d']).to_csv(top_signals_path, index=False)
            pd.DataFrame(columns=['symbol', 'signal_date', 'fwd_20d']).to_csv(worst_signals_path, index=False)

        logger.info(f"Generated paper validation reports under {self.reports_dir}")

        return {
            "summary_json": summary_json_path,
            "summary_txt": summary_txt_path,
            "csv_report": csv_report_path,
            "top_signals": top_signals_path,
            "worst_signals": worst_signals_path
        }
