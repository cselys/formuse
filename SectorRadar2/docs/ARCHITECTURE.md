# ARCHITECTURE.md

## Text architecture diagram

```text
app.py                                          Entry point + orchestrator
  │
  ├── config/         themes.yaml + settings.yaml  (editable without Python)
  │
  ├── data/           market data layer
  │   ├── provider_base.py                      MarketDataProvider (abstract)
  │   ├── yfinance_provider.py                  YFinanceProvider(MarketDataProvider)
  │    │   • batched yf.download + retry/backoff
  │    │   • tz-conversion UTC -> America/New_York
  │    │   • daily reference: prev close + today's open
  │    │   • failed symbol detection
  │   └─ cache.py                                 SnapshotStore(SQLite)
  │       └─ sector_snapshots  (timestamp, theme, ...)
       └─ stock_snapshots      (timestamp, symbol, ...)
  │
  ├── engine/         pure calculation engines (no I/O, no Streamlit)
  │   ├── price_engine.py      stock-level metrics (spec 8)
  │   ├── breadth_engine.py      theme breadth aggregation (spec 9-11)
  │   ├── reversal_engine.py   intraday high/low, reversal, recovery (spec 12-14)
  │   ├── sector_engine.py      per-theme orchestration (spec 9-17)
  │   ├── ranking_engine.py      rankings + optional composite (spec 15-16)
  │   └─ alerts.py                  cross-refresh alert detection (spec 27)
  │
  ├── ui/               Streamlit rendering only (no calculation logic)
  │   ├── dashboard.py      main dashboard panels + rendering
  │   ├── sector_detail.py  theme detail page + constituents + charts
  │   ├── charts.py               Plotly figures (return, breadth, avg/median)
  │   └─ formatting.py    shared formatting (pre-format strings + Styler.map colors)
  │
  ├── utils/            config, logging, market hours
  │   ├── config.py         load_settings(), load_themes(), get_setting()
  │   ├── logging.py      file + console handler
  │   └─ market_hours.py  NYSE session, market_status(), premarket_window()
  │
  ├── models/           data schemas (plain dataclasses)
  │   └─ schemas.py       StockSnapshot, ThemeMetrics, ETFComparison, Alert
  │
  ├── tests/            39 unit tests (synthetic data, no network)
  │
  └── README.md         project entry point
```

## Component responsibilities

### app.py
- Loads config (themes.yaml + settings.yaml) via `utils.config`
- Renders sidebar (controls + toggles) via `ui.dashboard.render_sidebar()`
- On auto-refresh (`st.fragment run_every=Ns`):
  - Fetches data via `data.YFinanceProvider.fetch_session()`
  - Runs engine pipeline via `engine.run_sector_engine()`
  - Persists snapshots via `data.SnapshotStore.save_snapshots()`
  - Renders dashboard via `ui.dashboard.render_dashboard()`
- Else: shows "Refresh now" button
- `st.set_page_config()` must be the first Streamlit command

### data/
- **provider_base.py**: Abstract `MarketDataProvider` with `get_intraday_prices()`, `get_daily_reference_prices()`, `fetch_session()`
- **yfinance_provider.py**: `YFinanceProvider(MarketDataProvider)`
  - `get_intraday_prices(symbols, interval, start, end)` — batched `yf.download`, retry/backoff
  - `get_daily_reference_prices(symbols)` — 15d 1d download, prev close + today's open
  - `fetch_session()`: combines both, detects failed symbols, returns `MarketData`
- **cache.py**: `SnapshotStore(SQLite)`
  - `save_snapshots(session_date, theme_metrics, stock_snapshots)` — INSERT OR REPLACE
  - `load_sector_history(theme, session_date)` — read back for V2 research
  - `load_stock_history(symbol, session_date)`
  - `recent_sessions(limit)`

### engine/
- All engines are **pure functions** of the data — no Streamlit, no I/O
- Input: `MarketData` + `dict` of `StockSnapshot` + `dict` of theme config
- Output: `ThemeMetrics` objects (or rankings/alerts)
- No `import streamlit` — UI is separate

### ui/
- **dashboard.py**: `render_dashboard(ctx)` — the main entry point for rendering
  - Renders header, status badge, alerts
  - Renders 4 panels (TOP UP, TOP DOWN, REVERSALS, RECOVERIES) via `_panel()`
  - Renders breadth momentum table
  - Renders ETF divergence table (if enabled)
  - Renders composite score expander (if enabled)
  - Renders "All themes" expandable table
  - Renders theme detail page via `ui.sector_detail.render_theme_detail()`
- **sector_detail.py**: `render_theme_detail(ctx)` — key metric cards, constituent table, 3 Plotly charts, ETF comparison, snapshot history
- **charts.py**: `theme_return_chart()`, `breadth_chart()`, `avg_vs_median_chart()`
- **formatting.py**: Shared formatting helpers (pre-format strings; `Styler.map` for font colors only; `Styler.format` is NOT applied — Streamlit does not support it)

### utils/
- **config.py**: `load_settings()`, `load_themes()`, `all_symbols()`, `get_setting()` — reads YAML + env overrides
- **logging.py**: File handler (`logs/sector_radar.log`) + console handler (WARNING+)
- **market_hours.py**: `market_status(now)` → dict(status, session_day, session_open, session_close, minutes_since_open, early_close, note), `premarket_window(now)`

### models/
- **schemas.py**: `StockSnapshot`, `ThemeMetrics`, `ETFComparison`, `Alert` — plain dataclasses, no ORM, no I/O

### tests/
- **conftest.py**: `make_bars()`, `make_daily()`, `build_metrics()`, `settings` fixture
- **test_price.py**: 10 tests: price metrics, missing data, staleness, daily_reference
- **test_breadth.py**: 7 tests: classification, strong breadth, boundary, empty input, missing stocks, change_from_open
- **test_reversal.py**: 10 tests: history analysis, state labeling, breadth momentum, min_history_bars gate, empty history, state cases
- **test_sector.py**: 13 tests: multi-theme shared tickers, missing stocks do not break, ETF excluded from breadth, small-sample flag, ranking ordering, composite score bounds, to_json shape, snapshot store roundtrip

## Important invariants

These must not be broken without updating all downstream code:

- Theme membership is configurable via `config/themes.yaml` — adding/removing tickers does not require code changes
- A stock MAY belong to multiple themes (e.g., MU is in Semiconductor, Memory, AI / Compute)
- Missing data must be handled gracefully: invalid stocks are excluded from percentages, counted in `missing_stocks`, never crash a calculation
- Theme calculations are deterministic given the same data and settings
- The AI/analytical layer must NOT replace the quantitative engine — JSON export (spec 28) is consumed by AI, but calculations originate in the Python engine
- yfinance data is delayed ~15 min, not tick-by-tick real-time. The UI always shows the data timestamp and a "delayed" notice
- The composite score is OFF by default and never the primary ranking
- Snapshots in SQLite are keyed by (timestamp, theme) / (timestamp, symbol); same timestamp/theme replaces previous (INSERT OR REPLACE)
- The dashboard auto-refresh uses `st.fragment(run_every=Ns)`; the interval is configurable in the sidebar
- The breadth momentum (5m/15m) is computed from the theme return series, using the nearest bar to the target window

## Repository map

Please see AI_CONTEXT.md for the full repository map and module documentation.