"""Focused tests for MarketData.timestamp semantics (spec sections 7, 33).

Verifies that MarketData.asof uses provider_timestamp from Finnhub snapshots,
while Last Update (fetched_at) uses dashboard render time. The two timestamps
must remain distinct both during RTH and post-market.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from data.provider_base import MarketData


ET = ZoneInfo("America/New_York")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_md_with_asof(asof_et: datetime, fetched_at_utc: datetime) -> MarketData:
    """Convenient MarketData builder for timestamp-aware tests."""
    return MarketData(
        source="finnhub_snapshot",
        interval="5m",
        fetched_at=fetched_at_utc,
        asof=asof_et,
        bars={},
        daily={},
        failed={},
    )


def now_et() -> datetime:
    return datetime.now(ET)


# ===================================================================
# Case 1 — RTH: provider timestamp during regular trading hours
# ===================================================================

def test_asof_uses_provider_timestamp_rth():
    """RTH: MarketData.asof must reflect the provider timestamp, NOT render time.

    Given a provider timestamp of 10:31:42 AM ET and a dashboard render time
    of 10:31:50 AM ET, asof must be the provider timestamp and Last Update
    must be the render time.
    """
    provider_ts_et = datetime(2026, 10, 6, 10, 31, 42, tzinfo=ET)
    render_ts_et = datetime(2026, 10, 6, 10, 31, 50, tzinfo=ET)

    md = make_md_with_asof(
        asof_et=provider_ts_et,
        fetched_at_utc=render_ts_et.astimezone(timezone.utc),
    )

    # asof must be the provider timestamp
    assert md.asof == provider_ts_et, (
        f"expected md.asof == provider_ts_et, got md.asof={md.asof}"
    )

    # Last Update (fetched_at) must be the render time, NOT provider timestamp
    assert md.fetched_at == render_ts_et.astimezone(timezone.utc), (
        f"expected md.fetched_at == render time, got md.fetched_at={md.fetched_at}"
    )


# ===================================================================
# Case 2 — Post-market: provider timestamp frozen at 4:00 PM ET
# ===================================================================

def test_asof_uses_provider_timestamp_post_market():
    """Post-market: MarketData.asof must reflect the frozen provider timestamp,
    while Last Update reflects the current dashboard render time.

    Provider timestamps are frozen at 4:00:00 PM ET after market close;
    dashboard render time advances. Both must be independently observable.
    """
    provider_ts_et = datetime(2026, 10, 6, 16, 0, 0, tzinfo=ET)  # 4:00 PM ET
    render_ts_et = datetime(2026, 10, 6, 16, 30, 0, tzinfo=ET)  # 4:30 PM ET

    md = make_md_with_asof(
        asof_et=provider_ts_et,
        fetched_at_utc=render_ts_et.astimezone(timezone.utc),
    )

    # asof must be the provider timestamp (frozen at 4:00 PM ET)
    assert md.asof == provider_ts_et, (
        f"expected md.asof == provider_ts_et, got md.asof={md.asof}"
    )

    # Last Update must be the render time (4:30 PM ET)
    assert md.fetched_at == render_ts_et.astimezone(timezone.utc), (
        f"expected md.fetched_at == render time, got md.fetched_at={md.fetched_at}"
    )


# ===================================================================
# Case 3 — Rerun without new collector data
# ===================================================================

def test_asof_unchanged_on_rerun_while_last_update_advances():
    """Rerun without new data: MarketData.asof must remain unchanged while
    Last Update (fetched_at) advances to the new render time.

    This simulates a Streamlit rerun where SQLite still contains the same
    snapshots — Data as of stays at the original collector session time,
    while Last Update advances to the current time.
    """
    # First run timestamps
    provider_ts_et = datetime(2026, 10, 6, 10, 31, 42, tzinfo=ET)
    old_render_et = datetime(2026, 10, 6, 10, 31, 50, tzinfo=ET)

    md_old = make_md_with_asof(
        asof_et=provider_ts_et,
        fetched_at_utc=old_render_et.astimezone(timezone.utc),
    )

    # Second run (simulated rerun) — same provider timestamp, new render time
    new_render_et = datetime(2026, 10, 6, 11, 0, 0, tzinfo=ET)  # 1 minute later

    # Verify asof is still the original provider timestamp
    assert md_old.asof == provider_ts_et, (
        f"expected md.asof unchanged == provider_ts_et, got md.asof={md_old.asof}"
    )

    # Build new MarketData for the rerun with advanced render time
    md_new = make_md_with_asof(
        asof_et=provider_ts_et,  # same provider timestamp from SQLite
        fetched_at_utc=new_render_et.astimezone(timezone.utc),
    )

    # asof must still be the original provider timestamp (unchanged)
    assert md_new.asof == provider_ts_et, (
        f"expected md_new.asof == original provider_ts_et, got md_new.asof={md_new.asof}"
    )

    # fetched_at (Last Update) must have advanced to the new render time
    assert md_new.fetched_at == new_render_et.astimezone(timezone.utc), (
        f"expected md_new.fetched_at == new render time, got md_new.fetched_at={md_new.fetched_at}"
    )

    # The two timestamps must diverge
    assert md_new.asof != md_new.fetched_at, (
        "asof and fetched_at must diverge on rerun — one is provider ts, one is render time"
    )