"""Completed US equity sessions and weeks; date-only cutoffs mean end of day."""
from functools import lru_cache

import numpy as np
import pandas as pd
import pandas_market_calendars as mcal

TZ = 'America/New_York'
OHLCV = ['Open', 'High', 'Low', 'Close', 'Volume']


def cutoff_timestamp(value=None):
    if value is None:
        return pd.Timestamp.now(tz=TZ)
    stamp = pd.Timestamp(value)
    if isinstance(value, str) and len(value) == 10:
        stamp += pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
    return stamp.tz_localize(TZ) if stamp.tzinfo is None else stamp.tz_convert(TZ)


@lru_cache(maxsize=128)
def schedule(start, end):
    return mcal.get_calendar('NYSE').schedule(start_date=start, end_date=end)


def session_dates(df):
    """Daily indexes are session labels, not instants to shift into another day."""
    dates = pd.DatetimeIndex(df.index)
    return dates.tz_localize(None).normalize() if dates.tz is not None else dates.normalize()


def completed_daily(df, as_of=None):
    if df is None or df.empty:
        return pd.DataFrame(columns=OHLCV, index=pd.DatetimeIndex([]))
    cutoff = cutoff_timestamp(as_of)
    data = df.copy()
    data.index = session_dates(data)
    data = data[~data.index.duplicated(keep='last')].sort_index()
    if data.index[0] > cutoff.tz_localize(None).normalize():
        return data.iloc[:0]
    cal = schedule(str(data.index[0].date()), str(cutoff.date()))
    sessions = cal.index[cal.market_close <= cutoff]
    return data.loc[data.index.isin(sessions)]


def week_context(as_of=None):
    cutoff = cutoff_timestamp(as_of)
    today = cutoff.tz_localize(None).normalize()
    monday = today - pd.Timedelta(days=today.weekday())
    cal = schedule(str((monday - pd.Timedelta(days=21)).date()),
                   str((monday + pd.Timedelta(days=4)).date()))
    weeks = cal.groupby(cal.index.to_period('W-FRI')).tail(1)
    finished = weeks[weeks.market_close <= cutoff]
    last = finished.index[-1]
    period = last.to_period('W-FRI')
    previous = finished.index[-2]
    completed = cal[cal.market_close <= cutoff]
    return {
        'as_of': cutoff.isoformat(),
        'week_end': str(period.end_time.date()),
        'week_start': str((period.end_time.normalize() - pd.Timedelta(days=4)).date()),
        'last_session': str(last.date()),
        'previous_session': str(previous.date()),
        'latest_session': str(completed.index[-1].date()),
        'auto_weekly': last >= monday,
        'calendar': 'NYSE',
    }


def completed_weekly(df, as_of=None):
    """Only aggregate elapsed weeks containing every expected valid session.

    Missing bars never become an apparently complete OHLCV candle. Friday
    labels are retained even when the final trading session was Thursday.
    """
    cutoff = cutoff_timestamp(as_of)
    daily = completed_daily(df, cutoff)
    if daily.empty:
        return daily
    start = daily.index[0].to_period('W-FRI').start_time
    end = cutoff.tz_localize(None).to_period('W-FRI').end_time
    cal = schedule(str(start.date()), str(end.date()))
    rows, labels = [], []
    for period, sessions in cal.groupby(cal.index.to_period('W-FRI')):
        if sessions.market_close.iloc[-1] > cutoff:
            continue
        bars = daily.reindex(sessions.index)[OHLCV]
        if not np.isfinite(bars.to_numpy(dtype=float)).all():
            continue
        if (bars[['Open', 'High', 'Low', 'Close']] <= 0).any().any() or (bars.Volume < 0).any():
            continue
        rows.append([bars.Open.iloc[0], bars.High.max(), bars.Low.min(),
                     bars.Close.iloc[-1], bars.Volume.sum()])
        labels.append(period.end_time.normalize())
    return pd.DataFrame(rows, index=pd.DatetimeIndex(labels), columns=OHLCV)


def uses_completed_weeks(config):
    return str(config.get('scanner_version', '1.2')) not in ('1.1', '1.2')
