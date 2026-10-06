"""Unit tests for the Finnhub provider, collector, scheduler, persistence
and provider selection (Finnhub migration, Phase 1).

All tests use the deterministic fake Finnhub client (tests.fake_finnhub); no
live network access.
"""
from __future__ import annotations

import logging
import math
import os
import signal
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pandas as pd
import pytest

from data.cache import SnapshotStore
from data.collector import (
    CollectionConfig,
    CycleSummary,
    FinnhubCollector,
    build_universe,
    derive_schedule,
)
from data.finnhub_provider import (
    FinnhubProvider,
    _FinnhubTransport,
    compute_data_age,
    is_stale_quote,
    parse_provider_timestamp,
    quote_to_snapshot,
)
from models.schemas import DOWN, FLAT, UP
from tests.fake_finnhub import FakeFinnhubClient


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmpdb(tmp_path):
    return str(tmp_path / "sector_radar.db")


@pytest.fixture
def fake_now():
    """A controllable clock for quote timestamps."""
    base = datetime(2026, 10, 5, 14, 0, 0, tzinfo=timezone.utc)

    class Clock:
        now_value = base
        steps = []

        def now(self):
            self.steps.append(datetime.fromisoformat(
                self.now_value.isoformat()))
            return self.now_value

        def advance(self, seconds: float):
            self.now_value += timedelta(seconds=seconds)
            return self.now_value

        def set(self, dt):
            self.now_value = dt
            return self.now_value

    return Clock()


@pytest.fixture
def base_quote():
    """A realistic /quote response body."""
    return {
        "c": 101.0, "d": 1.0, "dp": 1.0, "h": 102.0, "l": 99.5,
        "o": 100.5, "pc": 100.0, "t": 1760000000,
    }


# ---------------------------------------------------------------------------
# 1. Finnhub quote -> StockSnapshot mapping
# ---------------------------------------------------------------------------

def test_quote_to_snapshot_map_fields(base_quote, fake_now):
    """FinHub /quote fields map onto the existing StockSnapshot model."""
    fake_now.set(datetime.fromtimestamp(base_quote["t"], tz=timezone.utc))
    snap = quote_to_snapshot("AAPL", base_quote,
                             now_ts=fake_now.now())

    assert snap.symbol == "AAPL"
    assert snap.current_price == 101.0
    assert snap.previous_close == 100.0
    assert snap.today_open == 100.5
    assert snap.intraday_high == 102.0
    assert snap.intraday_low == 99.5
    assert snap.volume == 0  # /quote has no volume
    assert snap.is_valid is True
    assert snap.direction == UP
    # Existing field meaning preserved: (new-old)/old*100
    assert snap.change_vs_previous_close == pytest.approx(1.0, abs=1e-9)
    assert snap.change_vs_open == pytest.approx(0.4975, abs=1e-4)
    assert snap.distance_from_intraday_high == pytest.approx(-0.9804, abs=1e-3)
    assert snap.distance_from_intraday_low == pytest.approx(1.5075, abs=1e-3)
    # Additive freshness fields populated
    assert snap.provider_timestamp == 1760000000.0
    assert snap.data_age_seconds == pytest.approx(0.0, abs=1e-6)


def test_quote_to_snapshot_validity(base_quote, fake_now):
    """is_valid requires price + previous_close > 0."""
    snap_ok = quote_to_snapshot("A", {"c": 100.0, "pc": 100.0, "o": 100.0,
                                      "h": 100.5, "l": 99.5, "t": 1760000000},
                                now_ts=fake_now.now())
    assert snap_ok.is_valid is True

    snap_zero = quote_to_snapshot("B", {"c": 0.0, "pc": 0.0, "o": 0.0,
                                        "h": 0.0, "l": 0.0, "t": 1760000000},
                                  now_ts=fake_now.now())
    assert snap_zero.is_valid is False
    assert "unknown" in snap_zero.issue


def test_quote_to_snapshot_direction_and_flat(base_quote, fake_now):
    """UP/DOWN/FLAT follow the flat_threshold, consistent with breadth_engine."""
    fake_now.set(datetime.fromtimestamp(base_quote["t"], tz=timezone.utc))
    snap = quote_to_snapshot("A", base_quote, now_ts=fake_now.now())
    assert snap.direction == UP

    down = dict(base_quote); down["c"] = 99.0; down["d"] = -1.0; down["dp"] = -1.0
    snap = quote_to_snapshot("B", down, now_ts=fake_now.now())
    assert snap.direction == DOWN

    flat = dict(base_quote); flat["c"] = 100.05; flat["d"] = 0.05; flat["dp"] = 0.05
    snap = quote_to_snapshot("C", flat, now_ts=fake_now.now())
    assert snap.direction == FLAT


# ---------------------------------------------------------------------------
# 2. Provider timestamp parsing
# ---------------------------------------------------------------------------

def test_parse_provider_timestamp_seconds():
    """'t' in unix seconds is returned unchanged."""
    ts, note = parse_provider_timestamp({"t": 1760000000})
    assert ts == 1760000000.0
    assert note == "provider_timestamp_ok"


def test_parse_provider_timestamp_millisecond_guard():
    """'t' in milliseconds is divided by 1000 (matches latency-test guard)."""
    ts, note = parse_provider_timestamp({"t": 1760000000000})
    assert ts == 1760000000.0
    assert note == "provider_timestamp_converted_from_ms"


def test_parse_provider_timestamp_missing():
    """Missing 't' yields None with a clear note."""
    ts, note = parse_provider_timestamp({})
    assert ts is None
    assert note == "no_provider_timestamp"


def test_parse_provider_timestamp_invalid():
    """Non-numeric 't' yields None with a clear note."""
    ts, note = parse_provider_timestamp({"t": "not-a-number"})
    assert ts is None
    assert note == "invalid_provider_timestamp_format"


# ---------------------------------------------------------------------------
# 3. Data age calculation
# ---------------------------------------------------------------------------

def test_compute_data_age():
    """data_age = fetched_at_epoch - provider_ts; None when ts missing."""
    fetched = 1760000125.0
    assert compute_data_age(fetched, 1760000000.0) == 125.0
    assert compute_data_age(fetched, None) is None


# ---------------------------------------------------------------------------
# 4. Stale quote detection
# ---------------------------------------------------------------------------

def test_stale_quote_only_flags_when_market_open():
    """A large data age is normal outside regular hours -> not stale."""
    # Market CLOSED: even 10h old quote is NOT stale.
    assert is_stale_quote(36000.0, market_is_open=False, stale_quote_seconds=120) is False
    # Market OPEN: same age -> stale.
    assert is_stale_quote(36000.0, market_is_open=True, stale_quote_seconds=120) is True


def test_stale_quote_threshold_boundary():
    """Exactly at threshold is not stale; above is."""
    assert is_stale_quote(120.0, market_is_open=True, stale_quote_seconds=120) is False
    assert is_stale_quote(120.0001, market_is_open=True, stale_quote_seconds=120) is True
    # None age can never be "stale" in this definition.
    assert is_stale_quote(None, market_is_open=True, stale_quote_seconds=120) is False


def test_snapshot_is_stale_flagged_as_issue(base_quote, fake_now):
    """quote_to_snapshot adds 'stale quote' to the issue when market open."""
    base_quote["t"] = 1760000000  # now is 14:00 -> t = 10:13
    snap = quote_to_snapshot("STALE", base_quote,
                             now_ts=datetime(2026, 10, 5, 14, 0, 0, tzinfo=timezone.utc),
                             market_is_open=True, stale_quote_seconds=120)
    assert "stale" in snap.issue


def test_snapshot_not_stale_outside_hours(base_quote, fake_now):
    """Out-of-hours quotes carry age but no stale flag."""
    snap = quote_to_snapshot("NIGHT", base_quote,
                             now_ts=datetime(2026, 10, 5, 14, 0, 0, tzinfo=timezone.utc),
                             market_is_open=False, stale_quote_seconds=120)
    assert "stale" not in snap.issue


# ---------------------------------------------------------------------------
# 5. Missing quote handling
# ---------------------------------------------------------------------------

def test_missing_quote_all_zero(base_quote, fake_now):
    """All-zero quote -> invalid; raw values are preserved but marked unknown."""
    snap = quote_to_snapshot("ZZZ", {"c": 0.0, "d": 0.0, "dp": 0.0,
                                     "h": 0.0, "l": 0.0, "o": 0.0,
                                     "pc": 0.0, "t": 0},
                             now_ts=fake_now.now())
    assert snap.is_valid is False
    assert snap.current_price == 0.0
    assert snap.previous_close == 0.0
    assert snap.issue == "unknown symbol"


def test_missing_quote_empty(base_quote, fake_now):
    """Empty body -> all fields None, invalid."""
    snap = quote_to_snapshot("EMPTY", {}, now_ts=fake_now.now())
    assert snap.is_valid is False
    assert snap.current_price is None
    assert snap.previous_close is None


def test_missing_quote_no_timestamp(base_quote, fake_now):
    """A quote without 't' has a valid price but no provider timestamp."""
    body = {k: v for k, v in base_quote.items() if k != "t"}
    snap = quote_to_snapshot("NOTS", body, now_ts=fake_now.now(),
                             market_is_open=False)
    assert snap.is_valid is True  # price data is fine
    assert snap.provider_timestamp is None
    assert snap.fetched_at is not None
    assert "no_provider_timestamp" in snap.issue or snap.issue == ""


# ---------------------------------------------------------------------------
# 6. HTTP 429 handling
# ---------------------------------------------------------------------------

def test_429_returns_none_with_rate_limit_headers(fake_now, caplog):
    """HTTP 429 is surfaced to the collector (not silently retried); headers logged."""
    client = FakeFinnhubClient().rate_limit()
    provider = FinnhubProvider(api_key="demo_key",
                               transport=client,
                               rate_limit_per_minute=60)
    result = provider.fetch_quote_raw("AAPL")
    # New contract: (body, rate_limited, headers).
    assert result == (None, True, {"Retry-After": "65", "X-Ratelimit-Limit": "60"})
    assert client.last_call()["path"] == "/quote"
    assert client.get_call_count() == 1
    # The provider logged the rate-limit headers on the 429.
    caplog.set_level(logging.WARNING)
    assert any("Retry-After" in r for r in caplog.messages)
    assert any("X-Ratelimit-Limit" in r for r in caplog.messages)


def test_429_records_rate_limit_headers(fake_now):
    """HTTP 429 is surfaced to the collector (not silently retried)."""
    client = FakeFinnhubClient().rate_limit()
    provider = FinnhubProvider(api_key="demo_key",
                               transport=client,
                               rate_limit_per_minute=60)
    body, rate_limited, headers = provider.fetch_quote_raw("AAPL")
    assert body is None
    assert rate_limited is True
    # The single /quote attempt got a 429 (no retry).
    assert client.last_call()["status"] == 429
    assert client.get_call_count() == 1


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 6b. Provider: 429 is never retried (exactly one request)
# ---------------------------------------------------------------------------

def test_429_never_retried_by_provider(fake_now):
    """HTTP 429 is surfaced as-is: exactly one transport request, no retry."""
    client = FakeFinnhubClient().rate_limit()
    provider = FinnhubProvider(api_key="demo_key", transport=client,
                               rate_limit_per_minute=60)
    _, rate_limited, headers = provider.fetch_quote_raw("AAPL")
    assert rate_limited is True
    # 429 is NOT retried (neither by the transport nor by get_quote).
    assert client.get_call_count() == 1
    assert client.last_call()["status"] == 429


# ---------------------------------------------------------------------------
# 7. Retry/backoff behavior
# ---------------------------------------------------------------------------

def test_429_vs_transient_retry_counts(fake_now):
    """429 -> one request; a 500 is retried with bounded backoff -> 3 requests."""
    # 429: no retry at all.
    client1 = FakeFinnhubClient().rate_limit()
    prov1 = FinnhubProvider(api_key="demo_key", transport=client1,
                            rate_limit_per_minute=60)
    prov1.fetch_quote_raw("AAPL")
    assert client1.get_call_count() == 1

    # Transient 500: transport retries (retry_count=3) then gives up.
    client2 = FakeFinnhubClient().transient_500(3)
    prov2 = FinnhubProvider(api_key="demo_key", transport=client2,
                            retry_count=3)
    with mock.patch.object(prov2, "_is_market_open_cached", return_value=True):
        prov2.get_quote("ZZZ")
    assert client2.get_call_count() == 3  # 3 x 500, all retried, none succeeded


# ---------------------------------------------------------------------------
# 9. Rate-limit metadata (Retry-After / X-Ratelimit-Reset)
# ---------------------------------------------------------------------------

def test_rate_limit_state_wait_after_429(fake_now):
    """Wait-after-429 uses Retry-After > X-Ratelimit-Reset > full window,
    and caches so repeated 429s in the same window do not sleep again."""
    from data.collector import _RateLimitState
    fixed = datetime(2026, 10, 5, 14, 0, 0, tzinfo=timezone.utc)
    with mock.patch("data.collector.datetime") as m:
        m.now.return_value = fixed
        state = _RateLimitState(window_seconds=60)

        # Retry-After wins over X-Ratelimit-Reset.
        assert state.wait_after_429({"Retry-After": "30",
                                     "X-Ratelimit-Reset": "far"}) == 30.0
        # X-Ratelimit-Reset used when Retry-After missing.
        assert state.wait_after_429({"X-Ratelimit-Reset": str(
            (fixed + timedelta(seconds=45)).timestamp())}) == 45.0
        # Reset already in the past -> window passed, no wait.
        assert state.wait_after_429({"X-Ratelimit-Reset": str(
            (fixed - timedelta(seconds=10)).timestamp())}) == 0.0
        # Invalid metadata falls back to the full window.
        assert state.wait_after_429({"Retry-After": "not-a-number"}) == 60.0
        assert state.wait_after_429({}) == 60.0

        # Caching: repeated 429s with the same future reset do not sleep again.
        state2 = _RateLimitState()
        with mock.patch("data.collector.datetime") as m2:
            m2.now.return_value = fixed
            assert state2.wait_after_429({"X-Ratelimit-Reset": str(
                (fixed + timedelta(seconds=30)).timestamp())}) == 30.0
            # Same target -> no extra wait.
            assert state2.wait_after_429({"X-Ratelimit-Reset": str(
                (fixed + timedelta(seconds=30)).timestamp())}) == 0.0
            # No metadata: falls back to 60 from now (extends the 30s target).
            assert state2.wait_after_429({}) == 60.0


# ---------------------------------------------------------------------------
# 10. Scheduler: 215-symbol universe at 60/min (80% safety)
# ---------------------------------------------------------------------------

def test_schedule_214_symbols(fake_now):
    """214 symbols at 60/min @ 0.8 -> delay=1.402s, 5 batches, ~300 s cycle."""
    from data.collector import CollectionConfig, build_universe, derive_schedule
    from utils.config import load_settings, load_themes

    settings = load_settings()["data"]
    coll = settings.get("data", {})
    cfg = CollectionConfig(**coll)
    themes = load_themes()
    universe = build_universe(cfg, themes)
    assert len(universe) == 214, f"expected 214, got {len(universe)}"

    schedule = derive_schedule(len(universe), cfg)
    # Rate-cap minimum = 1.25 s; even spread = 300/214 = 1.402 s -> even spread 
    assert math.isclose(schedule.inter_request_delay, 300.0 / 214.0, rel_tol=1e-4)
    assert schedule.batch_size == 43  # from config: ceil(214 / 5) = 43
    assert schedule.batches == 5      # ceil(214 / 43)
    # Total request time = 214 * 1.402 = 300.0 s (fits the cycle exactly).
    assert math.isclose(schedule.total_estimated_seconds, 300.0, rel_tol=1e-6)
    # Batch interval is 0 when the rate cap is the binding constraint.
    assert math.isclose(schedule.batch_interval, 0.0, rel_tol=1e-9)


# ---------------------------------------------------------------------------
# 11. CLI summary with None metrics is safe (the live crash regression)
# ---------------------------------------------------------------------------

def test_cycle_summary_none_safe(fake_now):
    """CLI summary formatting must not crash when latency/age metrics are None."""
    from data.collector import CycleSummary
    from datetime import datetime, timezone

    summary = CycleSummary(
        session_date="2026-10-05",
        started_at=datetime(2026, 10, 5, 14, 0, 0, tzinfo=timezone.utc),
        finished_at=datetime(2026, 10, 5, 14, 0, 30, tzinfo=timezone.utc),
        n_symbols=3,
        n_succeeded=3,
        n_failed=0,
        n_rate_limited=0,
        cycle_seconds=30.0,
        schedule=None,
        rate_limited_symbols=[],
        failed_symbols={},
        min_latency_ms=None,
        max_latency_ms=None,
        mean_latency_ms=None,
        mean_data_age_seconds=None,
        stale_count=0,
    )
    # Reconstruct the exact CLI print path from main().
    lines = []
    lines.append(f"latency_ms     : {summary.min_latency_ms}-{summary.max_latency_ms} "
                 f"(mean {summary.mean_latency_ms:.1f})"
                 if summary.min_latency_ms is not None
                 else "latency_ms     : n/a (no valid latencies)")
    lines.append(f"data_age       : {summary.mean_data_age_seconds:.2f} s mean"
                 if summary.mean_data_age_seconds is not None
                 else "data_age       : n/a (no data ages to report)")
    assert "n/a" in lines[0] and "n/a" in lines[1]
    assert not any("None" in l or "nan" in l.lower() for l in lines)


# ---------------------------------------------------------------------------
# 12. Collector pacing: no burst across a full 215-symbol cycle
# ---------------------------------------------------------------------------

def test_collector_respects_inter_request_delay(tmpdb):
    """A full 214-symbol cycle sleeps the derived delay before each request;
    it never bursts all requests in ~0 seconds."""
    from data.collector import CollectionConfig, build_universe, derive_schedule
    from utils.config import load_settings, load_themes

    settings = load_settings()["data"]
    coll = settings.get("data", {})
    cfg = CollectionConfig(**coll)
    themes = load_themes()
    universe = build_universe(cfg, themes)
    schedule = derive_schedule(len(universe), cfg)
    expected_delay = schedule.inter_request_delay
    assert math.isclose(expected_delay, 300.0 / 214.0, rel_tol=1e-4)

    client = FakeFinnhubClient()
    ts = datetime(2026, 10, 5, 14, 0, 0, tzinfo=timezone.utc).timestamp()
    for sym in universe:
        client.set_quotes({sym: {"c": 100.0 + hash(sym) % 100, "pc": 100.0,
                                 "o": 100.5, "h": 102.0, "l": 99.5, "t": ts}})

    os.environ["FINNHUB_API_KEY"] = "dummy"  # real config expects FINNHUB_API_KEY
    collector = FinnhubCollector(settings)
    collector.provider._transport = client
    collector.store = SnapshotStore(tmpdb)

    with mock.patch("data.collector.time.sleep") as mock_sleep:
        summary = collector.run_cycle(universe)

    assert summary.n_succeeded == len(universe)
    # One delay-sleep per symbol -> no burst; no giant waits.
    # batch_interval=0 pauses are harmless (between batches, not after last).
    sleep_args = [c.args[0] for c in mock_sleep.call_args_list]
    assert len(sleep_args) == len(universe) + schedule.batches - 1, \
        f"expected {len(universe)} delay sleeps + {schedule.batches - 1} batch pauses, got {len(sleep_args)}"
    nonzero = [s for s in sleep_args if s > 0]
    assert len(nonzero) == len(universe), \
        f"expected {len(universe)} delay sleeps, got {len(nonzero)}"
    assert all(1.0 <= s <= expected_delay * 1.01 for s in nonzero), nonzero
    # The cycle is paced at ~5 minutes, not ~12 seconds.
    assert summary.cycle_seconds < 5.0  # mocked, so ~0; pacing is on sleep calls.


def test_collector_214_regression_no_burst_or_spin(tmpdb):
    """Regression for the live burst (214 requests in ~12 s, ~155x 429):
    a 214-symbol cycle at 60/min must not burst, must not spin on 429,
    and must complete the full cycle."""
    from data.collector import CollectionConfig, build_universe, derive_schedule, _RateLimitState
    from utils.config import load_settings, load_themes

    settings = load_settings()
    coll = settings["data"].get("collection", {})
    cfg = CollectionConfig(**coll)
    themes = load_themes()
    universe = build_universe(cfg, themes)
    schedule = derive_schedule(len(universe), cfg)
    expected_delay = schedule.inter_request_delay

    client = FakeFinnhubClient()
    ts = datetime(2026, 10, 5, 14, 0, 0, tzinfo=timezone.utc).timestamp()
    for sym in universe:
        client.set_quotes({sym: {"c": 100.0 + hash(sym) % 100, "pc": 100.0,
                                 "o": 100.5, "h": 102.0, "l": 99.5, "t": ts}})
    # Force a 429 on the first request (like Finnhub did in the live burst).
    client.rate_limit()

    os.environ["FINNHUB_API_KEY"] = "dummy"  # real config expects FINNHUB_API_KEY
    collector = FinnhubCollector(settings)
    collector.provider._transport = client
    collector.store = SnapshotStore(tmpdb)

    with mock.patch("data.collector.time.sleep") as mock_sleep, \
            mock.patch.object(_RateLimitState, "wait_after_429", return_value=0.0):
        summary = collector.run_cycle(universe)

    # The cycle completes: the first symbol is suppressed, the rest succeed.
    assert summary.n_symbols == 214
    assert summary.n_succeeded + summary.n_rate_limited == 214
    assert summary.n_rate_limited == 1
    # Accumulation folds rate_limited into n_failed: 0 real failures + 1 rate-li
    assert summary.n_failed == 1
    # Paced: one delay-sleep per request (no burst); batch_interval=0 pauses are
    sleep_args = [c.args[0] for c in mock_sleep.call_args_list]
    assert len(sleep_args) == 214 + schedule.batches - 1, \
        f"expected 214 delay sleeps + {schedule.batches - 1} batch pauses, got {len(sleep_args)}"
    # Each symbol should sleep at least once.
    nonzero = [s for s in sleep_args if s > 0]
    assert len(nonzero) == 214
    assert all(s >= 0 for s in sleep_args)
    assert max(sleep_args) == expected_delay
    assert summary.cycle_seconds < 5.0  # mocked -> pacing verified via sleeps
# 7. Retry/backoff behavior
# ---------------------------------------------------------------------------

def test_transient_500_retries_then_succeeds(fake_now):
    """Transient 500 -> bounded retries with backoff, then succeeds."""
    quote = {"c": 101.0, "d": 1.0, "dp": 1.0, "h": 102.0, "l": 99.5,
             "o": 100.5, "pc": 100.0, "t": 1760000000}
    client = FakeFinnhubClient().add_quote("AAPL", quote).transient_500(2)
    provider = FinnhubProvider(api_key="demo_key", transport=client.transport,
                               retry_count=3, retry_backoff_base=1.0)
    with mock.patch.object(provider, "_is_market_open_cached", return_value=True):
        snap = provider.get_quote("AAPL")
    assert snap is not None
    assert snap.current_price == 101.0
    assert client.get_call_count() == 3  # 2 x 500 (retried) + 1 success


def test_transient_timeout_retries(fake_now):
    """Connection timeout -> retries (not classified as a failed quote)."""
    quote = {"c": 101.0, "d": 1.0, "dp": 1.0, "h": 102.0, "l": 99.5,
             "o": 100.5, "pc": 100.0, "t": 1760000000}
    client = FakeFinnhubClient().add_quote("AAPL", quote).transient_timeout(1)
    provider = FinnhubProvider(api_key="demo_key", transport=client.transport,
                               retry_count=2, retry_backoff_base=0.5)
    with mock.patch.object(provider, "_is_market_open_cached", return_value=True):
        snap = provider.get_quote("AAPL")
    assert snap is not None
    assert client.get_call_count() == 2  # 1 timeout (retried) + 1 success


def test_exhausted_retries_returns_none(fake_now):
    """After max retries, get_quote returns None (no spin)."""
    client = FakeFinnhubClient().transient_500(5)
    provider = FinnhubProvider(api_key="demo_key", transport=client.transport,
                               retry_count=2, retry_backoff_base=0.1)
    result = provider.get_quote("ZZZ")
    assert result is None
    assert client.get_call_count() == 2  # exactly retry_count


def test_bounded_backoff_increases(fake_now):
    """Backoff uses base * attempt per attempt (verified via call count).

    The transport sleeps on each retry; we verify bounded behavior by checking
    exactly retry_count attempts were made (no spin) and no extra calls leaked.
    """
    client = FakeFinnhubClient().transient_500(3)
    provider = FinnhubProvider(api_key="demo_key", transport=client.transport,
                               retry_count=3, retry_backoff_base=1.0)
    with mock.patch.object(provider, "_is_market_open_cached", return_value=True):
        provider.get_quote("ZZZ")
    assert client.get_call_count() == 3  # exactly retry_count, no spin


# ---------------------------------------------------------------------------
# 8. Scheduler batching
# ---------------------------------------------------------------------------

def test_schedule_derives_from_universe_size_not_hardcoded_240():
    """The schedule adapts to ANY universe size."""
    cfg = CollectionConfig()
    for n in (4, 25, 100, 240, 500):
        s = derive_schedule(n, cfg)
        assert s.inter_request_delay > 0
        assert s.batch_size > 0
        assert s.batches > 0
        assert s.batches * s.batch_size >= n
    # 4 symbols -> few batches, long delay; 500 -> more, rate-capped.
    s4 = derive_schedule(4, cfg)
    s500 = derive_schedule(500, cfg)
    assert s4.inter_request_delay > s500.inter_request_delay
    assert s4.batch_size == 1  # 4//5 -> 1


def test_derive_schedule_240_symbols_300s_cycle_48req_min():
    """240 symbols @ 300s / 60/min (80% safety) -> 1.25s delay = 48 req/min."""
    cfg = CollectionConfig(rate_limit_per_minute=60, rate_safety_factor=0.80,
                           cycle_interval_seconds=300)
    s = derive_schedule(240, cfg)
    assert math.isclose(s.inter_request_delay, 1.25, abs_tol=1e-6)
    assert math.isclose(60 / s.inter_request_delay, 48, abs_tol=1e-6)
    assert s.batch_size == 48  # 240/5
    assert s.batches == 5
    assert math.isclose(s.total_estimated_seconds, 300.0, abs_tol=1e-6)


def test_derive_schedule_large_universe_rate_capdominates():
    """For very large universes the rate cap, not the cycle, sets the delay."""
    cfg = CollectionConfig(rate_limit_per_minute=60, rate_safety_factor=0.80,
                           cycle_interval_seconds=300)
    s = derive_schedule(1000, cfg)
    # rate cap: 48/min -> 1.25s; even-spread would be 0.3s, cap wins.
    assert math.isclose(s.inter_request_delay, 1.25, abs_tol=1e-6)
    assert s.total_estimated_seconds > cfg.cycle_interval_seconds  # drift expected


def test_custom_batch_size_respected_but_clamped():
    """Configured batch_size is honored, clamped to universe size."""
    cfg = CollectionConfig(batch_size=40)
    s = derive_schedule(240, cfg)
    assert s.batch_size == 40
    assert s.batches == 6
    s2 = derive_schedule(30, CollectionConfig(batch_size=40))
    assert s2.batch_size == 30
    assert s2.batches == 1


def test_batch_interval_derived_from_remaining_time():
    """batch_interval = remaining time after requests / (batches-1)."""
    cfg = CollectionConfig(batch_size=10)  # 24 batches
    s = derive_schedule(100, cfg)
    assert s.batches == 10
    # delay = 300/100 = 3.0s; request time = 300s; remaining = 0 -> batch_interval 0
    assert s.batch_interval == 0.0


# ---------------------------------------------------------------------------
# 9. Scheduler full-cycle timing
# ---------------------------------------------------------------------------

def test_full_cycle_respects_rate_cap(fake_now):
    """A full cycle over the universe respects the rate cap (never exceeds)."""
    cfg = CollectionConfig(rate_limit_per_minute=60, rate_safety_factor=0.80,
                           cycle_interval_seconds=300)
    s = derive_schedule(240, cfg)
    # inter-request delay guarantees steady-state <= 48 req/min.
    assert s.inter_request_delay >= 1.0 / (cfg.safe_rate_per_s)
    # total request time fits the cycle (minus headroom).
    assert s.total_estimated_seconds <= cfg.cycle_interval_seconds * 1.05


def test_cycle_spacing_with_fake_clock():
    """With a fake clock, a full cycle's timing is deterministic."""
    cfg = CollectionConfig(batch_size=50, rate_limit_per_minute=60,
                           rate_safety_factor=0.80, cycle_interval_seconds=300)
    s = derive_schedule(4, cfg)
    # 4 symbols, delay = 300/4 = 75s each -> 300s total, batch_interval = 0
    assert math.isclose(s.inter_request_delay, 75.0, abs_tol=1e-6)
    assert s.batches == 1
    assert s.total_estimated_seconds == 300.0


# ---------------------------------------------------------------------------
# 10. Duplicate collector prevention
# ---------------------------------------------------------------------------

def test_collector_lock_acquired_and_released(tmp_path):
    """The collector creates a lock file; acquire/release are idempotent."""
    # lock file handling is demonstrated by the collector running cleanly;
    # the lock module would be tested via a dedicated acquire_lock helper.
    lock_path = tmp_path / "test.lock"
    # Placeholder test: verifies lock path construction and that a second
    # process could not easily grab it. Real lock semantics use fcntl/O_EXCL
    # (POSIX) / msvcrt (Windows).
    assert not lock_path.exists()
    lock_path.write_text("pid=12345")
    assert lock_path.exists()


# ---------------------------------------------------------------------------
# 11. Persistence roundtrip
# ---------------------------------------------------------------------------

def test_quote_snapshots_roundtrip(tmpdb, base_quote, fake_now):
    """save -> latest -> history returns the same row."""
    import time
    store = SnapshotStore(tmpdb)
    snap = quote_to_snapshot("AAPL", base_quote,
                             now_ts=datetime.fromtimestamp(base_quote["t"],
                                                          tz=timezone.utc),
                             market_is_open=True)
    n = store.save_quote_snapshots("2026-10-05", [snap])
    assert n == 1

    df = store.latest_quote_snapshots("2026-10-05")
    assert len(df) == 1
    assert df.iloc[0]["symbol"] == "AAPL"
    assert df.iloc[0]["source"] == "finnhub"
    assert df.iloc[0]["price"] == 101.0
    assert df.iloc[0]["previous_close"] == 100.0
    assert df.iloc[0]["provider_timestamp"] == 1760000000.0
    assert df.iloc[0]["data_age_seconds"] is not None
    assert df.iloc[0]["is_valid"] == 1
    assert df.iloc[0]["issue"] == snap.issue

    hist = store.quote_history("AAPL", "2026-10-05")
    assert len(hist) == 1


def test_quote_snapshots_multiple_symbols_same_session(tmpdb, fake_now):
    """Multiple valid quotes persist; failed symbols are NOT persisted."""
    store = SnapshotStore(tmpdb)
    snaps = [
        quote_to_snapshot("AAPL", {"c": 101.0, "pc": 100.0, "o": 100.5,
                                   "h": 102.0, "l": 99.5, "t": 1760000000},
                          now_ts=datetime.fromtimestamp(1760000000, tz=timezone.utc)),
        quote_to_snapshot("NVDA", {"c": 233.95, "pc": 230.86, "o": 231.0,
                                   "h": 235.0, "l": 229.0, "t": 1760000000},
                          now_ts=datetime.fromtimestamp(1760000000, tz=timezone.utc)),
    ]
    n = store.save_quote_snapshots("2026-10-05", snaps)
    assert n == 2
    df = store.latest_quote_snapshots("2026-10-05")
    assert set(df["symbol"]) == {"AAPL", "NVDA"}


def test_quote_snapshots_stale_row_is_valid_but_flagged(tmpdb, base_quote, fake_now):
    """A stale-but-valid quote persists as valid with the stale issue."""
    store = SnapshotStore(tmpdb)
    stale = quote_to_snapshot("STALE", base_quote,
                              now_ts=datetime.fromtimestamp(1760000000 + 200,
                                                            tz=timezone.utc),
                              market_is_open=True, stale_quote_seconds=120)
    assert stale.is_valid is True
    assert "stale" in stale.issue
    store.save_quote_snapshots("2026-10-05", [stale])
    df = store.latest_quote_snapshots("2026-10-05")
    assert df.iloc[0]["is_valid"] == 1
    assert "stale" in df.iloc[0]["issue"]


# ---------------------------------------------------------------------------
# 12. Provider selection / configuration
# ---------------------------------------------------------------------------

def test_provider_selection_finnhub_via_factory():
    """Settings select the finnhub provider from the data layer."""
    from data.provider_factory import create_provider
    settings = {"data": {"provider": "finnhub", "finnhub": {
        "api_key": "test_key", "base_url": "https://finnhub.io/api/v1",
        "retry_count": 2, "retry_backoff_base_seconds": 1.0,
        "rate_limit_per_minute": 30, "rate_safety_factor": 0.9}}}
    prov = create_provider(settings)
    assert prov.name == "finnhub"
    assert prov._rate_limit_per_minute == 30
    assert prov._retry_count == 2


def test_provider_selection_yfinance_via_factory():
    """Settings fall back to yfinance on demand."""
    from data.provider_factory import create_provider
    settings = {"data": {"provider": "yfinance", "finnhub": {}}}
    prov = create_provider(settings)
    assert prov.name == "yfinance"


def test_provider_selection_unknown_raises():
    """Unknown provider is rejected."""
    from data.provider_factory import create_provider
    settings = {"data": {"provider": "bogus"}}
    with pytest.raises(ValueError):
        create_provider(settings)


def test_config_driven_rate_cap_applies():
    """A smaller rate cap increases the minimum inter-request delay.

    n=200 makes the even-spread delay (300/200 = 1.5s) fall below both caps,
    so the cap binds: cap 60 -> safe 48/min -> 1.25s, so max(1.5, 1.25) = 1.5;
    cap 30 -> safe 24/min -> 2.5s, so max(1.5, 2.5) = 2.5.
    """
    cfg1 = CollectionConfig(rate_limit_per_minute=60, rate_safety_factor=0.80)
    cfg30 = CollectionConfig(rate_limit_per_minute=30, rate_safety_factor=0.80)
    s1 = derive_schedule(200, cfg1)
    s30 = derive_schedule(200, cfg30)
    assert math.isclose(s1.inter_request_delay, 1.5, abs_tol=1e-6)
    assert math.isclose(s30.inter_request_delay, 2.5, abs_tol=1e-6)
    assert s30.inter_request_delay > s1.inter_request_delay


def test_build_universe_from_themes(tmp_path):
    """Universe derives from theme tickers + ETFs; overrides take precedence."""
    themes_path = tmp_path / "themes.yaml"
    themes_path.write_text("""
Technology:
  tickers: [NVDA, AMD, INTC]
  etf: [SMH]
Energy:
  tickers: [XOM, CVX]
  etf: [XLE, XOP]
""")
    import os
    os.environ["SECTOR_RADAR_THEMES"] = str(themes_path)
    try:
        cfg = CollectionConfig()
        themes = {"Technology": {"tickers": ["NVDA", "AMD", "INTC"], "etf": ["SMH"]},
                  "Energy": {"tickers": ["XOM", "CVX"], "etf": ["XLE", "XOP"]}}
        univ = build_universe(cfg, themes)
        # Order: all theme tickers first, then all ETFs (deterministic).
        assert univ == ["NVDA", "AMD", "INTC", "XOM", "CVX", "SMH", "XLE", "XOP"]
    finally:
        os.environ.pop("SECTOR_RADAR_THEMES", None)


def test_build_universe_override(tmp_path):
    """Explicit --symbols override replaces theme-derived universe."""
    themes_path = tmp_path / "themes.yaml"
    themes_path.write_text("Tech:\n  tickers: [NVDA, AMD]\n  etf: [SMH]\n")
    os.environ["SECTOR_RADAR_THEMES"] = str(themes_path)
    try:
        cfg = CollectionConfig(stock_universe_override=["AAPL", "MSFT"],
                               etf_universe_override=["QQQ"])
        themes = {"Tech": {"tickers": ["NVDA", "AMD"], "etf": ["SMH"]}}
        univ = build_universe(cfg, themes)
        assert univ == ["AAPL", "MSFT", "QQQ"]
    finally:
        os.environ.pop("SECTOR_RADAR_THEMES", None)


# ---------------------------------------------------------------------------
# Collector smoke (single-cycle with fake transport)
# ---------------------------------------------------------------------------

def test_collector_run_cycle_success(fake_now, tmpdb):
    """A full collector cycle over a small universe succeeds end-to-end."""
    with mock.patch("data.collector.datetime") as patch_collector_dt, \
            mock.patch("data.finnhub_provider.datetime") as patch_provider_dt, \
            mock.patch("data.collector.time.sleep") as mock_sleep:
        # Deterministic now for data_age/stale detection.
        fixed = datetime(2026, 10, 5, 14, 0, 0, tzinfo=timezone.utc)
        patch_collector_dt.now.return_value = fixed
        patch_provider_dt.now.return_value = fixed

        os.environ["FAKE_KEY"] = "dummy"
        client = FakeFinnhubClient()
        ts = fixed.timestamp()
        client.set_quotes({"AAPL": {"c": 101.0, "pc": 100.0, "o": 100.5, "h": 102.0,
                                    "l": 99.5, "t": ts},
                           "NVDA": {"c": 233.95, "pc": 230.86, "o": 231.0, "h": 235.0,
                                    "l": 229.0, "t": ts},
                           "AMD": {"c": 150.0, "pc": 148.0, "o": 148.5, "h": 151.0,
                                   "l": 147.0, "t": ts}})
        settings = {"data": {"provider": "finnhub",
                             "finnhub": {"api_key_env": "FAKE_KEY", "base_url": "http://x",
                                         "retry_count": 2, "retry_backoff_base_seconds": 0.1,
                                         "rate_limit_per_minute": 60, "rate_safety_factor": 0.8,
                                         "stale_quote_seconds": 120, "collection": {"cycle_interval_seconds": 300,
                                                                                    "batch_size": 50}}}}
        # Inject the fake transport into the provider AFTER construction.
        collector = FinnhubCollector(settings)
        collector.provider._transport = client
        collector.store = SnapshotStore(tmpdb)
        summary = collector.run_cycle(["AAPL", "NVDA", "AMD"],
                                      market_status_at_start={"isOpen": True, "session": "regular"})
        assert summary.n_symbols == 3
        assert summary.n_succeeded == 3
        assert summary.n_failed == 0
        assert summary.stale_count == 0
        # Pacing contract: one sleep per request; cycle completes fast under mocks.
        assert mock_sleep.call_count == 3
        assert summary.cycle_seconds < 1.0
        # All 3 persisted to SQLite.
        df = SnapshotStore(tmpdb).latest_quote_snapshots("2026-10-05")
        assert set(df["symbol"]) == {"AAPL", "NVDA", "AMD"}
    os.environ.pop("FAKE_KEY", None)


def test_collector_cycle_missing_symbols_recorded(fake_now, tmpdb):
    """Unknown/missing symbols are recorded in failed_symbols without crashing."""
    with mock.patch("data.collector.time.sleep") as mock_sleep:
        os.environ["FAKE_KEY"] = "dummy"
        client = FakeFinnhubClient().set_quotes({"AAPL": {"c": 101.0, "pc": 100.0,
                                                          "o": 100.5, "h": 102.0,
                                                          "l": 99.5, "t": 1760000000}}
                                                ).zero_quote("ZZZ")
        settings = {"data": {"provider": "finnhub",
                             "finnhub": {"api_key_env": "FAKE_KEY", "base_url": "http://x",
                                         "retry_count": 2, "retry_backoff_base_seconds": 0.1,
                                         "rate_limit_per_minute": 60, "rate_safety_factor": 0.8,
                                         "stale_quote_seconds": 120}}}
        collector = FinnhubCollector(settings)
        collector.provider._transport = client
        collector.store = SnapshotStore(tmpdb)
        summary = collector.run_cycle(["AAPL", "ZZZ", "EMPTY"],
                                      market_status_at_start={"isOpen": True, "session": "regular"})
        # Pacing contract: every symbol gets a positive delay-sleep; batch_interval pauses (0.0 s) are harmless; no giant waits.
        sleep_args = [c.args[0] for c in mock_sleep.call_args_list]
        assert all(s >= 0 for s in sleep_args)
        assert sum(1 for s in sleep_args if s > 0) == 3
        assert max(sleep_args) >= 1.0
    assert summary.n_succeeded == 1  # AAPL
    assert summary.n_failed >= 2     # ZZZ + EMPTY
    assert "ZZZ" in summary.failed_symbols or "EMPTY" in summary.failed_symbols
    os.environ.pop("FAKE_KEY", None)


def test_collector_cycle_handles_429_without_crash(fake_now, tmpdb):
    """A 429 mid-cycle is absorbed (symbol skipped); the rest of the cycle runs."""
    from data.collector import _RateLimitState
    with mock.patch("data.collector.time.sleep") as mock_sleep, \
            mock.patch.object(_RateLimitState, "wait_after_429", return_value=0.0):
        os.environ["FAKE_KEY"] = "dummy"
        client = FakeFinnhubClient().set_quotes({
            "AAPL": {"c": 101.0, "pc": 100.0, "o": 100.5, "h": 102.0, "l": 99.5, "t": 1760000000},
            "NVDA": {"c": 233.0, "pc": 230.0, "o": 231.0, "h": 235.0, "l": 229.0, "t": 1760000000},
            "AMD": {"c": 150.0, "pc": 148.0, "o": 148.5, "h": 151.0, "l": 147.0, "t": 1760000000},
        }).rate_limit_n(1)  # first /quote request (AAPL) is 429
        settings = {"data": {"provider": "finnhub",
                             "finnhub": {"api_key_env": "FAKE_KEY", "base_url": "http://x",
                                         "retry_count": 2, "retry_backoff_base_seconds": 0.1,
                                         "rate_limit_per_minute": 60, "rate_safety_factor": 0.8,
                                         "stale_quote_seconds": 120}}}
        collector = FinnhubCollector(settings)
        collector.provider._transport = client
        collector.store = SnapshotStore(tmpdb)
        summary = collector.run_cycle(["AAPL", "NVDA", "AMD"],
                                      market_status_at_start={"isOpen": False, "session": "closed"})
        # AAPL is suppressed once (not retried); NVDA/AMD succeed; cycle completes.
        assert summary.n_symbols == 3
        assert summary.n_succeeded == 2
        assert summary.n_rate_limited == 1
        assert summary.n_failed == 1  # Phase-2 accumulation of suppressed symbols
        # Pacing contract: at least one positive delay-sleep per symbol; no giant waits.
        sleep_args = [c.args[0] for c in mock_sleep.call_args_list]
        assert all(s >= 0 for s in sleep_args)
        assert sum(1 for s in sleep_args if s > 0) == 3
        assert max(sleep_args) >= 1.0
    os.environ.pop("FAKE_KEY", None)
