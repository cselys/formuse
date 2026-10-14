"""Theme breadth aggregation (spec sections 9-11).

Classification uses a configurable neutral band so tiny moves are not
counted as meaningful (default +/-0.10%):

    > +flat_threshold  -> UP
    < -flat_threshold  -> DOWN
    otherwise          -> FLAT

"Strong" breadth (spec 10) uses a separate threshold (default +/-1.0%) so
"80% of stocks +0.2%" is distinguishable from "80% of stocks +2%".
"""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np

from data.freshness import (
    FreshnessPolicy,
    classify_eligibility,
    compute_eligibility_metadata,
    get_current_eligible_snapshots,
    QuoteEligibility,
    freshness_policy,
)
from models.schemas import DOWN, FLAT, StockSnapshot, UP
from utils.config import get_setting


def classify_direction(change_vs_close, flat_threshold: float = 0.10) -> str:
    """UP / DOWN / FLAT for a single stock vs its previous close."""
    if change_vs_close is None:
        return FLAT
    if change_vs_close > flat_threshold:
        return UP
    if change_vs_close < -flat_threshold:
        return DOWN
    return FLAT


def _ratio(num: int, den: int) -> float:
    return num / den * 100.0 if den else 0.0


def _create_freshness_policy(settings: dict) -> FreshnessPolicy:
    """Create FreshnessPolicy from settings."""
    return freshness_policy(settings)


def compute_breadth(stocks: List[StockSnapshot], settings: dict,
                    total: Optional[int] = None,
                    policy: Optional[FreshnessPolicy] = None) -> Dict:
    """Aggregate breadth statistics for one theme's configured stocks.

    Only VALID and ELIGIBLE stocks enter the percentages; missing/halted/stale
    stocks are counted in their respective categories (spec section 23: "8 / 10 valid").

    ``total`` is the number of CONFIGURED stocks — pass it when some
    configured tickers have no snapshot at all (unknown symbol).
    """
    policy = policy or _create_freshness_policy(settings)
    flat = get_setting(settings, "classification.flat_threshold", 0.10)
    strong = get_setting(settings, "classification.strong_move_threshold", 1.0)

    total = len(stocks) if total is None else total

    # Get eligibility metadata
    meta = compute_eligibility_metadata(stocks, policy)

    # Only ELIGIBLE stocks enter the percentages
    valid = [s for s in stocks if s.is_valid and s.change_vs_previous_close is not None
             and classify_eligibility(s, policy).participates_in_current]
    n = len(valid)

    if n:
        changes = np.array([s.change_vs_previous_close for s in valid], dtype=float)
        up = int((changes > flat).sum())
        down = int((changes < -flat).sum())
        strong_up = int((changes > strong).sum())
        strong_down = int((changes < -strong).sum())
        opens = np.array([s.change_vs_open for s in valid
                          if s.change_vs_open is not None], dtype=float)
    else:
        up = down = strong_up = strong_down = 0
        changes = np.array([])
        opens = np.array([])

    # Get eligibility metadata
    meta = compute_eligibility_metadata(stocks, policy)

    return {
        "total_stocks": total,
        "valid_stocks": n,
        "missing_stocks": total - n,
        "up_stocks": int((changes > flat).sum()) if n else 0,
        "down_stocks": int((changes < -flat).sum()) if n else 0,
        "flat_stocks": n - int((changes > flat).sum()) - int((changes < -flat).sum()) if n else 0,
        "up_percent": _ratio(int((changes > flat).sum()), n) if n else 0.0,
        "down_percent": _ratio(int((changes < -flat).sum()), n) if n else 0.0,
        "flat_percent": _ratio(n - int((changes > flat).sum()) - int((changes < -flat).sum()), n) if n else 0.0,
        "strong_up_percent": _ratio(int((changes > strong).sum()), n) if n else 0.0,
        "strong_down_percent": _ratio(int((changes < -strong).sum()), n) if n else 0.0,
        "average_return": float(changes.mean()) if n else 0.0,
        "median_return": float(np.median(changes)) if n else 0.0,
        "average_change_from_open": float(opens.mean()) if len(opens) else 0.0,
        "median_change_from_open": float(np.median(opens)) if len(opens) else 0.0,
        "total_volume": int(sum(s.volume for s in valid)) if n else 0,
        # Eligibility metadata
        "eligible_stocks": meta["eligible_stocks"],
        "aging_stocks": meta["aging_stocks"],
        "stale_stocks": meta["stale_stocks"],
        "no_data_stocks": meta["no_data_stocks"],
        "total_constituents": meta["total_constituents"],
        "oldest_quote_age": meta["oldest_quote_age"],
        "newest_quote_age": meta["newest_quote_age"],
    }


def _ratio(num: int, den: int) -> float:
    return num / den * 100.0 if den else 0.0
