"""Canonical Finnhub theme × market-time observations.

See docs/THEME_TIME_ALIGNMENT.md for target selection and coverage rules.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from data.freshness import classify_eligibility, freshness_policy
from data.snapshot_loader import snapshot_from_row
from engine.breadth_engine import compute_breadth


def prepare_quotes(quotes: pd.DataFrame, symbols) -> pd.DataFrame:
    """Keep valid market observations, deterministic ties by latest fetch."""
    q = quotes[quotes["symbol"].isin(symbols)].copy()
    q["provider_timestamp"] = pd.to_numeric(q["provider_timestamp"], errors="coerce")
    q = q[np.isfinite(q["provider_timestamp"]) & (q["provider_timestamp"] > 0)]
    if q.empty:
        return q
    good = [snapshot_from_row(row).is_valid for row in q.to_dict("records")]
    q = q.loc[good].sort_values(["provider_timestamp", "fetched_at", "symbol"], kind="stable")
    return q.drop_duplicates(["symbol", "provider_timestamp"], keep="last")


def observation_at(quotes: pd.DataFrame, symbols, target, settings: dict) -> dict:
    """Latest valid row per constituent at/before T; never use a future quote.

    ``quotes`` must have passed prepare_quotes. Delivery time breaks ties only:
    this is reconstruction of market observations, not a live-availability backtest.
    """
    target = pd.Timestamp(target)
    q = quotes[quotes["provider_timestamp"] <= target.timestamp()]
    latest = q.drop_duplicates("symbol", keep="last")
    stocks = [snapshot_from_row(row, target) for row in latest.to_dict("records")]
    breadth = compute_breadth(stocks, settings, total=len(symbols))
    policy = freshness_policy(settings)
    eligible = [s for s in stocks if classify_eligibility(s, policy).participates_in_current]
    count = breadth["valid_stocks"]
    sufficient = count >= min(2, len(symbols)) and count > 0
    breadth.update(
        eligible_count=count, eligible_stocks=count,
        no_data_stocks=breadth["no_data_stocks"] + len(symbols) - len(stocks),
        total_constituents=len(symbols), sufficient=sufficient,
        status="PASS" if sufficient else "INSUFFICIENT DATA",
        constituents=tuple(sorted(s.symbol for s in eligible)),
        observation_id=tuple(sorted((s.symbol, s.provider_timestamp) for s in eligible)),
    )
    if not sufficient:
        # Coverage remains explicit; unsupported scalar signals are never zero.
        for key in ("up_percent", "down_percent", "flat_percent", "strong_up_percent",
                    "strong_down_percent", "average_return", "median_return",
                    "average_change_from_open", "median_change_from_open"):
            breadth[key] = np.nan
        breadth["valid_stocks"] = 0
        breadth["missing_stocks"] = len(symbols)
    breadth.update(avg_return=breadth["average_return"],
                   valid_count=count, up_count=breadth["up_stocks"],
                   down_count=breadth["down_stocks"])
    return breadth


def build_theme_history(quotes: pd.DataFrame, symbols, asof, settings: dict):
    """Fixed five-minute market grid, plus exact current/5m/15m.

    Grid targets are wall-clock five-minute boundaries in market time, never
    fetch times. Exact offset targets use the same as-of selection rule.
    Empty rows are retained so missing current data cannot become older data.
    """
    symbols = list(dict.fromkeys(symbols))
    prepared = prepare_quotes(quotes, symbols)
    if asof is None:
        empty = observation_at(prepared, symbols, pd.Timestamp(0, tz="UTC"), settings)
        return pd.DataFrame(), empty
    current = pd.Timestamp(asof)
    prepared = prepared[prepared["provider_timestamp"] <= current.timestamp()]
    targets = {current}
    if not prepared.empty:
        times = pd.to_datetime(prepared["provider_timestamp"], unit="s", utc=True)
        start = times.min()
        targets.update(pd.date_range(start.ceil("5min"), current.floor("5min").tz_convert("UTC"),
                                     freq="5min"))
        for minutes in (5, 15):
            offset = current - pd.Timedelta(minutes=minutes)
            if offset >= start:
                targets.add(offset)
    index = pd.to_datetime(sorted(targets), utc=True).tz_convert("America/New_York")
    history = pd.DataFrame([observation_at(prepared, symbols, t, settings)
                            for t in index], index=index)
    return history, history.iloc[-1].to_dict()
