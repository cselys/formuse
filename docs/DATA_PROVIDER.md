# DATA_PROVIDER.md

## Market data provider abstraction (spec section 7)

The application talks to a `MarketDataProvider` interface — nothing else needs to change when swapping providers.

### Interface

```python
class MarketDataProvider(ABC):
    name: str = "base"
    realtime: bool = False

    @abstractmethod
    def get_intraday_prices(self, symbols: List[str], interval: str,
                            start: Optional[datetime] = None,
                            end: Optional[datetime] = None) -> Dict[str, pd.DataFrame]:
        """Return {symbol: intraday OHLCV frame} (tz-aware ET index, regular session only)."""

    @abstractmethod
    def get_daily_reference_prices(self, symbols: List[str]) -> Dict[str, pd.DataFrame]:
        """Return {symbol: recent daily OHLCV frame} (tz-naive ET session dates)."""

    # ------------------------------------------------------------------ helper
    def fetch_session(self, symbols: List[str], interval: str,
                      start: Optional[datetime] = None,
                      end: Optional[datetime] = None,
                      expect_intraday: bool = True) -> MarketData:
        """Fetch intraday + daily data in one go and detect failed symbols."""
```

### YFinanceProvider (spec section 33)

`YFinanceProvider(MarketDataProvider)` — the only currently implemented provider.

**`realtime = False`** — yfinance free data is delayed, not tick-level real-time.

#### `get_intraday_prices(symbols, interval, start, end)`

- **Batching:** One `yf.download()` call per dataset (intraday + daily), not one per stock
- **Interval:** `5m` (default) or `1m`
- **`start` / `end`**: If `None`, uses session start (session_open - 1h) and session end (now or session_close)
- **`prepost=False`**: Regular-session bars only (09:30–16:00 ET)
- **`auto_adjust=False`**: Unadjusted prices (no split/div adjustment)
- **`threads=False`**: Single process (avoids GIL contention)
- **Timeout**: 30 s default, configurable via `settings.data.timeout`
- **Retry:** `retry_count` (default 3) with linear backoff `retry_backoff_seconds * attempt` (default 2.0 * attempt)
- **Error handling:** On total failure, returns empty `DataFrame`; per-symbol failures tracked in `MarketData.failed`

#### `_split_by_symbol(df)`

- Input: yfinance `DataFrame` with `MultiIndex (field, ticker)`
- Output: `{sym: DataFrame[open, high, low, close, volume]}` with:
  - Lower-case columns
  - Index tz-converted to `America/New_York`
  - Rows with NaN `close` dropped
  - **Daily bars** keep their original tz-naive date index (ET session dates)
  - **Intraday bars** have tz-aware UTC index converted to ET

#### `get_daily_reference_prices(symbols)`

- `yf.download(symbols, period='15d', interval='1d')`
- Normalizes index to naive ET dates (session dates)
- Returns `{sym: DataFrame[open, high, low, close, volume]}` per symbol
- `prev_close` = close of the most recent daily bar **strictly before** the session date (handles weekends/holidays)
- `today_open` = open of the session-date daily bar (or `None` if not yet available = pre-market)

#### `fetch_session(symbols, interval, start, end, expect_intraday)`

- Constructs `start` = `session_open - 1h` (to catch the opening auction)
- Constructs `end` = `now` if market OPEN, else `session_close`
- Calls `get_intraday_prices()` and `get_daily_reference_prices()`
- Builds `MarketData` with `asof` = max bar timestamp (ET)
- Populates `md.failed` dict for symbols with no data
- If `expect_intraday=False` (pre-market), symbols without intraday bars are **not** flagged as failed

### Rate-limit protection (spec 33)

- One batched `yf.download()` call per dataset (intraday + daily) instead of one request per stock
- Linear backoff: `retry_backoff_seconds * attempt` (default 2.0 * attempt)
- No progress threads (`progress=False, threads=False`)
- Modest timeout (`timeout=30` default)
- All per-symbol failures are logged via `utils.logging.get_logger()`

### Data freshness & staleness

- yfinance data is delayed ~15 minutes (not tick-level real-time)
- The UI **always** shows the data timestamp (`Data as of HH:MM ET`)
- A "delayed" notice appears in the header when:
  - Market is OPEN and `age_min = (now_et - md.asof).total_seconds / 60 > stale_warn_minutes` (default 20)
- When market is CLOSED/HOLIDAY/WEEKEND, staleness is not flagged (data is final)
- The `cache_ttl_seconds` (default 55) controls how long fresh data is reused within a session

### Refresh behavior (spec 21)

- **Market OPEN**: re-download at most every `cache_ttl_seconds` (default 55s)
- **Market CLOSED/HOLIDAY/WEEKEND**: data is final; re-download at most hourly (3600s)
- **PRE-MARKET**: re-download at most every 10 minutes (600s)
- `fetch_session()` is called on each auto-refresh tick (`st.fragment run_every=Ns`)
- The `settings.data.intraday_interval` (default `5m`, configurable via sidebar to `1m`) controls the bar interval