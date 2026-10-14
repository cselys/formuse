"""Stock-level metric calculations (spec section 8).

Definitions (verbatim from the spec):

    change_vs_previous_close = (current_price - previous_close) / previous_close * 100
    change_vs_open           = (current_price - today_open)     / today_open     * 100
    distance_from_intraday_high = (current_price - intraday_high) / intraday_high * 100
    distance_from_intraday_low  = (current_price - intraday_low)  / intraday_low  * 100

All functions are pure: they take bars + references and return metrics.
Missing/halted/IPO/stale data must never crash a calculation (spec 23).
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

from data.provider_base import MarketData
from models.schemas import DOWN, FLAT, StockSnapshot, UP
from utils.config import get_setting
from utils.logging import get_logger

logger = get_logger(__name__)

_EMPTY_BARS = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])


def _pct(new: Optional[float], old: Optional[float]) -> Optional[float]:
    """Percentage change ``new`` vs ``old``; None when undefined."""
    try:
        if new is None or old is None:
            return None
        new, old = float(new), float(old)
        if not (np.isfinite(new) and np.isfinite(old)) or old == 0:
            return None
        return (new - old) / old * 100.0
    except (TypeError, ValueError):
        return None


def clean_bars(bars: Optional[pd.DataFrame]) -> pd.DataFrame:
    """Normalize intraday bars: dedupe timestamps (keep last), sort, drop NaN closes."""
    if bars is None or bars.empty:
        return _EMPTY_BARS.copy()
    b = bars.copy()
    b = b[~b.index.duplicated(keep="last")]
    b = b.sort_index()
    b = b.dropna(subset=["close"])
    return b


def daily_reference(daily: Optional[pd.DataFrame], session_date) -> Tuple[Optional[float], Optional[float]]:
    """``(previous_close, today_open)`` from recent daily bars.

    previous_close : close of the most recent daily bar STRICTLY before the
                     session date (handles weekends/holidays correctly).
    today_open     : official regular-session open from the session-date daily
                     bar (spec 22). None when not available yet (pre-market).
    """
    if daily is None or daily.empty or "close" not in daily:
        return None, None
    d = daily.sort_index()
    sd = pd.Timestamp(session_date)
    # Session dates are ET calendar dates — normalize both sides to tz-naive.
    if d.index.tz is not None:
        d = d.copy()
        d.index = d.index.tz_localize(None)
    if sd.tzinfo is not None:
        sd = sd.tz_localize(None)
    prev = d[d.index < sd]
    prev_close: Optional[float] = None
    if len(prev) > 0:
        v = prev["close"].iloc[-1]
        prev_close = float(v) if pd.notna(v) else None
    today_open: Optional[float] = None
    if sd in d.index:
        v = d.loc[sd, "open"]
        today_open = float(v) if pd.notna(v) else None
    return prev_close, today_open


def build_stock_metrics(symbol: str,
                        bars: Optional[pd.DataFrame],
                        previous_close: Optional[float],
                        today_open: Optional[float],
                        *,
                        asof: Optional[datetime],
                        now_ts: Optional[datetime],
                        flat_threshold: float = 0.10,
                        stale_warn_minutes: float = 20.0,
                        market_is_open: bool = False) -> StockSnapshot:
    """Compute one stock's metrics from intraday bars + daily reference."""
    ts_iso = asof.isoformat() if asof is not None else (
        now_ts.isoformat() if now_ts is not None else "")
    base = dict(
        symbol=symbol, timestamp=ts_iso,
        previous_close=(float(previous_close)
                        if previous_close is not None and np.isfinite(previous_close) else None),
        today_open=(float(today_open) if today_open is not None and np.isfinite(today_open) else None),
        current_price=None, intraday_high=None, intraday_low=None,
        change_vs_previous_close=None, change_vs_open=None,
        distance_from_intraday_high=None, distance_from_intraday_low=None,
        volume=0, is_valid=False, issue="", direction=FLAT,
    )

    b = clean_bars(bars)
    if b.empty:
        base["issue"] = "no intraday data"
        return StockSnapshot(**base)
    if base["previous_close"] is None:
        base["issue"] = "no valid previous close (IPO?)"
        return StockSnapshot(**base)

    close = float(b["close"].iloc[-1])
    high = float(b["high"].max()) if "high" in b and b["high"].notna().any() else close
    low = float(b["low"].min()) if "low" in b and b["low"].notna().any() else close
    volume = int(b["volume"].fillna(0).sum()) if "volume" in b else 0

    issue = ""
    if base["today_open"] is None:
        issue = "no official open yet"
    if market_is_open and asof is not None and now_ts is not None:
        age_min = (now_ts - asof).total_seconds() / 60.0
        if age_min > stale_warn_minutes:
            issue = f"{issue} + stale quote" if issue else "stale quote"

    m_change = _pct(close, base["previous_close"])
    o_change = _pct(close, base["today_open"])
    direction = UP if (m_change or 0.0) > flat_threshold else \
                DOWN if (m_change or 0.0) < -flat_threshold else FLAT

    return StockSnapshot(
        symbol=symbol, timestamp=ts_iso,
        previous_close=base["previous_close"], today_open=base["today_open"],
        current_price=close, intraday_high=high, intraday_low=low,
        change_vs_previous_close=m_change, change_vs_open=o_change,
        distance_from_intraday_high=_pct(close, high),
        distance_from_intraday_low=_pct(close, low),
        volume=volume, is_valid=True, issue=issue, direction=direction,
    )


def build_all_stock_metrics(md: MarketData, settings: dict,
                            now_ts: datetime,
                            market_is_open: bool = False) -> Dict[str, StockSnapshot]:
    """Build per-stock metrics for every symbol in a MarketData bundle."""
    flat = get_setting(settings, "classification.flat_threshold", 0.10)
    stale_min = get_setting(settings, "data.stale_warn_minutes", 20.0)
    asof = md.asof if md.asof is not None else now_ts
    session_date = asof.date()

    out: Dict[str, StockSnapshot] = {}
    for sym, bars in md.bars.items():
        daily = md.daily.get(sym)
        prev_close, today_open = daily_reference(daily, session_date)
        out[sym] = build_stock_metrics(
            sym, bars, prev_close, today_open,
            asof=asof, now_ts=now_ts,
            flat_threshold=flat, stale_warn_minutes=stale_min,
            market_is_open=market_is_open,
        )

    # Symbols the provider returned no bars for at all (delisted / halted / typo).
    for sym, reason in md.failed.items():
        if sym in out:
            snap = out[sym]
            if snap.is_valid:
                snap.issue = f"{snap.issue} + {reason}" if snap.issue else reason
            continue
        out[sym] = StockSnapshot(
            symbol=sym,
            timestamp=asof.isoformat() if asof is not None else "",
            previous_close=None, today_open=None, current_price=None,
            intraday_high=None, intraday_low=None,
            change_vs_previous_close=None, change_vs_open=None,
            distance_from_intraday_high=None, distance_from_intraday_low=None,
            volume=0, is_valid=False, issue=reason, direction=FLAT,
        )
    return out
