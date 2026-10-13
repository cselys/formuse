# Stock Scanner V1.2 — Paper Validation Subsystem

## 1. Overview & Purpose

The **Paper Validation Subsystem** is a deterministic research infrastructure designed to answer:

> *"When Scanner V1.2 generated this signal using only information available at that time, what happened to the stock afterward?"*

The subsystem operates entirely offline and independently of execution engines. It **never** places orders, submits trades, or connects to brokerage APIs.

---

## 2. Core Modules (`src/paper/`)

- **`models.py`**: Pydantic/Dataclass models for Paper Signal Records, Outcomes, and State Transitions.
- **`signal_recorder.py`**: Runs daily scans, saves immutable JSON snapshots (`data/paper_validation/signals/YYYY-MM-DD.json`), filters paper candidates based on configuration, and generates stable unique signal IDs.
- **`outcome_tracker.py`**: Automatically tracks subsequent market performance, forward returns (+1D, +3D, +5D, +10D, +20D), MFE, and MAE using trading days.
- **`state_tracker.py`**: Tracks subsequent scanner states across daily snapshots to build transition history (`initial_state`, `final_state`, `transition_path`).
- **`performance.py`**: Aggregates signal outcomes by state, candidate score buckets, entry quality buckets, and market regime.
- **`paper_report.py`**: Generates daily, weekly, and monthly aggregate reports (`daily_report.csv`, `weekly_report.csv`, `monthly_report.csv`, `summary.json`, `summary.txt`, `top_signals.csv`, `worst_signals.csv`).
- **`validation_runner.py`**: CLI orchestrator supporting `--record`, `--update`, and `--report`.

---

## 3. Workflow

1. **After Market Close**: Run `python run_paper_validation.py --record` to save an immutable scan snapshot and generate paper signal records.
2. **Subsequent Days**: Run `python run_paper_validation.py --update` to update forward returns, MFE/MAE, and state transitions using newly available daily market bars.
3. **Weekly / Monthly**: Run `python run_paper_validation.py --report --report-type weekly` to generate aggregate performance reports.

---

## 4. Signal & Outcome Methodology

- **Signal Price**: Final daily close available at scan time (`close`).
- **Forward Returns**: Calculated as `(future_close / signal_price) - 1` over +1D, +3D, +5D, +10D, and +20D trading sessions.
- **MFE / MAE**: Measured over 5, 10, and 20 trading sessions using daily High (`MFE = (max_high / signal_price) - 1`) and Low (`MAE = (min_low / signal_price) - 1`).
- **Completion Status**: Marked as `OPEN`, `PARTIAL`, or `COMPLETE` (once 20 trading days have elapsed).

---

## 5. Safety & Lookahead Isolation

- **Lookahead Safety**: Original scanner signals use strictly past data available up to the signal date. Future data is exclusively accessed by the outcome tracker after the signal date.
- **No Trading Connection**: The subsystem contains zero brokerage or order placement capabilities. Research infrastructure only.
