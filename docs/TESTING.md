# TESTING.md

## Test runner

```bash
python -m pytest tests/ -q
```

All 39 tests pass in ~2 seconds on the test machine. Tests use **synthetic data only** — no yfinance, no network access.

## Test organization

Tests live in `tests/` and are organized as follows:

### `tests/__init__.py`
Empty — marks the directory as a Python package.

### `tests/conftest.py`
Shared fixtures:
- `settings` — loads `config/settings.yaml` (the real config file)
- `make_bars(closes, **kwargs)` — synthetic intraday 5-min bars (tz-aware ET)
- `make_daily(prev_close, today_open, **session_date)` → 3 daily bars (2 before session date + session date)
- `make_md(bars_map, daily_map, **interval, **failed)` → `MarketData` helper
- `build_metrics(closes_map, **settings, **prev_close, **today_open, **session, **failed)` → `(MarketData, dict of StockSnapshot)`

### `test_price.py` (10 tests)

Unit tests for per-stock metric calculations (spec 8, 23):

- `test_change_vs_previous_close` — `prev_close → current`
- `test_change_vs_open` — `open → current`
- `test_intraday_high_low_distances_volume` — full metric suite (high/low, distances, volume)
- `test_missing_bars_invalid` — no intraday data → `is_valid = False`
- `test_missing_previous_close_invalid` — no prev close → `is_valid = False`
- `test_nan_close_rows_dropped` — NaN close rows removed, not poisoning high/low
- `test_duplicate_timestamps_deduped` — duplicate timestamps kept once (last), volume not double-counted
- `test_stale_quote_flagged_but_still_valid` — `stale quote` issue set, but `is_valid` remains `True`
- `test_no_open_yet` — `today_open = None` → `change_vs_open = None`, still valid
- `test_daily_reference` — prev close + today open from daily bars
- `test_all_metrics_missing_symbol_handled` — missing symbol in `StockSnapshot` dict

### `test_breadth.py` (7 tests)

Unit tests for breadth aggregation (spec 9-11):

- `test_up_percent_8_of_10` — 8 up / 10 = 80%
- `test_strong_breadth_distinguishes_magnitude` — `80% +0.2%` vs `80% +2%` → different `strong_up%`
- `test_flat_threshold_boundary` — `0.11 → UP`, `0.10 → FLAT`, `-0.10 → FLAT`, `-0.11 → DOWN`
- `test_empty_input_no_crash` — `compute_breadth([])` → zeros
- `test_missing_stocks_excluded_not_fatal` — 12 configured, 10 valid, 2 missing → `80% up`
- `test_change_from_open_aggregation` — change from open with custom today_open

### `test_reversal.py` (10 tests)

Unit tests for reversal / recovery / state (spec 12-14):

- `test_reversal_from_high` — high +3.2%, current +0.5% → reversal = -2.7 pp
- `test_recovery_from_low` — low -3.0%, current -0.5% → recovery = +2.5 pp
- `test_breadth_momentum_5m_15m` — now 80%, 5m ago 70%, 15m ago 50% → Δ5m +10, Δ15m +30
- `test_min_history_bars_gate_momentum` — 3 bars → `has_history=True`; 2 bars → `has_history=False`; momentum NaN when no history
- `test_empty_history` — `analyze_history(None)` → `has_history=False`, all NaN
- `test_state_trending_up` / `test_state_trending_down` / `test_state_reversing_down` / `test_state_recovering_up` / `test_state_mixed` / `test_reversal_state_requires_history` — all `classify_state()` exact matches
- `test_theme_return_series_from_bars` — 2 stocks with bars, series has 3 rows, avg/up% computed correctly
- `test_theme_return_series_skips_bad_symbols` — bad/missing bars skipped in series

### `test_sector.py` (12 tests)

Unit tests for multi-theme orchestration & persistence (spec 35):

- `test_same_ticker_in_multiple_themes` — MU in Semiconductor + Memory + AI/Compute; each theme computes correctly
- `test_missing_stocks_do_not_break_theme` — 10 configured, 8 valid, 2 missing → `total=8, valid=8, missing=2`
- `test_etf_excluded_from_breadth` — ETF not counted as constituent; ETF return / basket / divergence computed
- `test_small_sample_flag` — `valid=3 < 5 → small_sample=True`
- `test_rankings_ordering` — `top_up/top_down` return correct theme
- `test_composite_score_bounds` — scores in [0, 100], higher score for better theme
- `test_to_json_shape` — `ThemeMetrics.to_json()` has exact key set per spec 28
- `test_snapshot_store_roundtrip` — SQLite save/load: 1 sector row + 2 stock rows; idempotent upsert

### Running a specific test file

```bash
python -m pytest tests/test_price.py -q
python -m pytest tests/test_breadth.py -q
python -m pytest tests/test_reversal.py -q
python -m pytest tests/test_sector.py -q
```

### Adding a new test

1. Import the needed helpers from `tests.conftest`
2. Write a `def test_XXX(settings):` function
3. Use `build_metrics()` to create `MarketData + StockSnapshots`
4. Assert the expected output
5. Run `python -m pytest tests/ -q` to verify nothing is broken

## CI / integration

The test suite is designed to run without network access, no yfinance, and no special environment. It can be run in any CI pipeline or locally.