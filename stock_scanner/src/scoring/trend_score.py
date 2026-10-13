"""
Trend score calculation (0-100) for stock_scanner.
Weights: Weekly Trend (25), Daily Trend (25), Momentum (15), Relative Strength (15), Volume (10), Structure (10).
"""

def calculate_trend_score(
    weekly_indicators: dict,
    daily_indicators: dict,
    structure_analysis: dict,
    rs_analysis: dict,
    config: dict
) -> tuple[float, dict]:
    """
    Calculate deterministic trend score (0-100) and component breakdown.
    """
    weights = config['scoring']['weights']['trend']
    max_weekly = weights['weekly_trend']
    max_daily = weights['daily_trend']
    max_mom = weights['momentum']
    max_rs = weights['relative_strength']
    max_vol = weights['volume']
    max_struct = weights['structure']

    # 1. Weekly Trend (max 25)
    w_score = 0.0
    w_close = weekly_indicators.get('close', 0)
    w_ema20 = weekly_indicators.get('ema20', 0)
    w_ema40 = weekly_indicators.get('ema40', 0)
    w_slope20 = weekly_indicators.get('ema20_slope', 0)
    w_slope40 = weekly_indicators.get('ema40_slope', 0)

    if w_close > w_ema20: w_score += 5.0
    if w_ema20 > w_ema40: w_score += 5.0
    if w_slope20 > 0: w_score += 5.0
    if w_slope40 > 0: w_score += 5.0
    if w_close > w_ema40: w_score += 3.0
    if structure_analysis.get('structure_type') == 'bullish': w_score += 2.0
    w_score = min(w_score, max_weekly)

    # 2. Daily Trend (max 25)
    d_score = 0.0
    d_close = daily_indicators.get('close', 0)
    d_ema20 = daily_indicators.get('ema20', 0)
    d_ema50 = daily_indicators.get('ema50', 0)
    d_ema200 = daily_indicators.get('ema200', 0)
    d_slope20 = daily_indicators.get('ema20_slope', 0)
    d_slope50 = daily_indicators.get('ema50_slope', 0)

    if d_close > d_ema20: d_score += 5.0
    if d_ema20 > d_ema50: d_score += 5.0
    if d_ema50 > d_ema200: d_score += 5.0
    if d_slope20 > 0: d_score += 4.0
    if d_slope50 > 0: d_score += 3.0
    if structure_analysis.get('higher_high') and structure_analysis.get('higher_low'): d_score += 3.0
    d_score = min(d_score, max_daily)

    # 3. Momentum (max 15)
    m_score = 0.0
    rsi = daily_indicators.get('rsi', 50)
    macd = daily_indicators.get('macd', 0)
    macd_signal = daily_indicators.get('macd_signal', 0)
    macd_hist = daily_indicators.get('macd_hist', 0)
    roc20 = daily_indicators.get('roc20', 0)

    # Healthy bullish RSI range: 50 to 75
    if 50 <= rsi <= 75:
        m_score += 5.0
    elif 40 <= rsi < 50:
        m_score += 2.5
    elif rsi > 75:
        m_score += 3.0 # Slightly penalize extremely overbought

    if macd > macd_signal: m_score += 3.0
    if macd_hist > 0: m_score += 4.0
    if roc20 > 0: m_score += 3.0
    m_score = min(m_score, max_mom)

    # 4. Relative Strength (max 15)
    rs_score = 0.0
    rs_20 = rs_analysis.get('rs_20d', 0)
    rs_60 = rs_analysis.get('rs_60d', 0)

    if rs_20 > 5.0: rs_score += 8.0
    elif rs_20 > 0: rs_score += 5.0

    if rs_60 > 10.0: rs_score += 7.0
    elif rs_60 > 0: rs_score += 4.0
    rs_score = min(rs_score, max_rs)

    # 5. Volume (max 10)
    v_score = 0.0
    vol_ratio = daily_indicators.get('volume_ratio', 1.0)
    if vol_ratio >= 1.2:
        v_score += 10.0
    elif vol_ratio >= 0.9:
        v_score += 8.0 # Normal volume in established trend is not penalized
    else:
        v_score += 5.0
    v_score = min(v_score, max_vol)

    # 6. Structure (max 10)
    s_score = 0.0
    if structure_analysis.get('higher_high'): s_score += 3.0
    if structure_analysis.get('higher_low'): s_score += 3.0
    if structure_analysis.get('recent_breakout'): s_score += 4.0
    elif structure_analysis.get('base_formation'): s_score += 2.0
    elif structure_analysis.get('lower_low'): s_score -= 3.0
    s_score = max(0.0, min(s_score, max_struct))

    total_score = w_score + d_score + m_score + rs_score + v_score + s_score
    total_score = round(max(0.0, min(100.0, total_score)), 1)

    breakdown = {
        'weekly_trend': round(w_score, 1),
        'daily_trend': round(d_score, 1),
        'momentum': round(m_score, 1),
        'relative_strength': round(rs_score, 1),
        'volume': round(v_score, 1),
        'structure': round(s_score, 1)
    }

    return total_score, breakdown
