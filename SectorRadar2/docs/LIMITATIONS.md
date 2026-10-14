# LIMITATIONS.md

## Data source limitations

- **yfinance is not a dedicated institutional real-time market-data feed**: Data is delayed approximately 15 minutes and is not tick-by-tick real-time. The UI always shows the `Data as of HH:MM ET` timestamp and a delayed notice when appropriate.
- **Missing / halted stocks**: If a ticker has no data for the session (delisted, halted, typo in theme config), it is gracefully excluded from calculations and counted in `missing_stocks`. The theme calculation still proceeds with valid stocks only.
- **Market hours**: The app is designed for the regular session (09:30–16:00 ET). Pre-market and post-market data are handled but not mixed into the main session metrics (spec 22).
- **Weekends and holidays**: No session data is available for non-trading days. The market status badge shows `WEEKEND` or `HOLIDAY`, and the app displays "Market closed — no session data" or "Market closed — showing last session."

## Theme definition limitations

- **Theme definitions are configuration-dependent**: The set of stocks in each theme comes from `config/themes.yaml`. If a configured ticker has no data, it is counted as `missing_stocks` but the theme still runs with whatever valid stocks exist.
- **A stock may belong to multiple themes**: This is by design (e.g., MU is in Semiconductor, Memory, AI / Compute). The UI displays this correctly.
- **Small themes**: Themes with fewer than 5 valid stocks get a `⚠️ small` flag. The flag is visible but the theme is not excluded from calculations or rankings.

## Breadth representation limitations

- **Breadth is only as representative as the configured constituents**: If only 3 out of 10 possible stocks in a theme are tradable, the `up_percent` reflects those 3 only. The `missing_stocks` count is always shown (`{valid}/{total}`) so the user sees the sample size.
- **Flat threshold ±0.10%**: Very small moves (within ±0.10%) are classified as FLAT. This prevents noise from tiny fluctuations from being counted as meaningful direction.

## ETF divergence limitations

- **ETF divergence depends on available ETF mappings and data**: If the ETF ticker has no intraday data or no previous close, the divergence entry shows `—` for all fields.
- **ETF ≠ constituents**: The ETF is a market-capitalization-weighted proxy and is NOT one of the constituent stocks. The basket return is the equal-weight average of constituents only.

## Historical analysis limitations

- **Historical data structure is persisted for V2**: SQLite snapshots store timestamped theme metrics, but there is no UI backtesting or pattern detection UI in V1.
- **Breadth momentum (5m/15m)** is computed from the current session's history only — it does not reference past sessions' data unless manually queried from SQLite.

## AI layer limitations

- **AI-ready JSON export exists** (spec 28) but the AI layer is not currently part of the quantitative engine. The JSON is consumed by a separate AI process; it does not compute metrics.
- **No buy/sell recommendations**: The app is an analytics tool; no AI-generated trading signals are produced.

## Performance limitations

- **Refresh interval**: The default auto-refresh is 60 seconds. For real-time trading use cases, a dedicated market-data feed would be required.
- **Symbol count**: The universe of 194 tickens + 21 ETFs is feasible for batch yfinance downloads (~30s). A much larger universe would require a different data provider.
- **SQLite**: The persistence file (`data/sector_radar.db`) grows with each refresh cycle. It is not pruned automatically; V2 may implement cleanup.

## What the MVP does NOT guarantee

- Real-time / tick-level data
- Predictive / forward-looking statements
- Automatic pattern detection over multiple timeframes
- Integration with brokers or execution systems
- Coverage of all publicly traded stocks (only the configured universe)
- Stability under extreme market volatility (the app may briefly show stale or missing data)