"""CLI adapter for the isolated historical state pattern finder."""
import argparse
from pathlib import Path
import sys

import yaml

from stock_scanner.src.historical.pattern_finder import find_patterns, validate_options
from stock_scanner.src.historical.pattern_source import DEFAULT_STORE
from stock_scanner.src.reporting.pattern_report import render_terminal, save_reports


def main(argv=None):
    parser = argparse.ArgumentParser(description='Query existing verified canonical history; no downloads or state recalculation.',
        epilog='States occupy consecutive completed NYSE sessions (no compression or gap skipping). The final state must be within recent-days; span counts both endpoints. Unverified/conflicting observations are excluded.')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--states', help='Exact comma-separated sequence of 2 or 3 scanner states')
    mode.add_argument('--auto', action='store_true', help='Discover sequences of 2 through max-states daily observations')
    parser.add_argument('--recent-days', type=int, default=10, help='Recent completed trading sessions for the final state (default 10)')
    parser.add_argument('--max-states', type=int, choices=(2, 3), default=3)
    parser.add_argument('--max-span-days', type=int, default=20, help='Maximum inclusive trading-session span, 1–20 (default 20)')
    parser.add_argument('--min-occurrences', type=int, default=1, help='Minimum occurrence count in automatic mode (default 1)')
    parser.add_argument('--limit', type=int, default=100, help='Maximum displayed matches or discovered patterns (default 100); counts remain complete')
    parser.add_argument('--as-of', help='Evaluation cutoff: ISO timestamp or YYYY-MM-DD (date-only means end of day ET)')
    default_config = Path('config') if Path('config/scanner.yaml').is_file() else Path(__file__).resolve().parents[1] / 'config'
    parser.add_argument('--config-dir', type=Path, default=default_config)
    parser.add_argument('--history-store', type=Path, default=DEFAULT_STORE, help='Existing canonical lookup SQLite store; opened read-only')
    parser.add_argument('--output-dir', type=Path, default=Path('output/reports/patterns'))
    args = parser.parse_args(argv)
    options = {name: getattr(args, name) for name in ('states', 'auto', 'recent_days', 'max_states', 'max_span_days', 'min_occurrences', 'limit')}
    try:
        validate_options(**options)
    except ValueError as exc:
        parser.error(str(exc))
    try:
        universe = yaml.safe_load((args.config_dir / 'universe.yaml').read_text(encoding='utf-8'))
        if not isinstance(universe, dict) or not isinstance(universe.get('categories'), dict):
            raise ValueError('Universe must contain a categories mapping')
        report = find_patterns(universe, **options, as_of=args.as_of, store_path=args.history_store)
        outputs = save_reports(report, args.output_dir)
        print(render_terminal(report))
        print(f"HTML: {outputs['html']}\nJSON: {outputs['json']}")
        return 2 if report['status'] == 'INSUFFICIENT_HISTORY' else 0
    except (OSError, ValueError, TypeError, KeyError, AttributeError, yaml.YAMLError) as exc:
        print(f'Unable to query historical patterns: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
