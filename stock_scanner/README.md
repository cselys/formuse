# Stock Scanner System (`stock_scanner`)

A deterministic Daily/Weekly stock scanner built in Python 3.11+.

`stock_scanner` is a standalone project designed to download historical market data using `yfinance`, compute causal technical indicators, detect market structure, calculate multi-dimensional scores (Trend, Bottom, Reversal, Setup Quality), classify stocks into defined market states, compute relative strength against market and category benchmarks, and output console, CSV, and JSON reports with optional Google Gemini AI explanations.

---

## Architecture & Design Principles

1. **Deterministic Technical Analysis**: All indicators and scores are strictly mathematical and reproducible.
2. **No Lookahead Bias / Future Data**: All indicators (EMAs, RSI, MACD, ATR, ROC, slopes, swing points) are causal.
3. **Independent Scopes**: Keeps separate scores (`trend_score`, `bottom_score`, `reversal_score`) rather than one generic score.
4. **Gemini as Explanation Only**: Gemini API is optional and never modifies technical scores, indicators, or classifications.
5. **Robust Error Handling**: One bad or delisted ticker will not terminate the entire scan.

---

## Project Structure

```
stock_scanner/
├── config/
│   ├── universe.yaml
│   └── scanner.yaml
├── data/
│   ├── raw/
│   ├── processed/
│   └── reports/
├── src/
│   ├── __init__.py
│   ├── data/
│   │   ├── __init__.py
│   │   └── yfinance_loader.py
│   ├── indicators/
│   │   ├── __init__.py
│   │   ├── trend.py
│   │   ├── momentum.py
│   │   ├── volatility.py
│   │   ├── volume.py
│   │   └── structure.py
│   ├── analysis/
│   │   ├── __init__.py
│   │   ├── daily.py
│   │   ├── weekly.py
│   │   ├── relative_strength.py
│   │   └── regime.py
│   ├── scoring/
│   │   ├── __init__.py
│   │   ├── trend_score.py
│   │   ├── bottom_score.py
│   │   ├── reversal_score.py
│   │   └── setup_quality.py
│   ├── ai/
│   │   ├── __init__.py
│   │   └── gemini.py
│   ├── reporting/
│   │   ├── __init__.py
│   │   ├── console.py
│   │   ├── csv_report.py
│   │   └── json_report.py
│   └── scanner.py
├── tests/
│   ├── test_indicators.py
│   ├── test_scoring.py
│   ├── test_regime.py
│   └── test_yfinance.py
├── requirements.txt
├── .env.example
├── .gitignore
└── run_scanner.py
```

---

## Installation

1. Navigate to the `stock_scanner` directory:
   ```bash
   cd stock_scanner
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

---

## Environment Variables

Copy `.env.example` to `.env` if you wish to use Google Gemini AI explanations:
```bash
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash
```
*Note: The scanner works completely without an API key if `--ai` is not specified.*

---

## Universe & Configuration

- **`config/universe.yaml`**: Defines stock categories (semiconductors, technology, energy, financials, small_caps), their category benchmarks (SMH, QQQ, XLE, XLF, IWM), and symbols. Easily customizable.
- **`config/scanner.yaml`**: Configures all indicator parameters, swing lookbacks, scoring weights, and classification thresholds.

---

## CLI Usage

From the parent `dailyscanner` directory, the existing command remains supported:

```powershell
python -m stock_scanner.run_scanner --report-period daily
```

### State breakdown and stock history lookup

Every scan that produces results also writes
`output/reports/state_breakdown_YYYY-MM-DD.html`, using the same state grouping,
Candidate Score ordering, values and `--top` limit as the terminal. The daily
HTML report includes that same section. No scores or states are recalculated
by the report renderers.

Look up the most recent completed trading sessions from the existing local
price cache, without running a new market download:

```powershell
# From dailyscanner
python -m stock_scanner lookup NVDA --period 10d
python -m stock_scanner lookup AAPL --period 30d

# Equivalent entry point, including from inside stock_scanner
python run_scanner.py lookup NVDA --period 5d
```

`5d`, `10d` and `20d` mean **trading sessions**, including the latest locally
available completed regular session. Weekends, exchange holidays and unfinished
sessions are excluded. Missing price sessions inside the selected interval
remain visible as NA rows rather than being replaced with older days.

The output is `output/reports/stock_history_NVDA_10d_YYYY-MM-DD.html`, with the
latest included trading date in its filename. Paths for reports are relative
to the command's working directory, matching existing report behavior.

Lookup selects benchmarks and slices prices separately at each historical date.
It displays `RECORDED_VERIFIED` only when saved input, policy, calculation and
result fingerprints qualify; otherwise it calculates `RECONSTRUCTED_VERIFIED`
using the existing completed-week historical policy. Legacy records remain
separate `RECORDED_LEGACY / UNVERIFIED` artifacts, never substituted for verified
scores. Missing prerequisites produce NA with a reason.

The SQLite store at `stock_scanner/data/history_lookup/results.sqlite3` preserves
immutable revisions and explicit provenance. Conflicts retain the first canonical
result and flag `RECONCILIATION_REQUIRED`; no later JSON or changed price cache
silently replaces it. Verification describes the identified cached adjusted
history and policy, not proof of original historical price vintages. Normal
V1.2 scoring and partial-week scanning behavior are unchanged.

See [HISTORY_LOOKUP.md](docs/HISTORY_LOOKUP.md) for data sources, fields, validation,
and configuration/output-directory options.

### Existing scan commands

Run the scanner with various command-line options:

```bash
# Run full universe scan
python run_scanner.py

# Scan specific category
python run_scanner.py --category semiconductors

# Scan single symbol
python run_scanner.py --symbol NVDA

# Filter by state
python run_scanner.py --state STRONG_UPTREND

# Limit top N results per state
python run_scanner.py --top 5

# Enable Gemini AI explanations
python run_scanner.py --ai

# Combine filters and AI
python run_scanner.py --category semiconductors --ai --top 10
```

---

## State Classifications

Stocks are classified into:
- `STRONG_UPTREND`
- `UPTREND`
- `EARLY_UPTREND`
- `BOTTOM_FORMING`
- `BOTTOM_BREAKOUT`
- `REVERSAL`
- `REVERSAL_CONFIRMED`
- `NEUTRAL`
- `DOWNTREND`
- `STRONG_DOWNTREND`
- `AVOID`

---

## Output Files

Scan reports are automatically saved under `data/reports/` by date:
- **`data/reports/YYYY-MM-DD.csv`**: Flat CSV report for spreadsheet analysis.
- **`data/reports/YYYY-MM-DD.json`**: Complete machine-readable JSON structure for downstream integration (e.g. options trading engines).

Additionally, every full daily scan automatically generates an enhanced **Daily Market Intelligence Report** under `output/reports/`:

- **`output/reports/daily_report_YYYY-MM-DD.txt`**: Readable terminal-style report (Top 10 stocks up/down, sector breadth, sector index performance).
- **`output/reports/daily_report_YYYY-MM-DD.html`**: Browser-readable HTML report with the same sections and tables.
- **`output/reports/daily_report_YYYY-MM-DD.csv`**: Combined machine-readable CSV.
- **`output/reports/stocks_up_YYYY-MM-DD.csv`**, **`stocks_down_YYYY-MM-DD.csv`**, **`sectors_YYYY-MM-DD.csv`**, **`sector_indexes_YYYY-MM-DD.csv`**: Separate per-section CSV files.

The daily report covers:
- **Top 10 Stocks Up / Down**: Ranked by daily percentage change using the same yfinance daily data as the scanner. Index/benchmark ETFs are excluded.
- **Top 3 Sectors Up / Down (Stock Breadth)**: Ranked by the fraction of constituent stocks that are up/down (`up_count / total`, `down_count / total`), not sector ETF returns. Sector indexes/ETFs are excluded from breadth.
- **Top 3 Sector Indexes Up / Down**: Separate ranking of configured sector ETFs by their own daily change (see `sector_indexes` in `config/universe.yaml`).

Missing/invalid daily-change data for a ticker is logged and skipped rather than crashing the scan.

---

## Historical Walk-Forward Validation

### V1.3 completed-week reports

Install the updated requirements (`python -m pip install -r requirements.txt`).
V1.3 uses the NYSE session calendar, including holidays and early closes, to
exclude unfinished daily sessions and unfinished weeks from live calculations.

```bash
# Daily report, plus weekly report after the final session of the week/weekend
python run_scanner.py

# Explicit latest completed-week report, including when run midweek
python run_scanner.py --report-period weekly

# Force both market reports, or just the daily market report
python run_scanner.py --report-period both
python run_scanner.py --report-period daily
```

The report-period switch controls the enhanced market reports; existing scanner
CSV/JSON and CALL/PUT watchlist outputs continue to be generated. `auto` is the
default and adds the weekly report from the final session's close through Sunday.

Weekly files are named `output/reports/weekly_report_YYYY-MM-DD.{html,txt,csv,json}`.
The date is the Friday week label; the actual final session is shown separately
(e.g. Thursday before Good Friday). Separate `weekly_stocks_up`,
`weekly_stocks_down`, `weekly_sectors`, `weekly_sector_indexes`, and
`weekly_diagnostics` CSV files use the same date suffix.

Reports include weekly movers, stock breadth, sector ETF returns, candidate
rankings, weekly trend/momentum/structure, 4/12-week market and category relative
strength, daily/weekly alignment, and missing-data coverage. Midweek requests
calculate the report's scores and daily direction at the completed week's final
session, not the current day. Filtered reports explicitly say `filtered subset`.

Weekly diagnostics are descriptive and do not change scoring weights or state
rules. The completed-candle input policy can change live scores compared with
V1.2. Setting `scanner_version` to `"1.1"` or `"1.2"` retains the previous live
and historical weekly-candle selection behavior; the new weekly report always
uses completed weeks. See [weekly methodology](docs/WEEKLY_REPORTS.md).

Scanner V1.2 also includes an out-of-sample **Historical Walk-Forward Validation** subsystem (`src/historical/`) for simulating historical decision-making using strictly point-in-time data cutoffs.

Usage:
```bash
python run_historical_walk_forward.py --start-date 2025-01-01 --end-date 2026-07-31 --frequency month_end
```

See [`docs/HISTORICAL_WALK_FORWARD.md`](docs/HISTORICAL_WALK_FORWARD.md) for full methodology and report specifications.

---

Scanner V1.2 includes a deterministic **Paper Validation subsystem** (`src/paper/`) for recording real-time scanner signals and tracking subsequent performance without placing orders or connecting to brokerages.

Usage:
```bash
# Record today's scan snapshot and paper signals
python run_paper_validation.py --record

# Update outstanding signal outcomes and state transitions
python run_paper_validation.py --update

# Generate aggregate performance reports
python run_paper_validation.py --report --report-type daily
```

See [`docs/PAPER_VALIDATION.md`](docs/PAPER_VALIDATION.md) for full methodology and workflow details.

---

## Testing

Run unit tests with `pytest`:
```bash
pytest
```
