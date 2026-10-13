"""
Data models and structures for Paper Validation subsystem.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime


@dataclass
class PaperSignal:
    signal_id: str
    scanner_version: str
    signal_date: str
    symbol: str
    category: str
    signal_type: str  # State name (e.g. REVERSAL, EARLY_UPTREND, etc.)
    signal_tier: str  # ACTIONABLE or WATCHLIST
    signal_price: float
    signal_timestamp: str
    price_source: str = "close"
    trend_score: float = 0.0
    bottom_score: float = 0.0
    reversal_score: float = 0.0
    entry_quality: float = 0.0
    candidate_score: float = 0.0
    market_regime: str = "UNKNOWN"
    relative_strength: Dict[str, Any] = field(default_factory=dict)
    indicators_snapshot: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "scanner_version": self.scanner_version,
            "signal_date": self.signal_date,
            "symbol": self.symbol,
            "category": self.category,
            "signal_type": self.signal_type,
            "signal_tier": self.signal_tier,
            "signal_price": self.signal_price,
            "signal_timestamp": self.signal_timestamp,
            "price_source": self.price_source,
            "trend_score": self.trend_score,
            "bottom_score": self.bottom_score,
            "reversal_score": self.reversal_score,
            "entry_quality": self.entry_quality,
            "candidate_score": self.candidate_score,
            "market_regime": self.market_regime,
            "relative_strength": self.relative_strength,
            "indicators_snapshot": self.indicators_snapshot,
            "created_at": self.created_at
        }


@dataclass
class PaperOutcome:
    signal_id: str
    symbol: str
    signal_date: str
    signal_price: float
    status: str = "OPEN"  # OPEN, PARTIAL, COMPLETE
    forward_returns: Dict[str, Optional[float]] = field(default_factory=lambda: {
        "1d": None,
        "3d": None,
        "5d": None,
        "10d": None,
        "20d": None
    })
    mfe: Dict[str, Optional[float]] = field(default_factory=lambda: {
        "5d": None,
        "10d": None,
        "20d": None
    })
    mae: Dict[str, Optional[float]] = field(default_factory=lambda: {
        "5d": None,
        "10d": None,
        "20d": None
    })
    future_prices: Dict[str, Optional[float]] = field(default_factory=dict)
    state_transitions: List[Dict[str, str]] = field(default_factory=list)
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "symbol": self.symbol,
            "signal_date": self.signal_date,
            "signal_price": self.signal_price,
            "status": self.status,
            "forward_returns": self.forward_returns,
            "mfe": self.mfe,
            "mae": self.mae,
            "future_prices": self.future_prices,
            "state_transitions": self.state_transitions,
            "updated_at": self.updated_at
        }
