"""
Daily analysis runner for stock_scanner.
Computes daily indicators, swings, and structure for a symbol DataFrame.
"""

import pandas as pd
from stock_scanner.src.indicators.trend import calculate_ema, calculate_slope
from stock_scanner.src.indicators.momentum import calculate_rsi, calculate_macd, calculate_roc
from stock_scanner.src.indicators.volatility import calculate_atr, calculate_atr_pct, calculate_distance_pct
from stock_scanner.src.indicators.volume import calculate_volume_sma, calculate_volume_ratio
from stock_scanner.src.indicators.structure import analyze_market_structure


def run_daily_analysis(df: pd.DataFrame, config: dict) -> tuple[pd.DataFrame, dict]:
    """
    Run all daily indicators and structure analysis.
    Returns (enriched_dataframe, latest_indicators_dict).
    """
    cfg = config['indicators']['daily']
    p_ema20, p_ema50, p_ema200 = cfg['ema_periods']

    df = df.copy()
    df['EMA20'] = calculate_ema(df['Close'], p_ema20)
    df['EMA50'] = calculate_ema(df['Close'], p_ema50)
    df['EMA200'] = calculate_ema(df['Close'], p_ema200)

    df['EMA20_slope'] = calculate_slope(df['EMA20'], period=5)
    df['EMA50_slope'] = calculate_slope(df['EMA50'], period=5)

    df['RSI14'] = calculate_rsi(df['Close'], period=cfg['rsi_period'])
    macd, signal, hist = calculate_macd(df['Close'], fast=cfg['macd_fast'], slow=cfg['macd_slow'], signal=cfg['macd_signal'])
    df['MACD'] = macd
    df['MACD_signal'] = signal
    df['MACD_hist'] = hist

    df['ATR14'] = calculate_atr(df, period=cfg['atr_period'])
    df['ATR_pct'] = calculate_atr_pct(df, df['ATR14'])
    df['ROC20'] = calculate_roc(df['Close'], period=cfg['roc_period'])

    h20, l20 = cfg['high_low_periods']
    df['High20'] = df['High'].rolling(window=h20, min_periods=1).max()
    df['Low20'] = df['Low'].rolling(window=l20, min_periods=1).min()
    df['High50'] = df['High'].rolling(window=50, min_periods=1).max()
    df['Low50'] = df['Low'].rolling(window=50, min_periods=1).min()
    df['High52w'] = df['High'].rolling(window=252, min_periods=1).max()
    df['Low52w'] = df['Low'].rolling(window=252, min_periods=1).min()

    df['Volume_SMA20'] = calculate_volume_sma(df['Volume'], period=cfg['volume_sma_period'])
    df['Volume_Ratio'] = calculate_volume_ratio(df['Volume'], df['Volume_SMA20'])

    df['Dist_EMA20'] = calculate_distance_pct(df['Close'], df['EMA20'])
    df['Dist_EMA50'] = calculate_distance_pct(df['Close'], df['EMA50'])
    df['Dist_EMA200'] = calculate_distance_pct(df['Close'], df['EMA200'])

    # Structure analysis
    struct_cfg = config['structure']
    structure = analyze_market_structure(df, lookback=struct_cfg['swing_lookback'], breakout_lookback=struct_cfg['breakout_lookback'])

    latest = df.iloc[-1]
    indicators = {
        'close': float(latest['Close']),
        'open': float(latest['Open']),
        'high': float(latest['High']),
        'low': float(latest['Low']),
        'volume': float(latest['Volume']),
        'ema20': float(latest['EMA20']),
        'ema50': float(latest['EMA50']),
        'ema200': float(latest['EMA200']),
        'ema20_slope': float(latest['EMA20_slope']) if not pd.isna(latest['EMA20_slope']) else 0.0,
        'ema50_slope': float(latest['EMA50_slope']) if not pd.isna(latest['EMA50_slope']) else 0.0,
        'rsi': float(latest['RSI14']),
        'macd': float(latest['MACD']),
        'macd_signal': float(latest['MACD_signal']),
        'macd_hist': float(latest['MACD_hist']),
        'atr': float(latest['ATR14']),
        'atr_pct': float(latest['ATR_pct']),
        'roc20': float(latest['ROC20']) if not pd.isna(latest['ROC20']) else 0.0,
        'high_20d': float(latest['High20']),
        'low_20d': float(latest['Low20']),
        'high_52w': float(latest['High52w']),
        'low_52w': float(latest['Low52w']),
        'volume_sma': float(latest['Volume_SMA20']),
        'volume_ratio': float(latest['Volume_Ratio']),
        'distance_ema20': float(latest['Dist_EMA20']),
        'distance_ema50': float(latest['Dist_EMA50']),
        'distance_ema200': float(latest['Dist_EMA200']),
        'structure': structure
    }

    return df, indicators
