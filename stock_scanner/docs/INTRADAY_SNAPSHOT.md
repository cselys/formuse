# Isolated intraday snapshot

From `dailyscanner`:

```powershell
python -m stock_scanner.intraday_snapshot
```

Explicit configuration and output root:

```powershell
python -m stock_scanner.intraday_snapshot --config-dir config --output-root output --max-age-seconds 300
```

This independent module does not change the existing scanner CLI or schedule.
It selects `./config/universe.yaml` when present, otherwise the package's
`config/universe.yaml`. The repository-root configuration is the full universe;
the package configuration is a smaller sample. All categories, constituent
symbols, benchmarks, explicit ETFs, and configured sector indexes are considered.
Invalid entries are reported separately, never converted to guessed tickers.
In particular the main YAML currently contains a literal boolean `true`.

The actual configured sector indexes are XLK, XLF, XLE, XLV, XLI, XLY, XLP,
XLU, XLC, XLRE and XLB. Category benchmarks do not become sector indexes.

The terminal and HTML contain these six rankings:

1. TOP 10 STOCKS UP
2. TOP 10 STOCKS DOWN
3. TOP 3 SECTORS UP — STOCK BREADTH
4. TOP 3 SECTORS DOWN — STOCK BREADTH
5. TOP 3 SECTOR INDEXES UP
6. TOP 3 SECTOR INDEXES DOWN

Only strictly positive/negative changes enter the corresponding price rankings.
Fewer than ten/three rows are expected when fewer instruments qualify.
Price ties use alphabetical symbol order. Breadth reuses the existing
`compute_sector_breadth` formula: advancing/declining count divided by eligible
stock count, including flat stocks in the denominator. Ties use directional
count, then average change (descending for up, ascending for down), then sector
name. Symbols are deduplicated globally for stock/index rankings and within
each category for breadth, while preserving membership in different categories.
Configured benchmarks, ETFs, index-typed categories and provider-classified
ETFs/indexes are excluded from individual-stock rankings and breadth.
Category coverage and up/down/flat counts are shown, including empty categories.

## Quote policy and limitations

Yahoo Finance is the existing project's data source. The new transport uses its
quote-only `/v7/finance/quote` endpoint, also used by
[yfinance's quote implementation](https://github.com/ranaroussi/yfinance/blob/main/yfinance/scrapers/quote.py).
It does not use `history`, `download` or `fast_info` (which can retrieve bars).
Authentication cookies and crumbs remain in memory; there is no persistent
provider cache. Requests use batches of 50, a one-second inter-batch delay,
three attempts with exponential backoff, and a 15-second request timeout.
Each failed batch or omitted symbol is disclosed; remaining batches continue.
The endpoint is unofficial and may reject authentication or rate-limit access.
Authentication accepts non-JSON responses (`Accept: */*`): the cookie endpoint
can return HTML with HTTP 404, while the crumb endpoint returns plain text.
Requiring JSON at authentication can cause HTTP 406 before any quotes are fetched.
HTTP failures identify the status code and cookie/crumb/quote stage, without
exposing authentication crumbs, cookies or request URLs.

Regular-session change is `(regularMarketPrice / regularMarketPreviousClose - 1)
* 100`. These are executed-price fields, never bid/ask or provider percentages.
An accepted quote requires USD, the US Eastern exchange timezone, a recognized
instrument type, provider REGULAR session state, positive finite prices, and
a trade timestamp from the current regular session no more than 300 seconds old
by default. Freshness is checked after all requests complete, so older early
batches may be excluded. NYSE calendar holidays and early closes are respected.
Timestamps and source labels are disclosed. Yahoo may supply delayed data;
the timestamp check is not a guarantee of real-time consolidated trade coverage.
The previous-close field is trusted as the provider's regular-session reference;
there is no independent corporate-action verification or bar fallback.

Premarket, after-hours and closed-session reports explicitly identify the session
and exclude all prices. This first version does not support extended-hours
comparisons because a sufficiently reliable reference is not established.
Missing metadata or stale/invalid/non-comparable prices are unavailable, never flat.

Only rendered HTML is saved, under `<output-root>/intraday_reports/`, using an
Eastern timestamp with microseconds, a random suffix and exclusive creation.
There are no raw snapshots, JSON/CSV observations, database, report index,
watchlist writes or daily/weekly cache writes. Each run starts independently.
The existing breadth helper is imported read-only; no scanner instance or scan
pipeline is invoked. No scoring, classification, regime, volume or V1.3 frozen
rules are changed. No order execution is connected.

Exit codes: 0 for a report with at least one accepted quote (partial failures
allowed); 2 for an HTML diagnostic report with no accepted quotes; 1 for a
configuration/output error. CLI argument errors also use argparse exit code 2.

## Offline regression tests

```powershell
python -m pytest stock_scanner/tests/test_intraday_snapshot.py
```

Tests use mocked quote responses, including the full real YAML universe.
They cover reference prices, breadth, ties, ETFs, configured indexes, sessions,
freshness, partial failures, transport retries, unique output, escaping and
non-interference. Mocked tests are not live provider verification.
