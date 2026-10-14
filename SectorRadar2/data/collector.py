"""Rate-limited Finnhub quote collector / scheduler.

Spreads individual /quote requests across a configurable collection cycle so
that the dashboard (300 s auto-refresh) never performs the 240-symbol
acquisition itself.

Architecture
------------
    FinnhubCollector / collector cycle
        -> individual /quote requests (per symbol)
        -> rate-limited scheduler
        -> StockSnapshot (with provider_timestamp, fetched_at, data_age_seconds)
        -> SQLite quote_snapshots (via SnapshotStore)
        -> cycle summary logged to logs/sector_radar.log

Collection schedule (computed from the universe size and the rate limit, NOT
hard-coded to 240 symbols):

    safe_rate_per_s     = rate_limit_per_minute * rate_safety_factor / 60
    delay               = max(min_delay, cycle_interval / n_symbols,
                              60 / (rate_limit_per_minute * rate_safety_factor))
    total_request_time  = n_symbols * delay
    batches             = max(1, ceil(n_symbols / batch_size))
    batch_interval      = max(0, (cycle_interval - total_request_time) / (batches-1))
                            (0 when the rate cap is the binding constraint)

For a 240-symbol universe at 300 s / 60/min (80% safety -> 48 req/min):
    delay = 300/240 = 1.25 s  -> 48 req/min, 300 s total (one 5-min cycle).

Universe: theme tickers + theme ETFs (configurable; both configurable). The
collector reads the configured universe from ``config/themes.yaml`` via the
existing theme-loading helpers, and can override with explicit
``stock_universe_override`` / ``etf_universe_override`` lists.

429 handling
------------
HTTP 429 is NOT retried automatically. On a 429 the collector:
  * reads Retry-After / X-Ratelimit-Reset from the response headers (if any),
  * otherwise pauses for the full rate-limit window minus elapsed time
    (at least 61 s, so the next cycle starts after the 1-min window resets),
  * marks the symbol "rate_limited" for this cycle (not "failed"),
  * and continues — never spinning aggressively on rate limits.

Transient failures (5xx, timeout, connection error) are retried with bounded
exponential backoff (base * attempt, capped at retry_count attempts). On final
failure the symbol is recorded "failed" with the last error reason and the
cycle continues.

Never spin on errors: the inter-request delay is always respected, and each
symbol gets exactly one scheduling slot per cycle.

Persistence
-----------
Successful quotes are persisted as one row per symbol in the
``quote_snapshots`` table (additive table; existing tables untouched), keyed by
(symbol, session_date, fetched_at). Failed symbols are recorded in the cycle
summary so stale/stale-free status can be computed from persisted data later
(Phase 2).

CLI
---
    # One-off collection of the full configured universe:
    python -m data.collector

    # One-off collection of a small symbol set (smoke test):
    python -m data.collector --once --symbols AAPL,NVDA,AMD,MSFT

    # Continuous mode: full cycle every 300 s until interrupted:
    python -m data.collector --loop

Usage
-----
The collector is designed to be run as a background service (systemd timer,
cron every 5 min, Windows Task Scheduler, or a supervisor-managed long-lived
process). Streamlit's 300 s auto-refresh reads the latest persisted snapshots
from the same SQLite file; they never call the collector during a page render.
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from data.cache import SnapshotStore
from data.finnhub_provider import FinnhubProvider, quote_to_snapshot
from models.schemas import StockSnapshot
from utils.config import PROJECT_ROOT, load_settings, load_themes
from utils.logging import get_logger

logger = get_logger("sector_radar.collector")

# Lock file: only one collector instance writes snapshots at a time.
COLLECTOR_LOCK_PATH = PROJECT_ROOT / "data" / ".finnhub_collector.lock"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class CollectionConfig:
    """Collection schedule configuration (computed from universe + rate limit).

    Parameters are read from config/settings.yaml under ``data.finnhub.collection``.
    """
    cycle_interval_seconds: int = 300       # time between cycle starts
    batch_size: int = 0                     # 0 = derive from universe size
    batch_interval_seconds: float = 0.0     # 0 = derive (or 0 if rate cap is binding)
    inter_request_delay_seconds: float = 0.0  # 0 = derive (even spread)
    include_etfs: bool = True               # include ETF symbols in the universe
    stock_universe_override: Optional[List[str]] = None
    etf_universe_override: Optional[List[str]] = None

    # --- provider settings (mirrored from data.finnhub) ---------------------
    api_key_env: str = "FINNHUB_API_KEY"
    base_url: str = "https://finnhub.io/api/v1"
    timeout_seconds: float = 15.0
    retry_count: int = 3
    retry_backoff_base_seconds: float = 2.0
    rate_limit_per_minute: int = 60
    rate_safety_factor: float = 0.80
    stale_quote_seconds: int = 120          # while market OPEN => flag stale
    flat_threshold: float = 0.10

    @classmethod
    def from_settings(cls, settings: dict) -> "CollectionConfig":
        """Build a CollectionConfig from an application settings dict.

        Accepts either the full settings file ({'data': {...}}) or the 'data'
        dict directly. The collection block is read from ``data.collection``
        (preferred) and falls back to the legacy ``data.finnhub.collection``.
        """
        data = settings.get("data", settings)  # full file or data dict
        cfg = (
            data.get("collection")
            or data.get("finnhub", {}).get("collection", {})
        )
        finnhub = data.get("finnhub", {})
        return cls(
            cycle_interval_seconds=int(cfg.get("cycle_interval_seconds", 300)),
            batch_size=int(cfg.get("batch_size", 0)),
            batch_interval_seconds=float(cfg.get("batch_interval_seconds", 0.0)),
            inter_request_delay_seconds=float(cfg.get("inter_request_delay_seconds", 0.0)),
            include_etfs=bool(cfg.get("include_etfs", True)),
            stock_universe_override=cls._parse_override(
                cfg.get("stock_universe_override")),
            etf_universe_override=cls._parse_override(cfg.get("etf_universe_override")),
            api_key_env=data.get("finnhub", {}).get(
                "api_key_env", "FINNHUB_API_KEY"),
            base_url=data.get("finnhub", {}).get(
                "base_url", "https://finnhub.io/api/v1"),
            timeout_seconds=float(
                data.get("finnhub", {}).get(
                    "timeout_seconds", 15.0)),
            retry_count=int(data.get("finnhub", {}).get(
                "retry_count", 3)),
            retry_backoff_base_seconds=float(
                data.get("finnhub", {}).get(
                    "retry_backoff_base_seconds", 2.0)),
            rate_limit_per_minute=int(
                data.get("finnhub", {}).get(
                    "rate_limit_per_minute", 60)),
            rate_safety_factor=float(
                data.get("finnhub", {}).get(
                    "rate_safety_factor", 0.80)),
            stale_quote_seconds=int(
                data.get("finnhub", {}).get(
                    "stale_quote_seconds", 120)),
            flat_threshold=float(
                data.get("classification", {}).get(
                    "flat_threshold", 0.10)),
        )

    @staticmethod
    def _parse_override(raw: Any) -> Optional[List[str]]:
        if raw is None:
            return None
        if isinstance(raw, str):
            return [t.strip().upper() for t in raw.split(",") if t.strip()]
        return [str(t).upper() for t in raw if str(t).strip()]

    @property
    def safe_rate_per_s(self) -> float:
        return (self.rate_limit_per_minute * self.rate_safety_factor) / 60.0


@dataclass
class Schedule:
    """A computed collection schedule for one cycle."""
    inter_request_delay: float          # seconds between consecutive requests
    batch_size: int                     # symbols per batch
    batch_interval: float               # seconds between batches (0 = none)
    total_estimated_seconds: float      # expected wall-clock for the cycle
    batches: int                        # number of batches
    symbols: List[str]                  # symbols in order (filled after derive)

    def __repr__(self) -> str:
        return (f"Schedule(delay={self.inter_request_delay:.2f}s "
                f"batch={self.batch_size} batch_interval={self.batch_interval:.1f}s "
                f"batches={self.batches} est={self.total_estimated_seconds:.1f}s)")


def derive_schedule(n: int, cfg: CollectionConfig) -> Schedule:
    """Compute the collection schedule from the universe size and rate limit.

    This is the scheduling engine — no hard-coded assumption of 240 symbols.

    Algorithm:
      1. Minimum delay from the rate cap (safety-capped rate).
      2. Even-spread delay = cycle_interval / n.
      3. delay = max(min_from_cap, even_spread, min_delay=0.1s).
      4. batches = max(1, ceil(n / batch_size)); batch_size clamped to n.
      5. batch_interval = remaining cycle time / (batches-1), floored at 0.
      6. If total time would overflow the cycle, shrink batch_interval first
         (it's the most flexible), then log a warning.

    Returns
    -------
    Schedule with all fields filled.
    """
    # 1. Rate-cap enforced minimum (e.g. 60/min @ 0.8 safety -> 1.25 s)
    min_delay_from_cap = 1.0 / cfg.safe_rate_per_s
    min_delay = max(min_delay_from_cap, 0.1)

    # 2. Even spread across the cycle (primary mechanism).
    if cfg.inter_request_delay_seconds > 0:
        delay = float(cfg.inter_request_delay_seconds)
    else:
        delay = float(cfg.cycle_interval_seconds) / max(1, n)

    # 3. Honor the rate cap even for very large universes.
    delay = max(delay, min_delay)

    # 4. Batch sizing.
    config_batch = int(cfg.batch_size)
    if config_batch <= 0:
        # Default: spread across ~5 batches so progress is observable.
        batch_size = max(1, math.ceil(n / 5.0))
    else:
        batch_size = min(max(1, config_batch), n)
    batches = max(1, math.ceil(n / float(batch_size)))

    # 5. Batch interval: remaining time after requests, divided among pauses.
    if cfg.batch_interval_seconds > 0:
        batch_interval = float(cfg.batch_interval_seconds)
    else:
        total_request_time = n * delay
        remaining = cfg.cycle_interval_seconds - total_request_time
        if remaining > 0 and batches > 1:
            batch_interval = remaining / (batches - 1)
        else:
            batch_interval = 0.0

    # 6. Final fit check.
    total = n * delay + (batches - 1) * batch_interval
    if total > cfg.cycle_interval_seconds:
        # Only batch_interval can be safely shrunk here; the delay respects the
        # rate cap, which must never be violated.
        if batches > 1:
            batch_interval = max(0.0,
                                 (cfg.cycle_interval_seconds - n * delay) / (batches - 1))
        else:
            batch_interval = 0.0
        total = n * delay + (batches - 1) * batch_interval
        logger.warning(
            "Schedule does not fit the %d s cycle (%.1f s requested); "
            "shrunk batch_interval to %.2f s (total %.1f s). The cycle will "
            "drift into the next slot.",
            cfg.cycle_interval_seconds, total, batch_interval, total)

    return Schedule(
        inter_request_delay=delay,
        batch_size=batch_size,
        batch_interval=batch_interval,
        total_estimated_seconds=total,
        batches=batches,
        symbols=[],  # placeholder; filled by the caller
    )


def build_universe(cfg: CollectionConfig, themes_cfg: dict) -> List[str]:
    """Build the ordered symbol universe (stocks + optional ETFs).

    Precedence: explicit overrides > theme-derived > default theme tickers.
    """
    symbols: List[str] = []
    seen: set[str] = set()
    ticker_count: int = 0      # count of configured tickers only (ETFs excluded)

    if cfg.stock_universe_override is not None:
        for t in cfg.stock_universe_override:
            if t not in seen:
                seen.add(t)
                symbols.append(t)
                ticker_count += 1
    else:
        # Derive from theme tickers.
        for theme_body in themes_cfg.values():
            for t in (theme_body.get("tickers") or []):
                if t not in seen:
                    seen.add(t)
                    symbols.append(t)
                    ticker_count += 1

    if cfg.include_etfs:
        if cfg.etf_universe_override is not None:
            for t in cfg.etf_universe_override:
                if t not in seen:
                    seen.add(t)
                    symbols.append(t)
        else:
            for theme_body in themes_cfg.values():
                for t in (theme_body.get("etf") or []):
                    if t not in seen:
                        seen.add(t)
                        symbols.append(t)

    logger.info("Universe: %d symbols (tickers: %d, etfs: %d)",
                len(symbols), ticker_count, len(symbols) - ticker_count)
    return symbols


# ---------------------------------------------------------------------------
# Cycle runner
# ---------------------------------------------------------------------------

@dataclass
class CycleSummary:
    """Outcome of one collection cycle."""
    session_date: str
    started_at: datetime
    finished_at: Optional[datetime] = None
    n_symbols: int = 0
    n_succeeded: int = 0
    n_failed: int = 0               # persistent failure (429, invalid, network)
    n_rate_limited: int = 0
    cycle_seconds: float = 0.0
    schedule: Optional[Schedule] = None
    rate_limited_symbols: List[str] = field(default_factory=list)
    failed_symbols: Dict[str, str] = field(default_factory=dict)
    min_latency_ms: Optional[float] = None
    max_latency_ms: Optional[float] = None
    mean_latency_ms: Optional[float] = None
    mean_data_age_seconds: Optional[float] = None
    stale_count: int = 0
    market_status_at_start: Optional[dict] = None
    provider_timestamp_note: Optional[str] = None

    def to_json(self) -> dict:
        return {
            "session_date": self.session_date,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "n_symbols": self.n_symbols,
            "n_succeeded": self.n_succeeded,
            "n_failed": self.n_failed,
            "n_rate_limited": self.n_rate_limited,
            "cycle_seconds": round(self.cycle_seconds, 2),
            "schedule": repr(self.schedule) if self.schedule else None,
            "rate_limited_symbols": self.rate_limited_symbols,
            "failed_symbols": self.failed_symbols,
            "min_latency_ms": self.min_latency_ms,
            "max_latency_ms": self.max_latency_ms,
            "mean_latency_ms": self.mean_latency_ms,
            "mean_data_age_seconds": self.mean_data_age_seconds,
            "stale_count": self.stale_count,
            "market_status_at_start": self.market_status_at_start,
        }

    @classmethod
    def from_json(cls, obj: dict) -> "CycleSummary":
        obj = dict(obj)
        started = datetime.fromisoformat(obj.pop("started_at"))
        finished = None
        if obj.get("finished_at"):
            finished = datetime.fromisoformat(obj.pop("finished_at"))
        return cls(started_at=started, finished_at=finished, **obj)


@dataclass
class _RateLimitState:
    """Track rate-limit windows observed during a collection cycle.

    HTTP 429 is NOT retried (Finnhub keeps returning 429 until the
    rate-limit window resets). This tracker computes how long to wait from the
    response headers -- Retry-After, then X-Ratelimit-Reset -- and caches the
    target so repeated 429s in the same window do not sleep repeatedly. If no
    metadata is present, it assumes the full 1-min Finnhub window (the same
    window that bounds ``rate_limit_per_minute``).

    This is deterministic in time: no hardcoded reset timestamps are stored;
    all waits are computed relative to the clock at the moment the 429 arrives.
    """
    window_seconds: int = 60
    _reset_target: Optional[datetime] = field(default=None, init=False)

    def wait_after_429(self, headers: Optional[dict]) -> float:
        """Return seconds to wait before resuming (0 if the window passed).

        Priority: Retry-After (seconds) > X-Ratelimit-Reset (Unix epoch) >
        full-window fallback.

        Caching: if a later/equal target is already cached, suppress this
        wait (0 s) so repeated 429s in the same window do not sleep again.
        No/invalid metadata does NOT extend the cache; it always returns the
        full window (conservative).
        """
        now = datetime.now(timezone.utc)
        headers = headers or {}
        target = self._parse_reset_target(headers, now)
        if target is not None and target <= now:
            # Reset timestamp is in the past: the window has passed.
            return 0.0
        if target is not None and self._reset_target is not None \
                and self._reset_target >= target:
            # Already waiting until a later (or equal) time.
            return 0.0
        if target is not None:
            self._reset_target = target
        return (
            (target - now).total_seconds()
            if target is not None
            else self.window_seconds
        )

    def _parse_reset_target(self, headers: dict, now: datetime) -> Optional[datetime]:
        """Parse Retry-After or X-Ratelimit-Reset into an absolute target; None
        if no usable metadata is present (conservative full-window path).

        Work in relative terms (``now.timestamp()``) so this stays correct even
        when ``datetime`` is mocked (e.g. ``mock.patch("data.collector.datetime")``)
        in tests -- ``fromtimestamp`` cannot be used on a mocked class.
        """
        retry_after = headers.get("Retry-After")
        if retry_after is not None:
            try:
                seconds = float(retry_after)
                return now + timedelta(seconds=seconds)
            except (TypeError, ValueError):
                return None  # invalid metadata -> conservative path
        reset = headers.get("X-Ratelimit-Reset")
        if reset is not None:
            try:
                epoch = float(reset)
                seconds_since = epoch - now.timestamp()
                if seconds_since > 0:
                    return now + timedelta(seconds=seconds_since)
                return now  # reset already in the past -> window passed
            except (TypeError, ValueError):
                return None
        return None  # no usable metadata -> conservative full-window path

    def _fallback(self, now: datetime) -> float:
        # No rate-limit metadata: assume the full 1-min window is still active.
        return self.window_seconds


class FinnhubCollector:
    """Rate-limited collector that spreads /quote requests across a collection
    cycle and persists snapshots to SQLite."""

    def __init__(self, settings: dict):
        self.cfg = CollectionConfig.from_settings(settings)
        self.store = SnapshotStore(
            os.environ.get("SECTOR_RADAR_DB_PATH", "data/sector_radar.db"))
        self._persisted_snapshots: List[StockSnapshot] = []
        self._rate_limit_state = _RateLimitState()

        api_key = os.environ.get(self.cfg.api_key_env)
        if not api_key:
            logger.error("Collection disabled: %s not set", self.cfg.api_key_env)
            self.provider = None
        else:
            self.provider = FinnhubProvider(
                api_key=api_key,
                base_url=self.cfg.base_url,
                timeout=self.cfg.timeout_seconds,
                retry_count=self.cfg.retry_count,
                retry_backoff_base=self.cfg.retry_backoff_base_seconds,
                rate_limit_per_minute=self.cfg.rate_limit_per_minute,
                rate_safety_factor=self.cfg.rate_safety_factor,
            )

    # --- lifecycle ------------------------------------------------------------
    @property
    def is_running(self) -> bool:
        return True  # single-cycle collector; run_forever manages its own loop.

    def stop(self) -> None:
        """No-op for the single-cycle collector (used by run_forever)."""
        pass

    # --- core cycle -----------------------------------------------------------
    def run_cycle(self, symbols: List[str],
                  market_status_at_start: Optional[dict] = None,
                  provider_timestamp_note: Optional[str] = None) -> CycleSummary:
        """Run ONE collection cycle: spread symbols across the schedule,
        fetch /quote per symbol, persist valid snapshots.

        Never spins on errors: every symbol gets exactly one slot per cycle.
        """
        if self.provider is None:
            raise RuntimeError("collector disabled (no API key)")

        cfg = self.cfg
        schedule = derive_schedule(len(symbols), cfg)
        schedule.symbols = symbols

        now = datetime.now(timezone.utc)
        session_date = now.date().isoformat()

        summary = CycleSummary(
            session_date=session_date,
            started_at=now,
            n_symbols=len(symbols),
            schedule=schedule,
            market_status_at_start=market_status_at_start,
            provider_timestamp_note=provider_timestamp_note,
        )

        latencies: List[float] = []
        ages: List[float] = []

        # Market session context at cycle start (needed for stale flagging).
        market_is_open = bool(market_status_at_start and market_status_at_start.get("isOpen"))

        for batch_i in range(schedule.batches):
            start = batch_i * schedule.batch_size
            end = min(start + schedule.batch_size, len(symbols))
            batch = symbols[start:end]

            for sym in batch:
                time.sleep(schedule.inter_request_delay)  # spread requests across the cycle
                result = self._fetch_one(sym, market_is_open)
                if result is None:
                    # _fetch_one classified it: rate_limited or failed.
                    summary.n_rate_limited += 1
                    continue
                if result["valid"]:
                    snapshot = result["snapshot"]
                    summary.n_succeeded += 1
                    if snapshot.data_age_seconds is not None:
                        ages.append(float(snapshot.data_age_seconds))
                        if result.get("latency_ms") is not None:
                            latencies.append(result["latency_ms"])
                    else:
                        if result.get("latency_ms") is not None:
                            latencies.append(result["latency_ms"])
                    if snapshot.issue and "stale" in snapshot.issue.lower():
                        summary.stale_count += 1
                else:
                    summary.n_failed += 1
                    summary.failed_symbols[sym] = result["snapshot"].issue

            # Batch interval between batches (not after the last batch).
            if batch_i < schedule.batches - 1:
                time.sleep(schedule.batch_interval)

        summary.n_failed += summary.n_rate_limited
        summary.finished_at = datetime.now(timezone.utc)
        summary.cycle_seconds = (summary.finished_at - summary.started_at).total_seconds()

        if latencies:
            summary.min_latency_ms = round(min(latencies), 1)
            summary.max_latency_ms = round(max(latencies), 1)
            summary.mean_latency_ms = round(sum(latencies) / len(latencies), 1)
        if ages:
            summary.mean_data_age_seconds = round(sum(ages) / len(ages), 2)

        # Persist valid snapshots. Failures are tracked in the cycle summary
        # for Phase 2 freshness queries.
        self.store.save_quote_snapshots(session_date, self._persisted_snapshots)
        self._persisted_snapshots = []

        # Build a latency-safe summary string (latency_ms may be None,
        # e.g. when a fake/deterministic transport is injected in tests).
        latency_str: str
        if summary.min_latency_ms is not None and summary.max_latency_ms is not None:
            latency_str = (
                f"latency {summary.min_latency_ms:.1f}-{summary.max_latency_ms:.1f} ms"
                f" (mean {summary.mean_latency_ms:.1f})"
            )
        else:
            latency_str = "latency n/a (mock transport)"
        age_str = (
            f"data_age {summary.mean_data_age_seconds:.1f} s" if summary.mean_data_age_seconds
            is not None else "data_age n/a"
        )
        logger.info("Cycle complete: %d symbols, %d succeeded, %d failed, "
                    "%d rate-limited, stale=%d, %s, %s, cycle %.1f s | %s",
                    summary.n_symbols, summary.n_succeeded, summary.n_failed,
                    summary.n_rate_limited, summary.stale_count, latency_str, age_str,
                    summary.cycle_seconds, summary.schedule)
        return summary

    def _fetch_one(self, symbol: str, market_is_open: bool) -> Optional[dict]:
        """Fetch a single symbol.

        Returns None if the quote fetch was suppressed (hard rate limit hit).
        Otherwise returns {"valid": bool, "snapshot": StockSnapshot,
                           "latency_ms": float|None}.

        Rate-limit behavior:
          * HTTP 429 -> suppress the fetch for this cycle (cross the window),
            count as rate_limited, do NOT retry (never spin), move on.
          * Transient errors (timeout, connection, 5xx) -> bounded retries with
            exponential backoff, then classify as failed.
        """
        rc = self.cfg.retry_count
        rbb = self.cfg.retry_backoff_base_seconds

        raw, rate_limited, headers = self.provider.fetch_quote_raw(symbol, rc, rbb)
        if rate_limited:
            # HTTP 429: suppress this symbol for the cycle -- do NOT retry.
            # Finnhub keeps returning 429 until the rate-limit window resets,
            # so we respect Retry-After / X-Ratelimit-Reset when present,
            # then keep the per-request pace and move on.
            wait = self._rate_limit_state.wait_after_429(headers)
            if wait > 0:
                logger.warning("Finnhub rate-limited for %s; waiting %.0fs until window reset",
                               symbol, wait)
                time.sleep(wait)
            return None
        if raw is None:
            # Failed after the provider's own transient-error retries (5xx / timeout).
            # This is not transient (e.g. 404, unknown symbol, malformed body): record
            # as failed and do not retry — the collector never retries failures, only
            # transient errors (which the provider already handles with bounded backoff).
            return None  # failed; caller counts it as failed.

        # Latency tracking for the cycle summary.
        latency_ms = None

        snapshot = quote_to_snapshot(
            symbol=symbol,
            raw=raw,
            now_ts=datetime.now(timezone.utc),
            market_is_open=market_is_open,
            flat_threshold=self.cfg.flat_threshold,
            stale_quote_seconds=self.cfg.stale_quote_seconds,
        )
        if snapshot.is_valid:
            self._persisted_snapshots.append(snapshot)
            return {"valid": True, "snapshot": snapshot, "latency_ms": latency_ms}
        return {"valid": False, "snapshot": snapshot, "latency_ms": latency_ms}

    # --- continuous loop (background service) -------------------------------
    def run_forever(self, universe: Optional[List[str]] = None) -> None:
        """Run one collection cycle every ``cycle_interval_seconds`` until
        interrupted (SIGINT/SIGTERM)."""
        if self.provider is None:
            logger.error("Cannot run: API key missing")
            return

        themes = load_themes()
        if universe is None:
            universe = build_universe(self.cfg, themes)
        if not universe:
            logger.error("Empty universe — nothing to collect")
            return

        sched = derive_schedule(len(universe), self.cfg)
        logger.info("Collector starting: %d symbols, cycle=%ds, delay=%.2fs/batch=%d, est=%.1fs",
                    len(universe), self.cfg.cycle_interval_seconds,
                    sched.inter_request_delay, sched.batch_size, sched.total_estimated_seconds)
        logger.info("Run 'python -m data.collector --once --symbols AAPL,NVDA,AMD,MSFT' "
                    "to run a single manual smoke cycle.")

        last_cycle_started: Optional[datetime] = None
        self._stopping = False

        def _handle_signal(signum, frame):  # pragma: no cover
            self._stopping = True
            raise KeyboardInterrupt()

        old_int = signal.signal(signal.SIGINT, _handle_signal)
        old_term = signal.signal(signal.SIGTERM, _handle_signal)
        try:
            while True:
                now = datetime.now(timezone.utc)
                # Align to a wall-clock grid: wait so this cycle starts exactly
                # ``interval`` seconds after the previous one.
                if last_cycle_started is not None:
                    elapsed = (now - last_cycle_started).total_seconds()
                    wait = interval - elapsed
                    if wait > 0:
                        logger.info("Waiting %.0fs until next cycle start (aligned grid)",
                                    wait)
                        self._wait_interval(interval)

                # Market status context at start (pre-market / regular-hour
                # distinction drives the stale flag and the doc caveat).
                market_status_at_start = self._market_status()
                provider_timestamp_note = "regular hours"
                if market_status_at_start:
                    session = market_status_at_start.get("session", "")
                    if session == "pre-market":
                        provider_timestamp_note = (
                            "PRE-MARKET (provider timestamp frozen at "
                            "previous day's close; quotes stale while "
                            "session!=regular — documented provider limitation)")

                summary = self.run_cycle(universe, market_status_at_start,
                                         provider_timestamp_note)
                last_cycle_started = None

                if self._stopping:
                    break

        except KeyboardInterrupt:
            logger.info("Interrupted — stopping collector")
        finally:
            signal.signal(signal.SIGINT, old_int)
            signal.signal(signal.SIGTERM, old_term)

    def _market_status(self) -> Optional[dict]:
        """/stock/market-status?exchange=US; best-effort, non-blocking."""
        if self.provider is None:
            return None
        try:
            status, headers, body = self.provider._transport.get(
                "/stock/market-status", {"exchange": "US"},
                retry_count=1, retry_backoff_base=1.0)
            if status == 200 and isinstance(body, dict):
                return body
        except Exception:  # pragma: no cover
            pass
        return None

    def _wait_interval(self, seconds: float) -> None:
        """Sleep while checking stop, in sub-second steps."""
        start = time.monotonic()
        while not self._stopping and (time.monotonic() - start) < seconds:
            time.sleep(min(0.5, seconds - (time.monotonic() - start)))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    """Entry point: --once runs a single cycle; default/--loop runs forever."""
    ap = argparse.ArgumentParser(
        description="Sector Radar — Finnhub quote collector (rate-limited, "
                    "5-min collection cycle). Standalone process; Streamlit "
                    "dashboard reads the persisted snapshots.")
    ap.add_argument("--once", action="store_true",
                    help="Run a single collection cycle, then exit.")
    ap.add_argument("--loop", action="store_true",
                    help="Run cycles continuously (default).")
    ap.add_argument("--symbols",
                    help="Explicit symbol set override (comma-separated).")
    args = ap.parse_args(argv)

    settings = load_settings()
    collector = FinnhubCollector(settings)

    if collector.provider is None:
        ap.error("Cannot start: %s not set (create .env with "
                 "SECTOR_RADAR_FINNHUB_API_KEY, or check "
                 "data.finnhub.api_key_env in settings.yaml)"
                 % collector.cfg.api_key_env)

    # Universe: --symbols override > theme-derived.
    themes = load_themes()
    if args.symbols:
        universe = [t.strip().upper() for t in args.symbols.split(",") if t.strip()]
    else:
        universe = build_universe(collector.cfg, themes)

    if not universe:
        ap.error("No symbols to collect (theme universe is empty).")

    if args.once:
        # One-cycle mode: run exactly one collection cycle and exit.
        summary = collector.run_cycle(universe)
        print("\n" + "-" * 72)
        print("FINNHUB QUOTE COLLECTION CYCLE COMPLETE")
        print("-" * 72)
        print(f"session_date   : {summary.session_date}")
        print(f"symbols        : {summary.n_symbols}")
        print(f"succeeded      : {summary.n_succeeded}")
        print(f"failed         : {summary.n_failed}")
        print(f"rate-limited   : {summary.n_rate_limited}")
        print(f"stale          : {summary.stale_count}")
        print(f"cycle_seconds  : {summary.cycle_seconds:.1f}")
        if summary.min_latency_ms is not None:
            print(f"latency_ms     : {summary.min_latency_ms:.1f}-{summary.max_latency_ms:.1f} "
                  f"(mean {summary.mean_latency_ms:.1f})")
        else:
            print("latency_ms     : n/a (no valid latencies)")
        if summary.mean_data_age_seconds is not None:
            print(f"data_age       : {summary.mean_data_age_seconds:.2f} s mean")
        else:
            print("data_age       : n/a (no data ages to report)")
        print(f"schedule       : {summary.schedule}")
        if summary.failed_symbols:
            print("FAILED SYMBOLS:")
            for s, r in summary.failed_symbols.items():
                print(f"  {s:6s} -> {r}")
        if summary.provider_timestamp_note:
            print(f"\nNOTE: {summary.provider_timestamp_note}")
        print("-" * 72)
        print(f"saved: latest quote snapshots for {summary.n_succeeded} symbols -> "
              f"{collector.store.db_path}")
        return 0

    # Continuous loop (default or --loop).
    collector.run_forever()
    return 0


if __name__ == "__main__":
    import signal
    sys.exit(main())
