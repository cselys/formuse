"""
Weekly analysis runner for stock_scanner.
Computes weekly indicators and trends from resampled weekly data.
"""

import pandas as pd
from stock_scanner.src.indicators.trend import calculate_ema, calculate_slope
from stock_scanner.src.indicators.momentum import calculate_rsi, calculate_macd
from stock_scanner.src.indicators.volatility import calculate_atr
from stock_scanner.src.indicators.volume import calculate_volume_sma, calculate_volume_ratio


def run_weekly_analysis(df_weekly: pd.DataFrame, config: dict) -> dict:
    """
    Run weekly indicators on resampled weekly OHLCV.
    Returns latest weekly indicators dictionary.
    """
    if df_weekly.empty or len(df_weekly) < 10:
        return {
            'close': 0.0,
            'ema10': 0.0,
            'ema20': 0.0,
            'ema40': 0.0,
            'ema50': 0.0,
            'ema20_slope': 0.0,
            'ema40_slope': 0.0,
            'rsi': 50.0,
            'macd': 0.0,
            'macd_signal': 0.0,
            'macd_hist': 0.0,
            'atr': 0.0,
            'volume_ratio': 1.0
        }

    cfg = config['indicators']['weekly']
    p10, p20, p40, p50 = cfg['ema_periods']

    df = df_weekly.copy()
    df['EMA10'] = calculate_ema(df['Close'], p10)
    df['EMA20'] = calculate_ema(df['Close'], p20)
    df['EMA40'] = calculate_ema(df['Close'], p40)
    df['EMA50'] = calculate_ema(df['Close'], p50)

    df['EMA20_slope'] = calculate_slope(df['EMA20'], period=3)
    df['EMA40_slope'] = calculate_slope(df['EMA40'], period=3)

    df['RSI14'] = calculate_rsi(df['Close'], period=cfg['rsi_period'])
    macd, signal, hist = calculate_macd(df['Close'], fast=cfg['macd_fast'], slow=cfg['macd_slow'], signal=cfg['macd_signal'])
    df['MACD'] = macd
    df['MACD_signal'] = signal
    df['MACD_hist'] = hist

    df['ATR14'] = calculate_atr(df, period=cfg['atr_period'])
    df['Volume_SMA20'] = calculate_volume_sma(df['Volume'], period=cfg['volume_sma_period'])
    df['Volume_Ratio'] = calculate_volume_ratio(df['Volume'], df['Volume_SMA20'])

    latest = df.iloc[-1]
    return {
        'close': float(latest['Close']),
        'ema10': float(latest['EMA10']),
        'ema20': float(latest['EMA20']),
        'ema40': float(latest['EMA40']),
        'ema50': float(latest['EMA50']),
        'ema20_slope': float(latest['EMA20_slope']) if not pd.isna(latest['EMA20_slope']) else 0.0,
        'ema40_slope': float(latest['EMA40_slope']) if not pd.isna(latest['EMA40_slope']) else 0.0,
        'rsi': float(latest['RSI14']),
        'macd': float(latest['MACD']),
        'macd_signal': float(latest['MACD_signal']),
        'macd_hist': float(latest['MACD_hist']),
        'atr': float(latest['ATR14']),
        'volume_ratio': float(latest['Volume_Ratio'])
    }
