# Stock Scanner V1.2 — Methodology & Scoring

## Core Philosophy

V1.3 retains the score definitions below and adds completed-session/week inputs
and descriptive weekly diagnostics. The precise calendar, availability,
alignment and report rules are in [WEEKLY_REPORTS.md](WEEKLY_REPORTS.md).

`stock_scanner` decouples **trend strength** from **entry attractiveness**. A stock can possess a high trend score but terrible entry location due to overextension; separating these dimensions ensures robust candidate ranking.

---

## 1. Score Definitions

### Trend Score (0–100)
Measures long-term and intermediate trend health.
- **Weights**:
  - Weekly Trend: 25%
  - Daily Trend: 25%
  - Momentum: 15%
  - Relative Strength: 15%
  - Volume: 10%
  - Structure: 10%
- *Note*: Trend Score measures trend strength, not entry location.

### Bottom Score (0–100)
Evaluates evidence of base formation and stabilization after a significant decline (requires structural stabilization, higher lows, and RSI/MACD recovery).

### Reversal Score (0–100)
Evaluates transition from downtrend to recovery (prior downtrend, higher low, EMA20 reclaim, positive slope, and RSI/MACD improvement).

### Entry Quality (0–100)
Independent score evaluating price location relative to moving averages (EMA20/EMA50 distance), ATR % volatility health, and breakout volume. Punishes extreme overextension (>10% above EMA20).

### Candidate Score (0–100)
The final weighted ranking composite:
- Trend Score: 45%
- Entry Quality: 30%
- Relative Strength: 15%
- State Quality: 10%

---

## 2. Market Regimes & States

### Market Regimes (SPY/QQQ)
- `MARKET_UPTREND`: Price > EMA20 and EMA20 > EMA50.
- `MARKET_DOWNTREND`: Price < EMA20 and EMA20 < EMA50.
- `MARKET_NEUTRAL`: Mixed moving average alignment.

### State Classifications
- `STRONG_UPTREND`: Trend score >= 85, bullish weekly/daily conditions, RSI > 50.
- `UPTREND`: Trend score >= 70, bullish weekly/daily conditions.
- `EARLY_UPTREND`: Improving trend conditions, price near or above EMA20, non-negative slope.
- `BOTTOM_FORMING`: Base formation / stabilization after decline.
- `BOTTOM_BREAKOUT`: Valid bottom structure with recent breakout and flexible volume confirmation window.
- `REVERSAL`: Early actionable reversal structure.
- `REVERSAL_CONFIRMED`: Stronger evidence with weekly trend alignment.
- `NEUTRAL`: Sideways or mixed state.
- `DOWNTREND` / `STRONG_DOWNTREND`: Bearish alignment.
- `AVOID`: Insufficient data, extreme illiquidity, or data anomalies (`atr_pct > 15%`).

---

## 3. Weekly Candle Treatment
- Resamples daily OHLCV into Friday-ending weekly bars (`W-FRI`).
- Strictly enforces `drop_partial=True` in historical evaluations to drop incomplete current weeks, preventing lookahead bias.
