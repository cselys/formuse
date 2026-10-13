# Stock Scanner V1.2 — Historical Walk-Forward Validation

## 1. Overview & Purpose

The **Historical Walk-Forward Validation** subsystem is an out-of-sample historical simulation designed to evaluate how Scanner V1.2 would have performed if run historically using strictly point-in-time data available at each scan date.

This is distinct from the real-time Paper Validation subsystem (which records live signals forward from the V1.2 freeze) and the previous 864-observation evaluation report.

---

## 2. Core Modules (`src/historical/`)

- **`walk_forward.py`**: Orchestrates historical walk-forward signal generation, outcome tracking, and reporting.
- **`historical_signal.py`**: Generates point-in-time scanner signals across scheduled monthly/weekly dates, enforcing strict date slicing and excluding incomplete weekly candles (`drop_partial=True`).
- **`historical_outcome.py`**: Calculates multi-horizon forward returns (`+1D`, `+5D`, `+10D`, `+20D`, `+40D`, `+60D`), MFE/MAE over 5D to 60D using High/Low, and relative outperformance vs SPY and QQQ.
- **`historical_report.py`**: Aggregates performance by state, candidate score buckets, entry quality buckets, market regime, category, and monthly periodicity.

---

## 3. Usage & CLI

Run walk-forward validation with configurable date ranges and frequencies:

```bash
cd stock_scanner
python run_historical_walk_forward.py --start-date 2025-01-01 --end-date 2026-07-31 --frequency month_end
```

---

## 4. Output Reports (`data/evaluation/walk_forward/`)

- `signals.csv`: Raw frozen historical signals.
- `outcomes.csv`: Multi-horizon forward returns and MFE/MAE.
- `monthly_report.csv`: Monthly periodicity consistency.
- `state_report.csv`: Performance grouped by market state.
- `score_report.csv`: Performance grouped by Candidate Score bucket.
- `regime_report.csv`: Performance grouped by Market Regime.
- `category_report.csv`: Performance grouped by stock category.
- `top_signals.csv` / `worst_signals.csv`: Top and worst ranked signals.
- `summary.json` / `summary.txt`: Executive summary reports.

---

## 5. Lookahead Audit & Safety

- Strict point-in-time slicing ensures no future daily bars or incomplete weekly candles are accessed during signal generation.
- Automated tests verify that modifying future prices does not alter historical signal scores or states.
