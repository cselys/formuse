"""Unit tests: multi-theme orchestration, rankings, persistence (spec 35, 25)."""
import pytest

from data.cache import SnapshotStore
from engine.ranking_engine import (biggest_recoveries, biggest_reversals,
                                   composite_scores, top_down, top_up)
from engine.reversal_engine import analyze_history
from engine.sector_engine import run_sector_engine
from tests.conftest import build_metrics


def test_same_ticker_in_multiple_themes(settings):
    """MU may belong to Semiconductor, Memory and AI / Compute at once."""
    md, m = build_metrics(
        {"NVDA": [102.0], "AMD": [104.0], "MU": [105.0]},
        settings=settings,
    )
    themes_cfg = {
        "Semiconductor": {"tickers": ["NVDA", "AMD", "MU"], "etf": []},
        "Memory": {"tickers": ["MU"], "etf": []},
        "AI / Compute": {"tickers": ["NVDA", "MU"], "etf": []},
    }
    out = {x.theme: x for x in run_sector_engine(themes_cfg, m, md, settings)}
    assert out["Semiconductor"].average_return == pytest.approx((2 + 4 + 5) / 3)
    assert out["Semiconductor"].valid_stocks == 3
    assert out["Memory"].average_return == pytest.approx(5.0)
    assert out["Memory"].valid_stocks == 1
    assert out["AI / Compute"].average_return == pytest.approx((2 + 5) / 2)
    assert all(x.valid_stocks > 0 for x in out.values())


def test_missing_stocks_do_not_break_theme(settings):
    """10 configured, 8 valid, 2 missing -> compute with the 8 (spec 23)."""
    md, m = build_metrics({"A": [101.0], "B": [102.0]}, settings=settings)
    themes_cfg = {"T": {"tickers": ["A", "B", "XX1", "XX2"], "etf": []}}
    t = run_sector_engine(themes_cfg, m, md, settings)[0]
    assert t.total_stocks == 4
    assert t.valid_stocks == 2
    assert t.missing_stocks == 2
    assert t.up_percent == pytest.approx(100.0)
    assert t.state is not None  # still classified, gracefully


def test_etf_excluded_from_breadth(settings):
    """ETFs are compared but never counted as constituents (spec 17)."""
    md, m = build_metrics({"A": [101.0], "B": [103.0], "SMH": [99.0]},
                          settings=settings)
    themes_cfg = {"T": {"tickers": ["A", "B"], "etf": ["SMH"]}}
    t = run_sector_engine(themes_cfg, m, md, settings)[0]
    assert t.total_stocks == 2
    assert t.valid_stocks == 2
    assert len(t.etf) == 1
    e = t.etf[0]
    assert e.etf == "SMH"
    assert e.etf_return == pytest.approx(-1.0)
    assert e.basket_return == pytest.approx(2.0)
    assert e.divergence == pytest.approx(-3.0)


def test_small_sample_flag(settings):
    md, m = build_metrics({"A": [101.0], "B": [101.0], "C": [101.0]},
                          settings=settings)
    t = run_sector_engine({"T": {"tickers": ["A", "B", "C"], "etf": []}},
                          m, md, settings)[0]
    assert t.small_sample is True
    assert t.valid_stocks == 3


def test_rankings_ordering(settings):
    md, m = build_metrics({"A": [110.0], "B": [105.0], "C": [90.0], "D": [95.0]},
                          settings=settings)
    themes_cfg = {
        "Up": {"tickers": ["A", "B"], "etf": []},
        "Down": {"tickers": ["C", "D"], "etf": []},
    }
    out = run_sector_engine(themes_cfg, m, md, settings)
    assert top_up(out, 1)[0].theme == "Up"
    assert top_down(out, 1)[0].theme == "Down"
    assert [x.theme for x in top_up(out)] == ["Up", "Down"]
    assert [x.theme for x in top_down(out)] == ["Down", "Up"]


def test_reversal_recovery_rankings(settings):
    md, m = build_metrics({"A": [105.0], "B": [95.0]}, settings=settings)
    themes_cfg = {"T": {"tickers": ["A", "B"], "etf": []}}
    out = run_sector_engine(themes_cfg, m, md, settings)
    # single-bar session: high == low == current -> no reversal/recovery rows
    assert biggest_reversals(out, 6, threshold=0.0) == []
    assert biggest_recoveries(out, 6, threshold=0.0) == []


def test_composite_score_bounds(settings):
    md, m = build_metrics({"A": [110.0], "B": [105.0], "C": [90.0], "D": [95.0]},
                          settings=settings)
    themes_cfg = {
        "U1": {"tickers": ["A", "B"], "etf": []},
        "D1": {"tickers": ["C", "D"], "etf": []},
    }
    out = run_sector_engine(themes_cfg, m, md, settings)
    scores = composite_scores(out, {"breadth": 0.4, "avg_return": 0.3,
                                    "median_return": 0.2, "volume": 0.1})
    assert set(scores) == {"U1", "D1"}
    assert all(0.0 <= v <= 100.0 for v in scores.values())
    assert scores["U1"] > scores["D1"]


def test_to_json_shape(settings):
    """The V2 AI layer consumes this exact structure (spec 28)."""
    md, m = build_metrics({"A": [101.0], "B": [102.0]}, settings=settings)
    t = run_sector_engine({"T": {"tickers": ["A", "B"], "etf": []}},
                          m, md, settings)[0]
    j = t.to_json()
    for key in ("theme", "average_return", "median_return", "up_percent",
                "strong_up_percent", "change_from_open", "intraday_high",
                "reversal_from_high", "breadth_momentum_15m", "state"):
        assert key in j
    assert j["theme"] == "T"
    assert j["average_return"] == pytest.approx(1.5)


def test_snapshot_store_roundtrip(tmp_path, settings):
    md, m = build_metrics({"A": [101.0], "B": [102.0]}, settings=settings)
    out = run_sector_engine({"T": {"tickers": ["A", "B"], "etf": []}},
                            m, md, settings)
    store = SnapshotStore(tmp_path / "radar.db")
    n = store.save_snapshots("2026-10-02", out,
                             [s for s in m.values() if s.is_valid])
    assert n == 1 + 2

    df = store.load_sector_history("T", "2026-10-02")
    assert len(df) == 1
    assert float(df.iloc[0]["up_percent"]) == pytest.approx(100.0)
    assert float(df.iloc[0]["average_return"]) == pytest.approx(1.5)

    sdf = store.load_stock_history("A", "2026-10-02")
    assert len(sdf) == 1
    assert float(sdf.iloc[0]["change_vs_close"]) == pytest.approx(1.0)
    assert float(sdf.iloc[0]["price"]) == pytest.approx(101.0)

    # idempotent upsert: re-saving the same timestamp replaces, not duplicates
    store.save_snapshots("2026-10-02", out,
                         [s for s in m.values() if s.is_valid])
    assert len(store.load_sector_history("T", "2026-10-02")) == 1
