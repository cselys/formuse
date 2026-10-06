"""Unit tests: reversal, recovery, breadth momentum, and state (spec 12-14, 35)."""
import pandas as pd
import pytest

from engine.reversal_engine import (analyze_history, classify_state,
                                    theme_return_series)
from models.schemas import (MIXED, RECOVERING_UP, REVERSING_DOWN,
                            TRENDING_DOWN, TRENDING_UP)
from tests.conftest import make_bars


def _hist(values, ups=None) -> pd.DataFrame:
    """Synthetic theme return series, one row per 5-minute bar."""
    idx = pd.date_range("2026-10-02 09:35", periods=len(values), freq="5min", tz="US/Eastern")
    n = len(values)
    return pd.DataFrame({
        "avg_return": list(values),
        "median_return": list(values),
        "up_percent": list(ups) if ups is not None else [50.0] * n,
        "down_percent": [50.0] * n,
        "valid_count": [3.0] * n,
    }, index=idx)


def test_reversal_from_high(settings):
    """high +3.2%, current +0.5% -> reversal = -2.7 pp (spec 35)."""
    h = analyze_history(_hist([1.0, 2.0, 3.2, 1.5, 0.5]), settings)
    assert h["intraday_high"] == pytest.approx(3.2)
    assert h["reversal_from_high"] == pytest.approx(0.5 - 3.2)
    # the session low is the current value itself (0.5), so recovery = 0
    assert h["recovery_from_low"] == pytest.approx(0.0)


def test_recovery_from_low(settings):
    """low -3.0%, current -0.5% -> recovery = +2.5 pp (spec 35)."""
    h = analyze_history(_hist([-1.0, -2.0, -3.0, -2.0, -0.5]), settings)
    assert h["intraday_low"] == pytest.approx(-3.0)
    assert h["recovery_from_low"] == pytest.approx(-0.5 - (-3.0))
    # the session high is the current value itself (-0.5), so giveback = 0
    assert h["reversal_from_high"] == pytest.approx(0.0)


def test_breadth_momentum_5m_15m(settings):
    h = analyze_history(_hist([0.0] * 5, ups=[40.0, 50.0, 60.0, 70.0, 80.0]), settings)
    assert h["breadth_now"] == pytest.approx(80.0)
    assert h["breadth_5m_ago"] == pytest.approx(70.0)
    assert h["breadth_15m_ago"] == pytest.approx(50.0)
    assert h["breadth_change_5m"] == pytest.approx(10.0)
    assert h["breadth_change_15m"] == pytest.approx(30.0)


def test_min_history_bars_gate_momentum(settings):
    h3 = analyze_history(_hist([0.0, 0.0, 0.0], ups=[40.0, 50.0, 80.0]), settings)
    assert h3["has_history"] is True
    h2 = analyze_history(_hist([0.0, 0.0], ups=[40.0, 80.0]), settings)
    assert h2["has_history"] is False
    assert h2["breadth_change_5m"] != h2["breadth_change_5m"]  # NaN


def test_empty_history(settings):
    h = analyze_history(None, settings)
    assert h["has_history"] is False
    assert h["reversal_from_high"] != h["reversal_from_high"]  # NaN


def test_state_trending_up(settings):
    assert classify_state(2.0, 1.5, 82.0, 10.0, -0.1, 0.5, settings, True) == TRENDING_UP


def test_state_trending_down(settings):
    assert classify_state(-2.0, -1.5, 10.0, 82.0, 0.5, -0.1, settings, True) == TRENDING_DOWN


def test_state_reversing_down(settings):
    """Spec example: peak +3.4%, current +0.8%, breadth 44% -> REVERSING DOWN."""
    assert classify_state(0.8, 0.3, 44.0, 56.0, -2.6, 0.5, settings, True) == REVERSING_DOWN


def test_state_recovering_up(settings):
    """Spec example: low -3.0%, current -0.4% -> recovery +2.6 pp."""
    assert classify_state(-0.4, -1.0, 40.0, 60.0, -0.6, 2.6, settings, True) == RECOVERING_UP


def test_state_mixed(settings):
    assert classify_state(0.2, 0.1, 55.0, 40.0, 0.0, 0.2, settings, True) == MIXED


def test_reversal_state_requires_history(settings):
    # Same numbers, but without session history we cannot call it a reversal.
    assert classify_state(0.8, 0.3, 44.0, 56.0, -2.6, 0.5, settings, False) != REVERSING_DOWN


def test_theme_return_series_from_bars(settings):
    bars = {
        "A": make_bars([101.0, 103.0, 105.0]),
        "B": make_bars([99.0, 99.0, 100.0]),
    }
    s = theme_return_series(bars, {"A": 100.0, "B": 100.0}, ["A", "B"], 0.10)
    assert len(s) == 3
    assert s["avg_return"].iloc[0] == pytest.approx((1.0 + -1.0) / 2)
    assert s["avg_return"].iloc[1] == pytest.approx((3.0 + -1.0) / 2)
    assert s["avg_return"].iloc[2] == pytest.approx((5.0 + 0.0) / 2)
    assert s["up_percent"].iloc[0] == pytest.approx(50.0)   # A up, B down
    assert s["up_percent"].iloc[2] == pytest.approx(50.0)   # A up, B flat (0%)


def test_theme_return_series_skips_bad_symbols(settings):
    bars = {
        "A": make_bars([101.0, 102.0]),
        "B": pd.DataFrame(),
    }
    s = theme_return_series(bars, {"A": 100.0, "B": None}, ["A", "B"], 0.10)
    assert len(s) == 2
    assert s["avg_return"].iloc[-1] == pytest.approx(2.0)
