# PROJECT_OVERVIEW.md

## Project identity

**Sector Radar** is a desktop market-structure scanner for U.S. equities.

**Problem it solves:** Shows what is happening inside market sectors/themes right now during the first 60–90 minutes after market open.

**V1 does NOT:** Predict the market, recommend stocks, or operate as a real-time tick-level feed.

## Core concept

The central object is the **THEME / SECTOR**. Stocks are the underlying constituents.

The user should primarily think:

```text
What themes are moving?

How broad is the move?

Is the move strengthening?

Is it reversing?

Is it recovering?

Is the move concentrated in a few stocks?
```

Rather than:

```text
Which individual stock should I buy?
```

## What V1 currently displays

### Panels (sidebar-toggleable)

- **TOP UP**: Themes ranked by average return (descending). Columns: Theme, Avg %, vs Open, Up %, Strong Up %, Stocks, State
- **TOP DOWN**: Themes ranked by average return (ascending). Columns: Theme, Avg %, vs Open, Down %, Strong Down %, Stocks, State
- **REVERSALS**: Themes that gave back >= threshold from intraday peak. Columns: Theme, Intraday Peak, Current, Giveback, Breadth (up %), State
- **RECOVERIES**: Themes that recovered >= threshold from intraday low. Columns: Theme, Intraday Low, Current, Recovery, Breadth (up %), State

### Supplemental sections (always visible when enabled)

- **BREADTH MOMENTUM**: Up% now vs 5m ago vs 15m ago, with Δ5m and Δ15m in pp. Sorted by Δ15m descending.
- **ETF / BASKET DIVERGENCE**: Theme equal-weight basket return vs ETF return, difference in pp. Shown as informational only — NOT a trading recommendation.
- **Composite score** (V1.1 experimental, off by default): Min-max normalized blend of breadth (0.40), avg return (0.30), median return (0.20), volume (0.10, log10). For reference only; raw panels are the source of truth.
- **All themes table**: Expandable table with every theme's key metrics (avg, median, up/down/strong%, vs open, high/giveback/low/recovery, Δ5m/Δ15m, state, small-sample flag)
- **Theme detail page**: Selectable from sidebar. Shows key metric cards, constituent table (sortable by return/v/open/volume/dist-to-high), 3 Plotly charts (return from open, breadth, avg vs median), ETF comparison where available, session snapshot history from SQLite

### Market status badge

- **OPEN**: 🟢 OPEN — metrics are live during regular session (09:30–16:00 ET)
- **PREMARKET**: 🟠 PRE-MARKET — metrics populate after 09:30 ET; pre-market prices are NOT mixed into session calculations
- **CLOSED**: ⚪ CLOSED — final session data remains available; no new data appended
- **WEEKEND / HOLIDAY**: ⚪ WEEKEND / 🔴 HOLIDAY — no session data for the day; "Market closed — showing last session" or "Market closed — no session data"

### Data freshness

- yfinance free data is delayed ~15 minutes (not tick-by-tick real-time)
- The "Data as of" timestamp is always shown in ET
- A "delayed" notice appears in the header when the age of the data exceeds the stale-warn threshold (default 20 min) and the market is open

## What V1 does NOT do

- Make any buy/sell recommendations (the AI layer, V2, is separate and analytical only)
- Use true real-time tick data
- Backtest historical patterns (historical data structure is persisted for V2 research, but no UI backtesting)
- Detect multi-timeframe patterns automatically (breadth momentum 5m/15m is shown, but pattern detection is not automated)
- Integrate with a real-time data provider (only yfinance is implemented; the provider interface is abstracted for V2)
- Run fully auto without user interaction (data must be fetched on refresh, UI rerenders)

## Architecture overview

```text
app.py                                          Entry point + orchestrator
  │
  ├── config/         themes.yaml + settings.yaml  (editable without Python)
  │
  ├── data/           yfinance provider + SQLite
  │    └─ snapshot persistence for V2 research
  │
  ├── engine/         pure calculation engines
  │    │── price_engine.py          stock metrics
  │    │── breadth_engine.py        theme breadth
  │    │── reversal_engine.py       history / reversal / recovery / state
  │    │── sector_engine.py         per-theme orchestration
  │    │── ranking_engine.py        rankings + optional composite
  │    └─ alerts.py                 cross-refresh alerts
  │
  ├── ui/               Streamlit rendering only
  │    │── dashboard.py             4 panels + momentum + ETF + detail
  │    │── sector_detail.py         theme detail page
  │    │── charts.py                Plotly figures
  │    └─ formatting.py             pre-format strings + Styler.map colors
  │
  ├── utils/          config, logging, market hours
  │
  ├── tests/          39 unit tests (synthetic data, no network)
  │
  └── README.md         project entry point
```

## Repository map

Please see AI_CONTEXT.md for the full repository map and module documentation.

## Start

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Tests

```bash
python -m pytest tests/ -q
```

39 tests pass, covering price calculations, breadth classification, reversal/recovery state, multi-theme orchestration, ranking, composite scores, and snapshot persistence. All tests use synthetic data — no yfinance or network access required.

## Configuration

- **themes.yaml** (`config/themes.yaml`): Theme definitions — tickers, ETF mappings. Edit without touching Python.
- **settings.yaml** (`config/settings.yaml`): Thresholds (flat, strong, reversal, recovery), UI settings (top_n, min_theme_size, time_window_minutes, small_sample warning), alert thresholds, composite weights, refresh interval, data interval.

Both files are in `config/` and can be edited without Python changes.

## Known limitations

- yfinance is not a dedicated real-time market-data feed; data is delayed ~15 min
- Theme definitions are configuration-dependent
- Breadth is only as representative as the configured constituents
- ETF divergence depends on available ETF mappings and data
- Historical analysis structure is persisted for V2 but no UI backtesting exists
- AI-ready JSON export exists but AI analysis is not currently part of the quantitative engine

## Current project status

- **Version:** V1 / MVP
- **Status:** Feature complete
- **Tests:** 39 passing
- **Live yfinance pipeline:** verified
- **Dashboard:** verified (all 4 panels, momentum, ETF, detail page)
- **SQLite persistence:** verified
- **Alerts:** verified
- **AI JSON export:** verified