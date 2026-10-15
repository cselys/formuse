"""
yfinance data loader and validator for stock_scanner.
Handles downloading adjusted historical daily data, validation, cleaning, and weekly resampling.
Also supports cache-aware incremental downloads via the historical_cache module.
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
import numpy as np
import pandas as pd

logger = logging.getLogger("stock_scanner.data")

try:
    import yfinance as yf
except ImportError:
    yf = None

from stock_scanner.src.data.historical_cache import (
    CacheMetadata,
    load_cached_data,
    persist_cache,
    update_symbol_cache,
)


class DataValidationError(Exception):
    """Raised when downloaded data fails quality checks."""
    pass


class YFinanceLoader:
    """Robust downloader and validator for historical stock data using yfinance."""

    def __init__(self, history_years: int = 3, retries: int = 3, delay: float = 1.5):
        self.history_years = history_years
        self.retries = retries
        self.delay = delay

    def download_ticker(self, symbol: str, start_date: Optional[str] = None, end_date: Optional[str] = None, min_bars: int = 30) -> pd.DataFrame:
        """
        Download daily adjusted historical data for a single symbol using yfinance.
        auto_adjust=True is used.
        """
        if yf is None:
            raise ImportError("yfinance is not installed. Please install requirements.")

        if not end_date:
            end_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        if not start_date:
            start_dt = datetime.now() - timedelta(days=365 * self.history_years)
            start_date = start_dt.strftime("%Y-%m-%d")

        symbol = symbol.strip().upper()
        df = pd.DataFrame()

        for attempt in range(1, self.retries + 1):
            try:
                logger.debug(f"Downloading {symbol} (attempt {attempt}/{self.retries}) from {start_date} to {end_date}")
                ticker_obj = yf.Ticker(symbol)
                df = ticker_obj.history(start=start_date, end=end_date, auto_adjust=True, actions=False)

                if df is not None and not df.empty:
                    break
            except Exception as e:
                logger.warning(f"Error downloading {symbol} on attempt {attempt}: {e}")
                if attempt < self.retries:
                    time.sleep(self.delay * attempt)

        if df is None or df.empty:
            raise DataValidationError(f"Empty or failed download for symbol: {symbol}")

        df = self._clean_and_validate_dataframe(df, symbol, min_bars=min_bars)
        return df

    def download_ticker_cached(
        self,
        symbol: str,
        fetch_recent_days: int = 5,
    ) -> Tuple[Optional[pd.DataFrame], CacheMetadata]:
        """
        Download recent data for a symbol using cache-aware incremental logic.

        Uses the persistent historical cache to avoid downloading the full dataset
        on every run. Only fetches a small recent window from yfinance.

        Returns (new_data_df, updated_metadata).
        new_data_df may be None if no new data was fetched or on failure.
        """
        symbol_upper = symbol.strip().upper()
        metadata = CacheMetadata.load(symbol_upper)

        # Use the cache module's update logic
        success, updated_meta = update_symbol_cache(
            symbol_upper,
            fetch_recent_days=fetch_recent_days,
        )

        # If the cache was updated (either with new data or preserved existing),
        # load the current cached data and return it
        if success:
            cached = load_cached_data(symbol_upper)
            # Also update the loader's metadata reference
            metadata = updated_meta
            return cached, metadata
        else:
            # Failure - return existing cache if any, with failed metadata
            cached = load_cached_data(symbol_upper)
            return cached, metadata

    def download_universe(self, symbols: List[str]) -> Dict[str, pd.DataFrame]:
        """
        Download data for a list of symbols. One bad ticker will not terminate the entire scan.
        Returns a dictionary of symbol -> cleaned DataFrame.
        """
        results = {}
        for symbol in symbols:
            symbol_upper = symbol.strip().upper()
            if symbol_upper in results:
                continue
            try:
                df = self.download_ticker(symbol_upper)
                results[symbol_upper] = df
                logger.info(f"Successfully downloaded and validated {symbol_upper} ({len(df)} daily bars)")
            except Exception as e:
                logger.error(f"Failed to download/validate symbol {symbol_upper}: {e}")
        return results

    def _clean_and_validate_dataframe(self, df: pd.DataFrame, symbol: str, min_bars: int = 30) -> pd.DataFrame:
        """
        Clean and validate raw yfinance DataFrame.
        Handles MultiIndex columns, timezone differences, missing values, duplicates, and OHLC consistency.
        """
        if df.empty:
            raise DataValidationError(f"DataFrame for {symbol} is empty.")

        # Handle MultiIndex columns if returned by yfinance
        if isinstance(df.columns, pd.MultiIndex):
            # Flatten or extract the price level
            df.columns = [col[0] if isinstance(col, tuple) else col for col in df.columns]

        # Standardize column names
        col_map = {}
        for col in df.columns:
            col_lower = str(col).lower()
            if 'open' in col_lower:
                col_map[col] = 'Open'
            elif 'high' in col_lower:
                col_map[col] = 'High'
            elif 'low' in col_lower:
                col_map[col] = 'Low'
            elif 'close' in col_lower:
                col_map[col] = 'Close'
            elif 'volume' in col_lower:
                col_map[col] = 'Volume'

        df = df.rename(columns=col_map)

        required_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
        missing_cols = [c for c in required_cols if c not in df.columns]
        if missing_cols:
            raise DataValidationError(f"Symbol {symbol} missing required columns: {missing_cols}")

        df = df[required_cols].copy()

        # Handle index: ensure datetime, remove timezone, sort chronologically, drop duplicate dates
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)

        if df.index.tz is not None:
            df.index = df.index.tz_convert(None)

        df = df[~df.index.duplicated(keep='last')]
        df = df.sort_index()

        # Drop rows with NaN in OHLC
        df = df.dropna(subset=['Open', 'High', 'Low', 'Close'])

        # Replace negative or zero volume with NaN/0, non-negative volume check
        df['Volume'] = df['Volume'].fillna(0)
        df.loc[df['Volume'] < 0, 'Volume'] = 0

        if len(df) < min_bars:
            raise DataValidationError(f"Insufficient historical bars for {symbol}: {len(df)} bars (minimum {min_bars} required).")

        # OHLC consistency check
        invalid_mask = (df['High'] < df['Low']) | (df['High'] < df['Open']) | (df['High'] < df['Close']) | \
                       (df['Low'] > df['Open']) | (df['Low'] > df['Close'])
        if invalid_mask.sum() > 0:
            logger.warning(f"Symbol {symbol} has {invalid_mask.sum()} bars with OHLC inconsistency. Cleaning...")
            # Fix minor inconsistencies or drop
            df = df[~invalid_mask]

        if len(df) < min_bars:
            raise DataValidationError(f"Insufficient valid bars after cleaning for {symbol}: {len(df)}")

        return df

    def resample_to_weekly(self, df_daily: pd.DataFrame, as_of_date: Optional[str] = None, drop_partial: bool = False, calendar_aware: bool = False) -> pd.DataFrame:
        """
        Resample Daily adjusted OHLCV into Weekly OHLCV.
        Week ends on Friday (W-FRI).
        If drop_partial is True or as_of_date is provided, ensures any incomplete current week
        whose Friday target has not been fully reached or exceeds as_of_date is dropped,
        returning strictly completed weekly candles (`weekly_completed`), avoiding lookahead bias.
        """
        if calendar_aware:
            from stock_scanner.src.data.market_calendar import completed_weekly
            return completed_weekly(df_daily, as_of_date)
        if df_daily.empty:
            return pd.DataFrame()

        if as_of_date:
            as_dt = pd.to_datetime(as_of_date)
            df_daily = df_daily[df_daily.index <= as_dt]

        resampled = df_daily.resample('W-FRI').agg({
            'Open': 'first',
            'High': 'max',
            'Low': 'min',
            'Close': 'last',
            'Volume': 'sum'
        })

        resampled = resampled.dropna(subset=['Open', 'High', 'Low', 'Close'])
        resampled = resampled[resampled['Volume'] >= 0]

        if drop_partial and not df_daily.empty:
            # If the last bar in df_daily is not Friday, the latest resampled W-FRI bar
            # might be a partial week unless the last daily bar is a Friday and equals or exceeds the week end.
            last_daily_date = df_daily.index[-1]
            # Find the W-FRI bin for the last daily bar
            # In pandas, resample('W-FRI') assigns week ending on Friday.
            # If last_daily_date is e.g. Wednesday, the W-FRI bin is that Friday. But the week is partial.
            # We drop the last resampled bar if last_daily_date.weekday() < 4 (Monday=0 to Thursday=3)
            # or if last_daily_date is strictly before the Friday of that week.
            if len(resampled) > 0:
                last_week_end = resampled.index[-1]
                # If last daily date is before that week's Friday, it's a partial week
                if last_daily_date < last_week_end and last_daily_date.weekday() < 4:
                    resampled = resampled.iloc[:-1]

        return resampled
