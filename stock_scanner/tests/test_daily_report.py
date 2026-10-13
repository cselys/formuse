"""
Unit tests for the enhanced daily report (stock rankings, sector breadth,
sector index performance, and file output).
"""

import os
import tempfile

import pytest

from stock_scanner.src.reporting.stock_rankings import (
    rank_stocks_up,
    rank_stocks_down,
    extract_stock_rows,
)
from stock_scanner.src.reporting.sector_rankings import (
    compute_sector_breadth,
    top_sectors_up,
    top_sectors_down,
)
from stock_scanner.src.reporting.sector_indexes import (
    top_sector_indexes_up,
    top_sector_indexes_down,
    build_sector_index_rows,
)
from stock_scanner.src.reporting.daily_report import DailyReport
from stock_scanner.src.reporting.file_writer import save_daily_report


def make_record(symbol, category, change_pct, state='UPTREND', score=70.0,
                is_index_etf=False, close=100.0, rs_20d=1.0, rs_trend='positive'):
    return {
        'symbol': symbol,
        'category': category,
        'is_index_etf': is_index_etf,
        'daily_change_pct': change_pct,
        'state': state,
        'candidate_score': score,
        'entry_quality': 60.0,
        'market_regime': 'MARKET_UPTREND',
        'daily': {'close': close},
        'relative_strength': {'rs_20d': rs_20d, 'rs_trend': rs_trend},
    }


# --------------------------------------------------------------------------- #
# Stock rankings
# --------------------------------------------------------------------------- #

def test_rank_stocks_up_sorting():
    recs = [
        make_record('A', 't', 5.0),
        make_record('B', 't', 10.0),
        make_record('C', 't', 1.0),
        make_record('D', 't', -2.0),
    ]
    up = rank_stocks_up(recs, top_n=10)
    assert [r['symbol'] for r in up] == ['B', 'A', 'C']
    assert up[0]['change_pct'] == 10.0
    assert all(r['change_pct'] > 0 for r in up)


def test_rank_stocks_down_sorting():
    recs = [
        make_record('A', 't', 5.0),
        make_record('B', 't', -10.0),
        make_record('C', 't', -1.0),
        make_record('D', 't', 2.0),
    ]
    down = rank_stocks_down(recs, top_n=10)
    assert [r['symbol'] for r in down] == ['B', 'C']
    assert down[0]['change_pct'] == -10.0
    assert all(r['change_pct'] < 0 for r in down)


def test_rank_stocks_fewer_than_ten():
    recs = [make_record(f'S{i}', 't', float(i + 1)) for i in range(5)]
    up = rank_stocks_up(recs, top_n=10)
    assert len(up) == 5
    assert len(rank_stocks_down(recs, top_n=10)) == 0


def test_rank_stocks_excludes_index_etfs():
    recs = [
        make_record('NVDA', 'tech', 5.0),
        make_record('XLK', 'tech', 3.0, is_index_etf=True),
        make_record('AAPL', 'tech', 2.0),
    ]
    up = rank_stocks_up(recs, top_n=10)
    symbols = [r['symbol'] for r in up]
    assert 'XLK' not in symbols
    assert 'NVDA' in symbols


def test_rank_stocks_missing_data_skipped(caplog):
    recs = [
        make_record('OK', 't', 4.0),
        {'symbol': 'BAD', 'category': 't', 'is_index_etf': False, 'daily_change_pct': None,
         'state': 'UPTREND', 'candidate_score': 50.0, 'daily': {'close': 100.0}},
        {'symbol': 'NAN', 'category': 't', 'is_index_etf': False, 'daily_change_pct': float('nan'),
         'state': 'UPTREND', 'candidate_score': 50.0, 'daily': {'close': 100.0}},
    ]
    rows = extract_stock_rows(recs)
    symbols = [r['symbol'] for r in rows]
    assert 'OK' in symbols
    assert 'BAD' not in symbols
    assert 'NAN' not in symbols


# --------------------------------------------------------------------------- #
# Sector breadth
# --------------------------------------------------------------------------- #

def test_sector_breadth_ratios():
    # Sector A: 4 up, 1 down
    recs = [make_record(f'A{i}', 'sector_a', 1.0) for i in range(4)]
    recs += [make_record('ADOWN', 'sector_a', -1.0)]
    # Sector B: 3 up, 7 down
    recs += [make_record(f'B{i}', 'sector_b', 1.0) for i in range(3)]
    recs += [make_record(f'B{i}', 'sector_b', -1.0) for i in range(7)]

    breadth = compute_sector_breadth(recs)
    by_name = {b['sector']: b for b in breadth}

    a = by_name['sector_a']
    assert a['total_stock_count'] == 5
    assert a['sector_up_count'] == 4
    assert a['sector_down_count'] == 1
    assert pytest.approx(a['up_ratio']) == 0.8

    b = by_name['sector_b']
    assert b['total_stock_count'] == 10
    assert b['sector_down_count'] == 7
    assert pytest.approx(b['down_ratio']) == 0.7


def test_sector_breadth_excludes_index_etfs():
    # A sector that would look bullish if XLK counted, bearish if not.
    recs = [
        make_record('NVDA', 'tech', -3.0),
        make_record('MSFT', 'tech', -1.0),
        make_record('XLK', 'tech', 5.0, is_index_etf=True),
    ]
    breadth = compute_sector_breadth(recs)
    tech = breadth[0]
    assert tech['total_stock_count'] == 2
    assert tech['sector_up_count'] == 0
    assert tech['sector_down_count'] == 2


def test_top_sectors_up_ranking_by_breadth():
    recs = [
        make_record(f'A{i}', 'sector_a', 1.0) for i in range(4)
    ] + [make_record('ADOWN', 'sector_a', -1.0)]
    recs += [make_record(f'B{i}', 'sector_b', 1.0) for i in range(3)]
    recs += [make_record(f'B{i}', 'sector_b', -1.0) for i in range(7)]
    # sector_c: 1 up, 0 down -> 100%
    recs += [make_record('C', 'sector_c', 1.0)]

    top = top_sectors_up(recs, top_n=3)
    assert [t['sector'] for t in top] == ['sector_c', 'sector_a', 'sector_b']


def test_top_sectors_down_ranking_by_breadth():
    # sector_a: 7 down / 10 = 70% ; sector_b: 2 down / 4 = 50% ; sector_c: 1/1 = 100%
    recs = [
        make_record(f'A{i}', 'sector_a', -1.0) for i in range(7)
    ] + [make_record(f'AUP{i}', 'sector_a', 1.0) for i in range(3)]
    recs += [make_record(f'B{i}', 'sector_b', -1.0) for i in range(2)]
    recs += [make_record(f'B{i}', 'sector_b', 1.0) for i in range(2)]
    recs += [make_record('C', 'sector_c', -1.0)]

    top = top_sectors_down(recs, top_n=3)
    # sector_c has the highest down ratio (100%).
    assert top[0]['sector'] == 'sector_c'
    assert top[1]['sector'] == 'sector_a'
    assert pytest.approx(top[1]['down_ratio']) == 0.7


def test_sector_breadth_tie_breaking():
    # Two sectors both 50% up; sector_a has higher up_count and higher avg.
    recs = [
        make_record(f'A{i}', 'sector_a', 2.0) for i in range(3)
    ] + [make_record(f'A{i}', 'sector_a', -1.0) for i in range(3)]
    recs += [
        make_record(f'B{i}', 'sector_b', 1.0) for i in range(2)
    ] + [make_record(f'B{i}', 'sector_b', -1.0) for i in range(2)]

    top = top_sectors_up(recs, top_n=2)
    assert top[0]['sector'] == 'sector_a'


# --------------------------------------------------------------------------- #
# Sector index ranking
# --------------------------------------------------------------------------- #

def _make_context(data):
    return {'sector_index_data': data}


def test_sector_index_up_down():
    ctx = _make_context({
        'technology': {'symbol': 'XLK', 'sector': 'technology', 'change_pct': 2.0, 'close': 100.0},
        'energy': {'symbol': 'XLE', 'sector': 'energy', 'change_pct': 3.0, 'close': 90.0},
        'financials': {'symbol': 'XLF', 'sector': 'financials', 'change_pct': -1.0, 'close': 45.0},
    })
    up = top_sector_indexes_up(ctx, top_n=3)
    assert [r['symbol'] for r in up] == ['XLE', 'XLK', 'XLF']
    down = top_sector_indexes_down(ctx, top_n=3)
    assert [r['symbol'] for r in down] == ['XLF', 'XLK', 'XLE']


def test_sector_index_top3_limit():
    ctx = _make_context({
        'a': {'symbol': 'AA', 'sector': 'a', 'change_pct': 1.0, 'close': 1.0},
        'b': {'symbol': 'BB', 'sector': 'b', 'change_pct': 2.0, 'close': 1.0},
        'c': {'symbol': 'CC', 'sector': 'c', 'change_pct': 3.0, 'close': 1.0},
        'd': {'symbol': 'DD', 'sector': 'd', 'change_pct': 4.0, 'close': 1.0},
    })
    assert len(top_sector_indexes_up(ctx, top_n=3)) == 3


def test_sector_index_missing_data_skipped():
    ctx = _make_context({
        'ok': {'symbol': 'OKK', 'sector': 'ok', 'change_pct': 1.0, 'close': 1.0},
        'bad': {'symbol': 'BAD', 'sector': 'bad', 'change_pct': None, 'close': None},
    })
    rows = build_sector_index_rows(ctx)
    assert [r['symbol'] for r in rows] == ['OKK']


# --------------------------------------------------------------------------- #
# File output
# --------------------------------------------------------------------------- #

def _full_report():
    recs = [
        make_record('NVDA', 'tech', 5.82, 'STRONG_UPTREND', 91.4),
        make_record('AMD', 'tech', 4.97, 'UPTREND', 87.2),
        make_record('XOM', 'energy', -1.2, 'DOWNTREND', 40.0),
    ]
    ctx = {
        'sector_index_data': {
            'technology': {'symbol': 'XLK', 'sector': 'technology', 'change_pct': 2.17, 'close': 200.0},
            'energy': {'symbol': 'XLE', 'sector': 'energy', 'change_pct': 3.42, 'close': 90.0},
        }
    }
    return DailyReport(recs, ctx, scan_date='2026-09-09')


def test_file_output_creates_files():
    report = _full_report()
    with tempfile.TemporaryDirectory() as tmp:
        paths = save_daily_report(report, output_dir=tmp, scan_date='2026-09-09')
        assert os.path.exists(paths['txt'])
        assert os.path.exists(paths['csv'])
        assert os.path.exists(paths['html'])
        for label, path in paths['separate_csv'].items():
            assert os.path.exists(path)


def test_file_output_filename_date():
    report = _full_report()
    with tempfile.TemporaryDirectory() as tmp:
        paths = save_daily_report(report, output_dir=tmp, scan_date='2026-09-09')
        assert os.path.basename(paths['txt']) == 'daily_report_2026-09-09.txt'
        assert os.path.basename(paths['csv']) == 'daily_report_2026-09-09.csv'
        assert os.path.basename(paths['html']) == 'daily_report_2026-09-09.html'
        assert os.path.basename(paths['separate_csv']['stocks_up']) == 'stocks_up_2026-09-09.csv'
        assert os.path.basename(paths['separate_csv']['sector_indexes']) == 'sector_indexes_2026-09-09.csv'


def test_file_output_expected_sections():
    report = _full_report()
    with tempfile.TemporaryDirectory() as tmp:
        paths = save_daily_report(report, output_dir=tmp, scan_date='2026-09-09')
        with open(paths['txt'], encoding='utf-8') as f:
            txt = f.read()
        assert 'TOP 10 STOCKS UP' in txt
        assert 'TOP 10 STOCKS DOWN' in txt
        assert 'TOP 3 SECTORS UP' in txt
        assert 'TOP 3 SECTORS DOWN' in txt
        assert 'TOP 3 SECTOR INDEXES UP' in txt
        assert 'TOP 3 SECTOR INDEXES DOWN' in txt
        assert 'NVDA' in txt
        with open(paths['html'], encoding='utf-8') as f:
            html = f.read()
        assert 'Stock Scanner Daily Report' in html
        assert '<table>' in html


def test_file_output_no_crash_on_bad_ticker():
    recs = [
        make_record('GOOD', 'tech', 3.0),
        {'symbol': 'BAD', 'category': 'tech', 'is_index_etf': False, 'daily_change_pct': None,
         'state': 'UPTREND', 'candidate_score': 50.0, 'daily': {'close': 100.0}},
    ]
    ctx = {'sector_index_data': {'tech': {'symbol': 'XLK', 'sector': 'tech', 'change_pct': None, 'close': None}}}
    report = DailyReport(recs, ctx, scan_date='2026-09-09')
    with tempfile.TemporaryDirectory() as tmp:
        paths = save_daily_report(report, output_dir=tmp, scan_date='2026-09-09')
        assert os.path.exists(paths['txt'])
        assert os.path.exists(paths['csv'])
        assert os.path.exists(paths['html'])