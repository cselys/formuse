"""
Market State Classification and Market Regime Detection engine for stock_scanner V1.2.
Classifies stocks into defined market states and detects SPY/QQQ market regime.
"""

import logging
import pandas as pd

logger = logging.getLogger("stock_scanner.analysis")


def detect_market_regime(df_benchmark: pd.DataFrame) -> dict:
    """
    Detect lightweight deterministic market regime using benchmark (SPY/QQQ).
    Returns regime name ('MARKET_UPTREND', 'MARKET_NEUTRAL', 'MARKET_DOWNTREND') and score.
    """
    if df_benchmark is None or df_benchmark.empty or len(df_benchmark) < 50:
        return {'regime': 'MARKET_NEUTRAL', 'regime_score': 50.0}

    close = df_benchmark['Close']
    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()

    cur_close = close.iloc[-1]
    cur_ema20 = ema20.iloc[-1]
    cur_ema50 = ema50.iloc[-1]

    if cur_close > cur_ema20 and cur_ema20 > cur_ema50:
        return {'regime': 'MARKET_UPTREND', 'regime_score': 85.0}
    elif cur_close < cur_ema20 and cur_ema20 < cur_ema50:
        return {'regime': 'MARKET_DOWNTREND', 'regime_score': 25.0}
    else:
        return {'regime': 'MARKET_NEUTRAL', 'regime_score': 50.0}


def classify_state(
    trend_score: float,
    bottom_score: float,
    reversal_score: float,
    daily_indicators: dict,
    weekly_indicators: dict,
    structure_analysis: dict,
    rs_analysis: dict,
    config: dict,
    state_history: list = None,
    trend_history: list = None,
) -> str:
    """
    Classify stock into one of the defined market states using V1.2 deterministic rules.
    Incorporates flexible volume confirmation window for BOTTOM_BREAKOUT and early vs confirmed reversal distinction.

    Optional history (causal: days strictly before today only):
    - state_history: list of past state strings, oldest -> newest
    - trend_history: list of past trend_scores, oldest -> newest
    When provided, two 2026-10-15 gates apply:
    - BOTTOM family requires a prior "washout" (trend_score <= bottom_washout_trend_max
      within bottom_washout_lookback_days) — no washout, no bottom call.
    - REVERSAL express lane: reversal_express_days consecutive reversal-family states
      with a strictly rising trend_score promote straight to UPTREND.
    When history is None, behavior is unchanged (V1.2 rules as before).
    """
    close = daily_indicators.get('close', 0)
    volume = daily_indicators.get('volume_sma', 0)
    atr_pct = daily_indicators.get('atr_pct', 0)

    if close <= 0 or pd_is_nan(close) or volume <= 1000 or atr_pct > 15.0:
        return 'AVOID'

    rsi = daily_indicators.get('rsi', 50)
    d_ema20 = daily_indicators.get('ema20', 0)
    d_ema50 = daily_indicators.get('ema50', 0)
    d_ema200 = daily_indicators.get('ema200', 0)
    w_close = weekly_indicators.get('close', 0)
    w_ema20 = weekly_indicators.get('ema20', 0)
    w_ema40 = weekly_indicators.get('ema40', 0)
    w_slope20 = weekly_indicators.get('ema20_slope', 0)

    bb_cfg = config.get('bottom_breakout', {'min_bottom_score': 65, 'volume_ratio_threshold': 1.2})
    min_b_score = bb_cfg.get('min_bottom_score', 65)
    vol_thresh = bb_cfg.get('volume_ratio_threshold', 1.2)

    # 1. STRONG_UPTREND
    if (
        trend_score >= 85
        and w_close > w_ema20
        and w_ema20 > w_ema40
        and w_slope20 > 0
        and close > d_ema20
        and d_ema20 > d_ema50
        and d_ema50 > d_ema200
        and structure_analysis.get('structure_type') in ['bullish', 'neutral']
        and rsi > 50
    ):
        return 'STRONG_UPTREND'

    # 2. UPTREND
    if trend_score >= 70 and close > d_ema20 and d_ema20 > d_ema50:
        return 'UPTREND'

    # 2b. REVERSAL express lane (2026-10-15 fix 3): a stock that has sat in the
    # reversal family for N days with a monotonically rising trend_score is
    # already in an uptrend (WMT case: 8 REVERSAL days, trend 20.5 -> 62).
    gates = config.get('state_gates', {}) or {}
    _REV_FAMILY = ('REVERSAL', 'REVERSAL_CONFIRMED', 'EARLY_UPTREND')
    _exp_n = int(gates.get('reversal_express_days', 3) or 3)
    if (
        state_history and trend_history
        and len(state_history) >= _exp_n and len(trend_history) >= _exp_n
        and all(s in _REV_FAMILY for s in state_history[-_exp_n:])
        and all(b > a for a, b in zip(trend_history[-_exp_n:-1], trend_history[-_exp_n + 1:]))
        and close > d_ema20
    ):
        return 'UPTREND'

    # 3. REVERSAL (Actionable early reversal)
    if reversal_score >= 55 and (structure_analysis.get('higher_low') or structure_analysis.get('recent_breakout')) and close >= d_ema20 * 0.97:
        return 'REVERSAL'

    # 4. REVERSAL_CONFIRMED (Stronger evidence, weekly alignment)
    if reversal_score >= 70 and w_close > w_ema20 and w_slope20 > 0:
        return 'REVERSAL_CONFIRMED'

    # 5. BOTTOM_BREAKOUT (V1.2 updated with flexible volume confirmation check)
    # 2026-10-15 fix 2: no washout (trend never <= thresh) -> not a real bottom.
    _wo_thresh = float(gates.get('bottom_washout_trend_max', 35) or 35)
    _wo_lb = int(gates.get('bottom_washout_lookback_days', 60) or 60)
    vol_ratio = daily_indicators.get('volume_ratio', 1.0)
    if bottom_score >= min_b_score and (structure_analysis.get('recent_breakout') or vol_ratio >= vol_thresh) \
            and _had_washout(trend_history, _wo_thresh, _wo_lb):
        return 'BOTTOM_BREAKOUT'

    # 6. BOTTOM_FORMING
    if bottom_score >= 55 and (structure_analysis.get('higher_low') or structure_analysis.get('base_formation')) \
            and _had_washout(trend_history, _wo_thresh, _wo_lb):
        return 'BOTTOM_FORMING'

    # 7. EARLY_UPTREND
    if trend_score >= 50 and (close > d_ema20 or abs(daily_indicators.get('distance_ema20', -5)) <= 2.5) and daily_indicators.get('ema20_slope', -1) >= -0.2:
        return 'EARLY_UPTREND'

    # 8. STRONG_DOWNTREND
    if trend_score <= 20 and close < d_ema20 and d_ema20 < d_ema50 and d_ema50 < d_ema200 and structure_analysis.get('structure_type') == 'bearish':
        return 'STRONG_DOWNTREND'

    # 9. DOWNTREND
    if trend_score <= 35 and close < d_ema20 and d_ema20 < d_ema50:
        return 'DOWNTREND'

    # 10. Default NEUTRAL
    return 'NEUTRAL'


def _had_washout(trend_history, thresh: float, lookback_days: int) -> bool:
    """True if trend_score hit <= thresh within the lookback window (fix 2).

    None history -> True (gate not applicable, preserve old behavior).
    """
    if not trend_history:
        return True
    window = trend_history[-lookback_days:]
    try:
        return min(window) <= thresh
    except (TypeError, ValueError):
        return True


def pd_is_nan(val) -> bool:
    return pd.isna(val)
