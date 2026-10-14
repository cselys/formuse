"""Theme rankings (spec section 15) and the optional composite score (16).

The rankings are deliberately SEPARATE — the user should see what each one
means. Do NOT collapse them into a single score (the composite is optional
and never the primary ranking in V1).
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional

import numpy as np

from models.schemas import ThemeMetrics


def _rank(metrics: List[ThemeMetrics],
          key: str,
          n: Optional[int],
          reverse: bool = True,
          where: Optional[Callable[[ThemeMetrics], bool]] = None) -> List[ThemeMetrics]:
    """Generic ranking by a ThemeMetrics attribute (NaN-safe)."""
    rows = [x for x in metrics if x.valid_stocks > 0]
    if where:
        rows = [x for x in rows if where(x)]

    def sort_value(x: ThemeMetrics):
        v = getattr(x, key)
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return -np.inf if not reverse else np.inf
        return v

    rows.sort(key=sort_value, reverse=reverse)
    return rows[:n] if n else rows


def top_up(metrics: List[ThemeMetrics], n: int = 6) -> List[ThemeMetrics]:
    """Rank by average_return descending (spec: 'Top Up')."""
    return _rank(metrics, "average_return", n, reverse=True)


def top_down(metrics: List[ThemeMetrics], n: int = 6) -> List[ThemeMetrics]:
    """Rank by average_return ascending (spec: 'Top Down')."""
    return _rank(metrics, "average_return", n, reverse=False)


def broadest_up(metrics: List[ThemeMetrics], n: int = 6) -> List[ThemeMetrics]:
    return _rank(metrics, "up_percent", n, reverse=True)


def broadest_down(metrics: List[ThemeMetrics], n: int = 6) -> List[ThemeMetrics]:
    return _rank(metrics, "down_percent", n, reverse=True)


def biggest_reversals(metrics: List[ThemeMetrics], n: int = 6,
                      threshold: float = 0.0) -> List[ThemeMetrics]:
    """reversal_from_high ascending (most giveback first)."""
    return _rank(metrics, "reversal_from_high", n, reverse=False,
                 where=lambda m: np.isfinite(m.reversal_from_high)
                 and m.reversal_from_high < -abs(threshold))


def biggest_recoveries(metrics: List[ThemeMetrics], n: int = 6,
                       threshold: float = 0.0) -> List[ThemeMetrics]:
    """recovery_from_low descending."""
    return _rank(metrics, "recovery_from_low", n, reverse=True,
                 where=lambda m: np.isfinite(m.recovery_from_low)
                 and m.recovery_from_low > abs(threshold))


def build_rankings(metrics: List[ThemeMetrics], settings: dict,
                   min_theme_size: int = 0, top_n: int = 6) -> Dict[str, List[ThemeMetrics]]:
    """All rankings in one dict, filtered by minimum valid-stocks count."""
    rev_thr = float(settings.get("state", {}).get("reversal_threshold", 1.0)) \
        if isinstance(settings, dict) else 1.0
    rec_thr = float(settings.get("state", {}).get("recovery_threshold", 1.0)) \
        if isinstance(settings, dict) else 1.0
    sized = [m for m in metrics if m.valid_stocks >= min_theme_size]
    return {
        "top_up": top_up(sized, top_n),
        "top_down": top_down(sized, top_n),
        "broadest_up": broadest_up(sized, top_n),
        "broadest_down": broadest_down(sized, top_n),
        "reversals": biggest_reversals(sized, top_n, threshold=rev_thr),
        "recoveries": biggest_recoveries(sized, top_n, threshold=rec_thr),
    }


def composite_scores(metrics: List[ThemeMetrics], weights: Dict[str, float]) -> Dict[str, float]:
    """Optional composite score (spec section 16) — NOT a primary ranking.

    Each component is min-max normalized across themes to 0-100, volume is
    log10-transformed first so high-volume mega themes don't dominate.
    """
    rows = [x for x in metrics if x.valid_stocks > 0]
    if not rows:
        return {}

    def norm(values: List[float]) -> np.ndarray:
        arr = np.array(values, dtype=float)
        lo, hi = float(np.nanmin(arr)), float(np.nanmax(arr))
        if not np.isfinite(lo) or not np.isfinite(hi) or hi == lo:
            return np.full(len(arr), 50.0)
        return (arr - lo) / (hi - lo) * 100.0

    breadth = norm([x.up_percent for x in rows])
    avg = norm([x.average_return for x in rows])
    med = norm([x.median_return for x in rows])
    volume = norm([float(np.log10(max(x.total_volume, 0) + 1)) for x in rows])

    w = weights or {}
    wb = float(w.get("breadth", 0.40))
    wa = float(w.get("avg_return", 0.30))
    wm = float(w.get("median_return", 0.20))
    wv = float(w.get("volume", 0.10))
    total = (wb + wa + wm + wv) or 1.0

    return {x.theme: round(float((wb * breadth[i] + wa * avg[i]
                                  + wm * med[i] + wv * volume[i]) / total), 1)
            for i, x in enumerate(rows)}
