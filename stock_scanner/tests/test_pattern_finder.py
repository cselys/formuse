"""Offline regressions using the real canonical-envelope/store contract."""
import hashlib
import json
from pathlib import Path
import sqlite3

import pytest
import yaml

from stock_scanner.src.data.scanner_history import ScannerHistoryStore, SNAPSHOT_FIELDS, result_envelope
from stock_scanner.src.historical.pattern_finder import find_patterns, completed_sessions, validate_options
from stock_scanner.src.historical.pattern_source import read_history
from stock_scanner.src.reporting.pattern_report import save_reports, render_terminal

DATES = ['2026-10-05', '2026-10-06', '2026-10-07', '2026-10-08', '2026-10-09']
UNIVERSE = {'categories': {'tech': {'symbols': ['AAA', 'AAA', 'BBB']}, 'other': {'symbols': ['AAA']}}}


def envelope(symbol, date, state, *, close=100, signature='fixture-code-v1', source='RECORDED'):
    result = dict.fromkeys(SNAPSHOT_FIELDS)
    result.update(state=state, candidate_score=55.0, daily={'close': close})
    context = dict(calculation_policy='w-fri-drop-partial-v1', input_signature=f'{symbol}-{date}',
                   calculation_signature=signature, category_benchmark='QQQ', market_benchmark='SPY',
                   frame_fingerprints={'daily': 'd', 'weekly': 'w', 'category_benchmark': 'c', 'market_benchmark': 'm'})
    return result_envelope(symbol, date, '1.2', context, result, source, {'fixture': True}, None)


@pytest.fixture
def store(tmp_path):
    return ScannerHistoryStore(tmp_path / 'history.sqlite3')


def add(store, symbol, date, state, **kwargs):
    item = envelope(symbol, date, state, **kwargs)
    store.put(item['metadata']['revision_id'], item)
    return item


def query(store, **kwargs):
    options = dict(states='BOTTOM_FORMING,REVERSAL', recent_days=3, as_of='2026-10-09', store_path=store.path)
    options.update(kwargs)
    return find_patterns(UNIVERSE, **options)


def test_exact_two_states_and_metadata(store):
    add(store, 'AAA', DATES[1], 'BOTTOM_FORMING', close=100)
    add(store, 'AAA', DATES[2], 'REVERSAL', close=110)
    add(store, 'AAA', DATES[4], 'UPTREND')
    report = query(store)
    assert report['status'] == 'MATCHES_FOUND'
    assert len(report['matches']) == 1
    match = report['matches'][0]
    assert (match['start_date'], match['end_date'], match['sessions']) == (DATES[1], DATES[2], 2)
    assert match['categories'] == ['other', 'tech']
    assert match['price_change_pct'] == pytest.approx(10)
    assert match['latest_recorded_state'] == 'UPTREND'
    assert match['latest_candidate_score'] == 55
    assert match['final_within_recent_window']
    assert match['observations'][0]['source'] == 'RECORDED_VERIFIED'


def test_three_states(store):
    for date, state in zip(DATES[1:4], ['STRONG_DOWNTREND', 'BOTTOM_FORMING', 'REVERSAL']):
        add(store, 'AAA', date, state)
    report = query(store, states='STRONG_DOWNTREND,BOTTOM_FORMING,REVERSAL')
    assert len(report['matches']) == 1
    assert report['matches'][0]['sessions'] == 3


@pytest.mark.parametrize('states', [('REVERSAL', 'BOTTOM_FORMING'), ('BOTTOM_FORMING', 'NEUTRAL', 'REVERSAL')])
def test_wrong_order_or_intervening_state(store, states):
    for date, state in zip(DATES[1:], states):
        add(store, 'AAA', date, state)
    assert query(store)['matches'] == []
    assert query(store)['status'] == 'NO_MATCHES'


def test_missing_session_breaks_continuity(store):
    add(store, 'AAA', DATES[1], 'BOTTOM_FORMING')
    add(store, 'AAA', DATES[3], 'REVERSAL')
    report = query(store)
    assert report['status'] == 'INSUFFICIENT_HISTORY'
    assert not report['matches']


def test_different_symbols_never_join(store):
    add(store, 'AAA', DATES[1], 'BOTTOM_FORMING')
    add(store, 'BBB', DATES[2], 'REVERSAL')
    assert query(store)['usable_windows'] == 0


def test_recent_boundary_looks_before_window_without_reanchoring(store):
    add(store, 'AAA', DATES[1], 'BOTTOM_FORMING')
    add(store, 'AAA', DATES[2], 'REVERSAL')
    assert len(query(store, recent_days=3)['matches']) == 1
    report = query(store, recent_days=2)
    assert report['recent_start'] == DATES[3]
    assert not report['matches']


def test_max_span_exact_boundary(store):
    for date, state in zip(DATES[1:4], ['STRONG_DOWNTREND', 'BOTTOM_FORMING', 'REVERSAL']):
        add(store, 'AAA', date, state)
    states = 'STRONG_DOWNTREND,BOTTOM_FORMING,REVERSAL'
    assert len(query(store, states=states, max_span_days=3)['matches']) == 1
    with pytest.raises(ValueError, match='span'):
        query(store, states=states, max_span_days=2)
    auto = query(store, states=None, auto=True, max_span_days=2)
    assert all(len(p['states']) == 2 for p in auto['patterns'])


def test_discovery_occurrences_distinct_symbols_duplicates_and_limits(store):
    for symbol, states in [('AAA', ['BOTTOM_FORMING', 'REVERSAL', 'BOTTOM_FORMING', 'REVERSAL']),
                           ('BBB', ['BOTTOM_FORMING', 'REVERSAL'])]:
        for date, state in zip(DATES, states):
            add(store, symbol, date, state)
            add(store, symbol, date, state)  # Idempotent recorded occurrence.
    report = query(store, states=None, auto=True, recent_days=4, min_occurrences=3, limit=1)
    assert len(report['patterns']) == 1
    pattern = report['patterns'][0]
    assert pattern['states'] == ['BOTTOM_FORMING', 'REVERSAL']
    assert pattern['occurrences'] == 3 and pattern['distinct_symbols'] == 2
    assert pattern['most_recent_date'] == DATES[3]
    assert query(store, states=None, auto=True, min_occurrences=99)['status'] == 'NO_PATTERNS_MEET_THRESHOLD'


def test_repeated_states_are_daily_observations_not_compressed(store):
    for date in DATES:
        add(store, 'AAA', date, 'BOTTOM_FORMING')
    report = query(store, states=None, auto=True, recent_days=4)
    by_length = {len(p['states']): p for p in report['patterns']}
    assert by_length[2]['occurrences'] == 4
    assert by_length[3]['occurrences'] == 3


@pytest.mark.parametrize('options', [
    {'states': 'BOGUS,REVERSAL'}, {'states': 'REVERSAL'},
    {'states': 'REVERSAL,NEUTRAL,UPTREND,AVOID'}, {'max_states': 4},
    {'max_span_days': 21}, {'recent_days': 0}, {'limit': 0}, {'min_occurrences': 0},
])
def test_bad_options_rejected(options):
    base = dict(states='BOTTOM_FORMING,REVERSAL')
    base.update(options)
    with pytest.raises(ValueError):
        validate_options(**base)


def test_conflict_breaks_chain_and_latest_does_not_fall_back(store):
    add(store, 'AAA', DATES[1], 'BOTTOM_FORMING')
    add(store, 'AAA', DATES[2], 'REVERSAL')
    add(store, 'AAA', DATES[4], 'UPTREND')
    add(store, 'AAA', DATES[4], 'AVOID')
    report = query(store)
    assert report['matches'][0]['latest_recorded_state'] is None
    add(store, 'AAA', DATES[2], 'NEUTRAL')
    report = query(store)
    assert report['status'] == 'INSUFFICIENT_HISTORY'
    assert any('RECONCILIATION_REQUIRED' in r['reason'] for r in report['excluded_observations'])


@pytest.mark.parametrize('corruption', ['state', 'fingerprint', 'mapping', 'unverified', 'flag'])
def test_unverified_corrupt_or_flagged_revisions_are_excluded(store, corruption):
    item = add(store, 'AAA', DATES[1], 'BOTTOM_FORMING')
    add(store, 'AAA', DATES[2], 'REVERSAL')
    if corruption == 'state':
        item['result']['state'] = 'REVERSAL'
    elif corruption == 'fingerprint':
        item['metadata']['result_fingerprint'] = 'bad'
    elif corruption == 'mapping':
        item['metadata']['symbol'] = 'BBB'
    elif corruption == 'unverified':
        item['metadata']['result_source'] = 'RECORDED_LEGACY'
    else:
        item['metadata']['reconciliation_status'] = 'RECONCILIATION_REQUIRED'
    with sqlite3.connect(store.path) as conn:
        conn.execute('UPDATE history_revisions SET payload=? WHERE revision_id=?',
                     (json.dumps(item), item['metadata']['revision_id']))
    assert not query(store)['matches']


def test_legacy_only_and_missing_store_never_promoted_or_created(store):
    assert query(store)['status'] == 'INSUFFICIENT_HISTORY'
    assert not store.path.exists()
    with sqlite3.connect(store.path) as conn:
        conn.execute('CREATE TABLE results (payload TEXT)')
        conn.execute('INSERT INTO results VALUES (?)', (json.dumps({'state': 'REVERSAL'}),))
    report = query(store)
    assert report['source']['status'] == 'UNVERIFIED_ONLY'
    assert report['source']['legacy_counts']['results'] == 1


def test_policy_boundary_and_missing_price(store):
    add(store, 'AAA', DATES[1], 'BOTTOM_FORMING', close=None)
    add(store, 'AAA', DATES[2], 'REVERSAL')
    report = query(store)
    assert report['matches'][0]['start_price'] is None
    assert report['matches'][0]['price_change_pct'] is None
    add(store, 'BBB', DATES[1], 'BOTTOM_FORMING')
    add(store, 'BBB', DATES[2], 'REVERSAL', signature='different-config')
    assert query(store)['policy_breaks'] == 1


def test_future_and_incomplete_current_sessions_do_not_change_results(store):
    add(store, 'AAA', DATES[1], 'BOTTOM_FORMING')
    add(store, 'AAA', DATES[2], 'REVERSAL')
    before = query(store, as_of='2026-10-08T12:00:00-04:00')
    add(store, 'AAA', DATES[3], 'AVOID')
    add(store, 'AAA', DATES[4], 'REVERSAL')
    after = query(store, as_of='2026-10-08T12:00:00-04:00')
    assert before['matches'] == after['matches']
    assert before['recent_end'] == after['recent_end'] == DATES[2]


def test_weekend_holiday_and_early_close_conventions():
    assert completed_sessions('2026-10-11', 1)[1] == ['2026-10-09']
    assert completed_sessions('2026-04-03', 1)[1] == ['2026-04-02']
    assert completed_sessions('2026-11-27T12:59:00-05:00', 1)[1] == ['2026-11-25']
    assert completed_sessions('2026-11-27T13:00:00-05:00', 1)[1] == ['2026-11-27']


def test_repeated_outputs_are_distinct_escaped_and_json_complete(store, tmp_path):
    add(store, 'AAA', DATES[1], 'BOTTOM_FORMING')
    add(store, 'AAA', DATES[2], 'REVERSAL')
    report = query(store)
    report['issues'].append('<script>unsafe</script>')
    outputs = [save_reports(report, tmp_path / 'patterns') for _ in range(2)]
    assert len({p for pair in outputs for p in pair.values()}) == 4
    html = Path(outputs[0]['html']).read_text(encoding='utf-8')
    assert '<script>' not in html and '&lt;script&gt;' in html
    assert json.loads(Path(outputs[0]['json']).read_text()) == report
    assert 'BOTTOM_FORMING -> REVERSAL' in render_terminal(report)


def test_command_no_download_reconstruction_or_state_writes(store, tmp_path, monkeypatch, capsys):
    import stock_scanner.run_scanner as cli
    import stock_scanner.src.historical.stock_lookup as lookup
    import stock_scanner.src.data.historical_cache as cache
    from stock_scanner.src.data.yfinance_loader import YFinanceLoader
    add(store, 'AAA', DATES[1], 'BOTTOM_FORMING')
    add(store, 'AAA', DATES[2], 'REVERSAL')
    config = tmp_path / 'config'
    config.mkdir()
    (config / 'universe.yaml').write_text(yaml.safe_dump(UNIVERSE))
    protected = ['cache/daily.parquet', 'cache/weekly.parquet', 'cache/metadata.json',
                 'output/v13_forward/observations.json', 'output/v13_forward/outcomes.json', 'output/call_stocks.yaml']
    for name in protected:
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b'protected')
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in tmp_path.rglob('*') if p.is_file()}
    def forbidden(*args, **kwargs):
        pytest.fail('Pattern query must not download, reconstruct or write source data')
    for obj, name in [(cli.StockScanner, 'scan'), (lookup, 'lookup_stock'), (lookup, 'analyze_snapshot'),
                      (cache, 'load_cached_data'), (YFinanceLoader, 'download_ticker'),
                      (ScannerHistoryStore, 'put'), (ScannerHistoryStore, 'preserve_artifact')]:
        monkeypatch.setattr(obj, name, forbidden)
    args = ['find-pattern', '--states', 'BOTTOM_FORMING,REVERSAL', '--as-of', '2026-10-09',
            '--config-dir', str(config), '--history-store', str(store.path), '--output-dir', str(tmp_path / 'output/reports/patterns')]
    assert cli.main(args) == 0
    assert cli.main(args) == 0
    for name, digest in before.items():
        assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == digest
    added = {str(p) for p in tmp_path.rglob('*') if p.is_file()} - before.keys()
    assert len(added) == 4
    assert all(Path(p).parent.name == 'patterns' and Path(p).suffix in ('.html', '.json') for p in added)
    assert 'MATCHES_FOUND' in capsys.readouterr().out


def test_read_only_sqlite_connection(store, monkeypatch):
    add(store, 'AAA', DATES[1], 'BOTTOM_FORMING')
    connect = sqlite3.connect
    seen = []
    def check(database, **kwargs):
        seen.append(database)
        conn = connect(database, **kwargs)
        with pytest.raises(sqlite3.OperationalError):
            conn.execute('CREATE TABLE forbidden (x)')
        return conn
    monkeypatch.setattr(sqlite3, 'connect', check)
    read_history(store.path, DATES[-1])
    assert len(seen) == 1 and seen[0].endswith('?mode=ro')
