# DATA_MODEL.md

## StockSnapshot (spec section 8)

| Field | Type | Description |
|-------|------|-------------|
| `symbol` | `str` | Ticker symbol |
| `timestamp` | `str` (ISO-8601, ET) | "As of" time for this snapshot |
| `previous_close` | `Optional[float]` | Official previous close price |
| `today_open` | `Optional[float]` | Official regular-session open price (spec 22). `None` when not yet available (pre-market) |
| `current_price` | `Optional[float]` | Last close price of the intraday session |
| `intraday_high` | `Optional[float]` | Maximum `high` across the intraday bars (session high) |
| `intraday_low` | `Optional[float]` | Minimum `low` across the intraday bars (session low) |
| `change_vs_previous_close` | `Optional[float]` | `(current_price - previous_close) / previous_close * 100` |
| `change_vs_open` | `Optional[float]` | `(current_price - today_open) / today_open * 100`. `None` when `today_open` is `None` |
| `distance_from_intraday_high` | `Optional[float]` | `(current_price - intraday_high) / intraday_high * 100`. `<= 0` when defined |
| `distance_from_intraday_low` | `Optional[float]` | `(current_price - intraday_low) / intraday_low * 100`. `>= 0` when defined |
| `volume` | `int` | Sum of intraday bar volumes (session total so far) |
| `is_valid` | `bool` | `True` when `current_price` and `previous_close` are finite and `previous_close` is available |
| `issue` | `str` | Human-readable reason if not valid (e.g. `"no intraday data"`, `"no valid previous close (IPO?)"`, `"stale quote"`, `"no open yet"`)
| `direction` | `str` | `UP` if `change_vs_previous_close > flat_threshold`, `DOWN` if `< -flat_threshold`, else `FLAT` |

## ThemeMetrics (spec sections 9-15)

| Field | Type | Description |
|-------|------|-------------|
| `theme` | `str` | Theme name |
| `timestamp` | `str` (ISO-8601, ET) | Data snapshot "as of" time |
| `total_stocks` | `int` | Number of tickers configured into the theme |
| `valid_stocks` | `int` | Number of configured tickers that have a valid `StockSnapshot` with `change_vs_previous_close` |
| `missing_stocks` | `int` | `total_stocks - valid_stocks` |
| `up_stocks` | `int` | Count of valid stocks with `change_vs_previous_close > flat_threshold` |
| `down_stocks` | `int` | Count of valid stocks with `change_vs_previous_close < -flat_threshold` |
| `flat_stocks` | `int` | `valid_stocks - up_stocks - down_stocks` |
| `up_percent` | `float` | `up_stocks / valid_stocks * 100` if `valid_stocks > 0`, else `0.0` |
| `down_percent` | `float` | `down_stocks / valid_stocks * 100` if `valid_stocks > 0`, else `0.0` |
| `flat_percent` | `float` | `flat_stocks / valid_stocks * 100` if `valid_stocks > 0`, else `0.0` |
| `strong_up_percent` | `float` | `valid_stocks with change > strong_threshold / valid_stocks * 100` if `valid_stocks > 0`, else `0.0` |
| `strong_down_percent` | `float` | `valid_stocks with change < -strong_threshold / valid_stocks * 100` if `valid_stocks > 0`, else `0.0` |
| `average_return` | `float` | Mean of `change_vs_previous_close` across valid stocks |
| `median_return` | `float` | Median of `change_vs_previous_close` across valid stocks |
| `average_change_from_open` | `float` | Mean of `change_vs_open` across valid stocks that have `change_vs_open is not None` |
| `median_change_from_open` | `float` | Median of `change_vs_open` across valid stocks that have `change_vs_open is not None` |
| `total_volume` | `int` | Sum of `volume` across valid stocks |
| `intraday_high` | `float` | Maximum theme average return across the session history (spec 13) |
| `intraday_low` | `float` | Minimum theme average return across the session history (spec 13) |
| `reversal_from_high` | `float` | `current_avg_return - intraday_high` (pp, `<= 0`). Session history must exist for this to be meaningful. |
| `recovery_from_low` | `float` | `current_avg_return - intraday_low` (pp, `>= 0`). Session history must exist for this to be meaningful. |
| `breadth_now` | `float` | Current `up_percent` value |
| `breadth_5m_ago` | `Optional[float]` | `up_percent` at the bar nearest to 5 minutes before the last bar (computed from history) |
| `breadth_15m_ago` | `Optional[float]` | `up_percent` at the bar nearest to 15 minutes before the last bar |
| `breadth_change_5m` | `Optional[float]` | `breadth_now - breadth_5m_ago` (pp) |
| `breadth_change_15m` | `Optional[float]` | `breadth_now - breadth_15m_ago` (pp) |
| `state` | `str` | One of: `TRENDING_UP`, `TRENDING_DOWN`, `REVERSING_DOWN`, `RECOVERING_UP`, `MIXED` (spec 12) |
| `small_sample` | `bool` | `True` when `valid_stocks < 5` (spec 24) |
| `etf` | `List[ETFComparison]` | ETF comparison entries (spec 17). Empty list if no ETF mappings or no data. |
| `history` | `Optional[pandas.DataFrame]` | Theme return series (bars × symbols). `None` if no history computed. Excluded from `to_json()`. |

### `ThemeMetrics.to_json()` (spec section 28)

Returns a dict with exactly these keys (all numeric values rounded as shown):

```json
{
  "theme": "theme_name",
  "average_return": round(avg, 3),
  "median_return": round(med, 3),
  "up_percent": round(up, 1),
  "strong_up_percent": round(strg, 1),
  "change_from_open": round(acfromopen, 3),
  "intraday_high": round(ih, 3),
  "intraday_low": round(il, 3),
  "reversal_from_high": round(rfh, 3),
  "recovery_from_low": round(rl, 3),
  "breadth_now": round(bn, 1) if bn is not None else None,
  "breadth_momentum_15m": round(bc15, 1) if bc15 is not None else None,
  "state": state,
  "valid_stocks": valid,
  "total_stocks": total
}
```

## ETFComparison (spec section 17)

| Field | Type | Description |
|-------|------|-------------|
| `etf` | `str` | ETF ticker symbol |
| `etf_return` | `Optional[float]` | ETF return `(price - prev_close) / prev_close * 100`. `None` when ETF data unavailable |
| `basket_return` | `float` | Theme equal-weight average return (from `average_return`) |
| `divergence` | `Optional[float]` | `etf_return - basket_return` in percentage points. `None` when ETF return is `None` |

## Alert (spec section 27)

| Field | Type | Description |
|-------|------|-------------|
| `kind` | `str` | One of: `"Breadth Breakout"`, `"Breadth Collapse"`, `"Strong Reversal"`, `"Strong Recovery"`, `"Top 3 Entry"`, `"Top 3 Exit"` |
| `theme` | `str` | Theme name |
| `message` | `str` | Human-readable description of the observed fact |
| `severity` | `str` | `"info"` or `"warn"` |

## Database schema (SQLite, spec sections 25-26)

### `sector_snapshots`

| Column | Type | Constraints |
|---------|------|-------------|
| `session_date` | `TEXT` | NOT NULL |
| `timestamp` | `TEXT` | NOT NULL |
| `theme` | `TEXT` | NOT NULL |
| `total_stocks` | `INTEGER` | |
| `up_stocks` | `INTEGER` | |
| `down_stocks` | `INTEGER` | |
| `flat_stocks` | `INTEGER` | |
| `up_percent` | `REAL` | |
| `down_percent` | `REAL` | |
| `average_return` | `REAL` | |
| `median_return` | `REAL` | |
| `average_change_from_open` | `REAL` | |
| `intraday_high` | `REAL` | |
| `intraday_low` | `REAL` | |
| `breadth` | `REAL` | |
| `state` | `TEXT` | |
| `PRIMARY KEY` | `(timestamp, theme)` | |
| `INDEX` | `(theme, session_date)` | |

### `stock_snapshots`

| Column | Type | Constraints |
|---------|------|-------------|
| `session_date` | `TEXT` | NOT NULL |
| `timestamp` | `TEXT` | NOT NULL |
| `symbol` | `TEXT` | NOT NULL |
| `price` | `REAL` | |
| `previous_close` | `REAL` | |
| `today_open` | `REAL` | |
| `change_vs_close` | `REAL` | |
| `change_vs_open` | `REAL` | |
| `volume` | `INTEGER` | |
| `intraday_high` | `REAL` | |
| `intraday_low` | `REAL` | |
| `PRIMARY KEY` | `(timestamp, symbol)` | |
| `INDEX` | `(symbol, session_date)` | |

### Notes

- `session_date` is the ET date derived from `md.asof.date()` (or the current ET date if `md.asof` is `None`)
- `INSERT OR REPLACE` on `(timestamp, theme)` / `(timestamp, symbol)` — same timestamp replaces previous row
- Indexes support queries like "all snapshots for theme X in session Y"