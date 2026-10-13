"""Completed-week snapshots and matching market intelligence report exports."""
import csv
import html
import io
import json
import logging
import math
from pathlib import Path

import pandas as pd

from stock_scanner.src.analysis.snapshot import analyze_snapshot
from stock_scanner.src.analysis.weekly_diagnostics import weekly_diagnostics
from stock_scanner.src.data.market_calendar import completed_daily, completed_weekly
from stock_scanner.src.reporting.daily_report import DailyReport
from stock_scanner.src.reporting.stock_rankings import _is_stock

logger = logging.getLogger('stock_scanner.reporting')


def build_weekly_records(raw, symbols, benchmarks, index_symbols, config, context):
    """Scores and diagnostics use the final session of the requested week."""
    empty = pd.DataFrame(columns=['Open', 'High', 'Low', 'Close', 'Volume'], index=pd.DatetimeIndex([]))
    daily, weekly = {}, {}
    for symbol, frame in raw.items():
        try:
            daily[symbol] = completed_daily(frame, context['last_session'])
            weekly[symbol] = completed_weekly(daily[symbol], context['last_session'])
        except (ValueError, TypeError, KeyError):
            logger.exception('Invalid weekly input for %s', symbol)
            daily[symbol], weekly[symbol] = empty, empty
    market_symbol = 'SPY' if 'SPY' in daily else 'QQQ'
    market = daily.get(market_symbol, empty)
    records = []
    for symbol, category in symbols.items():
        df = daily.get(symbol, empty)
        w = weekly.get(symbol, empty)
        benchmark_symbol = benchmarks.get(category, 'SPY')
        benchmark = daily.get(benchmark_symbol, empty)
        record = {
            'symbol': symbol, 'category': category, 'is_index_etf': symbol in index_symbols,
            'scanner_version': config.get('scanner_version', '1.2'),
            'score_as_of': context['last_session'],
            'data_date': str(df.index[-1].date()) if not df.empty else None,
            'market_benchmark': market_symbol, 'category_benchmark': benchmark_symbol,
        }
        try:
            if not w.empty and str(w.index[-1].date()) == context['week_end']:
                record.update(analyze_snapshot(df, w, benchmark, market, config))
            record['weekly_diagnostics'] = weekly_diagnostics(
                w, record.get('daily', {}), config, context,
                weekly.get(market_symbol), weekly.get(benchmark_symbol))
        except Exception:
            logger.exception('Unable to analyze weekly snapshot for %s', symbol)
            record['weekly_diagnostics'] = {'status': 'ANALYSIS_ERROR', 'weekly_change_pct': None}
        records.append(record)
    return records


def _clean(value):
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


class WeeklyReport:
    def __init__(self, records, context, sector_indexes, scope='full universe'):
        self.context = context
        self.scope = scope
        self.records = _clean(records)
        stocks = [r for r in self.records if _is_stock(r)]
        adapted = []
        self.diagnostics = []
        for r in stocks:
            d = r['weekly_diagnostics']
            adapted.append({**r, 'daily_change_pct': d.get('weekly_change_pct'),
                            'daily': {'close': d.get('weekly_close')}})
            ind = d.get('indicators', {})
            st = d.get('structure', {})
            self.diagnostics.append({
                'symbol': r['symbol'], 'category': r['category'], 'status': d['status'],
                'data_date': r.get('data_date'), 'data_week_end': d.get('data_week_end'),
                'weekly_change_pct': d.get('weekly_change_pct'), 'weekly_direction': d.get('weekly_direction'),
                'daily_direction': d.get('daily_direction'), 'alignment': d.get('alignment'),
                'state': r.get('state'), 'candidate_score': r.get('candidate_score'),
                'entry_quality': r.get('entry_quality'), 'score_as_of': r.get('score_as_of'),
                'rsi': ind.get('rsi'), 'rsi_change': d.get('rsi_change'),
                'macd_hist': ind.get('macd_hist'), 'macd_hist_change': d.get('macd_hist_change'),
                'volume_ratio': ind.get('volume_ratio'), 'atr': ind.get('atr'),
                'ema20': ind.get('ema20'), 'ema40': ind.get('ema40'),
                'ema20_slope': ind.get('ema20_slope'),
                'higher_high': st.get('higher_high'), 'higher_low': st.get('higher_low'),
                'lower_high': st.get('lower_high'), 'lower_low': st.get('lower_low'),
                'breakout': st.get('recent_breakout'), 'breakdown': st.get('recent_breakdown'),
                'market_benchmark': r.get('market_benchmark'), 'category_benchmark': r.get('category_benchmark'),
                **{f'market_{k}': v for k, v in d.get('relative_strength_market', {}).items()},
                **{f'category_{k}': v for k, v in d.get('relative_strength_category', {}).items()},
            })
        by_symbol = {r['symbol']: r for r in self.records}
        indexes = {}
        for sector, symbol in sector_indexes.items():
            r = by_symbol.get(symbol.upper(), {})
            d = r.get('weekly_diagnostics', {})
            indexes[sector] = {'symbol': symbol, 'sector': sector, 'close': d.get('weekly_close'),
                               'change_pct': d.get('weekly_change_pct'), 'status': d.get('status', 'MISSING')}
        base = DailyReport(adapted, {'sector_index_data': indexes}, context['week_end'])
        def columns(names):
            return [{k: r.get(k) for k in names.split()} for r in self.diagnostics]

        self.sections = {
            'TOP 10 STOCKS UP': base.top_stocks_up,
            'TOP 10 STOCKS DOWN': base.top_stocks_down,
            'TOP 3 SECTORS UP - STOCK BREADTH': base.top_sectors_up,
            'TOP 3 SECTORS DOWN - STOCK BREADTH': base.top_sectors_down,
            'TOP 3 SECTOR INDEXES UP': [r for r in base.sector_indexes_up if r['change_pct'] > 0],
            'TOP 3 SECTOR INDEXES DOWN': [r for r in base.sector_indexes_down if r['change_pct'] < 0],
            'ALL SECTOR BREADTH': base.sector_breadth,
            'SECTOR INDEX COVERAGE': list(indexes.values()),
            'TOP SCANNER CANDIDATES': sorted(
                [r for r in columns('symbol category state candidate_score entry_quality weekly_direction alignment')
                 if r['candidate_score'] is not None], key=lambda r: (-r['candidate_score'], r['symbol']))[:10],
            'WEEKLY TECHNICAL DIAGNOSTICS': columns('symbol status weekly_direction daily_direction alignment data_date data_week_end'),
            'WEEKLY TREND AND MOMENTUM': columns('symbol ema20 ema40 ema20_slope rsi rsi_change macd_hist macd_hist_change volume_ratio atr'),
            'WEEKLY STRUCTURE': columns('symbol higher_high higher_low lower_high lower_low breakout breakdown'),
            'WEEKLY RELATIVE STRENGTH': columns('symbol market_benchmark market_rs_4w market_rs_12w category_benchmark category_rs_4w category_rs_12w'),
        }
        valid = sum(r['weekly_diagnostics'].get('weekly_change_pct') is not None for r in stocks)
        self.coverage = {'requested_stocks': len(stocks), 'valid_weekly_returns': valid,
                         'missing_weekly_returns': len(stocks) - valid,
                         'ready_diagnostics': sum(r['weekly_diagnostics']['status'] == 'OK' for r in stocks)}

    def metadata(self):
        return {
            **self.context, 'scope': self.scope, **self.coverage,
            'scanner_version': self.records[0].get('scanner_version') if self.records else None,
            'market_regime_at_week_close': next((r.get('market_regime') for r in self.records if r.get('market_regime')), 'UNAVAILABLE'),
            'return_definition': 'Previous completed weekly close to latest completed weekly close',
            'score_basis': 'Existing daily/weekly scanner formulas at last_session; not a new weekly score',
            'direction_definition': 'UP: close > EMA20 > slow EMA and rising EMA20; DOWN: inverse; otherwise MIXED',
            'direction_slow_ema': 'Weekly EMA40; daily EMA50',
            'structure_note': 'Swing points require five subsequent completed weeks for confirmation',
        }


def _csv(rows):
    if not rows:
        return 'No data\n'
    stream = io.StringIO(newline='')
    columns = list(dict.fromkeys(k for row in rows for k in row))
    writer = csv.DictWriter(stream, fieldnames=columns, lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def render_weekly_text(report):
    parts = ['STOCK SCANNER WEEKLY REPORT']
    parts.extend(f'{key.replace("_", " ").title()}: {value}' for key, value in report.metadata().items())
    for title, rows in report.sections.items():
        parts.extend(['', title])
        if not rows:
            parts.append('No data')
            continue
        columns = list(dict.fromkeys(k for row in rows for k in row))
        cells = [[k.replace('_', ' ').title() for k in columns]]
        cells.extend([_display(row.get(k)) for k in columns] for row in rows)
        widths = [max(len(row[i]) for row in cells) for i in range(len(columns))]
        parts.append(' | '.join(cell.ljust(width) for cell, width in zip(cells[0], widths)))
        parts.append('-+-'.join('-' * width for width in widths))
        parts.extend(' | '.join(cell.ljust(width) for cell, width in zip(row, widths)) for row in cells[1:])
    return '\n'.join(parts)


def _display(value):
    if value is None:
        return 'N/A'
    if isinstance(value, float):
        return f'{value:.2f}'
    return str(value)


def save_weekly_report(report, output_dir='output/reports'):
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    base = directory / f"weekly_report_{report.context['week_end']}"
    sections_html = []
    for title, rows in report.sections.items():
        if rows:
            columns = list(dict.fromkeys(k for row in rows for k in row))
            head = ''.join(f'<th>{html.escape(k.replace("_", " ").title())}</th>' for k in columns)
            body = ''.join('<tr>' + ''.join(f'<td>{html.escape(_display(row.get(k)))}</td>' for k in columns) + '</tr>' for row in rows)
            table = f'<div class="table"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'
        else:
            table = '<p>No data</p>'
        sections_html.append(f'<h2>{html.escape(title)}</h2>{table}')
    metadata = ''.join(f'<p><b>{html.escape(k.replace("_", " ").title())}:</b> {html.escape(str(v))}</p>' for k, v in report.metadata().items())
    document = ('<!doctype html><html lang="en"><meta charset="utf-8">'
                '<title>Stock Scanner Weekly Report</title><style>'
                'body{font:14px Segoe UI,Arial;margin:24px;background:#f7f7f7;color:#222}'
                'table{border-collapse:collapse;background:white}th,td{padding:8px;border:1px solid #ddd;white-space:nowrap}'
                'th{background:#16213e;color:white}.table{overflow-x:auto}h2{margin-top:30px}'
                '</style><h1>Stock Scanner Weekly Report</h1>' + metadata + ''.join(sections_html) + '</html>')
    content = {
        'txt': render_weekly_text(report), 'html': document,
        'csv': _csv([report.metadata()]) + '\n' + '\n'.join(title + '\n' + _csv(rows) for title, rows in report.sections.items()),
        'json': json.dumps({'metadata': report.metadata(), 'sections': report.sections, 'records': report.records}, indent=2, allow_nan=False),
    }
    paths = {}
    for extension, body in content.items():
        path = base.with_suffix('.' + extension)
        path.write_text(body, encoding='utf-8')
        paths[extension] = str(path)
    for key, rows in [('stocks_up', report.sections['TOP 10 STOCKS UP']),
                      ('stocks_down', report.sections['TOP 10 STOCKS DOWN']),
                      ('sectors', report.sections['ALL SECTOR BREADTH']),
                      ('sector_indexes', report.sections['SECTOR INDEX COVERAGE']),
                      ('diagnostics', report.diagnostics)]:
        path = directory / f"weekly_{key}_{report.context['week_end']}.csv"
        path.write_text(_csv(rows), encoding='utf-8')
        paths[key] = str(path)
    return paths
