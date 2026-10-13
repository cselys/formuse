"""
Walk-forward orchestrator module for historical out-of-sample validation.
Coordinates signal generation, outcome calculation, and reporting.
"""

import argparse
import logging
import sys
from datetime import datetime

from dotenv import load_dotenv

from stock_scanner.src.historical.historical_signal import HistoricalSignalGenerator
from stock_scanner.src.historical.historical_outcome import HistoricalOutcomeTracker
from stock_scanner.src.historical.historical_report import HistoricalReporter


def run_walk_forward_validation(start_date: str = "2025-01-01", end_date: str = "2026-07-31", frequency: str = "month_end"):
    print("=" * 80)
    print("STOCK SCANNER V1.2 — HISTORICAL WALK-FORWARD VALIDATION")
    print("=" * 80)
    print(f"Period: {start_date} to {end_date} | Frequency: {frequency}")

    generator = HistoricalSignalGenerator()
    tracker = HistoricalOutcomeTracker()
    reporter = HistoricalReporter()

    print("\n1. Generating historical point-in-time signals...")
    df_signals = generator.run_walk_forward_scan(start_date=start_date, end_date=end_date, frequency=frequency)

    if df_signals.empty:
        print("No historical signals generated.")
        return

    print(f"Generated {len(df_signals)} historical signals.")

    print("\n2. Tracking forward returns (+1D to +60D), MFE/MAE, and benchmark comparisons...")
    df_outcomes = tracker.process_outcomes(df_signals)

    if df_outcomes.empty:
        print("No historical outcomes calculated.")
        return

    print(f"Processed outcomes for {len(df_outcomes)} signals.")

    print("\n3. Generating aggregate walk-forward reports...")
    reports = reporter.generate_all_reports(df_outcomes)

    print("\nWalk-forward reports generated successfully:")
    for k, v in reports.items():
        print(f" - {k}: {v}")

    print("\nHISTORICAL WALK-FORWARD VALIDATION COMPLETE")


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(description="Scanner V1.2 Historical Walk-Forward Validation Runner")
    parser.add_argument("--start-date", type=str, default="2025-01-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, default="2026-07-31", help="End date (YYYY-MM-DD)")
    parser.add_argument("--frequency", type=str, default="month_end", choices=["month_end", "weekly", "custom"], help="Scan frequency")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    run_walk_forward_validation(start_date=args.start_date, end_date=args.end_date, frequency=args.frequency)


if __name__ == "__main__":
    main()
