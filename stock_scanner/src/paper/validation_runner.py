"""
Validation runner CLI for Paper Validation subsystem.
Coordinates signal recording, outcome tracking, state transition updates, and report generation.
"""

import argparse
import logging
import sys
from datetime import datetime

from dotenv import load_dotenv

from stock_scanner.src.paper.signal_recorder import SignalRecorder
from stock_scanner.src.paper.outcome_tracker import OutcomeTracker
from stock_scanner.src.paper.state_tracker import StateTracker
from stock_scanner.src.paper.paper_report import PaperReporter


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(description="Scanner V1.2 Paper Validation Subsystem Runner")
    parser.add_argument("--record", action="store_true", help="Run today's scan, record immutable snapshot and paper signals")
    parser.add_argument("--update", action="store_true", help="Update outcomes and state transitions for all recorded signals")
    parser.add_argument("--report", action="store_true", help="Generate performance reports and rankings")
    parser.add_argument("--report-type", type=str, default="daily", choices=["daily", "weekly", "monthly"], help="Report type frequency")
    parser.add_argument("--category", type=str, help="Scan a specific category during recording")
    parser.add_argument("--date", type=str, help="Override scan date (YYYY-MM-DD) for recording")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    if not (args.record or args.update or args.report):
        # Default behavior if no flags specified: run all three steps
        args.record = True
        args.update = True
        args.report = True

    recorder = SignalRecorder()
    tracker = OutcomeTracker()
    state_tracker = StateTracker()
    reporter = PaperReporter()

    if args.record:
        print("Running Paper Validation: Recording Scan Snapshot & Signals...")
        res = recorder.record_daily_scan(scan_date=args.date, target_category=args.category)
        print(f"Recorded snapshot: {res.get('snapshot_path')}")
        print(f"Candidates recorded: {res.get('candidates_recorded')}")

    if args.update:
        print("Running Paper Validation: Updating Outcomes & State Transitions...")
        tracker.update_all_outcomes()
        state_tracker.update_state_transitions()
        print("Outcomes and state transitions updated successfully.")

    if args.report:
        print(f"Running Paper Validation: Generating {args.report_type.upper()} Reports...")
        paths = reporter.generate_reports(report_type=args.report_type)
        print("Reports generated successfully:")
        for k, v in paths.items():
            print(f" - {k}: {v}")


if __name__ == "__main__":
    main()
