"""Content-addressed historical results; never a price source or trading engine."""
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def calculation_signature(config):
    """Include actual implementation/configuration, not only the version label."""
    digest = hashlib.sha256(json.dumps(config, sort_keys=True).encode())
    files = []
    for folder in ('analysis', 'scoring', 'indicators'):
        files.extend((PROJECT_ROOT / 'src' / folder).glob('*.py'))
    files.extend(PROJECT_ROOT / 'src/data' / name for name in ('market_calendar.py', 'yfinance_loader.py'))
    for path in sorted(files):
        digest.update(path.relative_to(PROJECT_ROOT).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def input_signature(symbol, category, category_benchmark, market_benchmark, *frames):
    digest = hashlib.sha256(json.dumps([symbol, category, category_benchmark, market_benchmark]).encode())
    for frame in frames:
        if frame is None:
            digest.update(b'none')
            continue
        canonical = frame[['Open', 'High', 'Low', 'Close', 'Volume']].astype('float64').copy()
        # Daily timestamps from the loader may carry a UTC offset in a naive index.
        canonical.index = pd.DatetimeIndex(canonical.index).tz_localize(None).normalize()
        digest.update(str(canonical.shape).encode())
        digest.update(pd.util.hash_pandas_object(canonical, index=True).values.tobytes())
    return digest.hexdigest()


def weekly_policy(config, *, historical=True):
    if str(config.get('scanner_version', '1.2')) in ('1.1', '1.2'):
        return 'w-fri-drop-partial-v1' if historical else 'w-fri-live-partial-v1'
    return 'nyse-completed-weeks-v1'


def history_context(config_signature, symbol, category, category_benchmark, market_benchmark, *frames,
                    calculation_policy=None):
    return {'calculation_signature': config_signature,
            'input_signature': input_signature(symbol, category, category_benchmark, market_benchmark, *frames),
            'category_benchmark': category_benchmark, 'market_benchmark': market_benchmark,
            'calculation_policy': calculation_policy,
            'frame_fingerprints': {
                name: input_signature(symbol, category, category_benchmark, market_benchmark, frame)
                for name, frame in zip(('daily', 'weekly', 'category_benchmark', 'market_benchmark'), frames)}}


SNAPSHOT_FIELDS = (
    'state', 'candidate_score', 'trend_score', 'entry_quality', 'bottom_score', 'reversal_score',
    'market_regime', 'market_regime_score', 'trend_score_breakdown', 'bottom_score_breakdown',
    'reversal_score_breakdown', 'entry_quality_details', 'candidate_score_breakdown',
    'daily', 'weekly', 'relative_strength', 'structure',
)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def result_fingerprint(record):
    """Fingerprint the complete deterministic snapshot, excluding live-only annotations."""
    return _digest({key: record[key] for key in SNAPSHOT_FIELDS})


def revision_id(envelope):
    metadata = envelope['metadata']
    # Time and file location are observations, not calculation identity.
    return _digest({
        'identity': {key: metadata[key] for key in (
            'symbol', 'evaluation_date', 'scanner_version', 'calculation_policy',
            'input_fingerprint', 'calculation_fingerprint', 'reconstruction_status')},
        'result': envelope['result'],
    })


def result_envelope(symbol, date, version, context, result, source, data_identity, daily_change):
    metadata = {
        'schema_version': 2, 'symbol': symbol, 'evaluation_date': date,
        'scanner_version': version, 'calculation_policy': context['calculation_policy'],
        'result_source': source, 'reconstruction_status': 'VERIFIED',
        'data_source': 'local_adjusted_ohlcv', 'data_cache_identity': data_identity,
        'category_benchmark_symbol': context['category_benchmark'],
        'market_benchmark_symbol': context['market_benchmark'],
        'input_fingerprint': context['input_signature'],
        'calculation_fingerprint': context['calculation_signature'],
        'frame_fingerprints': context['frame_fingerprints'],
        'result_fingerprint': result_fingerprint(result),
        'history_context': context, 'daily_change_pct': daily_change,
        'generated_at': datetime.now(timezone.utc).isoformat(),
    }
    envelope = {'metadata': metadata,
                'result': {**{key: result[key] for key in SNAPSHOT_FIELDS}, 'scanner_version': version}}
    metadata['revision_id'] = revision_id(envelope)
    return envelope


class ScannerHistoryStore:
    """Append-only revisions and a first-established canonical result per symbol/date.

    The pre-integrity `results` table is deliberately left intact but never trusted.
    There is no implicit promotion of a different input or result revision.
    """
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else PROJECT_ROOT / 'data/history_lookup/results.sqlite3'

    @staticmethod
    def key(symbol, date, context):
        payload = ['lookup-v2', symbol, date, context]
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def get(self, key):
        if not self.path.exists():
            return None
        with sqlite3.connect(self.path) as connection:
            try:
                row = connection.execute(
                    'SELECT payload FROM history_revisions WHERE input_key = ? ORDER BY rowid LIMIT 1',
                    (key,)).fetchone()
            except sqlite3.OperationalError:
                return None
        payload = json.loads(row[0]) if row else None
        return self._checked(payload)

    @staticmethod
    def _checked(payload):
        if payload is None:
            return None
        if (payload['metadata']['revision_id'] != revision_id(payload)
                or payload['metadata']['result_fingerprint'] != result_fingerprint(payload['result'])):
            raise ValueError('Historical revision integrity check failed.')
        return payload

    def canonical(self, symbol, date):
        if not self.path.exists():
            return None
        with sqlite3.connect(self.path) as connection:
            try:
                row = connection.execute(
                    'SELECT r.payload FROM history_canonical c JOIN history_revisions r '
                    'ON r.revision_id = c.revision_id WHERE c.symbol = ? AND c.evaluation_date = ?',
                    (symbol, date)).fetchone()
            except sqlite3.OperationalError:
                return None
        return self._checked(json.loads(row[0])) if row else None

    def put(self, key, record):
        self._checked(record)
        metadata = record['metadata']
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute('CREATE TABLE IF NOT EXISTS history_revisions '
                               '(revision_id TEXT PRIMARY KEY, input_key TEXT NOT NULL, payload TEXT NOT NULL)')
            connection.execute('CREATE INDEX IF NOT EXISTS history_inputs ON history_revisions(input_key)')
            connection.execute('CREATE TABLE IF NOT EXISTS history_canonical '
                               '(symbol TEXT, evaluation_date TEXT, revision_id TEXT NOT NULL, '
                               'PRIMARY KEY(symbol, evaluation_date))')
            connection.execute('INSERT OR IGNORE INTO history_revisions VALUES (?, ?, ?)',
                               (metadata['revision_id'], key, json.dumps(record, sort_keys=True, allow_nan=False)))
            connection.execute('INSERT OR IGNORE INTO history_canonical VALUES (?, ?, ?)',
                               (metadata['symbol'], metadata['evaluation_date'], metadata['revision_id']))

    def preserve_artifact(self, record, path):
        """Keep unverified originals even if the date-based JSON is later replaced."""
        artifact = {'result': record, 'source_path': str(path), 'status': 'RECORDED_LEGACY / UNVERIFIED'}
        identity = _digest(artifact)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute('CREATE TABLE IF NOT EXISTS history_artifacts '
                               '(artifact_id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
            connection.execute('INSERT OR IGNORE INTO history_artifacts VALUES (?, ?)',
                               (identity, json.dumps(artifact, sort_keys=True, allow_nan=False)))
        return identity


def recorded_snapshots(symbol, date, directories):
    """Read dated artifacts without claiming they are point-in-time verified."""
    found = []
    for directory in directories:
        path = Path(directory) / f'{date}.json'
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding='utf-8'))
            records = payload.get('results', [])
            for record in records:
                if record.get('symbol') != symbol or record.get('data_date') != date:
                    continue
                found.append((record, path))
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return found


def compatible_record(record, context, version):
    """Require explicit policy, exact inputs/code, and an intact full-result stamp."""
    try:
        return (bool(context['calculation_policy'])
                and record.get('history_context') == context
                and str(record.get('scanner_version')) == version
                and record.get('data_status', 'OK') == 'OK'
                and record.get('history_result_fingerprint') == result_fingerprint(record))
    except (KeyError, TypeError, ValueError):
        return False
