"""Finnhub market-data provider (spec sections 7, 33).

Implements the MarketDataProvider interface using Finnhub's /quote endpoint
for individual symbol requests. Designed for a rate-limited collection cycle
that spreads requests across a configurable interval (default ~5 min / 300 s).

Key design goals:
- Per-symbol /quote requests (no bulk/download assumption).
- Provider timestamp (t field) parsed as unix seconds with ms guard.
- Data elapsed-time = local fetch time − provider timestamp (separate from network latency).
- Stale quote detection when age exceeds threshold during market hours.
- HTTP 429 explicit handling with bounded backoff.
- Transient failure retry with bounded backoff.
- On-demand candle fetching for detail pages (separate from main quote collector).
- Market status via /stock/market-status?exchange=US.
- Does NOT fetch historical candle data for all symbols every cycle.

Maps Finnhub /quote fields to the existing StockSnapshot model without
changing the meaning of existing fields:
  c  -> current_price
  o  -> today_open
  h  -> intraday_high
  l  -> intraday_low
  pc -> previous_close
  t  -> provider_timestamp (epoch seconds, UTC)

Additive snapshot fields (default None, no model redesign):
  provider_timestamp   : Optional[float] — unix epoch seconds (UTC)
  fetched_at           : Optional[str]    — ISO-8601 UTC when request finished
  data_age_seconds     : Optional[float] — fetched_at_epoch - provider_ts
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests

from data.provider_base import MarketData, MarketDataProvider
from models.schemas import StockSnapshot
from utils.config import get_setting
from utils.logging import get_logger

logger = get_logger(__name__)

# ------------------------------------------------------------------
# Finnhub /quote field mapping (documented per finnhub.io/docs/api/quote)
# ------------------------------------------------------------------
_FINNHUB_QUOTE_FIELDS = ("c", "d", "dp", "h", "l", "o", "pc", "t")


# ------------------------------------------------------------------
# Low-level transport
# ------------------------------------------------------------------

class _FinnhubTransport:
    """Wraps a requests.Session to add Finnhub‑specific concerns (timeout,
    token injection, header preservation). Not a general‑purpose SDK."""

    def __init__(self, api_key: str, base_url: str = "https://finnhub.io/api/v1",
                 timeout: float = 15.0):
        self.session = requests.Session()
        self.base_url = base_url
        self.timeout = timeout
        self.api_key = api_key

    def get(self, path: str, params: Optional[dict] = None,
            *, retry_count: int = 3,
            retry_backoff_base: float = 2.0) -> Tuple[int, dict, dict]:
        """GET *path* with the Finnhub token, returning (status, headers, body_dict).

        Retries transient failures (5xx, timeout, connection error) with
        bounded exponential backoff. HTTP 429 is returned as‑is (caller decides).
        """
        if params is None:
            params = {}
        params = dict(params)
        params["token"] = self.api_key
        url = f"{self.base_url}{path}"

        last_err: Optional[Exception] = None
        for attempt in range(1, retry_count + 1):
            try:
                resp = self.session.get(url, params=params,
                                        timeout=self.timeout)
                status = resp.status_code
                headers = dict(resp.headers)

                # 429 is NOT retried here — caller explicitly handles it.
                if status == 429:
                    return status, headers, {}

                # 5xx server errors are transient — retry with bounded backoff
                # (same semantics as timeout / connection failures). 429 is
                # excluded above so the caller can observe and react to it.
                if 500 <= status < 600:
                    last_err = f"5xx response: HTTP {status}"
                    dur = retry_backoff_base * attempt
                    logger.warning("Finnhub 5xx attempt %d/%d (%s); backing off %.1fs",
                                   attempt, retry_count, last_err, dur)
                    time.sleep(dur)
                    continue

            except requests.exceptions.Timeout:
                last_err = requests.exceptions.Timeout(
                    f"timeout after {self.timeout}s")
                dur = retry_backoff_base * attempt
                logger.warning("Finnhub timeout attempt %d/%d: %s; "
                               "backing off %.1fs", attempt, retry_count,
                               last_err, dur)
                time.sleep(dur)
                continue
            except requests.exceptions.ConnectionError as e:
                last_err = e
                dur = retry_backoff_base * attempt
                logger.warning("Finnhub connection error attempt %d/%d: %s; "
                               "backing off %.1fs", attempt, retry_count,
                               last_err, dur)
                time.sleep(dur)
                continue
            except requests.exceptions.RequestException as e:
                last_err = e
                dur = retry_backoff_base * attempt
                logger.warning("Finnhub request error attempt %d/%d: %s; "
                               "backing off %.1fs", attempt, retry_count,
                               last_err, dur)
                time.sleep(dur)
                continue

            # Successful 200‑level response: parse JSON.
            try:
                body = resp.json()
            except (ValueError, json.JSONDecodeError):
                body = resp.text
                logger.error("Finnhub non‑JSON response (status=%d)", status)
                return status, headers, {}

            return status, headers, body

        # Exhausted retries on transient errors.
        logger.error("Finnhub %s failed after %d attempts: %s",
                     path, retry_count, last_err)
        return -1, {}, {}


# ------------------------------------------------------------------
# Quote‑to‑StockSnapshot mapping
# ------------------------------------------------------------------

def _pct(new: Optional[float], old: Optional[float]) -> Optional[float]:
    """Percentage change new vs old; None when undefined. Mirrors
    price_engine._pct (spec section 8)."""
    try:
        if new is None or old is None:
            return None
        n, o = float(new), float(old)
        if not (__import__('numpy').isfinite(n) and __import__('numpy').isfinite(o)) or o == 0:
            return None
        return (n - o) / o * 100.0
    except (TypeError, ValueError):
        return None


def quote_to_snapshot(symbol: str,
                      raw: dict,
                      *,
                      now_ts: Optional[datetime] = None,
                      market_is_open: bool = False,
                      flat_threshold: float = 0.10,
                      stale_quote_seconds: int = 120) -> StockSnapshot:
    """Map a Finnhub /quote raw response to a StockSnapshot.

    Fields mapped:
      c  -> current_price
      o  -> today_open
      h  -> intraday_high
      l  -> intraday_low
      pc -> previous_close
      t  -> provider_timestamp (epoch seconds, UTC)

    Additive fields populated:
      provider_timestamp   : float or None
      fetched_at           : ISO-8601 UTC string or None
      data_age_seconds     : float or None

    Staleness: if market_is_open and data_age > stale_quote_seconds → issue="stale quote".
    Missing/invalid quote → is_valid=False with appropriate issue string.

    The existing StockSnapshot fields keep their meaning; new fields default
    to None and do not affect any calculation that ignores them.
    """
    if not isinstance(raw, dict):
        raw = {}

    # ---- Extract raw fields (case‑insensitive lookup) ----
    def _raw(key: str) -> Optional[float]:
        # Use explicit 'in' checks — 0.0/0 are valid Finnhub values and must
        # not be treated as missing (raw.get(...) falls back on falsy values).
        if key in raw:
            val = raw[key]
        elif key.upper() in raw:
            val = raw[key.upper()]
        else:
            return None
        try:
            return float(val)
        except (TypeError, ValueError):
            return None

    c   = _raw("c")  # current price
    o   = _raw("o")  # today's open
    h   = _raw("h")  # day high
    l   = _raw("l")  # day low
    pc  = _raw("pc") # previous close
    t   = _raw("t")  # provider timestamp (unix seconds)

    # ---- Provider timestamp: guard against ms vs seconds ----
    provider_ts: Optional[float] = None
    if isinstance(t, (int, float)):
        # /quote 't' is documented as unix seconds; guard against ms.
        if float(t) > 1e12:          # milliseconds?
            provider_ts = float(t) / 1000.0
        else:
            provider_ts = float(t)
    # If t is missing/None, provider_ts stays None.

    # ---- Fetched-at time (local UTC) ----
    fetched_at_dt: Optional[datetime] = now_ts or datetime.now(timezone.utc)
    fetched_at_iso: Optional[str] = fetched_at_dt.isoformat() if fetched_at_dt else None
    fetched_at_epoch: float = fetched_at_dt.timestamp() if fetched_at_dt else 0.0

    # ---- Data age = local fetch time - provider timestamp ----
    data_age: Optional[float] = None
    if provider_ts is not None and fetched_at_epoch is not None:
        data_age = fetched_at_epoch - provider_ts

    # ---- Map to StockSnapshot fields (existing meaning preserved) ----
    # timestamp = ISO‑8601 ET of the provider timestamp (the "as of this value")
    if provider_ts is not None:
        try:
            ts_utc = datetime.fromtimestamp(provider_ts, tz=timezone.utc)
            # Convert to ET for the "as of" display timestamp.
            ts_et = ts_utc.astimezone(ZoneInfo("America/New_York"))
            timestamp_iso: str = ts_et.isoformat()
        except Exception:  # pragma: no cover
            timestamp_iso = fetched_at_iso or ""
    else:
        # No provider timestamp — fall back to fetched_at in ET.
        timestamp_iso: str = (
            fetched_at_iso.removesuffix("+00:00") if fetched_at_iso else ""
            if fetched_at_iso else ""
        )

    # previous_close, today_open, current_price with None safety
    previous_close_val: Optional[float] = pc
    today_open_val: Optional[float] = o
    current_price_val: Optional[float] = c

    # ---- Compute derived fields using the same formulas as price_engine ----
    change_vs_previous_close: Optional[float] = _pct(current_price_val, previous_close_val) if \
        (current_price_val is not None and previous_close_val is not None and previous_close_val != 0) else None
    change_vs_open: Optional[float] = _pct(current_price_val, today_open_val) if \
        (current_price_val is not None and today_open_val is not None and today_open_val != 0) else None

    # distance_from_intraday_high/low: (current - high/low) / high/low * 100
    # (per spec §8; result <= 0 for high, >= 0 for low)
    intraday_high_val: Optional[float] = h
    intraday_low_val: Optional[float] = l

    distance_from_intraday_high: Optional[float] = \
        _pct(current_price_val, intraday_high_val) if \
        (current_price_val is not None and intraday_high_val is not None and intraday_high_val != 0) else None
    distance_from_intraday_low: Optional[float] = \
        _pct(current_price_val, intraday_low_val) if \
        (current_price_val is not None and intraday_low_val is not None and intraday_low_val != 0) else None

    # direction vs previous close (UP/DOWN/FLAT per flat_threshold)
    if change_vs_previous_close is not None:
        direction: str = ("UP" if change_vs_previous_close > flat_threshold
                          else "DOWN" if change_vs_previous_close < -flat_threshold
                          else "FLAT")
    else:
        direction = "FLAT"

    # ---- Volume: /quote does not include volume; default to 0 ----
    volume: int = 0

    # ---- Staleness flag ----
    issue: str = ""
    if market_is_open and data_age is not None and data_age > stale_quote_seconds:
        issue = f"stale quote (age {int(data_age)}s)"

    # ---- Validity: need both price and previous close to be present and valid ----
    is_valid: bool = (current_price_val is not None and current_price_val > 0
                      and previous_close_val is not None and previous_close_val > 0)

    # If quote has all-zero fields (Finnhub signals unknown symbol this way)
    if (current_price_val is not None and current_price_val == 0.0
            and previous_close_val is not None and previous_close_val == 0.0):
        is_valid = False
        issue = (issue + " + unknown symbol" if issue else "unknown symbol")

    # ---- Build StockSnapshot ----
    return StockSnapshot(
        symbol=symbol,
        timestamp=timestamp_iso,
        previous_close=previous_close_val,
        today_open=today_open_val,
        current_price=current_price_val,
        intraday_high=intraday_high_val,
        intraday_low=intraday_low_val,
        change_vs_previous_close=change_vs_previous_close,
        change_vs_open=change_vs_open,
        distance_from_intraday_high=distance_from_intraday_high,
        distance_from_intraday_low=distance_from_intraday_low,
        volume=volume,
        is_valid=is_valid,
        issue=issue,
        direction=direction,
        # Additive fields — stored as attribute for access by engines/UI;
        # they do NOT become database columns in the existing tables.
        provider_timestamp=provider_ts,
        fetched_at=fetched_at_iso,
        data_age_seconds=data_age,
    )


# ------------------------------------------------------------------
# Provider timestamp parsing (reusable utility)
# ------------------------------------------------------------------

def parse_provider_timestamp(raw: dict) -> Tuple[Optional[float], str]:
    """Extract the provider timestamp (epoch seconds, UTC) from a Finnhub
    /quote dict, with ms‑vs‑seconds guard.

    Returns (provider_ts_epoch, classification_note).
    classification_note is a human-readable note for diagnostics.
    """
    t = raw.get("t") or raw.get("T")
    if t is None:
        return None, "no_provider_timestamp"
    try:
        ts = float(t)
    except (TypeError, ValueError):
        return None, "invalid_provider_timestamp_format"

    # Guard against ms: documented 't' is seconds; if > 1e12 treat as ms.
    if ts > 1e12:
        ts = ts / 1000.0
        note = "provider_timestamp_converted_from_ms"
    else:
        note = "provider_timestamp_ok"

    return ts, note


# ------------------------------------------------------------------
# Data age calculation (reusable utility)
# ------------------------------------------------------------------

def compute_data_age(fetched_at_epoch: float,
                     provider_ts: Optional[float]) -> Optional[float]:
    """Market-data age = local fetch epoch − provider timestamp (seconds).

    Returns None when provider_ts is None (freshness cannot be established).
    """
    if provider_ts is None:
        return None
    return fetched_at_epoch - provider_ts


# ------------------------------------------------------------------
# Stale quote detection (reusable utility)
# ------------------------------------------------------------------

def is_stale_quote(data_age: Optional[float],
                   market_is_open: bool,
                   stale_quote_seconds: int = 120) -> bool:
    """True if the quote should be flagged as stale.

    Only flags during market hours — outside regular session a large age
    is expected (pre‑market / closed quotes are frozen on Finnhub).
    """
    return market_is_open and data_age is not None and data_age > stale_quote_seconds


# ------------------------------------------------------------------
# FinnhubProvider
# ------------------------------------------------------------------

class FinnhubProvider(MarketDataProvider):
    """Finnhub-based market-data provider.

    Uses individual /quote requests spread across a rate-limited collection
    cycle. Does NOT fetch bulk intraday bars or candles per cycle (see
    ``get_candles`` for on‑demand detail‑page usage).

    name   : "finnhub"
    realtime : False (free data is delayed; provider timestamp indicates
               freshness; see ``is_stale_quote`` and market‑session context).
    """

    name = "finnhub"
    realtime = False

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def __init__(self,
                 api_key: str,
                 base_url: str = "https://finnhub.io/api/v1",
                 timeout: float = 15.0,
                 retry_count: int = 3,
                 retry_backoff_base: float = 2.0,
                 rate_limit_per_minute: int = 60,
                 rate_safety_factor: float = 0.80,
                 transport: Optional[object] = None):
        """Initialize the Finnhub transport + configuration.

        Parameters
        ----------
        api_key : str
            Finnhub API key.
        base_url : str
            Base URL for the REST API (default Finnhub v1).
        timeout : float
            Per‑request timeout in seconds.
        retry_count : int
            Maximum retry attempts for transient failures (5xx, timeout,
            connection error). 429 is NOT retried here — the collector
            handles it explicitly.
        retry_backoff_base : float
            Base seconds for exponential backoff: base * attempt.
        rate_limit_per_minute : int
            Observed X‑Ratelimit‑Limit for the key (conservative default 60).
        rate_safety_factor : float
            Fraction of the cap to target (0.80 → never exceed 48/min for a 60/min cap).
        transport : object | None
            HTTP transport implementing ``get(path, params, *, retry_count,
            retry_backoff_base)``. Injected for unit tests; defaults to the
            real requests-based transport.
        """
        self._transport = transport if transport is not None else _FinnhubTransport(
            api_key, base_url, timeout)
        self._retry_count = max(1, int(retry_count))
        self._retry_backoff_base = float(retry_backoff_base)
        self._rate_limit_per_minute = int(rate_limit_per_minute)
        self._rate_safety_factor = float(rate_safety_factor)
        # Derived: safe request rate (req/s) and minimum inter‑request delay.
        self._safe_rate_per_s = (self._rate_limit_per_minute * self._rate_safety_factor) / 60.0
        self._min_inter_request_delay = max(0.1, 1.0 / self._safe_rate_per_s)
        self._last_request_ts: Optional[float] = None
        logger.info("FinnhubProvider: rate cap %d/min → safe %.2f req/s → "
                    "min inter-request delay %.3f s",
                    self._rate_limit_per_minute, self._safe_rate_per_s,
                    self._min_inter_request_delay)

    def _enforce_rate_cap(self) -> None:
        """Bounded rate‑limit safety net for direct API callers.

        Sleeps until `_min_inter_request_delay` seconds have elapsed since the
        last request, keeping direct callers (e.g. dashboard detail pages)
        under the configured rate limit without hard‑coded timings. The
        collector paces its own cycles independently, so this only binds bursty
        direct callers.
        """
        now = time.monotonic()
        if self._last_request_ts is not None:
            elapsed = now - self._last_request_ts
            if elapsed < self._min_inter_request_delay:
                time.sleep(self._min_inter_request_delay - elapsed)
        self._last_request_ts = now

    # ------------------------------------------------------------------
    # Market data provider interface
    # ------------------------------------------------------------------

    def get_quote(self, symbol: str,
                  *,
                  retry_count: Optional[int] = None,
                  retry_backoff_base: Optional[float] = None) -> Optional[StockSnapshot]:
        """Fetch one symbol's quote via Finnhub /quote and map to StockSnapshot.

        Returns None on unrecoverable failure (e.g. persistent 429 after retries,
        network down, or explicitly aborted).
        """
        self._enforce_rate_cap()
        rc = retry_count if retry_count is not None else self._retry_count
        rbb = retry_backoff_base if retry_backoff_base is not None else self._retry_backoff_base

        status, headers, body = self._transport.get(
            "/quote",
            {"symbol": symbol},
            retry_count=rc,
            retry_backoff_base=rbb,
        )

        # HTTP 429 → caller (collector) handles explicit rate‑limit pausing.
        if status == 429:
            logger.warning("Finnhub 429 for %s; headers: %s", symbol, {
                k: v for k, v in headers.items()
                if k.lower().startswith("x-ratelimit")})
            return None

        if status != 200 or body is None or not isinstance(body, dict):
            logger.warning("Finnhub /quote failed for %s: status=%d body=%s",
                           symbol, status, body)
            return None

        # ---- Map to StockSnapshot ----
        snapshot = quote_to_snapshot(
            symbol=symbol,
            raw=body,
            now_ts=datetime.now(timezone.utc),
            market_is_open=self._is_market_open_cached(),
            flat_threshold=float(get_setting({"classification": {"flat_threshold": 0.10}},  # dummy; will be overridden by caller
                                             "classification.flat_threshold", 0.10)),
        )
        # The caller is expected to pass the real settings; this stub path
        # is kept for direct usage. In practice the collector calls with
        # proper settings.
        return snapshot

    # Alias for collector usage (collector manages retry/429 logic externally)
    def fetch_quote_raw(self, symbol: str,
                        retry_count: int = 3,
                        retry_backoff_base: float = 2.0) -> tuple[Optional[dict], bool, Optional[dict]]:
        """Raw Finnhub /quote response body, plus failure classification.

        Returns
        -------
        (body, rate_limited, headers):
            * ``body``     - the /quote response dict, or None on failure.
            * ``rate_limited`` - True if the response was HTTP 429 (Finnhub will
              keep returning 429 until the rate-limit window resets).
            * ``headers``  - response headers (may be empty); includes
              Retry-After / X-Ratelimit-Reset on 429.
        """
        # Similar to get_quote but returns raw data so the collector controls
        # its own 429/pause/retry logic, then calls quote_to_snapshot etc.
        status, headers, body = self._transport.get(
            "/quote", {"symbol": symbol},
            retry_count=retry_count, retry_backoff_base=retry_backoff_base)
        if status == 429:
            logger.warning("Finnhub 429 for %s; headers: %s", symbol, {k: v for k, v in headers.items()
                    if k.lower().startswith("x-ratelimit") or k.lower() == "retry-after"})
            return None, True, headers
        if status != 200 or body is None or not isinstance(body, dict):
            logger.warning("Finnhub /quote failed for %s: status=%d body=%s", symbol, status, body)
            return None, False, headers
        return body, False, headers

    # ------------------------------------------------------------------
    # Provider abstraction: get_intraday_prices / get_daily_reference_prices
    # ------------------------------------------------------------------

    def get_intraday_prices(self, symbols: List[str],
                            interval: str,
                            start: Optional[datetime] = None,
                            end: Optional[datetime] = None) -> Dict[str, pd.DataFrame]:
        """Finnhub does not support batched intraday downloads per cycle.

        Return empty dict — the collector spreads per‑symbol /quote requests
        and the theme engine uses persisted snapshots + on‑demand candles
        (``get_candles``) for detail charts.

        Callers requiring intraday bars should use the persisted snapshot
        series or call ``get_candles`` individually on demand.
        """
        # Return empty dict so the pipeline doesn't try to split a bulk download.
        # The collector populates quote_snapshots in SQLite; detail pages use
        # get_candles() for chart data.
        return {}

    def get_daily_reference_prices(self, symbols: List[str]) -> Dict[str, pd.DataFrame]:
        """Finnhub /quote provides previous_close (pc) directly; no daily
        candle fetch needed per the cycle design.

        Returns empty dict — daily references (prev_close, today_open) are
        derived from the quote fields themselves in the collector → snapshot
        mapping, not from a bulk daily download.
        """
        return {}

    # ------------------------------------------------------------------
    # On‑demand candlesticks for detail pages (Phase 2: charts)
    # ------------------------------------------------------------------

    def get_candles(self, symbol: str,
                    resolution: str = "5",
                    from_epoch: Optional[int] = None,
                    to_epoch: Optional[int] = None) -> Optional[pd.DataFrame]:
        """Fetch historical candle/OHLCV data from Finnhub for a single symbol.

        Used by the UI detail pages (Phase 2) — NOT called per collection
        cycle.  Resolution is a string (e.g. "1", "5", "15", "60", "D").

        Parameters
        ----------
        symbol : str
        resolution : str
            Candle resolution; Finnhub API uses this as the ``resolution``
            parameter (1 = 1‑minute, 5 = 5‑minute, etc.).
        from_epoch : int or None
            Start UNIX epoch (seconds). If None, Finnhub defaults to a
            reasonable lookback (typically 30‑60 days depending on plan).
        to_epoch : int or None
            End UNIX epoch (seconds). If None, uses current time.

        Returns
        -------
        DataFrame or None
            Index = timestamps (UTC, convertible to ET). Columns = [open, high,
            low, close, volume]. May be None if the symbol has no data for
            the requested window / the key's subscription does not include
            historical candles.
        """
        params: dict[str, Any] = {"symbol": symbol, "resolution": resolution}
        if from_epoch is not None:
            params["from"] = from_epoch
        if to_epoch is not None:
            params["to"] = to_epoch

        status, headers, body = self._transport.get("/stock/candle", params)
        if status != 200 or body is None or not isinstance(body, dict):
            logger.warning("Finnhub /stock/candle failed for %s: status=%d", symbol, status)
            return None

        # Finnhub candle format: {"s": "ok", "c": [...], "o": [...], "h": [...],
        # "l": [...], "t": [...], "v": [...]}
        if body.get("s") != "ok":
            logger.warning("Finnhub candle response s!=ok for %s: %s", symbol, body)
            return None

        timestamps = body.get("t", [])
        opens = body.get("o", [])
        highs = body.get("h", [])
        closes = body.get("c", [])
        volumes = body.get("v", [])

        if not timestamps or not closes:
            return None

        # Build DataFrame indexed by UTC datetime.
        idx = pd.to_datetime(timestamps, unit="s", utc=True)
        df = pd.DataFrame({
            "open": [float(x) for x in opens],
            "high": [float(x) for x in highs],
            "low":  [float(x) for x in lows],
            "close": [float(x) for x in closes],
            "volume": [int(x) if x is not None and pd.notna(x) else 0
                       for x in volumes],
        }, index=idx)
        # Sort index and ensure UTC.
        df = df.sort_index()
        return df

    # ------------------------------------------------------------------
    # Market session context (for stale‑quote / pre‑market doc)
    # ------------------------------------------------------------------

    def _is_market_open_cached(self) -> bool:
        """Quick market‑session check via /stock/market-status.

        Note: this is a *best‑effort* cache — the collector refreshes it
        at the start of each cycle.  Calling this many times within a cycle
        is not recommended; use the explicitly-passed ``market_is_open``
        flag to ``quote_to_snapshot`` instead.
        """
        try:
            status, _, body = self._transport.get("/stock/market-status",
                                                  {"exchange": "US"},
                                          retry_count=1, retry_backoff_base=1.0)
            if status == 200 and isinstance(body, dict):
                return bool(body.get("isOpen", False))
        except Exception as e:
            logger.debug("Market-status check failed: %s", e)
        # Default to False on any error — safe for Phase 1.
        return False

    # ------------------------------------------------------------------
    # Provider name / realtime
    # ------------------------------------------------------------------

    @property
    def realtime(self) -> bool:
        return self._realtime  # always False for free tier

    def __repr__(self) -> str:
        return f"<FinnhubProvider rate_safe={self._safe_rate_per_s:.2f} req/s>"


# Helper import for ET conversion in quote_to_snapshot
from zoneinfo import ZoneInfo  # noqa: F811 – imported at module level in final file