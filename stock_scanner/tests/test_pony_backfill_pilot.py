"""Single-pilot guards, using only synthetic prices and temporary databases."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket
import sqlite3

import numpy as np
import pandas as pd
import pytest
import yaml

from stock_scanner import pony_backfill_pilot as pilot
from stock_scanner.src.data.market_calendar import schedule
from stock_scanner.src.data.scanner_history import (
    ScannerHistoryStore, calculation_signature, history_context, revision_id,
)
import stock_scanner.src.historical.stock_lookup as lookup


@pytest.fixture(params=['2026-09-23', '2026-09-22', '2026-09-24'])
def environment(tmp_path, monkeypatch, request):
    date = request.param
    config = yaml.safe_load((pilot.ROOT / 'config/scanner.yaml').read_text())
    (tmp_path / 'config').mkdir()
    (tmp_path / 'config/scanner.yaml').write_text(yaml.safe_dump(config))
    universe = {'categories': {'china': {'symbols': ['PONY'], 'benchmark': 'QQQ'}}}
    (tmp_path / 'config/universe.yaml').write_text(yaml.safe_dump(universe))
    cache = tmp_path / 'stock_scanner/src/cache'
    cache.mkdir(parents=True)
    index = schedule('2025-06-02', date).index
    x = np.arange(len(index))
    frames = {}
    for symbol, growth in [('PONY', .13), ('QQQ', .07), ('SPY', .03)]:
        close = 100 + growth*x + 3*np.sin(x/7)
        frames[symbol] = pd.DataFrame(dict(Open=close, High=close+2, Low=close-2,
                                          Close=close+.3, Volume=1_000_000+x*100), index=index)
        frames[symbol].to_parquet(cache / f'{symbol}.parquet')
    calculation = calculation_signature(config)
    weekly = lookup.YFinanceLoader().resample_to_weekly(frames['PONY'], as_of_date=date, drop_partial=True)
    context = history_context(calculation, 'PONY', 'china', 'QQQ', 'SPY', frames['PONY'], weekly,
                              frames['QQQ'], frames['SPY'], calculation_policy=pilot.POLICY)
    monkeypatch.setattr(pilot, 'ROOT', tmp_path)
    monkeypatch.setattr(pilot, 'EXPECTED_CONFIG_ROOT', tmp_path / 'config')
    monkeypatch.setattr(pilot, 'ADDITIONAL_INPUTS', {**pilot.ADDITIONAL_INPUTS, **({date: context['input_signature']} if date != pilot.DATE else {})})
    monkeypatch.setattr(pilot, 'PLANNED_INPUT', context['input_signature'])
    monkeypatch.setattr(pilot, 'PLANNED_CALCULATION', calculation)
    path = tmp_path / 'stock_scanner/data/history_lookup/results.sqlite3'
    path.parent.mkdir(parents=True)
    connect = sqlite3.connect

    def guarded_connect(database, *args, **kwargs):
        # Even an accidental default-store connection must fail the test.
        name = str(database).replace('\\', '/').lower()
        assert str(tmp_path).replace('\\', '/').lower() in name, 'Non-fixture database access'
        return connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, 'connect', guarded_connect)
    monkeypatch.setattr(socket, 'create_connection', lambda *a, **kw: pytest.fail('Network forbidden'))
    monkeypatch.setattr(lookup, 'load_cached_data', lambda *a: pytest.fail('Default cache loader forbidden'))
    bundle = pilot._load_inputs(calculation, date=date)
    candidate = pilot._stage(bundle, context['input_signature'], calculation, date=date).envelope
    # Preserve a valid unrelated PLTR record plus opaque artifact/legacy payloads.
    existing = deepcopy(candidate)
    existing['metadata']['symbol'] = 'PLTR'
    existing['metadata']['revision_id'] = revision_id(existing)
    store = ScannerHistoryStore(path)
    store.put(store.key('PLTR', date, existing['metadata']['history_context']), existing)
    with connect(path) as db:
        db.execute('CREATE TABLE history_artifacts(artifact_id TEXT PRIMARY KEY,payload TEXT NOT NULL)')
        db.execute('INSERT INTO history_artifacts VALUES (?,?)', ('untouched-artifact', '{"status":"UNVERIFIED"}'))
        db.execute('CREATE TABLE results(cache_key TEXT PRIMARY KEY,payload TEXT NOT NULL)')
        db.execute('INSERT INTO results VALUES (?,?)', ('untouched-legacy', '{"old":true}'))
    monkeypatch.setattr(pilot, 'EXPECTED_COUNTS', {'history_revisions': 1, 'history_canonical': 1, 'history_artifacts': 1, 'results': 1})
    monkeypatch.setattr(pilot, 'EXPECTED_DATABASE_SHA256', hashlib.sha256(path.read_bytes()).hexdigest())
    return dict(date=date, root=tmp_path, path=path, frames=frames, bundle=bundle, candidate=candidate,
                input=context['input_signature'], calculation=calculation, connect=connect)


def run(env, **overrides):
    args = dict(symbol='PONY', date=env['date'], expected_input=env['input'],
                expected_calculation=env['calculation'], apply=True)
    args.update(overrides)
    return pilot.run_pilot(**args)


def digest(env):
    return hashlib.sha256(env['path'].read_bytes()).hexdigest()


def rejected(env, match=None, **kwargs):
    before = digest(env)
    with pytest.raises((pilot.PilotAbort, ValueError, KeyError, sqlite3.Error), match=match):
        run(env, **kwargs)
    assert digest(env) == before


def test_exact_date_staging_is_isolated_and_cwd_independent(environment, monkeypatch):
    env = environment
    monkeypatch.chdir(env['root'] / 'stock_scanner')
    monkeypatch.setattr(ScannerHistoryStore, 'put', lambda *a: pytest.fail('Disk store must not stage'))
    before = digest(env)
    receipt = run(env, apply=False)
    assert not receipt['applied'] and digest(env) == before
    assert receipt['metadata']['symbol'] == 'PONY'
    assert receipt['metadata']['evaluation_date'] == environment['date']
    assert receipt['metadata']['scanner_version'] == '1.2'
    assert receipt['metadata']['calculation_policy'] == pilot.POLICY


def test_atomic_success_preserves_every_existing_row_and_cache(environment):
    env = environment
    before = pilot._read_before(env['path'])
    hashes = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (env['root']/'stock_scanner/src/cache').glob('*')}
    receipt = run(env)
    with env['connect'](env['path']) as db:
        after = pilot._snapshot(db)
    for table in pilot.TABLES:
        assert after[table][:len(before[table])] == before[table]
        assert len(after[table]) == len(before[table]) + (table in ('history_revisions', 'history_canonical'))
    assert receipt['inserted'] == {'history_revisions': 1, 'history_canonical': 1}
    assert after['history_canonical'][-1] == ('PONY', environment['date'], receipt['metadata']['revision_id'])
    assert all(hashlib.sha256(p.read_bytes()).hexdigest() == h for p, h in hashes.items())


@pytest.mark.parametrize('override', [{'symbol': 'PLTR'}, {'symbol': 'pony'}, {'date': '2026-09-25'},
                                      {'date': '2026-09-23T00:00:00'}])
def test_other_target_is_rejected(environment, override):
    rejected(environment, 'Only PONY', **override)


@pytest.mark.parametrize('field', ['date', 'symbol'])
def test_wrong_lookup_identity(environment, monkeypatch, field):
    original = pilot.lookup_stock
    def wrong(*args, **kwargs):
        report = original(*args, **kwargs)
        if field == 'date':
            report.rows[0]['date'] = '2026-09-21'
        else:
            report.symbol = 'PLTR'
        return report
    monkeypatch.setattr(pilot, 'lookup_stock', wrong)
    rejected(environment)


@pytest.mark.parametrize('symbol', ['PONY', 'QQQ', 'SPY'])
def test_missing_exact_date(environment, symbol):
    env = environment
    env['frames'][symbol].iloc[:-1].to_parquet(env['root']/f'stock_scanner/src/cache/{symbol}.parquet')
    rejected(env, 'Missing exact-date')


@pytest.mark.parametrize('failure', ['short', 'gap', 'weekly'])
def test_existing_input_and_completed_week_guards(environment, monkeypatch, failure):
    env = environment
    if failure == 'weekly':
        original = lookup.YFinanceLoader.resample_to_weekly
        monkeypatch.setattr(lookup.YFinanceLoader, 'resample_to_weekly',
                            lambda *a, **kw: original(*a, **kw).iloc[-9:])
    else:
        frame = env['frames']['PONY']
        frame = frame.iloc[-99:] if failure == 'short' else frame.drop(frame.index[-20])
        frame.to_parquet(env['root']/'stock_scanner/src/cache/PONY.parquet')
    rejected(env, 'Exact-date lookup failed')


def test_actual_input_fingerprint_mismatch(environment):
    env = environment
    frame = env['frames']['PONY'].copy()
    frame.loc[frame.index[-1], 'Volume'] += 123
    frame.to_parquet(env['root']/'stock_scanner/src/cache/PONY.parquet')
    rejected(env, 'Input fingerprint mismatch')


def test_actual_configuration_fingerprint_mismatch(environment):
    env = environment
    path = env['root']/'config/scanner.yaml'
    config = yaml.safe_load(path.read_text())
    config['pilot_test_changed_configuration'] = True
    path.write_text(yaml.safe_dump(config))
    rejected(env, 'Calculation fingerprint mismatch')


@pytest.mark.parametrize('field', ['expected_input', 'expected_calculation'])
def test_required_planned_fingerprints(environment, field):
    rejected(environment, 'approved plan', **{field: '0'*64})


def test_v13_root_configuration_rejected(environment):
    path = environment['root']/'config/scanner.yaml'
    config = yaml.safe_load(path.read_text())
    config['scanner_version'] = '1.3'
    path.write_text(yaml.safe_dump(config))
    rejected(environment, 'Root configuration')


@pytest.mark.parametrize('kind', ['canonical', 'revision'])
def test_existing_target_blocks_even_an_orphan(environment, kind):
    env = environment
    with env['connect'](env['path']) as db:
        m = env['candidate']['metadata']
        if kind == 'canonical':
            db.execute('INSERT INTO history_canonical VALUES (?,?,?)', ('PONY', environment['date'], m['revision_id']))
        else:
            db.execute('INSERT INTO history_revisions VALUES (?,?,?)',
                       (m['revision_id'], ScannerHistoryStore.key('PONY', environment['date'], m['history_context']), json.dumps(env['candidate'])))
    rejected(env, f'Target {"canonical mapping" if kind == "canonical" else "revision"} already exists')


@pytest.mark.parametrize('failure', ['fingerprint', 'provenance'])
def test_candidate_verification_failure(environment, monkeypatch, failure):
    original = pilot.lookup_stock
    def corrupt(*args, **kwargs):
        report = original(*args, **kwargs)
        meta = kwargs['store'].envelope['metadata']
        if failure == 'fingerprint':
            meta['result_fingerprint'] = 'bad'
        else:
            meta['data_cache_identity'] = {'unexpected': 'path'}
        return report
    monkeypatch.setattr(pilot, 'lookup_stock', corrupt)
    rejected(environment)


@pytest.mark.parametrize('table', ['history_revisions', 'history_canonical'])
def test_insertion_error_rolls_back_everything(environment, monkeypatch, table):
    env = environment
    class FailingConnection(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if sql.startswith('INSERT INTO '+table+' '):
                raise sqlite3.IntegrityError('injected insert failure')
            return super().execute(sql, *args, **kwargs)
    original = sqlite3.connect
    monkeypatch.setattr(sqlite3, 'connect', lambda *a, **kw: original(*a, **{**kw, 'factory': FailingConnection}))
    rejected(env, 'injected insert failure')


def test_post_insert_invariant_failure_rolls_back(environment, monkeypatch):
    original = pilot._post_insert
    def changed_artifact(connection, *args):
        connection.execute("UPDATE history_artifacts SET payload='unexpected'")
        original(connection, *args)
    monkeypatch.setattr(pilot, '_post_insert', changed_artifact)
    rejected(environment, 'Post-insert invariant')


@pytest.mark.parametrize('kind', ['input', 'calculation'])
def test_immediate_prewrite_fingerprints_recomputed(environment, monkeypatch, kind):
    original = pilot._load_inputs
    calls = []
    def changed(expected, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            if kind == 'calculation':
                monkeypatch.setattr(pilot, 'calculation_signature', lambda config: 'changed')
            else:
                path = environment['root']/'stock_scanner/src/cache/PONY.parquet'
                frame = pd.read_parquet(path)
                frame.iloc[-1, frame.columns.get_loc('Volume')] += 1
                frame.to_parquet(path)
        return original(expected, **kwargs)
    monkeypatch.setattr(pilot, '_load_inputs', changed)
    rejected(environment, 'fingerprint mismatch')
    assert len(calls) == 2


@pytest.mark.parametrize('kind', ['canonical', 'revision'])
def test_target_appearing_during_staging_is_preserved_and_blocks_insert(environment, monkeypatch, kind):
    env = environment
    original = pilot._insert
    observed = []
    def race(path, before, stage, *args):
        m = stage.envelope['metadata']
        with env['connect'](path) as db:
            if kind == 'canonical':
                db.execute('INSERT INTO history_canonical VALUES (?,?,?)', ('PONY', environment['date'], m['revision_id']))
            else:
                db.execute('INSERT INTO history_revisions VALUES (?,?,?)',
                           (m['revision_id'], stage.input_key, json.dumps(stage.envelope)))
        observed.append(digest(env))
        return original(path, before, stage, *args)
    monkeypatch.setattr(pilot, '_insert', race)
    with pytest.raises(pilot.PilotAbort, match='already exists'):
        run(env)
    assert digest(env) == observed[0]


def test_unexpected_trigger_blocks_all_writes(environment):
    env = environment
    with env['connect'](env['path']) as db:
        db.execute("CREATE TRIGGER dangerous AFTER INSERT ON history_canonical BEGIN DELETE FROM results; END")
    rejected(env, 'triggers')


def test_default_is_staging_without_disk_store_or_recalculation_at_commit(environment, monkeypatch):
    env = environment
    calls = []
    original = lookup.analyze_snapshot
    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(lookup, 'analyze_snapshot', counted)
    monkeypatch.setattr(ScannerHistoryStore, '__init__', lambda *a, **kw: pytest.fail('Disk staging forbidden'))
    before = digest(env)
    receipt = pilot.run_pilot('PONY', environment['date'], expected_input=env['input'],
                              expected_calculation=env['calculation'])
    assert receipt['applied'] is False and digest(env) == before
    assert len(calls) == 1
    calls.clear()
    run(env)
    assert len(calls) == 1  # Commit revalidates via lookup but stops before scoring.


def test_staged_key_tampering_blocks_write(environment, monkeypatch):
    original = pilot._insert
    def corrupt(path, before, stage, *args):
        stage.input_key = 'wrong'
        return original(path, before, stage, *args)
    monkeypatch.setattr(pilot, '_insert', corrupt)
    rejected(environment, 'Staged input key mismatch')


def test_allowlist_contains_only_original_and_two_additions():
    assert pilot.DATE == '2026-09-23'
    assert pilot.ADDITIONAL_INPUTS == {
        '2026-09-22': 'd951298e7406068400ec08e3891c6ceaa0c75885df59ae2d18beaec28adf551d',
        '2026-09-24': 'ac8af63fd73235071e8e2ffd27416b561ac91728575eb652f71b55eefc1978d0',
    }
    for day in pd.date_range('2026-09-01', '2026-10-31'):
        date = str(day.date())
        if date in (pilot.DATE, *pilot.ADDITIONAL_INPUTS):
            pilot._target('PONY', date)
        else:
            with pytest.raises(pilot.PilotAbort):
                pilot._target('PONY', date)
    for symbol in ['PLTR', 'QQQ', 'SPY', 'pony', ' PONY', '', None]:
        with pytest.raises(pilot.PilotAbort):
            pilot._target(symbol, pilot.DATE)


@pytest.mark.parametrize('field', ['symbol', 'date'])
def test_duplicate_collection_request_rejected(environment, field):
    value = 'PONY' if field == 'symbol' else environment['date']
    rejected(environment, 'no duplicate or batch', **{field: [value, value]})


@pytest.mark.parametrize('option', ['--symbol', '--date', '--expected-input', '--expected-calculation'])
def test_duplicate_cli_options_rejected_before_execution(monkeypatch, option):
    monkeypatch.setattr(pilot, 'run_pilot', lambda *a, **kw: pytest.fail('Duplicate reached execution'))
    values = {'--symbol': 'PONY', '--date': '2026-09-22', '--expected-input': 'input',
              '--expected-calculation': 'calculation'}
    args = [part for item in values.items() for part in item] + [option, values[option]]
    with pytest.raises(SystemExit) as exc:
        pilot.main(args)
    assert exc.value.code == 2


@pytest.mark.parametrize('kind', ['counts', 'same_count_content'])
def test_unexpected_baseline_rejected_before_staging(environment, monkeypatch, kind):
    env = environment
    with env['connect'](env['path']) as db:
        if kind == 'counts':
            db.execute("INSERT INTO results VALUES ('extra','untouched')")
        else:
            db.execute("UPDATE results SET payload='external change'")
    monkeypatch.setattr(pilot, '_stage', lambda *a, **kw: pytest.fail('Baseline failure reached staging'))
    rejected(env, 'Database baseline')


@pytest.mark.parametrize('kind', ['root', 'policy'])
def test_config_root_or_policy_mismatch(environment, monkeypatch, kind):
    if kind == 'root':
        monkeypatch.setattr(pilot, 'EXPECTED_CONFIG_ROOT', environment['root']/'wrong-config')
    else:
        monkeypatch.setattr(pilot, 'weekly_policy', lambda config: 'nyse-completed-weeks-v1')
    rejected(environment, 'root mismatch' if kind == 'root' else 'Root configuration')


def test_physical_baseline_rechecked_inside_transaction(environment, monkeypatch):
    env = environment
    original = pilot._insert
    external_digest = []
    def race(path, *args):
        with env['connect'](path) as db:
            # Identical table contents, different physical database fingerprint.
            db.execute('CREATE INDEX external_index ON results(payload)')
        external_digest.append(digest(env))
        return original(path, *args)
    monkeypatch.setattr(pilot, '_insert', race)
    with pytest.raises(pilot.PilotAbort, match='Database baseline fingerprint'):
        run(env)
    assert digest(env) == external_digest[0]


def test_success_cannot_be_replayed_or_advance_the_other_date(environment, monkeypatch):
    env = environment
    run(env)
    rejected(env, 'Target canonical mapping already exists')
    other = next(date for date in pilot.ADDITIONAL_INPUTS if date != env['date'])
    monkeypatch.setattr(pilot, '_stage', lambda *a, **kw: pytest.fail('Second candidate reached staging'))
    rejected(env, 'Database baseline', date=other, expected_input=pilot.ADDITIONAL_INPUTS[other])


def test_staging_rejects_another_allowlisted_date(environment, monkeypatch):
    original = pilot.lookup_stock
    def wrong_key(*args, **kwargs):
        stage = kwargs['store']
        wrong = next(date for date in (pilot.DATE, *pilot.ADDITIONAL_INPUTS) if date != stage.date)
        stage.key('PONY', wrong, environment['candidate']['metadata']['history_context'])
        return original(*args, **kwargs)
    monkeypatch.setattr(pilot, 'lookup_stock', wrong_key)
    rejected(environment, 'substituted a different target date')
