"""Plotly chart builders (spec section 20).

Chart 1 — theme average return from open
Chart 2 — breadth (Up %)
Chart 3 — average vs median return (concentration view)
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import pandas as pd
import plotly.graph_objects as go

POS = "#16a34a"
NEG = "#dc2626"
MUTED = "#6b7280"
BREADTH = "#2563eb"
MEDIAN = "#d97706"


def _base_layout(fig: go.Figure, title: str, ytitle: str, height: int = 300):
    fig.update_layout(
        height=height,
        margin=dict(l=10, r=10, t=34, b=10),
        title=dict(text=title, font=dict(size=14)),
        yaxis=dict(title=ytitle, tickformat=".1f", gridcolor="#f0f0f0"),
        xaxis=dict(hoverformat="%I:%M %p"),
        template="plotly_white",
        showlegend=False,
    )
    return fig


def _add_window_line(fig: go.Figure, window_end: Optional[datetime]):
    if window_end is None:
        return
    fig.add_vline(
        x=pd.Timestamp(window_end),
        line=dict(color="#9ca3af", width=1, dash="dot"),
        annotation_text="scanner window end",
        annotation_position="top right",
        annotation_font_size=10,
    )


def theme_return_chart(history: Optional[pd.DataFrame], theme: str,
                       window_end: Optional[datetime] = None) -> go.Figure:
    """Chart 1: theme average return (%) from market open."""
    fig = go.Figure()
    if history is None or history.empty:
        fig.update_layout(title=f"{theme} — no session data yet")
        return _base_layout(fig, f"{theme} — average return from open", "Theme avg return (%)")
    x = pd.to_datetime(history.index)
    y = history["avg_return"].astype(float)
    color = POS if float(y.iloc[-1]) >= 0 else NEG
    fig.add_trace(go.Scatter(
        x=x, y=y, mode="lines",
        line=dict(color=color, width=2),
        fill="tozeroy", fillcolor="rgba(120,120,120,0.06)",
        hovertemplate="%{x|%l}<br>avg return: %{y:+.2f}%<extra></extra>",
    ))
    fig.add_hline(y=0, line=dict(color="#d1d5db", width=1))
    _add_window_line(fig, window_end)
    return _base_layout(fig, f"{theme} — average return from open", "Theme avg return (%)")


def breadth_chart(history: Optional[pd.DataFrame], theme: str,
                  window_end: Optional[datetime] = None) -> go.Figure:
    """Chart 2: breadth — Up % (and Down % for context) over the session."""
    fig = go.Figure()
    if history is None or history.empty:
        fig.update_layout(title=f"{theme} — no session data yet")
        return _base_layout(fig, f"{theme} — breadth", "Up / Down %")
    x = pd.to_datetime(history.index)
    fig.add_trace(go.Scatter(
        x=x, y=history["up_percent"].astype(float), mode="lines",
        line=dict(color=POS, width=2), name="Up %",
        hovertemplate="%{x|%l}<br>up: %{y:.0f}%<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=x, y=history["down_percent"].astype(float), mode="lines",
        line=dict(color=NEG, width=2), name="Down %",
        hovertemplate="%{x|%l}<br>down: %{y:.0f}%<extra></extra>",
    ))
    fig.add_hline(y=50, line=dict(color="#d1d5db", width=1, dash="dash"))
    _add_window_line(fig, window_end)
    fig.update_layout(showlegend=True)
    return _base_layout(fig, f"{theme} — breadth (Up % / Down %)", "Percent of valid stocks")


def avg_vs_median_chart(history: Optional[pd.DataFrame], theme: str,
                        window_end: Optional[datetime] = None) -> go.Figure:
    """Chart 3: average vs median return — divergence signals concentration."""
    fig = go.Figure()
    if history is None or history.empty:
        fig.update_layout(title=f"{theme} — no session data yet")
        return _base_layout(fig, f"{theme} — average vs median", "Return (%)")
    x = pd.to_datetime(history.index)
    fig.add_trace(go.Scatter(
        x=x, y=history["avg_return"].astype(float), mode="lines",
        line=dict(color=POS, width=2), name="Average",
        hovertemplate="%{x|%l}<br>avg: %{y:+.2f}%<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=x, y=history["median_return"].astype(float), mode="lines",
        line=dict(color=MEDIAN, width=2), name="Median",
        hovertemplate="%{x|%l}<br>median: %{y:+.2f}%<extra></extra>",
    ))
    fig.add_hline(y=0, line=dict(color="#d1d5db", width=1))
    _add_window_line(fig, window_end)
    fig.update_layout(showlegend=True)
    return _base_layout(fig, f"{theme} — average vs median return", "Return (%)")
