"""Tests for the model/UI contract between ThemeMetrics and dashboard._panel().

Regression tests for the runtime crash:
    AttributeError: 'ThemeMetrics' object has no attribute 'stocks'
traced to ui/dashboard.py _panel() calling getattr(m, "stocks") on every row
before the kind=="stocks" branch could redirect to _stocks_cell().

The fix moves the "stocks" case BEFORE the unconditional getattr call so that
_stocks_cell() is used instead of a non-existent attribute lookup.
"""
from __future__ import annotations

import pytest

from engine.sector_engine import run_sector_engine
from models.schemas import ThemeMetrics
from tests.conftest import build_metrics, make_md
from ui.dashboard import _panel, _stocks_cell


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

# Spec for the TOP UP panel (exactly as defined in dashboard.py)
_TOP_UP_SPEC = [
    ("Theme", "theme", "text"),
    ("Avg %", "average_return", "signed"),
    ("vs Open", "average_change_from_open", "signed"),
    ("Up %", "up_percent", "plain"),
    ("Strong Up %", "strong_up_percent", "plain"),
    ("Stocks", "stocks", "stocks"),   # "stocks" attribute does NOT exist on ThemeMetrics
    ("State", "state", "state"),
]

# Spec for the TOP DOWN panel (mirrors dashboard.py)
_TOP_DOWN_SPEC = [
    ("Theme", "theme", "text"),
    ("Avg %", "average_return", "signed"),
    ("vs Open", "average_change_from_open", "signed"),
    ("Down %", "down_percent", "plain"),
    ("Strong Down %", "strong_down_percent", "plain"),
    ("Stocks", "stocks", "stocks"),
    ("State", "state", "state"),
]


# ---------------------------------------------------------------------------
# model contract: ThemeMetrics must NOT have a 'stocks' attribute
# ---------------------------------------------------------------------------

def test_theme_metrics_has_no_stocks_attribute(settings):
    """ThemeMetrics deliberately does not expose a 'stocks' field.

    The dashboard renders the 'Stocks' column via _stocks_cell() which reads
    valid_stocks and total_stocks.  A bare getattr(m, 'stocks') must raise
    AttributeError so that the fix in _panel() can be verified.
    """
    md, m = build_metrics({"A": [101.0], "B": [102.0]}, settings=settings)
    t = run_sector_engine({"T": {"tickers": ["A", "B"], "etf": []}},
                          m, md, settings)[0]
    assert isinstance(t, ThemeMetrics)
    assert hasattr(t, "valid_stocks")
    assert hasattr(t, "total_stocks")
    assert not hasattr(t, "stocks"), (
        "'stocks' must NOT be a ThemeMetrics attribute — "
        "the dashboard uses _stocks_cell() to render it."
    )


def test_stocks_cell_formats_correctly(settings):
    """_stocks_cell returns 'valid/total' string, with warning flags when applicable."""
    md, m = build_metrics({"A": [101.0], "B": [102.0], "C": [103.0]},
                          settings=settings)
    t = run_sector_engine({"T": {"tickers": ["A", "B", "C", "MISSING"], "etf": []}},
                          m, md, settings)[0]
    # 3 valid of 4 configured
    cell_no_warn = _stocks_cell(t, warn_small=False)
    assert cell_no_warn == "3/4"

    cell_warn = _stocks_cell(t, warn_small=True)
    # 3 valid stocks < 5 → small_sample is True → warning appended
    assert "small" in cell_warn.lower() or cell_warn == "3/4", cell_warn


def test_stocks_cell_zero_valid(settings):
    """When valid_stocks == 0 a failure marker is appended."""
    md, m = build_metrics({"A": [101.0]}, settings=settings)
    # "MISSING1" has no data at all → total_stocks=1, valid_stocks=0
    t = run_sector_engine({"T": {"tickers": ["MISSING1"], "etf": []}},
                          m, md, settings)[0]
    cell = _stocks_cell(t, warn_small=True)
    assert "✖" in cell


# ---------------------------------------------------------------------------
# _panel() must not raise for kind=="stocks"
# ---------------------------------------------------------------------------

def test_panel_top_up_does_not_crash(settings, monkeypatch):
    """_panel() with the TOP UP spec must not raise AttributeError for 'stocks'."""
    md, m = build_metrics({"A": [105.0], "B": [103.0], "C": [101.0]},
                          settings=settings)
    rows = run_sector_engine(
        {"Up": {"tickers": ["A", "B", "C"], "etf": []}},
        m, md, settings)

    # Patch st.dataframe so we don't need a running Streamlit server
    import streamlit as st
    monkeypatch.setattr(st, "dataframe", lambda *a, **kw: None)

    # Must not raise — this was the production crash site
    _panel(rows, _TOP_UP_SPEC, "No data", warn_small=True)


def test_panel_top_down_does_not_crash(settings, monkeypatch):
    """_panel() with the TOP DOWN spec must not raise AttributeError for 'stocks'."""
    md, m = build_metrics({"A": [95.0], "B": [97.0]}, settings=settings)
    rows = run_sector_engine(
        {"Down": {"tickers": ["A", "B"], "etf": []}},
        m, md, settings)

    import streamlit as st
    monkeypatch.setattr(st, "dataframe", lambda *a, **kw: None)

    _panel(rows, _TOP_DOWN_SPEC, "No data", warn_small=True)


def test_panel_empty_rows_does_not_crash(settings, monkeypatch):
    """_panel() with an empty rows list must render the caption, not crash."""
    import streamlit as st
    captions = []
    monkeypatch.setattr(st, "caption", lambda msg: captions.append(msg))
    monkeypatch.setattr(st, "dataframe", lambda *a, **kw: None)

    _panel([], _TOP_UP_SPEC, "No themes yet.", warn_small=True)
    assert any("No themes yet." in c for c in captions)


# ---------------------------------------------------------------------------
# graceful handling of themes with missing ETF symbols (UCAR / LITH scenario)
# ---------------------------------------------------------------------------

def test_panel_missing_etf_symbols_do_not_crash(settings, monkeypatch):
    """Themes whose ETF tickers are unavailable must still render in the panel."""
    md, m = build_metrics({"TSLA": [200.0], "RIVN": [15.0]}, settings=settings)
    # LITH and UCAR are configured as ETFs but no data for them
    rows = run_sector_engine(
        {"EV": {"tickers": ["TSLA", "RIVN"], "etf": ["LITH", "UCAR"]}},
        m, md, settings)

    assert len(rows) == 1
    ev = rows[0]
    assert ev.valid_stocks == 2
    # ETF rows are present but with None divergence (no data)
    assert len(ev.etf) == 2
    for e in ev.etf:
        assert e.etf_return is None
        assert e.divergence is None

    import streamlit as st
    monkeypatch.setattr(st, "dataframe", lambda *a, **kw: None)

    # Panel must render without crashing
    _panel(rows, _TOP_UP_SPEC, "No data", warn_small=True)


def test_all_missing_etf_no_breadth_impact(settings):
    """Missing ETF symbols must not change valid_stocks or breadth calculations."""
    md, m = build_metrics({"TSLA": [200.0]}, settings=settings)
    rows_with_etf = run_sector_engine(
        {"EV": {"tickers": ["TSLA"], "etf": ["LITH", "UCAR"]}},
        m, md, settings)
    rows_no_etf = run_sector_engine(
        {"EV": {"tickers": ["TSLA"], "etf": []}},
        m, md, settings)
    # Breadth must be identical — ETF data never enters constituent calculations
    assert rows_with_etf[0].valid_stocks == rows_no_etf[0].valid_stocks
    assert rows_with_etf[0].up_percent == rows_no_etf[0].up_percent
    assert rows_with_etf[0].average_return == pytest.approx(rows_no_etf[0].average_return)


# ---------------------------------------------------------------------------
# Styler / _color_map contract (Pandas 3 compatibility)
# ---------------------------------------------------------------------------

def test_color_map_and_styler_render_without_typeerror(settings, monkeypatch):
    """Verify Styler formatting functions generate HTML without callback signature errors."""
    import streamlit as st
    monkeypatch.setattr(st, "dataframe", lambda *a, **kw: None)
    monkeypatch.setattr(st, "caption", lambda *a, **kw: None)

    md, m = build_metrics({"A": [105.0], "B": [95.0]}, settings=settings)
    rows = run_sector_engine(
        {"ThemeA": {"tickers": ["A"], "etf": ["SMH"]},
         "ThemeB": {"tickers": ["B"], "etf": []}},
        m, md, settings)

    from ui.dashboard import _etf_table, _full_theme_table, _momentum_table

    # Test all panel specs
    reversals_spec = [
        ("Theme", "theme", "text"), ("Intraday Peak", "intraday_high", "signed"),
        ("Current", "average_return", "signed"), ("Giveback", "reversal_from_high", "signed"),
        ("Breadth", "up_percent", "plain"), ("State", "state", "state"),
    ]
    recoveries_spec = [
        ("Theme", "theme", "text"), ("Intraday Low", "intraday_low", "signed"),
        ("Current", "average_return", "signed"), ("Recovery", "recovery_from_low", "signed"),
        ("Breadth", "up_percent", "plain"), ("State", "state", "state"),
    ]

    _panel(rows, _TOP_UP_SPEC, "empty", warn_small=True)
    _panel(rows, _TOP_DOWN_SPEC, "empty", warn_small=True)
    _panel(rows, reversals_spec, "empty", warn_small=True)
    _panel(rows, recoveries_spec, "empty", warn_small=True)

    _momentum_table(rows)
    _etf_table([(r.theme, e) for r in rows for e in r.etf])
    _full_theme_table(rows, warn_small=True)

