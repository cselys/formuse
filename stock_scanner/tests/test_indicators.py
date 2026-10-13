"""
Unit tests for technical indicators in stock_scanner.
Uses synthetic deterministic test data.
"""

import pytest
import pandas as pd
import numpy as np

from stock_scanner.src.indicators.trend import calculate_ema, calculate_slope
from stock_scanner.src.indicators.momentum import calculate_rsi, calculate_macd, calculate_roc
from stock_scanner.src.indicators.volatility import calculate_atr, calculate_atr_pct, calculate_distance_pct
from stock_scanner.src.indicators.volume import calculate_volume_sma, calculate_volume_ratio
from stock_scanner.src.indicators.structure import detect_swing_points, analyze_market_structure


@pytest.fixture
def synthetic_price_df():
    """Create synthetic uptrend price series for testing."""
    dates = pd.date_range(start="2025-01-01", periods=100, freq="B")
    prices = np.linspace(100, 150, 100) + np.sin(np.linspace(0, 20, 100)) * 2
    highs = prices + 1.5
    lows = prices - 1.5
    opens = prices - 0.5
    volumes = np.random.randint(1000000, 5000000, size=100).astype(float)

    df = pd.DataFrame({
        'Open': opens,
        'High': highs,
        'Low': lows,
        'Close': prices,
        'Volume': volumes
    }, index=dates)
    return df


def test_calculate_ema(synthetic_price_df):
    ema = calculate_ema(synthetic_price_df['Close'], period=20)
    assert len(ema) == len(synthetic_price_df)
    assert not ema.isna().all()


def test_calculate_rsi(synthetic_price_df):
    rsi = calculate_rsi(synthetic_price_df['Close'], period=14)
    assert len(rsi) == len(synthetic_price_df)
    assert rsi.iloc[-1] >= 0 and rsi.iloc[-1] <= 100


def test_calculate_macd(synthetic_price_df):
    macd, signal, hist = calculate_macd(synthetic_price_df['Close'])
    assert len(macd) == len(synthetic_price_df)
    assert len(signal) == len(synthetic_price_df)
    assert len(hist) == len(synthetic_price_df)


def test_calculate_atr(synthetic_price_df):
    atr = calculate_atr(synthetic_price_df, period=14)
    assert len(atr) == len(synthetic_price_df)
    assert atr.iloc[-1] > 0


def test_market_structure(synthetic_price_df):
    struct = analyze_market_structure(synthetic_price_df, lookback=5, breakout_lookback=20)
    assert isinstance(struct, dict)
    assert 'structure_type' in struct
    assert 'recent_breakout' in struct
