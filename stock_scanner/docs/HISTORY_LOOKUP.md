# State breakdown and historical stock lookup

## Commands and paths

From the parent `dailyscanner` directory:

```powershell
python -m stock_scanner.run_scanner --report-period daily
python -m stock_scanner lookup NVDA --period 10d
python -m stock_scanner.run_scanner lookup AAPL --period 30d
```

From the package directory:

```powershell
python run_scanner.py lookup NVDA --period 5d
```

`lookup` accepts `--config-dir` and `--output-dir`. Default configuration comes
from `./config/scanner.yaml` and `./config/universe.yaml` when available, otherwise
from the package configuration. Default output remains working-directory-relative
`output/reports`, consistent with existing scanner reports.

Files:

- `state_breakdown_YYYY-MM-DD.html`: every nonempty normal scan; date follows the
  existing report data date. Filtered scans and `--top` retain the terminal scope.
- `stock_history_SYMBOL_Nd_YYYY-MM-DD.html`: uppercase symbol, normalized count,
  and latest locally available completed trading session. Repeating a query for
  the same symbol/count/end date replaces this HTML file.

Both files are self-contained HTML without a running Python application, remote
assets or JavaScript. The daily HTML also embeds the state section.

## Shared state breakdown

`StateBreakdown` builds the original state groups and sorts their members by
Candidate Score descending, preserving stable ties and the original state order.
It does not classify stocks. The terminal, daily HTML and standalone HTML render
the same model and number formatting. Fields remain Symbol, Category, Candidate
Score, Trend Score, Entry Quality, Bottom Score, Reversal Score, RS(20d), RSI and
EMA20 distance. Existing signal tiers are included in HTML if present. The old
terminal has per-group displayed counts, not percentages or tier calculations;
no new interpretations are added.

## Lookup data flow and persistence

1. Read the existing package-relative `src/cache/SYMBOL.parquet` through
   `load_cached_data`. Read only the stock and its market/category benchmarks.
2. Use the existing NYSE calendar and `completed_daily` to remove holidays and
   sessions whose regular close has not passed. Date-only test/API cutoffs mean
   end of day; timezone-aware timestamp cutoffs honor their time.
3. Anchor the window at the most recent valid cached completed close. Select
   N exchange sessions ending there, not N calendar days. If the cache is stale,
   state its end date and the expected latest completed market session.
4. Slice the stock and benchmarks independently through each row's date T.
   Select SPY when it has data through T, otherwise QQQ, preserving the existing
   preference. Availability after T never participates in that selection.
   The category benchmark still follows the configured universe.
5. Apply the unchanged historical weekly policy. V1.1/V1.2 use
   `w-fri-drop-partial-v1` (the existing `drop_partial=True` path); V1.3 uses
   `nyse-completed-weeks-v1`. Normal V1.1/V1.2 scanning still uses its existing
   partial-week policy, explicitly identified as `w-fri-live-partial-v1`.
6. Reuse `RECORDED_VERIFIED` only if symbol/date/version, calculation policy,
   configuration/code fingerprint, all sliced input fingerprints, and the full
   deterministic result fingerprint qualify. Normal scan records now stamp the
   policy and result fingerprint as metadata only. Older or incompatible records
   are `RECORDED_LEGACY / UNVERIFIED` artifacts; they never supply the main
   historical scores, even when reconstruction is unavailable. Their complete
   original payload and source path are preserved separately in SQLite and shown
   in expandable HTML details. Original JSON files are never rewritten by lookup.
7. Otherwise calculate `RECONSTRUCTED_VERIFIED` with `analyze_snapshot`. Verified
   means reproducible from the identified cached adjusted data and calculation
   policy; it does not establish an original provider price vintage or live run.
8. Persist an immutable revision and pin the first verified result for each
   symbol/date as canonical. Repeated identical revisions are idempotent. A
   conflicting input, code/configuration/policy, or compatible saved payload is
   retained as a different revision; the report keeps the established canonical
   result and explicitly flags `RECONCILIATION_REQUIRED`. Its close and daily
   change are also retained to avoid mixing revised prices with old scores.
   No automatic promotion or reconciliation is performed. This feature provides
   conflict detection and preservation, not a reconciliation command.

### Revision store and provenance

`data/history_lookup/results.sqlite3` now contains `history_revisions`,
`history_canonical`, and (when needed) `history_artifacts`. Inserts are
append-only/idempotent; the canonical mapping is never overwritten. Revision IDs
are deterministic SHA-256 hashes of symbol/date/version, policy, input and code
fingerprints, verification status, and the result payload. Generation time and
file location do not create different calculation revisions.

Each verified revision has a metadata envelope containing symbol,
evaluation_date, scanner_version, calculation_policy, result_source,
reconstruction_status, data_source, data_cache_identity, category and market
benchmark symbols, individual daily/weekly/benchmark frame fingerprints,
combined input_fingerprint, calculation_fingerprint, result_fingerprint,
history_context, generated_at, revision_id, daily_change_pct, and the result
payload. Recorded revisions also identify their saved JSON source path.

The old flat `results` table is preserved but not reused because its missing
provenance cannot be established retroactively. Existing archives lacking the
new policy/result stamp remain unverified artifacts. This starts a new verified
canonical history without claiming that old flat cache entries were verified.

Appending future prices does not change an earlier revision. Changing historical
prices, configuration or implementation creates a new input identity and may
require reconciliation; it does not replace an established canonical result.
If the revision store cannot be read or written safely, lookup withholds verified
scores rather than silently issuing an unpinned replacement. Preserve/back up the
SQLite store to preserve canonical history; deleting it loses those decisions.

## Table fields and transitions

Each trading session has a row, newest first, with:

Date, Close, Daily %, State, Candidate Score, Trend Score, Entry Quality,
Bottom Score, Reversal Score, RS 20d %, RS 60d %, RSI, Market Regime, State
Transition, Result Source, Scanner Version, Missing Data reason, Calculation
Policy, Market Benchmark and Revision Status. Expandable details expose complete
provenance and unverified archive artifacts. An existing
Signal Tier is included when a verified record supplies it; reconstruction does
not invent a tier. RS values are the existing stock return minus category
benchmark return, in percentage points.

The summary shows requested period, actual session count, from/through dates,
latest state, latest Candidate Score and latest Market Regime. Summary values
refer to the latest row; missing latest results do not fall back to older scores.

Transitions compare chronological neighbors within the displayed window. A row
with a changed state is highlighted and shows `previous → current`. The first
row chronologically has no inferred transition. Missing states break the chain;
no transition is inferred across missing results.

## Missing data and safety

- A symbol outside the universe can be looked up when locally cached; the
  scanner's existing custom-symbol SPY benchmark is used and disclosed.
- A symbol without usable cached completed prices prints a clear message and
  exits with status 1, without writing an empty/misleading report.
- Fewer than N covered sessions returns a shorter report and explains coverage.
- Missing internal sessions remain explicit NA rows. The following day's Daily %
  is NA if the preceding trading session's close is missing.
- Reconstruction requires the existing walk-forward minimum of 100 stock bars,
  at least 10 completed weekly bars, 61 aligned stock/category benchmark sessions,
  and 50 market benchmark bars. Missing/invalid OHLCV, missing sessions in the
  available input history, or absent benchmark endpoints withhold scores and
  states with a reason. This is a lookup eligibility check, not a strategy change.
- A stored bar dated today is treated as finalized only after its scheduled
  close, following the existing calendar convention. The price provider does not
  give a separate immutable finalization flag.

The public service separates lookup from CLI/rendering so date-range selection
can be added later. Date ranges and week/month period aliases are not implemented.

## Verification

Run the full test suite with `python -m pytest tests`, with the package's parent
on PYTHONPATH when not installed. New tests cover exact shared state values,
files/HTML escaping, symbol and period validation, 5d/10d counts, date ordering,
weekends/holidays/open sessions, insufficient and missing data, unavailable
calculations, deterministic persistence, changes to past versus future data,
record provenance, state transitions, missing HTML, no downloads and CLI usage.

### Integrity remediation verification (September 22, 2026)

AUDIT REMEDIATION RESULT: PASS for the four identified lookup issues.

- Full suite: **141 passed**, including 20 new integrity cases in
  `tests/test_lookup_integrity.py`. Relevant existing lookup assertions were
  updated to require verified source labels and separate unverified artifacts.
- Cold-cache tests compare complete snapshots for V1.2 and V1.3 after appending
  five future sessions and changing stock/category/market prices separately.
- Future-only SPY availability leaves QQQ selected at T; when both exist at T,
  SPY remains selected. Both tests assert full snapshot equality and no NA result.
- Matching policy/input/code/result stamps permit saved reuse without calculation;
  the test compares the complete saved snapshot with independent reconstruction.
  Missing stamps, altered results, different inputs and partial-week policies
  cannot substitute unverified values into the main history.
- Archive conflicts and changed historical prices preserve the canonical result;
  distinct verified revisions are retained and reconciliation is flagged.
  Provenance survives reopening SQLite and repeated inserts remain idempotent.
- The exact command `python -m stock_scanner lookup NVDA --period 10d`, run from
  `dailyscanner` with the project virtual environment on PATH, succeeded. Its
  parent configuration selected V1.2, with ten sessions September 8–21. The
  latest completed session was September 21: UPTREND, Candidate 79.0, Trend 76.0,
  Entry 98.0, Bottom 54.5, Reversal 65.5, MARKET_UPTREND. All ten main rows were
  RECONSTRUCTED_VERIFIED under `w-fri-drop-partial-v1`.
- Parsed the generated HTML to check all ten dates, state transitions and
  provenance; eight original saved artifacts were retained separately. Output:
  `../output/reports/stock_history_NVDA_10d_2026-09-21.html`.
- Repeated the actual September 14 availability reproduction using cached NVDA:
  adding SPY bars only after September 14 retained Candidate 64.8 and
  MARKET_NEUTRAL with QQQ; the inverse with SPY already available retained SPY.
- For every actual NVDA date in that ten-session window, a fresh reconstruction
  through T matched the entire snapshot and revision ID after appending five
  extreme future stock/benchmark sessions. These checks used memory stores.
- SHA-256 checks confirmed no changes to analysis, scoring, indicator, calendar,
  loader, or scoring-configuration files during remediation. Normal scanner
  modifications add only policy and result-fingerprint metadata.

The scope of VERIFIED remains explicit: reproducibility from the identified
cached adjusted history, not proof of an immutable historical provider vintage.

### Original implementation verification (before integrity remediation)

Changed modules/files for this feature:

- Added `__main__.py`, `src/data/scanner_history.py`,
  `src/historical/stock_lookup.py`, `src/reporting/state_breakdown.py`,
  `src/reporting/stock_history.py`.
- Updated `run_scanner.py`, `src/scanner.py` (provenance metadata only),
  `src/reporting/console.py`, `src/reporting/daily_report.py`,
  `src/reporting/renderers.py`, `src/reporting/file_writer.py`, `.gitignore`.
- Added `tests/test_state_breakdown.py`, `tests/test_stock_lookup.py`.
- Updated `README.md`, `docs/ARCHITECTURE.md`, `docs/DEVELOPMENT_GUIDE.md`;
  added this document. Existing AGENTS.md rules required no changes.

Original pre-remediation full suite: **121 passed** (76 existing tests plus 45 new cases). SHA-256 checks
confirmed no changes to scoring, analysis/classification/market regime,
indicators or `config/scanner.yaml` during this feature implementation.

Real verification used the parent `dailyscanner/config` and its saved JSON:
NVDA 10d covered **2026-09-08 through 2026-09-21**, with 10 rows. Latest original
recorded values: UPTREND, Candidate Score 79.0, MARKET_UPTREND; source
RECORDED_LEGACY. Other days without usable saved records were reconstructed.

Generated examples inside the package directory:

- `output/reports/state_breakdown_2026-09-21.html`: 310 symbols across 10 groups,
  taken directly from the existing parent-directory scan JSON, without rescoring.
- `output/reports/stock_history_NVDA_10d_2026-09-21.html`: validated standalone
  HTML with 10 rows and the original latest recorded values above.
