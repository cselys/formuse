# REVERSAL_RECOVERY.md

## Intraday high/low from session history (spec section 13)

**IMPORTANT:** The theme intraday high/low are computed from the **SESSION HISTORY** — the theme's average return at every bar — not from the current snapshot. This is what makes reversal/recovery detection meaningful.

### How the session history is built

1. For each valid constituent symbol, compute `return_t = close_t / prev_close * 100 - 100` at every bar time
2. At each bar time, compute the theme's average return: `mean(return_t across valid symbols)`
3. The resulting time series is the session history
4. `intraday_high = max(theme average return across session history)`
5. `intraday_low  = min(theme average return across session history)`
6. `current        = theme average return at the last bar`

### Reversal

- `reversal_from_high = current - intraday_high` (pp, `<= 0`)
- A theme that was higher earlier in the session but has given back ground
- Shown in the **REVERSALS** panel, ranked by giveback (largest first)

### Recovery

- `recovery_from_low = current - intraday_low` (pp, `>= 0`)
- A theme that was lower earlier in the session but has recovered toward zero
- Shown in the **RECOVERIES** panel, ranked by recovery (largest first)

### State labeling (spec 12)

The theme state is determined by `classify_state()`, which checks reversal/recovery first, then trend:

```text
if has_history and reversal_from_high <= -rev_thr and up_percent < 50:
    return REVERSING_DOWN
if has_history and recovery_from_low >= rec_thr and avg_return < 0:
    return RECOVERING_UP
if avg_return > 0 and vs_open > 0 and up_percent > breadth_thr:
    return TRENDING_UP
if avg_return < 0 and vs_open < 0 and down_percent > breadth_thr:
    return TRENDING_DOWN
return MIXED
```

### Breadth momentum (spec 14)

- `breadth_now` = current `up_percent`
- `breadth_5m_ago` = `up_percent` at the bar nearest to 5 min before the last bar
- `breadth_15m_ago` = `up_percent` at the bar nearest to 15 min before the last bar
- `breadth_change_5m` = `breadth_now - breadth_5m_ago` (pp)
- `breadth_change_15m` = `breadth_now - breadth_15m_ago` (pp)

Used in the **BREADTH MOMENTUM** table, sorted by `Δ15m` descending (is participation expanding or contracting?).

### Min history bars gate (spec 12)

- `min_history_bars = 3` (from `config/settings.yaml`)
- If the session history has fewer than 3 bars, `has_history = False`
- `reversal_from_high` and `recovery_from_low` are still computed from whatever history exists
- `breadth_change_5m` and `breadth_change_15m` are `NaN` when `has_history` is `False`
- `REVERSING_DOWN` and `RECOVERING_UP` state labels are also `False` when `has_history` is `False` (the reversal/recovery logic is skipped)

### Example: REVERSING_DOWN (spec)

- Peak: +3.4%
- Current: +0.8%
- Giveback: -2.6 pp
- Breadth: 44% (down from higher levels)
- State: **REVERSING_DOWN**

### Example: RECOVERING_UP (spec 4)

- Low: -3.0%
- Current: -0.4%
- Recovery: +2.6 pp
- State: **RECOVERING_UP**