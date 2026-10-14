"""Main dashboard — the four panels + momentum + ETF + detail (spec 18, 32).

Design goal (spec 32): answer these in <10 seconds:
  1. which themes are going up?          -> TOP UP panel
  2. which themes are going down?        -> TOP DOWN panel
  3. broad or concentrated?              -> Avg vs Median + Up% side by side
  4. which are reversing?                -> REVERSALS panel
  5. which are recovering?               -> RECOVERIES panel
  6. what changed in the last 5-15 min?  -> BREADTH MOMENTUM table

NOTE: Streamlit does NOT apply ``Styler.format`` (display formatting) —
tables are pre-formatted into strings, and Styler is used only for
font colors (which Streamlit does support).
"""
from __future__ import annotations

from typing import List
import math
from numbers import Real

import pandas as pd
import streamlit as st

from models.schemas import ThemeMetrics
from data.freshness import current_signal_policy, classify_eligibility
from ui.formatting import fmt_plain, fmt_signed, fmt_time, plain_color, \
    signed_color, state_color, state_label
from ui.sector_detail import render_theme_detail


# ---------------------------------------------------------------------------
# table building helpers
# ---------------------------------------------------------------------------
def _stocks_cell(m: ThemeMetrics, warn_small: bool) -> str:
    cell = f"{m.valid_stocks}/{m.total_stocks}"
    if m.valid_stocks == 0:
        cell += " ✖"
    elif m.small_sample and warn_small:
        cell += " ⚠️ small"
    return cell


def _color_map(sty, display_df: pd.DataFrame, numeric_df: pd.DataFrame,
               col: str, color_fn) -> "pd.io.formats.style.Styler":
    """Apply a font color from the numeric value to a pre-formatted column.

    Uses Styler.apply(axis=0) (column-wise), the correct pandas 3 API.
    Styler.map() passes only the cell display value (a pre-formatted string);
    we need the *numeric* value from the parallel DataFrame to pick a color.
    Styler.apply receives the whole column as a Series so we can zip it with
    the numeric column and return one CSS string per row.
    """
    num = numeric_df[col].reset_index(drop=True)

    def apply_col(_display_col: pd.Series) -> list:
        return [color_fn(v) for v in num]

    return sty.apply(apply_col, axis=0, subset=[col])


def _panel(rows: List[ThemeMetrics],
           spec: List[tuple],  # (label, ThemeMetrics field, kind)
           empty_note: str,
           warn_small: bool) -> None:
    """Render one ranking panel. kind: text | signed | plain | state | stocks | breadth."""
    if not rows:
        st.caption(f"_{empty_note}_")
        return
    display_cols: dict = {}
    numeric_cols: dict = {}
    for label, field, kind in spec:
        if kind == "stocks":
            # "stocks" is a composite cell built from valid_stocks / total_stocks;
            # ThemeMetrics has no attribute named "stocks".  Do NOT call getattr here.
            display_cols[label] = [_stocks_cell(m, warn_small) for m in rows]
            continue
        if kind == "breadth":
            # Display breadth ratio like "8/8 up" using up_stocks / valid_stocks
            values = []
            for m in rows:
                if m.valid_stocks > 0:
                    values.append(f"{m.up_stocks}/{m.valid_stocks} up")
                else:
                    values.append("0/0")
            display_cols[label] = values
            numeric_cols[label] = [m.up_percent for m in rows]
            continue
        values = [getattr(m, field) for m in rows]
        if kind == "text":
            display_cols[label] = values
        elif kind == "state":
            display_cols[label] = [state_label(v) for v in values]
            numeric_cols[label] = values
        elif kind == "signed":
            display_cols[label] = [fmt_signed(v) for v in values]
            numeric_cols[label] = values
        else:  # plain
            display_cols[label] = [fmt_plain(v) for v in values]
            numeric_cols[label] = values

    dfd = pd.DataFrame(display_cols)
    dfn = pd.DataFrame(numeric_cols)
    sty = dfd.style.hide(axis="index")
    for label, field, kind in spec:
        if kind == "signed":
            sty = _color_map(sty, dfd, dfn, label, signed_color)
        elif kind == "plain":
            sty = _color_map(sty, dfd, dfn, label, plain_color)
        elif kind == "state":
            sty = sty.map(lambda v: state_color(v), subset=[label])
    st.dataframe(sty, width="stretch")


def _sort_key_momentum(rows: List[ThemeMetrics]) -> List[ThemeMetrics]:
    from ui.formatting import missing as _miss
    def k(m: ThemeMetrics):
        v = m.breadth_change_15m if not _miss(m.breadth_change_15m) else (
            m.breadth_change_5m if not _miss(m.breadth_change_5m) else -1e9)
        return -v
    return sorted(rows, key=k)


def _momentum_table(metrics: List[ThemeMetrics]) -> None:
    mom = _sort_key_momentum(metrics)
    if not mom:
        st.caption("No breadth data yet (session just started or data unavailable).")
        return
    display = {
        "Theme": [m.theme for m in mom],
        "Up % Now": [fmt_plain(m.breadth_now) for m in mom],
        "5m Ago": [fmt_plain(m.breadth_5m_ago) for m in mom],
        "15m Ago": [fmt_plain(m.breadth_15m_ago) for m in mom],
        "Δ 5m": [fmt_signed(m.breadth_change_5m, 1, " pp") for m in mom],
        "Δ 15m": [fmt_signed(m.breadth_change_15m, 1, " pp") for m in mom],
    }
    numeric = {
        "5m Ago": [m.breadth_5m_ago for m in mom],
        "15m Ago": [m.breadth_15m_ago for m in mom],
        "Δ 5m": [m.breadth_change_5m for m in mom],
        "Δ 15m": [m.breadth_change_15m for m in mom],
        "Up % Now": [m.breadth_now for m in mom],
    }
    dfd = pd.DataFrame(display)
    dfn = pd.DataFrame(numeric)
    sty = dfd.style.hide(axis="index")
    sty = _color_map(sty, dfd, dfn, "5m Ago", plain_color)
    sty = _color_map(sty, dfd, dfn, "15m Ago", plain_color)
    sty = _color_map(sty, dfd, dfn, "Up % Now", plain_color)
    sty = _color_map(sty, dfd, dfn, "Δ 5m", signed_color)
    sty = _color_map(sty, dfd, dfn, "Δ 15m", signed_color)
    st.dataframe(sty, width="stretch", height=400)


def _etf_table(etf_rows: List[tuple]) -> None:
    if not etf_rows:
        return
    display = {
        "Theme": [t for t, e in etf_rows],
        "ETF": [e.etf for t, e in etf_rows],
        "ETF Return": [fmt_signed(e.etf_return) for t, e in etf_rows],
        "Basket Return": [fmt_signed(e.basket_return) for t, e in etf_rows],
        "Divergence": [fmt_signed(e.divergence, 2, " pp") for t, e in etf_rows],
    }
    numeric = {
        "ETF Return": [e.etf_return for t, e in etf_rows],
        "Basket Return": [e.basket_return for t, e in etf_rows],
        "Divergence": [e.divergence for t, e in etf_rows],
    }
    dfd = pd.DataFrame(display)
    dfn = pd.DataFrame(numeric)
    if dfd["ETF Return"].apply(lambda v: v == "—").all():
        st.caption("No ETF data available right now.")
        return
    sty = dfd.style.hide(axis="index")
    sty = _color_map(sty, dfd, dfn, "ETF Return", signed_color)
    sty = _color_map(sty, dfd, dfn, "Basket Return", signed_color)
    sty = _color_map(sty, dfd, dfn, "Divergence", signed_color)
    st.dataframe(sty, width="stretch", height=300)


def _full_theme_table(metrics: List[ThemeMetrics], warn_small: bool) -> None:
    full = list(metrics)
    if not full:
        st.caption("No theme has valid data yet.")
        return
    display = {
        "Theme": [m.theme for m in full],
        "Stocks": [_stocks_cell(m, warn_small) for m in full],
        "Avg %": [fmt_signed(m.average_return) for m in full],
        "Median %": [fmt_signed(m.median_return) for m in full],
        "vs Open": [fmt_signed(m.average_change_from_open) for m in full],
        "Up %": [fmt_plain(m.up_percent) for m in full],
        "Down %": [fmt_plain(m.down_percent) for m in full],
        "Strong Up %": [fmt_plain(m.strong_up_percent) for m in full],
        "Strong Down %": [fmt_plain(m.strong_down_percent) for m in full],
        "High %": [fmt_signed(m.intraday_high) for m in full],
        "Giveback": [fmt_signed(m.reversal_from_high, 1, " pp") for m in full],
        "Low %": [fmt_signed(m.intraday_low) for m in full],
        "Recovery": [fmt_signed(m.recovery_from_low, 1, " pp") for m in full],
        "Δ5m": [fmt_signed(m.breadth_change_5m, 1, " pp") for m in full],
        "Δ15m": [fmt_signed(m.breadth_change_15m, 1, " pp") for m in full],
        "State": [m.observation_status if m.observation_status != "PASS"
                  else state_label(m.state) for m in full],
    }
    numeric = {
        "Avg %": [m.average_return for m in full],
        "Median %": [m.median_return for m in full],
        "vs Open": [m.average_change_from_open for m in full],
        "High %": [m.intraday_high for m in full],
        "Low %": [m.intraday_low for m in full],
        "Giveback": [m.reversal_from_high for m in full],
        "Recovery": [m.recovery_from_low for m in full],
        "Δ5m": [m.breadth_change_5m for m in full],
        "Δ15m": [m.breadth_change_15m for m in full],
    }
    dfd = pd.DataFrame(display)
    dfn = pd.DataFrame(numeric)
    sty = dfd.style.hide(axis="index")
    for col in numeric:
        sty = _color_map(sty, dfd, dfn, col, signed_color)
    for col in ("Up %", "Down %", "Strong Up %", "Strong Down %", "Stocks"):
        sty = sty.map(lambda v: "color:#374151", subset=[col])
    sty = sty.map(lambda v: state_color(v), subset=["State"])
    st.dataframe(sty, width="stretch", height=420)


# ---------------------------------------------------------------------------
# header
# ---------------------------------------------------------------------------
_STATUS_BADGES = {
    "OPEN": "🟢 OPEN",
    "PREMARKET": "🟠 PRE-MARKET",
    "CLOSED": "⚪ CLOSED",
    "WEEKEND": "⚪ WEEKEND",
    "HOLIDAY": "🔴 HOLIDAY",
}


def _render_header(ctx: dict) -> None:
    mkt, md = ctx["mkt"], ctx["md"]
    st.markdown("# 📡 SECTOR RADAR")
    cols = st.columns([1.05, 1.35, 1.25, 1.25, 1.1])
    cols[0].markdown(f"**Market:** US Equities")
    cols[1].markdown(f"**Data:** {md.source} (delayed — not tick data)")
    cols[2].markdown(f"**Last Update:** {fmt_time(ctx['last_update'])}")
    cols[3].markdown(f"**Data as of:** {fmt_time(ctx['data_asof'])}")
    cols[4].markdown(f"**Market Status:** {_STATUS_BADGES.get(mkt['status'], mkt['status'])}")

    if mkt.get("early_close"):
        st.caption("⚠️ Early close today (calendar).")
    if ctx.get("window_note"):
        st.caption(ctx["window_note"])
    if mkt["status"] == "PREMARKET":
        st.info("Pre-market: regular-session metrics populate after the 09:30 ET open. "
                "Pre-market prices are NOT mixed into session calculations.")
    elif mkt["status"] in ("WEEKEND", "HOLIDAY"):
        st.info(mkt.get("note", "Market is closed."))
    if ctx.get("data_delayed") and mkt["status"] == "OPEN":
        st.caption("ℹ️ Data is from persisted Finnhub snapshots. "
                   "The 'Data as of' timestamp shows the collector session time.")


def _alert_tickers(theme: str, stock_metrics: dict, themes_cfg: dict,
                   settings: dict) -> str:
    """Display only: descending return order for every alert kind."""
    policy = current_signal_policy(settings)
    eligible = []
    for symbol in dict.fromkeys(themes_cfg.get(theme, {}).get("tickers", [])):
        snapshot = stock_metrics.get(symbol)
        if snapshot is None or not classify_eligibility(snapshot, policy).participates_in_current:
            continue
        change = snapshot.change_vs_previous_close
        if isinstance(change, bool) or not isinstance(change, Real) or not math.isfinite(change):
            continue
        eligible.append((symbol, change))
    eligible.sort(key=lambda item: (-item[1], item[0]))
    return " · ".join(f"{symbol} {fmt_signed(change)}" for symbol, change in eligible[:5])


def _render_alerts(alerts: List, stock_metrics: dict, themes_cfg: dict,
                   settings: dict) -> None:
    if not alerts:
        return
    st.subheader("🚨 Alerts")
    for a in alerts[:10]:
        icon = "📉" if "Collapse" in a.kind or "Reversal" in a.kind else "📈"
        st.warning(f"**{a.kind.upper()}** — {a.message}", icon=icon)
        tickers = _alert_tickers(a.theme, stock_metrics, themes_cfg, settings)
        if tickers:
            st.caption(tickers)


# ---------------------------------------------------------------------------
# main entry
# ---------------------------------------------------------------------------
def render_dashboard(ctx: dict) -> None:
    settings = ctx["settings"]
    warn_small = settings.get("ui", {}).get("show_small_sample_warning", True)
    show = ctx["show"]
    rankings = ctx["rankings"]
    metrics: List[ThemeMetrics] = ctx["metrics"]

    _render_header(ctx)
    _render_alerts(ctx["alerts"], ctx["stock_metrics"], ctx["themes_cfg"], settings)

    st.markdown("---")

    # ============================================================
    # LEVEL 1 — MARKET NOW
    # ============================================================
    st.subheader("MARKET NOW")
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("▲ TOP UP")
        st.caption("Themes with the strongest average stock returns.")
        if show.get("top_up", True):
            _panel(
                rankings["top_up"],
                [("Theme", "theme", "text"), ("Avg %", "average_return", "signed"),
                 ("vs Open", "average_change_from_open", "signed"),
                 ("Up %", "up_percent", "plain"), ("Strong Up %", "strong_up_percent", "plain"),
                 ("Stocks", "stocks", "stocks"), ("Breadth", "up_stocks", "breadth"), ("State", "state", "state")],
                "No themes with valid data yet.",
                warn_small,
            )
        else:
            st.caption("_(hidden via sidebar)_")
    with col2:
        st.subheader("▼ TOP DOWN")
        st.caption("Themes with the weakest average stock returns.")
        if show.get("top_down", True):
            _panel(
                rankings["top_down"],
                [("Theme", "theme", "text"), ("Avg %", "average_return", "signed"),
                 ("vs Open", "average_change_from_open", "signed"),
                 ("Down %", "down_percent", "plain"), ("Strong Down %", "strong_down_percent", "plain"),
                 ("Stocks", "stocks", "stocks"), ("Breadth", "down_stocks", "breadth"), ("State", "state", "state")],
                "No themes with valid data yet.",
                warn_small,
            )
        else:
            st.caption("_(hidden via sidebar)_")

    # ============================================================
    # BREADTH CONFIRMATION
    # ============================================================
    st.subheader("BREADTH CONFIRMATION")
    col3, col4 = st.columns(2)
    with col3:
        st.subheader("🟡 BROADEST UP")
        st.caption("Breadth confirmation: themes with the highest share of advancing stocks.")
        if show.get("broadest_up", True):
            _panel(
                rankings["broadest_up"],
                [("Theme", "theme", "text"), ("Up %", "up_percent", "plain"),
                 ("Eligible / Total", "stocks", "stocks"), ("Avg Return", "average_return", "signed")],
                "No breadth confirmation data yet.",
                warn_small,
            )
        else:
            st.caption("_(hidden via sidebar)_")
    with col4:
        st.subheader("🟢 BROADEST DOWN")
        st.caption("Breadth confirmation: themes with the highest share of declining stocks.")
        if show.get("broadest_down", True):
            _panel(
                rankings["broadest_down"],
                [("Theme", "theme", "text"), ("Down %", "down_percent", "plain"),
                 ("Eligible / Total", "stocks", "stocks"), ("Avg Return", "average_return", "signed")],
                "No breadth confirmation data yet.",
                warn_small,
            )
        else:
            st.caption("_(hidden via sidebar)_")

    # ============================================================
    # WHAT IS CHANGING?
    # ============================================================
    st.subheader("WHAT IS CHANGING?")
    st.caption("Themes where participation is expanding or contracting fastest.")
    _momentum_table(metrics)

    # ============================================================
    # PRICE ACTION
    # ============================================================
    st.subheader("PRICE ACTION")
    col5, col6 = st.columns(2)
    with col5:
        st.subheader("🔴 REVERSALS")
        st.caption("Themes pulling back from intraday highs.")
        if show.get("reversals", True):
            _panel(
                rankings["reversals"],
                [("Theme", "theme", "text"), ("Intraday Peak", "intraday_high", "signed"),
                 ("Current", "average_return", "signed"),
                 ("Giveback", "reversal_from_high", "signed"),
                 ("Breadth", "up_percent", "plain"), ("State", "state", "state")],
                "No reversals above the current threshold yet.",
                warn_small,
            )
        else:
            st.caption("_(hidden via sidebar)_")
    with col6:
        st.subheader("🟡 RECOVERIES")
        st.caption("Themes recovering from intraday lows.")
        if show.get("recoveries", True):
            _panel(
                rankings["recoveries"],
                [("Theme", "theme", "text"), ("Intraday Low", "intraday_low", "signed"),
                 ("Current", "average_return", "signed"),
                 ("Recovery", "recovery_from_low", "signed"),
                 ("Breadth", "up_percent", "plain"), ("State", "state", "state")],
                "No recoveries above the current threshold yet.",
                warn_small,
            )
        else:
            st.caption("_(hidden via sidebar)_")

    # ============================================================
    # ETF DIVERGENCE
    # ============================================================
    if show.get("etf", True) and ctx.get("etf_rows"):
        st.subheader("ETF DIVERGENCE")
        st.caption("Themes where ETF pricing differs from the eligible stock basket.")
        _etf_table(ctx["etf_rows"])

    # ============================================================
    # expanders (preserved from original)
    # ============================================================
    if ctx.get("composite"):
        with st.expander("Composite score (experimental — NOT the primary ranking)"):
            st.caption("Min-max normalized blend of breadth, average and median return and volume. "
                       "For reference only; the raw panels above are the source of truth.")
            cdf = pd.DataFrame([
                {"Theme": t, "Score": f"{v:.0f}"} for t, v in sorted(
                    ctx["composite"].items(), key=lambda kv: -kv[1])
            ])
            st.dataframe(cdf.style.hide(axis="index"), width="stretch", height=300)

    # ------------------------------------------------------- full theme table
    with st.expander(f"All themes ({len(metrics)})"):
        _full_theme_table(metrics, warn_small)

    # ------------------------------------------------------- theme detail
    st.divider()
    render_theme_detail(ctx)
