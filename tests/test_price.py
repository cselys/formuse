"""Unit tests: per-stock price calculations (spec sections 8, 23, 35).

previous close -> current, open -> current, intraday high/low, distances,
volume, plus the data-quality cases (missing data, duplicates, stale).
"""
import numpy as np
import pandas as pd
import pytest

from engine.price_engine import (build_all_stock_metrics, build_stock_metrics,
                                 clean_bars, daily_reference)
from tests.conftest import build_metrics, make_bars, make_daily


def _idx(periods: int = 3) -> pd.DatetimeIndex:
    return pd.date_range("2026-10-02 09:30", periods=periods, freq="5min", tz="US/Eastern")


def test_change_vs_previous_close(settings):
    bars = make_bars([105.0])
    m = build_stock_metrics("T", bars, 100.0, 100.0,
                            asof=bars.index[-1], now_ts=bars.index[-1])
    assert m.is_valid
    assert m.change_vs_previous_close == pytest.approx(5.0)


def test_change_vs_open(settings):
    bars = make_bars([105.0])
    m = build_stock_metrics("T", bars, 100.0, 102.0,
                            asof=bars.index[-1], now_ts=bars.index[-1])
    assert m.change_vs_open == pytest.approx((105.0 - 102.0) / 102.0 * 100.0)


def test_intraday_high_low_distances_volume(settings):
    idx = _idx(3)
    bars = pd.DataFrame({
        "open": [100.5, 103.0, 107.0],
        "high": [103.5, 107.2, 107.5],
        "low": [100.0, 102.0, 104.8],
        "close": [103.0, 107.0, 105.0],
        "volume": [1000, 2000, 500],
    }, index=idx)
    m = build_stock_metrics("T", bars, 100.0, 100.5,
                            asof=idx[-1], now_ts=idx[-1])
    assert m.current_price == pytest.approx(105.0)
    assert m.intraday_high == pytest.approx(107.5)
    assert m.intraday_low == pytest.approx(100.0)
    assert m.change_vs_previous_close == pytest.approx(5.0)
    assert m.change_vs_open == pytest.approx((105.0 - 100.5) / 100.5 * 100.0)
    assert m.distance_from_intraday_high == pytest.approx((105.0 - 107.5) / 107.5 * 100.0)
    assert m.distance_from_intraday_low == pytest.approx((105.0 - 100.0) / 100.0 * 100.0)
    assert m.volume == 3500
    assert m.direction == "UP"


def test_missing_bars_invalid(settings):
    ts = pd.Timestamp("2026-10-02 09:35", tz="US/Eastern")
    m = build_stock_metrics("T", None, 100.0, 100.0, asof=ts, now_ts=ts)
    assert not m.is_valid
    assert "no intraday data" in m.issue


def test_missing_previous_close_invalid(settings):
    bars = make_bars([101.0])
    m = build_stock_metrics("T", bars, None, 100.0,
                            asof=bars.index[-1], now_ts=bars.index[-1])
    assert not m.is_valid
    assert "previous close" in m.issue


def test_nan_close_rows_dropped(settings):
    idx = _idx(3)
    bars = pd.DataFrame({
        "open": [100.0, 101.0, 102.0],
        "high": [101.0, np.nan, 103.5],
        "low": [99.5, 100.5, 101.5],
        "close": [100.0, np.nan, 103.0],
        "volume": [100.0, 100.0, 100.0],
    }, index=idx)
    m = build_stock_metrics("T", bars, 100.0, 100.0,
                            asof=idx[-1], now_ts=idx[-1])
    assert m.is_valid
    assert m.current_price == pytest.approx(103.0)
    assert m.intraday_high == pytest.approx(103.5)  # NaN row must not poison the high
    assert m.volume == 200  # NaN-close row not counted


def test_duplicate_timestamps_deduped(settings):
    idx = pd.DatetimeIndex(
        ["2026-10-02 09:30", "2026-10-02 09:30", "2026-10-02 09:35"],
        tz="US/Eastern")
    bars = pd.DataFrame({
        "open": [100.0, 101.0, 102.0],
        "high": [100.5, 101.5, 103.0],
        "low": [99.5, 100.0, 101.5],
        "close": [100.0, 101.0, 102.5],
        "volume": [100, 100, 100],
    }, index=idx)
    m = build_stock_metrics("T", bars, 100.0, 100.0,
                            asof=idx[-1], now_ts=idx[-1])
    assert m.is_valid
    assert m.current_price == pytest.approx(102.5)
    assert m.intraday_high == pytest.approx(103.0)
    assert m.volume == 200  # duplicate row not double-counted


def test_stale_quote_flagged_but_still_valid(settings):
    asof = pd.Timestamp("2026-10-02 09:40", tz="US/Eastern")
    now = asof + pd.Timedelta(minutes=30)
    bars = make_bars([101.0])
    m = build_stock_metrics("T", bars, 100.0, 100.0,
                            asof=asof, now_ts=now,
                            market_is_open=True, stale_warn_minutes=20.0)
    assert m.is_valid
    assert "stale quote" in m.issue


def test_no_open_yet(settings):
    bars = make_bars([101.0])
    m = build_stock_metrics("T", bars, 100.0, None,
                            asof=bars.index[-1], now_ts=bars.index[-1])
    assert m.is_valid
    assert m.change_vs_open is None
    assert "open" in m.issue


def test_daily_reference(settings):
    daily = make_daily(100.0, 100.5)
    pc, open_ = daily_reference(daily, "2026-10-02")
    assert pc == pytest.approx(100.0)
    assert open_ == pytest.approx(100.5)


def test_all_metrics_missing_symbol_handled(settings):
    md, m = build_metrics({"A": [101.0]}, settings=settings, failed={"B": "halted"})
    assert m["A"].is_valid
    assert "B" in m
    assert not m["B"].is_valid
    assert "halted" in m["B"].issue
