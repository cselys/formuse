# CALCULATIONS.md

## Per-stock metrics (spec section 8)

All formulas are applied per-stock. `previous_close` and `today_open` come from daily reference bars; `open`, `high`, `low`, `close`, `volume` come from intraday 5-minute (or 1-minute) bars.

### `change_vs_previous_close`

```text
(current_price - previous_close) / previous_close * 100
```

- `current_price`: last close of the intraday bars
- `previous_close`: close of the most recent daily bar strictly before the session date
- Returns `None` when `previous_close` is `None`, not finite, or zero

### `change_vs_open`

```text
(current_price - today_open) / today_open * 100
```

- `today_open`: official regular-session open from the daily bar (spec 22)
- Returns `None` when `today_open` is `None` (pre-market, spec 22)

### `distance_from_intraday_high`

```text
(current_price - intraday_high) / intraday_high * 100
```

- `intraday_high`: maximum `high` across the intraday bars (session high)
- Returns `None` when `intraday_high` is not finite or bar data is empty
- Value is `<= 0` when defined

### `distance_from_intraday_low`

```text
(current_price - intraday_low) / intraday_low * 100
```

- `intraday_low`: minimum `low` across the intraday bars (session low)
- Returns `None` when `intraday_low` is not finite
- Value is `>= 0` when defined

### Classification: UP / DOWN / FLAT

After `change_vs_previous_close` is computed:

```text
> +flat_threshold  -> UP
< -flat_threshold  -> DOWN
otherwise          -> FLAT
```

- Default `flat_threshold = 0.10` (from `config/settings.yaml`)
- `change_vs_previous_close` is `None` → `FLAT`

### `strong up` / `strong down` (spec 10)

Uses a separate threshold so "80% of stocks +0.2%" is distinguishable from "80% of stocks +2%":

```text
> +strong_move_threshold  -> strong up
< -strong_move_threshold  -> strong down
```

- Default `strong_move_threshold = 1.0` (from `config/settings.yaml`)

## Theme breadth (spec sections 9-11)

### Classification per stock

Same rules as above: `> flat_threshold → UP`, `< -flat_threshold → DOWN`, `otherwise → FLAT`.

### Breadth percentages

```text
up_percent   = up_stocks / valid_stocks * 100
down_percent = down_stocks / valid_stocks * 100
flat_percent = flat_stocks / valid_stocks * 100
```

- `valid_stocks` = count of stocks where `is_valid and change_vs_previous_close is not None`
- `missing_stocks` = `total_stocks - valid_stocks` (spec 23: "8 / 10 valid")
- If `valid_stocks == 0`, all percentages are `0.0`

### Strong breadth (spec 10)

```text
strong_up_percent = valid_stocks with change > strong_threshold / valid_stocks * 100
strong_down_percent = valid_stocks with change < -strong_threshold / valid_stocks * 100
```

- Default `strong_threshold = 1.0` (from `config/settings.yaml`)

### Average return

```text
mean(change_vs_previous_close across valid stocks)
```

### Median return

```text
median(change_vs_previous_close across valid stocks)
```

### Average change from open

```text
mean(change_vs_open across valid stocks that have change_vs_open is not None)
```

### Median change from open

```text
median(change_vs_open across valid stocks that have change_vs_open is not None)
```

### Total volume

```text
sum(volume across valid stocks)
```

## Theme state logic (spec 12)

Priority: reversal/recovery → trend → MIXED

```text
rev_thr = get_setting(settings, "state.reversal_threshold", 1.0)
rec_thr = get_setting(settings, "state.recovery_threshold", 1.0)
breadth_thr = get_setting(settings, "state.breadth_threshold", 60.0)
vs_open = avg_change_from_open or 0.0

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

## Breadth momentum (spec 14)

```text
breadth_now       = up_percent at the last bar
breadth_5m_ago    = up_percent at the bar nearest to 5 min before the last bar
breadth_15m_ago   = up_percent at the bar nearest to 15 min before the last bar
breadth_change_5m = breadth_now - breadth_5m_ago   (pp)
breadth_change_15m= breadth_now - breadth_15m_ago (pp)
```

Computed from `theme_return_series()` → `analyze_history()`.

## Theme state logic (spec 12, repeated for clarity)

```text
rev_thr = settings.state.reversal_threshold (default 1.0)
rec_thr = settings.state.recovery_threshold (default 1.0)
breadth_thr = settings.state.breadth_threshold (default 60.0)
vs_open = avg_change_from_open or 0.0

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

Note the asymmetry:
- **REVERSING_DOWN** requires `up_percent < 50` (breadth has flipped down)
- **RECOVERING_UP** requires `avg_return < 0` (still negative) but `recovery_from_low >= threshold` (has recovered off the lows)

## Reversal calculation (spec 13)

```text
intraday_high = max(theme average return across session history)
intraday_low  = min(theme average return across session history)
current         = theme average return at the last bar (last bar = most recent)
reversal_from_high = current - intraday_high   (pp, <= 0)
recovery_from_low  = current - intraday_low    (pp, >= 0)
```

The intraday high/low are from the **session history**, not the current snapshot. This is what makes reversal/recovery detection meaningful.

## Recovery calculation (spec 13)

Same as reversal, using the session low:

```text
intraday_low = min(theme average return across session history)
recovery_from_low = current - intraday_low   (pp, >= 0)
```

## Small-theme handling (spec 24)

- A theme with fewer than 5 valid stocks gets `small_sample = True` flag
- The flag is displayed in the UI (⚠️ small) and noted in the detail page
- The theme is **not** excluded from calculations or rankings — its flag is merely visible

## Composite score (spec 16, optional, NOT primary ranking)

```text
components (min-max normalized across themes to 0-100):
  breadth          = (up_percent - min_up%) / (max_up% - min_up%) * 100
  avg_return       = (avg_return - min_avg) / (max_avg - min_avg) * 100
  median_return    = (median_return - min_med) / (max_med - min_med) * 100
  volume           = log10(max(volume, 0) + 1) → min-max normalized * 100

composite = (0.40 * breadth + 0.30 * avg_return + 0.20 * median_return + 0.10 * volume) / (sum of weights)

Weights default from settings.yaml composite:
  breadth: 0.40, avg_return: 0.30, median_return: 0.20, volume: 0.10
```

The composite is **off by default** and never the primary ranking. The raw panels (TOP UP, TOP DOWN, etc.) are the source of truth.