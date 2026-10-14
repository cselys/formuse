"""Shared fixtures and synthetic data builders (spec section 35).

All tests run on synthetic data — no yfinance, no network.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

import pandas as pd
from data.provider_base import MarketData
from engine.price_engine import build_all_stock_metrics
from utils.config import load_settings

SESSION_START = "2026-10-02 09:30:00"


@pytest.fixture
def fake_now():
    """Provide a fake clock for deterministic time testing."""
    from datetime import datetime, timezone

    class Clock:
        def __init__(self, time="2026-10-05 14:00:00"):
            self.now = datetime.strptime(time, "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=timezone.utc
            )
            self.timestamp = self.now.timestamp()

        def now(self, tz=None):
            if tz is None:
                return self.now
            return self.now.astimezone(tz)

        def utcnow(self):
            return self.now

        def __call__(self):
            return self.now

    return Clock()


def make_bars(closes, *, start=SESSION_START, freq="5min", volume=1000.0) -> pd.DataFrame:
    """Synthetic regular-session intraday bars from a list of closes."""
    closes = [float(c) for c in closes]
    opens = [closes[0]] + closes[:-1]
    idx = pd.date_range(start, periods=len(closes), freq=freq, tz="US/Eastern")
    return pd.DataFrame({
        "open": opens,
        "high": [max(o, c) for o, c in zip(opens, closes)],
        "low": [min(o, c) for o, c in zip(opens, closes)],
        "close": closes,
        "volume": [volume] * len(closes),
    }, index=idx)


def make_daily(prev_close, today_open, *, session_date="2026-10-02") -> pd.DataFrame:
    """Three daily bars: two before the session date + the session-date bar.

    previous close  = close of the 2026-10-01 bar
    today open      = open of the session-date bar
    """
    idx = pd.to_datetime([
        pd.Timestamp("2026-09-30"),
        pd.Timestamp("2026-10-01"),
        pd.Timestamp(session_date),
    ])
    return pd.DataFrame({
        "open": [98.0, float(prev_close), float(today_open)],
        "high": [99.0, float(prev_close) + 1.0, float(today_open) + 1.0],
        "low": [97.0, float(prev_close) - 1.0, float(today_open) - 1.0],
        "close": [98.5, float(prev_close), float(today_open)],
        "volume": [1e6, 1e6, 1e6],
    }, index=idx)


@pytest.fixture
def tmpdb():
    """Provide a temporary database path for test snapshot storage."""
    import os
    import tempfile
    path = os.path.join(tempfile.gettempdir(), "sector_radar_test.db")
    # Remove any existing file at this path
    if os.path.exists(path):
        os.remove(path)
    yield path
    # Cleanup after the test
    if os.path.exists(path):
        os.remove(path)


def make_md(bars_map, daily_map=None, *, interval="5m", failed=None) -> MarketData:
    asof = None
    for frame in bars_map.values():
        if frame is not None and not frame.empty:
            t = frame.index.max()
            asof = t if asof is None else max(asof, t)
    return MarketData(
        source="test",
        interval=interval,
        fetched_at=datetime.now(timezone.utc),
        asof=asof,
        bars=bars_map,
        daily=daily_map or {},
        failed=failed or {},
    )


@pytest.fixture
def settings():
    """The real config/settings.yaml — engines must respect the config."""
    return load_settings()


@pytest.fixture
def settings():
    """The real config/settings.yaml — engines must respect the config."""
    return load_settings()


def build_metrics(closes_map, *, settings, prev_close=100.0, today_open=100.0,
                  session="2026-10-02", failed=None):
    """``{sym: [closes...]}`` -> ``(MarketData, {sym: StockSnapshot})``."""
    bars, daily = {}, {}
    for sym, closes in closes_map.items():
        bars[sym] = make_bars(closes)
        daily[sym] = make_daily(prev_close, today_open, session_date=session)
    md = make_md(bars, daily, interval="5m", failed=failed)
    metrics = build_all_stock_metrics(md, settings, now_ts=md.asof, market_is_open=True)
    # Set default data_age_seconds for test snapshots (fresh quotes)
    for snap in metrics.values():
        if snap.is_valid and snap.data_age_seconds is None:
            snap.data_age_seconds = 10.0
    return md, metrics
