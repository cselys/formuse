"""Quote freshness eligibility layer (spec: data quality layer).

Separates UNIVERSE MEMBERSHIP (configured in themes.yaml) from
QUOTE ELIGIBILITY (runtime data freshness).

A stock can be in the universe but INELIGIBLE for current calculations
due to stale or missing quote data.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Set
import math

from models.schemas import StockSnapshot


@dataclass(frozen=True)
class FreshnessPolicy:
    """Policy for classifying quote freshness.

    Attributes:
        fresh_max_seconds: Maximum age (seconds) for a quote to be FRESH.
        stale_threshold_seconds: Minimum age (seconds) for a quote to be STALE.
            AGING is the range: fresh_max_seconds <= age < stale_threshold_seconds.
        include_aging_in_current: If True, AGING quotes participate in current
            metrics (default False: only FRESH participates in current metrics).
    """
    fresh_max_seconds: int = 60
    stale_threshold_seconds: int = 300
    include_aging_in_current: bool = False


class QuoteEligibility:
    """Eligibility classification for a quote snapshot."""
    FRESH = "FRESH"
    AGING = "AGING"
    STALE = "STALE"
    NO_DATA = "NO_DATA"

    def __init__(
        self,
        category: str,
        data_age_seconds: Optional[float],
        policy: Optional["FreshnessPolicy"] = None,
    ):
        self.category = category
        self.data_age_seconds = data_age_seconds
        self._policy = policy

    @property
    def participates_in_current(self) -> bool:
        """Whether this quote participates in current metrics (breadth, average, etc.)."""
        if self.category == self.FRESH:
            return True
        if self.category == self.AGING:
            return self._policy.include_aging_in_current if self._policy else False
        return False  # STALE, NO_DATA

    @property
    def participates_in_history(self) -> bool:
        """Whether this quote participates in historical calculations (reversal/recovery)."""
        # Only FRESH participates in history; AGING/STALE/NO_DATA excluded
        return self.category == self.FRESH

    @property
    def metadata(self) -> dict:
        return {
            "category": self.category,
            "data_age_seconds": self.data_age_seconds,
            "participates_current": self.participates_in_current,
            "participates_history": self.participates_in_history,
        }


def classify_eligibility(
    snapshot: StockSnapshot,
    policy: Optional["FreshnessPolicy"] = None,
    market_is_open: bool = False,
) -> QuoteEligibility:
    """Classify a StockSnapshot's freshness eligibility.

    Args:
        snapshot: The stock snapshot to classify.
        policy: Freshness policy (uses defaults if None).
        market_is_open: Whether market is currently open (affects staleness logic
            for backwards compatibility with existing stale_quote_seconds).

    Returns:
        QuoteEligibility with category and participation flags.
    """
    if policy is None:
        policy = FreshnessPolicy()

    # Invalid or missing snapshot -> NO_DATA
    if not snapshot.is_valid:
        return QuoteEligibility(
            category=QuoteEligibility.NO_DATA,
            data_age_seconds=snapshot.data_age_seconds,
            policy=policy,
        )

    data_age = snapshot.data_age_seconds

    # Missing or invalid age -> NO_DATA
    if data_age is None:
        return QuoteEligibility(
            category=QuoteEligibility.NO_DATA,
            data_age_seconds=None,
            policy=policy,
        )

    # Invalid/non-finite age -> NO_DATA
    try:
        if not (isinstance(data_age, (int, float)) and math.isfinite(data_age)):
            return QuoteEligibility(
                category=QuoteEligibility.NO_DATA,
                data_age_seconds=data_age,
                policy=policy,
            )
    except (TypeError, ValueError):
        return QuoteEligibility(
            category=QuoteEligibility.NO_DATA,
            data_age_seconds=data_age,
            policy=policy,
        )

    # Negative age -> NO_DATA (clock skew not expected in normal operation)
    if data_age < 0:
        return QuoteEligibility(
            category=QuoteEligibility.NO_DATA,
            data_age_seconds=data_age,
            policy=policy,
        )

    # Classification by age
    if data_age < policy.fresh_max_seconds:
        category = QuoteEligibility.FRESH
    elif data_age < policy.stale_threshold_seconds:
        category = QuoteEligibility.AGING
    else:
        category = QuoteEligibility.STALE

    return QuoteEligibility(category=category, data_age_seconds=data_age, policy=policy)


def split_by_eligibility(
    snapshots: List[StockSnapshot],
    policy: "FreshnessPolicy",
) -> Dict[str, List[StockSnapshot]]:
    """Split a list of snapshots by eligibility category.

    Returns dict with keys: FRESH, AGING, STALE, NO_DATA
    """
    result = {
        QuoteEligibility.FRESH: [],
        QuoteEligibility.AGING: [],
        QuoteEligibility.STALE: [],
        QuoteEligibility.NO_DATA: [],
    }
    for snap in snapshots:
        elig = classify_eligibility(snap, policy=FreshnessPolicy())
        result[elig.category].append(snap)
    return result


def get_eligible_snapshots(
    snapshots: List[StockSnapshot],
    policy: Optional["FreshnessPolicy"] = None,
) -> List[StockSnapshot]:
    """Return only snapshots that participate in current metrics."""
    if policy is None:
        policy = FreshnessPolicy()
    return [s for s in snapshots if classify_eligibility(s, policy).participates_in_current]


def get_history_eligible_snapshots(
    snapshots: List[StockSnapshot],
    policy: Optional["FreshnessPolicy"] = None,
) -> List[StockSnapshot]:
    """Return only snapshots that participate in historical calculations."""
    if policy is None:
        policy = FreshnessPolicy()
    return [s for s in snapshots if classify_eligibility(s, policy).participates_in_history]


def compute_eligibility_metadata(
    snapshots: List[StockSnapshot],
    policy: Optional["FreshnessPolicy"] = None,
) -> dict:
    """Compute diagnostic metadata about quote freshness.

    Returns dict with:
        eligible_stocks: count participating in current metrics
        aging_stocks: count AGING
        stale_stocks: count STALE
        no_data_stocks: count NO_DATA
        total_constituents: total snapshots provided
        oldest_quote_age: max data_age_seconds across all snapshots
        newest_quote_age: min data_age_seconds across all snapshots
    """
    if policy is None:
        policy = FreshnessPolicy()

    fresh = 0
    aging = 0
    stale = 0
    no_data = 0
    all_ages = []

    for snap in snapshots:
        elig = classify_eligibility(snap, policy)
        if elig.category == QuoteEligibility.FRESH:
            fresh += 1
        elif elig.category == QuoteEligibility.AGING:
            aging += 1
        elif elig.category == QuoteEligibility.STALE:
            stale += 1
        else:
            no_data += 1

        if snap.data_age_seconds is not None:
            all_ages.append(snap.data_age_seconds)

    return {
        "eligible_stocks": fresh,
        "aging_stocks": aging,
        "stale_stocks": stale,
        "no_data_stocks": no_data,
        "total_constituents": len(snapshots),
        "oldest_quote_age": max(all_ages) if all_ages else None,
        "newest_quote_age": min(all_ages) if all_ages else None,
    }


def get_current_eligible_snapshots(
    snapshots: List[StockSnapshot],
    policy: Optional["FreshnessPolicy"] = None,
) -> List[StockSnapshot]:
    """Alias for get_eligible_snapshots for clarity."""
    return get_eligible_snapshots(snapshots, policy)


def get_history_eligible_snapshots(
    snapshots: List[StockSnapshot],
    policy: Optional["FreshnessPolicy"] = None,
) -> List[StockSnapshot]:
    """Return only snapshots that participate in historical calculations."""
    if policy is None:
        policy = FreshnessPolicy()
    return [s for s in snapshots if classify_eligibility(s, policy).participates_in_history]


def get_history_eligible_symbols(
    snapshots: List[StockSnapshot],
    policy: Optional["FreshnessPolicy"] = None,
) -> Set[str]:
    """Return set of symbols eligible for historical calculations."""
    if policy is None:
        policy = FreshnessPolicy()
    return {
        s.symbol
        for s in snapshots
        if classify_eligibility(s, policy).participates_in_history
    }