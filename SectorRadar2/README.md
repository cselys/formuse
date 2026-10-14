# Sector Radar

A market-structure scanner for U.S. equities that monitors sectors/themes during the first 60–90 minutes after market open.

![Sector Radar Dashboard](shot_final.png)

## What it does

Sector Radar identifies sectors/themes that are broadly moving up, moving down, reversing, or recovering during the first hour of the U.S. market session. It shows whether moves are broad or concentrated in a few stocks.

**V1 does NOT:** predict the market, recommend stocks, or use real-time tick data.

## Features (V1)

- **TOP UP** — Themes ranked by average return, with breadth and strong-up percentage
- **TOP DOWN** — Themes ranked by average return (most negative first)
- **REVERSALS** — Themes that gave back ground from their intraday peak
- **RECOVERIES** — Themes that recovered toward zero from their intraday low
- **BREADTH MOMENTUM** — Up% now vs 5m and 15m ago, showing if participation is expanding or contracting
- **ETF / BASKET DIVERGENCE** — Theme equal-weight basket vs ETF proxy (informational only)
- **Theme detail page** — Constituents, 3 Plotly charts, ETF comparison, session snapshot history
- **Market status** badge (OPEN/PREMARKET/CLOSED/WEEKEND/HOLIDAY)
- **Auto-refresh** at configurable intervals (30s/60s/120s/300s)
- **Alerts** (breadth breakout/collapse, strong reversal/recovery, Top-3 entry/exit)
- **Full theme table** with all metrics
- **Small-sample warning** (⚠️ when valid stocks < 5)

## Architecture

The app uses a modular architecture:

- **`config/`** — themes.yaml + settings.yaml (editable without Python)
- **`data/`** — yfinance provider + SQLite persistence
- **`engine/`** — pure calculation engines (no Streamlit)
- **`ui/`** — Streamlit rendering only
- **`utils/`** — config, logging, market hours
- **`models/`** — data schemas (dataclasses)
- **`tests/`** — 39 unit tests (synthetic data, no network)
- **`app.py`** — orchestrator + entry point

## Installation

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Running tests

```bash
python -m pytest tests/ -q
```

39 tests pass, covering price calculations, breadth classification, reversal/ recovery state, multi-theme orchestration, ranking, composite scores, and snapshot persistence.

## Configuration

- Edit `config/themes.yaml` to add/remove themes and tickers (no Python changes needed)
- Edit `config/settings.yaml` to adjust thresholds, UI settings, and alert thresholds
- Both files are referenced via `SECTOR_RADAR_SETTINGS` and `SECTOR_RADAR_THEMES` env vars (optional)

## Data provider

Uses **yfinance** — free data, delayed ~15 minutes, not tick-level real-time. The UI always shows the `Data as of HH:MM ET` timestamp and a delayed notice when appropriate.

## Documentation

See the `docs/` folder for comprehensive documentation:

- `AI_CONTEXT.md` — project identity + architecture + invariants
- `PROJECT_OVERVIEW.md` — high-level description + features
- `ARCHITECTURE.md` — text diagram + component responsibilities
- `DATA_FLOW.md` — complete data path from yfinance to UI
- `DATA_MODEL.md` — StockSnapshot + ThemeMetrics field definitions
- `CALCULATIONS.md` — exact formulas for all metrics
- `THEME_DEFINITIONS.md` — all 31 configured themes with constituent counts
- `RANKINGS.md` — separate rankings + optional composite score
- `REVERSAL_RECOVERY.md` — intraday high/low, reversal, recovery, state
- `ETF_DIVERGENCE.md` — ETF vs basket comparison
- `ALERTS.md` — breadth breakout/collapse, strong reversal/recovery, Top-3
- `DATA_PROVIDER.md` — yfinance provider abstraction + rate-limit handling
- `DATABASE.md` — SQLite schema + snapshot behavior
- `UI.md` — dashboard layout + panel descriptions + state badges
- `CONFIGURATION.md` — where config lives + how to edit
- `TESTING.md` — how to run tests + test organization
- `OPERATIONS.md` — runbook: start, tests, troubleshooting, market-open checklist
- `LIMITATIONS.md` — what the MVP does NOT guarantee
- `PROJECT_STATUS.md` — baseline checkpoint + verified items
- `ROADMAP.md` — V1 complete / V1.1 possible / V2 possible / Future

## License

This project is for analytics/research purposes only. It does not provide buy/sell recommendations.