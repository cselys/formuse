"""Load one immutable session read into current stocks and market history."""
from __future__ import annotations

import math
from zoneinfo import ZoneInfo

import pandas as pd

from data.provider_base import MarketData
from engine.price_engine import _pct
from models.schemas import StockSnapshot


def snapshot_from_row(row, target=None) -> StockSnapshot:
    """Use each observation's own references; age is relative to market target."""
    def value(key):
        v = row.get(key)
        return None if v is None or pd.isna(v) else v

    provider = value("provider_timestamp")
    age = value("data_age_seconds")
    if target is not None:
        age = target.timestamp() - provider if provider is not None else None
    price, previous = value("price"), value("previous_close")
    change = _pct(price, previous)
    return StockSnapshot(
        symbol=row["symbol"], timestamp=str(value("fetched_at") or ""),
        previous_close=previous, today_open=value("today_open"),
        current_price=price, intraday_high=value("intraday_high"),
        intraday_low=value("intraday_low"), change_vs_previous_close=change,
        change_vs_open=_pct(price, value("today_open")),
        distance_from_intraday_high=_pct(price, value("intraday_high")),
        distance_from_intraday_low=_pct(price, value("intraday_low")),
        volume=int(value("volume") or 0),
        is_valid=bool(value("is_valid")) and change is not None,
        issue=value("issue") or "", provider_timestamp=provider,
        fetched_at=value("fetched_at"), data_age_seconds=age,
        direction="UP" if change is not None and change > .10 else (
            "DOWN" if change is not None and change < -.10 else "FLAT"),
    )


def load_snapshot_market_data(store, session_date, render_time):
    """No network. Both outputs derive from exactly the same SQL statement."""
    quotes = store.session_quote_snapshots(session_date)
    bars, stocks = {}, {}
    provider_times = pd.to_numeric(quotes["provider_timestamp"], errors="coerce")
    finite = provider_times[provider_times.map(lambda x: pd.notna(x) and math.isfinite(x) and x > 0)]
    asof = (pd.to_datetime(finite.max(), unit="s", utc=True).tz_convert(
        ZoneInfo("America/New_York")) if len(finite) else None)
    for symbol, group in quotes.groupby("symbol", sort=False):
        group = group.sort_values("fetched_at", kind="stable")
        stocks[symbol] = snapshot_from_row(group.iloc[-1], asof)
        frame = group.rename(columns={"today_open": "open", "intraday_high": "high",
                                      "intraday_low": "low", "price": "close"}).copy()
        frame.index = pd.to_datetime(frame["provider_timestamp"], unit="s", utc=True,
                                     errors="coerce")
        bars[symbol] = frame[frame.index.notna()].sort_index()
    return MarketData(source="finnhub_snapshot", interval="5m", fetched_at=render_time,
                      asof=asof, bars=bars, quote_snapshots=quotes), stocks
