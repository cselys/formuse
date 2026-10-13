"""Terminal, HTML and JSON outputs for read-only historical pattern queries."""
from datetime import datetime
from html import escape
import json
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo


def _value(value):
    if value is None:
        return 'N/A'
    if isinstance(value, float):
        return f'{value:.2f}'
    if isinstance(value, list):
        return ', '.join(map(str, value)) if value else 'N/A'
    return str(value)


def report_tables(report):
    if report['mode'] == 'auto':
        yield 'Discovered patterns', ['Pattern', 'Occurrences', 'Distinct stocks', 'Most recent', 'Examples'], [
            [' -> '.join(r['states']), r['occurrences'], r['distinct_symbols'], r['most_recent_date'],
             '; '.join(f"{e['symbol']} {e['start_date']} to {e['end_date']}" for e in r['examples'])] for r in report['patterns']]
    else:
        yield 'Exact pattern matches', ['Symbol', 'Current categories', 'Pattern', 'Start', 'End', 'Sessions',
              'Start price', 'End price', 'Change %', 'Latest recorded date', 'Latest state', 'Latest Candidate', 'Verification', 'Within recent window'], [
            [r['symbol'], r['categories'], ' -> '.join(r['states']), r['start_date'], r['end_date'], r['sessions'],
             r['start_price'], r['end_price'], r['price_change_pct'], r['latest_recorded_date'], r['latest_recorded_state'],
             r['latest_candidate_score'], r['verification_status'], r['final_within_recent_window']] for r in report['matches']]
    yield 'History coverage', ['Symbol', 'Current categories', 'Eligible sessions', 'Requested including lookback', 'Missing or excluded sessions'], [
        [r['symbol'], r['categories'], r['eligible_sessions'], r['requested_sessions'], r['missing_or_excluded_sessions']] for r in report['coverage']]
    yield 'Excluded observations', ['Symbol', 'Date', 'Reason'], [[r['symbol'], r['date'], r['reason']] for r in report['excluded_observations']]


def summary(report):
    return [f"Historical state pattern finder: {report['status']}",
            f"Mode: {report['mode']} | As-of: {report['as_of']}",
            f"Recent final-state window: {report['recent_start']} through {report['recent_end']} (completed NYSE sessions)",
            f"Options: {json.dumps(report['options'], sort_keys=True)}",
            f"Canonical source: {report['source']['path']} ({report['source']['status']})",
            f"Unverified store artifacts (all dates, excluded): {report['source']['legacy_counts']}",
            f"Evaluable windows: {report['usable_windows']} | Occurrences: {report['total_occurrences']} | Qualifying distinct patterns: {report['total_patterns']}",
            f"Policy-boundary windows excluded: {report['policy_breaks']} | Symbols with any eligible coverage: {sum(r['eligible_sessions'] > 0 for r in report['coverage'])}/{len(report['coverage'])}"]


def render_terminal(report):
    lines = summary(report) + report['issues'] + report['messages']
    # Keep terminal concise; the reports contain all per-symbol coverage details.
    title, headers, rows = next(report_tables(report))
    lines.extend(['', title, ' | '.join(headers)])
    lines.extend(' | '.join(_value(v) for v in row) for row in rows)
    if not rows:
        lines.append(report['status'] + ': no result rows to display.')
    return '\n'.join(lines)


def render_html(report):
    parts = ['<!doctype html><html lang="en"><head><meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width, initial-scale=1"><title>Historical state patterns</title>',
             '<style>body{font:14px "Segoe UI",Arial,sans-serif;background:#f5f7fa;color:#203047;margin:28px}h1,h2{color:#16213e}.table-wrap{overflow-x:auto}table{border-collapse:collapse;background:white;width:100%;margin-bottom:24px}th,td{padding:10px;border-bottom:1px solid #dce2e9;text-align:left}th{background:#16213e;color:white}tr:nth-child(even){background:#edf2f9}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style></head><body><h1>Historical state patterns</h1>']
    parts.extend(f'<p>{escape(line)}</p>' for line in summary(report))
    parts.append('<ul>' + ''.join(f'<li>{escape(line)}</li>' for line in report['issues'] + report['messages']) + '</ul>')
    for title, headers, rows in report_tables(report):
        parts.append(f'<h2>{escape(title)}</h2><div class="table-wrap"><table><thead><tr>' +
                     ''.join(f'<th>{escape(h)}</th>' for h in headers) + '</tr></thead><tbody>')
        for row in rows:
            parts.append('<tr>' + ''.join(f'<td>{escape(_value(v))}</td>' for v in row) + '</tr>')
        if not rows:
            parts.append(f'<tr><td colspan="{len(headers)}">No entries — {escape(report["status"])}</td></tr>')
        parts.append('</tbody></table></div>')
    parts.append('<details><summary>Matching observation provenance</summary><pre>' +
                 escape(json.dumps(report['matches'], indent=2, allow_nan=False)) + '</pre></details></body></html>')
    return ''.join(parts)


def save_reports(report, output_dir='output/reports/patterns'):
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    contents = {'json': json.dumps(report, indent=2, allow_nan=False), 'html': render_html(report)}
    stamp = datetime.now(ZoneInfo('America/New_York')).strftime('%Y%m%d_%H%M%S_%f_ET')
    while True:
        stem = f'patterns_{report["mode"]}_{stamp}_{uuid4().hex}'
        paths = {ext: directory / f'{stem}.{ext}' for ext in contents}
        created = []
        try:
            for ext, content in contents.items():
                with paths[ext].open('x', encoding='utf-8') as stream:
                    created.append(paths[ext])
                    stream.write(content)
            return {ext: str(path.resolve()) for ext, path in paths.items()}
        except FileExistsError:
            for path in created:
                path.unlink()  # Only this attempt's newly created output files.
        except OSError:
            for path in created:
                path.unlink()
            raise
