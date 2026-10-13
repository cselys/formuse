"""Deterministic quote-only regression tests; never contact a market provider."""
from datetime import datetime, timedelta
import hashlib
from pathlib import Path
from unittest.mock import Mock
from urllib.error import HTTPError

import pytest
import yaml

from stock_scanner import intraday_snapshot as snap
from stock_scanner.intraday_quotes import YahooQuotes

NOW = datetime(2026, 10, 8, 11, 0, tzinfo=snap.ET)
ROOT = Path(__file__).resolve().parents[2]


def quote(symbol, change=10, **overrides):
    return dict(symbol=symbol, regularMarketPrice=100 + change,
                regularMarketPreviousClose=100,
                regularMarketTime=(NOW - timedelta(seconds=10)).timestamp(),
                marketState='REGULAR', exchangeTimezoneName='America/New_York',
                currency='USD', quoteType='EQUITY', **overrides)


@pytest.fixture
def universe(tmp_path):
    config = dict(market_benchmarks=['SPY'], etf_symbols=['FUND'],
                  sector_indexes={'configured_index': 'CUSTOM'},
                  categories={'alpha': {'symbols': ['AAA', 'AAA', 'BBB', 'FLAT', 'MISS', 'FUND']},
                              'beta': {'symbols': ['AAA', 'CCC'], 'benchmark': 'BENCH'},
                              'empty': {'symbols': []},
                              'funds': {'symbols': ['OTHER'], 'instrument_type': 'etf'}})
    path = tmp_path / 'universe.yaml'
    path.write_text(yaml.safe_dump(config), encoding='utf-8')
    return snap.read_universe(path)


def test_breadth_dedup_memberships_and_configured_indexes(universe):
    quotes = {s: quote(s, c) for s, c in {'AAA': 10, 'BBB': -5, 'FLAT': 0, 'CCC': -10,
                                        'CUSTOM': 50, 'FUND': 90, 'OTHER': 70}.items()}
    quotes['UNCONFIGURED'] = quote('UNCONFIGURED', 99)
    report = snap.build_report(universe, quotes, {}, NOW)
    assert [r['symbol'] for r in report['sections'][0]] == ['AAA']
    assert report['sections'][0][0]['sectors'] == ['alpha', 'beta']
    assert report['sections'][0][0]['change'] == pytest.approx(10)
    breadth = {r['sector']: r for r in report['breadth']}
    assert breadth['alpha']['total_stock_count'] == 3
    assert breadth['alpha']['sector_up_count'] == 1
    assert breadth['alpha']['sector_down_count'] == 1
    assert breadth['alpha']['sector_flat_count'] == 1
    assert breadth['alpha']['up_ratio'] == pytest.approx(1 / 3)
    assert breadth['beta']['total_stock_count'] == 2
    assert report['sections'][4][0]['symbol'] == 'CUSTOM'
    assert report['sections'][5] == []
    assert 'MISS' in report['unavailable']
    assert 'empty' in [r[0] for r in report['audit']]


@pytest.mark.parametrize('field,value', [
    ('regularMarketPrice', None), ('regularMarketPrice', float('inf')),
    ('regularMarketPrice', True), ('symbol', 'WRONG'),
    ('regularMarketPreviousClose', 0), ('regularMarketPreviousClose', float('nan')),
    ('regularMarketTime', (NOW - timedelta(minutes=6)).timestamp()),
    ('regularMarketTime', (NOW + timedelta(seconds=1)).timestamp()),
    ('regularMarketTime', None), ('marketState', 'POST'),
    ('currency', 'CAD'), ('exchangeTimezoneName', 'Europe/London'),
    ('quoteType', 'CRYPTOCURRENCY'),
])
def test_invalid_quotes_never_rank(universe, field, value):
    row = quote('AAA')
    row[field] = value
    report = snap.build_report(universe, {'AAA': row}, {}, NOW)
    assert not report['priced']
    assert report['unavailable']['AAA']
    assert all(not section for section in report['sections'])


@pytest.mark.parametrize('when,session', [
    ('2026-10-08T08:00:00-04:00', 'PREMARKET'),
    ('2026-10-08T17:00:00-04:00', 'AFTER_HOURS'),
    ('2026-10-10T11:00:00-04:00', 'CLOSED'),
    ('2026-12-25T11:00:00-05:00', 'CLOSED'),
    ('2026-11-27T14:00:00-05:00', 'AFTER_HOURS'),
])
def test_session_calendar_and_no_extended_fallback(universe, when, session):
    report = snap.build_report(universe, {'AAA': quote('AAA')}, {}, datetime.fromisoformat(when))
    assert report['session'] == session
    assert not report['priced']


def test_provider_type_excludes_unlisted_etf(universe):
    row = quote('AAA')
    row['quoteType'] = 'ETF'
    report = snap.build_report(universe, {'AAA': row}, {}, NOW)
    assert len(report['priced']) == 1
    assert not report['sections'][0]
    assert not report['breadth']


def test_ties_and_previous_close_not_provider_percentage(universe):
    quotes = {s: quote(s, 10) for s in ['AAA', 'BBB', 'CCC']}
    quotes['AAA']['regularMarketChangePercent'] = 999
    report = snap.build_report(universe, quotes, {}, NOW)
    assert [r['symbol'] for r in report['sections'][0]] == ['AAA', 'BBB', 'CCC']
    assert report['sections'][0][0]['change'] == pytest.approx(10)


def test_full_real_yaml_universe():
    path = ROOT / 'config/universe.yaml'
    config = yaml.safe_load(path.read_text())
    universe = snap.read_universe(path)
    expected = {s.strip().upper() for c in config['categories'].values()
                for s in c['symbols'] if isinstance(s, str)}
    expected.update(config['market_benchmarks'])
    expected.update(config['sector_indexes'].values())
    expected.update(c['benchmark'] for c in config['categories'].values() if 'benchmark' in c)
    assert set(universe['symbols']) == expected
    assert set(universe['categories']) == set(config['categories'])
    assert set(universe['indexes'].values()) == set(config['sector_indexes'].values())
    assert any('True' in issue for issue in universe['invalid'])


def test_transport_batches_retries_partial_failures():
    sleeps = []
    provider = YahooQuotes(batch_size=2, attempts=2, sleep=sleeps.append)
    provider._batch = Mock(side_effect=[OSError(), [quote('AAA')], OSError(), OSError()])
    quotes, failures = provider.fetch(['CCC', 'BBB', 'AAA', 'AAA'])
    assert set(quotes) == {'AAA'}
    assert set(failures) == {'BBB', 'CCC'}
    assert [call.args[0] for call in provider._batch.call_args_list] == [
        ['AAA', 'BBB'], ['AAA', 'BBB'], ['CCC'], ['CCC']]
    assert len(sleeps) == 3


def test_transport_only_quote_endpoint():
    provider = YahooQuotes()
    provider.crumb = 'memory-only'
    provider._get = Mock(return_value='{"quoteResponse":{"result":[{"symbol":"AAA"}]}}')
    provider.fetch(['AAA'])
    url = provider._get.call_args.args[0]
    assert '/v7/finance/quote?' in url
    assert 'chart' not in url


def test_authentication_accepts_non_json_and_expected_cookie_404():
    provider = YahooQuotes(attempts=1)
    requests = []

    def open_response(request, **kwargs):
        requests.append(request)
        assert request.get_header('Accept') == '*/*'
        if request.full_url == 'https://fc.yahoo.com':
            raise HTTPError(request.full_url, 404, 'Not Found', {}, None)
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = (b'memory-secret' if '/getcrumb' in request.full_url
                                      else b'{"quoteResponse":{"result":[{"symbol":"AAPL"}]}}')
        return response

    provider.opener.open = Mock(side_effect=open_response)
    quotes, failures = provider.fetch(['AAPL'])
    assert set(quotes) == {'AAPL'} and not failures
    assert len(requests) == 3
    assert provider.crumb == 'memory-secret'


@pytest.mark.parametrize('stage,status', [('cookie authentication', 406),
                                         ('crumb authentication', 429),
                                         ('quote retrieval', 401)])
def test_http_diagnostics_identify_stage_without_authentication_secrets(stage, status):
    provider = YahooQuotes(attempts=1)
    def get(url):
        if provider.request_stage == stage:
            raise HTTPError(url+'?crumb=SECRET', status, 'SECRET', {}, None)
        return 'memory-crumb'
    provider._get = get
    quotes, failures = provider.fetch(['AAPL'])
    assert not quotes
    assert stage in failures['AAPL'] and f'HTTP {status}' in failures['AAPL']
    assert 'SECRET' not in failures['AAPL'] and 'http' not in failures['AAPL']


def test_repeated_cli_only_writes_html_and_preserves_state(tmp_path, capsys):
    # Exercise the actual entry point with a full configured universe and partial failure.
    universe = snap.read_universe(ROOT / 'config/universe.yaml')
    provider = Mock()
    provider.fetch.return_value = ({s: quote(s) for s in universe['symbols'] if s != 'AAPL'},
                                   {'AAPL': 'Simulated provider failure'})
    protected = ['cache/daily.parquet', 'cache/weekly.parquet', 'cache/metadata.json',
                 'output/v13_forward/observations.json', 'output/call_stocks.yaml',
                 'config/scanner.yaml']
    for name in protected:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'unchanged sentinel')
    before = {str(p): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    args = ['--config-dir', str(ROOT / 'config'), '--output-root', str(tmp_path / 'output')]
    assert snap.main(args, provider=provider, clock=lambda: NOW) == 0
    assert snap.main(args, provider=provider, clock=lambda: NOW) == 0
    assert provider.fetch.call_args.args[0] == universe['symbols']
    for name, data in before.items():
        assert Path(name).read_bytes() == data
    new = {str(p) for p in tmp_path.rglob('*') if p.is_file()} - before.keys()
    assert len(new) == 2
    assert all(Path(p).suffix == '.html' and Path(p).parent.name == 'intraday_reports' for p in new)
    text = capsys.readouterr().out
    assert 'Simulated provider failure' in text
    for title in snap.TITLES:
        assert title in text


def test_html_escape_and_zero_success_exit(universe, tmp_path, capsys):
    report = snap.build_report(universe, {}, {'AAA': '<script>alert(1)</script>'}, NOW)
    html = snap.render_html(report)
    assert '<script>' not in html
    assert '&lt;script&gt;' in html
    provider = Mock()
    provider.fetch.return_value = ({}, {})
    assert snap.main(['--config-dir', str(ROOT / 'config'), '--output-root', str(tmp_path)],
                     provider=provider, clock=lambda: NOW) == 2
    assert len(list(tmp_path.rglob('*.html'))) == 1


def test_existing_source_and_state_unchanged_by_generation(universe, tmp_path):
    paths = [ROOT / 'v13_forward_validation.py']
    paths += list((ROOT / 'stock_scanner/src').rglob('*.py'))
    paths += list((ROOT / 'config').glob('*.yaml'))
    paths += [p for p in (ROOT / 'output/v13_forward').rglob('*') if p.is_file()]
    def digest():
        return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    before = digest()
    report = snap.build_report(universe, {'AAA': quote('AAA')}, {}, NOW)
    snap.save_report(report, tmp_path)
    assert digest() == before
