"""
Sector index/ETF performance ranking for the daily report.

Separate from stock-based sector breadth. Ranks configured sector ETFs by their
own daily percentage change. Missing/invalid index data is skipped, never fatal.
"""

import logging
from typing import List, Dict, Any

logger = logging.getLogger("stock_scanner.reporting")


def build_sector_index_rows(report_context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Build rows for sector indexes from report_context['sector_index_data'].
    Skips entries with missing/invalid daily change (logged, not raised).
    """
    sector_data = (report_context or {}).get('sector_index_data', {})
    rows = []
    for sector_name, entry in sector_data.items():
        change_pct = entry.get('change_pct')
        if change_pct is None:
            symbol = entry.get('symbol', '?')
            logger.warning(f"WARNING: Unable to calculate daily change for sector index {symbol}")
            continue
        try:
            change_pct = float(change_pct)
        except (TypeError, ValueError):
            logger.warning(f"WARNING: Unable to calculate daily change for sector index {entry.get('symbol', '?')}")
            continue
        if change_pct != change_pct:  # NaN check
            logger.warning(f"WARNING: Unable to calculate daily change for sector index {entry.get('symbol', '?')}")
            continue
        rows.append({
            'symbol': entry.get('symbol', ''),
            'sector': entry.get('sector', sector_name),
            'close': entry.get('close'),
            'change_pct': change_pct,
        })
    return rows


def top_sector_indexes_up(report_context: Dict[str, Any], top_n: int = 3) -> List[Dict[str, Any]]:
    rows = build_sector_index_rows(report_context)
    rows.sort(key=lambda r: r['change_pct'], reverse=True)
    return rows[:top_n]


def top_sector_indexes_down(report_context: Dict[str, Any], top_n: int = 3) -> List[Dict[str, Any]]:
    rows = build_sector_index_rows(report_context)
    rows.sort(key=lambda r: r['change_pct'])
    return rows[:top_n]