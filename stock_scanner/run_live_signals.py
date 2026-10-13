#!/usr/bin/env python3
"""
Run live current scan across the expanded universe for Friday 2026-08-28,
filter for actionable and watchlist signals, display metrics and reasons,
and save CSV/JSON reports under data/reports/.
"""

import sys
import os
import json
from datetime import datetime
from dotenv import load_dotenv

from stock_scanner.src.scanner import StockScanner
from stock_scanner.src.reporting.csv_report import save_csv_report
from stock_scanner.src.reporting.json_report import save_json_report


def main():
    load_dotenv()
    print("=" * 80)
    print("STOCK SCANNER V1.2 — LIVE CURRENT SCAN (SESSION: 2026-08-28)")
    print("=" * 80)

    scanner = StockScanner()
    results = scanner.scan()
    if isinstance(results, tuple):
        results, _ = results

    if not results:
        print("No scan results generated.")
        return

    # Filter criteria for actionable / watchlist signals
    # Actionable: REVERSAL, EARLY_UPTREND, BOTTOM_BREAKOUT with Candidate Score >= 70
    # Watchlist: UPTREND, BOTTOM_FORMING, REVERSAL_CONFIRMED (or STRONG_UPTREND) with Candidate Score >= 70
    actionable_states = {'REVERSAL', 'EARLY_UPTREND', 'BOTTOM_BREAKOUT'}
    watchlist_states = {'UPTREND', 'BOTTOM_FORMING', 'REVERSAL_CONFIRMED', 'STRONG_UPTREND'}

    filtered_signals = []
    for r in results:
        state = r.get('state')
        c_score = r.get('candidate_score', 0.0)

        tier = None
        if state in actionable_states and c_score >= 70.0:
            tier = "ACTIONABLE"
        elif state in watchlist_states and c_score >= 70.0:
            tier = "WATCHLIST"

        if tier:
            r['signal_tier'] = tier
            filtered_signals.append(r)

    print(f"\nTotal universe symbols scanned: {len(results)}")
    print(f"Actionable / Watchlist signals identified: {len(filtered_signals)}\n")

    print("-" * 120)
    print(f"{'Symbol':<8} {'Category':<22} {'Tier':<12} {'State':<20} {'CandScore':<10} {'EntryQ':<8} {'Trend':<8} {'RSI':<6} {'Regime':<18}")
    print("-" * 120)

    for s in filtered_signals:
        sym = s['symbol']
        cat = s['category']
        tier = s['signal_tier']
        state = s['state']
        c_score = f"{s['candidate_score']:.1f}"
        eq = f"{s['entry_quality']:.1f}"
        trend = f"{s['trend_score']:.1f}"
        rsi = f"{s['daily'].get('rsi', 0.0):.1f}"
        regime = s['market_regime']

        print(f"{sym:<8} {cat:<22} {tier:<12} {state:<20} {c_score:<10} {eq:<8} {trend:<8} {rsi:<6} {regime:<18}")

        # Reason for signal (breakdown summary)
        breakdown = s.get('candidate_score_breakdown', {})
        print(f"   -> Reason / Breakdown: State={state} (Score: {c_score}), Trend={trend}, EntryQuality={eq}, RSI={rsi}, Regime={regime}")
        print(f"      Details: {breakdown}\n")

    print("-" * 120)

    # Save normal CSV/JSON reports
    scan_date = "2026-08-28" # Latest completed session
    csv_path = save_csv_report(results, output_dir="data/reports", scan_date=scan_date)
    json_path = save_json_report(results, output_dir="data/reports", scan_date=scan_date)

    print(f"\nReports saved successfully:")
    print(f" - CSV:  {csv_path}")
    print(f" - JSON: {json_path}")


if __name__ == "__main__":
    main()
