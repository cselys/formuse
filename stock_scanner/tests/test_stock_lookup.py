import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

import stock_scanner.src.historical.stock_lookup as lookup
from stock_scanner.src.data.market_calendar import schedule, completed_daily, completed_weekly
from stock_scanner.src.data.scanner_history import (
    ScannerHistoryStore, calculation_signature, history_context, weekly_policy, result_fingerprint,
)
from stock_scanner.src.reporting.stock_history import save_stock_history, render_stock_history

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def config():
    return yaml.safe_load((ROOT / 'config/scanner.yaml').read_text())


@pytest.fixture(scope='module')
def prices():
    dates = schedule('2024-01-02', '2025-04-25').index
    close = 100 + np.arange(len(dates)) * .1 + np.sin(np.arange(len(dates)) / 6)
    return pd.DataFrame({'Open': close, 'High': close + 1, 'Low': close - 1,
                         'Close': close + .2, 'Volume': 1_000_000.0}, index=dates)


@pytest.fixture
def run_lookup(config, prices, tmp_path):
    universe = {'categories': {'tech': {'symbols': ['NVDA'], 'benchmark': 'QQQ'}}}
    def run(symbol='nvda', period='5d', data=None, as_of='2025-04-21', **kwargs):
        frames = {'NVDA': prices, 'SPY': prices, 'QQQ': prices} if data is None else data
        return lookup.lookup_stock(symbol, period, config, universe, as_of=as_of,
                                   load_prices=lambda name: frames.get(name),
                                   store=ScannerHistoryStore(tmp_path / 'history.sqlite3'),
                                   report_dirs=[tmp_path / 'recorded'], **kwargs)
    return run


@pytest.mark.parametrize('value,expected', [(' nvda ', 'NVDA'), ('brk-b', 'BRK-B'), ('brk.b', 'BRK.B')])
def test_symbol_normalization(value, expected):
    assert lookup.normalize_symbol(value) == expected


@pytest.mark.parametrize('value', ['', '../NVDA', 'A/B', '<script>', 'NVDA foo', 'NUL', 'CON', 'A:'])
def test_invalid_symbols(value):
    with pytest.raises(ValueError):
        lookup.normalize_symbol(value)


@pytest.mark.parametrize('period', ['0d', '-5d', '10', '1w', '10.5d', '5001d'])
def test_invalid_periods(period):
    with pytest.raises(ValueError):
        lookup.parse_period(period)


@pytest.mark.parametrize('period,dates', [
    ('5d', ['2025-04-21', '2025-04-17', '2025-04-16', '2025-04-15', '2025-04-14']),
    ('10d', ['2025-04-21', '2025-04-17', '2025-04-16', '2025-04-15', '2025-04-14',
             '2025-04-11', '2025-04-10', '2025-04-09', '2025-04-08', '2025-04-07']),
])
def test_trading_sessions_and_order(run_lookup, period, dates):
    report = run_lookup(period=period)
    assert [row['date'] for row in report.rows] == dates
    assert all(row['state'] is not None for row in report.rows)
    assert report.symbol == 'NVDA'


@pytest.mark.parametrize('as_of,expected', [('2025-04-18', '2025-04-17'), ('2025-04-19', '2025-04-17'),
    ('2025-04-20', '2025-04-17'), ('2025-04-25 15:59:00-04:00', '2025-04-24'),
    ('2025-04-25 16:01:00-04:00', '2025-04-25')])
def test_latest_completed_session(run_lookup, as_of, expected):
    assert run_lookup(as_of=as_of).through == expected


def test_no_symbol_cache(run_lookup):
    report = run_lookup(symbol='MISSING')
    assert not report.rows
    assert any('No local completed daily price cache' in message for message in report.messages)
    assert any('outside' in message for message in report.messages)


def test_outside_universe_with_cache(run_lookup, prices):
    report = run_lookup(symbol='OTHER', data={'OTHER': prices, 'SPY': prices, 'QQQ': prices})
    assert len(report.rows) == 5
    assert all(row['state'] is not None for row in report.rows)
    assert any('SPY benchmark' in message for message in report.messages)


def test_insufficient_history(run_lookup, prices):
    short = prices.loc['2025-04-15':'2025-04-21']
    report = run_lookup(data={'NVDA': short, 'SPY': prices, 'QQQ': prices}, period='10d')
    assert len(report.rows) == 4
    assert all(row['state'] is None and row['candidate_score'] is None for row in report.rows)
    assert any('Only 4' in message for message in report.messages)


def test_missing_benchmark_is_not_neutral_score(run_lookup, prices):
    report = run_lookup(data={'NVDA': prices, 'SPY': prices})
    assert all(row['state'] is None and row['market_regime'] is None for row in report.rows)
    assert all('benchmark' in row['missing_reason'] for row in report.rows)


def test_missing_price_session_stays_visible(run_lookup, prices):
    broken = prices.drop(pd.Timestamp('2025-04-16'))
    report = run_lookup(data={'NVDA': broken, 'SPY': prices, 'QQQ': prices})
    missing = next(row for row in report.rows if row['date'] == '2025-04-16')
    assert len(report.rows) == 5
    assert missing['close'] is None and missing['state'] is None
    after = next(row for row in report.rows if row['date'] == '2025-04-17')
    assert after['daily_change_pct'] is None


def test_missing_calculation(run_lookup, monkeypatch):
    def fail(*args, **kwargs):
        raise ValueError('Missing information')
    monkeypatch.setattr(lookup, 'analyze_snapshot', fail)
    report = run_lookup()
    assert all(row['source'] == 'MISSING' and row['state'] is None for row in report.rows)


def test_repeated_lookup_uses_persistence_and_is_deterministic(run_lookup, monkeypatch):
    original = lookup.analyze_snapshot
    calls = []
    def calculate(*args):
        calls.append(1)
        return original(*args)
    monkeypatch.setattr(lookup, 'analyze_snapshot', calculate)
    first = run_lookup()
    second = run_lookup()
    assert len(calls) == 5
    assert first == second
    assert render_stock_history(first) == render_stock_history(second)


def test_future_stock_and_benchmark_prices_do_not_change_history(run_lookup, prices):
    original = run_lookup(as_of='2025-04-17')
    changed = prices.copy()
    changed.loc[changed.index > '2025-04-17', ['Open', 'High', 'Low', 'Close']] *= 20
    replay = run_lookup(data={'NVDA': changed, 'SPY': changed, 'QQQ': changed}, as_of='2025-04-17')
    assert original.rows == replay.rows


def test_changed_past_prices_invalidate_cached_results(run_lookup, prices, monkeypatch):
    run_lookup()
    changed = prices.copy()
    changed.loc[changed.index == '2025-04-14', ['Open', 'High', 'Low', 'Close']] *= 1.05
    original = lookup.analyze_snapshot
    calls = []
    def calculate(*args):
        calls.append(1)
        return original(*args)
    monkeypatch.setattr(lookup, 'analyze_snapshot', calculate)
    run_lookup(data={'NVDA': changed, 'SPY': prices, 'QQQ': prices})
    assert len(calls) == 5


def test_state_transitions_and_missing_breaks(run_lookup, monkeypatch):
    original = lookup.analyze_snapshot
    def calculate(daily, *args):
        record = original(daily, *args)
        day = str(daily.index[-1].date())
        if day == '2025-04-16':
            raise ValueError('Missing result')
        record['state'] = 'UPTREND' if day in ('2025-04-14', '2025-04-21') else 'REVERSAL'
        return record
    monkeypatch.setattr(lookup, 'analyze_snapshot', calculate)
    report = run_lookup()
    by_date = {row['date']: row for row in report.rows}
    assert by_date['2025-04-15']['transition'] == 'UPTREND → REVERSAL'
    assert by_date['2025-04-17']['transition'] is None
    assert by_date['2025-04-21']['transition'] == 'REVERSAL → UPTREND'
    assert render_stock_history(report).count('class="changed"') == 2


def test_html_filename_and_fields(run_lookup, tmp_path):
    report = run_lookup(period='10d')
    path = Path(save_stock_history(report, tmp_path))
    assert path.name == 'stock_history_NVDA_10d_2025-04-21.html'
    page = path.read_text(encoding='utf-8')
    for text in ('NVDA', '10 trading days', 'Candidate Score', 'Bottom Score', 'Reversal Score', 'RS 60d %', 'Market Regime', 'RECONSTRUCTED'):
        assert text in page
    assert '<script' not in page
    assert not save_stock_history(lookup.StockHistory('NONE', 5, [], [], '1.3'), tmp_path)


def test_matching_recorded_json_reused_and_legacy_unverified_ignored(run_lookup, config, prices, tmp_path):
    directory = tmp_path / 'recorded'
    directory.mkdir()
    daily = completed_daily(prices, '2025-04-21')
    weekly = completed_weekly(daily, '2025-04-21')
    record = lookup.analyze_snapshot(daily, weekly, daily, daily, config)
    record.update(symbol='NVDA', data_date='2025-04-21', scanner_version='1.3')
    record['history_context'] = history_context(calculation_signature(config), 'NVDA', 'tech', 'QQQ', 'SPY', daily, weekly, daily, daily,
                                               calculation_policy=weekly_policy(config))
    record['history_result_fingerprint'] = result_fingerprint(record)
    path = directory / '2025-04-21.json'
    path.write_text(json.dumps({'results': [record]}))
    report = run_lookup()
    assert report.rows[0]['source'] == 'RECORDED_VERIFIED'
    assert report.rows[0]['candidate_score'] == record['candidate_score']
    del record['history_context']
    path.write_text(json.dumps({'results': [record]}))
    # An already verified immutable revision remains canonical, but the replaced
    # archive itself is now explicitly unverified and cannot supply new scores.
    replay = run_lookup()
    assert replay.rows[0]['source'] == 'RECORDED_VERIFIED'
    assert replay.rows[0]['legacy_artifacts'][0]['status'] == 'UNVERIFIED'


def test_html_reports_are_not_required(run_lookup, tmp_path):
    report = run_lookup()
    assert len(report.rows) == 5
    assert not list(tmp_path.rglob('*.html'))


def test_timestamped_legacy_artifact_preserved_without_bypassing_missing_benchmark(run_lookup, prices, tmp_path):
    directory = tmp_path / 'recorded'
    directory.mkdir()
    record = {'symbol': 'NVDA', 'data_date': '2025-04-21', 'as_of': '2025-04-22T00:20:00-04:00',
              'scanner_version': '1.3', 'state': 'REVERSAL', 'candidate_score': 81.7,
              'daily': {'close': float(prices.loc['2025-04-21', 'Close']), 'rsi': 57.3}}
    path = directory / '2025-04-21.json'
    path.write_text(json.dumps({'results': [record]}))
    report = run_lookup(data={'NVDA': prices})
    assert report.rows[0]['state'] is None
    assert report.rows[0]['candidate_score'] is None
    assert report.rows[0]['source'] == 'MISSING'
    artifact = report.rows[0]['legacy_artifacts'][0]
    assert artifact['source'] == 'RECORDED_LEGACY' and artifact['status'] == 'UNVERIFIED'
    assert artifact['result']['candidate_score'] == 81.7
    assert report.rows[0]['trend_score'] is None
    record['as_of'] = '2025-04-21T12:00:00-04:00'
    path.write_text(json.dumps({'results': [record]}))
    assert run_lookup(data={'NVDA': prices}).rows[0]['state'] is None


def test_lookup_never_calls_download(run_lookup, monkeypatch):
    from stock_scanner.src.data.yfinance_loader import YFinanceLoader
    monkeypatch.setattr(YFinanceLoader, 'download_ticker', lambda *a, **k: pytest.fail('Lookup attempted a download'))
    assert len(run_lookup().rows) == 5


def test_cli_lookup_uses_existing_entrypoint(monkeypatch, run_lookup, tmp_path):
    from stock_scanner import run_scanner
    report = run_lookup()
    monkeypatch.setattr(lookup, 'lookup_stock', lambda *a, **k: report)
    assert run_scanner.main(['lookup', 'nvda', '--period', '5d', '--config-dir', str(ROOT / 'config'), '--output-dir', str(tmp_path)]) == 0
    assert (tmp_path / 'stock_history_NVDA_5d_2025-04-21.html').exists()


def test_cli_invalid_period_exits_cleanly():
    from stock_scanner import run_scanner
    with pytest.raises(SystemExit) as error:
        run_scanner.main(['lookup', 'NVDA', '--period', 'nope'])
    assert error.value.code == 2
