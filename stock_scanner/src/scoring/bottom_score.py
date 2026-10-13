"""
Bottom score calculation (0-100) for stock_scanner.
Requires evidence of stabilization, higher lows, RSI/MACD improvement, and EMA20 reclaim.
"""

def calculate_bottom_score(
    daily_indicators: dict,
    structure_analysis: dict,
    rs_analysis: dict,
    df_daily: object,
    config: dict
) -> tuple[float, dict]:
    """
    Calculate deterministic bottom score (0-100) and component breakdown.
    Do not classify as bottoming merely because it fell a large percentage.
    """
    weights = config['scoring']['weights']['bottom']

    score = 0.0
    breakdown = {}

    # 1. 52-week decline (max 15): requires substantial prior decline (e.g. down > 30% from 52w high)
    max_score = weights['decline_52w']
    high_52w = daily_indicators.get('high_52w', daily_indicators.get('close', 1))
    current_close = daily_indicators.get('close', 0)
    decline_pct = (high_52w - current_close) / high_52w * 100.0 if high_52w > 0 else 0
    if decline_pct >= 40.0:
        s = max_score
    elif decline_pct >= 25.0:
        s = max_score * 0.7
    elif decline_pct >= 15.0:
        s = max_score * 0.4
    else:
        s = 0.0
    score += s
    breakdown['decline_52w'] = round(s, 1)

    # 2. Decline stabilization (max 15): no new 20-day low recently or price stabilizing above support
    max_score = weights['stabilization']
    low_20d = daily_indicators.get('low_20d', current_close)
    dist_from_20d_low = (current_close - low_20d) / low_20d * 100.0 if low_20d > 0 else 0
    if 0 <= dist_from_20d_low <= 5.0 and not structure_analysis.get('lower_low'):
        s = max_score
    elif 5.0 < dist_from_20d_low <= 10.0:
        s = max_score * 0.7
    else:
        s = max_score * 0.3
    score += s
    breakdown['stabilization'] = round(s, 1)

    # 3. Higher Low (max 15)
    max_score = weights['higher_low']
    s = max_score if structure_analysis.get('higher_low') else 0.0
    score += s
    breakdown['higher_low'] = round(s, 1)

    # 4. RSI improvement (max 10): RSI recovering from oversold (<30) back above 40
    max_score = weights['rsi_improvement']
    rsi = daily_indicators.get('rsi', 50)
    if 40 <= rsi <= 60:
        s = max_score
    elif 30 <= rsi < 40:
        s = max_score * 0.7
    else:
        s = max_score * 0.2
    score += s
    breakdown['rsi_improvement'] = round(s, 1)

    # 5. MACD improvement (max 10): MACD histogram positive or crossing signal
    max_score = weights['macd_improvement']
    macd_hist = daily_indicators.get('macd_hist', 0)
    s = max_score if macd_hist > 0 else (max_score * 0.5 if macd_hist > -0.5 else 0.0)
    score += s
    breakdown['macd_improvement'] = round(s, 1)

    # 6. EMA20 reclaim (max 10): Close near or above EMA20
    max_score = weights['ema20_reclaim']
    dist_ema20 = daily_indicators.get('distance_ema20', -10)
    if dist_ema20 >= 0:
        s = max_score
    elif -3.0 <= dist_ema20 < 0:
        s = max_score * 0.7
    else:
        s = max_score * 0.2
    score += s
    breakdown['ema20_reclaim'] = round(s, 1)

    # 7. Volume confirmation (max 10): volume expansion on up days
    max_score = weights['volume_confirmation']
    vol_ratio = daily_indicators.get('volume_ratio', 1.0)
    s = max_score if vol_ratio >= 1.2 else (max_score * 0.7 if vol_ratio >= 0.9 else max_score * 0.3)
    score += s
    breakdown['volume_confirmation'] = round(s, 1)

    # 8. Relative strength improvement (max 10)
    max_score = weights['rs_improvement']
    rs_20 = rs_analysis.get('rs_20d', -10)
    s = max_score if rs_20 > 0 else (max_score * 0.6 if rs_20 > -5.0 else 0.0)
    score += s
    breakdown['rs_improvement'] = round(s, 1)

    # 9. Distance from 52w low (max 5)
    max_score = weights['distance_from_low']
    low_52w = daily_indicators.get('low_52w', current_close)
    dist_52w_low = (current_close - low_52w) / low_52w * 100.0 if low_52w > 0 else 0
    if dist_52w_low <= 15.0:
        s = max_score
    elif dist_52w_low <= 30.0:
        s = max_score * 0.6
    else:
        s = max_score * 0.2
    score += s
    breakdown['distance_from_low'] = round(s, 1)

    total_score = round(max(0.0, min(100.0, score)), 1)
    return total_score, breakdown
