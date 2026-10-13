"""Standalone HTML renderer for structured stock history, with no web runtime."""
from html import escape
import json
from pathlib import Path

LOOKUP_FIELDS = (
    ('date', 'Date'), ('close', 'Close'), ('daily_change_pct', 'Daily %'), ('state', 'State'),
    ('candidate_score', 'Candidate Score'), ('trend_score', 'Trend Score'),
    ('entry_quality', 'Entry Quality'), ('bottom_score', 'Bottom Score'),
    ('reversal_score', 'Reversal Score'), ('rs_20d', 'RS 20d %'), ('rs_60d', 'RS 60d %'),
    ('rsi', 'RSI'), ('market_regime', 'Market Regime'), ('transition', 'State Transition'),
    ('source', 'Result Source'), ('scanner_version', 'Scanner Version'), ('missing_reason', 'Missing Data'),
    ('calculation_policy', 'Calculation Policy'), ('market_benchmark', 'Market Benchmark'),
    ('reconciliation_status', 'Revision Status'),
)


def _format(key, value):
    if value is None:
        return 'N/A'
    if isinstance(value, float):
        return f'{value:.1f}' if key.endswith('_score') or key == 'entry_quality' else f'{value:.2f}'
    return str(value)


def render_stock_history(report):
    latest = report.rows[0] if report.rows else {}
    summary = {
        'Symbol': report.symbol, 'Period': f'{report.requested_sessions} trading days',
        'From': report.start, 'Through': report.through, 'Trading sessions': len(report.rows),
        'Latest state': latest.get('state'), 'Latest Candidate Score': latest.get('candidate_score'),
        'Latest Market Regime': latest.get('market_regime'), 'Scanner version': report.scanner_version,
    }
    metadata = ''.join(f'<div><dt>{escape(k)}</dt><dd>{escape(_format(k, v))}</dd></div>' for k, v in summary.items())
    messages = ''.join(f'<li>{escape(message)}</li>' for message in report.messages)
    fields = list(LOOKUP_FIELDS)
    if any(row.get('signal_tier') is not None for row in report.rows):
        fields.insert(4, ('signal_tier', 'Signal Tier'))
    header = ''.join(f'<th scope="col">{escape(label)}</th>' for _, label in fields)
    body = []
    provenance = []
    for row in report.rows:
        cells = []
        for key, _ in fields:
            value = escape(_format(key, row.get(key)))
            if key == 'state':
                value = f'<span class="badge">{value}</span>'
            cells.append(f'<td>{value}</td>')
        changed = ' class="changed"' if row.get('transition') else ''
        body.append(f'<tr{changed}>' + ''.join(cells) + '</tr>')
        details = {'provenance': row.get('provenance'),
                   'observed_revision_ids': row.get('observed_revision_ids', []),
                   'legacy_artifacts': row.get('legacy_artifacts', [])}
        provenance.append(f'<details><summary>{escape(row["date"])} — provenance and '
                          'RECORDED_LEGACY / UNVERIFIED artifacts</summary><pre>'
                          f'{escape(json.dumps(details, indent=2, default=str))}</pre></details>')
    title = f'{report.symbol} — {report.requested_sessions} Trading Day History'
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{escape(title)}</title><style>'
            'body{font:15px Segoe UI,Arial,sans-serif;margin:28px;color:#203047;background:#f5f7fa}'
            'h1{font-size:26px}dl{display:flex;flex-wrap:wrap;gap:18px;padding:20px;background:white;border-radius:8px}'
            'dt{font-size:12px;color:#526175}dd{margin:5px 0;font-weight:600}'
            '.table-wrap{overflow-x:auto;border:1px solid #dce2e9;border-radius:6px;background:white}'
            'table{border-collapse:collapse;width:100%}th,td{padding:10px;border-bottom:1px solid #dce2e9;white-space:nowrap;text-align:left}'
            'th{background:#16213e;color:white;font-size:12px}td{font-size:13px}'
            '.badge{padding:4px 7px;background:#edf2f9;border-radius:4px;font-weight:600}'
            'tr.changed{background:#fff3d4}tr.changed td:first-child{border-left:4px solid #b77700}'
            '.notes{line-height:1.6}li{margin:5px 0}@media print{.table-wrap{overflow:visible}body{margin:0;font-size:10px}}'
            '</style></head><body>'
            f'<h1>{escape(title)}</h1><dl>{metadata}</dl><ul class="notes">{messages}</ul>'
            '<p>Newest session first. Highlighted rows mark a change from the immediately preceding displayed trading session. '
            'Missing states break the transition chain.</p>'
            f'<div class="table-wrap"><table><thead><tr>{header}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'
            '<p>Unverified archives below are historical artifacts, not inputs to the verified scores above.</p>'
            f'{"".join(provenance)}'
            '</body></html>')


def save_stock_history(report, output_dir='output/reports'):
    if not report.rows:
        return None
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f'stock_history_{report.symbol}_{report.requested_sessions}d_{report.through}.html'
    path.write_text(render_stock_history(report), encoding='utf-8')
    return str(path.resolve())
