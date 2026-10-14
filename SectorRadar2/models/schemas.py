"""Data schemas for Sector Radar (spec sections 8, 9, 12, 25, 28).

Plain dataclasses — no ORM, no I/O. Calculation logic lives in ``engine/``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Theme states (spec section 12)
# ---------------------------------------------------------------------------
TRENDING_UP = "TRENDING_UP"
TRENDING_DOWN = "TRENDING_DOWN"
REVERSING_DOWN = "REVERSING_DOWN"
RECOVERING_UP = "RECOVERING_UP"
MIXED = "MIXED"

ALL_STATES = [TRENDING_UP, TRENDING_DOWN, REVERSING_DOWN, RECOVERING_UP, MIXED]

STATE_LABELS: Dict[str, str] = {
    TRENDING_UP: "TRENDING UP",
    TRENDING_DOWN: "TRENDING DOWN",
    REVERSING_DOWN: "REVERSING ↓",
    RECOVERING_UP: "RECOVERING ↑",
    MIXED: "MIXED",
}

# green = positive, red = negative, orange = reversal, blue = recovery,
# gray = mixed (spec section 31)
STATE_COLORS: Dict[str, str] = {
    TRENDING_UP: "#16a34a",
    TRENDING_DOWN: "#dc2626",
    REVERSING_DOWN: "#d97706",
    RECOVERING_UP: "#2563eb",
    MIXED: "#6b7280",
}

# Per-stock direction
UP = "UP"
DOWN = "DOWN"
FLAT = "FLAT"


# ---------------------------------------------------------------------------
# Per-stock metrics (spec section 8)
# ---------------------------------------------------------------------------
@dataclass
class StockSnapshot:
    symbol: str
    timestamp: str                        # ISO-8601 (ET) — "as of" this value
    previous_close: Optional[float]
    today_open: Optional[float]            # official regular-session open
    current_price: Optional[float]
    intraday_high: Optional[float]
    intraday_low: Optional[float]
    change_vs_previous_close: Optional[float]   # percent
    change_vs_open: Optional[float]            # percent
    distance_from_intraday_high: Optional[float]  # percent (<= 0)
    distance_from_intraday_low: Optional[float]   # percent (>= 0)
    volume: int
    is_valid: bool = True
    issue: str = ""                       # e.g. "stale quote", "no intraday data"
    direction: str = FLAT                 # UP / DOWN / FLAT (vs previous close)
    # ---- additive freshness fields (Finnhub migration, Phase 1) ----
    provider_timestamp: Optional[float] = None  # unix epoch seconds, UTC, from /quote 't'
    fetched_at: Optional[str] = None              # ISO-8601 UTC when request finished
    data_age_seconds: Optional[float] = None      # fetched_at_epoch - provider_ts
    _latency_ms: Optional[float] = None           # internal: network request duration (ms)


# ---------------------------------------------------------------------------
# ETF / basket comparison (spec section 17)
# ---------------------------------------------------------------------------
@dataclass
class ETFComparison:
    etf: str
    etf_return: Optional[float]           # ETF % vs its previous close
    basket_return: float                  # theme equal-weight average return %
    divergence: Optional[float]           # etf_return - basket_return, in pp
    note: str = ""


# ---------------------------------------------------------------------------
# Theme metrics (spec sections 9-15)
# ---------------------------------------------------------------------------
@dataclass
class ThemeMetrics:
    theme: str
    timestamp: str                        # ISO-8601 (ET) of the data snapshot
    total_stocks: int
    valid_stocks: int
    missing_stocks: int
    up_stocks: int
    down_stocks: int
    flat_stocks: int
    up_percent: float
    down_percent: float
    flat_percent: float
    strong_up_percent: float
    strong_down_percent: float
    average_return: float                 # % vs previous close
    median_return: float
    average_change_from_open: float       # % vs today's open
    median_change_from_open: float
    total_volume: int
    intraday_high: float                  # max theme avg return this session
    intraday_low: float                   # min theme avg return this session
    reversal_from_high: float             # current - intraday_high (pp, <= 0)
    recovery_from_low: float              # current - intraday_low (pp, >= 0)
    breadth_now: float
    breadth_5m_ago: Optional[float]
    breadth_15m_ago: Optional[float]
    breadth_change_5m: Optional[float]    # pp
    breadth_change_15m: Optional[float]   # pp
    state: str
    small_sample: bool
    etf: List[ETFComparison] = field(default_factory=list)
    history: Optional["object"] = field(default=None, repr=False)  # pandas DataFrame

    # ---- eligibility metadata (freshness layer) ----
    eligible_stocks: int = 0
    aging_stocks: int = 0
    stale_stocks: int = 0
    no_data_stocks: int = 0
    oldest_quote_age: Optional[float] = None
    newest_quote_age: Optional[float] = None
    observation_status: str = "PASS"

    # ------------------------------------------------------------------ json
    def to_json(self) -> Dict:
        """Structured summary for the V2 AI layer (spec section 28).

        The AI layer consumes this; it must never recompute these numbers.
        """
        return {
            "theme": self.theme,
            "average_return": round(self.average_return, 3),
            "median_return": round(self.median_return, 3),
            "up_percent": round(self.up_percent, 1),
            "strong_up_percent": round(self.strong_up_percent, 1),
            "change_from_open": round(self.average_change_from_open, 3),
            "intraday_high": round(self.intraday_high, 3),
            "intraday_low": round(self.intraday_low, 3),
            "reversal_from_high": round(self.reversal_from_high, 3),
            "recovery_from_low": round(self.recovery_from_low, 3),
            "breadth_now": round(self.breadth_now, 1) if self.breadth_now is not None else None,
            "breadth_momentum_15m": (round(self.breadth_change_15m, 1)
                                     if self.breadth_change_15m is not None else None),
            "state": self.state,
            "valid_stocks": self.valid_stocks,
            "total_stocks": self.total_stocks,
            "eligible_stocks": self.eligible_stocks,
            "aging_stocks": self.aging_stocks,
            "stale_stocks": self.stale_stocks,
            "no_data_stocks": self.no_data_stocks,
            "oldest_quote_age": round(self.oldest_quote_age, 1) if self.oldest_quote_age is not None else None,
            "newest_quote_age": round(self.newest_quote_age, 1) if self.newest_quote_age is not None else None,
        }


# ---------------------------------------------------------------------------
# Alerts (spec section 27)
# ---------------------------------------------------------------------------
@dataclass
class Alert:
    kind: str
    theme: str
    message: str
    severity: str = "info"   # "info" | "warn"
