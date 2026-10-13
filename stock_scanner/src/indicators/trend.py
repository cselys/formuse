"""
Trend indicators (EMAs and slopes) for stock_scanner.
All calculations are causal and use pandas/numpy.
"""

import pandas as pd
import numpy as np


def calculate_ema(series: pd.Series, period: int) -> pd.Series:
    """Calculate Exponential Moving Average (EMA)."""
    return series.ewm(span=period, adjust=False).mean()


def calculate_slope(series: pd.Series, period: int = 5) -> pd.Series:
    """Calculate rolling slope of a series over a period using linear regression / diff."""
    # Normalized slope: (current - past) / past or simple difference.
    # Using simple difference or percentage change over period.
    return (series - series.shift(period)) / series.shift(period) * 100.0
