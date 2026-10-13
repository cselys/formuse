"""
Volatility indicators (ATR, ATR percentage, distance metrics) for stock_scanner.
"""

import pandas as pd
import numpy as np


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Calculate Average True Range (ATR)."""
    high = df['High']
    low = df['Low']
    close = df['Close']

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()

    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    return atr


def calculate_atr_pct(df: pd.DataFrame, atr: pd.Series) -> pd.Series:
    """Calculate ATR as a percentage of Close price."""
    return (atr / df['Close']) * 100.0


def calculate_distance_pct(series: pd.Series, baseline: pd.Series) -> pd.Series:
    """Calculate percentage distance from series to baseline (e.g. Close from EMA20)."""
    return ((series - baseline) / baseline) * 100.0
