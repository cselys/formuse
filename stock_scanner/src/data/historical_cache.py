"""
Persistent historical price cache with incremental daily updates.

Provides:
- Per-symbol Parquet caching of daily OHLCV data
- Metadata tracking (dates, row counts, fetch status, error messages)
- Incremental updates (only fetch new data since last cached bar)
- Restart-safe, idempotent operations
- Failure preservation (never destroys existing valid cache)
"""

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

import pandas as pd

logger = logging.getLogger("stock_scanner.data.cache")


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _cache_root() -> str:
    """Return the absolute path to the project cache directory."""
    # Resolve relative to the project root (parent of stock_scanner/)
    root = os.path.dirname(os.path.dirname(__file__))  # ..\dailyscanner
    cache_dir = os.path.join(root, "cache")
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def _metadata_path(symbol: str) -> str:
    """Path to the JSON metadata file for a given symbol."""
    return os.path.join(_cache_root(), "metadata", f"{symbol.upper()}_meta.json")


def _cache_path(symbol: str) -> str:
    """Path to the Parquet cache file for a given symbol."""
    return os.path.join(_cache_root(), f"{symbol.upper()}.parquet")


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

class CacheMetadata:
    """Metadata describing the cached history for one symbol."""

    def __init__(
        self,
        symbol: str,
        first_date: Optional[str] = None,
        last_date: Optional[str] = None,
        row_count: int = 0,
        last_successful_fetch: Optional[str] = None,
        fetch_status: str = "ok",  # ok, failed, no_new_data
        error_message: Optional[str] = None,
    ):
        self.symbol = symbol
        self.first_date = first_date
        self.last_date = last_date
        self.row_count = row_count
        self.last_successful_fetch = last_successful_fetch
        self.fetch_status = fetch_status
        self.error_message = error_message

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "first_date": self.first_date,
            "last_date": self.last_date,
            "row_count": self.row_count,
            "last_successful_fetch": self.last_successful_fetch,
            "fetch_status": self.fetch_status,
            "error_message": self.error_message,
        }

    @staticmethod
    def from_dict(d: dict) -> "CacheMetadata":
        m = CacheMetadata(
            symbol=d.get("symbol", ""),
            first_date=d.get("first_date"),
            last_date=d.get("last_date"),
            row_count=d.get("row_count", 0),
            last_successful_fetch=d.get("last_successful_fetch"),
            fetch_status=d.get("fetch_status", "ok"),
            error_message=d.get("error_message"),
        )
        return m

    def save(self) -> None:
        os.makedirs(os.path.dirname(_metadata_path(self.symbol)), exist_ok=True)
        with open(_metadata_path(self.symbol), "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    @staticmethod
    def load(symbol: str) -> "CacheMetadata":
        p = _metadata_path(symbol)
        if not os.path.exists(p):
            return CacheMetadata(symbol=symbol)
        try:
            with open(p, "r", encoding="utf-8") as f:
                return CacheMetadata.from_dict(json.load(f))
        except Exception:
            return CacheMetadata(symbol=symbol)


# ---------------------------------------------------------------------------
# Cache read / write
# ---------------------------------------------------------------------------

def load_cached_data(symbol: str) -> Optional[pd.DataFrame]:
    """
    Load cached daily OHLCV data for a symbol from Parquet.

    Returns DataFrame with DatetimeIndex and columns [Open, High, Low, Close, Volume],
    or None if no cache exists.
    """
    p = _cache_path(symbol)
    if not os.path.exists(p):
        return None
    try:
        df = pd.read_parquet(p)
        # Ensure index is DatetimeIndex
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)
        df = df.sort_index()
        try:
            logger.debug(f"Loaded {len(df)} cached bars for {symbol} from {p}")
        except Exception:
            pass
        return df
    except Exception as e:
        try:
            logger.warning(f"Failed to load cache for {symbol}: {e}")
        except Exception:
            pass
        return None


def persist_cache(symbol: str, df: pd.DataFrame, metadata: CacheMetadata) -> None:
    """
    Persist daily OHLCV data to Parquet and update metadata.

    The DataFrame must have a DatetimeIndex and columns [Open, High, Low, Close, Volume].
    """
    # Ensure proper structure
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    df = df[~df.index.duplicated(keep="last")]

    cache_dir = _cache_root()
    os.makedirs(cache_dir, exist_ok=True)
    os.makedirs(os.path.join(cache_dir, "metadata"), exist_ok=True)

    # Write parquet
    p = _cache_path(symbol)
    df.to_parquet(p, index=True)
    try:
        logger.info(f"Persisted {len(df)} bars for {symbol} to {p}")
    except Exception:
        pass

    # Update metadata
    metadata.row_count = len(df)
    if df.index.isna().sum() == 0 and len(df) > 0:
        metadata.first_date = str(df.index[0].date())
        metadata.last_date = str(df.index[-1].date())
    try:
        metadata.save()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Incremental update logic
# ---------------------------------------------------------------------------

def _find_latest_cached_trading_date(symbol: str) -> Optional[str]:
    """Return the latest cached date string (YYYY-MM-DD), or None if no cache."""
    df = load_cached_data(symbol)
    if df is None or df.empty:
        return None
    # Return the last date as a string
    return str(df.index[-1].date())


def _request_recent_window(
    symbol: str,
    start_date: str,
    end_date: str,
) -> Optional[pd.DataFrame]:
    """
    Request a recent window from yfinance.

    Returns cleaned DataFrame or None on failure.
    """
    from stock_scanner.src.data.yfinance_loader import YFinanceLoader, DataValidationError

    loader = YFinanceLoader(history_years=1)  # Only need recent data
    try:
        df = loader.download_ticker(symbol, start_date=start_date, end_date=end_date, min_bars=1)
        logger.info(f"Fetched {len(df)} recent bars for {symbol} from {start_date} to {end_date}")
        return df
    except DataValidationError as e:
        logger.warning(f"yfinance data validation error for {symbol}: {e}")
        return None
    except Exception as e:
        # Use str() safely; if logger is unavailable, fall back to print
        err_msg = str(e) if e else "unknown error"
        try:
            logger.warning(f"Failed to fetch recent data for {symbol}: {err_msg}")
        except Exception:
            pass
        return None


def _merge_and_deduplicate(
    cached_df: pd.DataFrame,
    new_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Merge cached and new data, deduplicating by date.

    For overlapping dates, keep the newest valid observation.
    Returns the merged DataFrame sorted chronologically.
    """
    if cached_df is None or cached_df.empty:
        return new_df.sort_index()
    if new_df is None or new_df.empty:
        return cached_df.sort_index()

    combined = pd.concat([cached_df, new_df])
    # Duplicate handling: keep the last occurrence (newest data wins)
    combined = combined[~combined.index.duplicated(keep="last")]
    combined = combined.sort_index()

    try:
        logger.info(
            f"Merged cache ({len(cached_df)} bars) + new ({len(new_df)} bars) -> "
            f"{len(combined)} total bars after dedup"
        )
    except Exception:
        pass
    return combined


def update_symbol_cache(
    symbol: str,
    fetch_recent_days: int = 5,
) -> Tuple[bool, CacheMetadata]:
    """
    Incrementally update the cached history for one symbol.

    Logic:
    1. Load existing cache (if any)
    2. Find latest cached trading date
    3. Request a small window of recent data from yfinance
       (from (latest_cached - fetch_recent_days) to today)
    4. Merge + deduplicate (new data keeps overlapping dates)
    5. Persist cache + metadata
    6. Return (success, metadata)

    Returns (False, metadata) if yfinance fails but existing cache is preserved.
    """
    symbol_upper = symbol.strip().upper()
    metadata = CacheMetadata.load(symbol_upper)

    # Step 1: Load existing cache
    cached_df = load_cached_data(symbol_upper)
    latest_cached = _find_latest_cached_trading_date(symbol_upper)

    # Step 2 & 3: Determine fetch window
    if latest_cached:
        # Fetch from a few days before the latest cached date to today
        # This handles missed runs, weekends, holidays, and small corrections
        latest_dt = pd.to_datetime(latest_cached)
        fetch_start = (latest_dt - timedelta(days=fetch_recent_days)).strftime("%Y-%m-%d")
        fetch_end = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

        # Avoid fetching if we already have very recent data
        if fetch_start >= latest_cached:
            logger.info(f"No new data to fetch for {symbol}: latest cached = {latest_cached}")
            return True, metadata
    else:
        # First run - no cache; need full history
        # Minimum required by scanner: 252 trading days (~1 year) for 52w high/low,
        # plus indicators needing ~30 days, but we fetch more to be safe
        fetch_start = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
        fetch_end = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        logger.info(f"First run for {symbol}: fetching full historical period {fetch_start} to {fetch_end}")

    # Step 4: Fetch from yfinance
    new_df = _request_recent_window(symbol_upper, fetch_start, fetch_end)

    # Step 5: Merge and persist
    if new_df is not None and not new_df.empty:
        merged = _merge_and_deduplicate(cached_df, new_df)
        persist_cache(symbol_upper, merged, metadata)
        # Reset error message on success
        metadata.fetch_status = "ok"
        metadata.error_message = None
        metadata.last_successful_fetch = datetime.now().strftime("%Y-%m-%d")
        metadata.save()
        return True, metadata
    else:
        # yfinance failed - preserve existing cache
        metadata.fetch_status = "failed"
        metadata.error_message = f"yfinance fetch failed for window {fetch_start} to {fetch_end}"
        # Do NOT update last_successful_fetch
        metadata.save()
        # If we have existing cache, that's still valid
        if cached_df is not None and not cached_df.empty:
            logger.info(f"Preserved existing cache for {symbol} ({len(cached_df)} bars) after fetch failure")
            return True, metadata
        # No cache and no new data - this is a real failure
        logger.error(f"Failed to fetch data for {symbol} and no existing cache present")
        return False, metadata


def refresh_symbol_cache(
    symbol: str,
    refresh_days: int = 60,
) -> Tuple[bool, CacheMetadata]:
    """
    Periodic reconciliation: refresh a window of recent history.

    Fetches the most recent `refresh_days` trading days from yfinance
    and merges them into the cache, replacing any old data within that window.

    Useful for "periodic maintenance" full rebuilds of recent history.
    """
    symbol_upper = symbol.strip().upper()
    metadata = CacheMetadata.load(symbol_upper)
    cached_df = load_cached_data(symbol_upper)

    if cached_df is None or cached_df.empty:
        # No cache - do a full download instead
        return update_symbol_cache(symbol, fetch_recent_days=refresh_days)

    # Determine window to refresh: from (latest_date - refresh_days) to today
    latest_date = pd.to_datetime(str(cached_df.index[-1].date()))
    fetch_start = (latest_date - timedelta(days=refresh_days)).strftime("%Y-%m-%d")
    fetch_end = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    new_df = _request_recent_window(symbol_upper, fetch_start, fetch_end)

    if new_df is not None and not new_df.empty:
        # For refresh, we want to replace data in the refresh window
        # Strategy: merge, then for overlapping dates, keep the new data
        merged = _merge_and_deduplicate(cached_df, new_df)
        # Optionally: trim very old data if desired, but we keep it simple
        persist_cache(symbol_upper, merged, metadata)
        metadata.fetch_status = "ok"
        metadata.error_message = None
        metadata.last_successful_fetch = datetime.now().strftime("%Y-%m-%d")
        metadata.save()
        return True, metadata
    else:
        # Failure - preserve existing cache
        metadata.fetch_status = "failed"
        metadata.error_message = f"yfinance refresh failed for window {fetch_start} to {fetch_end}"
        metadata.save()
        return False, metadata


def force_full_rebuild(symbol: str) -> Tuple[bool, CacheMetadata]:
    """
    Force a full historical rebuild for a symbol.

    Downloads the full required history and replaces the cache.
    Intended for CLI use with --rebuild-cache.
    """
    from stock_scanner.src.data.yfinance_loader import YFinanceLoader, DataValidationError

    symbol_upper = symbol.strip().upper()
    metadata = CacheMetadata.load(symbol_upper)

    loader = YFinanceLoader(history_years=3)
    try:
        df = loader.download_ticker(symbol_upper)
        persist_cache(symbol_upper, df, metadata)
        metadata.fetch_status = "ok"
        metadata.error_message = None
        metadata.last_successful_fetch = datetime.now().strftime("%Y-%m-%d")
        metadata.save()
        return True, metadata
    except Exception as e:
        metadata.fetch_status = "failed"
        metadata.error_message = str(e)
        metadata.save()
        logger.error(f"Full rebuild failed for {symbol}: {e}")
        return False, metadata


# ---------------------------------------------------------------------------
# Batch utilities
# ---------------------------------------------------------------------------

def update_universe_cache(
    symbols: list,
    fetch_recent_days: int = 5,
    parallel: bool = False,
) -> Dict[str, Tuple[bool, CacheMetadata]]:
    """
    Update cache for multiple symbols.

    Returns dict of symbol -> (success, metadata).
    """
    results = {}
    for sym in symbols:
        success, meta = update_symbol_cache(sym, fetch_recent_days=fetch_recent_days)
        results[sym] = (success, meta)
    return results