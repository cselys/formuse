# RANKINGS.md

## Separate rankings (spec section 15)

The rankings are deliberately **separate** — the user should see what each one means. Do NOT collapse them into a single score (the composite is optional and never the primary ranking in V1).

### `top_up` (spec: "Top Up")

- **Sort by:** `average_return` descending
- **Columns in panel:** Theme, Avg %, vs Open, Up %, Strong Up %, Stocks, State
- **Filter:** `valid_stocks > 0` and (optionally) `valid_stocks >= min_theme_size`

### `top_down` (spec: "Top Down")

- **Sort by:** `average_return` ascending (most negative first)
- **Columns in panel:** Theme, Avg %, vs Open, Down %, Strong Down %, Stocks, State
- **Filter:** same as TOP UP

### `broadest_up` (spec: "Broadest Up")

- **Sort by:** `up_percent` descending
- **Interpretation:** Themes where the largest number of stocks are moving up, regardless of magnitude
- **Columns in panel:** Theme, Avg %, vs Open, Up %, Strong Up %, Stocks, State

### `broadest_down` (spec: "Broadest Down")

- **Sort by:** `down_percent` descending
- **Interpretation:** Themes where the largest number of stocks are moving down, regardless of magnitude
- **Columns in panel:** Theme, Avg %, vs Open, Down %, Strong Down %, Stocks, State

### `biggest_reversals` (spec: "Biggest Reversal")

- **Sort by:** `reversal_from_high` ascending (most giveback first)
- **Filter:** `reversal_from_high < -abs(threshold)` (strict inequality; a reversal of exactly 0 pp is not a reversal)
- **Threshold:** from `settings.state.reversal_threshold` (default 1.0 pp)
- **Columns in panel:** Theme, Intraday Peak, Current, Giveback, Breadth (up %), State
- **Interpretation:** Themes that have given back the most ground from their intraday peak

### `biggest_recoveries` (spec: "Biggest Recovery")

- **Sort by:** `recovery_from_low` descending
- **Filter:** `recovery_from_low > abs(threshold)` (strict inequality; a recovery of exactly 0 pp is not a recovery)
- **Threshold:** from `settings.state.recovery_threshold` (default 1.0 pp)
- **Columns in panel:** Theme, Intraday Low, Current, Recovery, Breadth (up %), State
- **Interpretation:** Themes that have recovered the most ground from their intraday low

## Composite score (spec section 16)

**Optional** — NOT the primary ranking in V1.

- Each component is min-max normalized across themes to 0–100:
  - `breadth` = `(up_percent - min_up%) / (max_up% - min_up%) * 100`
  - `avg_return` = `(avg_return - min_avg) / (max_avg - min_avg) * 100`
  - `median_return` = `(median_return - min_med) / (max_med - min_med) * 100`
  - `volume` = `log10(max(volume, 0) + 1)` → min-max normalized * 100
- Weights (from `settings.composite.weights`, default):
  - `breadth: 0.40`, `avg_return: 0.30`, `median_return: 0.20`, `volume: 0.10`
- Final score: `(w_b * breadth[i] + w_a * avg[i] + w_m * med[i] + w_v * vol[i]) / (sum of weights)`
- Rounded to 1 decimal place
- Returned as `{theme: score, ...}`
- **Transparency:** The raw panels above are the source of truth; the composite is for reference only

## How to read the ranking panels

Each panel displays `top_n` themes (default 6) from `build_rankings()`.
The `min_theme_size` setting filters out themes with fewer valid stocks than the threshold.
The `show` toggles in the sidebar control which panels are visible.