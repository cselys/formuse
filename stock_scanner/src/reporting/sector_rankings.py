"""
Sector breadth ranking calculations for the daily report.

Sector breadth is based on the INDIVIDUAL STOCKS assigned to each sector, not
sector ETF/index performance. Sector indexes and benchmarks are excluded.
"""

import logging
from typing import List, Dict, Any

from stock_scanner.src.reporting.stock_rankings import _is_stock

logger = logging.getLogger("stock_scanner.reporting")


def compute_sector_breadth(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    For every configured sector, count up/down/flat stocks and compute ratios.

    Returns a list of sector dicts:
        {
            'sector', 'sector_up_count', 'sector_down_count', 'sector_flat_count',
            'total_stock_count', 'up_ratio', 'down_ratio', 'avg_change_pct'
        }
    Sectors with no usable stock rows are omitted.
    """
    sector_map: Dict[str, Dict[str, Any]] = {}

    for record in results:
        if not _is_stock(record):
            continue

        sector = record.get('category') or 'unknown'
        change_pct = record.get('daily_change_pct')
        if change_pct is None:
            continue

        try:
            change_pct = float(change_pct)
        except (TypeError, ValueError):
            continue
        if change_pct != change_pct:  # NaN check
            continue

        bucket = sector_map.setdefault(sector, {
            'sector': sector,
            'up': 0,
            'down': 0,
            'flat': 0,
            'sum_change': 0.0,
        })
        bucket['sum_change'] += change_pct
        if change_pct > 0:
            bucket['up'] += 1
        elif change_pct < 0:
            bucket['down'] += 1
        else:
            bucket['flat'] += 1

    out = []
    for sector, b in sector_map.items():
        total = b['up'] + b['down'] + b['flat']
        if total == 0:
            continue
        out.append({
            'sector': sector,
            'sector_up_count': b['up'],
            'sector_down_count': b['down'],
            'sector_flat_count': b['flat'],
            'total_stock_count': total,
            'up_ratio': b['up'] / total,
            'down_ratio': b['down'] / total,
            'avg_change_pct': b['sum_change'] / total,
        })

    # Sort deterministically: higher up_ratio first, then higher up_count,
    # then larger average daily return.
    out.sort(key=lambda s: (s['up_ratio'], s['sector_up_count'], s['avg_change_pct']), reverse=True)
    return out


def top_sectors_up(results: List[Dict[str, Any]], top_n: int = 3) -> List[Dict[str, Any]]:
    """Rank sectors by breadth up ratio (up_count / total)."""
    return compute_sector_breadth(results)[:top_n]


def top_sectors_down(results: List[Dict[str, Any]], top_n: int = 3) -> List[Dict[str, Any]]:
    """Rank sectors by breadth down ratio (down_count / total), most negative first."""
    sectors = compute_sector_breadth(results)
    # Higher down_ratio first, then higher down_count, then LOWER avg return.
    sectors.sort(key=lambda s: (-s['down_ratio'], -s['sector_down_count'], s['avg_change_pct']))
    return sectors[:top_n]