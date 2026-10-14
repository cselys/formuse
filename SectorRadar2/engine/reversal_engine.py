"""Intraday high/low, reversal, recovery, and theme state detection
(spec sections 12-14).

IMPORTANT (spec section 13): the theme intraday high/low are computed from
the SESSION HISTORY — the theme's average return at every bar — not from the
current snapshot. This is what makes reversal/recovery detection meaningful.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Set

import numpy as np
import pandas as pd

from data.freshness import FreshnessPolicy, get_history_eligible_symbols
from models.schemas import (MIXED, RECOVERING_UP, REVERSING_DOWN,
                            TRENDING_DOWN, TRENDING_UP)
from utils.config import get_setting
from utils.logging import get_logger

logger = get_logger(__name__)

_HIST_COLS = ["avg_return", "median_return", "up_percent", "down_percent", "valid_count"]


def theme_return_series(bars_map: Dict[str, pd.DataFrame],
                        prev_close_map: Dict[str, float],
                        symbols: List[str],
                        flat_threshold: float = 0.10,
                        eligible_symbols: Optional[Set[str]] = None) -> pd.DataFrame:
    """Per-bar theme-level return series (spec section 13).

    Parameters
    ----------
    bars_map       : {symbol: intraday OHLCV frame}
    prev_close_map : {symbol: previous close}
    symbols        : symbols to include (valid ones only)
    eligible_symbols : optional set of symbols eligible for history (FRESH only)

    Returns
    -------
    DataFrame indexed by bar timestamp (ET) with columns:
        avg_return, median_return, up_percent, down_percent, valid_count
    """
    rets: Dict[str, pd.Series] = {}
    for sym in symbols:
        if eligible_symbols is not None and sym not in eligible_symbols:
            continue
        bars = bars_map.get(sym)
        pc = prev_close_map.get(sym)
        if bars is None or bars.empty or pc is None or not np.isfinite(pc) or pc == 0:
            continue
        b = bars.dropna(subset=["close"]).sort_index()
        if b.empty:
            continue
        rets[sym] = b["close"].astype(float) / float(pc) * 100.0 - 100.0
    if not rets:
        return pd.DataFrame(columns=_HIST_COLS)

    r = pd.DataFrame(rets).sort_index()
    valid_count = r.notna().sum(axis=1)
    out = pd.DataFrame(index=r.index)
    out["avg_return"] = r.mean(axis=1)
    out["median_return"] = r.median(axis=1)
    out["up_percent"] = np.where(valid_count > 0,
                                 (r > flat_threshold).sum(axis=1) / valid_count * 100.0,
                                 np.nan)
    out["down_percent"] = np.where(valid_count > 0,
                                   (r < -flat_threshold).sum(axis=1) / valid_count * 100.0,
                                   np.nan)
    out["valid_count"] = valid_count
    out = out[out["avg_return"].notna()]
    return out


def _up_at_offset(history: pd.DataFrame, minutes: int) -> Optional[float]:
    """Last observation at/before target, at most 60 seconds earlier.

    Never clamp an unavailable horizon or select a future observation. An
    explicit missing observation blocks fallback to older populated rows.
    """
    idx = history.index
    if len(idx) < 2:
        return None
    last = idx[-1]
    target = last - pd.Timedelta(minutes=minutes)
    pos = int(idx.searchsorted(target, side="right")) - 1
    if pos < 0:
        return None
    picked = idx[pos]
    if (target - picked).total_seconds() >= 60:
        return None
    v = history["up_percent"].iloc[pos]
    return float(v) if pd.notna(v) else None


def analyze_history(history: Optional[pd.DataFrame], settings: dict) -> Dict:
    """Intraday high/low, reversal, recovery, and breadth momentum (spec 13-14).

    All return values are in percentage points:
        reversal_from_high <= 0   (giveback from the session peak)
        recovery_from_low  >= 0   (recovery off the session trough)
    """
    min_bars = int(get_setting(settings, "state.min_history_bars", 3))
    result = {
        "intraday_high": np.nan, "intraday_low": np.nan,
        "reversal_from_high": np.nan, "recovery_from_low": np.nan,
        "peak_ts": None, "trough_ts": None,
        "breadth_now": np.nan,
        "breadth_5m_ago": np.nan, "breadth_15m_ago": np.nan,
        "breadth_change_5m": np.nan, "breadth_change_15m": np.nan,
        "has_history": False,
    }
    if history is None or history.empty:
        return result

    history = history.sort_index()

    idx = history.index
    high = float(history["avg_return"].max())
    low = float(history["avg_return"].min())
    current = float(history["avg_return"].iloc[-1])
    breadth_now = history["up_percent"].iloc[-1]

    observed = history[history["avg_return"].notna()]
    observations = (observed["observation_id"].nunique()
                    if "observation_id" in observed else len(observed))
    result.update({
        "intraday_high": high,
        "intraday_low": low,
        "reversal_from_high": current - high,
        "recovery_from_low": current - low,
        "peak_ts": observed["avg_return"].idxmax() if len(observed) else None,
        "trough_ts": observed["avg_return"].idxmin() if len(observed) else None,
        "breadth_now": float(breadth_now) if pd.notna(breadth_now) else np.nan,
        "has_history": bool(observations >= min_bars and np.isfinite(current)),
    })

    if observations >= min_bars:
        b5 = _up_at_offset(history, 5)
        b15 = _up_at_offset(history, 15)
        if b5 is not None:
            result["breadth_5m_ago"] = b5
            result["breadth_change_5m"] = result["breadth_now"] - b5
        if b15 is not None:
            result["breadth_15m_ago"] = b15
            result["breadth_change_15m"] = result["breadth_now"] - b15
    return result


def classify_state(avg_return: float,
                   avg_change_from_open: Optional[float],
                   up_percent: float,
                   down_percent: float,
                   reversal_from_high: float,
                   recovery_from_low: float,
                   settings: dict,
                   has_history: bool) -> str:
    """Determine the theme intraday state (spec section 12).

    Priority: reversal/recovery first (they are the "story"), then trend,
    then MIXED. Thresholds are configurable in settings.yaml.
    """
    rev_thr = get_setting(settings, "state.reversal_threshold", 1.0)
    rec_thr = get_setting(settings, "state.recovery_threshold", 1.0)
    breadth_thr = get_setting(settings, "state.breadth_threshold", 60.0)
    vs_open = avg_change_from_open or 0.0

    if has_history and np.isfinite(reversal_from_high):
        if reversal_from_high <= -rev_thr and up_percent < 50.0:
            # was substantially higher earlier, has given back and breadth flipped
            return REVERSING_DOWN
    if has_history and np.isfinite(recovery_from_low):
        if recovery_from_low >= rec_thr and avg_return < 0:
            # was substantially lower earlier, still negative but off the lows
            return RECOVERING_UP

    if avg_return > 0 and vs_open > 0 and up_percent > breadth_thr:
        return TRENDING_UP
    if avg_return < 0 and vs_open < 0 and down_percent > breadth_thr:
        return TRENDING_DOWN
    return MIXED
