"""
Unit tests for scoring modules in stock_scanner.
"""

import pytest
from stock_scanner.src.scoring.trend_score import calculate_trend_score
from stock_scanner.src.scoring.bottom_score import calculate_bottom_score
from stock_scanner.src.scoring.reversal_score import calculate_reversal_score
from stock_scanner.src.scoring.entry_quality import calculate_entry_quality
from stock_scanner.src.scoring.candidate_score import calculate_candidate_score


@pytest.fixture
def mock_config():
    return {
        'scoring': {
            'weights': {
                'trend': {
                    'weekly_trend': 25, 'daily_trend': 25, 'momentum': 15,
                    'relative_strength': 15, 'volume': 10, 'structure': 10
                },
                'bottom': {
                    'decline_52w': 15, 'stabilization': 15, 'higher_low': 15,
                    'rsi_improvement': 10, 'macd_improvement': 10, 'ema20_reclaim': 10,
                    'volume_confirmation': 10, 'rs_improvement': 10, 'distance_from_low': 5
                },
                'reversal': {
                    'prior_downtrend': 15, 'higher_low': 15, 'ema20_reclaim': 15,
                    'ema20_slope_positive': 10, 'rsi_improvement': 10, 'macd_bullish_cross': 10,
                    'swing_breakout': 10, 'volume_confirmation': 5, 'rs_improvement': 5
                },
                'setup_quality': {
                    'extension_penalty_threshold': 10.0
                }
            }
        }
    }


def test_trend_score(mock_config):
    weekly_ind = {'close': 150, 'ema20': 140, 'ema40': 130, 'ema20_slope': 1.0, 'ema40_slope': 1.0}
    daily_ind = {'close': 150, 'ema20': 145, 'ema50': 140, 'ema200': 120, 'rsi': 60, 'macd': 2.0, 'macd_signal': 1.0, 'macd_hist': 1.0, 'roc20': 5.0, 'volume_ratio': 1.5}
    struct = {'structure_type': 'bullish', 'higher_high': True, 'higher_low': True, 'recent_breakout': True}
    rs = {'rs_20d': 6.0, 'rs_60d': 12.0}

    score, breakdown = calculate_trend_score(weekly_ind, daily_ind, struct, rs, mock_config)
    assert 0 <= score <= 100
    assert score > 70


def test_bottom_score(mock_config):
    daily_ind = {'close': 100, 'high_52w': 180, 'low_20d': 95, 'rsi': 45, 'macd_hist': 0.5, 'distance_ema20': 1.0, 'volume_ratio': 1.3, 'low_52w': 90}
    struct = {'higher_low': True, 'lower_low': False}
    rs = {'rs_20d': 2.0}

    score, breakdown = calculate_bottom_score(daily_ind, struct, rs, None, mock_config)
    assert 0 <= score <= 100


def test_reversal_score(mock_config):
    weekly_ind = {'close': 105, 'ema20': 102, 'ema20_slope': 0.5}
    daily_ind = {'close': 105, 'ema50': 110, 'ema200': 120, 'distance_ema20': 1.5, 'ema20_slope': 0.8, 'rsi': 55, 'macd': -0.5, 'macd_signal': -0.8, 'macd_hist': 0.3, 'volume_ratio': 1.4}
    struct = {'higher_low': True, 'recent_breakout': True}
    rs = {'rs_20d': 3.0}

    score, breakdown = calculate_reversal_score(daily_ind, weekly_ind, struct, rs, mock_config)
    assert 0 <= score <= 100


def test_entry_quality(mock_config):
    daily_ind = {'distance_ema20': 2.5, 'distance_ema50': 5.0, 'atr_pct': 2.5, 'volume_ratio': 1.3}
    struct = {'recent_breakout': True}
    score, details = calculate_entry_quality(daily_ind, struct, mock_config)
    assert 0 <= score <= 100


def test_candidate_score(mock_config):
    mock_config['scoring']['weights']['candidate'] = {
        'trend_weight': 0.45, 'entry_quality_weight': 0.30,
        'relative_strength_weight': 0.15, 'state_quality_weight': 0.10
    }
    mock_config['scoring']['weights']['state_quality'] = {'UPTREND': 80}
    rs = {'rs_20d': 5.0}
    score, breakdown = calculate_candidate_score(85.0, 90.0, rs, 'UPTREND', mock_config)
    assert 0 <= score <= 100
