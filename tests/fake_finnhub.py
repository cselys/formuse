"""Deterministic fake Finnhub client for unit tests.

Never touches the network. Supports scripted quote responses, 429 simulation,
transient failure simulation, fake clocks, and request counting.

Usage
-----
    from tests.fake_finnhub import FakeFinnhubClient
    import time

    client = FakeFinnhubClient()
    client.add_quote("AAPL", {"c": 101.0, "pc": 100.0, "o": 100.5,
                              "h": 102.0, "l": 99.5, "t": ts})
    client.add_quote("NVDA", {"c": 233.95, "pc": 230.86, "o": 231.0,
                              "h": 235.0, "l": 229.0, "t": ts})

    # 429 on the next request:
    client.rate_limit()

    # First 3 requests fail with 500, then succeed:
    client.transient_500(3)

    # Replace all quote timestamps with a fake clock:
    client.now = lambda: datetime.fromisoformat("2026-10-05T14:00:00+00:00")
    client.sleep = lambda s: None  # no real sleeps in tests
"""
from __future__ import annotations

import requests
import time

from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional


class FakeFinnhubClient:
    """Deterministic Finnhub client for tests.

    Attributes (injected):
      now : callable -> datetime.now for quote timestamps (default real now)
      sleep : callable (seconds) -> None (default: real time.sleep)
    """

    def __init__(self, responses: Optional[dict] = None):
        self.responses: Dict[tuple, tuple] = {}
        # endpoint (method, path, symbol-or-"*") -> remaining 429 hits;
        # the wildcard key ("*") covers every symbol.
        self.rate_limited: Dict[tuple, int] = {}
        # transient 500s (endpoint -> remaining)
        self.fail_500: Dict[tuple, int] = {}       # (endpoint, symbol) -> remaining 500s
        # simulated timeouts (endpoint -> remaining)
        self.fail_timeout: Dict[tuple, int] = {}   # (endpoint, symbol) -> remaining timeouts
        self.calls: List[dict] = []                 # every request recorded
        self.now = lambda: datetime.now(timezone.utc)
        self.sleep = lambda s: None
        if responses:
            for sym, body in responses.items():
                self.add_quote(sym, body)

    def _key(self, endpoint: str, symbol: Optional[str] = None) -> tuple:
        return ("GET", endpoint, symbol or "*")

    @property
    def transport(self):
        """Exposes the fake transport so the collector/provider can be injected
        with it for unit tests (FinnhubProvider uses _transport)."""
        return self

    # ----------------------------------------------------------------- quotes
    def add_quote(self, symbol: str, body: dict) -> "FakeFinnhubClient":
        """Script a /quote response for *symbol*."""
        self.responses[self._key("/quote", symbol)] = (200, {}, dict(body))
        return self

    def set_quotes(self, responses: Dict[str, dict]) -> "FakeFinnhubClient":
        """Script /quote responses for multiple symbols at once."""
        for sym, body in responses.items():
            self.add_quote(sym, body)
        return self

    # --- malformed / missing-field quotes -------------------------------------------------
    def zero_quote(self, symbol: str) -> "FakeFinnhubClient":
        """All-zero quote (Finnhub's unknown-symbol signal)."""
        return self.add_quote(symbol, {
            "c": 0.0, "d": 0.0, "dp": 0.0, "h": 0.0, "l": 0.0,
            "o": 0.0, "pc": 0.0, "t": 0})

    def unknown_quote(self, symbol: str) -> "FakeFinnhubClient":
        """Quote without any data fields."""
        return self.add_quote(symbol, {})

    def no_timestamp_quote(self, symbol: str) -> "FakeFinnhubClient":
        """Quote missing the 't' provider timestamp."""
        return self.add_quote(symbol, {
            "c": 101.0, "pc": 100.0, "o": 100.5, "h": 102.0, "l": 99.5})

    def ms_timestamp(self, symbol: str) -> "FakeFinnhubClient":
        """Quote with 't' in milliseconds (must be divided by 1000)."""
        return self.add_quote(symbol, {
            "c": 101.0, "pc": 100.0, "o": 100.5, "h": 102.0, "l": 99.5,
            "t": 1760000000000})

    def stale_quote(self, symbol: str, age_seconds: float) -> "FakeFinnhubClient":
        """Quote with a provider timestamp older than *age_seconds*."""
        base = datetime.now(timezone.utc)
        return self.add_quote(symbol, {
            "c": 101.0, "pc": 100.0, "o": 100.5, "h": 102.0, "l": 99.5,
            "t": (base.timestamp() - age_seconds)})

    # ---------------------------------------------------------------- rate limits
    def rate_limit(self) -> "FakeFinnhubClient":
        """Next /quote request returns HTTP 429."""
        self.rate_limited[self._key("/quote")] = self.rate_limited.get(
            self._key("/quote"), 0) + 1
        return self

    def rate_limit_n(self, n: int) -> "FakeFinnhubClient":
        """Next *n* /quote requests return HTTP 429."""
        self.rate_limited[self._key("/quote")] = self.rate_limited.get(
            self._key("/quote"), 0) + n
        return self

    # ------------------------------------------------------------------ failures
    def transient_500(self, n: int) -> "FakeFinnhubClient":
        """Next *n* /quote requests fail with HTTP 500."""
        self.fail_500[self._key("/quote")] = self.fail_500.get(
            self._key("/quote"), 0) + n
        return self

    def transient_timeout(self, n: int) -> "FakeFinnhubClient":
        """Next *n* /quote requests raise requests.exceptions.Timeout."""
        self.fail_timeout[self._key("/quote")] = self.fail_timeout.get(
            self._key("/quote"), 0) + n
        return self

    # ---------------------------------------------------------------- recording
    def get_call_count(self) -> int:
        return len(self.calls)

    def last_call(self) -> Optional[dict]:
        return self.calls[-1] if self.calls else None

    def clear_calls(self) -> None:
        self.calls.clear()

    # ---------------------------------------------------------------- transport
    def get(self, path: str, params: dict,
            *, retry_count: int, retry_backoff_base: float) -> tuple:
        """Mirror of _FinnhubTransport.get with fake behavior.

        Retry semantics (same as the real transport):
          * 429 is returned as-is (no retry) — caller handles it.
          * 5xx is transient -> retried with bounded exponential backoff.
          * timeouts raise immediately -> retried with backoff.
          * otherwise the scripted/response body is returned.
        """
        last_err: Optional[Exception] = None
        for attempt in range(1, retry_count + 1):
            try:
                symbol = params.get("symbol")
                key = self._key(path, symbol)
                call = {
                    "path": path, "params": dict(params), "symbol": symbol,
                    "retry_count": retry_count, "retry_backoff_base": retry_backoff_base,
                }
                now_epoch = self.now().timestamp()

                # --- 429 ------------------------------------------------------------------
                # Counter semantics + endpoint wildcard so both rate_limit() and
                # symbol-specific keys work. The wildcard key ("*") covers every symbol.
                hit = None
                if key in self.rate_limited and self.rate_limited[key] > 0:
                    hit = key
                elif self._key(path, "*") in self.rate_limited \
                        and self.rate_limited[self._key(path, "*")] > 0:
                    hit = self._key(path, "*")
                if hit:
                    self.rate_limited[hit] -= 1
                    call["status"] = 429
                    self.calls.append(call)
                    return (429, {"Retry-After": "65", "X-Ratelimit-Limit": "60"}, {})

                # --- transient failures (endpoint-wildcard key so any symbol works) ----
                if self.fail_500.get(self._key(path, "*"), 0) > 0:
                    self.fail_500[self._key(path, "*")] -= 1
                    last_err = f"5xx response: HTTP 500"
                    call["status"] = 500
                    self.calls.append(call)  # record retried attempts
                    time.sleep(retry_backoff_base * attempt)  # backoff on retry
                    continue  # retry like the real transport does on 5xx
                if self.fail_timeout.get(self._key(path, "*"), 0) > 0:
                    self.fail_timeout[self._key(path, "*")] -= 1
                    call["status"] = None  # no HTTP status for a simulated timeout
                    self.calls.append(call)  # record the retried attempt
                    raise requests.exceptions.Timeout(
                        f"timeout after 15s (simulated)")

                # --- scripted response --------------------------------------------------
                if key in self.responses:
                    status, headers, body = self.responses[key]
                    if path == "/quote" and isinstance(body, dict) and "t" not in body:
                        body = dict(body, t=now_epoch)
                    call["status"] = status
                    self.calls.append(call)
                    return (status, dict(headers), body)

                # --- default ------------------------------------------------------------
                call["status"] = 404
                self.calls.append(call)
                return (404, {}, {"error": "no data", "message": "unknown symbol"})

            except requests.exceptions.Timeout as e:
                last_err = e
                time.sleep(retry_backoff_base * attempt)  # backoff on retry
                continue

        # --- exhausted retries: return last error status --------------------------
        if isinstance(last_err, Exception):
            return (-1, {}, {})
        return (404, {}, {"error": "no data"})
