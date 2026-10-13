"""One state grouping and row model for terminal and HTML reports."""
from dataclasses import dataclass
from html import escape
from pathlib import Path

STATE_ORDER = (
    'STRONG_UPTREND', 'UPTREND', 'EARLY_UPTREND', 'BOTTOM_FORMING',
    'BOTTOM_BREAKOUT', 'REVERSAL', 'REVERSAL_CONFIRMED', 'NEUTRAL',
    'DOWNTREND', 'STRONG_DOWNTREND', 'AVOID',
)
FIELDS = (
    ('symbol', 'Symbol'), ('category', 'Category'), ('candidate_score', 'Candidate Score'),
    ('trend_score', 'Trend Score'), ('entry_quality', 'Entry Quality'),
    ('bottom_score', 'Bottom Score'), ('reversal_score', 'Reversal Score'),
    ('rs_20d', 'RS (20d) %'), ('rsi', 'RSI'), ('distance_ema20', 'EMA20 Distance %'),
)


@dataclass
class StateGroup:
    state: str
    rows: list
    total_count: int


class StateBreakdown:
    def __init__(self, results, top_n=None):
        grouped = {state: [] for state in STATE_ORDER}
        for record in results:
            state = record.get('state', 'NEUTRAL')
            grouped[state if state in grouped else 'NEUTRAL'].append(record)
        self.groups = []
        self.top_n = top_n
        for state in STATE_ORDER:
            items = sorted(grouped[state], key=lambda r: r.get('candidate_score', 0), reverse=True)
            if not items:
                continue
            total_count = len(items)
            if top_n:
                items = items[:top_n]
            rows = []
            for record in items:
                row = {key: record.get(key, '' if key in ('symbol', 'category') else 0)
                       for key, _ in FIELDS[:7]}
                row.update(rs_20d=record.get('relative_strength', {}).get('rs_20d', 0.0),
                           rsi=record.get('daily', {}).get('rsi', 50.0),
                           distance_ema20=record.get('daily', {}).get('distance_ema20', 0.0))
                # Preserve an existing tier; do not infer an actionable/watchlist label.
                if 'signal_tier' in record:
                    row['signal_tier'] = record['signal_tier']
                rows.append(row)
            self.groups.append(StateGroup(state, rows, total_count))


def formatted_row(row):
    values = []
    for key, _ in FIELDS:
        value = row[key]
        if key in ('symbol', 'category'):
            values.append(str(value))
        elif key == 'rs_20d':
            values.append(f'{value:+.1f}%')
        elif key == 'distance_ema20':
            values.append(f'{value:+.1f}%')
        else:
            values.append(f'{value:.1f}')
    return values


def render_state_terminal(model):
    parts = ['\n' + '=' * 110, ' ' * 40 + 'STATE BREAKDOWN', '=' * 110]
    for group in model.groups:
        parts.extend([
            f'\n--- {group.state} ({len(group.rows)} symbols) ---',
            f"{'Symbol':<8} {'Cat':<15} {'CandScore':<10} {'Trend':<7} {'EntryQ':<7} {'Bottom':<7} {'Revers':<7} {'RS(20d)':<9} {'RSI':<6} {'EMA20%':<7}",
            '-' * 110,
        ])
        for row in group.rows:
            sym, cat, cand, trend, entry, bottom, reversal, rs, rsi, distance = formatted_row(row)
            parts.append(f'{sym:<8} {cat:<15} {cand:<10} {trend:<7} {entry:<7} {bottom:<7} {reversal:<7} {rs:<10} {rsi:<6} {distance:<8}')
    parts.append('\n' + '=' * 110 + '\n')
    return '\n'.join(parts)


def render_state_section(model):
    parts = ['<h2>STATE BREAKDOWN</h2>']
    if not model.groups:
        parts.append('<p>No scan results.</p>')
    for group in model.groups:
        extra = any('signal_tier' in r for r in group.rows)
        title = f'{group.state} ({len(group.rows)} symbols)'
        parts.append(f'<h3>{escape(title)}</h3>')
        if len(group.rows) != group.total_count:
            parts.append(f'<p>Showing {len(group.rows)} of {group.total_count} in this state.</p>')
        heads = [label for _, label in FIELDS] + (['Signal Tier'] if extra else [])
        parts.append('<div class="state-table"><table><thead><tr>' + ''.join(f'<th>{escape(h)}</th>' for h in heads) + '</tr></thead><tbody>')
        for row in group.rows:
            cells = formatted_row(row) + ([str(row.get('signal_tier', 'N/A'))] if extra else [])
            parts.append('<tr>' + ''.join(f'<td>{escape(c)}</td>' for c in cells) + '</tr>')
        parts.append('</tbody></table></div>')
    return '\n'.join(parts)


def save_state_breakdown(model, scan_date, output_dir='output/reports'):
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f'state_breakdown_{scan_date}.html'
    page = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>State Breakdown — {escape(scan_date)}</title>'
            '<style>body{font:15px Segoe UI,Arial;background:#f7f7f7;color:#222;margin:24px}'
            'table{border-collapse:collapse;background:white}th,td{padding:8px;border:1px solid #ddd;text-align:left;white-space:nowrap}'
            'th{background:#16213e;color:white}.state-table{overflow-x:auto}h3{margin-top:28px}</style></head><body>'
            f'<h1>Stock Scanner State Breakdown</h1><p>Data date: {escape(scan_date)}</p>'
            + render_state_section(model) + '</body></html>')
    path.write_text(page, encoding='utf-8')
    return str(path)
