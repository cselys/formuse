"""
Daily report data model.

Assembles all report sections from scan results and report context into a single
structure that can be rendered to terminal / TXT / CSV / HTML without duplicating
calculation logic.
"""

import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

from stock_scanner.src.reporting.stock_rankings import rank_stocks_up, rank_stocks_down
from stock_scanner.src.reporting.sector_rankings import top_sectors_up, top_sectors_down, compute_sector_breadth
from stock_scanner.src.reporting.sector_indexes import top_sector_indexes_up, top_sector_indexes_down
from stock_scanner.src.reporting.state_breakdown import StateBreakdown

logger = logging.getLogger("stock_scanner.reporting")

_SECTOR_INDEX_SECTORS = {
    'XLK': 'Technology',
    'XLF': 'Financials',
    'XLE': 'Energy',
    'XLV': 'Healthcare',
    'XLI': 'Industrials',
    'XLY': 'Consumer Discretionary',
    'XLP': 'Consumer Staples',
    'XLU': 'Utilities',
    'XLC': 'Communication Services',
    'XLRE': 'Real Estate',
    'XLB': 'Materials',
}

# Map config keys (lowercase) to display labels.
_SECTOR_KEY_LABELS = {
    'technology': 'Technology',
    'financials': 'Financials',
    'energy': 'Energy',
    'healthcare': 'Healthcare',
    'industrials': 'Industrials',
    'consumer_discretionary': 'Consumer Discretionary',
    'consumer_staples': 'Consumer Staples',
    'utilities': 'Utilities',
    'communication_services': 'Communication Services',
    'real_estate': 'Real Estate',
    'materials': 'Materials',
}


class DailyReport:
    """Structured daily report data model."""

    def __init__(
        self,
        results: List[Dict[str, Any]],
        report_context: Optional[Dict[str, Any]] = None,
        scan_date: Optional[str] = None,
        state_breakdown: Optional[StateBreakdown] = None,
        top_n: Optional[int] = None,
    ):
        self.scan_date = scan_date or datetime.now().strftime("%Y-%m-%d")
        self.market_regime = self._detect_market_regime(results)
        self.universe_size = self._count_stocks(results)
        self.top_stocks_up = rank_stocks_up(results, top_n=10)
        self.top_stocks_down = rank_stocks_down(results, top_n=10)
        self.top_sectors_up = top_sectors_up(results, top_n=3)
        self.top_sectors_down = top_sectors_down(results, top_n=3)
        self.sector_breadth = compute_sector_breadth(results)
        self.sector_indexes_up = top_sector_indexes_up(report_context or {}, top_n=3)
        self.sector_indexes_down = top_sector_indexes_down(report_context or {}, top_n=3)
        # Keep original scan results for the existing scanner signal tables.
        self.scan_results = results
        self.state_breakdown = state_breakdown if state_breakdown is not None else StateBreakdown(results, top_n)

    @staticmethod
    def _detect_market_regime(results: List[Dict[str, Any]]) -> str:
        regimes = [r.get('market_regime') for r in results if r.get('market_regime')]
        if regimes:
            return regimes[0]
        return 'NEUTRAL'

    @staticmethod
    def _count_stocks(results: List[Dict[str, Any]]) -> int:
        from stock_scanner.src.reporting.stock_rankings import _is_stock
        return sum(1 for r in results if _is_stock(r))

    @property
    def has_scan_results(self) -> bool:
        return bool(self.scan_results)

    def sector_index_label(self, symbol: str) -> str:
        label = _SECTOR_INDEX_SECTORS.get((symbol or '').upper())
        if label:
            return label
        return ''
