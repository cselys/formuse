"""Exact daily-state patterns over already established canonical observations."""
from collections import defaultdict
from datetime import datetime, timezone

import pandas as pd

from stock_scanner.src.data.market_calendar import cutoff_timestamp, schedule
from stock_scanner.src.historical.pattern_source import DEFAULT_STORE, number, read_history
from stock_scanner.src.reporting.state_breakdown import STATE_ORDER


def validate_options(states=None, *, auto=False, recent_days=10, max_states=3,
                     max_span_days=20, min_occurrences=1, limit=100):
    if bool(states) == bool(auto):
        raise ValueError('Choose exactly one of --states or --auto.')
    for name, value, low, high in [('recent-days', recent_days, 1, 5000),
                                  ('max-states', max_states, 2, 3),
                                  ('max-span-days', max_span_days, 1, 20),
                                  ('min-occurrences', min_occurrences, 1, 1000000),
                                  ('limit', limit, 1, 1000000)]:
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise ValueError(f'--{name} must be an integer from {low} to {high}.')
    pattern = tuple(s.strip().upper() for s in states.split(',')) if isinstance(states, str) else tuple(states or ())
    if not auto:
        if not 2 <= len(pattern) <= max_states:
            raise ValueError('Explicit patterns require 2 or 3 daily states, within --max-states.')
        unknown = set(pattern) - set(STATE_ORDER)
        if unknown:
            raise ValueError(f'Invalid states: {", ".join(sorted(unknown))}. Valid states: {", ".join(STATE_ORDER)}')
        if len(pattern) > max_span_days:
            raise ValueError('Pattern length exceeds --max-span-days; each state occupies one session.')
    elif max_span_days < 2:
        raise ValueError('Automatic discovery needs --max-span-days of at least 2.')
    return pattern


def completed_sessions(as_of, count):
    cutoff = cutoff_timestamp(as_of)
    if pd.isna(cutoff):
        raise ValueError('Invalid as-of timestamp')
    # Calendar-day padding only obtains a calendar range; all counting uses its sessions.
    days = max(40, count * 2 + 30)
    while True:
        cal = schedule(str((cutoff - pd.Timedelta(days=days)).date()), str(cutoff.date()))
        eligible = cal.index[cal.market_close <= cutoff]
        if len(eligible) >= count:
            return cutoff, [str(day.date()) for day in eligible[-count:]]
        days *= 2


def configured_memberships(universe):
    memberships, excluded, issues = defaultdict(set), set(), []
    for field in ('market_benchmarks', 'etf_symbols'):
        excluded.update(s.strip().upper() for s in universe.get(field, []) if isinstance(s, str))
    excluded.update(s.strip().upper() for s in universe.get('sector_indexes', {}).values() if isinstance(s, str))
    for name, category in universe.get('categories', {}).items():
        benchmark = category.get('benchmark')
        if isinstance(benchmark, str):
            excluded.add(benchmark.strip().upper())
        for symbol in category.get('symbols', []):
            if not isinstance(symbol, str) or not symbol.strip():
                issues.append(f'{name}: invalid configured symbol {symbol!r}; ignored for category labels.')
                continue
            symbol = symbol.strip().upper()
            memberships[symbol].add(name)
            if str(category.get('instrument_type', '')).lower() in ('index', 'etf'):
                excluded.add(symbol)
    return {s: sorted(names) for s, names in memberships.items()}, excluded, issues


def find_patterns(universe, *, states=None, auto=False, recent_days=10, max_states=3,
                  max_span_days=20, min_occurrences=1, limit=100, as_of=None,
                  store_path=DEFAULT_STORE):
    pattern = validate_options(states, auto=auto, recent_days=recent_days, max_states=max_states,
                               max_span_days=max_span_days, min_occurrences=min_occurrences, limit=limit)
    lengths = list(range(2, min(max_states, max_span_days) + 1)) if auto else [len(pattern)]
    cutoff, sessions = completed_sessions(as_of, recent_days + max(lengths) - 1)
    recent = sessions[-recent_days:]
    source = read_history(store_path, recent[-1])
    memberships, excluded, issues = configured_memberships(universe)
    issues.extend(source['issues'])
    by_symbol = defaultdict(dict)
    for row in source['observations']:
        if row['symbol'] not in excluded:
            by_symbol[row['symbol']][row['date']] = row
    matches, coverage = [], []
    usable_windows = 0
    policy_breaks = 0
    for symbol in sorted(set(by_symbol) | (set(memberships) - excluded)):
        daily = by_symbol[symbol]
        eligible_count = sum(bool(daily.get(d, {}).get('eligible')) for d in sessions)
        coverage.append(dict(symbol=symbol, categories=memberships.get(symbol, []),
                             eligible_sessions=eligible_count, requested_sessions=len(sessions),
                             missing_or_excluded_sessions=[d for d in sessions if not daily.get(d, {}).get('eligible')]))
        latest = daily[max(daily)] if daily else {}
        for end in range(len(sessions) - recent_days, len(sessions)):
            for length in lengths:
                dates = sessions[end - length + 1:end + 1]
                if len(dates) != length:
                    continue
                rows = [daily.get(d) for d in dates]
                if any(not row or not row['eligible'] for row in rows):
                    continue
                # Do not splice a change of scanner policy/config/code into a state pattern.
                if any(row['policy_identity'] != rows[0]['policy_identity'] for row in rows):
                    policy_breaks += 1
                    continue
                usable_windows += 1
                sequence = tuple(row['state'] for row in rows)
                if not auto and sequence != pattern:
                    continue
                start_price, end_price = rows[0]['close'], rows[-1]['close']
                change = number((end_price / start_price - 1) * 100) if start_price and end_price else None
                matches.append(dict(symbol=symbol, categories=memberships.get(symbol, []),
                                    states=list(sequence), start_date=dates[0], end_date=dates[-1],
                                    sessions=length, start_price=start_price, end_price=end_price,
                                    price_change_pct=change, final_within_recent_window=True,
                                    latest_recorded_date=latest.get('date'),
                                    latest_recorded_state=latest.get('state') if latest.get('eligible') else None,
                                    latest_candidate_score=latest.get('candidate_score') if latest.get('eligible') else None,
                                    latest_record_status=latest.get('source') if latest.get('eligible') else latest.get('reason'),
                                    verification_status='VERIFIED', reconciliation_status='CANONICAL',
                                    observations=[dict(date=row['date'], state=row['state'], source=row['source'],
                                                       revision_id=row['revision_id'], provenance=row['provenance']) for row in rows]))
    matches.sort(key=lambda r: (r['end_date'], r['symbol'], r['states']))
    # Dates descending; deterministic alphabetical symbol/sequence tie breaks.
    matches.sort(key=lambda r: r['end_date'], reverse=True)
    groups = defaultdict(list)
    for match in matches:
        groups[tuple(match['states'])].append(match)
    patterns = [dict(states=list(sequence), occurrences=len(rows),
                     distinct_symbols=len({r['symbol'] for r in rows}), most_recent_date=max(r['end_date'] for r in rows),
                     examples=[dict(symbol=r['symbol'], start_date=r['start_date'], end_date=r['end_date']) for r in rows[:5]])
                for sequence, rows in sorted(groups.items()) if len(rows) >= min_occurrences]
    patterns.sort(key=lambda r: r['most_recent_date'], reverse=True)
    patterns.sort(key=lambda r: (-r['occurrences'], -r['distinct_symbols']))
    status = 'MATCHES_FOUND' if (patterns if auto else matches) else ('NO_MATCHES' if usable_windows else 'INSUFFICIENT_HISTORY')
    if auto and matches and not patterns:
        status = 'NO_PATTERNS_MEET_THRESHOLD'
    excluded_rows = [dict(symbol=r['symbol'], date=r['date'], reason=r['reason'])
                     for r in source['observations'] if not r['eligible'] and r['date'] in sessions]
    messages = [
        'Each state occupies exactly one consecutive completed NYSE session; repeated states are retained, not compressed. Gaps break continuity.',
        'The final state must lie in the recent completed-session window anchored to as-of, never to the last stored observation.',
        'Only existing fingerprint-checked canonical revisions are eligible. Unverified artifacts and conflicting revisions are excluded; no reconstruction is performed.',
        'VERIFIED means reproducible under the stored adjusted-price policy, not proof of the original provider vintage or availability on that date.',
        'As-of limits evaluation dates. This queries today\'s established canonical store, not a historical snapshot of what the store contained at that time.',
        'Latest recorded fields refer to the latest canonical session through as-of, not necessarily the pattern end. An invalid latest row does not fall back to an older score.',
        'Categories are current YAML memberships, not reconstructed historical memberships. Stored symbols outside that universe remain searchable with no category.',
        'Occurrence counts are overlapping daily windows, not independent samples or distinct-stock counts. Frequency does not establish profitability or predictive value.',
        'Forward returns are unavailable here: the canonical history source has no linked outcome fields. No future prices or prospective validation records are read.',
        'Missing fields are N/A (JSON null); report limits do not alter occurrence counts.',
    ]
    if any(r['missing_or_excluded_sessions'] for r in coverage):
        messages.append('Coverage is incomplete. No match only means no match in evaluable windows; it is not evidence of absence in missing history.')
    return dict(schema_version=1, generated_at=datetime.now(timezone.utc).isoformat(), mode='auto' if auto else 'explicit',
                status=status, as_of=cutoff.isoformat(), recent_start=recent[0], recent_end=recent[-1],
                scan_start=sessions[0], recent_sessions=recent, options=dict(states=list(pattern), recent_days=recent_days,
                    max_states=max_states, max_span_days=max_span_days, min_occurrences=min_occurrences, limit=limit),
                source=dict(path=source['path'], status=source['source_status'], legacy_counts=source['legacy_counts']),
                usable_windows=usable_windows, policy_breaks=policy_breaks,
                total_occurrences=len(matches), total_patterns=len(patterns),
                matches=matches if auto else matches[:limit], patterns=patterns[:limit] if auto else [],
                coverage=coverage, excluded_observations=excluded_rows, issues=issues, messages=messages)
