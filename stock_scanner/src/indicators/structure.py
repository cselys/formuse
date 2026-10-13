"""
Market structure and swing detection for stock_scanner.
Detects Higher Highs, Higher Lows, Lower Highs, Lower Lows, consolidations, breakouts, and base formations.
"""

import pandas as pd
import numpy as np


def detect_swing_points(df: pd.DataFrame, lookback: int = 5) -> pd.DataFrame:
    """
    Detect local swing highs and swing lows using a rolling window lookback.
    Returns DataFrame with boolean columns 'is_swing_high', 'is_swing_low', 'swing_high', 'swing_low'.
    """
    highs = df['High']
    lows = df['Low']

    # Rolling max/min for window of 2*lookback + 1 centered at index
    # To avoid future data, we check if high is the max in the past lookback bars
    is_swing_high = pd.Series(False, index=df.index)
    is_swing_low = pd.Series(False, index=df.index)

    # Vectorized / rolling check for past lookback bars
    for i in range(lookback, len(df) - lookback):
        window_highs = highs.iloc[i - lookback : i + lookback + 1]
        window_lows = lows.iloc[i - lookback : i + lookback + 1]

        if highs.iloc[i] == window_highs.max():
            is_swing_high.iloc[i] = True
        if lows.iloc[i] == window_lows.min():
            is_swing_low.iloc[i] = True

    df = df.copy()
    df['is_swing_high'] = is_swing_high
    df['is_swing_low'] = is_swing_low
    df['swing_high'] = np.where(is_swing_high, highs, np.nan)
    df['swing_low'] = np.where(is_swing_low, lows, np.nan)

    return df


def analyze_market_structure(df: pd.DataFrame, lookback: int = 5, breakout_lookback: int = 20) -> dict:
    """
    Analyze market structure over recent history.
    Returns a dict with structure summary:
    - structure_type: 'bullish', 'bearish', 'consolidating', 'neutral'
    - higher_high: bool
    - higher_low: bool
    - lower_high: bool
    - lower_low: bool
    - recent_breakout: bool
    - recent_breakdown: bool
    - base_formation: bool
    """
    if len(df) < breakout_lookback + lookback:
        return {
            'structure_type': 'neutral',
            'higher_high': False,
            'higher_low': False,
            'lower_high': False,
            'lower_low': False,
            'recent_breakout': False,
            'recent_breakdown': False,
            'base_formation': False
        }

    df_swings = detect_swing_points(df, lookback=lookback)
    swing_highs = df_swings[df_swings['is_swing_high']]['High']
    swing_lows = df_swings[df_swings['is_swing_low']]['Low']

    hh = False
    hl = False
    lh = False
    ll = False

    if len(swing_highs) >= 2:
        hh = swing_highs.iloc[-1] > swing_highs.iloc[-2]
        lh = swing_highs.iloc[-1] < swing_highs.iloc[-2]

    if len(swing_lows) >= 2:
        hl = swing_lows.iloc[-1] > swing_lows.iloc[-2]
        ll = swing_lows.iloc[-1] < swing_lows.iloc[-2]

    current_close = df['Close'].iloc[-1]
    recent_high = df['High'].iloc[-breakout_lookback:-1].max()
    recent_low = df['Low'].iloc[-breakout_lookback:-1].min()

    recent_breakout = current_close > recent_high
    recent_breakdown = current_close < recent_low

    # Consolidation / base formation: price range over last 20 bars is tight (e.g. within 5%)
    price_range_pct = (df['High'].iloc[-breakout_lookback:].max() - df['Low'].iloc[-breakout_lookback:].min()) / df['Close'].iloc[-1] * 100.0
    base_formation = price_range_pct < 8.0 and not recent_breakout and not recent_breakdown

    # Determine structure type
    if hh and hl:
        structure_type = 'bullish'
    elif lh and ll:
        structure_type = 'bearish'
    elif base_formation:
        structure_type = 'consolidating'
    elif hl and not lh:
        structure_type = 'bullish'
    elif lh and not hl:
        structure_type = 'bearish'
    else:
        structure_type = 'neutral'

    return {
        'structure_type': structure_type,
        'higher_high': bool(hh),
        'higher_low': bool(hl),
        'lower_high': bool(lh),
        'lower_low': bool(ll),
        'recent_breakout': bool(recent_breakout),
        'recent_breakdown': bool(recent_breakdown),
        'base_formation': bool(base_formation)
    }
