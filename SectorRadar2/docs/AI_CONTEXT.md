# AI_CONTEXT.md

## Project identity

**Sector Radar** is a market-structure scanner for U.S. equities that monitors sectors/themes during the first 60-90 minutes after market open and identifies:

- Sectors/themes showing broad upside strength
- Sectors/themes showing broad downside weakness
- Sectors/themes that opened strong and are now reversing downward
- Sectors/themes that opened weak and are now recovering upward
- Broad moves vs. moves driven by only a few large stocks
- Changes in sector breadth over time

**It does NOT predict the market.** It shows what is happening inside market sectors/themes right now.

**It is NOT a stock screener** and does not recommend which individual stocks to buy. The central object is the THEME/SECTOR, not individual stocks.

## What V1 currently does

The V1 dashboard can display:

- **TOP UP**: Themes ranked by average return (descending), with up% and strong up% alongside
- **TOP DOWN**: Themes ranked by average return (ascending), with down% and strong down% alongside
- **REVERSALS**: Themes that opened higher but gave back ground from their intraday peak
- **RECOVERIES**: Themes that opened lower but recovered toward zero
- **BREADTH MOMENTUM**: Up% now vs 5m ago vs 15m ago, with delta columns
- **ETF/BASKET DIVERGENCE**: Theme equal-weight basket return vs ETF return, shown as divergence in percentage points
- **Full theme table**: All themes with average return, median return, up/down/strong percentages, vs open, high/low/giveback/recovery, breadth momentum, state
- **Theme detail page**: Key metrics cards, constituent table (sortable), 3 Plotly charts (return from open, breadth, avg vs median), ETF comparison, session snapshot history
- **Market status**: OPEN/PREMARKET/CLOSED/WEEKEND/HOLIDAY with badge
- **Auto-refresh**: Configurable interval (30s/60s/120s/300s) via `st.fragment(run_every=...)`
- **Data delay notice**: yfinance data is delayed (~15 min), timestamp always shown

**V1 does NOT:**

- Make any buy/sell recommendations (AI layer is separate and analytical only)
- Use tick-by-tick real-time data (yfinance is delayed ~15 min, clearly disclosed)
- Backtest historical patterns (historical data structure is persisted for V2, but no backtesting UI)
- Detect patterns automatically over multiple timeframes (breadth momentum 5m/15m is shown, but pattern detection is not automated)
- Integrate with real-time data providers (only yfinance is implemented; plugin interface is ready but not wired)
- Run fully auto without user interaction (data must be fetched, UI refreshed)

## Architecture

### Major components and their responsibilities

```text
app.py                                          Entry point + orchestrator
  └─ loads config (themes.yaml + settings.yaml)
  ├─ renders sidebar (controls + toggles)
  ├─ on auto-refresh (st.fragment run_every=Ns):
  │    │    fetches data via YFinanceProvider
  │    │    runs engine pipeline
  │    │    renders dashboard
  │    │    persists snapshots to SQLite
  │    └─ else: shows "Refresh now" button
  └─ renders: header, 4 panels, breadth momentum,
              ETF divergence, composite (opt), full table, detail

data/                                           Market data layer
  ├─ provider_base.py                           Abstract MarketDataProvider
  ├─ yfinance_provider.py                       YFinanceProvider(MarketDataProvider)
  │    └─ batched yf.download + retry/backoff
  │    └─ tz-conversion UTC -> America/New_York
  │    └─ daily reference (prev close + today's open)
  │    └─ failed symbol detection
  └─ cache.py                                    SnapshotStore(SQLite)
       └─ sector_snapshots(timestamp, theme, ...)
       └─ stock_snapshots(timestamp, symbol, ...)

engine/                                         Pure calculation engines (no I/O, no Streamlit)
  ├─ price_engine.py                            Stock-level metrics (spec 8)
  │    └─ build_stock_metrics(), build_all_stock_metrics()
  │    └─ _pct(), clean_bars(), daily_reference()
  ├─ breadth_engine.py                          Theme breadth aggregation (spec 9-11)
  │    └─ classify_direction(), compute_breadth()
  ├─ reversal_engine.py                         Intraday high/low, reversal, recovery (spec 12-14)
  │    └─ theme_return_series(), analyze_history()
  │    └─ classify_state()                     // reversal/recovery/trend/mixed
  ├─ sector_engine.py                           Per-theme orchestration (spec 9-17)
  │    └─ build_theme_metrics(), run_sector_engine()
  ├─ ranking_engine.py                          Rankings + optional composite (spec 15-16)
  │    └─ top_up(), top_down(), broadest_up(), etc.
  │    └─ composite_scores()                     // min-max normalized, off by default
  └─ alerts.py                                  Cross-refresh alert detection (spec 27)
       └─ detect_alerts(), top3_by_return()

ui/                                             Streamlit rendering only (no calculation logic)
  ├─ dashboard.py                               Main dashboard panels + rendering
  ├─ sector_detail.py                           Theme detail page
  ├─ charts.py                                  Plotly figures (return, breadth, avg/median)
  └─ formatting.py                              Shared formatting helpers (no Styler.format —
  │    pre-format strings + Styler.map for font colors)

utils/                                          Utilities, config, logging, market hours
  ├─ config.py                                  load_settings(), load_themes(), get_setting()
  ├─ logging.py                                 Rotating file + console handler
  └─ market_hours.py                            NYSE calendar, session_day, market_status()

models/                                         Data schemas (plain dataclasses)
  └─ schemas.py                                 StockSnapshot, ThemeMetrics, ETFComparison, Alert

tests/                                          39 unit tests covering:
  ├─ test_price.py                              // per-stock metrics, missing data, staleness
  ├─ test_breadth.py                            // classification, strong breadth, boundary
  ├─ test_reversal.py                           // history analysis, state labeling
  ├─ test_sector.py                             // multi-theme, missing stocks, ETF exclusion,
  │    │                                        rankings, composite, snapshot store
  └─ test_price.py                              // daily_reference, all metrics missing symbol

## Repository map

```
SectorRadar/
├── app.py                                      Entry point + orchestrator
├── config/
│   ├── themes.yaml                             Theme universe (31 themes, 194 tickers + 21 ETFs)
│   └── settings.yaml                           All configurable thresholds + UI settings
├── data/
│   ├── provider_base.py                        Abstract MarketDataProvider
│   ├── yfinance_provider.py                    YFinanceProvider(MarketDataProvider)
│   └── cache.py                                SnapshotStore(SQLite) — sector_snapshots + stock_snapshots
├── engine/
│   ├── price_engine.py                         Stock metrics (per spec 8)
│   ├── breadth_engine.py                       Breadth aggregation (spec 9-11)
│   ├── reversal_engine.py                      History / reversal / recovery / state (spec 12-14)
│   ├── sector_engine.py                        Per-theme orchestration (spec 9-17)
│   ├── ranking_engine.py                       Rankings + composite (spec 15-16)
│   └── alerts.py                               Cross-refresh alert detection (spec 27)
├── models/
│   └── schemas.py                              StockSnapshot, ThemeMetrics, ETFComparison, Alert
├── ui/
│   ├── dashboard.py                            Main dashboard rendering (4 panels, momentum, ETF, detail)
│   ├── sector_detail.py                        Theme detail page + constituent table + charts
│   ├── charts.py                               Plotly figures (return, breadth, avg/median)
│   └── formatting.py                           Shared formatting (pre-format strings; Styler.map for colors only)
├── utils/
│   ├── config.py                               load_settings(), load_themes(), get_setting()
│   ├── logging.py                              File + console handler
│   └─ market_hours.py                          NYSE session, market_status(), premarket_window()
├── tests/
│   ├── test_price.py                           // 10 tests: price metrics, missing data, staleness
│   ├── test_breadth.py                         // 7 tests: classification, strong breadth, boundaries
│   ├── test_reversal.py                        // 9 tests: history analysis, state labeling
│   ├── test_sector.py                          // 13 tests: multi-theme, missing stocks,
  │    │                                        ETF exclusion, rankings, composite, snapshot store
  └─ conftest.py                                Shared fixtures (make_bars, make_daily, build_metrics, settings)
├── config/
│   ├── themes.yaml                             31 themes with tickers + ETF mappings
│   └── settings.yaml                           Thresholds, UI settings, alert settings, composite weights
├── README.md                                   Project overview + startup guide
├── docs/                                       (created in this task)
└── requirements.txt                           streamlit, yfinance, pandas, numpy, plotly, PyYAML, pandas-market-calendars, pytest
```

## Core concepts (precise definitions)

- **stock metric**: per-spec change_vs_previous_close, change_vs_open, intraday_high/low, distance_from_intraday_high/low, volume, direction (UP/DOWN/FLAT)
- **theme**: a configured group of tickers (from config/themes.yaml). A stock may belong to multiple themes.
- **constituent**: a ticker that is configured into a theme. ETFs are NOT constituents (they are comparison only).
- **breadth**: percentage of valid stocks in a theme that are UP (above flat_threshold), DOWN (below -flat_threshold), or FLAT (within +/-flat_threshold). missing_stocks = configured - valid.
- **average return**: arithmetic mean of change_vs_previous_close across valid stocks in the theme
- **median return**: median of change_vs_previous_close across valid stocks
- **strong up**: change_vs_previous_close > strong_move_threshold (default 1.0%)
- **strong down**: change_vs_previous_close < -strong_move_threshold
- **up %**: valid_stocks with change > flat_threshold / valid_count * 100
- **down %**: valid_stocks with change < -flat_threshold / valid_count * 100
- **strong up %**: valid_stocks with change > strong_threshold / valid_count * 100
- **strong down %**: valid_stocks with change < -strong_threshold / valid_count * 100
- **breadth momentum**: up% now vs 5m ago vs 15m ago, with delta in pp (computed from theme return series)
- **theme state** (spec 12):
  - TRENDING_UP: avg_return > 0 & vs_open > 0 & up% > breadth_threshold
  - TRENDING_DOWN: avg_return < 0 & vs_open < 0 & down% > breadth_threshold
  - REVERSING_DOWN: session history has intraday high, reversal_from_high <= -reversal_threshold & up% < 50
  - RECOVERING_UP: session history has intraday low, recovery_from_low >= recovery_threshold & avg_return < 0
  - MIXED: otherwise
- **reversal_from_high**: current intraday avg return - session intraday high (pp, <= 0)
- **recovery_from_low**: current intraday avg return - session intraday low (pp, >= 0)
- **ETF divergence**: ETF return (prev close) - theme basket return (equal-weight, pp). ETF is NOT counted as a constituent.
- **ranking**: separate rankings (not collapsed into one score):
  - top_up: average_return descending
  - top_down: average_return ascending
  - broadest_up: up_percent descending
  - broadest_down: down_percent descending
  - biggest_reversals: reversal_from_high ascending (most giveback first), filtered by threshold
  - biggest_recoveries: recovery_from_low descending (recovery > threshold), filtered by threshold
- **composite score** (spec 16, optional, NOT primary ranking):
  - min-max normalized across themes: breadth (0.40), avg_return (0.30), median_return (0.20), volume (0.10, log10 transformed)
  - Can be toggled on via settings.yaml `composite.enabled: true`

## Important invariants

These must not be broken without updating all downstream code:

- Theme membership is configurable via config/themes.yaml — adding/removing tickers does not require code changes
- A stock MAY belong to multiple themes (e.g., MU is in Semiconductor, Memory, AI / Compute)
- Missing data must be handled gracefully: invalid stocks are excluded from percentages, counted in missing_stocks, never crash a calculation
- Theme calculations are deterministic given the same data and settings
- The AI/analytical layer must NOT replace the quantitative engine — JSON export (spec 28) is consumed by AI, but calculations originate in the Python engine
- yfinance data is delayed (~15 min), not tick-by-tick real-time. The UI always shows the data timestamp and a "delayed" notice
- The composite score is OFF by default and never the primary ranking
- Snapshots in SQLite are keyed by (timestamp, theme) / (timestamp, symbol); same timestamp/theme replaces previous (INSERT OR REPLACE)
- The dashboard auto-refresh uses `st.fragment(run_every=Ns)`; the interval is configurable in the sidebar
- The breadth momentum (5m/15m) is computed from the theme return series, using the nearest bar to the target window

## Configuration

- **themes.yaml**: All theme definitions — tickers, ETF mappings, description. Editable without touching Python.
- **settings.yaml**: All thresholds (flat, strong, reversal, recovery), UI settings (top_n, min_theme_size, time_window_minutes, small_sample warning), alert thresholds, composite weights, refresh interval
- Both files are in `config/` and can be edited without Python code changes

## Database

- SQLite file at `data/sector_radar.db` (configurable via SECTOR_RADAR_DB_PATH env var)
- Tables:
  - `sector_snapshots`: timestamp, theme, total_stocks, up_stocks, down_stocks, flat_stocks, up_percent, down_percent, average_return, median_return, average_change_from_open, intraday_high, intraday_low, breadth, state, PRIMARY KEY (timestamp, theme), indexes on (theme, session_date)
  - `stock_snapshots`: timestamp, symbol, price, previous_close, today_open, change_vs_close, change_vs_open, volume, intraday_high, intraday_low, PRIMARY KEY (timestamp, symbol), indexes on (symbol, session_date)
- Snapshots are INSERT OR REPLACE on (timestamp, theme) / (timestamp, symbol) — same timestamp replaces previous
- Session date is the ET date of the data snapshot (from md.asof.date())

## Testing

- 39 pytest unit tests covering:
  - price metrics (change_vs_previous_close, open, distances, volume, missing data, duplicates, staleness, daily_reference)
  - breadth classification (up/down/flat counts, strong breadth, boundary, missing stocks excluded, change_from_open aggregation)
  - reversal/recovery analysis (history, breadth momentum, state labeling, no-history gate, empty history)
  - sector orchestration (same ticker in multiple themes, missing stocks don't break, ETF excluded from breadth, small-sample flag, rankings, composite score bounds, to_json shape, snapshot store roundtrip)
- Run: `python -m pytest tests/ -q`
- Tests use synthetic data — no network access, no yfinance

## How to modify safely

Recommended workflow:

1. Read AI_CONTEXT.md for project overview and invariants
2. Read the relevant module documentation (engine/, ui/, data/)
3. Inspect existing tests in tests/ to understand expected behavior
4. Make the smallest change possible — themes via config/themes.yaml, thresholds via settings.yaml
5. Add/update tests in tests/ to cover the new behavior
6. Run the full test suite: `python -m pytest tests/ -q`
7. Verify dashboard behavior: `streamlit run app.py`, check panels populate
8. Update documentation if invariants or interfaces change

## AI disclaimer

This project is an analytics tool, not a trading agent. The quantitative engine calculates all market metrics. An AI layer (V2) may consume the structured JSON output, but must not compute raw metrics. All AI prompts must follow the language guidelines in spec section 29: "Analyze the supplied market statistics and describe unusual sector behavior. Do not make buy/sell recommendations. Distinguish observed facts from interpretation. Mention sample size and data limitations."