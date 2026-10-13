"""Read-only view of the existing lookup canonical store; never reconstructs."""
from collections import defaultdict
from contextlib import closing
import json
import math
from pathlib import Path
import sqlite3

from stock_scanner.src.data.scanner_history import PROJECT_ROOT, ScannerHistoryStore
from stock_scanner.src.reporting.state_breakdown import STATE_ORDER

DEFAULT_STORE = PROJECT_ROOT / 'data/history_lookup/results.sqlite3'


def number(value, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) and (not positive or value > 0) else None


def _check(envelope, symbol, date, identity):
    ScannerHistoryStore._checked(envelope)
    meta, result = envelope['metadata'], envelope['result']
    if (meta['symbol'], meta['evaluation_date'], meta['revision_id']) != (symbol, date, identity):
        raise ValueError('Canonical mapping and revision identity disagree')
    if meta.get('reconstruction_status') != 'VERIFIED' or meta.get('result_source') not in ('RECORDED', 'RECONSTRUCTED'):
        raise ValueError('RECORDED_LEGACY / UNVERIFIED or unsupported provenance')
    if meta.get('calculation_policy') not in ('w-fri-drop-partial-v1', 'nyse-completed-weeks-v1'):
        raise ValueError('Unverified completed-session calculation policy')
    context = meta['history_context']
    for field, key in [('calculation_fingerprint', 'calculation_signature'),
                       ('input_fingerprint', 'input_signature'),
                       ('calculation_policy', 'calculation_policy'),
                       ('frame_fingerprints', 'frame_fingerprints')]:
        if not meta.get(field) or meta[field] != context.get(key):
            raise ValueError('Incomplete or inconsistent provenance')
    if result.get('scanner_version') != meta.get('scanner_version'):
        raise ValueError('Scanner version mismatch')
    if result.get('state') not in STATE_ORDER:
        raise ValueError('Unknown or missing scanner state')
    for item in (envelope, meta, result):
        if item.get('reconciliation_status', 'CANONICAL') != 'CANONICAL':
            raise ValueError('RECONCILIATION_REQUIRED')
        if item.get('conflict') or item.get('reconciliation_required'):
            raise ValueError('RECONCILIATION_REQUIRED')
        if set(item.get('observed_revision_ids', [])) - {identity}:
            raise ValueError('RECONCILIATION_REQUIRED')
    return meta, result


def read_history(path, through):
    """Read a consistent SQLite snapshot using mode=ro and existing hash checks.

    All established revisions for a symbol/date are inspected for ambiguity.
    Legacy artifacts/flat results are counted but never supply usable states.
    No input-price access, store creation, migration, or reconciliation occurs.
    """
    path = Path(path).resolve()
    report = dict(path=str(path), observations=[], issues=[], legacy_counts={},
                  source_status='AVAILABLE')
    if not path.is_file():
        report.update(source_status='MISSING', issues=['Canonical history store is missing; no store was created.'])
        return report
    try:
        # Avoid creating WAL shared-memory sidecars on a read-only query.
        if Path(str(path) + '-wal').exists() and not Path(str(path) + '-shm').exists():
            raise ValueError('WAL store has no existing shared-memory file; read withheld to avoid creating one')
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as connection:
            connection.execute('PRAGMA query_only=ON')
            connection.execute('BEGIN')
            tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table in ('results', 'history_artifacts'):
                if table in tables:
                    report['legacy_counts'][table] = connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
            if not {'history_canonical', 'history_revisions'} <= tables:
                report.update(source_status='UNVERIFIED_ONLY', issues=['No canonical revision tables; legacy rows are not eligible.'])
                return report
            canonical = connection.execute(
                'SELECT symbol, evaluation_date, revision_id FROM history_canonical '
                'WHERE evaluation_date <= ? ORDER BY symbol, evaluation_date, revision_id', (through,)).fetchall()
            revisions = connection.execute('SELECT revision_id, payload FROM history_revisions').fetchall()
        indexed, by_session = {}, defaultdict(set)
        for identity, payload in revisions:
            try:
                envelope = json.loads(payload)
                meta = envelope['metadata']
                key = (meta['symbol'], meta['evaluation_date'])
                if key[1] <= through:
                    by_session[key].add(identity)
                indexed[identity] = envelope
            except (TypeError, ValueError, KeyError):
                # Unknown identity cannot safely be assigned to a particular session.
                report['issues'].append(f'Malformed stored revision: {identity}')
                indexed[identity] = None
        mappings = defaultdict(set)
        for symbol, date, identity in canonical:
            mappings[(symbol, date)].add(identity)
        for (symbol, date), identities in sorted(mappings.items()):
            row = dict(symbol=symbol, date=date, eligible=False, state=None,
                       candidate_score=None, close=None, reason=None)
            try:
                if len(identities) != 1 or by_session[(symbol, date)] - identities:
                    raise ValueError('RECONCILIATION_REQUIRED: distinct stored revisions for this session')
                identity = next(iter(identities))
                envelope = indexed.get(identity)
                if envelope is None:
                    raise ValueError('Missing or malformed canonical revision')
                meta, result = _check(envelope, symbol, date, identity)
                row.update(eligible=True, state=result['state'],
                           candidate_score=number(result.get('candidate_score')),
                           close=number(result.get('daily', {}).get('close'), positive=True),
                           provenance=meta, revision_id=identity,
                           source=meta['result_source'] + '_VERIFIED',
                           verification_status='VERIFIED', reconciliation_status='CANONICAL',
                           policy_identity=[meta['scanner_version'], meta['calculation_policy'], meta['calculation_fingerprint']])
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                row['reason'] = str(exc)
            report['observations'].append(row)
        if report['issues']:
            # Malformed revisions could hide a conflict; fail closed for the query.
            for row in report['observations']:
                row.update(eligible=False, reason='Store integrity incomplete: malformed revision present')
            report['source_status'] = 'INTEGRITY_ERROR'
    except (OSError, sqlite3.Error, ValueError) as exc:
        report.update(source_status='UNAVAILABLE', observations=[], issues=[str(exc)])
    return report
