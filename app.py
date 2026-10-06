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
from datetime import timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from data.cache import SnapshotStore
from data.provider_base import MarketData
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
    """Load the latest quote snapshots from SQLite and convert to StockSnapshot dict.

    Returns a mapping ``{symbol: StockSnapshot}`` keyed by symbol, constructed from
    the ``quote_snapshots`` table so the downstream engine receives pre-built
    per-stock metrics without any yfinance / FinHub network call.
    """
    from models.schemas import StockSnapshot, UP, DOWN, FLAT
    from engine.price_engine import _pct
    from utils.logging import get_logger
    logger = get_logger(__name__)

    df = store.latest_quote_snapshots(session_date=session_date)
    stock_metrics: dict = {}
    for _, row in df.iterrows():
        current_price = row["price"]
        previous_close = row["previous_close"]
        today_open = row["today_open"]

        # change_vs_previous_close
        change_vs_previous_close = _pct(current_price, previous_close)

        # change_vs_open
        change_vs_open = _pct(current_price, today_open)

        # distance_from_intraday_high
        distance_from_intraday_high = _pct(current_price, row["intraday_high"])

        # distance_from_intraday_low
        distance_from_intraday_low = _pct(current_price, row["intraday_low"])

        # direction
        if change_vs_previous_close is not None:
            if change_vs_previous_close > 0.10:
                direction = UP
            elif change_vs_previous_close < -0.10:
                direction = DOWN
            else:
                direction = FLAT
        else:
            direction = FLAT

        snapshot = StockSnapshot(
            symbol=row["symbol"],
            timestamp=row["fetched_at"] or "",
            previous_close=previous_close,
            today_open=today_open,
            current_price=current_price,
            intraday_high=row["intraday_high"],
            intraday_low=row["intraday_low"],
            change_vs_previous_close=change_vs_previous_close,
            change_vs_open=change_vs_open,
            distance_from_intraday_high=distance_from_intraday_high,
            distance_from_intraday_low=distance_from_intraday_low,
            volume=int(row["volume"]) if row["volume"] is not None else 0,
            is_valid=bool(row["is_valid"]),
            issue=row["issue"] or "",
            direction=direction,
            # Additive fields from the persisted snapshot
            provider_timestamp=row["provider_timestamp"],
            fetched_at=row["fetched_at"],
            data_age_seconds=row["data_age_seconds"],
        )
        stock_metrics[row["symbol"]] = snapshot

    return stock_metrics


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
        refresh_sec = st.selectbox(
            "Interval", [30, 60, 120, 300, 600], index=1,
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

    # Determine the session date for snapshot loading
    now_et_val = now_et()
    mkt = market_status(now_et_val)
    session_date = (mkt["session_day"].isoformat() if mkt["session_day"]
                    else now_et_val.date().isoformat())

    # Load the latest persisted Finnhub quote snapshots from SQLite
    stock_metrics = load_finnhub_snapshots(store, session_date)

    # Determine the latest provider timestamp across all persisted snapshots
    latest_provider_ts: Optional[float] = None
    for snap in stock_metrics.values():
        if snap.provider_timestamp is not None:
            if latest_provider_ts is None or snap.provider_timestamp > latest_provider_ts:
                latest_provider_ts = snap.provider_timestamp

    # Convert latest provider timestamp to ET for display
    if latest_provider_ts is not None:
        latest_provider_et = datetime.fromtimestamp(
            latest_provider_ts, tz=ZoneInfo("America/New_York"))
    else:
        latest_provider_et = now_et_val

    # ---------------------------------------------------------------------------
    # Construct MarketData.bars from persisted quote_snapshots history
    # ---------------------------------------------------------------------------
    bars: dict = {}
    latest_fetched_at: Optional[datetime] = None

    for sym in stock_metrics:
        hist = store.quote_history(sym, session_date)
        if hist.empty:
            continue
        # Use the most recent snapshot (last row, ordered by fetched_at)
        row = hist.iloc[-1]
        # Build a single-row DataFrame indexed by fetched_at (ET)
        try:
            idx = pd.to_datetime(row["fetched_at"]).tz_convert(
                ZoneInfo("America/New_York"))
        except Exception:
            idx = pd.to_datetime(row["fetched_at"])
        df = pd.DataFrame(
            {
                "open": [row["today_open"] if row["today_open"] is not None else 0.0],
                "high": [row["intraday_high"] if row["intraday_high"] is not None else 0.0],
                "low": [row["intraday_low"] if row["intraday_low"] is not None else 0.0],
                "close": [row["price"] if row["price"] is not None else 0.0],
                "volume": [int(row["volume"]) if row["volume"] is not None else 0],
            },
            index=[idx],
        )
        bars[sym] = df

        # Track the latest fetched_at across all symbols
        try:
            fa = pd.to_datetime(row["fetched_at"])
            if latest_fetched_at is None or fa > latest_fetched_at:
                latest_fetched_at = fa
        except Exception:
            pass

    # ---------------------------------------------------------------------------
    # Build MarketData with persisted timestamps (NOT Streamlit render time)
    # ---------------------------------------------------------------------------
    if latest_fetched_at is not None:
        # Convert to ET for consistent display
        latest_fetched_et = latest_fetched_at.astimezone(ZoneInfo("America/New_York"))
    else:
        latest_fetched_et = now_et_val

    # Use latest provider timestamp for "Data as of", render time for "Last Update"
    md = MarketData(
        source="finnhub_snapshot",
        interval="5m",
        fetched_at=now_et_val,
        asof=latest_provider_et,
        bars=bars,
        daily={},
        failed={},
    )

    sidebar = render_sidebar(settings, themes_cfg)
    eff = sidebar["settings"]

    def ctx_and_render() -> None:
        nonlocal stock_metrics
        now = now_et()
        mkt = market_status(now)

        # Refresh snapshot data on each rerun — re-read the latest persisted
        # Finnhub quotes from SQLite. No yfinance / FinHub network call is made.
        stock_metrics = load_finnhub_snapshots(store, session_date)

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


main()