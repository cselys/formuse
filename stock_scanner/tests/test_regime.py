"""
Unit tests for regime classification in stock_scanner.
"""

import pytest
from stock_scanner.src.analysis.regime import classify_state


def test_classify_state_avoid():
    daily_ind = {'close': 0, 'volume_sma': 100, 'atr_pct': 2.0}
    state = classify_state(50, 50, 50, daily_ind, {}, {}, {}, {})
    assert state == 'AVOID'


def test_classify_state_strong_uptrend():
    daily_ind = {'close': 150, 'volume_sma': 1000000, 'atr_pct': 2.0, 'rsi': 65, 'ema20': 145, 'ema50': 135, 'ema200': 110, 'ema20_slope': 1.0, 'distance_ema20': 3.4}
    weekly_ind = {'close': 150, 'ema20': 140, 'ema40': 130, 'ema20_slope': 1.0}
    struct = {'structure_type': 'bullish'}
    rs = {'rs_20d': 5.0}

    state = classify_state(90, 10, 10, daily_ind, weekly_ind, struct, rs, {'scoring': {'weights': {}}})
    assert state == 'STRONG_UPTREND'
