"""yfinance-based market data provider (spec sections 7, 33).

IMPORTANT: yfinance free data is DELAYED (roughly 15 minutes) and is NOT
tick-by-tick real-time data. It is adequate for a 1m/5m scanner, and the UI
always shows the data timestamp. A real-time provider can be added later by
subclassing ``MarketDataProvider`` — nothing else needs to change.

Batching + rate-limit protection (spec section 33):
  * one batched ``yf.download`` call per dataset (intraday + daily) instead of
    one request per stock,
  * retries with linear backoff,
  * no progress threads, modest timeout.
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd
import yfinance as yf

from data.provider_base import MarketDataProvider
from utils.logging import get_logger
from utils.market_hours import ET

logger = get_logger(__name__)

_INTRADAY_FIELDS = ["Open", "High", "Low", "Close", "Volume"]


class YFinanceProvider(MarketDataProvider):
    name = "yfinance"
    realtime = False

    def __init__(self, retry_count: int = 3, retry_backoff_seconds: float = 2.0, timeout: int = 30):
        self.retry_count = max(1, int(retry_count))
        self.retry_backoff_seconds = float(retry_backoff_seconds)
        self.timeout = int(timeout)

    # ------------------------------------------------------------------ core
    def _download(self, symbols: List[str], **kwargs) -> pd.DataFrame:
        """``yf.download`` with retry + backoff. Empty frame on total failure."""
        last_err = "empty response"
        for attempt in range(1, self.retry_count + 1):
            try:
                df = yf.download(list(symbols), progress=False, auto_adjust=False,
                                 threads=False, timeout=self.timeout, **kwargs)
                if df is not None and not df.empty:
                    return df
                last_err = "empty response"
            except Exception as exc:  # noqa: BLE001 — any provider error: log & retry
                last_err = f"{type(exc).__name__}: {exc}"
            if attempt < self.retry_count:
                wait = self.retry_backoff_seconds * attempt
                logger.warning("yf.download attempt %d/%d failed (%s); retrying in %.1fs",
                               attempt, self.retry_count, last_err, wait)
                time.sleep(wait)
        logger.error("yf.download failed after %d attempts: %s", self.retry_count, last_err)
        return pd.DataFrame()

    @staticmethod
    def _split_by_symbol(df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
        """Split a yfinance (field, ticker) download into per-symbol frames.

        Each frame: lowercase columns open/high/low/close/volume; index
        tz-converted to America/New_York; rows with NaN close dropped.
        """
        out: Dict[str, pd.DataFrame] = {}
        if df is None or df.empty:
            return out
        if not isinstance(df.columns, pd.MultiIndex):
            # Should not happen (we always pass a list), but stay defensive.
            return out
        tickers = pd.unique(df.columns.get_level_values(1))
        for t in tickers:
            sym = str(t)
            sub = df.xs(sym, axis=1, level=1)
            keep = [c for c in _INTRADAY_FIELDS if c in sub.columns]
            sub = sub[keep]
            sub.columns = [c.lower() for c in keep]
            sub = sub.dropna(subset=["close"])
            if not sub.empty:
                idx = sub.index
                if isinstance(idx, pd.DatetimeIndex) and idx.tz is not None:
                    # Intraday bars come tz-aware (UTC) -> ET. Daily bars come
                    # tz-naive session dates and must stay as-is.
                    sub.index = idx.tz_convert(ET)
            out[sym] = sub
        return out

    # ------------------------------------------------------------- interface
    def get_intraday_prices(self, symbols: List[str], interval: str,
                            start: Optional[datetime] = None,
                            end: Optional[datetime] = None) -> Dict[str, pd.DataFrame]:
        """Batched intraday OHLCV for all symbols (regular session only)."""
        if start is not None and end is not None:
            df = self._download(symbols, start=start, end=end,
                                interval=interval, prepost=False)
        else:
            df = self._download(symbols, period="1d", interval=interval, prepost=False)
        return self._split_by_symbol(df)

    def get_daily_reference_prices(self, symbols: List[str]) -> Dict[str, pd.DataFrame]:
        """Batched recent daily bars (previous close + today's official open)."""
        df = self._download(symbols, period="15d", interval="1d")
        out = self._split_by_symbol(df)
        for sym, frame in out.items():
            if frame.empty:
                continue
            idx = frame.index
            if isinstance(idx, pd.DatetimeIndex) and idx.tz is None:
                # yfinance daily index is already naive session dates (ET).
                frame.index = pd.to_datetime(idx)
            else:
                # Defensive: tz-aware index -> convert to naive ET dates.
                frame.index = pd.to_datetime(idx, utc=True).tz_convert(ET).tz_localize(None)
            out[sym] = frame.sort_index()
        return out
