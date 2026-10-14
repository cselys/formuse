# Canonical Finnhub theme observations

This document supersedes the yfinance/history portions of DATA_FLOW.md,
CALCULATIONS.md, and REVERSAL_RECOVERY.md for the production Finnhub path.

## Production path

`SnapshotStore.session_quote_snapshots(session)` performs one SQLite SELECT.
`load_snapshot_market_data()` constructs MarketData (including the complete raw
quote history) and the stock detail snapshots from that same read. Every
Streamlit fragment refresh repeats the read, recomputes session selection, and
rebuilds MarketData. It performs no network requests.

`run_pipeline → build_theme_metrics → build_theme_history → observation_at →
compute_breadth` produces historical basket aggregates. The parallel
`current_observation → compute_breadth` path uses the same provider cutoff and
aggregation definitions with a separate current-signal policy.
`analyze_history` derives extrema and momentum from those observations.
ThemeMetrics receives the current observation's aggregates and that history's
derived signals. The UI only formats these fields; it does not recompute them.

The separate OHLCV-provider compatibility path remains for existing non-Finnhub
callers/tests. Production supplies `MarketData.quote_snapshots`, including an
empty DataFrame when the session has no data; it never falls back to raw OHLCV
alignment merely because the quote session is empty.

## Clock and target selection

* Current target T is MarketData.asof, the maximum finite positive persisted
  provider timestamp in the session, across stocks and ETFs. It is a shared
  market-data cutoff, not render time or a different time for each theme.
* Historical targets lie on fixed five-minute clock boundaries, beginning at
  the first boundary on/after the theme's first valid provider observation.
  Current T and exact T−5m/T−15m targets are included when within the observed
  session. These are sampling targets; the underlying prices always come from
  persisted observations, not interpolation.
* For each theme constituent at each target, select the latest **valid** quote
  with provider_timestamp <= T. Valid includes a finite calculable return and
  nonzero previous close. A later invalid quote does not replace an earlier
  valid one; the earlier quote must still pass the age rule at T.
* Duplicate `(symbol, provider_timestamp)` observations are resolved by the
  greatest persisted fetched_at. Exact duplicates cannot inflate the minimum
  history count. Equal targets are deduplicated and sorted.
* `fetched_at` breaks duplicate ties only. This is retrospective reconstruction
  of market observations available in the frozen read. It is **not** a backtest
  of what the application had received at historical wall-clock time T. A quote
  delivered after T may describe provider market time at/before T.
* A five-minute grid samples the session; peak/low means the extrema of the
  supported sampled basket observations, not tick-level session extrema.

MarketData.asof still means provider time. MarketData.fetched_at / Last Update
still means the dashboard render time. With no provider observation, asof is
None, never replaced with render time. Bars retain provider-time indexes and
raw per-row metadata; production basket calculations consume quote_snapshots.

## Freshness and coverage

Age at target = `T - provider_timestamp`, in seconds. Historical policy remains
unchanged: FRESH <60s, AGING 60–299s, STALE >=300s; default membership is FRESH
only, with the legacy include_aging_in_current option preserved for history.
MARKET NOW separately uses `current_signal_max_age_seconds: 180`: valid quotes
with nonnegative age strictly below this limit participate. Current quality is
FRESH <60s, AGING 60–179s, STALE >=180s; invalid/missing/future => NO_DATA.
A 120-second quote may be eligible for MARKET NOW while remaining classified
as AGING/RECENT rather than FRESH. The current stale boundary follows the
configured signal limit; historical classifications are not rewritten.
Settings are read from data.finnhub.freshness, with data.freshness as the legacy
fallback. There is no unbounded carry-forward and no future quote selection.

The user selected partial baskets with **at least two eligible constituents**
for multi-stock themes. A configured one-stock theme can use its one stock.
There is no substitution of one stock for a multi-stock theme. The observation
records eligible_count, constituent identities, and provider timestamps. Partial
baskets can change composition over time; their movement is not a fixed-cohort
performance measurement. Coverage and the existing small-sample flag remain
important when interpreting these signals.

Insufficient observations retain coverage counts but scalar returns and
percentages are NaN, with status INSUFFICIENT DATA. ThemeMetrics.valid_stocks is
zero for an unsupported basket (so rankings and alerts cannot use it);
eligible_stocks retains the actual eligible count. No eligible data is not 0%
breadth. A supported basket with no up stocks really is 0%.

Missing current data remains missing even if valid earlier observations exist.
The history retains explicit missing rows. Tables keep the theme visible with
missing markers, and the full table/detail caption shows insufficient status.
No UI sections or columns were added.

## Formulas

Every selected quote uses its **own** previous_close and today_open, with the
existing `_pct` formula. Average and median are the arithmetic mean and median
of eligible constituent returns, with equal stock weights. Breadth keeps the
user-confirmed neutral band: up is return > +0.10%, down is return < −0.10%,
unless the existing configurable classification threshold is changed.

* up_pct = 100 × up_count / eligible_count
* down_pct = 100 × down_count / eligible_count
* peak = max(supported historical theme average returns)
* low = min(supported historical theme average returns)
* current = current-signal basket average at the shared provider cutoff
* reversal magnitude = peak − current
* stored reversal_from_high = current − peak (existing signed convention)
* recovery_from_low = current − low

Both ThemeMetrics.up_percent and breadth_now come from the same current basket.
Historical peak/low and offset breadth remain based on the original 60s policy.
Current return can therefore exceed those historical extrema; arithmetic stays
unclamped and current values are never inserted into the historical series.
Breadth momentum uses the same series at T−5m/T−15m. It never clamps an
unavailable interval to the first row or selects a future row. The generic
history lookup permits a preceding observation only when less than 60 seconds
old; production builds exact offset targets. Explicit missing observations block
fallback. The existing minimum-history gate counts distinct supported basket
observations; repeated provider observations do not create additional evidence.
Missing current or historical breadth gives a missing delta.

Ranking formulas, alert thresholds/names, theme universe, collector, request
strategy, SQLite schema, and AI JSON fields were not changed.

## Regression and frozen-data verification

`tests/test_theme_alignment.py` exercises SQLite → loader → run_pipeline → UI,
asynchronous delivery, the +2/−1/+3 basket, 3/5 breadth, reversal/recovery
invariants, known offsets, insufficient spans/coverage, future/stale exclusion,
duplicate quotes, quote-specific references, refresh/session rollover, policy
configuration, and actual Streamlit rendering and refresh.

`scratch/correctness_20261007/verify_alignment.py` reads the original frozen
database read-only, compares every canonical historical row against an
independent SQL oracle, captures rendered tables, and verifies that the frozen
file's SHA-256 is unchanged. Pipeline persistence is redirected to a separate
verification output database. See ALIGNMENT_REPORT.md in that directory for
the numeric results and missing-data limitations.

After the current-only window change, run this unchanged verifier with
`SECTOR_RADAR_SETTINGS=scratch/current_signal_20261007/compatibility60.yaml`.
This preserves the historical oracle and legacy current assertions. In a
separate process with the normal settings, run
`python scratch/current_signal_20261007/verify_current.py` for the 180s oracle,
exact historical-frame equality, and actual Streamlit AppTest against read-only
normal SQLite data. `tests/test_current_signals.py` covers strict boundaries,
future exclusion, partial/minimum baskets, and unchanged historical bases.
