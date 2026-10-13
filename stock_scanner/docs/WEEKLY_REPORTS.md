# V1.3 weekly reports and completed sessions

## Running

Use `python run_scanner.py --report-period auto|daily|weekly|both` from the
project directory. The default `auto` generates daily market reports and adds
weekly reports after the final exchange session of the current Monday–Sunday
week closes. Saturday and Sunday runs also qualify. An explicit weekly request
on Monday–Thursday uses the last completed week. No scheduler is installed.

All modes retain the scanner CSV/JSON and existing daily CALL/PUT watchlists.
Weekly reports never overwrite those watchlists. Weekly files and section CSVs
have a `weekly_` prefix. Repeated runs for the same week replace that week's
report files, as daily reports do. A filtered run for a week also replaces the
same filenames, with `scope: filtered subset` clearly displayed.

## Calendar and data quality

`src/data/market_calendar.py` uses `pandas-market-calendars`' NYSE schedule for
this US equity universe. Official library usage documentation:
https://pandas-market-calendars.readthedocs.io/en/latest/usage.html

Live scans capture one timezone-aware cutoff for the entire run. Daily bars
belonging to sessions not yet closed are excluded in V1.3. Weekly bars retain
Friday labels but become available after the last actual session of that week
closes. Holidays, daylight saving time, and early closes follow the calendar.
Date-only historical cutoffs mean end of that date in America/New_York;
timestamp cutoffs honor the provided time (naive timestamps mean New York).

Weekly OHLCV requires every expected session to have finite values, positive
prices and nonnegative volume. Missing sessions cause that week's candle to
be excluded, never filled from another week. Adjusted prices come from the
existing data loader. A cached daily bar dated today is assumed finalized after
the scheduled close; the provider does not supply a separate finalization flag.

Weekly returns require both the target and immediately preceding weekly bars:
`100 * (latest_close / previous_close - 1)`. A missing prior week does not
silently turn a multiweek return into a one-week return. Stale/missing stocks
remain visible in coverage but are omitted from return rankings and breadth.
Breadth denominators count only stocks with usable weekly returns. ETFs are
excluded from stock rankings and stock breadth; their returns are separate.
Non-benchmark ETFs in mixed categories are identified by `etf_symbols` in
`config/universe.yaml`; whole ETF categories may use `instrument_type: etf`.

## Diagnostics

These fields are descriptive; no new predictive score or probability is added.

- Weekly UP: close > EMA20 > EMA40 and positive three-week EMA20 slope.
- Weekly DOWN: close < EMA20 < EMA40 and negative three-week EMA20 slope.
- Daily direction uses EMA20/EMA50 and the existing five-session EMA20 slope.
- Otherwise direction is MIXED; missing history is INSUFFICIENT_DATA.
- Weekly readiness requires at least the longest configured EMA period plus
  three consecutive completed weeks (53 with the current configuration).
- Alignment distinguishes ALIGNED_UP, ALIGNED_DOWN,
  PULLBACK_IN_WEEKLY_UPTREND, RECOVERY_IN_WEEKLY_DOWNTREND, and MIXED.
- RSI and MACD histogram changes compare the last two completed weeks.
- Breakouts/breakdowns compare the current weekly close with the high/low of
  the preceding 20 completed bars, excluding the current bar.
- Weekly swing structure uses five bars on either side of the pivot; a pivot
  is usable only after its five confirming weeks have completed. It is never
  treated as known on the original pivot date.
- Relative strength is stock return minus benchmark return in percentage
  points over 4 and 12 calendar weeks, against SPY (QQQ fallback) and the
  category benchmark separately. Missing endpoints yield unavailable values.

Report scores, daily direction and market regime are evaluated as of the
week's actual final session. `market_regime_at_week_close` is the existing
daily benchmark regime at that cutoff. Candidate Score remains the ranking
mechanism. Weekly movers are ranked by realized weekly return, not by a
prediction. Top candidate lists retain the existing bullish-oriented ranking.

## Versioning and validation

`scanner_version: "1.3"` selects completed-calendar inputs in live and historical
evaluation. Scoring formulas, weights, classification precedence and thresholds
are unchanged. V1.1/V1.2 select their previous live/historical resampling paths
for reproducibility. Newly generated weekly reports always use completed
calendar weeks regardless of the score version, so they are a new artifact,
not a reproduction of old live reports.

V1.3 historical weekly schedules include the actual final exchange session
instead of skipping a week when Friday is a holiday. Weekly report diagnostics
do not feed Trend Score, Entry Quality, Candidate Score, or Gemini decisions.

Tests cover partial weeks, ordinary and early closes, Good Friday, timezone
cutoffs, missing sessions, missing previous weeks, future-data invariance,
legacy resampling, scanner integration, ETF exclusion, coverage and exports.
Run the full suite after changes with `python -m pytest tests` (with the parent
directory on PYTHONPATH when the package is not installed).
