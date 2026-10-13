"""Local-only, point-in-time historical scanner lookup."""
from dataclasses import dataclass
import logging
import math
import re
import sqlite3

import numpy as np
import pandas as pd

from stock_scanner.src.analysis.snapshot import analyze_snapshot
from stock_scanner.src.data.historical_cache import load_cached_data
from stock_scanner.src.data.market_calendar import completed_daily, completed_weekly, cutoff_timestamp, schedule, uses_completed_weeks, week_context
from stock_scanner.src.data.yfinance_loader import YFinanceLoader
from stock_scanner.src.data.scanner_history import (
    PROJECT_ROOT, ScannerHistoryStore, calculation_signature, history_context, recorded_snapshots,
    compatible_record, result_envelope, weekly_policy,
)
from stock_scanner.src.validation.universe_validator import validate_universe_yaml

logger = logging.getLogger('stock_scanner.lookup')


def normalize_symbol(value):
    symbol = value.strip().upper()
    if not re.fullmatch(r'[A-Z][A-Z0-9]*(?:[.-][A-Z0-9]+)?', symbol) or len(symbol) > 15:
        raise ValueError('Use a stock symbol such as NVDA, AAPL or BRK-B (letters, numbers, dot or hyphen).')
    if symbol in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}:
        raise ValueError('That symbol is a reserved filename; use a valid stock symbol.')
    return symbol


def parse_period(value):
    match = re.fullmatch(r'([1-9][0-9]*)d', value.strip().lower())
    if not match or int(match[1]) > 5000:
        raise ValueError('Period must be 1d–5000d, counted in trading sessions (for example 5d, 10d, 20d).')
    return int(match[1])


@dataclass
class StockHistory:
    symbol: str
    requested_sessions: int
    rows: list
    messages: list
    scanner_version: str

    @property
    def through(self):
        return self.rows[0]['date'] if self.rows else None

    @property
    def start(self):
        return self.rows[-1]['date'] if self.rows else None


def _finite(value):
    return isinstance(value, (int, float, np.number)) and math.isfinite(value)


def _price(frame, date):
    if date not in frame.index or 'Close' not in frame:
        return None
    value = frame.loc[date, 'Close']
    return float(value) if _finite(value) and value > 0 else None


def _empty_row(date, close, daily_change):
    return {'date': str(date.date()), 'close': close, 'daily_change_pct': daily_change,
            **dict.fromkeys(['state', 'candidate_score', 'trend_score', 'entry_quality', 'bottom_score',
                            'reversal_score', 'rs_20d', 'rs_60d', 'rsi', 'market_regime', 'signal_tier']),
            'source': 'MISSING', 'missing_reason': '', 'previous_state': None, 'transition': None}


def _apply_snapshot(row, record, source):
    for key in ('state', 'candidate_score', 'trend_score', 'entry_quality', 'bottom_score',
                'reversal_score', 'market_regime', 'signal_tier'):
        row[key] = record.get(key)
    row['rsi'] = record.get('daily', {}).get('rsi')
    for key in ('rs_20d', 'rs_60d'):
        row[key] = record.get('relative_strength', {}).get(key)
    row['source'] = source
    row['scanner_version'] = record.get('scanner_version')
    for key, value in row.items():
        if isinstance(value, (float, np.number)) and not _finite(value):
            row[key] = None


def _validate_inputs(stock, benchmark, market, day):
    if len(stock) < 100:
        return 'Insufficient stock history: at least 100 prior/current bars are required, as in walk-forward evaluation.'
    for label, frame, minimum in [('stock', stock, 100), ('category benchmark', benchmark, 61), ('market benchmark', market, 50)]:
        if frame is None or len(frame) < minimum or frame.index[-1] != day:
            return f'Missing or insufficient {label} history through this session.'
        columns = ['Open', 'High', 'Low', 'Close', 'Volume']
        if any(c not in frame for c in columns):
            return f'Missing OHLCV columns in {label} cache.'
        values = frame[columns].to_numpy(dtype=float)
        if not np.isfinite(values).all() or (values[:, :4] <= 0).any() or (values[:, 4] < 0).any():
            return f'Invalid OHLCV values in {label} history.'
        if ((frame.High < frame[['Open', 'Close', 'Low']].max(axis=1)) |
                (frame.Low > frame[['Open', 'Close', 'High']].min(axis=1))).any():
            return f'Inconsistent OHLC prices in {label} history.'
        expected = schedule(str(frame.index[0].date()), str(day.date())).index
        if not expected.isin(frame.index).all():
            return f'Missing price sessions in {label} history; reconstruction withheld.'
    if len(stock.index.intersection(benchmark.index)) < 61:
        return 'Fewer than 61 aligned stock/category benchmark sessions for relative strength.'
    return None


def lookup_stock(symbol, period, config, universe, *, as_of=None, load_prices=None, store=None,
                 report_dirs=None, data_cache_identity=None):
    symbol = normalize_symbol(symbol)
    count = parse_period(period)
    loader = load_prices or load_cached_data
    store = store if store is not None else ScannerHistoryStore()
    directories = report_dirs if report_dirs is not None else [PROJECT_ROOT / 'data/reports']
    cutoff = cutoff_timestamp(as_of)
    messages = []
    version = str(config.get('scanner_version', '1.2'))
    # Validate universe configuration before using it for category/benchmark lookup.
    # This prevents silent filtering of invalid symbol types (booleans, numbers, etc.)
    # that would otherwise cause the symbol to fall back to "custom-symbol SPY benchmark"
    # as if the universe were valid when it is not.
    validate_universe_yaml(universe, file_path=getattr(config, '__file__', None) or 'config/universe.yaml')
    category, benchmark_symbol = 'custom', 'SPY'
    found = False
    for name, details in universe.get('categories', {}).items():
        if symbol in {s.strip().upper() for s in details.get('symbols', []) if isinstance(s, str)}:
            category, benchmark_symbol, found = name, details.get('benchmark', 'QQQ').strip().upper(), True
    if not found:
        messages.append('Symbol is outside the configured universe; using the scanner custom-symbol SPY benchmark.')
    frames = {}
    for name in dict.fromkeys([symbol, benchmark_symbol, 'SPY', 'QQQ']):
        try:
            frames[name] = completed_daily(loader(name), cutoff)
        except (OSError, ValueError, TypeError, KeyError):
            frames[name] = pd.DataFrame()
            messages.append(f'Unable to read valid local data for {name}.')
    stock = frames[symbol]
    if stock.empty or 'Close' not in stock:
        messages.append(f'No local completed daily price cache for {symbol}. Run a normal scan with --symbol {symbol} first; lookup never downloads data.')
        return StockHistory(symbol, count, [], messages, version)
    valid_dates = [date for date in stock.index if _price(stock, date) is not None]
    if not valid_dates:
        messages.append('No valid completed closing prices in the local cache.')
        return StockHistory(symbol, count, [], messages, version)
    latest = valid_dates[-1]
    dates = schedule(str(stock.index[0].date()), str(latest.date())).index[-count:]
    if len(dates) < count:
        messages.append(f'Only {len(dates)} trading sessions are covered by the local cache; {count} requested.')
    current = week_context(cutoff)['latest_session']
    if str(latest.date()) < current:
        messages.append(f'Local cache ends {latest.date()}; latest completed exchange session is {current}. No download was performed.')
    signature = calculation_signature(config)
    rows = []
    sessions = schedule(str(stock.index[0].date()), str(latest.date())).index
    positions = {date: i for i, date in enumerate(sessions)}
    for day in dates:
        close = _price(stock, day)
        position = positions[day]
        prior_close = _price(stock, sessions[position - 1]) if position else None
        change = (close / prior_close - 1) * 100 if close is not None and prior_close else None
        row = _empty_row(day, close, change)
        rows.append(row)
        if close is None:
            row['missing_reason'] = 'Missing/invalid daily close for this trading session.'
            continue
        date = str(day.date())
        artifacts = recorded_snapshots(symbol, date, directories)
        row['legacy_artifacts'] = []
        daily = stock.loc[:day]
        benchmark = frames[benchmark_symbol].loc[:day]
        # Availability must be decided at T, not at the end of the lookup window.
        market_symbol = 'SPY' if not frames['SPY'].loc[:day].empty else 'QQQ'
        market = frames[market_symbol].loc[:day]
        context = None
        try:
            reason = _validate_inputs(daily, benchmark, market, day)
            if reason:
                row['missing_reason'] = reason
                continue
            weekly = (completed_weekly(daily, date) if uses_completed_weeks(config)
                      else YFinanceLoader().resample_to_weekly(daily, as_of_date=date, drop_partial=True))
            if len(weekly) < 10:
                row['missing_reason'] = 'Insufficient completed weekly history (10 bars required).'
                continue
            context = history_context(signature, symbol, category, benchmark_symbol, market_symbol,
                                      daily, weekly, benchmark, market,
                                      calculation_policy=weekly_policy(config))
            cache_key = store.key(symbol, date, context)
            # Never trust pre-integrity flat cache records or overwrite a pinned revision.
            envelope = store.get(cache_key)
            identity = data_cache_identity or {
                name: str(PROJECT_ROOT / 'src/cache' / f'{name}.parquet') if load_prices is None
                else f'injected_loader:{name}'
                for name in dict.fromkeys((symbol, benchmark_symbol, market_symbol))}
            candidates = []
            for record, path in artifacts:
                if compatible_record(record, context, version):
                    saved = result_envelope(symbol, date, version, context, record, 'RECORDED', identity, change)
                    saved['metadata']['recorded_source_path'] = str(path)
                    candidates.append(saved)
            if envelope is None:
                envelope = candidates[0] if candidates else result_envelope(
                    symbol, date, version, context, analyze_snapshot(daily, weekly, benchmark, market, config),
                    'RECONSTRUCTED', identity, change)
                store.put(cache_key, envelope)
            for candidate in candidates:
                store.put(cache_key, candidate)
            canonical = store.canonical(symbol, date)
            observed = {item['metadata']['revision_id'] for item in [envelope, *candidates]}
            conflict = bool(observed - {canonical['metadata']['revision_id']})
            metadata = canonical['metadata']
            _apply_snapshot(row, canonical['result'], metadata['result_source'] + '_VERIFIED')
            row.update(provenance=metadata, calculation_policy=metadata['calculation_policy'],
                       market_benchmark=metadata['market_benchmark_symbol'], revision_id=metadata['revision_id'],
                       reconciliation_status='RECONCILIATION_REQUIRED' if conflict else 'CANONICAL',
                       observed_revision_ids=sorted(observed))
            # Do not mix a pinned score with newly revised prices in the same row.
            row['close'] = canonical['result']['daily']['close']
            row['daily_change_pct'] = metadata['daily_change_pct']
            if conflict:
                messages.append(f'{date}: RECONCILIATION_REQUIRED. Retaining canonical revision '
                                f'{metadata["revision_id"]}; different observed revisions were preserved.')
        except (OSError, sqlite3.Error, ValueError, TypeError, KeyError, IndexError) as exc:
            logger.warning('Cannot reconstruct %s on %s: %s', symbol, day.date(), exc)
            row['missing_reason'] = 'Verified result unavailable; check local inputs/configuration and revision-store integrity.'
        finally:
            # Artifacts remain separate even when verified reconstruction is unavailable.
            for record, path in artifacts:
                if context is not None and compatible_record(record, context, version):
                    continue
                artifact = {'source': 'RECORDED_LEGACY', 'status': 'UNVERIFIED',
                            'source_path': str(path), 'result': record}
                try:
                    artifact['artifact_id'] = store.preserve_artifact(record, path)
                except (OSError, sqlite3.Error, TypeError, ValueError):
                    messages.append(f'{date}: could not persist an unverified archive artifact; original JSON retained.')
                row['legacy_artifacts'].append(artifact)
    previous = None
    for row in rows:
        if row['state'] is not None and previous is not None:
            row['previous_state'] = previous
            if row['state'] != previous:
                row['transition'] = f'{previous} → {row["state"]}'
        previous = row['state']
    messages.append('RECONSTRUCTED_VERIFIED means the completed-week lookup policy on fingerprinted cached '
                    'adjusted prices, not an original historical price vintage. RECORDED_VERIFIED requires matching '
                    'inputs, calculation policy/code and an intact result fingerprint. RECORDED_LEGACY / UNVERIFIED '
                    'artifacts are shown separately and never supply verified scores. Canonical revisions are immutable; '
                    'conflicting revisions require explicit reconciliation.')
    return StockHistory(symbol, count, list(reversed(rows)), list(dict.fromkeys(messages)), version)
