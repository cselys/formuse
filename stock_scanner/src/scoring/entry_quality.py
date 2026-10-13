"""
Entry Quality scoring module for stock_scanner V1.2.
Independent of trend_score, evaluating EMA20/EMA50 extension risk, ATR %, pullback quality, and breakout volume.
"""

def calculate_entry_quality(
    daily_indicators: dict,
    structure_analysis: dict,
    config: dict
) -> tuple[float, dict]:
    """
    Calculate independent Entry Quality score (0-100) and component metrics.
    """
    cfg = config.get('scoring', {}).get('weights', {}).get('entry_quality', {})

    opt_max = cfg.get('distance_ema20_optimal_max', 5.0)
    ext_mod = cfg.get('extension_moderate', 8.0)
    ext_ext = cfg.get('extension_extreme', 10.0)
    atr_min = cfg.get('atr_pct_optimal_min', 1.5)
    atr_max = cfg.get('atr_pct_optimal_max', 4.5)

    dist_ema20 = daily_indicators.get('distance_ema20', 0.0)
    dist_ema50 = daily_indicators.get('distance_ema50', 0.0)
    atr_pct = daily_indicators.get('atr_pct', 2.0)
    vol_ratio = daily_indicators.get('volume_ratio', 1.0)

    score = 60.0  # Baseline neutral-positive

    # 1. EMA20 Extension Risk
    if 0.0 <= dist_ema20 <= opt_max:
        score += 20.0
    elif opt_max < dist_ema20 <= ext_mod:
        score += 5.0
    elif ext_mod < dist_ema20 <= ext_ext:
        score -= 10.0
    elif dist_ema20 > ext_ext:
        score -= 25.0
    elif dist_ema20 < -2.0:
        score -= 10.0

    # 2. ATR % volatility health
    if atr_min <= atr_pct <= atr_max:
        score += 10.0
    elif atr_pct < 1.0:
        score += 5.0
    elif atr_pct > 7.0:
        score -= 10.0

    # 3. Structure & Volume triggers
    if structure_analysis.get('recent_breakout') and vol_ratio >= 1.1:
        score += 15.0
    elif structure_analysis.get('base_formation'):
        score += 12.0
    elif structure_analysis.get('higher_low'):
        score += 8.0

    total_score = round(max(0.0, min(100.0, score)), 1)

    details = {
        'distance_from_ema20': round(dist_ema20, 2),
        'distance_from_ema50': round(dist_ema50, 2),
        'atr_pct': round(atr_pct, 2),
        'is_extended': bool(dist_ema20 > ext_ext),
        'is_optimal_pullback': bool(0.0 <= dist_ema20 <= opt_max),
        'volume_ratio': round(vol_ratio, 2)
    }

    return total_score, details
