"""
Volume indicators for stock_scanner.
"""

import pandas as pd


def calculate_volume_sma(volume: pd.Series, period: int = 20) -> pd.Series:
    """Calculate Volume Simple Moving Average."""
    return volume.rolling(window=period, min_periods=1).mean()


def calculate_volume_ratio(volume: pd.Series, volume_sma: pd.Series) -> pd.Series:
    """Calculate volume ratio (current volume / volume SMA)."""
    return volume / volume_sma.replace(0, 1.0)
