"""NYSE market-hours helpers (spec section 21).

Uses ``pandas_market_calendars`` for holiday / early-close awareness, with a
simple Mon–Fri fallback if the calendar lookup fails. All datetimes are
America/New_York (ET).
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd
import pandas_market_calendars as mcal

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")

_DEFAULT_OPEN = time(9, 30)
_DEFAULT_CLOSE = time(16, 0)
_PREMARKET_OPEN = time(4, 0)

_calendar = None


def _calendar():
    global _calendar
    if _calendar is None:
        try:
            _calendar = mcal.get_calendar("XNYS")
        except Exception:  # pragma: no cover - calendar failure is rare
            _calendar = False
    return _calendar


def now_et() -> datetime:
    return datetime.now(ET)


def is_session_day(day: date) -> bool:
    """True if the NYSE has a regular session on ``day``."""
    cal = _calendar()
    if cal:
        try:
            days = cal.valid_days(day - timedelta(days=1), day + timedelta(days=1))
            return any(ts.astimezone(UTC).date() == day for ts in days)
        except Exception:
            pass
    return day.weekday() < 5  # fallback: Mon–Fri


def session_open_close(day: date) -> tuple[time, time]:
    """Regular-session open/close times for ``day`` (handles early closes)."""
    cal = _calendar()
    if cal:
        try:
            ts = pd.Timestamp(day, tz=ET)
            return cal.open_time_on(ts), cal.close_time_on(ts)
        except Exception:
            pass
    return _DEFAULT_OPEN, _DEFAULT_CLOSE


def latest_session_day(on_or_before: date) -> Optional[date]:
    d = on_or_before
    for _ in range(20):
        if is_session_day(d):
            return d
        d -= timedelta(days=1)
    return None


def _at(day: date, t: time) -> datetime:
    return datetime(day.year, day.month, day.day, t.hour, t.minute, t.second, tzinfo=ET)


def market_status(now: Optional[datetime] = None) -> dict:
    """Describe the market state as of ``now`` (default: current ET time).

    Returns a dict with:
      status            'OPEN' | 'PREMARKET' | 'CLOSED' | 'WEEKEND' | 'HOLIDAY'
      session_day       date of the session being displayed
      session_open      datetime (ET) of the regular open
      session_close     datetime (ET) of the regular close
      minutes_since_open float | None
      early_close       bool (13:30 sessions etc.)
      note              human-readable explanation
    """
    if now is None:
        now = now_et()
    now = now.astimezone(ET) if now.tzinfo else now.replace(tzinfo=ET)
    day = now.date()

    if not is_session_day(day):
        last = latest_session_day(day)
        o, c = session_open_close(last) if last else (_DEFAULT_OPEN, _DEFAULT_CLOSE)
        status = "WEEKEND" if day.weekday() >= 5 else "HOLIDAY"
        return {
            "status": status,
            "session_day": last,
            "session_open": _at(last, o) if last else None,
            "session_close": _at(last, c) if last else None,
            "minutes_since_open": None,
            "early_close": c < _DEFAULT_CLOSE,
            "note": "Market closed — showing last session" if last else "Market closed — no session data",
        }

    o, c = session_open_close(day)
    open_dt = _at(day, o)
    close_dt = _at(day, c)

    if now < open_dt:
        status, note = "PREMARKET", f"Pre-market — regular session opens {o.strftime('%H:%M')} ET"
        minutes = None
    elif now <= close_dt:
        status, note = "OPEN", "Regular session in progress"
        minutes = (now - open_dt).total_seconds() / 60.0
    else:
        status, note = "CLOSED", "Market closed for the day — showing today's session"
        minutes = (close_dt - open_dt).total_seconds() / 60.0

    return {
        "status": status,
        "session_day": day,
        "session_open": open_dt,
        "session_close": close_dt,
        "minutes_since_open": minutes,
        "early_close": c < _DEFAULT_CLOSE,
        "note": note,
    }


def premarket_window(now: Optional[datetime] = None) -> bool:
    """True if ``now`` falls in the pre-market hours (04:00–09:30 ET) of a session day."""
    if now is None:
        now = now_et()
    now = now.astimezone(ET) if now.tzinfo else now.replace(tzinfo=ET)
    if not is_session_day(now.date()):
        return False
    o, _ = session_open_close(now.date())
    return _PREMARKET_OPEN <= now.time() < o
