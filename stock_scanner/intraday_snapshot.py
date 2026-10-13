"""Independent snapshot CLI: python -m stock_scanner.intraday_snapshot."""
import argparse
from datetime import datetime, time, timezone
from html import escape
import math
from pathlib import Path
import re
import sys
from uuid import uuid4
from zoneinfo import ZoneInfo

import yaml

from stock_scanner.intraday_quotes import YahooQuotes

ET = ZoneInfo('America/New_York')
TITLES = (
    'TOP 10 STOCKS UP', 'TOP 10 STOCKS DOWN',
    'TOP 3 SECTORS UP — STOCK BREADTH', 'TOP 3 SECTORS DOWN — STOCK BREADTH',
    'TOP 3 SECTOR INDEXES UP', 'TOP 3 SECTOR INDEXES DOWN',
)


def read_universe(path):
    config = yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    if not isinstance(config, dict) or not isinstance(config.get('categories'), dict):
        raise ValueError('Universe must contain a categories mapping')
    symbols, excluded, categories, indexes, invalid = set(), set(), {}, {}, []

    def add(value, location):
        if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9^][A-Za-z0-9.^=\-]*', value.strip()):
            invalid.append(f'{location}: invalid symbol {value!r}')
            return None
        symbol = value.strip().upper()
        symbols.add(symbol)
        return symbol

    for field in ('market_benchmarks', 'etf_symbols'):
        for value in config.get(field, []):
            symbol = add(value, field)
            if symbol:
                excluded.add(symbol)
    for sector, value in config.get('sector_indexes', {}).items():
        symbol = add(value, f'sector_indexes.{sector}')
        if symbol:
            indexes[str(sector)] = symbol
            excluded.add(symbol)
    for name, category in config['categories'].items():
        if not isinstance(category, dict) or not isinstance(category.get('symbols', []), list):
            raise ValueError(f'Invalid category: {name}')
        members = set()
        for value in category.get('symbols', []):
            symbol = add(value, f'categories.{name}')
            if symbol:
                members.add(symbol)
        categories[str(name)] = members
        if str(category.get('instrument_type', '')).lower() in ('index', 'etf'):
            excluded.update(members)
        if category.get('benchmark') is not None:
            symbol = add(category['benchmark'], f'categories.{name}.benchmark')
            if symbol:
                excluded.add(symbol)
    return dict(symbols=sorted(symbols), excluded=excluded, categories=categories,
                indexes=indexes, invalid=invalid, config_path=str(Path(path).resolve()))


def session_context(now):
    """NYSE holidays and early closes, using the project's calendar dependency."""
    import pandas_market_calendars as mcal
    local = now.astimezone(ET)
    schedule = mcal.get_calendar('NYSE').schedule(local.date(), local.date())
    if schedule.empty:
        return 'CLOSED', None, None
    opening = schedule.iloc[0].market_open.to_pydatetime()
    closing = schedule.iloc[0].market_close.to_pydatetime()
    if opening <= now < closing:
        return 'REGULAR', opening, closing
    if local.time() >= time(4) and now < opening:
        return 'PREMARKET', opening, closing
    if closing <= now and local.time() < time(20):
        return 'AFTER_HOURS', opening, closing
    return 'CLOSED', opening, closing


def validate_quote(symbol, quote, now, session, opening, max_age):
    if not isinstance(quote, dict) or quote.get('symbol') != symbol:
        raise ValueError('Malformed quote or mismatched symbol')
    if session != 'REGULAR':
        raise ValueError(f'{session}: extended-hours/closed-session pricing unsupported')
    if quote.get('marketState') != 'REGULAR':
        raise ValueError(f"Provider session is {quote.get('marketState', 'unknown')}")
    if quote.get('exchangeTimezoneName') != 'America/New_York' or quote.get('currency') != 'USD':
        raise ValueError('Non-comparable market timezone or currency')
    if quote.get('quoteType') not in ('EQUITY', 'ETF', 'INDEX'):
        raise ValueError('Unknown or unsupported instrument type')
    try:
        if any(isinstance(quote.get(key), bool) for key in
               ('regularMarketPrice', 'regularMarketPreviousClose', 'regularMarketTime')):
            raise ValueError('Boolean quote field')
        price = float(quote['regularMarketPrice'])
        reference = float(quote['regularMarketPreviousClose'])
        timestamp = datetime.fromtimestamp(float(quote['regularMarketTime']), timezone.utc)
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        raise ValueError('Missing or invalid executed price, previous close or timestamp') from None
    if not all(math.isfinite(v) and v > 0 for v in (price, reference)):
        raise ValueError('Invalid executed price or previous regular close')
    age = (now - timestamp).total_seconds()
    if age < 0 or age > max_age or timestamp < opening:
        raise ValueError('Stale, future or out-of-session trade timestamp')
    change = (price / reference - 1) * 100
    if not math.isfinite(change):
        raise ValueError('Invalid percentage change')
    return dict(symbol=symbol, price=price, reference=reference, change=change,
                timestamp=timestamp.astimezone(ET).isoformat(), age=age,
                quote_type=quote['quoteType'], source=str(quote.get('quoteSourceName', 'Yahoo Finance')))


def build_report(universe, quotes, failures, now, max_age=300, label='Yahoo Finance quote snapshot'):
    if now.tzinfo is None or not math.isfinite(max_age) or max_age <= 0:
        raise ValueError('Timezone-aware timestamp and positive finite freshness limit required')
    # Reuse the unchanged daily report formula, without invoking StockScanner.
    from stock_scanner.src.reporting.sector_rankings import compute_sector_breadth
    session, opening, closing = session_context(now)
    priced, unavailable = {}, {}
    for symbol in universe['symbols']:
        if symbol not in quotes:
            unavailable[symbol] = failures.get(symbol, 'Provider returned no quote')
            continue
        try:
            priced[symbol] = validate_quote(symbol, quotes[symbol], now, session, opening, max_age)
        except ValueError as exc:
            unavailable[symbol] = str(exc)
    stocks, breadth_input, audit = {}, [], []
    for sector, members in sorted(universe['categories'].items()):
        eligible = 0
        for symbol in sorted(members):
            row = priced.get(symbol)
            if symbol in universe['excluded'] or not row or row['quote_type'] != 'EQUITY':
                continue
            eligible += 1
            stocks.setdefault(symbol, dict(row, sectors=[]))['sectors'].append(sector)
            breadth_input.append(dict(symbol=symbol, category=sector, daily_change_pct=row['change']))
        audit.append((sector, len(members), eligible))
    breadth = compute_sector_breadth(breadth_input)
    up = sorted(breadth, key=lambda r: (-r['up_ratio'], -r['sector_up_count'], -r['avg_change_pct'], r['sector']))[:3]
    down = sorted(breadth, key=lambda r: (-r['down_ratio'], -r['sector_down_count'], r['avg_change_pct'], r['sector']))[:3]
    index_rows = {}
    for sector, symbol in sorted(universe['indexes'].items()):
        if symbol in priced:
            index_rows.setdefault(symbol, dict(priced[symbol], sectors=[]))['sectors'].append(sector)

    def rank(rows, positive, count):
        return sorted((r for r in rows if (r['change'] > 0 if positive else r['change'] < 0)),
                      key=lambda r: (-r['change'] if positive else r['change'], r['symbol']))[:count]

    return dict(universe=universe, generated=now.astimezone(ET), session=session,
                priced=priced, unavailable=unavailable, max_age=max_age, label=label,
                sections=[rank(stocks.values(), True, 10), rank(stocks.values(), False, 10),
                          up, down, rank(index_rows.values(), True, 3), rank(index_rows.values(), False, 3)],
                breadth=breadth, audit=audit)


def tables(report):
    for i, (title, rows) in enumerate(zip(TITLES, report['sections'])):
        if i in (2, 3):
            headers = ['Sector', 'Advancing', 'Declining', 'Flat', 'Eligible', 'Breadth %']
            ratio = 'up_ratio' if i == 2 else 'down_ratio'
            values = [[r['sector'], r['sector_up_count'], r['sector_down_count'],
                       r['sector_flat_count'], r['total_stock_count'], f"{100*r[ratio]:.2f}%"] for r in rows]
        else:
            headers = ['Symbol', 'Sectors', 'Last trade', 'Previous close', 'Change', 'Trade time ET', 'Source']
            values = [[r['symbol'], ', '.join(r['sectors']), f"{r['price']:.4f}", f"{r['reference']:.4f}",
                       f"{r['change']:+.2f}%", r['timestamp'], r['source']] for r in rows]
        yield title, headers, values
    counts = {r['sector']: r for r in report['breadth']}
    yield 'CATEGORY COVERAGE AND BREADTH AUDIT', ['Category', 'Configured unique', 'Eligible stocks', 'Up', 'Down', 'Flat'], [
        [sector, total, eligible, counts.get(sector, {}).get('sector_up_count', 0),
         counts.get(sector, {}).get('sector_down_count', 0), counts.get(sector, {}).get('sector_flat_count', 0)]
        for sector, total, eligible in report['audit']]
    yield 'UNAVAILABLE SYMBOLS', ['Symbol', 'Reason'], list(sorted(report['unavailable'].items()))
    yield 'CONFIGURATION ISSUES', ['Issue'], [[issue] for issue in report['universe']['invalid']]


def summary(report):
    timestamps = [r['timestamp'] for r in report['priced'].values()]
    return [
        'INTRADAY MARKET SNAPSHOT', report['label'],
        f"Generated: {report['generated'].isoformat()} ET | Session: {report['session']}",
        f"Configuration: {report['universe']['config_path']}",
        f"Configured unique symbols: {len(report['universe']['symbols'])} | Priced: {len(report['priced'])} | Unavailable: {len(report['unavailable'])} | Invalid configuration entries: {len(report['universe']['invalid'])}",
        f"Accepted trade timestamps ET: {min(timestamps) if timestamps else 'N/A'} through {max(timestamps) if timestamps else 'N/A'}",
        f"Freshness limit: {report['max_age']:g} seconds. Regular session only; extended hours are unavailable.",
        'Change = (latest executed regular price / previous regular-session close - 1) * 100. No bid/ask or bar-history fallback.',
        'Flat stocks count in eligible breadth. Missing quotes never count as flat. ETFs/indexes are excluded from stock breadth.',
        'Ties: change then symbol; breadth ratio, directional count, directional average return, then sector name.',
        'Yahoo quotes may be delayed; timestamps do not guarantee real-time exchange coverage.',
    ]


def render_text(report):
    lines = summary(report)
    for title, headers, rows in tables(report):
        lines.extend(['', '=' * 100, title, ' | '.join(headers)])
        lines.extend(' | '.join(map(str, row)) for row in rows)
        if not rows:
            lines.append('No eligible entries')
    return '\n'.join(lines)


def render_html(report):
    parts = ['<!doctype html><html lang="en"><meta charset="utf-8"><title>Intraday market snapshot</title>',
             '<style>body{font:14px "Segoe UI",Arial,sans-serif;background:#f7f7f7;color:#222;margin:24px}h1,h2{color:#16213e}table{border-collapse:collapse;background:white;width:100%;margin-bottom:28px}th,td{text-align:left;padding:9px;border-bottom:1px solid #ddd}th{background:#16213e;color:white}tr:nth-child(even){background:#f2f2f2}</style>',
             '<h1>Intraday market snapshot</h1>']
    parts.extend(f'<p>{escape(line)}</p>' for line in summary(report)[1:])
    for title, headers, rows in tables(report):
        parts.append(f'<h2>{escape(title)}</h2><table><thead><tr>')
        parts.extend(f'<th>{escape(h)}</th>' for h in headers)
        parts.append('</tr></thead><tbody>')
        for row in rows:
            parts.append('<tr>' + ''.join(f'<td>{escape(str(v))}</td>' for v in row) + '</tr>')
        if not rows:
            parts.append(f'<tr><td colspan="{len(headers)}">No eligible entries</td></tr>')
        parts.append('</tbody></table>')
    return ''.join(parts) + '</html>'


def save_report(report, output_root):
    # Always use a dedicated child directory; never overwrite existing artifacts.
    directory = Path(output_root) / 'intraday_reports'
    directory.mkdir(parents=True, exist_ok=True)
    stamp = report['generated'].strftime('%Y%m%d_%H%M%S_%f_ET')
    content = render_html(report)
    while True:
        path = directory / f'intraday_snapshot_{stamp}_{uuid4().hex[:12]}.html'
        try:
            with path.open('x', encoding='utf-8') as output:
                output.write(content)
            return path
        except FileExistsError:
            continue


def main(argv=None, *, provider=None, clock=None):
    parser = argparse.ArgumentParser(description=__doc__)
    default = Path('config') if Path('config/universe.yaml').is_file() else Path(__file__).resolve().parents[1] / 'config'
    parser.add_argument('--config-dir', type=Path, default=default)
    parser.add_argument('--output-root', type=Path, default=Path('output'))
    parser.add_argument('--max-age-seconds', type=float, default=300)
    args = parser.parse_args(argv)
    if not math.isfinite(args.max_age_seconds) or args.max_age_seconds <= 0:
        parser.error('--max-age-seconds must be positive and finite')
    try:
        universe = read_universe(args.config_dir / 'universe.yaml')
        quotes, failures = (provider or YahooQuotes()).fetch(universe['symbols'])
        now = (clock or (lambda: datetime.now(timezone.utc)))()
        report = build_report(universe, quotes, failures, now, args.max_age_seconds)
        path = save_report(report, args.output_root)
        print(render_text(report))
        print(f'HTML report: {path.resolve()}')
        return 0 if report['priced'] else 2
    except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError) as exc:
        print(f'Unable to generate intraday snapshot: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
