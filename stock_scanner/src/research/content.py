"""Signal definitions and report content, traced from the ACTUAL V1.2/V1.3 code.

Source of truth:
- src/analysis/regime.py classify_state / detect_market_regime
- src/scoring/{trend,bottom,reversal,entry_quality,candidate}_score.py
- config/scanner.yaml thresholds
No formulas are restated from memory alone; each item cites the traced condition.
"""

DEFINITIONS_HTML = """
<p class=note>Traced from <code>src/analysis/regime.py:classify_state</code> and
<code>src/scoring/*.py</code>, with <code>config/scanner.yaml</code> weights.
Guard first: <code>AVOID</code> when close <= 0, volume_sma <= 1000, or atr_pct > 15%.
Rules are evaluated in order; first match wins.</p>
<table border=1 style='border-collapse:collapse;font-size:12px'>
<tr><th>State (in evaluation order)</th><th>Trigger condition (actual)</th></tr>
<tr><td>STRONG_UPTREND</td><td>trend_score &ge; 85 AND weekly close > weekly EMA20 AND weekly EMA20 > weekly EMA40 AND weekly EMA20 slope > 0 AND close > daily EMA20 AND daily EMA20 > daily EMA50 AND daily EMA50 > daily EMA200 AND structure_type in {bullish, neutral} AND RSI > 50</td></tr>
<tr><td>UPTREND</td><td>trend_score &ge; 70 AND close > daily EMA20 AND daily EMA20 > daily EMA50</td></tr>
<tr><td>REVERSAL</td><td>reversal_score &ge; 55 AND (higher_low OR recent_breakout) AND close &ge; EMA20 &times; 0.97</td></tr>
<tr><td>REVERSAL_CONFIRMED</td><td>reversal_score &ge; 70 AND weekly close > weekly EMA20 AND weekly EMA20 slope > 0</td></tr>
<tr><td>BOTTOM_BREAKOUT</td><td>bottom_score &ge; 65 AND (recent_breakout OR volume_ratio &ge; 1.2)</td></tr>
<tr><td>BOTTOM_FORMING</td><td>bottom_score &ge; 55 AND (higher_low OR base_formation)</td></tr>
<tr><td>EARLY_UPTREND</td><td>trend_score &ge; 50 AND (close > daily EMA20 OR |distance_ema20| &le; 2.5) AND daily EMA20 slope &ge; &minus;0.2</td></tr>
<tr><td>STRONG_DOWNTREND</td><td>trend_score &le; 20 AND close < EMA20 < EMA50 < EMA200 AND structure_type == bearish</td></tr>
<tr><td>DOWNTREND</td><td>trend_score &le; 35 AND close < EMA20 AND EMA20 < EMA50</td></tr>
<tr><td>NEUTRAL</td><td>default — no prior rule matched</td></tr>
</table>
<h3>Scores (score contribution, not triggers)</h3>
<table border=1 style='border-collapse:collapse;font-size:12px'>
<tr><th>Score</th><th>Composition (actual)</th></tr>
<tr><td>Trend Score (0&ndash;100)</td><td>Weekly trend 25 (close>EMA20 +5, EMA20>EMA40 +5, slope20>0 +5, slope40>0 +5, close>EMA40 +3, bullish structure +2) + Daily trend 25 (close>EMA20 +5, EMA20>EMA50 +5, EMA50>EMA200 +5, slope20>0 +4, slope50>0 +3, HH&HL +3) + Momentum 15 (RSI 50&ndash;75 +5 / 40&ndash;50 +2.5 / >75 +3; MACD>signal +3; hist>0 +4; ROC20>0 +3) + RS 15 (rs20>5 +8 / >0 +5; rs60>10 +7 / >0 +4) + Volume 10 (ratio&ge;1.2 +10 / &ge;0.9 +8 / else +5) + Structure 10 (HH +3, HL +3, breakout +4 / base +2 / lower_low &minus;3)</td></tr>
<tr><td>Bottom Score (0&ndash;100)</td><td>52w decline 15 (&ge;40% full, &ge;25% 0.7&times;, &ge;15% 0.4&times;) + stabilization 15 (&le;5% above 20d low & no LL full; &le;10% 0.7&times;; else 0.3&times;) + higher_low 15 (binary) + RSI improvement 10 (40&ndash;60 full; 30&ndash;40 0.7&times;; else 0.2&times;) + MACD improvement 10 (hist>0 full; >&minus;0.5 half; else 0) + EMA20 reclaim 10 (&ge;0 full; &ge;&minus;3 0.7&times;; else 0.2&times;) + volume confirmation 10 (ratio&ge;1.2 full; &ge;0.9 0.7&times;; else 0.3&times;) + RS improvement 10 (rs20>0 full; >&minus;5 0.6&times;; else 0) + distance from 52w low 5 (&le;15% full; &le;30% 0.6&times;; else 0.2&times;)</td></tr>
<tr><td>Reversal Score (0&ndash;100)</td><td>prior_downtrend 15 (below EMA50/200 or LL full; else half) + higher_low 15 (binary; else 0.3&times;) + EMA20 reclaim 15 (&ge;0 full; &ge;&minus;2 0.8&times;; else 0.2&times;) + EMA20 slope 10 (>0 full; >&minus;0.5 0.4&times;; else 0) + RSI improvement 10 (45&ndash;70 full; 35&ndash;45 0.7&times;; else 0.3&times;) + MACD cross 10 (MACD>signal or hist>0 full; else 0.3&times;) + swing breakout 10 (breakout full; base 0.4&times;; else 0) + volume 5 (ratio&ge;1.2 full; else 0.6&times;) + RS 5 (rs20>0 full; else 0.4&times;)</td></tr>
<tr><td>Entry Quality (0&ndash;100)</td><td>Baseline 60 &plusmn; EMA20 extension (0..5% +20; 5..8% +5; 8..10% &minus;10; >10% &minus;25; <&minus;2% &minus;10) &plusmn; ATR% health (1.5&ndash;4.5 +10; <1 +5; >7 &minus;10) &plusmn; structure/volume (recent_breakout & ratio&ge;1.1 +15; base_formation +12; higher_low +8). Volume contributes via breakout+direction-agnostic ratio only — credit is given for elevated volume with a breakout, or for base/HL structure regardless of volume direction; elevated volume alone without breakout adds no structure/volume trigger points.</td></tr>
<tr><td>Candidate Score (0&ndash;100)</td><td>0.45&times;Trend + 0.30&times;Entry Quality + 0.15&times;RS-normalized + 0.10&times;State Quality. RS-normalized = clamp(50 + 2.5&times;rs_20d, 0, 100). State Quality map: REVERSAL 95, EARLY_UPTREND 90, BOTTOM_BREAKOUT 85, UPTREND 80, STRONG_UPTREND 75, BOTTOM_FORMING 70, REVERSAL_CONFIRMED 65, NEUTRAL 50, DOWNTREND 30, STRONG_DOWNTREND 20, AVOID 0.</td></tr>
</table>
<h3>Market Regime (SPY/QQQ)</h3>
<p><code>MARKET_UPTREND</code>: benchmark close > EMA20 > EMA50 (score 85). <code>MARKET_DOWNTREND</code>: close < EMA20 < EMA50 (score 25). <code>MARKET_NEUTRAL</code>: mixed (score 50). Requires &ge;50 benchmark bars, else NEUTRAL.</p>
<h3>Trigger vs score vs classification (RCAT-relevant)</h3>
<p class=note><b>BOTTOM_FORMING/BOTTOM_BREAKOUT are classified from the Bottom Score and
structure/volume triggers only</b> — Trend Score, RS, and EMA20/EMA50 position are NOT
conditions for those two states (they affect the Bottom Score components decline/stabilization/reclaim/RS-improvement,
but BOTTOM_BREAKOUT in particular can fire on <code>volume_ratio &ge; 1.2</code> alone once
bottom_score &ge; 65, even with price far below EMA20/EMA50 and strongly negative RS).
This distinction matters for the RCAT case study below.</p>
"""


def limitations_html(missing_reasons):
    return f"""
<ul>
<li>Recorded observations come from scan JSON (<code>data/reports</code>) produced by live
scans — <b>RECORDED</b> provenance, with per-record <code>history_context</code> and
<code>history_result_fingerprint</code> metadata. Verified reconstruction via the existing
SQLite revision store was not re-run here; RECORDED is used as-is and never mixed with
unverified artifacts.</li>
<li>Forward outcomes use the existing local parquet price cache (adjusted OHLC). Horizons are
trading sessions strictly after the observation date; insufficient future bars leave the horizon
NA (not filled). Missing reasons: observation date too recent for the horizon, or symbol not in
the local cache.</li>
<li>{missing_reasons}</li>
<li>Observation-level statistics treat every recorded row as one observation; event/transition
statistics count state changes once. Neither is de-duplicated into "independent signals" beyond
that.</li>
<li>Descriptive research only. Sample-size labels (INSUFFICIENT <10, SMALL 10&ndash;29,
DESCRIPTIVE &ge;30) describe statistical coverage, not signal quality; N&ge;30 does not prove an edge.</li>
<li>Recorded scan dates include gaps (e.g. 2026-09-17 missing) — transitions never inferred
across gaps.</li>
<li>V1.2/V1.3 scoring, classification, thresholds and volume logic were NOT modified for this
report; no new Call/Put score; no threshold optimization.</li>
</ul>
"""
