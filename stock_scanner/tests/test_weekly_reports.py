"""Calendar boundaries, point-in-time diagnostics and weekly report integration."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from stock_scanner.src.data.market_calendar import (
    completed_daily, completed_weekly, schedule, week_context, uses_completed_weeks,
)
from stock_scanner.src.data.yfinance_loader import YFinanceLoader
from stock_scanner.src.analysis.weekly_diagnostics import weekly_diagnostics, direction
from stock_scanner.src.analysis.snapshot import analyze_snapshot
from stock_scanner.src.reporting.weekly_report import build_weekly_records, WeeklyReport, save_weekly_report

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def config():
    return yaml.safe_load((ROOT / 'config/scanner.yaml').read_text())


def bars(start='2023-01-03', end='2025-12-05'):
    dates = schedule(start, end).index
    close = 100 + np.arange(len(dates)) * .1 + np.sin(np.arange(len(dates)) / 4)
    return pd.DataFrame({'Open': close - .1, 'High': close + 1, 'Low': close - 1,
                         'Close': close, 'Volume': 1_000_000.0}, index=dates)


@pytest.mark.parametrize('cutoff,week_end,auto', [
    ('2025-04-17 15:59:00-04:00', '2025-04-11', False),
    ('2025-04-17 16:01:00-04:00', '2025-04-18', True),  # Good Friday
    ('2025-04-19 12:00:00-04:00', '2025-04-18', True),
    ('2025-04-23 12:00:00-04:00', '2025-04-18', False),
    ('2025-11-28 12:59:00-05:00', '2025-11-21', False),
    ('2025-11-28 13:01:00-05:00', '2025-11-28', True),  # Early close
    ('2025-09-19 15:59:00-04:00', '2025-09-12', False),
    ('2025-09-19 16:01:00-04:00', '2025-09-19', True),
])
def test_week_completion(cutoff, week_end, auto):
    context = week_context(cutoff)
    assert context['week_end'] == week_end
    assert bool(context['auto_weekly']) is auto
    result = completed_weekly(bars('2025-03-01'), cutoff)
    assert str(result.index[-1].date()) == week_end


def test_holiday_ohlcv_and_missing_session():
    data = bars('2025-04-07', '2025-04-17')
    weekly = completed_weekly(data, '2025-04-17')
    last = data.loc['2025-04-14':]
    assert weekly.index[-1] == pd.Timestamp('2025-04-18')
    assert weekly.iloc[-1].Open == last.Open.iloc[0]
    assert weekly.iloc[-1].Close == last.Close.iloc[-1]
    assert weekly.iloc[-1].High == last.High.max()
    assert weekly.iloc[-1].Low == last.Low.min()
    assert weekly.iloc[-1].Volume == last.Volume.sum()
    missing = completed_weekly(data.drop(pd.Timestamp('2025-04-15')), '2025-04-17')
    assert missing.index[-1] == pd.Timestamp('2025-04-11')


def test_timestamp_and_date_cutoffs_and_timezone_labels():
    data = bars('2025-09-01', '2025-09-19')
    before_close = completed_daily(data, '2025-09-19 19:59:00+00:00')
    assert before_close.index[-1] == pd.Timestamp('2025-09-18')
    assert completed_daily(data, '2025-09-19').index[-1] == pd.Timestamp('2025-09-19')
    localized = data.copy()
    localized.index = localized.index.tz_localize('America/New_York')
    pd.testing.assert_frame_equal(completed_weekly(data, '2025-09-19'),
                                  completed_weekly(localized, '2025-09-19'))


def test_future_data_invariance(config):
    original = bars()
    changed = original.copy()
    changed.loc[changed.index > '2025-04-17', ['Open', 'High', 'Low', 'Close']] *= 20
    context = week_context('2025-04-23')
    kwargs = ({'TEST': 'tech'}, {'tech': 'SPY'}, {'SPY'}, config, context)
    a = build_weekly_records({'TEST': original, 'SPY': original}, *kwargs)
    b = build_weekly_records({'TEST': changed, 'SPY': changed}, *kwargs)
    assert a == b
    assert a[0]['score_as_of'] == '2025-04-17'
    assert a[0]['weekly_diagnostics']['status'] == 'OK'


def test_diagnostics_returns_and_relative_strength(config):
    data = bars()
    context = week_context('2025-04-17')
    weekly = completed_weekly(data, '2025-04-17')
    daily = {'close': 120, 'ema20': 110, 'ema50': 100, 'ema20_slope': 1}
    diagnostic = weekly_diagnostics(weekly, daily, config, context, weekly, weekly)
    expected = (weekly.Close.iloc[-1] / weekly.Close.iloc[-2] - 1) * 100
    assert diagnostic['weekly_change_pct'] == pytest.approx(expected)
    assert diagnostic['weekly_direction'] == 'UP'
    assert diagnostic['alignment'] == 'ALIGNED_UP'
    assert diagnostic['relative_strength_market'] == {'rs_4w': 0.0, 'rs_12w': 0.0}
    assert diagnostic['rsi_change'] is not None
    bearish_daily = {'close': 80, 'ema20': 90, 'ema50': 100, 'ema20_slope': -1}
    assert weekly_diagnostics(weekly, bearish_daily, config, context)['alignment'] == 'PULLBACK_IN_WEEKLY_UPTREND'


def test_insufficient_and_stale_data_are_not_neutral(config):
    context = week_context('2025-04-17')
    weekly = completed_weekly(bars('2025-03-01'), '2025-04-17')
    result = weekly_diagnostics(weekly, {}, config, context)
    assert result['status'] == 'INSUFFICIENT_HISTORY'
    assert result['weekly_direction'] == 'INSUFFICIENT_DATA'
    result = weekly_diagnostics(weekly.iloc[:-1], {}, config, context)
    assert result['status'] == 'STALE_OR_MISSING'
    assert result['weekly_change_pct'] is None
    assert direction({'close': float('nan')}) == 'INSUFFICIENT_DATA'


def test_missing_previous_week_does_not_become_multiweek_return(config):
    context = week_context('2025-04-17')
    weekly = completed_weekly(bars(), '2025-04-17').drop(pd.Timestamp('2025-04-11'))
    result = weekly_diagnostics(weekly, {}, config, context)
    assert result['weekly_change_pct'] is None
    assert result['status'] == 'INSUFFICIENT_HISTORY'


def test_weekly_exports_coverage_etfs_and_escaping(config, tmp_path):
    data = bars()
    context = week_context('2025-04-17')
    records = build_weekly_records({'TEST': data, 'SPY': data, 'XLK': data},
        {'TEST': '<tech>', 'MISSING': '<tech>', 'XLK': '<tech>'}, {'<tech>': 'SPY'},
        {'SPY', 'XLK'}, config, context)
    report = WeeklyReport(records, context, {'technology': 'XLK'}, scope='filtered subset')
    assert report.coverage['requested_stocks'] == 2
    assert report.coverage['valid_weekly_returns'] == 1
    assert all(r['symbol'] != 'XLK' for r in report.sections['TOP 10 STOCKS UP'])
    assert report.sections['ALL SECTOR BREADTH'][0]['total_stock_count'] == 1
    files = save_weekly_report(report, tmp_path)
    assert len(files) == 9
    doc = Path(files['html']).read_text(encoding='utf-8')
    assert '&lt;tech&gt;' in doc and '<tech>' not in doc
    parsed = json.loads(Path(files['json']).read_text())
    assert parsed['metadata']['last_session'] == '2025-04-17'
    assert parsed['metadata']['scope'] == 'filtered subset'
    assert parsed['records'][1]['weekly_diagnostics']['status'] == 'STALE_OR_MISSING'
    assert 'WEEKLY TECHNICAL DIAGNOSTICS' in Path(files['txt']).read_text()
    assert all('2025-04-18' in p for p in files.values())


def test_legacy_weekly_resampling_is_unchanged():
    data = bars('2025-04-07', '2025-04-17')
    loader = YFinanceLoader()
    assert loader.resample_to_weekly(data, '2025-04-17', True).index[-1] == pd.Timestamp('2025-04-11')
    assert loader.resample_to_weekly(data, '2025-04-17', True, calendar_aware=True).index[-1] == pd.Timestamp('2025-04-18')
    assert not uses_completed_weeks({'scanner_version': '1.1'})
    assert not uses_completed_weeks({'scanner_version': '1.2'})


@pytest.mark.parametrize('version', ['1.1', '1.2', '1.3'])
def test_scanner_integration_and_weekend_snapshot(config, monkeypatch, version):
    import stock_scanner.src.scanner as module
    config['scanner_version'] = version
    scanner = module.StockScanner.__new__(module.StockScanner)
    scanner.config, scanner.version = config, version
    scanner.universe = {'categories': {'tech': {'symbols': ['TEST'], 'benchmark': 'SPY'}},
                        'market_benchmarks': ['SPY'], 'sector_indexes': {'tech': 'XLK'}}
    scanner.loader = YFinanceLoader()
    data = bars()
    monkeypatch.setattr(module, 'update_universe_cache', lambda *a, **k: None)
    monkeypatch.setattr(module, 'load_cached_data', lambda *a: data.copy())
    monkeypatch.setattr(module, 'save_watchlist_yaml', lambda *a, **k: {})
    result, context = scanner.scan(as_of='2025-04-23', report_period='both')
    assert context['generate_weekly']
    assert context['weekly_records'][0]['data_date'] == '2025-04-17'
    if version == '1.3':
        assert result[0]['data_date'] == '2025-04-23'
        assert result[0]['weekly']['close'] == data.loc['2025-04-17', 'Close']
    else:
        legacy_weekly = scanner.loader.resample_to_weekly(data)
        expected = analyze_snapshot(data, legacy_weekly, data, data, config)
        for key in ('candidate_score', 'trend_score', 'state', 'entry_quality'):
            assert result[0][key] == expected[key]


@pytest.mark.parametrize('as_of,expected', [('2025-04-23', False), ('2025-04-17', True)])
def test_auto_weekly_selection(config, monkeypatch, as_of, expected):
    import stock_scanner.src.scanner as module
    scanner = module.StockScanner.__new__(module.StockScanner)
    scanner.config, scanner.version = config, '1.3'
    scanner.universe = {'categories': {'tech': {'symbols': ['TEST', 'ETF'], 'benchmark': 'SPY'}}, 'etf_symbols': ['ETF']}
    scanner.loader = YFinanceLoader()
    data = bars()
    monkeypatch.setattr(module, 'update_universe_cache', lambda *a, **k: None)
    monkeypatch.setattr(module, 'load_cached_data', lambda *a: data)
    monkeypatch.setattr(module, 'save_watchlist_yaml', lambda *a, **k: {})
    results, context = scanner.scan(as_of=as_of)
    assert context['generate_weekly'] == expected
    assert ('weekly_records' in context) == expected
    assert next(r for r in results if r['symbol'] == 'ETF')['is_index_etf']


def test_weekly_historical_schedule_uses_holiday_final_session(config, tmp_path):
    from stock_scanner.src.historical.historical_signal import HistoricalSignalGenerator
    from types import SimpleNamespace
    data = bars('2025-04-01', '2025-04-30')
    data.index += pd.Timedelta(hours=4)  # Loader's UTC-converted daily labels
    scanner = SimpleNamespace(config=config, loader=SimpleNamespace(download_ticker=lambda symbol: data))
    generator = HistoricalSignalGenerator(scanner, str(tmp_path))
    dates = generator.generate_schedule('2025-04-01', '2025-04-30', 'weekly')
    assert '2025-04-17' in dates
    assert '2025-04-18' not in dates
    assert '2025-04-30' not in dates  # Not yet the final session of its week


@pytest.mark.parametrize('period', ['daily', 'weekly', 'both', 'auto'])
def test_cli_report_selection(period, config, monkeypatch, tmp_path):
    import sys
    from stock_scanner import run_scanner
    data = bars('2024-01-02', '2025-04-17')
    context = week_context('2025-04-17')
    records = build_weekly_records({'TEST': data, 'SPY': data}, {'TEST': 'tech'},
                                    {'tech': 'SPY'}, {'SPY'}, config, context)
    class Scanner:
        def scan(self, **kwargs):
            assert kwargs['report_period'] == period
            return records, {'generate_weekly': period != 'daily', 'weekly_records': records,
                             'weekly_context': context, 'scope': 'filtered subset',
                             'sector_indexes_cfg': {}}
    monkeypatch.setattr(run_scanner, 'StockScanner', Scanner)
    monkeypatch.setattr(run_scanner, 'load_dotenv', lambda: None)
    monkeypatch.setattr(run_scanner, 'display_console_report', lambda *a, **k: None)
    monkeypatch.setattr(sys, 'argv', ['run_scanner.py', '--report-period', period])
    monkeypatch.chdir(tmp_path)
    run_scanner.main()
    report_dir = tmp_path / 'output/reports'
    assert (report_dir / 'weekly_report_2025-04-18.html').exists() == (period != 'daily')
    assert (report_dir / 'daily_report_2025-04-17.html').exists() == (period != 'weekly')
    assert (tmp_path / 'data/reports/2025-04-17.json').exists()
