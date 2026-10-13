"""Cold-cache integrity regressions for the historical lookup audit findings."""
import copy
import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

import stock_scanner.src.historical.stock_lookup as lookup
from stock_scanner.src.data.market_calendar import completed_daily, completed_weekly, schedule
from stock_scanner.src.data.scanner_history import (
    ScannerHistoryStore, result_fingerprint, weekly_policy,
)
from stock_scanner.src.reporting.stock_history import render_stock_history

T = '2025-04-17'  # Thursday before Good Friday: completed holiday week in V1.3.


@pytest.fixture
def inputs():
    index = schedule('2024-01-02', '2025-04-25').index
    x = np.arange(len(index))
    frames = {}
    for name, growth in [('NVDA', .13), ('QQQ', .07), ('SPY', .03)]:
        close = 100 + growth * x + 3 * np.sin(x / 7)
        frames[name] = pd.DataFrame(dict(Open=close, High=close+2, Low=close-2,
                                         Close=close+.3, Volume=1_000_000+x*100), index=index)
    config = yaml.safe_load((Path(__file__).parents[1] / 'config/scanner.yaml').read_text())
    universe = {'categories': {'tech': {'symbols': ['NVDA'], 'benchmark': 'QQQ'}}}
    return frames, config, universe


def run(inputs, path, *, frames=None, as_of='2025-04-25', report_dirs=(), period='10d'):
    data, config, universe = inputs
    data = data if frames is None else frames
    store = ScannerHistoryStore(path)
    report = lookup.lookup_stock('NVDA', period, config, universe, as_of=as_of,
                                 load_prices=lambda name: data.get(name), store=store,
                                 report_dirs=report_dirs,
                                 data_cache_identity={'fixture': 'integrity-ohlcv-v1'})
    return report, store


def at(report, date=T):
    return next(row for row in report.rows if row['date'] == date)


def archive(directory, envelope, **changes):
    record = copy.deepcopy(envelope['result'])
    metadata = envelope['metadata']
    record.update(symbol=metadata['symbol'], data_date=metadata['evaluation_date'],
                  history_context=metadata['history_context'], data_status='OK')
    record.update(changes)
    record['history_result_fingerprint'] = result_fingerprint(record)
    directory.mkdir(exist_ok=True)
    path = directory / f'{metadata["evaluation_date"]}.json'
    path.write_text(json.dumps({'results': [record]}))
    return path, record


@pytest.mark.parametrize('version', ['1.2', '1.3'])
@pytest.mark.parametrize('future_symbol', ['NVDA', 'QQQ', 'SPY'])
def test_cold_future_prices_and_appended_sessions_leave_full_snapshot_identical(inputs, tmp_path, version, future_symbol):
    frames, config, _ = inputs
    config['scanner_version'] = version
    through_t = {name: frame.loc[:T] for name, frame in frames.items()}
    before, first = run(inputs, tmp_path/'before.sqlite', frames=through_t)
    future = {name: frame.copy() for name, frame in frames.items()}
    mask = future[future_symbol].index > T
    future[future_symbol].loc[mask, ['Open', 'High', 'Low', 'Close']] *= 25
    future[future_symbol].loc[mask, 'Volume'] *= 10
    after, second = run(inputs, tmp_path/'after.sqlite', frames=future)
    a, b = first.canonical('NVDA', T), second.canonical('NVDA', T)
    assert a['result'] == b['result']  # Includes every score, indicator, structure and weekly field.
    assert a['metadata']['input_fingerprint'] == b['metadata']['input_fingerprint']
    assert a['metadata']['revision_id'] == b['metadata']['revision_id']
    assert at(before)['candidate_score'] == at(after)['candidate_score']
    assert at(after)['source'] == 'RECONSTRUCTED_VERIFIED'


@pytest.mark.parametrize('spy_available_at_t', [False, True])
def test_future_benchmark_availability_cannot_change_selection_or_make_t_missing(inputs, tmp_path, spy_available_at_t):
    frames, _, _ = inputs
    before_data = {name: frame.loc[:T] for name, frame in frames.items()}
    if not spy_available_at_t:
        before_data.pop('SPY')
    before, first = run(inputs, tmp_path/'before.sqlite', frames=before_data)
    after_data = {name: frame.copy() for name, frame in frames.items()}
    if not spy_available_at_t:
        after_data['SPY'] = after_data['SPY'].loc[after_data['SPY'].index > T]
    after, second = run(inputs, tmp_path/'after.sqlite', frames=after_data)
    assert at(before)['state'] is not None and at(after)['state'] is not None
    assert at(before)['market_benchmark'] == at(after)['market_benchmark'] == ('SPY' if spy_available_at_t else 'QQQ')
    assert first.canonical('NVDA', T)['result'] == second.canonical('NVDA', T)['result']
    assert first.canonical('NVDA', T)['metadata']['revision_id'] == second.canonical('NVDA', T)['metadata']['revision_id']


def test_independent_cold_reconstructions_are_deterministic(inputs, tmp_path):
    _, first = run(inputs, tmp_path/'first.sqlite', as_of=T)
    _, second = run(inputs, tmp_path/'second.sqlite', as_of=T)
    assert first.canonical('NVDA', T)['result'] == second.canonical('NVDA', T)['result']
    assert first.canonical('NVDA', T)['metadata']['revision_id'] == second.canonical('NVDA', T)['metadata']['revision_id']


@pytest.mark.parametrize('incompatibility', ['missing_fingerprint', 'partial_week_policy', 'changed_result', 'changed_inputs'])
def test_incompatible_archive_never_replaces_verified_reconstruction(inputs, tmp_path, incompatibility):
    _, source = run(inputs, tmp_path/'baseline.sqlite', as_of=T, period='1d')
    original = source.canonical('NVDA', T)
    directory = tmp_path/'recorded'
    path, saved = archive(directory, original)
    if incompatibility == 'missing_fingerprint':
        saved.pop('history_context')
    elif incompatibility == 'partial_week_policy':
        saved['history_context']['calculation_policy'] = 'w-fri-live-partial-v1'
    elif incompatibility == 'changed_inputs':
        saved['history_context']['input_signature'] = 'different-history'
    # This corruption must be caught even if all input metadata still matches.
    saved['candidate_score'] = 1.0
    saved['state'] = 'AVOID'
    path.write_text(json.dumps({'results': [saved]}))
    report, store = run(inputs, tmp_path/'fresh.sqlite', as_of=T, period='1d', report_dirs=[directory])
    assert at(report)['source'] == 'RECONSTRUCTED_VERIFIED'
    assert store.canonical('NVDA', T)['result'] == original['result']
    assert at(report)['legacy_artifacts'][0]['status'] == 'UNVERIFIED'
    assert at(report)['legacy_artifacts'][0]['result']['candidate_score'] == 1.0
    html = render_stock_history(report)
    assert 'RECONSTRUCTED_VERIFIED' in html and 'RECORDED_LEGACY' in html and 'UNVERIFIED' in html


def test_matching_verified_archive_reuses_complete_snapshot_without_calculation(inputs, tmp_path, monkeypatch):
    _, original = run(inputs, tmp_path/'original.sqlite', as_of=T, period='1d')
    baseline = original.canonical('NVDA', T)
    directory = tmp_path/'recorded'
    archive(directory, baseline)
    monkeypatch.setattr(lookup, 'analyze_snapshot', lambda *a: pytest.fail('Compatible recorded snapshot should be reused'))
    report, store = run(inputs, tmp_path/'fresh.sqlite', as_of=T, period='1d', report_dirs=[directory])
    assert at(report)['source'] == 'RECORDED_VERIFIED'
    assert store.canonical('NVDA', T)['result'] == baseline['result']
    assert not at(report)['legacy_artifacts']


@pytest.mark.parametrize('verified_conflict', [False, True])
def test_later_conflicting_archive_cannot_replace_canonical_revision(inputs, tmp_path, verified_conflict):
    database = tmp_path/'history.sqlite'
    first, store = run(inputs, database, as_of=T, period='1d')
    baseline = store.canonical('NVDA', T)
    directory = tmp_path/'recorded'
    path, record = archive(directory, baseline, candidate_score=1.0, state='AVOID')
    if not verified_conflict:
        record.pop('history_context')
        path.write_text(json.dumps({'results': [record]}))
    second, store = run(inputs, database, as_of=T, period='1d', report_dirs=[directory])
    assert at(first)['candidate_score'] == at(second)['candidate_score']
    assert at(first)['state'] == at(second)['state']
    assert store.canonical('NVDA', T) == baseline
    with sqlite3.connect(database) as db:
        if verified_conflict:
            assert at(second)['reconciliation_status'] == 'RECONCILIATION_REQUIRED'
            assert db.execute('SELECT count(*) FROM history_revisions').fetchone()[0] == 2
        else:
            assert at(second)['legacy_artifacts'][0]['status'] == 'UNVERIFIED'
            assert db.execute('SELECT count(*) FROM history_artifacts').fetchone()[0] == 1


def test_changed_historical_inputs_preserve_revision_and_flag_reconciliation(inputs, tmp_path):
    frames, _, _ = inputs
    database = tmp_path/'history.sqlite'
    before, store = run(inputs, database, as_of=T, period='1d')
    canonical = store.canonical('NVDA', T)
    changed = {name: frame.copy() for name, frame in frames.items()}
    changed['NVDA'].loc[T, ['Open', 'High', 'Low', 'Close']] *= 1.1
    after, store = run(inputs, database, frames=changed, as_of=T, period='1d')
    assert store.canonical('NVDA', T) == canonical
    assert at(after)['reconciliation_status'] == 'RECONCILIATION_REQUIRED'
    assert at(after)['close'] == at(before)['close']  # No mixing revised close with old score.
    with sqlite3.connect(database) as db:
        assert db.execute('SELECT count(*) FROM history_revisions').fetchone()[0] == 2


def test_provenance_round_trip_and_idempotent_revision(inputs, tmp_path):
    database = tmp_path/'history.sqlite'
    report, store = run(inputs, database, as_of=T, period='1d')
    envelope = store.canonical('NVDA', T)
    meta = envelope['metadata']
    key = store.key('NVDA', T, meta['history_context'])
    store.put(key, envelope)
    reopened = ScannerHistoryStore(database)
    assert reopened.get(key) == envelope == reopened.canonical('NVDA', T)
    assert meta['symbol'] == 'NVDA' and meta['evaluation_date'] == T
    assert meta['scanner_version'] == str(inputs[1]['scanner_version'])
    assert meta['result_source'] == 'RECONSTRUCTED' and meta['reconstruction_status'] == 'VERIFIED'
    assert meta['data_source'] == 'local_adjusted_ohlcv'
    assert meta['data_cache_identity'] == {'fixture': 'integrity-ohlcv-v1'}
    assert meta['market_benchmark_symbol'] == 'SPY' and meta['category_benchmark_symbol'] == 'QQQ'
    assert set(meta['frame_fingerprints']) == {'daily', 'weekly', 'category_benchmark', 'market_benchmark'}
    assert all(meta[name] for name in ['input_fingerprint', 'calculation_fingerprint', 'result_fingerprint',
                                      'generated_at', 'revision_id', 'calculation_policy'])
    assert at(report)['provenance'] == meta
    with sqlite3.connect(database) as db:
        assert db.execute('SELECT count(*) FROM history_revisions').fetchone()[0] == 1


def test_pre_integrity_cache_is_preserved_but_not_trusted(inputs, tmp_path):
    database = tmp_path/'old.sqlite'
    with sqlite3.connect(database) as db:
        db.execute('CREATE TABLE results(cache_key TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        db.execute('INSERT INTO results VALUES (?, ?)', ('old', '{"candidate_score":1}'))
    report, store = run(inputs, database, as_of=T, period='1d')
    assert at(report)['source'] == 'RECONSTRUCTED_VERIFIED'
    with sqlite3.connect(database) as db:
        assert db.execute('SELECT payload FROM results').fetchone()[0] == '{"candidate_score":1}'


def test_weekly_policy_identifies_legacy_live_difference_without_changing_formulas(inputs):
    frames, config, _ = inputs
    config['scanner_version'] = '1.2'
    assert weekly_policy(config) == 'w-fri-drop-partial-v1'
    assert weekly_policy(config, historical=False) == 'w-fri-live-partial-v1'
    daily = completed_daily(frames['NVDA'], '2025-04-21')
    completed = lookup.YFinanceLoader().resample_to_weekly(daily, as_of_date='2025-04-21', drop_partial=True)
    live = lookup.YFinanceLoader().resample_to_weekly(daily)
    assert completed.index[-1] < live.index[-1]
    config['scanner_version'] = '1.3'
    assert weekly_policy(config) == weekly_policy(config, historical=False)
    assert completed_weekly(daily, '2025-04-21').index[-1] == pd.Timestamp('2025-04-18')
