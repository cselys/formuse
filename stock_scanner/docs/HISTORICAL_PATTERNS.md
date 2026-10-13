# Historical state pattern finder

From `dailyscanner`, using an environment with the existing scanner dependencies:

```powershell
python -m stock_scanner find-pattern --states BOTTOM_FORMING,REVERSAL --recent-days 10 --max-states 3 --max-span-days 20
python -m stock_scanner find-pattern --auto --recent-days 10 --max-states 3 --max-span-days 20 --min-occurrences 2 --limit 50
```

The repository environment can be used explicitly:

```powershell
.\stock_scanner\.venv-weekly\Scripts\python.exe -m stock_scanner find-pattern --states BOTTOM_FORMING,REVERSAL
```

The same dispatch works through `python -m stock_scanner.run_scanner find-pattern`
or, from `stock_scanner`, `python run_scanner.py find-pattern`. Normal scan and
lookup commands retain their behavior. `python -m stock_scanner.find_pattern`
is also available.

## Authoritative source and integrity

The source is the existing package-relative
`stock_scanner/data/history_lookup/results.sqlite3`: `history_canonical` selects
the first established revision for each symbol/date from `history_revisions`.
This is the lookup system's authoritative pinned, verified history, documented
in [HISTORY_LOOKUP.md](HISTORY_LOOKUP.md). It contains both previously verified
recorded results and previously verified reconstructed results, with their
original provenance retained. The finder performs no reconstruction itself.

`src/historical/pattern_source.py` opens that existing database with SQLite
`mode=ro` and `query_only`, reads a consistent transaction, and reuses
`ScannerHistoryStore._checked` for the full deterministic result and revision
fingerprints. Canonical identity, verification status, version and policy
metadata must agree. Missing or corrupt provenance excludes observations.
If the database is missing, it is not created. A WAL database lacking an
existing shared-memory sidecar is withheld to avoid creating a sidecar.

Distinct revisions for one symbol/session imply `RECONCILIATION_REQUIRED` and
exclude that session. Explicit reconciliation/conflict flags are also respected.
Identical revisions are idempotent; canonical symbol/session records are counted
once. No revision is promoted, overwritten or reconciled. Malformed revisions
that cannot safely be assigned to a session cause the query to withhold results.
The old `results` and `history_artifacts` tables are counted but never promoted.

Saved daily scan JSON under `data/reports/` and `stock_scanner/data/reports/`
is not an alternate verified source: lookup requires validation against the
identified inputs/code/policy before pinning those results. The finder does not
perform that validation or use unpinned archives. HTML is never a data source.
Daily/weekly Parquet data, price caches, the reconstruction pipeline, and V1.3
prospective observations/outcomes are not read or written by this query.

`VERIFIED` retains the existing scope: reproducibility from the specified
adjusted prices and policy, not proof of an immutable historical provider vintage.
The store may be sparse because it contains only previously established lookup
history. On initial inspection it held 128 canonical observations for 8 symbols,
dated July 30 through October 8, 2026. This is not full-universe historical coverage.

## Exact matching semantics

- Each requested state occupies one daily observation on a consecutive completed
  NYSE session. Patterns have 2 or 3 states. Repeated states are retained; runs are
  not compressed into transitions. An intervening state or missing/excluded
  session breaks the pattern. Stocks are never joined to each other.
- State validation uses the existing `STATE_ORDER` catalog, which matches the
  classifier's state values. No new classifications are introduced.
- `--recent-days` defaults to 10 (range 1–5000). The final state must fall within
  those completed exchange sessions, anchored to `--as-of` or current time. The
  window never shifts backward to make stale stored observations appear recent.
- The reader includes up to two sessions before that window to allow a pattern
  to begin earlier while ending inside it. `--max-span-days` counts both endpoints,
  defaults to 20, and cannot exceed 20. Natural spans remain exactly 2 or 3 sessions.
  An explicit pattern longer than the span/max-states is rejected. Auto searches
  lengths 2 through the smaller of max-states and max-span-days.
- `--as-of` uses existing exchange date conventions: a date-only value means
  end of day Eastern; an ISO timestamp honors its time. Current sessions before
  their scheduled close, holidays and weekends are excluded. Early closes count
  once their actual scheduled close has passed.
- No evaluation date after the cutoff participates in matching or latest-state
  fields. This searches today's established canonical history through that date,
  **not** what the database itself contained at a historical wall-clock instant.
  A previously reconstructed observation can therefore be queried at its evaluation
  date, with its later generation time disclosed in provenance.
- A window crossing scanner-version, calculation-policy or calculation-fingerprint
  changes is excluded rather than treating model/configuration changes as movement.

## Reports, counts and missing values

Terminal output summarizes coverage and results. Every invocation saves unique
HTML and JSON files in `output/reports/patterns/` using an Eastern timestamp,
microseconds, a random suffix and exclusive creation. Reports with no matches or
insufficient history are also saved. No historical report index is maintained.

Explicit matches include all requested fields. Start/end prices come from the
same canonical payloads as the states; change is `(end / start - 1) * 100`.
Missing prices/scores remain `N/A` or JSON `null`. Latest recorded fields refer
to the latest canonical session through the cutoff, which may be after the
pattern end; an excluded latest record does not fall back to an older score.
Complete per-observation provenance, including RECORDED versus RECONSTRUCTED,
is retained in JSON and expandable HTML details.

Automatic discovery counts distinct symbol/start/end/state-sequence occurrences,
including overlapping windows. Distinct-stock counts are reported separately.
Sort order is occurrence count descending, distinct stocks descending, most
recent date descending, then alphabetical sequence. Explicit results sort by end
date descending, symbol, then sequence. `--min-occurrences` applies to automatic
patterns. `--limit` limits displayed explicit matches or discovered patterns;
aggregate counts are computed before truncation. Automatic JSON/provenance retains
the supporting occurrences, including patterns below the display threshold.

`INSUFFICIENT_HISTORY` means no eligible contiguous window of a requested length
can be evaluated. `NO_MATCHES` means some eligible windows were evaluated without
a match. `NO_PATTERNS_MEET_THRESHOLD` means occurrences exist but fail the automatic
minimum. Sparse coverage is explicitly reported even when some windows match.
Each configured stock and each stored non-index symbol receives a coverage row.
Categories use current YAML memberships, not historical sector reconstruction;
symbols outside the current YAML remain searchable with no fabricated category.
Configured indexes/ETFs/benchmarks are excluded. Invalid YAML symbols are disclosed.

Counts do not establish profitability or predictive power. Overlapping occurrences
are not independent samples. No linked forward-outcome fields exist in this source,
so returns after a pattern are not attached and prospective validation is untouched.

Additional flags: `--config-dir`, `--history-store` (existing store only),
`--output-dir` (default `output/reports/patterns`). No writes occur outside the
selected report directory. Exit 0 indicates a completed query (including no match);
exit 2 indicates insufficient history or argparse validation errors; exit 1 means
configuration, cutoff or output failure. Source-integrity failures are explained
in diagnostic reports and yield insufficient history.

## Offline tests

```powershell
python -m pytest stock_scanner/tests/test_pattern_finder.py
```

Fixtures use the existing envelope creator and canonical store. Tests cover exact
patterns, wrong/intervening states, gaps, time/span boundaries, holidays and early
closes, repeats, counts, duplicates, integrity/conflicts, missing values, immutable
inputs, CLI dispatch, unique files, escaped HTML, and read-only SQLite access.
