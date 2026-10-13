# Stock Scanner V1.2 — Development Guide

## Installation
1. Navigate to `stock_scanner/`.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

---

## Running the Scanner
- Full scan:
  ```bash
  python run_scanner.py
  ```
- By category:
  ```bash
  python run_scanner.py --category semiconductors
  ```
- Single symbol:
  ```bash
  python run_scanner.py --symbol NVDA
  ```
- With Gemini AI:
  ```bash
  python run_scanner.py --ai
  ```

---

## Stock history lookup and state HTML

From `dailyscanner`, use:

```powershell
python -m stock_scanner lookup NVDA --period 10d
python -m stock_scanner.run_scanner lookup AAPL --period 20d
```

From `stock_scanner`, use `python run_scanner.py lookup NVDA --period 5d`.
Lookup accepts positive session counts from `1d` through `5000d`; weeks/months
are intentionally not aliases. It never downloads data. Populate/update prices
with the existing scanner command first if a cache is missing.

The lookup CLI accepts `--config-dir PATH` and `--output-dir PATH`. It uses
`./config` when present, otherwise the package's configuration directory. Report
paths default to `./output/reports`; the existing Parquet cache and the new
reconstruction cache are package-relative and independent of working directory.

Normal scans now also write `state_breakdown_<data-date>.html` (even for filtered
scans or weekly-report mode). Daily HTML embeds the identical state section.
`--top` applies to the terminal and both HTML state sections consistently.
The original per-state count is the number displayed; when truncated, HTML also
states the full group size. Existing signal tiers are retained when provided,
but no actionable/watchlist tier is newly inferred.

Tests: `tests/test_state_breakdown.py` and `tests/test_stock_lookup.py` verify
shared rendering, cached reconstruction, session cutoffs, validation, missing
data, transitions, no downloads, fingerprints and CLI integration. Existing
strategy and weekly-report tests must continue to pass unchanged.

Detailed data and reproducibility rules: [HISTORY_LOOKUP.md](HISTORY_LOOKUP.md).

## Running Tests

Run unit tests with pytest:
```bash
python -m pytest
```

---

## Running Historical Walk-Forward Validation
Execute out-of-sample historical walk-forward simulation and reporting:
```bash
python run_historical_walk_forward.py --start-date 2025-01-01 --end-date 2026-07-31 --frequency month_end
```
Execute paper validation recording, outcome updates, and report generation:
```bash
# Record today's scan snapshot and paper signals
python run_paper_validation.py --record

# Update outstanding outcomes and state transitions
python run_paper_validation.py --update

# Generate performance reports
python run_paper_validation.py --report --report-type daily
```


---

## CALL/PUT Watchlist & Shortlist Output Configuration
Every normal scanner run automatically generates YAML watchlist files under the `output/` directory based on `config/scanner.yaml` output settings:

### Configuration (`config/scanner.yaml`)
```yaml
output:
  shortlist:
    enabled: true
    size: 5
    sort_by: candidate_score
  save_full_list: true
```
- **`output.shortlist.enabled`**: Boolean (default `true`). Controls whether shortlist files are generated.
- **`output.shortlist.size`**: Positive integer (default `5`). Controls the maximum number of top-ranked candidates included in the shortlist.
- **`output.shortlist.sort_by`**: Sorting metric (default `candidate_score`). Uses existing V1.2 ranking.
- **`output.save_full_list`**: Boolean (default `true`). Controls whether full complete ranked lists are saved.

### Generated Files:
1. **Shortlist Files (`output/call_stocks.yaml`, `output/put_stocks.yaml`)**:
   - Contains top N ranked candidates (default top 5).
   - Priorities are renumbered sequentially starting at 1.
   - **Purpose**: Intended to be the **small downstream candidate universe for the future option scanner**.
2. **Full List Files (`output/call_stocks_full.yaml`, `output/put_stocks_full.yaml`)**:
   - Contains all ranked candidates across the universe.
   - Preserves complete ranking and original sequential priorities.
   - **Purpose**: Retained for comprehensive analysis, auditing, and debugging.

### Classification & Guardrails:
- **CALL Watchlist**: Bullish/upside candidates (`STRONG_UPTREND`, `UPTREND`, `EARLY_UPTREND`, `BOTTOM_FORMING`, `BOTTOM_BREAKOUT`, `REVERSAL`, `REVERSAL_CONFIRMED`) with qualifying candidate scores, sorted by candidate score descending.
- **PUT Watchlist**: Bearish/downside candidates (`DOWNTREND`, `STRONG_DOWNTREND`), sorted by candidate score ascending (strongest downtrend conviction first).
- **Crucial Note**: These YAML files represent scanner relevance and watchlists, **not direct trade or execution signals**. They do not execute trades or select option contracts.

---

## Coding Conventions & Guardrails
1. **No Intraday Engine Dependency**: Keep `stock_scanner` entirely independent.
2. **Causal Calculations**: All indicators must be strictly causal.
3. **No Parameter Overfitting**: Do not tune weights or thresholds arbitrarily against historical results.
4. **Preserve V1.1 Reproducibility**: Maintain compatibility and versioning (`scanner_version = "1.2"`).
