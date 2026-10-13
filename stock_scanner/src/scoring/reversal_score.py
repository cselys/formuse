"""
Reversal score calculation (0-100) for stock_scanner.
Evaluates previous downtrend, higher low, EMA20 reclaim, EMA20 slope turning positive, RSI/MACD improvement, breakout.
"""

def calculate_reversal_score(
    daily_indicators: dict,
    weekly_indicators: dict,
    structure_analysis: dict,
    rs_analysis: dict,
    config: dict
) -> tuple[float, dict]:
    """
    Calculate deterministic reversal score (0-100) and component breakdown.
    """
    weights = config['scoring']['weights']['reversal']

    score = 0.0
    breakdown = {}

    # 1. Prior downtrend (max 15): requires stock to have been below EMA50/200 or in downtrend
    max_score = weights['prior_downtrend']
    d_close = daily_indicators.get('close', 0)
    d_ema50 = daily_indicators.get('ema50', d_close)
    d_ema200 = daily_indicators.get('ema200', d_close)
    prior_below = (d_close < d_ema50) or (d_close < d_ema200) or structure_analysis.get('lower_low')
    s = max_score if prior_below else (max_score * 0.5)
    score += s
    breakdown['prior_downtrend'] = round(s, 1)

    # 2. Higher Low (max 15)
    max_score = weights['higher_low']
    s = max_score if structure_analysis.get('higher_low') else (max_score * 0.3)
    score += s
    breakdown['higher_low'] = round(s, 1)

    # 3. EMA20 reclaim (max 15)
    max_score = weights['ema20_reclaim']
    dist_ema20 = daily_indicators.get('distance_ema20', -5)
    if dist_ema20 >= 0:
        s = max_score
    elif -2.0 <= dist_ema20 < 0:
        s = max_score * 0.8
    else:
        s = max_score * 0.2
    score += s
    breakdown['ema20_reclaim'] = round(s, 1)

    # 4. EMA20 slope positive (max 10)
    max_score = weights['ema20_slope_positive']
    slope20 = daily_indicators.get('ema20_slope', 0)
    s = max_score if slope20 > 0 else (max_score * 0.4 if slope20 > -0.5 else 0.0)
    score += s
    breakdown['ema20_slope_positive'] = round(s, 1)

    # 5. RSI improvement (max 10)
    max_score = weights['rsi_improvement']
    rsi = daily_indicators.get('rsi', 50)
    if 45 <= rsi <= 70:
        s = max_score
    elif 35 <= rsi < 45:
        s = max_score * 0.7
    else:
        s = max_score * 0.3
    score += s
    breakdown['rsi_improvement'] = round(s, 1)

    # 6. MACD bullish crossover (max 10)
    max_score = weights['macd_bullish_cross']
    macd = daily_indicators.get('macd', 0)
    macd_signal = daily_indicators.get('macd_signal', 0)
    macd_hist = daily_indicators.get('macd_hist', 0)
    if macd > macd_signal or macd_hist > 0:
        s = max_score
    else:
        s = max_score * 0.3
    score += s
    breakdown['macd_bullish_cross'] = round(s, 1)

    # 7. Swing breakout (max 10)
    max_score = weights['swing_breakout']
    s = max_score if structure_analysis.get('recent_breakout') else (max_score * 0.4 if structure_analysis.get('base_formation') else 0.0)
    score += s
    breakdown['swing_breakout'] = round(s, 1)

    # 8. Volume confirmation (max 5)
    max_score = weights['volume_confirmation']
    vol_ratio = daily_indicators.get('volume_ratio', 1.0)
    s = max_score if vol_ratio >= 1.2 else (max_score * 0.6)
    score += s
    breakdown['volume_confirmation'] = round(s, 1)

    # 9. Relative strength improvement (max 5)
    max_score = weights['rs_improvement']
    rs_20 = rs_analysis.get('rs_20d', 0)
    s = max_score if rs_20 > 0 else (max_score * 0.4)
    score += s
    breakdown['rs_improvement'] = round(s, 1)

    total_score = round(max(0.0, min(100.0, score)), 1)
    return total_score, breakdown
