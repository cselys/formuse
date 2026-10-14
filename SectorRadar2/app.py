"""Sector Radar — Streamlit entry point.

Run:
    pip install -r requirements.txt
    streamlit run app.py

Architecture:
    app.py        orchestrates: load persisted snapshots -> run engines -> render
    data/         SQLite snapshot store + Finnhub collector
    engine/       pure calculations (price / breadth / reversal / ranking / alerts)
    ui/           Streamlit rendering only
"""
from __future__ import annotations

import copy
import os
import time
import warnings
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from data.cache import SnapshotStore
from data.provider_base import MarketData
from data.snapshot_loader import load_snapshot_market_data, snapshot_from_row
from engine.price_engine import build_all_stock_metrics
from engine.alerts import detect_alerts, top3_by_return
from engine.ranking_engine import build_rankings, composite_scores
from engine.sector_engine import run_sector_engine
from ui.dashboard import render_dashboard
from utils.config import all_symbols, get_setting, load_settings, load_themes
from utils.logging import get_logger
from utils.market_hours import now_et, market_status

logger = get_logger(__name__)

st.set_page_config(page_title="Sector Radar", page_icon="📡", layout="wide")

# ---------------------------------------------------------------------------
# cached resources
# ---------------------------------------------------------------------------
@st.cache_resource
def get_store() -> SnapshotStore:
    return SnapshotStore(os.environ.get("SECTOR_RADAR_DB_PATH", "data/sector_radar.db"))


# ---------------------------------------------------------------------------
# Load persisted Finnhub quote snapshots from SQLite
# ---------------------------------------------------------------------------
def load_finnhub_snapshots(store: SnapshotStore, session_date: str) -> dict:
    """Compatibility loader for callers needing only the latest persisted stocks."""
    df = store.latest_quote_snapshots(session_date=session_date)
    return {row["symbol"]: snapshot_from_row(row) for row in df.to_dict("records")}


# ---------------------------------------------------------------------------
# pipeline: engine -> persistence -> context for the UI
# ---------------------------------------------------------------------------
def run_pipeline(md: MarketData,
                 mkt: dict,
                 settings: dict,
                 themes_cfg: dict,
                 symbols: list,
                 store: SnapshotStore,
                 now,
                 stock_metrics: dict = None) -> dict:
    """Run the calculation pipeline.

    If ``stock_metrics`` are provided (e.g. from persisted Finnhub snapshots),
    they are used directly and ``build_all_stock_metrics`` is skipped so that
    no yfinance/FinnHub data fetch is triggered.  Otherwise the existing
    ``build_all_stock_metrics(md, ...)`` path is used as before.
    """
    t0 = time.monotonic()

    if stock_metrics is None:
        stock_metrics = build_all_stock_metrics(
            md, settings, now, market_is_open=(mkt["status"] == "OPEN"))
    metrics = run_sector_engine(themes_cfg, stock_metrics, md, settings)

    min_size = int(get_setting(settings, "ui.min_theme_size", 5))
    top_n = int(get_setting(settings, "ui.top_n", 6))
    rankings = build_rankings(metrics, settings, min_theme_size=min_size, top_n=top_n)

    composite = None
    if get_setting(settings, "composite.enabled", False):
        composite = composite_scores(metrics, get_setting(settings, "composite.weights", {}))

    alerts = detect_alerts(metrics, st.session_state.get("top3_last"), settings)
    st.session_state["top3_last"] = top3_by_return(metrics)

    session_date = (mkt["session_day"].isoformat() if mkt["session_day"]
                    else now.date().isoformat())
    try:
        store.save_snapshots(session_date, metrics,
                             [s for s in stock_metrics.values() if s.is_valid])
    except Exception:
        logger.exception("failed to persist snapshots")

    dur = time.monotonic() - t0
    logger.info("Calculation completed in %.2f sec (%d themes, %d symbols)",
                dur, len(metrics), len(stock_metrics))
    return {
        "metrics": metrics,
        "rankings": rankings,
        "composite": composite,
        "alerts": alerts,
        "etf_rows": [(m.theme, e) for m in metrics for e in m.etf],
        "stock_metrics": stock_metrics,
        "session_date": session_date,
    }


# ---------------------------------------------------------------------------
# sidebar (spec 30)
# ---------------------------------------------------------------------------
def render_sidebar(settings: dict, themes_cfg: dict) -> dict:
    with st.sidebar:
        st.markdown("## ⚙️ Settings")
        st.caption("Market: US Equities")

        st.markdown("**Scanner**")
        window = st.selectbox(
            "Time window",
            [30, 60, 90, 120, 0],
            index=1,
            format_func=lambda v: "Full day" if v == 0 else f"First {v} minutes",
        )
        min_size = st.number_input(
            "Minimum theme size (valid stocks)", 0, 30,
            int(get_setting(settings, "ui.min_theme_size", 5)), step=1)

        st.markdown("**Thresholds**")
        flat = st.number_input(
            "Up/flat threshold (%)", 0.0, 1.0,
            float(get_setting(settings, "classification.flat_threshold", 0.10)),
            step=0.05, format="%.2f")
        strong = st.number_input(
            "Strong move threshold (%)", 0.5, 5.0,
            float(get_setting(settings, "classification.strong_move_threshold", 1.0)),
            step=0.25, format="%.2f")
        rev_thr = st.number_input(
            "Reversal threshold (pp)", 0.5, 5.0,
            float(get_setting(settings, "state.reversal_threshold", 1.0)),
            step=0.25, format="%.2f")

        st.markdown("**Refresh**")
        auto = st.toggle("Auto Refresh", value=True)
        configured_refresh = get_setting(settings, "data.refresh_seconds", 300)
        # bool is an int subclass; only positive integer seconds are accepted.
        if type(configured_refresh) is not int or configured_refresh <= 0:
            configured_refresh = 300
        refresh_choices = sorted({30, 60, 120, 300, 600, configured_refresh})
        refresh_sec = st.selectbox(
            "Interval", refresh_choices, index=refresh_choices.index(configured_refresh),
            format_func=lambda v: f"{v} seconds")
        default_interval = "5m" if get_setting(settings, "data.intraday_interval", "5m") == "5m" else "1m"
        data_interval = st.radio("Data interval", ["5m", "1m"], horizontal=True,
                                 index=0 if default_interval == "5m" else 1)

        st.markdown("**Show**")
        show = {
            "top_up": st.checkbox("Top Up", value=True),
            "top_down": st.checkbox("Top Down", value=True),
            "broadest_up": st.checkbox("Broadest Up", value=True),
            "broadest_down": st.checkbox("Broadest Down", value=True),
            "reversals": st.checkbox("Reversals", value=True),
            "recoveries": st.checkbox("Recoveries", value=True),
            "etf": st.checkbox("ETF comparison", value=True),
        }

        st.markdown("**Theme detail**")
        detail = st.selectbox("Theme", ["(none)"] + list(themes_cfg.keys()), key="detail_theme")

        st.divider()
        st.caption(f"SQLite: {os.environ.get('SECTOR_RADAR_DB_PATH', 'data/sector_radar.db')}")
        st.caption("Analytics tool — not investment advice.")

    eff = copy.deepcopy(settings)
    eff.setdefault("ui", {})
    eff.setdefault("classification", {})
    eff.setdefault("state", {})
    eff["ui"]["time_window_minutes"] = int(window)
    eff["ui"]["min_theme_size"] = int(min_size)
    eff["classification"]["flat_threshold"] = float(flat)
    eff["classification"]["strong_move_threshold"] = float(strong)
    eff["state"]["reversal_threshold"] = float(rev_thr)
    eff["state"]["recovery_threshold"] = float(rev_thr)

    return {
        "settings": eff,
        "auto": auto,
        "refresh_sec": int(refresh_sec),
        "data_interval": data_interval,
        "show": show,
        "detail_theme": None if detail == "(none)" else detail,
    }


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> None:
    st.set_page_config(page_title="Sector Radar", page_icon="📡", layout="wide")
    settings = load_settings()
    themes_cfg = load_themes()
    symbols = all_symbols(themes_cfg)
    store = get_store()

    sidebar = render_sidebar(settings, themes_cfg)
    eff = sidebar["settings"]

    def ctx_and_render() -> None:
        now = now_et()
        mkt = market_status(now)
        session_date = (mkt["session_day"].isoformat() if mkt["session_day"]
                        else now.date().isoformat())
        # Current stocks, bars, and provider asof come from one consistent read
        # on EVERY fragment refresh, including session rollover.
        md, stock_metrics = load_snapshot_market_data(store, session_date, now)

        p = run_pipeline(md, mkt, eff, themes_cfg, symbols, store, now,
                         stock_metrics=stock_metrics)

        # first-hour scanner window (spec 21)
        window_minutes = int(eff["ui"]["time_window_minutes"])
        window_end = None
        window_note = None
        if window_minutes > 0 and mkt["session_open"] is not None:
            window_end = mkt["session_open"] + timedelta(minutes=window_minutes)
            if now >= window_end:
                window_note = (f"ℹ️ First-{window_minutes}-minute scanner window ended at "
                               f"{window_end.strftime('%I:%M %p').lstrip('0')} ET — "
                               f"extended-session view (metrics stay live).")
            else:
                window_note = (f"⏱️ First-{window_minutes}-minute scanner window: "
                               f"{mkt['session_open'].strftime('%I:%M %p').lstrip('0')}–"
                               f"{window_end.strftime('%I:%M %p').lstrip('0')} ET")

        stale = float(get_setting(eff, "data.stale_warn_minutes", 20.0))
        data_delayed = False
        if mkt["status"] == "OPEN" and md.asof is not None:
            data_delayed = (now - md.asof).total_seconds() / 60.0 > stale

        ctx = {
            "metrics": p["metrics"],
            "rankings": p["rankings"],
            "composite": p["composite"],
            "alerts": p["alerts"],
            "etf_rows": p["etf_rows"],
            "stock_metrics": p["stock_metrics"],
            "settings": eff,
            "mkt": mkt,
            "md": md,
            "last_update": now,
            "data_asof": md.asof,
            "window_end": window_end,
            "window_note": window_note,
            "data_delayed": data_delayed,
            "show": sidebar["show"],
            "detail_theme": sidebar["detail_theme"],
            "themes_cfg": themes_cfg,
            "store": store,
            "session_date": p["session_date"],
        }
        render_dashboard(ctx)

    if sidebar["auto"]:
        @st.fragment(run_every=f"{sidebar['refresh_sec']}s")
        def auto_refresh() -> None:
            ctx_and_render()
        auto_refresh()
    else:
        if st.button("⟳ Refresh now", type="primary"):
            st.session_state.pop("md_cache", None)
            st.session_state["force_refresh"] = True
        ctx_and_render()


if __name__ == "__main__":
    main()
