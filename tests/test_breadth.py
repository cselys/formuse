"""Unit tests: theme breadth (spec sections 9-11, 35)."""
import pytest

from engine.breadth_engine import classify_direction, compute_breadth
from models.schemas import DOWN, FLAT, UP
from tests.conftest import build_metrics


def test_up_percent_8_of_10(settings):
    """8 up / 10 = 80% (spec section 35)."""
    md, m = build_metrics({
        "S1": [102.0], "S2": [102.0], "S3": [102.0], "S4": [102.0],
        "S5": [102.0], "S6": [102.0], "S7": [102.0], "S8": [102.0],
        "S9": [99.0], "S10": [100.05],
    }, settings=settings)
    b = compute_breadth(list(m.values()), settings)
    assert b["up_stocks"] == 8
    assert b["down_stocks"] == 1
    assert b["flat_stocks"] == 1
    assert b["up_percent"] == pytest.approx(80.0)
    assert b["down_percent"] == pytest.approx(10.0)
    assert b["average_return"] == pytest.approx((8 * 2.0 + (-1.0) + 0.05) / 10)
    assert b["median_return"] == pytest.approx(2.0)


def test_strong_breadth_distinguishes_magnitude(settings):
    """'80% of stocks +0.2%' vs '80% of stocks +2%' — strong breadth differs."""
    md, mild = build_metrics({f"S{i}": [100.5] for i in range(8)}, settings=settings)
    b_mild = compute_breadth(list(mild.values()), settings)
    assert b_mild["up_percent"] == pytest.approx(100.0)
    assert b_mild["strong_up_percent"] == pytest.approx(0.0)

    md, strong = build_metrics({f"S{i}": [102.0] for i in range(8)}, settings=settings)
    b_strong = compute_breadth(list(strong.values()), settings)
    assert b_strong["up_percent"] == pytest.approx(100.0)
    assert b_strong["strong_up_percent"] == pytest.approx(100.0)


def test_flat_threshold_boundary(settings):
    assert classify_direction(0.11, 0.10) == UP
    assert classify_direction(0.10, 0.10) == FLAT
    assert classify_direction(-0.10, 0.10) == FLAT
    assert classify_direction(-0.11, 0.10) == DOWN
    assert classify_direction(None, 0.10) == FLAT


def test_empty_input_no_crash(settings):
    b = compute_breadth([], settings)
    assert b["valid_stocks"] == 0
    assert b["up_percent"] == 0.0
    assert b["average_return"] == 0.0


def test_missing_stocks_excluded_not_fatal(settings):
    """A theme with 10 configured, 8 valid, 2 missing -> '8/10 valid' (spec 23)."""
    md, m = build_metrics(
        {
            "A": [101.0], "B": [102.0], "C": [103.0], "D": [99.0],
            "E": [100.5], "F": [104.0], "G": [106.0], "H": [108.0],
            "I": [110.0], "J": [112.0],
        },
        settings=settings,
        failed={"K": "halted", "L": "no data returned by provider"},
    )
    snapshots = [m[t] for t in list("ABCDEFGHIJ") + ["K", "L"]]
    b = compute_breadth(snapshots, settings)
    assert b["total_stocks"] == 12
    assert b["valid_stocks"] == 10
    assert b["missing_stocks"] == 2
    assert b["up_percent"] == pytest.approx(90.0)  # all up except D


def test_change_from_open_aggregation(settings):
    md, m = build_metrics(
        {"A": [102.0], "B": [98.0]},
        settings=settings,
        prev_close=100.0,
        today_open=101.0,
    )
    b = compute_breadth(list(m.values()), settings)
    expected = ((102.0 / 101.0 - 1) * 100 + (98.0 / 101.0 - 1) * 100) / 2
    assert b["average_change_from_open"] == pytest.approx(expected)
