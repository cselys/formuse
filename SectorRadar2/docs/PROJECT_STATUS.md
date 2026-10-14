# PROJECT_STATUS.md

## Version: V1 / MVP

## Status: Feature complete

## Tests: 39 passing

## Live yfinance pipeline: verified

## Dashboard: verified (all 4 panels, momentum, ETF comparison, detail page)

## SQLite: verified (snapshot roundtrip, read/write)

## Alerts: verified (breadth breakout/collapse, strong reversal/recovery, Top-3 entry/exit)

## AI JSON export: verified (theme_metrics.to_json() shape per spec 28)

---

## Verified

- All 39 unit tests pass (synthetic data, no network)
- yfinance data pipeline works with 194 tickers + 21 ETFs
- All 4 ranking panels render correctly (TOP UP, TOP DOWN, REVERSALS, RECOVERIES)
- Breadth momentum table with Δ5m/Δ15m columns
- ETF divergence table with pp values
- Theme detail page with constituents, charts, ETF comparison
- Market status badge (OPEN/PREMARKET/CLOSED/WEEKEND/HOLIDAY)
- Auto-refresh at configurable intervals (30s/60s/120s/300s)
- Small-sample warning (⚠️ when valid < 5)
- Stale-data notice when data age > 20 min
- SQLite snapshot persistence (roundtrip verified)
- Formatting: signed/plain percentages, state colors, stock cells

---

## Not yet verified in a full live market session

- Extended session hours (beyond 16:00 ET) — the app is designed for 09:30–16:00 ET
- Real market-hour auto-refresh over many hours
- Edge cases with heavily halted or delisted tickers
- Concurrent user access (Streamlit single-user by default)

---

## Known limitations

- yfinance is not a dedicated real-time market-data feed (data delayed ~15 min)
- Theme definitions are configuration-dependent
- Breadth is only as representative as the configured constituents
- ETF divergence depends on available ETF mappings/data
- Historical analysis structure is persisted for V2 but no UI backtesting exists
- AI-ready JSON does not mean AI analysis is currently part of the quantitative engine
- The composite score is OFF by default and never the primary ranking

---

## Do not change casually

These interfaces and semantics must not be changed without updating all downstream code:

- `config/themes.yaml` structure (theme name → tickers + etf)
- `config/settings.yaml` key structure (flat_threshold, strong_move_threshold, reversal_threshold, recovery_threshold, etc.)
- `MarketData` dataclass fields (source, interval, fetched_at, asof, bars, daily, failed)
- `StockSnapshot` fields (symbol, timestamp, previous_close, today_open, current_price, intraday_high, intraday_low, change_vs_previous_close, change_vs_open, distance_from_intraday_high, distance_from_intraday_low, volume, is_valid, issue, direction)
- `ThemeMetrics` fields (all 35 fields as documented in DATA_MODEL.md)
- `MarketDataProvider` abstract interface (get_intraday_prices, get_daily_reference_prices, fetch_session)
- `classify_direction()`, `compute_breadth()`, `classify_state()` function signatures
- `Styler.map` vs `Styler.format` behavior in Streamlit (pre-format strings + map colors)
- `st.fragment(run_every=Ns)` auto-refresh mechanism
- Alert threshold defaults in `config/settings.yaml`