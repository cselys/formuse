"""
Setup Quality and Extension Risk scoring for stock_scanner.
Independent of trend_score, evaluating pullback vs extension, ATR %, and breakout quality.
"""

def calculate_setup_quality(
    daily_indicators: dict,
    structure_analysis: dict,
    config: dict
) -> tuple[float, dict]:
    """
    Calculate independent setup quality score (0-100) and metrics.
    """
    cfg = config['scoring']['weights']['setup_quality']

    dist_ema20 = daily_indicators.get('distance_ema20', 0.0)
    atr_pct = daily_indicators.get('atr_pct', 2.0)
    vol_ratio = daily_indicators.get('volume_ratio', 1.0)

    score = 50.0  # Baseline neutral

    # 1. Distance from EMA20 (optimal pullback vs extended)
    # Optimal entry pullback: 0% to +5% above EMA20. Extended: > 10% above EMA20.
    if 0.0 <= dist_ema20 <= 5.0:
        score += 25.0  # Perfect pullback / optimal entry
    elif 5.0 < dist_ema20 <= 10.0:
        score += 10.0  # Moderate extension
    elif dist_ema20 > 10.0:
        score -= 20.0  # Overextended risk
    elif dist_ema20 < -2.0:
        score -= 10.0  # Below EMA20 (weak pull or breakdown)

    # 2. ATR % volatility health (optimal 1.5% - 4.5%)
    if 1.5 <= atr_pct <= 4.5:
        score += 15.0
    elif atr_pct < 1.0:
        score += 5.0  # Low volatility base
    elif atr_pct > 7.0:
        score -= 10.0 # Extreme volatility risk

    # 3. Structure & Volume triggers
    if structure_analysis.get('recent_breakout') and vol_ratio >= 1.2:
        score += 20.0
    elif structure_analysis.get('base_formation'):
        score += 15.0
    elif structure_analysis.get('higher_low'):
        score += 10.0

    total_score = round(max(0.0, min(100.0, score)), 1)

    details = {
        'distance_from_ema20': round(dist_ema20, 2),
        'atr_pct': round(atr_pct, 2),
        'is_extended': bool(dist_ema20 > cfg['extension_penalty_threshold']),
        'is_pullback': bool(0.0 <= dist_ema20 <= 5.0),
        'is_breakout': bool(structure_analysis.get('recent_breakout'))
    }

    return total_score, details
