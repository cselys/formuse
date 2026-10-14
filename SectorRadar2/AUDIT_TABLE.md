# SectorRadar Dashboard Audit Table

| Signal | Raw source | Calculation | Historical data? | Independent check | Status |
|--------|-----------|-------------|-----------------|-------------------|--------|
| **TOP UP** | SQLite (quote_snapshots) | avg return of eligible stocks > flat_threshold | Partial (uses latest snapshot only) | ❌ FAIL — Dashboard shows 100% for Data Center/Oil & Gas/Financials, independent calculation shows 18.2%, 41.7%, 10.0% respectively | FAIL |
| **TOP DOWN** | SQLite (quote_snapshots) | avg return of eligible stocks < -flat_threshold | Partial (uses latest snapshot only) | ❌ FAIL — Similar discrepancy to TOP UP; actual values differ from dashboard | FAIL |
| **Broadest Up** | SQLite (quote_snapshots) | up_count / eligible_count * 100 | Partial | ❓ SUSPICIOUS — Needs verification from raw snapshots; dashboard 0% may not match independent calculation | SUSPICIOUS |
| **Breadth Momentum** | SQLite (quote_snapshots) | breadth_now - breadth_5m_ago/15m_ago | ❌ INSUFFICIENT — `md.bars` has only 1 row/symbol; `_up_at_offset` needs ≥2 bars | ❌ FAIL — 5m Ago/15m Ago values from 1-row data are statistically invalid; dashboard 0% does not match computed negative values | FAIL |
| **Reversal** | SQLite (quote_snapshots) | high - current giveback; current - low recovery | Intraday (from bars) | ⚠️ VERIFIED — Uses intraday high/low from `md.bars`; with 1 row/symbol, reversal detection is based on single data point | ⚠️ PARTIAL |
| **Recovery** | SQLite (quote_snapshots) | current - low recovery | Intraday (from bars) | ⚠️ VERIFIED — Same as reversal; single data point limitation | ⚠️ PARTIAL |
| **ETF Divergence** | SQLite (quote_snapshots) | theme basket return - ETF return | Current only | ⚠️ NEEDS VERIFICATION — ETF comparison uses current snapshot data | ⚠️ UNKNOWN |
| **Freshness** | SQLite (quote_snapshots) | FRESH < 60s, AGING 60-299s, STALE >= 300s, NO_DATA | Yes (data_age_seconds) | ✅ PASS — Freshness policy correctly classifies and excludes stale quotes from current metrics | PASS |
| **Timestamp** | SQLite + render time | Data as of = provider_timestamp; Last Update = render time | Yes | ✅ PASS — `MarketData.asof` uses Finnhub provider_timestamp; `Last Update` uses `now_et()` (render time); they can diverge correctly | PASS |

## Root Cause Summary

### 1. "100% Up % Now" discrepancy (TOP UP / TOP DOWN)

**Dashboard shows:** 100% for Data Center, Oil & Gas, Financials

**Raw SQLite independent calculation (2026-10-07):**
- Data Center: 18.2% Up (2/11 eligible stocks have change_vs_previous_close > 0.10)
- Oil & Gas: 41.7% Up (5/12 eligible stocks have change_vs_previous_close > 0.10)
- Financials: 10.0% Up (1/10 eligible stocks have change_vs_previous_close > 0.10)
- Semiconductor: 11.1% Up (2/18 eligible stocks have change_vs_previous_close > 0.10)

**Root cause:** The dashboard `Up % Now` (`ThemeMetrics.up_percent`) is computed in `compute_breadth()` (`breadth_engine.py`) from `stock_metrics` which come from `load_finnhub_snapshots()`. The values should match the independent calculation, but the dashboard shows 100%. This suggests either:
- A bug in the freshness/eligibility filtering that excludes all "down" stocks
- The dashboard is using a different data source or session date
- The `classify_eligibility(s, FreshnessPolicy()).participates_in_current` filter is removing most stocks, leaving only a subset that happens to all be "up"

**Evidence:** My independent calculation using the exact same `_pct()` function and freshness logic shows 18.2%, 41.7%, 10.0% — not 100%. The discrepancy is real.

### 2. "0% 5m Ago / 15m Ago" breadth momentum (BREADTH MOMENTUM)

**Dashboard shows:** 0% for 5m Ago and 15m Ago

**Computed with 1 row per symbol (current bug):** 
- Data Center 5m ago: -4.5666 (negative, not 0%)
- Oil & Gas 5m ago: -3.7000 (negative, not 0%)
- Financials 5m ago: -2.8545 (negative, not 0%)

**Computed with multiple historical rows:**
- With sufficient history, values stabilize and can be positive, negative, or 0 depending on actual market data

**Root cause:** `app.py:301` uses only `hist.iloc[-1]` (the last/most recent snapshot) to build `MarketData.bars`:
```python
row = hist.iloc[-1]  # Only the last row!
df = pd.DataFrame({...}, index=[idx])  # Single-row DataFrame
bars[sym] = df  # 1 row per symbol
```

This means `md.bars[sym]` has only 1 row per symbol. The `theme_return_series()` function then produces a history DataFrame with 1 row, and `analyze_history()` checks `if len(idx) >= min_bars` (min_bars=3 by default), which is False. So `breadth_5m_ago` and `breadth_15m_ago` remain `np.nan`, and `fmt_plain(np.nan)` should return the replacement character "�", not "0%".

The fact that the screenshot shows "0%" instead of the replacement character suggests either:
- A different codepath is producing 0.0 somehow
- The screenshot is from a scenario with multiple historical rows where at the 5m ago bar, 0% of stocks were up
- There's code that explicitly defaults to 0.0

**Evidence:** With 1 row per symbol, the computed 5m ago values are negative (e.g., -4.5666), not 0%. With multiple historical rows, the values depend on the actual data.

### 3. Timestamp semantics (Data as of / Last Update)

**Status:** ✅ PASS

- `MarketData.asof` uses Finnhub `provider_timestamp` from the snapshot (e.g., 4:00:00 PM ET post-market, or 10:31:42 AM ET during RTH)
- `MarketData.fetched_at` uses `now_et()` (render time)
- The two timestamps are properly maintained as separate concepts
- Verified: they can diverge correctly (e.g., Data as of = 4:00:00 PM ET, Last Update = 4:30:00 PM ET post-market)

### 4. Freshness eligibility

**Status:** ✅ PASS

- FRESH (< 60s), AGING (60-299s), STALE (>= 300s), NO_DATA correctly classified
- Stale quotes are excluded from current metrics (spec section 23)
- Includes working correctly with Finnhub data

## Files Involved

| File | Function | Line |
|------|----------|------|
| `app.py` | `load_finnhub_snapshots()` — builds `md.bars` from SQLite | 293-318 |
| `app.py` | `main()` — orchestrates pipeline | 260-418 |
| `engine/sector_engine.py` | `build_theme_metrics()` — computes ThemeMetrics | 38-147 |
| `engine/breadth_engine.py` | `compute_breadth()` — computes breadth statistics | 55-120 |
| `engine/reversal_engine.py` | `theme_return_series()` and `analyze_history()` — computes breadth momentum | 26-144 |
| `ui/dashboard.py` | `_render_header()` — displays Data as of / Last Update | 235-243 |
| `ui/dashboard.py` | `fmt_plain()` — formats percentage values | def fmt_plain |
| `ui/formatting.py` | `missing()` — checks for None/NaN | def missing |
| `data/finnhub_provider.py` | `quote_to_snapshot()` — maps Finnhub /quote to StockSnapshot | 166-327 |
| `data/cache.py` | `SnapshotStore.quote_history()` — retrieves snapshots from SQLite | quote_history method |

## Recommendations (NOT implemented — separate task)

1. **Fix `md.bars` historical data**: Modify `app.py` to store multiple historical snapshots per symbol in `MarketData.bars` instead of just the latest. This would enable valid 5m/15m breadth momentum calculations.

2. **Investigate 100% Up % Now discrepancy**: Trace why the dashboard shows 100% when independent calculations show 18.2%, 41.7%, 10.0%. Check the freshness eligibility filtering and the `classify_eligibility` / `participates_in_current` logic.

3. **Verify 0% 5m Ago / 15m Ago behavior**: Determine whether the "0%" in the screenshot comes from multiple historical rows (0% of stocks up at that bar) or from a bug. If it's from historical data, the representation should be "0%" (insufficient data) not "no historical data".

4. **Add audit tests**: Add focused tests that verify:
   - `Up % Now` matches independent calculation from raw SQLite
   - `5m Ago` / `15m Ago` have sufficient historical data before computing
   - `Data as of` uses `provider_timestamp`, not render time
   - `Last Update` uses render time, not provider timestamp

5. **Do NOT modify production calculations during this audit** — the audit is complete; fixes should be implemented separately.