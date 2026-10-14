"""Abstract market-data provider (spec sections 7, 33).

The rest of the application only talks to this interface, so a real-time
provider (Polygon, Alpaca, Finnhub, Twelve Data, ...) can be added later
without touching the engines or UI.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd


@dataclass
class MarketData:
    """One batched download of everything the app needs.

    bars      : {symbol: DataFrame[open, high, low, close, volume]}
                intraday bars, regular session only, tz-aware ET index.
    daily     : {symbol: DataFrame[open, high, low, close, volume]}
                recent daily bars, tz-naive ET session dates.
    failed    : {symbol: reason} — symbols with no usable data.
    asof      : most recent bar timestamp (ET), or None when no bars exist
                (e.g. pre-market). This is the timestamp the UI MUST show.
    """
    source: str
    interval: str
    fetched_at: datetime                  # wall-clock time the download finished (UTC)
    asof: Optional[datetime]
    bars: Dict[str, pd.DataFrame] = field(default_factory=dict)
    daily: Dict[str, pd.DataFrame] = field(default_factory=dict)
    failed: Dict[str, str] = field(default_factory=dict)
    # Persisted per-row provider timestamps and validity for canonical baskets.
    # None denotes legacy OHLCV input; an empty frame means no quote data.
    quote_snapshots: Optional[pd.DataFrame] = field(default=None, repr=False)

    @property
    def ok(self) -> int:
        return len(self.bars) - len([k for k, v in self.failed.items() if v])


class MarketDataProvider(ABC):
    """Interface every data provider must implement (spec section 7)."""

    name: str = "base"
    realtime: bool = False   # free data is delayed; only set True for real feeds

    @abstractmethod
    def get_intraday_prices(self, symbols: List[str], interval: str,
                            start: Optional[datetime] = None,
                            end: Optional[datetime] = None) -> Dict[str, pd.DataFrame]:
        """Return {symbol: intraday OHLCV frame} (tz-aware index, regular session)."""

    @abstractmethod
    def get_daily_reference_prices(self, symbols: List[str]) -> Dict[str, pd.DataFrame]:
        """Return {symbol: recent daily OHLCV frame} (tz-naive ET session dates)."""

    # ------------------------------------------------------------------ helper
    def fetch_session(self, symbols: List[str], interval: str,
                      start: Optional[datetime] = None,
                      end: Optional[datetime] = None,
                      expect_intraday: bool = True) -> MarketData:
        """Fetch intraday + daily data in one go and detect failed symbols.

        ``expect_intraday=False`` suppresses the "no intraday bars" failure
        flag (used pre-market, where intraday data legitimately does not exist).
        """
        from datetime import timezone
        from utils.logging import get_logger

        logger = get_logger(__name__)
        bars = self.get_intraday_prices(list(symbols), interval, start=start, end=end)
        daily = self.get_daily_reference_prices(list(symbols))

        failed: Dict[str, str] = {}
        for sym in symbols:
            b, d = bars.get(sym), daily.get(sym)
            has_bars = b is not None and not b.empty
            has_daily = d is not None and not d.empty and d["close"].notna().any()
            if has_bars and has_daily:
                continue
            if not has_bars and not has_daily:
                failed[sym] = "no data returned by provider"
            elif not has_bars:
                if expect_intraday:
                    failed[sym] = "no intraday bars (halted?)"
            else:
                failed[sym] = "no daily reference (IPO?)"

        asof: Optional[datetime] = None
        for frame in bars.values():
            if frame is not None and not frame.empty:
                t = frame.index.max()
                asof = t if asof is None else max(asof, t)

        if failed:
            logger.info("%s: %d/%d symbols unavailable: %s",
                        self.name, len(failed), len(symbols), ", ".join(sorted(failed)))
        return MarketData(
            source=self.name,
            interval=interval,
            fetched_at=datetime.now(timezone.utc),
            asof=asof,
            bars=bars,
            daily=daily,
            failed=failed,
        )
