"""Tests for the freshness eligibility layer."""
from __future__ import annotations

import pytest
from datetime import datetime, timezone

from data.freshness import (
    FreshnessPolicy,
    QuoteEligibility,
    classify_eligibility,
    split_by_eligibility,
    get_eligible_snapshots,
    get_history_eligible_snapshots,
    compute_eligibility_metadata,
    get_current_eligible_snapshots,
    get_history_eligible_symbols,
    get_current_eligible_snapshots,
    get_history_eligible_snapshots,
)
from models.schemas import StockSnapshot


class TestFreshnessPolicy:
    """Tests for FreshnessPolicy."""

    def test_default_values(self):
        policy = FreshnessPolicy()
        assert policy.fresh_max_seconds == 60
        assert policy.stale_threshold_seconds == 300
        assert policy.include_aging_in_current is False

    def test_custom_values(self):
        policy = FreshnessPolicy(
            fresh_max_seconds=30,
            stale_threshold_seconds=600,
            include_aging_in_current=True,
        )
        assert policy.fresh_max_seconds == 30
        assert policy.stale_threshold_seconds == 600
        assert policy.include_aging_in_current is True


class TestQuoteEligibility:
    """Tests for QuoteEligibility class."""

    def test_fresh_participates_in_current(self):
        policy = FreshnessPolicy()
        elig = QuoteEligibility(
            category=QuoteEligibility.FRESH,
            data_age_seconds=30.0,
            policy=FreshnessPolicy(),
        )
        assert elig.participates_in_current is True
        assert elig.participates_in_history is True

    def test_aging_excluded_by_default(self):
        policy = FreshnessPolicy()
        elig = QuoteEligibility(
            category=QuoteEligibility.AGING,
            data_age_seconds=120.0,
            policy=policy,
        )
        assert elig.participates_in_current is False
        assert elig.participates_in_history is False

    def test_aging_included_when_configured(self):
        policy = FreshnessPolicy(include_aging_in_current=True)
        elig = QuoteEligibility(
            category=QuoteEligibility.AGING,
            data_age_seconds=120.0,
            policy=policy,
        )
        assert elig.participates_in_current is True
        assert elig.participates_in_history is False

    def test_stale_excluded(self):
        policy = FreshnessPolicy()
        elig = QuoteEligibility(
            category=QuoteEligibility.STALE,
            data_age_seconds=331015.0,
            policy=policy,
        )
        assert elig.participates_in_current is False
        assert elig.participates_in_history is False

    def test_no_data_excluded(self):
        policy = FreshnessPolicy()
        elig = QuoteEligibility(
            category=QuoteEligibility.NO_DATA,
            data_age_seconds=None,
            policy=policy,
        )
        assert elig.participates_in_current is False
        assert elig.participates_in_history is False


class TestClassifyEligibility:
    """Tests for classify_eligibility function."""

    def _make_snapshot(self, age: float = None, is_valid: bool = True,
                       current_price: float = 100.0, previous_close: float = 99.0) -> StockSnapshot:
        return StockSnapshot(
            symbol="TEST",
            timestamp="2024-01-01T10:00:00-05:00",
            previous_close=previous_close,
            today_open=99.5,
            current_price=current_price,
            intraday_high=101.0,
            intraday_low=99.0,
            change_vs_previous_close=1.0,
            change_vs_open=0.5,
            distance_from_intraday_high=-1.0,
            distance_from_intraday_low=1.0,
            volume=1000000,
            is_valid=is_valid,
            issue="",
            direction="UP",
            data_age_seconds=age,
        )

    def test_fresh_quote_participates(self):
        """Fresh quote (<60s) participates in current metrics."""
        snap = self._make_snapshot(age=30.0)
        elig = classify_eligibility(snap, FreshnessPolicy())
        assert elig.category == "FRESH"
        assert elig.participates_in_current is True
        assert elig.participates_in_history is True

    def test_aging_excluded_by_default(self):
        """Aging quote (60-300s) excluded from current by default."""
        snap = self._make_snapshot(age=120.0)
        elig = classify_eligibility(snap, FreshnessPolicy())
        assert elig.category == "AGING"
        assert elig.participates_in_current is False
        assert elig.participates_in_history is False

    def test_aging_included_when_configured(self):
        """Aging quote included when include_aging_in_current=True."""
        snap = self._make_snapshot(age=120.0)
        policy = FreshnessPolicy(include_aging_in_current=True)
        elig = classify_eligibility(snap, policy)
        assert elig.category == "AGING"
        assert elig.participates_in_current is True

    def test_stale_excluded(self):
        """Stale quote (>=300s) always excluded."""
        snap = self._make_snapshot(age=300.0)
        elig = classify_eligibility(snap, FreshnessPolicy())
        assert elig.category == "STALE"
        assert elig.participates_in_current is False
        assert elig.participates_in_history is False

    def test_byddy_stale_excluded(self):
        """BYDDY with 331015s age is STALE and excluded."""
        snap = self._make_snapshot(age=331015.0)
        elig = classify_eligibility(snap, FreshnessPolicy())
        assert elig.category == "STALE"
        assert elig.participates_in_current is False
        assert elig.participates_in_history is False

    def test_invalid_quote_no_data(self):
        """Invalid snapshot becomes NO_DATA."""
        snap = self._make_snapshot(age=30.0, is_valid=False)
        elig = classify_eligibility(snap, FreshnessPolicy())
        assert elig.category == "NO_DATA"
        assert elig.participates_in_current is False

    def test_missing_age_no_data(self):
        """Missing data_age_seconds becomes NO_DATA."""
        snap = self._make_snapshot(age=None)
        elig = classify_eligibility(snap, FreshnessPolicy())
        assert elig.category == "NO_DATA"
        assert elig.participates_in_current is False
        assert elig.participates_in_history is False

    def test_negative_age_no_data(self):
        """Negative age (clock skew) becomes NO_DATA."""
        snap = self._make_snapshot(age=-5.0)
        elig = classify_eligibility(snap, FreshnessPolicy())
        assert elig.category == "NO_DATA"
        assert elig.participates_in_current is False
        assert elig.participates_in_history is False

    def test_nan_age_no_data(self):
        """NaN age becomes NO_DATA."""
        snap = self._make_snapshot(age=float('nan'))
        elig = classify_eligibility(snap, FreshnessPolicy())
        assert elig.category == "NO_DATA"
        assert elig.participates_in_current is False
        assert elig.participates_in_history is False

    def test_infinite_age_no_data(self):
        """Infinite age becomes NO_DATA."""
        snap = self._make_snapshot(age=float('inf'))
        elig = classify_eligibility(snap, FreshnessPolicy())
        assert elig.category == "NO_DATA"
        assert elig.participates_in_current is False
        assert elig.participates_in_history is False

    def test_non_numeric_age_no_data(self):
        """Non-numeric age becomes NO_DATA."""
        # This would be a data corruption case - string instead of float
        snap = StockSnapshot(
            symbol="TEST",
            timestamp="2024-01-01T10:00:00-05:00",
            previous_close=99.0,
            today_open=99.5,
            current_price=100.0,
            intraday_high=101.0,
            intraday_low=99.0,
            change_vs_previous_close=1.0,
            change_vs_open=0.5,
            distance_from_intraday_high=-1.0,
            distance_from_intraday_low=1.0,
            volume=1000000,
            is_valid=True,
            issue="",
            direction="UP",
            data_age_seconds="not a number",
        )
        elig = classify_eligibility(snap, FreshnessPolicy())
        assert elig.category == "NO_DATA"
        assert elig.participates_in_current is False
        assert elig.participates_in_history is False


class TestSplitByEligibility:
    """Tests for split_by_eligibility function."""

    def _make_snapshot(self, symbol: str, age: float = None, is_valid: bool = True):
        return StockSnapshot(
            symbol=symbol,
            timestamp="2024-01-01T10:00:00-05:00",
            previous_close=99.0,
            today_open=99.5,
            current_price=100.0,
            intraday_high=101.0,
            intraday_low=99.0,
            change_vs_previous_close=1.0,
            change_vs_open=0.5,
            distance_from_intraday_high=-1.0,
            distance_from_intraday_low=1.0,
            volume=1000000,
            is_valid=is_valid,
            issue="",
            direction="UP",
            data_age_seconds=age,
        )

    def test_split_by_eligibility(self):
        """Split correctly separates by category."""
        policy = FreshnessPolicy()
        stocks = [
            self._make_snapshot("FRESH1", 30.0),      # FRESH
            self._make_snapshot("AGING1", 120.0),     # AGING
            self._make_snapshot("STALE1", 300.0),     # STALE
            self._make_snapshot("STALE2", 500.0),     # STALE
            self._make_snapshot("NODATA1", 30.0, is_valid=False),  # NO_DATA
        ]
        result = split_by_eligibility(stocks, policy)
        assert len(result["FRESH"]) == 1
        assert len(result["AGING"]) == 1
        assert len(result["STALE"]) == 2
        assert len(result["NO_DATA"]) == 1


class TestEligibleSnapshots:
    """Tests for get_eligible_snapshots."""

    def _make_snapshot(self, symbol: str, age: float = None, is_valid: bool = True):
        return StockSnapshot(
            symbol=symbol,
            timestamp="2024-01-01T10:00:00-05:00",
            previous_close=99.0,
            today_open=99.5,
            current_price=100.0,
            intraday_high=101.0,
            intraday_low=99.0,
            change_vs_previous_close=1.0,
            change_vs_open=0.5,
            distance_from_intraday_high=-1.0,
            distance_from_intraday_low=1.0,
            volume=1000000,
            is_valid=is_valid,
            issue="",
            direction="UP",
            data_age_seconds=age,
        )

    def test_get_eligible_snapshots(self):
        """Only FRESH (and AGING if configured) are returned."""
        policy = FreshnessPolicy()
        stocks = [
            self._make_snapshot("FRESH1", 30.0),
            self._make_snapshot("FRESH2", 45.0),
            self._make_snapshot("AGING1", 120.0),
            self._make_snapshot("STALE1", 300.0),
        ]
        eligible = get_eligible_snapshots(stocks, policy)
        assert len(eligible) == 2  # only the two FRESH

    def test_get_eligible_snapshots_with_aging_enabled(self):
        """AGING included when configured."""
        policy = FreshnessPolicy(include_aging_in_current=True)
        stocks = [
            self._make_snapshot("FRESH1", 30.0),
            self._make_snapshot("AGING1", 120.0),
        ]
        eligible = get_eligible_snapshots(stocks, policy)
        assert len(eligible) == 2


class TestEligibilityMetadata:
    """Tests for compute_eligibility_metadata."""

    def _make_snapshot(self, symbol: str, age: float = None, is_valid: bool = True):
        return StockSnapshot(
            symbol=symbol,
            timestamp="2024-01-01T10:00:00-05:00",
            previous_close=99.0,
            today_open=99.5,
            current_price=100.0,
            intraday_high=101.0,
            intraday_low=99.0,
            change_vs_previous_close=1.0,
            change_vs_open=0.5,
            distance_from_intraday_high=-1.0,
            distance_from_intraday_low=1.0,
            volume=1000000,
            is_valid=is_valid,
            issue="",
            direction="UP",
            data_age_seconds=age,
        )

    def test_metadata_counts(self):
        """Metadata correctly counts each category."""
        policy = FreshnessPolicy()
        stocks = [
            self._make_snapshot("FRESH1", 30.0),      # FRESH
            self._make_snapshot("FRESH2", 45.0),      # FRESH
            self._make_snapshot("AGING1", 120.0),     # AGING
            self._make_snapshot("STALE1", 300.0),     # STALE
            self._make_snapshot("NODATA1", 30.0, is_valid=False),  # NO_DATA
        ]
        meta = compute_eligibility_metadata(stocks, policy)
        assert meta["eligible_stocks"] == 2
        assert meta["aging_stocks"] == 1
        assert meta["stale_stocks"] == 1
        assert meta["no_data_stocks"] == 1
        assert meta["total_constituents"] == 5
        assert meta["oldest_quote_age"] == 300.0
        assert meta["newest_quote_age"] == 30.0

    def test_byddy_metadata(self):
        """BYDDY extreme stale counted correctly."""
        policy = FreshnessPolicy()
        stocks = [
            StockSnapshot(
                symbol="BYDDY",
                timestamp="2024-01-01T10:00:00-05:00",
                previous_close=20.0,
                today_open=20.0,
                current_price=20.5,
                intraday_high=21.0,
                intraday_low=19.5,
                change_vs_previous_close=2.5,
                change_vs_open=2.5,
                distance_from_intraday_high=-2.5,
                distance_from_intraday_low=2.5,
                volume=100000,
                is_valid=True,
                issue="",
                direction="UP",
                data_age_seconds=331015.0,
            )
        ]
        meta = compute_eligibility_metadata(stocks, FreshnessPolicy())
        assert meta["stale_stocks"] == 1
        assert meta["eligible_stocks"] == 0
        assert meta["oldest_quote_age"] == 331015.0


class TestHistoryEligibleSymbols:
    """Tests for history eligibility."""

    def _make_snapshot(self, symbol: str, age: float = None, is_valid: bool = True):
        return StockSnapshot(
            symbol=symbol,
            timestamp="2024-01-01T10:00:00-05:00",
            previous_close=99.0,
            today_open=99.5,
            current_price=100.0,
            intraday_high=101.0,
            intraday_low=99.0,
            change_vs_previous_close=1.0,
            change_vs_open=0.5,
            distance_from_intraday_high=-1.0,
            distance_from_intraday_low=1.0,
            volume=1000000,
            is_valid=is_valid,
            issue="",
            direction="UP",
            data_age_seconds=age,
        )

    def test_fresh_only_in_history(self):
        """Only FRESH symbols in history."""
        policy = FreshnessPolicy()
        stocks = [
            self._make_snapshot("FRESH1", 30.0),
            self._make_snapshot("AGING1", 120.0),
            self._make_snapshot("STALE1", 300.0),
        ]
        symbols = get_history_eligible_symbols(stocks, policy)
        assert symbols == {"FRESH1"}


class TestEligibilityEdgeCases:
    """Edge case tests."""

    def _make_snapshot(self, symbol: str, age: float = None, is_valid: bool = True):
        return StockSnapshot(
            symbol=symbol,
            timestamp="2024-01-01T10:00:00-05:00",
            previous_close=99.0,
            today_open=99.5,
            current_price=100.0,
            intraday_high=101.0,
            intraday_low=99.0,
            change_vs_previous_close=1.0,
            change_vs_open=0.5,
            distance_from_intraday_high=-1.0,
            distance_from_intraday_low=1.0,
            volume=1000000,
            is_valid=is_valid,
            issue="",
            direction="UP",
            data_age_seconds=age,
        )

    def test_insufficient_eligible_sample(self):
        """Theme with insufficient eligible stocks triggers small_sample."""
        policy = FreshnessPolicy()
        stocks = [
            self._make_snapshot("FRESH1", 30.0),
            self._make_snapshot("FRESH2", 45.0),
            self._make_snapshot("FRESH3", 30.0),
        ]
        # 3 eligible < 5 threshold -> small_sample
        from data.freshness import get_eligible_snapshots
        eligible = get_eligible_snapshots(stocks, FreshnessPolicy())
        assert len(eligible) == 3  # would trigger small_sample threshold of 5

    def test_byddy_excluded_from_all(self):
        """BYDDY style stale quote excluded from all calculations."""
        policy = FreshnessPolicy()
        byddy = StockSnapshot(
            symbol="BYDDY",
            timestamp="2024-01-01T10:00:00-05:00",
            previous_close=20.0,
            today_open=20.0,
            current_price=20.5,
            intraday_high=21.0,
            intraday_low=19.5,
            change_vs_previous_close=2.5,
            change_vs_open=2.5,
            distance_from_intraday_high=-2.5,
            distance_from_intraday_low=2.5,
            volume=100000,
            is_valid=True,
            issue="",
            direction="UP",
            data_age_seconds=331015.0,
        )
        fresh = StockSnapshot(
            symbol="FRESH1",
            timestamp="2024-01-01T10:00:00-05:00",
            previous_close=99.0,
            today_open=99.5,
            current_price=100.0,
            intraday_high=101.0,
            intraday_low=99.0,
            change_vs_previous_close=1.0,
            change_vs_open=0.5,
            distance_from_intraday_high=-1.0,
            distance_from_intraday_low=1.0,
            volume=1000000,
            is_valid=True,
            issue="",
            direction="UP",
            data_age_seconds=30.0,
        )
        stocks = [byddy] + [self._make_snapshot(f"FRESH{i}", 30.0) for i in range(9)]
        from data.freshness import get_current_eligible_snapshots, compute_eligibility_metadata
        
        eligible = get_current_eligible_snapshots(stocks, FreshnessPolicy())
        assert len(eligible) == 9  # BYDDY excluded
        
        meta = compute_eligibility_metadata(stocks, FreshnessPolicy())
        assert meta["eligible_stocks"] == 9
        assert meta["stale_stocks"] == 1
        assert meta["total_constituents"] == 10


if __name__ == "__main__":
    pytest.main([__file__, "-v"])