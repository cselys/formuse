# ALERTS.md

## Cross-refresh alert detection (spec section 27)

Alerts describe **observed facts** — they never say "buy" or "sell" (spec section 29).

Alerts are detected by comparing the current refresh against:

1. **Absolute thresholds** (breadth jump/collapse, strong reversal/recovery)
2. **The previous refresh's Top-3** (entry / exit)

### Thresholds (from `config/settings.yaml`)

| Alert type                    | Setting                      | Default |
|------------------------------|------------------------------|---------|
| Breadth change (5 min)       | `alerts.breadth_change_5m`   | 15.0 pp |
| Breadth change (15 min)      | `alerts.breadth_change_15m`  | 20.0 pp |
| Strong reversal (pp)         | `alerts.strong_reversal_pp`  | 2.0 pp  |
| Strong recovery (pp)         | `alerts.strong_recovery_pp`  | 2.0 pp  |

### Breadth breakout / collapse

- If `breadth_change_5m >= 15`: **"Breadth Breakout"** — up% jumped at least 15 pp in 5 minutes
- If `breadth_change_5m <= -15`: **"Breadth Collapse"** — down% jumped at least 15 pp in 5 minutes
- Same logic for 15-min thresholds (default 20 pp)

### Strong reversal

- If `reversal_from_high <= -2.0` and `up_percent < 50`: **"Strong Reversal"** — the theme gave back at least 2 pp from its peak AND breadth has flipped (up% < 50)

### Strong recovery

- If `recovery_from_low >= 2.0`: **"Strong Recovery"** — the theme has recovered at least 2 pp from its intraday low

### Top-3 entry / exit (vs previous refresh)

- `previous_top3` is stored in `st.session_state["top3_last"]` from the prior run
- If a theme enters the current Top 3 but was not in the previous Top 3: **"Top 3 Entry"**
- If a theme was in the previous Top 3 but is not in the current Top 3: **"Top 3 Exit"**

### Alert format

```text
🚨 BREADTH BREAKOUT — Semiconductor breadth increased from 54% → 83% in 5 minutes. Average return +2.1%.
```

or

```text
🔔 STRONG REVERSAL — Semiconductor gave back 2.5 pp from its intraday peak +3.2% (now +0.7%, up 28%).
```

### How alerts are triggered

1. `detect_alerts(current_metrics, previous_top3, settings)` is called after each refresh
2. Alerts are appended to `ctx["alerts"]`
3. `st.session_state["top3_last"]` is updated to `top3_by_return(current)` for the next refresh
4. Alerts appear in the **🚨 Alerts** section at the top of the dashboard
5. Only the most recent 10 alerts are shown; older auto-refresh alerts drop off

### Alert lifecycle

- Alerts are **not persistent** across script runs (they are computed fresh each refresh)
- The `top3_last` session state persists across refreshes within a single Streamlit run
- Alerts do not accumulate indefinitely — they are replaced each refresh cycle