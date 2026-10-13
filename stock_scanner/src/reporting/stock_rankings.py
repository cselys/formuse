"""
Stock ranking calculations for the daily report.

Ranks individual stocks by their daily percentage change (from the same yfinance
daily data used by the scanner). Sector/benchmark/index ETFs are excluded.
Missing or invalid daily-change data is skipped, never fatal.
"""

import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger("stock_scanner.reporting")


def _is_stock(record: Dict[str, Any]) -> bool:
    """Return True if a scan record represents an individual stock (not an index/ETF)."""
    if record.get('is_index_etf', False):
        return False
    symbol = (record.get('symbol') or '').upper()
    # Defensive: benchmarks/known ETFs must never rank as stocks.
    if symbol in ('SPY', 'QQQ', 'SMH', 'XLE', 'XLF', 'IWM'):
        return False
    return True


def extract_stock_rows(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Build normalized stock rows from scan results, skipping indexes/ETFs and
    records with missing daily-change data (logged, not raised).
    """
    rows = []
    for record in results:
        if not _is_stock(record):
            continue

        change_pct = record.get('daily_change_pct')
        if change_pct is None:
            symbol = record.get('symbol', '?')
            logger.warning(f"WARNING: Unable to calculate daily change for {symbol}")
            continue

        try:
            change_pct = float(change_pct)
        except (TypeError, ValueError):
            logger.warning(f"WARNING: Unable to calculate daily change for {record.get('symbol', '?')}")
            continue
        if change_pct != change_pct:  # NaN check
            logger.warning(f"WARNING: Unable to calculate daily change for {record.get('symbol', '?')}")
            continue

        daily = record.get('daily', {}) or {}
        rs = record.get('relative_strength', {}) or {}

        rows.append({
            'symbol': record.get('symbol', ''),
            'category': record.get('category', ''),
            'sector': record.get('category', ''),
            'close': daily.get('close'),
            'change_pct': change_pct,
            'state': record.get('state', ''),
            'candidate_score': record.get('candidate_score'),
            'entry_quality': record.get('entry_quality', record.get('setup_quality')),
            'rs_20d': rs.get('rs_20d'),
            'rs_trend': rs.get('rs_trend', 'N/A'),
            'market_regime': record.get('market_regime', 'NEUTRAL'),
        })

    return rows


def rank_stocks_up(results: List[Dict[str, Any]], top_n: int = 10) -> List[Dict[str, Any]]:
    """Rank individual stocks by daily change descending (largest positive first)."""
    rows = extract_stock_rows(results)
    rows = [r for r in rows if r['change_pct'] is not None and r['change_pct'] > 0]
    rows.sort(key=lambda r: r['change_pct'], reverse=True)
    return rows[:top_n]


def rank_stocks_down(results: List[Dict[str, Any]], top_n: int = 10) -> List[Dict[str, Any]]:
    """Rank individual stocks by daily change ascending (most negative first)."""
    rows = extract_stock_rows(results)
    rows = [r for r in rows if r['change_pct'] is not None and r['change_pct'] < 0]
    rows.sort(key=lambda r: r['change_pct'])
    return rows[:top_n]