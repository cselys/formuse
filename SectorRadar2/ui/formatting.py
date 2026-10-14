"""Shared formatting/styling helpers (used by dashboard + sector detail).

Kept in a separate module to avoid circular imports between the UI modules.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import numpy as np

from models.schemas import STATE_COLORS, STATE_LABELS

POS = "#16a34a"
NEG = "#dc2626"
MUTED = "#6b7280"


def missing(v) -> bool:
    return v is None or (isinstance(v, float) and np.isnan(v))


def fmt_signed(v, nd: int = 2, suffix: str = "%") -> str:
    if missing(v):
        return "—"
    return f"{v:+.{nd}f}{suffix}"


def fmt_plain(v, suffix: str = "%") -> str:
    if missing(v):
        return "—"
    return f"{v:.0f}{suffix}"


def fmt_time(ts: Optional[datetime], na: str = "—") -> str:
    if ts is None:
        return na
    s = ts.strftime("%I:%M:%S %p").lstrip("0")
    return f"{s} ET"


def state_label(state: str) -> str:
    return STATE_LABELS.get(state, state)


def state_color(label: str) -> str:
    for k, v in STATE_LABELS.items():
        if v == label:
            return f"color:{STATE_COLORS[k]};font-weight:700"
    return ""


def signed_color(v) -> str:
    if missing(v):
        return ""
    if v > 0.05:
        return f"color:{POS};font-weight:600"
    if v < -0.05:
        return f"color:{NEG};font-weight:600"
    return f"color:{MUTED}"


def plain_color(v) -> str:
    if missing(v):
        return ""
    return "color:#374151"
