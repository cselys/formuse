"""Theme detail page (spec section 19).

Shows:
  * key metrics for the selected theme
  * all constituent stocks (sortable)
  * the three Plotly charts (return from open, breadth, avg vs median)
  * ETF / basket comparison where available
  * session snapshot history from SQLite

NOTE: Streamlit ignores ``Styler.format`` — values are pre-formatted into
strings; Styler is used for font colors only.
"""
from __future__ import annotations

from typing import Dict, List

import numpy as np
import pandas as pd
import streamlit as st

from models.schemas import DOWN, FLAT, UP
from ui.charts import avg_vs_median_chart, breadth_chart, theme_return_chart
from ui.formatting import (fmt_plain, fmt_signed, missing, plain_color,
                           signed_color, state_label)

_DIRECTION_COLORS = {UP: "#16a34a", DOWN: "#dc2626", FLAT: "#6b7280"}


def _direction_color(label: str) -> str:
    col = _DIRECTION_COLORS.get(label, "#6b7280")
    return f"color:{col};font-weight:700"


def _color_map(sty, col: str, num: pd.Series, color_fn):
    def f(v, i):
        return color_fn(num[i])
    return sty.map(f, subset=[col])


def render_theme_detail(ctx: dict) -> None:
    themes_cfg: Dict[str, dict] = ctx["themes_cfg"]
    metrics: List = ctx["metrics"]
    theme = ctx.get("detail_theme")

    st.subheader("THEME DETAIL")
    if not metrics:
        st.info("No theme data yet.")
        return

    m = next((x for x in metrics if x.theme == theme), None)
    if m is None:
        st.caption("Select a theme in the sidebar to see its constituents, charts and ETF comparison.")
        return

    cfg = themes_cfg.get(m.theme, {"tickers": [], "etf": []})
    window_end = ctx.get("window_end")

    c = st.columns(6)
    c[0].metric("Current Return", fmt_signed(m.average_return),
                delta=f"open {fmt_signed(m.average_change_from_open)}")
    c[1].metric("Median Return", fmt_signed(m.median_return))
    c[2].metric("Up / Down", f"{fmt_plain(m.up_percent)} / {fmt_plain(m.down_percent)}",
                delta=f"{m.up_stocks} up / {m.down_stocks} down")
    c[3].metric("Strong Up / Down",
                f"{fmt_plain(m.strong_up_percent)} / {fmt_plain(m.strong_down_percent)}")
    c[4].metric("Intraday High", fmt_signed(m.intraday_high),
                delta=f"giveback {fmt_signed(m.reversal_from_high, 1, ' pp')}")
    c[5].metric("Intraday Low", fmt_signed(m.intraday_low),
                delta=f"recovery {fmt_signed(m.recovery_from_low, 1, ' pp')}")

    note_bits = [f"Stocks: {m.valid_stocks}/{m.total_stocks} valid"]
    if m.observation_status != "PASS":
        note_bits.append(f"{m.observation_status} ({m.eligible_stocks} eligible constituents)")
    if m.small_sample:
        note_bits.append("⚠️ small sample — treat breadth with care")
    if m.breadth_change_15m is not None and not missing(m.breadth_change_15m):
        note_bits.append(f"breadth Δ15m {m.breadth_change_15m:+.0f} pp")
    state_note = {"TRENDING_UP": "🟢 TRENDING UP", "TRENDING_DOWN": "🔴 TRENDING DOWN",
                  "REVERSING_DOWN": "🟠 REVERSING DOWN", "RECOVERING_UP": "🔵 RECOVERING UP",
                  "MIXED": "⚪ MIXED"}.get(m.state, m.state)
    st.caption(f"**State:** {state_note}   ·   " + "   ·   ".join(note_bits))

    # ------------------------------------------------------- constituents
    st.markdown("**Constituents**")
    stock_metrics: Dict = ctx["stock_metrics"]
    rows = []
    for t in cfg["tickers"]:
        s = stock_metrics.get(t)
        valid = bool(s and s.is_valid)
        rows.append({
            "Ticker": t,
            "_price": s.current_price if valid else None,
            "Price": f"${s.current_price:,.2f}" if valid else "—",
            "_vc": s.change_vs_previous_close if s else None,
            "vs Close": fmt_signed(s.change_vs_previous_close) if s else "—",
            "_vo": s.change_vs_open if s else None,
            "vs Open": fmt_signed(s.change_vs_open) if s else "—",
            "_dh": s.distance_from_intraday_high if s else None,
            "Dist High": fmt_signed(s.distance_from_intraday_high) if s else "—",
            "Volume": f"{s.volume:,.0f}" if valid else "—",
            "_volume": s.volume if valid else 0,
            "State": s.direction if valid else "N/A",
            "Issue": ((s.issue if s else "not in universe") or "—"),
        })

    sort_choice = st.radio(
        "Sort constituents by",
        ["Return (vs close)", "Change from open", "Volume", "Distance from high"],
        horizontal=True,
        key=f"sort_{m.theme}",
    )

    sort_key = {"Return (vs close)": "_vc",
                "Change from open": "_vo",
                "Volume": "_volume",
                "Distance from high": "_dh"}[sort_choice]
    descending = sort_choice != "Distance from high"

    def sort_val(r):
        v = r[sort_key]
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return -np.inf
        return -v if descending else v

    sorted_rows = sorted(rows, key=sort_val)
    df = pd.DataFrame(sorted_rows)
    public_cols = ["Ticker", "Price", "vs Close", "vs Open", "Dist High",
                   "Volume", "State", "Issue"]
    sty = df[public_cols].style.hide(axis="index")
    num = df.set_axis(df[public_cols].index)
    sty = _color_map(sty, "vs Close", num["_vc"], signed_color)
    sty = _color_map(sty, "vs Open", num["_vo"], signed_color)
    sty = _color_map(sty, "Dist High", num["_dh"], signed_color)
    sty = sty.map(lambda v, i: _direction_color(v), subset=["State"])
    sty = sty.map(lambda v, i: "color:#6b7280", subset=["Issue"])
    sty = sty.map(lambda v, i: "color:#374151", subset=["Ticker", "Price", "Volume"])
    st.dataframe(sty, width="stretch",
                 height=min(40, max(len(df), 3)) * 38 + 40)

    # ------------------------------------------------------- charts
    st.markdown("**Intraday charts**")
    ch1, ch2, ch3 = st.columns(3)
    ch1.plotly_chart(theme_return_chart(m.history, m.theme, window_end),
                     width="stretch")
    ch2.plotly_chart(breadth_chart(m.history, m.theme, window_end),
                     width="stretch")
    ch3.plotly_chart(avg_vs_median_chart(m.history, m.theme, window_end),
                     width="stretch")

    # ------------------------------------------------------- ETF comparison
    if m.etf:
        st.markdown("**ETF / basket comparison**")
        display = {
            "ETF": [e.etf for e in m.etf],
            "ETF Return": [fmt_signed(e.etf_return) for e in m.etf],
            "Basket Return": [fmt_signed(e.basket_return) for e in m.etf],
            "Divergence": [fmt_signed(e.divergence, 2, " pp") for e in m.etf],
        }
        numeric = {
            "ETF Return": [e.etf_return for e in m.etf],
            "Basket Return": [e.basket_return for e in m.etf],
            "Divergence": [e.divergence for e in m.etf],
        }
        dfd = pd.DataFrame(display)
        dfn = pd.DataFrame(numeric)
        sty = dfd.style.hide(axis="index")
        sty = _color_map(sty, "ETF Return", dfn["ETF Return"], signed_color)
        sty = _color_map(sty, "Basket Return", dfn["Basket Return"], signed_color)
        sty = _color_map(sty, "Divergence", dfn["Divergence"], signed_color)
        st.dataframe(sty, width="stretch")
        st.caption("The ETF is a market-capitalization-weighted proxy and is NOT one of the "
                   "constituents. Divergence = ETF − basket. Informational only.")

    # ------------------------------------------------------- snapshot history
    store = ctx.get("store")
    session_date = ctx.get("session_date")
    if store is not None and session_date:
        with st.expander("Session snapshots (SQLite)"):
            hist = store.load_sector_history(m.theme, session_date)
            if hist.empty:
                st.caption("No snapshots stored yet for this session.")
            else:
                cols = ["timestamp", "up_percent", "down_percent", "average_return",
                        "median_return", "average_change_from_open", "intraday_high",
                        "intraday_low", "breadth", "state"]
                cols = [c for c in cols if c in hist.columns]
                st.dataframe(hist[cols].tail(96).reset_index(drop=True),
                             width="stretch", height=300)
