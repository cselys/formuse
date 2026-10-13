"""Guarded PONY pilot: one allowlisted date per invocation, never a batch.

Run as a module; staging is the default and --apply is an explicit write gate.
There is no bulk mode, database/config override, archive promotion, or retry.
"""
import argparse
from contextlib import closing
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import sqlite3

import pandas as pd
import yaml

from stock_scanner.src.data.market_calendar import completed_daily, schedule
from stock_scanner.src.validation.universe_validator import validate_universe_yaml
from stock_scanner.src.data.scanner_history import ScannerHistoryStore, calculation_signature, weekly_policy
from stock_scanner.src.historical.pattern_source import _check
from stock_scanner.src.historical.stock_lookup import lookup_stock

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_CONFIG_ROOT = Path('C:/Git/AI/Claude/dailyscanner/config')
SYMBOL, DATE = 'PONY', '2026-09-23'
POLICY = 'w-fri-drop-partial-v1'
PLANNED_INPUT = 'b219f816c52dbfb427b758aac85809fbec065e50def19e6bbb69a812abe3e6c2'
PLANNED_CALCULATION = '3a01a058a8481a5f165acf05c222358c458fbd1926334ead8b139ff2d074b055'
ADDITIONAL_INPUTS = {
    '2026-09-22': 'd951298e7406068400ec08e3891c6ceaa0c75885df59ae2d18beaec28adf551d',
    '2026-09-24': 'ac8af63fd73235071e8e2ffd27416b561ac91728575eb652f71b55eefc1978d0',
}
EXPECTED_DATABASE_SHA256 = 'a29beb4f4668c4b99f29fa4d05ec099184264a5e2c0598e0f318f47a93416d31'
EXPECTED_COUNTS = {'history_revisions': 159, 'history_canonical': 159,
                   'history_artifacts': 94, 'results': 19}
TABLES = ('history_revisions', 'history_canonical', 'history_artifacts', 'results')


class PilotAbort(RuntimeError):
    """A guard failed. Never automatically repair or retry."""


def _require(condition, reason):
    if not condition:
        raise PilotAbort(reason)


def _target(symbol, date):
    _require(type(symbol) is str and type(date) is str and symbol == SYMBOL
             and date in (DATE, *ADDITIONAL_INPUTS),
             'Only PONY and one exact allowlisted date are allowed; no duplicate or batch requests')


def _config_root():
    root = (ROOT / 'config').resolve()
    _require(root == EXPECTED_CONFIG_ROOT.resolve(), 'Configuration root mismatch')
    return root


def _baseline(path, rows):
    # A successful commit invalidates this proposal. Never silently advance it
    # for the other date; another reviewed baseline is required afterwards.
    _require(not Path(str(path) + '-wal').exists(), 'Active WAL requires a separate audit')
    _require({t: len(v) for t, v in rows.items()} == EXPECTED_COUNTS,
             'Database baseline counts mismatch')
    _require(hashlib.sha256(path.read_bytes()).hexdigest() == EXPECTED_DATABASE_SHA256,
             'Database baseline fingerprint mismatch')


def _snapshot(connection):
    tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    _require(tables == set(TABLES), 'Unexpected history schema; no migration allowed')
    _require(not connection.execute("SELECT 1 FROM sqlite_master WHERE type='trigger'").fetchone(),
             'History triggers are not supported')
    _require(connection.execute('PRAGMA integrity_check').fetchall() == [('ok',)],
             'SQLite integrity check failed')
    return {t: connection.execute(f'SELECT * FROM {t} ORDER BY rowid').fetchall() for t in TABLES}


def _absent_and_valid(rows, date=DATE):
    _require(not any(r[:2] == (SYMBOL, date) for r in rows['history_canonical']),
             'Target canonical mapping already exists')
    indexed, sessions = {}, set()
    for identity, key, payload in rows['history_revisions']:
        envelope = json.loads(payload)
        meta = envelope['metadata']
        session = (meta['symbol'], meta['evaluation_date'])
        _require(session != (SYMBOL, date), 'Target revision already exists')
        _check(envelope, *session, identity)
        _require(key == ScannerHistoryStore.key(*session, meta['history_context']), 'Stored input key mismatch')
        _require(session not in sessions, 'Conflicting historical revisions')
        sessions.add(session)
        indexed[identity] = envelope
    for symbol, date, identity in rows['history_canonical']:
        _check(indexed[identity], symbol, date, identity)
    _require(set(indexed) == {r[2] for r in rows['history_canonical']}, 'Unmapped historical revision')


def _database():
    path = ROOT / 'stock_scanner/data/history_lookup/results.sqlite3'
    _require(path.is_file(), 'History database must already exist')
    _require(not Path(str(path) + '-wal').exists(), 'Active WAL requires a separate audit')
    return path


def _read_before(path, date=DATE):
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as connection:
        connection.execute('PRAGMA query_only=ON')
        connection.execute('BEGIN')
        rows = _snapshot(connection)
        _absent_and_valid(rows, date)
        _baseline(path, rows)
        return rows


def _load_inputs(expected_calculation, date=DATE):
    _target(SYMBOL, date)
    paths = {s: ROOT / f'stock_scanner/src/cache/{s}.parquet' for s in (SYMBOL, 'QQQ', 'SPY')}
    config_root = _config_root()
    config_path, universe_path = config_root / 'scanner.yaml', config_root / 'universe.yaml'
    raw = {p: p.read_bytes() for p in [config_path, universe_path, *paths.values()]}
    config, universe = yaml.safe_load(raw[config_path]), yaml.safe_load(raw[universe_path])
    # Validate universe configuration before relying on its category/benchmark metadata.
    # This prevents silent filtering of invalid symbol types (booleans, numbers, etc.)
    # that would cause incorrect category assignments and benchmark selections.
    validate_universe_yaml(universe, file_path=str(universe_path))
    _require(str(config.get('scanner_version')) == '1.2' and weekly_policy(config) == POLICY,
             'Root configuration must be V1.2 with the approved completed-week policy')
    _require(calculation_signature(config) == expected_calculation, 'Calculation fingerprint mismatch')
    cal = schedule(date, date)
    _require(len(cal) == 1 and cal.market_close.iloc[0] <= pd.Timestamp.now(tz='UTC'),
             'Target session is not completed')
    frames = {s: completed_daily(pd.read_parquet(io.BytesIO(raw[p])), date) for s, p in paths.items()}
    for symbol, frame in frames.items():
        _require(not frame.empty and frame.index[-1] == pd.Timestamp(date),
                 f'Missing exact-date input: {symbol}')
    hashes = {str(p): hashlib.sha256(data).hexdigest() for p, data in raw.items()}
    return config, universe, frames, hashes, {s: str(p) for s, p in paths.items()}


def _verify(envelope, context, identities, date=DATE):
    _require(envelope is not None and context is not None, 'No verified staged candidate')
    meta, _ = _check(envelope, SYMBOL, date, envelope['metadata']['revision_id'])
    _require(meta['scanner_version'] == '1.2' and meta['calculation_policy'] == POLICY,
             'Candidate policy mismatch')
    _require(meta['history_context'] == context, 'Candidate context mismatch')
    _require(meta['result_source'] == 'RECONSTRUCTED' and meta['data_source'] == 'local_adjusted_ohlcv',
             'Candidate provenance mismatch')
    _require(meta['data_cache_identity'] == identities, 'Candidate cache provenance mismatch')
    _require(meta['category_benchmark_symbol'] == 'QQQ' and meta['market_benchmark_symbol'] == 'SPY',
             'Candidate benchmark mismatch')


class _ContextReady(RuntimeError):
    """Exit lookup after its validators/fingerprints, before snapshot calculation."""


class _MemoryStage:
    """Duck-typed lookup store with no path, filesystem or database connection."""
    def __init__(self, expected_input, expected_calculation, identities, context_only=False, date=DATE):
        _target(SYMBOL, date)
        self.date = date
        self.expected_input, self.expected_calculation = expected_input, expected_calculation
        self.identities, self.context_only = identities, context_only
        self.context = self.envelope = self.input_key = None

    def key(self, symbol, date, context):
        _target(symbol, date)
        _require(date == self.date, 'Lookup substituted a different target date')
        _require(context['input_signature'] == self.expected_input, 'Input fingerprint mismatch')
        _require(context['calculation_signature'] == self.expected_calculation, 'Calculation fingerprint mismatch')
        _require(context['calculation_policy'] == POLICY and context['category_benchmark'] == 'QQQ'
                 and context['market_benchmark'] == 'SPY', 'Lookup policy/benchmark mismatch')
        self.context = deepcopy(context)
        self.input_key = ScannerHistoryStore.key(symbol, date, context)
        if self.context_only:
            raise _ContextReady()
        return self.input_key

    def get(self, key):
        _require(key == self.input_key, 'Unexpected lookup key')
        return None

    def put(self, key, envelope):
        _require(self.envelope is None and key == self.input_key, 'Only one candidate may be staged')
        _verify(envelope, self.context, self.identities, self.date)
        self.envelope = deepcopy(envelope)

    def canonical(self, symbol, date):
        _target(symbol, date)
        _require(date == self.date, 'Canonical request substituted a different target date')
        return deepcopy(self.envelope)

    def preserve_artifact(self, *args):
        raise PilotAbort('Artifact ingestion is forbidden')


def _stage(bundle, expected_input, expected_calculation, *, context_only=False, date=DATE):
    config, universe, frames, _, identities = bundle
    stage = _MemoryStage(expected_input, expected_calculation, identities, context_only, date)
    try:
        report = lookup_stock(SYMBOL, '1d', config, universe, as_of=date,
                              load_prices=lambda s: frames[s].copy(deep=True), store=stage,
                              report_dirs=(), data_cache_identity=identities)
    except _ContextReady:
        _require(context_only and stage.context is not None, 'Unexpected context-only exit')
        return stage
    _require(not context_only, 'Input/completed-week validation failed before fingerprinting')
    _require(report.symbol == SYMBOL and report.scanner_version == '1.2' and len(report.rows) == 1,
             'Unexpected lookup result identity')
    row = report.rows[0]
    _require(row['date'] == date and row['source'] == 'RECONSTRUCTED_VERIFIED'
             and not row.get('missing_reason') and row.get('reconciliation_status') == 'CANONICAL',
             'Exact-date lookup failed: ' + str(row.get('missing_reason', '')))
    _verify(stage.envelope, stage.context, identities, date)
    _require(row['revision_id'] == stage.envelope['metadata']['revision_id'], 'Lookup revision mismatch')
    return stage


def _post_insert(connection, before, revision, mapping):
    expected = {t: list(rows) for t, rows in before.items()}
    expected['history_revisions'].append(revision)
    expected['history_canonical'].append(mapping)
    _require(_snapshot(connection) == expected, 'Post-insert invariant failed')
    _check(json.loads(revision[2]), *mapping)


def _insert(path, before, stage, original_hashes, expected_input, expected_calculation):
    # Existing store.put uses its own connection and INSERT OR IGNORE. This narrow
    # adapter instead holds the absence check and both plain INSERTs in one lock.
    date = stage.date
    _target(SYMBOL, date)
    with closing(sqlite3.connect(path.as_uri() + '?mode=rw', uri=True, timeout=0)) as connection:
        try:
            connection.execute('BEGIN IMMEDIATE')
            current = _snapshot(connection)
            _absent_and_valid(current, date)
            _require(current == before, 'History changed while staging; audit again')
            _baseline(path, current)
            fresh = _load_inputs(expected_calculation, date=date)
            context = _stage(fresh, expected_input, expected_calculation, context_only=True, date=date).context
            _require(fresh[3] == original_hashes and context == stage.context, 'Inputs changed while staging')
            _verify(stage.envelope, context, fresh[4], date)
            _require(stage.input_key == ScannerHistoryStore.key(SYMBOL, date, context),
                     'Staged input key mismatch')
            identity = stage.envelope['metadata']['revision_id']
            revision = (identity, stage.input_key, json.dumps(stage.envelope, sort_keys=True, allow_nan=False))
            mapping = (SYMBOL, date, identity)
            connection.execute('INSERT INTO history_revisions (revision_id,input_key,payload) VALUES (?,?,?)', revision)
            connection.execute('INSERT INTO history_canonical (symbol,evaluation_date,revision_id) VALUES (?,?,?)', mapping)
            _post_insert(connection, before, revision, mapping)
            connection.commit()
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise


def run_pilot(symbol, date, *, expected_input, expected_calculation, apply=False):
    """Stage by default. An authorized future caller must explicitly request apply."""
    _target(symbol, date)
    _require(type(apply) is bool, 'Apply must be an explicit boolean')
    planned_input = PLANNED_INPUT if date == DATE else ADDITIONAL_INPUTS[date]
    _require(expected_input == planned_input, 'Expected input differs from the approved plan')
    _require(expected_calculation == PLANNED_CALCULATION, 'Expected calculation differs from the approved plan')
    _config_root()
    path = _database()
    before = _read_before(path, date)
    bundle = _load_inputs(expected_calculation, date=date)
    stage = _stage(bundle, expected_input, expected_calculation, date=date)
    if apply:
        _insert(path, before, stage, bundle[3], expected_input, expected_calculation)
    return {'applied': bool(apply), 'metadata': deepcopy(stage.envelope['metadata']),
            'before_counts': {t: len(rows) for t, rows in before.items()},
            'inserted': {'history_revisions': int(bool(apply)), 'history_canonical': int(bool(apply))}}


class _Once(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        if getattr(namespace, self.dest, None) is not None:
            parser.error(f'Duplicate option {option_string}; one candidate per invocation')
        setattr(namespace, self.dest, values)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--symbol', required=True, choices=[SYMBOL], action=_Once)
    parser.add_argument('--date', required=True, choices=[DATE, *ADDITIONAL_INPUTS], action=_Once)
    parser.add_argument('--expected-input', required=True, action=_Once)
    parser.add_argument('--expected-calculation', required=True, action=_Once)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args(argv)
    try:
        receipt = run_pilot(args.symbol, args.date, expected_input=args.expected_input,
                            expected_calculation=args.expected_calculation, apply=args.apply)
    except (PilotAbort, OSError, sqlite3.Error, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f'Pilot stopped: {exc}. Inspect state; do not retry automatically.\n')
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
