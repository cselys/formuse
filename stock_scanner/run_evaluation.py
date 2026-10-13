#!/usr/bin/env python3
"""
Historical signal evaluation runner for Scanner V1.1.
"""

import logging
from datetime import datetime
from stock_scanner.src.scanner import StockScanner
from stock_scanner.src.analysis.historical_eval import HistoricalEvaluator

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


def main():
    print("Running Scanner V1.1 Historical Evaluation...")
    scanner = StockScanner()
    evaluator = HistoricalEvaluator(scanner)

    symbols = ['NVDA', 'AAPL', 'MSFT']
    # Get valid dates from SPY history
    try:
        spy_df = scanner.loader.download_ticker('SPY')
        # Pick dates 90, 60, and 30 trading days ago
        dates = [
            spy_df.index[-90].strftime('%Y-%m-%d'),
            spy_df.index[-60].strftime('%Y-%m-%d'),
            spy_df.index[-30].strftime('%Y-%m-%d')
        ]
    except Exception:
        dates = ['2026-05-01', '2026-06-01', '2026-07-01']

    print(f"Evaluating historical dates: {dates}")
    stats = evaluator.evaluate_historical_dates(symbols, dates)
    print(f"\nHistorical Evaluation Results:")
    print(f"Total Signals Evaluated: {stats.get('signals_count', 0)}")
    print("\nState Statistics:")
    for state, data in stats.get('states', {}).items():
        print(f" - {state}: count={data['count']}, avg +10D return={data['avg_fwd_10d']:.2f}%, win rate 5D={data['win_rate_5d']:.1f}%")

    print("\nScore Bucket Statistics:")
    for bucket, data in stats.get('score_buckets', {}).items():
        print(f" - Score {bucket}: count={data['count']}, avg +10D return={data['avg_fwd_10d']:.2f}%, win rate 10D={data['win_rate_10d']:.1f}%")

    print("\nHistorical Evaluation Complete.")


if __name__ == "__main__":
    main()
