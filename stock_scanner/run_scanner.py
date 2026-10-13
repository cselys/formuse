#!/usr/bin/env python3
"""
CLI entry point for stock_scanner.
"""

import argparse
import logging
import sys
from pathlib import Path
from datetime import datetime

# Support the documented `python run_scanner.py` from this project directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from stock_scanner.src.scanner import StockScanner
from stock_scanner.src.reporting.console import display_console_report
from stock_scanner.src.reporting.csv_report import save_csv_report
from stock_scanner.src.reporting.json_report import save_json_report
from stock_scanner.src.reporting.daily_report import DailyReport
from stock_scanner.src.reporting.file_writer import save_daily_report
from stock_scanner.src.reporting.weekly_report import WeeklyReport, save_weekly_report, render_weekly_text
from stock_scanner.src.reporting.state_breakdown import StateBreakdown, save_state_breakdown


def lookup_main(argv):
    import yaml
    from stock_scanner.src.historical.stock_lookup import lookup_stock, normalize_symbol, parse_period
    from stock_scanner.src.reporting.stock_history import save_stock_history
    from stock_scanner.src.data.scanner_history import PROJECT_ROOT

    parser = argparse.ArgumentParser(description='Look up historical scanner classifications using local cached data only.')
    parser.add_argument('symbol', help='Stock symbol, such as NVDA')
    parser.add_argument('--period', default='10d', help='Number of trading sessions, e.g. 5d, 10d, 20d (default: 10d)')
    default_config = Path('config') if Path('config/scanner.yaml').is_file() else Path(__file__).resolve().parents[1] / 'config'
    parser.add_argument('--config-dir', type=Path, default=default_config)
    parser.add_argument('--output-dir', type=Path, default=Path('output/reports'))
    args = parser.parse_args(argv)
    try:
        normalize_symbol(args.symbol)
        parse_period(args.period)
    except ValueError as exc:
        parser.error(str(exc))
    try:
        config = yaml.safe_load((args.config_dir / 'scanner.yaml').read_text(encoding='utf-8'))
        universe = yaml.safe_load((args.config_dir / 'universe.yaml').read_text(encoding='utf-8'))
        report = lookup_stock(args.symbol, args.period, config, universe,
                              report_dirs=list(dict.fromkeys([Path('data/reports').resolve(), PROJECT_ROOT / 'data/reports'])))
        for message in report.messages:
            print(message)
        path = save_stock_history(report, args.output_dir)
        if path is None:
            print('No history report generated: no completed local trading sessions are available.')
            return 1
        print(f'{report.symbol}: {len(report.rows)} trading sessions, {report.start} through {report.through}.')
        print(f"Latest state: {report.rows[0].get('state') or 'N/A'}")
        print(f'Stock history HTML: {path}')
        return 0
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as exc:
        print(f'Unable to generate stock history: {exc}', file=sys.stderr)
        return 1


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv and argv[0] == 'find-pattern':
        from stock_scanner.find_pattern import main as find_pattern_main
        return find_pattern_main(argv[1:])
    if argv and argv[0] == 'lookup':
        return lookup_main(argv[1:])
    if argv and argv[0] == 'scan':
        argv = argv[1:]
    load_dotenv()

    parser = argparse.ArgumentParser(description="Deterministic Daily/Weekly Stock Scanner System",
                                     epilog='History: python -m stock_scanner lookup NVDA --period 10d')
    parser.add_argument("--category", type=str, help="Scan a specific stock category from universe.yaml")
    parser.add_argument("--symbol", type=str, help="Scan a single stock symbol")
    parser.add_argument("--state", type=str, help="Filter results by state (e.g. STRONG_UPTREND, UPTREND, BOTTOM_FORMING, REVERSAL)")
    parser.add_argument("--top", type=int, help="Display top N results per state")
    parser.add_argument("--ai", action="store_true", help="Enable Google Gemini AI explanations")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--report-period", choices=['daily', 'weekly', 'both', 'auto'], default='auto',
                        help="auto adds a weekly report after the week's final market close (default)")

    args = parser.parse_args(argv)

    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    print("Starting Stock Scanner...")
    scanner = StockScanner()

    scan_out = scanner.scan(
        target_category=args.category,
        target_symbol=args.symbol,
        target_state=args.state,
        enable_ai=args.ai,
        top_n=args.top,
        report_period=args.report_period,
    )

    # scan() returns (results, report_context) for a full daily scan, or just
    # results for a filtered/custom scan.
    if isinstance(scan_out, tuple):
        results, report_context = scan_out
    else:
        results, report_context = scan_out, None

    if report_context and report_context.get('generate_weekly'):
        weekly = WeeklyReport(report_context.get('weekly_records', []),
                              report_context['weekly_context'], report_context['sector_indexes_cfg'],
                              scope=report_context['scope'])
        print(render_weekly_text(weekly))
        paths = save_weekly_report(weekly)
        print('Weekly report files saved:')
        for label, path in paths.items():
            print(f' - {label}: {path}')

    if not results:
        print("No scan results generated.")
        return

    # Display console report
    state_breakdown = StateBreakdown(results, top_n=args.top)
    display_console_report(results, top_n=args.top, state_breakdown=state_breakdown)

    # Determine the scan date from the actual data.
    # yfinance only provides data up to the last trading day, so use the
    # data_date from the first result rather than today's date to avoid
    # mismatching "today's date" with "yesterday's data".
    data_date = None
    if results:
        data_date = results[0].get('data_date')
    if not data_date:
        data_date = datetime.now().strftime("%Y-%m-%d")

    state_path = save_state_breakdown(state_breakdown, data_date)
    print(f'State breakdown HTML: {Path(state_path).resolve()}')

    csv_path = save_csv_report(results, output_dir="data/reports", scan_date=data_date)
    json_path = save_json_report(results, output_dir="data/reports", scan_date=data_date)

    print(f"Reports saved successfully:")
    print(f" - CSV:  {csv_path}")
    print(f" - JSON: {json_path}")

    # Generate the enhanced daily report (TXT / CSV / HTML) automatically when
    # a full daily scan is available.
    if report_context is not None and args.report_period != 'weekly':
        try:
            report = DailyReport(results, report_context, scan_date=data_date, state_breakdown=state_breakdown)
            print("\n" + "=" * 60)
            print("STOCK SCANNER DAILY REPORT")
            print("=" * 60)
            from stock_scanner.src.reporting.renderers import render_terminal_report
            print(render_terminal_report(report))

            report_paths = save_daily_report(report, output_dir="output/reports", scan_date=data_date)
            print("\nDaily report files saved:")
            print(f" - TXT:  {report_paths['txt']}")
            print(f" - CSV:  {report_paths['csv']}")
            for label, path in report_paths['separate_csv'].items():
                print(f" - CSV ({label}): {path}")
            print(f" - HTML: {report_paths['html']}")
        except Exception as e:
            print(f"Failed to generate daily report: {e}")


if __name__ == "__main__":
    raise SystemExit(main())
