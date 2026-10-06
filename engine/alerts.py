"""Simple cross-refresh alert detection (spec section 27).

Alerts describe OBSERVED FACTS — they never say "buy" or "sell"
(spec section 29). Compared against:
  * absolute thresholds (breadth jump/collapse, strong reversal/recovery),
  * the previous refresh's Top-3 (entry / exit).
"""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np

from models.schemas import Alert, ThemeMetrics
from utils.config import get_setting


def _finite(v) -> bool:
    return v is not None and np.isfinite(v)


def top3_by_return(metrics: List[ThemeMetrics]) -> Dict[str, float]:
    rows = [x for x in metrics if x.valid_stocks > 0]
    rows.sort(key=lambda x: x.average_return, reverse=True)
    return {x.theme: x.average_return for x in rows[:3]}


def detect_alerts(current: List[ThemeMetrics],
                  previous_top3: Optional[Dict[str, float]] = None,
                  settings: Optional[dict] = None) -> List[Alert]:
    s = settings or {}
    alerts: List[Alert] = []
    thr5 = float(get_setting(s, "alerts.breadth_change_5m", 15.0))
    thr15 = float(get_setting(s, "alerts.breadth_change_15m", 20.0))
    str_rev = float(get_setting(s, "alerts.strong_reversal_pp", 2.0))
    str_rec = float(get_setting(s, "alerts.strong_recovery_pp", 2.0))

    for m in current:
        if m.valid_stocks == 0:
            continue

        # Breadth breakout / collapse (5m and 15m)
        b5, b15 = m.breadth_change_5m, m.breadth_change_15m
        if _finite(b5) and b5 >= thr5:
            alerts.append(Alert(
                "Breadth Breakout", m.theme,
                f"{m.theme} breadth increased from {m.breadth_5m_ago:.0f}% to "
                f"{m.breadth_now:.0f}% in 5 minutes. Average return {m.average_return:+.2f}%. "
                f"Sample: {m.valid_stocks} stocks."))
        elif _finite(b5) and b5 <= -thr5:
            alerts.append(Alert(
                "Breadth Collapse", m.theme,
                f"{m.theme} breadth fell from {m.breadth_5m_ago:.0f}% to "
                f"{m.breadth_now:.0f}% in 5 minutes. Average return {m.average_return:+.2f}%. "
                f"Sample: {m.valid_stocks} stocks."))
        if _finite(b15) and b15 >= thr15:
            alerts.append(Alert(
                "Breadth Breakout", m.theme,
                f"{m.theme} breadth increased from {m.breadth_15m_ago:.0f}% to "
                f"{m.breadth_now:.0f}% in 15 minutes. Average return {m.average_return:+.2f}%."))
        elif _finite(b15) and b15 <= -thr15:
            alerts.append(Alert(
                "Breadth Collapse", m.theme,
                f"{m.theme} breadth fell from {m.breadth_15m_ago:.0f}% to "
                f"{m.breadth_now:.0f}% in 15 minutes. Average return {m.average_return:+.2f}%."))

        # Strong reversal / recovery
        if _finite(m.reversal_from_high) and m.reversal_from_high <= -str_rev and m.up_percent < 50:
            alerts.append(Alert(
                "Strong Reversal", m.theme,
                f"{m.theme} gave back {abs(m.reversal_from_high):.1f} pp from its intraday "
                f"peak {m.intraday_high:+.2f}% — now {m.average_return:+.2f}%, up {m.up_percent:.0f}%."))
        if _finite(m.recovery_from_low) and m.recovery_from_low >= str_rec:
            alerts.append(Alert(
                "Strong Recovery", m.theme,
                f"{m.theme} recovered {m.recovery_from_low:.1f} pp from its intraday low "
                f"{m.intraday_low:+.2f}% — now {m.average_return:+.2f}%."))

    # Top-3 entry / exit vs the previous refresh
    cur_top3 = top3_by_return(current)
    if previous_top3:
        for theme in cur_top3:
            if theme not in previous_top3:
                alerts.append(Alert(
                    "Top 3 Entry", theme,
                    f"{theme} entered the Top 3 by average return ({cur_top3[theme]:+.2f}%)"))
        for theme in previous_top3:
            if theme not in cur_top3:
                alerts.append(Alert(
                    "Top 3 Exit", theme,
                    f"{theme} fell out of the Top 3 by average return"))
    return alerts
