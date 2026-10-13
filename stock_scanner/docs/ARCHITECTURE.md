# Stock Scanner V1.2 — System Architecture

## Overview

V1.3 adds exchange-calendar completion checks in `src/data/market_calendar.py`,
descriptive diagnostics in `src/analysis/weekly_diagnostics.py`, and weekly
snapshots/exports in `src/reporting/weekly_report.py`. Live and weekly reports
share scoring orchestration through `src/analysis/snapshot.py`. Existing
scoring formulas remain unchanged. See [WEEKLY_REPORTS.md](WEEKLY_REPORTS.md).

`stock_scanner` is a standalone, deterministic Daily/Weekly stock scanner built in Python 3.11+. It operates independently of any intraday trading engines. The architecture strictly adheres to a modular pipeline where data loading, indicator calculations, structural analysis, scoring, regime classification, and reporting are decoupled.

---

## Module Responsibilities

1. **Data Layer (`src/data/`)**:
   - `yfinance_loader.py`: Responsible for fetching adjusted historical daily OHLCV data using `yfinance` (`auto_adjust=True`), validating chronological order, removing duplicate timestamps, verifying OHLC consistency, handling MultiIndex columns, and resampling daily data into completed weekly candles (`W-FRI`) with optional `as_of_date` and `drop_partial` support to eliminate lookahead bias.

2. **Indicators Layer (`src/indicators/`)**:
   - `trend.py`: Exponential Moving Averages (EMA) and percentage slope calculations.
   - `momentum.py`: Wilder's RSI-14, MACD (line, signal, histogram), and Rate of Change (ROC-20).
   - `volatility.py`: Average True Range (ATR-14), ATR %, and percentage distance from moving averages.
   - `volume.py`: Volume Simple Moving Average and Volume Ratio.
   - `structure.py`: Swing high/low detection, Higher Highs, Higher Lows, Lower Highs, Lower Lows, consolidations, breakouts, and breakdowns.

3. **Analysis Layer (`src/analysis/`)**:
   - `daily.py`: Orchestrates daily indicator calculations and structure analysis.
   - `weekly.py`: Orchestrates weekly indicator calculations.
   - `relative_strength.py`: Computes 20-day and 60-day relative returns against market benchmarks (SPY/QQQ) and category benchmarks.
   - `regime.py`: Classifies stocks into market states (`STRONG_UPTREND`, `UPTREND`, `EARLY_UPTREND`, `BOTTOM_FORMING`, `BOTTOM_BREAKOUT`, `REVERSAL`, `REVERSAL_CONFIRMED`, `NEUTRAL`, `DOWNTREND`, `STRONG_DOWNTREND`, `AVOID`) and detects broader market regime (`MARKET_UPTREND`, `MARKET_NEUTRAL`, `MARKET_DOWNTREND`) from SPY/QQQ.
   - `historical_eval.py`: Evaluates historical signals across past scan dates against forward returns (+1D, +5D, +10D, +20D) without lookahead bias.

4. **Scoring Layer (`src/scoring/`)**:
   - `trend_score.py`: Computes deterministic 0–100 trend strength score.
   - `bottom_score.py`: Computes independent 0–100 bottoming score.
   - `reversal_score.py`: Computes independent 0–100 reversal score.
   - `entry_quality.py`: Computes independent 0–100 entry quality score evaluating extension risk and pullbacks.
   - `candidate_score.py`: Computes final 0–100 weighted candidate ranking score.

5. **AI Layer (`src/ai/`)**:
   - `gemini.py`: Optional explanation layer using Google GenAI SDK (`google-genai`) with structured Pydantic output. Strictly explanation-only; never modifies technical scores or classifications.

6. **Reporting Layer (`src/reporting/`)**:
   - `console.py`: Formatted terminal output grouped by state and top candidate rankings.
   - `csv_report.py`: Flat CSV file exports by scan date.
   - `json_report.py`: Complete machine-readable JSON exports by scan date.

---

## Data Flow Pipeline

```
yfinance API
   ↓
YFinanceLoader (Download, Clean, Validate)
   ↓
Daily OHLCV DataFrame & Weekly Resampling (drop_partial=True)
   ↓
Technical Indicators (Trend, Momentum, Volatility, Volume, Structure)
   ↓
Relative Strength (vs Market & Category Benchmarks)
   ↓
Scoring Engine (Trend Score, Bottom Score, Reversal Score, Entry Quality)
   ↓
Market Regime Detector (SPY/QQQ) & State Classifier
   ↓
Candidate Score Ranking Engine (Weighted Composite)
   ↓
Reporting Engine (Console, CSV, JSON) & Optional Gemini Explanation
```

---

## Additive state breakdown and history lookup

- `src/reporting/state_breakdown.py`: constructs state groups once, preserving
  the existing state order, descending Candidate Score order and display limit.
  `console.py`, daily HTML and standalone state HTML consume that same model.
- `src/historical/stock_lookup.py`: local-only lookup service. Selects completed
  exchange sessions, validates price/benchmark coverage, slices all inputs at
  each date, and calls the existing `analysis/snapshot.py` calculation pipeline.
- `src/data/scanner_history.py`: fingerprints the configuration, implementation
  and sliced inputs; reads matching saved scan JSON and persists reconstructions
  in a separate SQLite cache. Lookup never changes the Parquet price cache.
- `src/reporting/stock_history.py`: standalone HTML from the lookup model,
  including transitions, source provenance and explicit NA values.
- `__main__.py` and `run_scanner.py`: shared CLI dispatch; existing scan flags
  remain valid and `lookup SYMBOL --period Nd` is additive.

The scanner only adds input/policy `history_context` and result-fingerprint metadata
stamps to its output records;
scoring, states, regime, signals and ranking are unchanged. HTML is always a
rendered output, never a source of historical state. See
[HISTORY_LOOKUP.md](HISTORY_LOOKUP.md) for the reconstruction contract.

## Dependency Relationships & Module Isolation

- **Isolation**: `stock_scanner` does not import or depend on any intraday trading engine or external projects.
- **Unidirectional Flow**: Data flows strictly downwards: Data → Indicators → Analysis/Scoring → Classification/Ranking → Reporting.
- **Scoring Independence**: `trend_score`, `bottom_score`, `reversal_score`, and `entry_quality` are calculated independently before feeding into `candidate_score`.
