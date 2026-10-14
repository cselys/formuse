# SectorRadar — Engineering Guide & Next-Step Plan

Architecture, verification status, operational runbook, and prioritized next steps

Prepared: 2026-10-11 | Project: C:\git\ai\Claude\SectorRadar

## 1. Purpose and operating principles

**Purpose.** SectorRadar scans U.S. equity themes using low-cost, near-real-time data and deterministic calculations. Its outputs include TOP UP, TOP DOWN, Broadest, Reversal, Recovery, Breadth Momentum, and ETF Divergence.

**Core principles**
- Theme is the primary analytical object.
- AI explains results; it does not calculate signals, rank themes, or generate buy/sell recommendations.
- Finnhub + SQLite are the data path; Streamlit reads persisted snapshots and does not run the collector loop.
- Keep calculations deterministic, simple, and interpretable. Do not add a composite score without a specific, validated need.
- Prefer production observations over speculative backend refactors.

## 2. Architecture and data flow

**Pipeline.** Finnhub quote requests → Collector → freshness/eligibility handling → SQLite snapshots → deterministic theme/breadth/signal calculations → Streamlit dashboard. AI is a downstream explanation layer only.

**Responsibilities**
- Collector: schedule requests, handle provider responses and rate limits, timestamp data, and persist snapshots.
- SQLite: durable snapshots used by the dashboard and historical calculations.
- Signal/calculation layer: deterministic eligibility, breadth, theme rankings, reversals/recovery, momentum, and ETF divergence.
- Streamlit: read stored data and render dashboard state; never host the continuous collector loop.
- AI explanation: summarize why a computed signal may matter without changing its value or rank.

**Operating commands**
- `python -m data.collector` — continuous collector mode.
- `python -m data.collector --once` — one collection cycle for debugging or controlled checks.
- `streamlit run app.py` — dashboard in a separate terminal.

## 3. Universe and schedule

**Latest reported universe.** 230 unique symbols: 209 stocks + 21 ETFs, across 33 themes. The reported build process deduplicates symbol assignments when constructing the universe.

**Reported schedule.** cycle_interval_seconds=300; batch_size=45; six batches for 230 symbols. The effective inter-request delay is derived from the schedule and rate-limit safety settings; a configured delay of zero does not necessarily mean requests have no delay.

**Important caveat.** Confirm the actual configuration loaded by the production collector matches the configuration used by the tests. Theme membership can overlap: symbol count and theme-assignment count are not the same thing.

## 4. Signal hierarchy and interpretation

**Primary signals.** TOP UP and TOP DOWN are the main directional theme signals.

**Confirmation.** Broadest is a breadth/participation confirmation signal, not an independent primary ranking.

**Auxiliary signals.** Breadth Momentum and ETF Divergence are more independent auxiliary signals, though not necessarily statistically independent.

**Overlapping signals.** Reversal and Recovery overlap conceptually and should not be treated as wholly independent evidence.

**Correlation caveat.** Some stocks belong to multiple themes. Signals across those themes can therefore share underlying constituents. A short, single-day independence audit does not establish multi-day regime independence.

## 5. Data timestamps and freshness

**MarketData.asof.** Use the Finnhub provider timestamp (`provider_timestamp`) to represent the quote's market-data time.

**MarketData.fetched_at / Last Update.** Represent fetch, persistence, or dashboard/render update time according to the current implementation. Do not label these as the provider quote time.

**RTH-only quote behavior.** The reported live check found Finnhub `/quote` timestamps freezing at 4:00 PM ET after regular trading hours. HTTP 200 alone does not prove that a quote is current after hours.

**Expected after-hours UI.** A quote may correctly display `Data as of: 4:00 PM ET` while `Last Update` continues to change as the collector/dashboard refreshes.

**Freshness eligibility.** Stale symbols such as BYDDY should be excluded from eligible calculations when freshness rules require it, rather than deleted from theme membership solely because one provider's quote is stale.

**Serial-cycle caveat.** A cycle fetches symbols serially. Per-symbol ages naturally vary across the cycle; do not use a naive mean `data_age` as the sole freshness threshold.

## 6. Rate limiting and scheduling

**Expected behavior.** The scheduler derives inter-request pacing and batch pauses from the cycle duration, universe size, configured provider rate limit, and safety factor.

**Production backoff.** The reported implementation prioritizes `Retry-After`, then `X-Ratelimit-Reset`, then a 60-second fallback, with state caching to suppress repeated waits for the same target. These details should be checked against the current source before relying on them operationally.

**What unit tests can establish.** Tests that mock `time.sleep` can verify that sleep calls are made and delay arguments are in expected ranges. They do not prove real elapsed request pacing.

**429 test caveat.** The reported regression test mocks `_RateLimitState.wait_after_429` to return zero. It therefore does not independently verify real backoff timing. Also, the fake client's `rate_limit()` was reported as a no-op, while unknown symbols trigger the fake 429 path; inspect the full fake transport before treating this as a faithful 429 recovery test.

**Operational rule.** Do not claim the real provider will never return 429 based only on unit tests. Validate the behavior in RTH using collector logs and observed response outcomes.

## 7. Test and audit status

**Reported test result.** `python -m pytest tests/ --tb=long -q` reported 169 passed, 0 failed, in 7.20 seconds. The user-provided audit says this result was reproduced across three runs.

**Fixture fix.** `FakeFinnhubClient.set_quotes()` replaces its quote dictionary. Correct test setup accumulates all symbol quotes into one dictionary and calls `set_quotes(quotes)` once.

**Universe expectation.** Tests were updated to exercise 230 symbols rather than the older 214-symbol universe.

**Legacy test name.** `test_collector_214_regression_no_burst_or_spin` still contains `214` in its name although the test body reportedly uses 230. This is cosmetic but may confuse maintainers.

**Test tracking blocker.** The reported `git ls-files --error-unmatch tests/test_finnhub_provider.py` returned exit code 1. Therefore that test file is not tracked by Git, and a normal tracked diff does not preserve the reported fix.

**Test status interpretation.** 169 passing tests are a useful local test milestone, not proof of live Finnhub behavior or reproducibility from a clean clone until the test file's repository/ignore status is resolved.

## 8. Git and change-control rules

Do not stage or commit unrelated files from `realtimesignals`, `webullrealcheck`, or `dailyscanner` without confirming repository boundaries and ownership.

Before any write operation, inspect the repository root, `git status --short --untracked-files=all`, `git diff --stat`, and `git diff --cached --stat`.

Check why the core test file is ignored or untracked with `git check-ignore -v tests/test_finnhub_provider.py` and `git ls-files --error-unmatch tests/test_finnhub_provider.py`.

Do not alter `.gitignore` or add files until the exact intended SectorRadar repository and desired tracking policy are clear.

Keep read-only audits separate from remediation tasks.

## 9. Recommended next steps

**Step 1 — Establish repository boundaries (read-only).** Run `git rev-parse --show-toplevel`, `git status --short --untracked-files=all`, `git diff --stat`, `git diff --cached --stat`, `git check-ignore -v tests/test_finnhub_provider.py`, and `git ls-files --error-unmatch tests/test_finnhub_provider.py`. Determine whether the reported unrelated files are in this repository or separate repositories.

**Step 2 — Make the test baseline reproducible.** After confirming repository ownership and ignore rules, decide whether `tests/test_finnhub_provider.py` should be tracked. Preserve unrelated changes. Do not claim a reproducible baseline from a clean checkout until the test file and its dependencies are available there.

**Step 3 — Add focused 429 tests only if coverage is missing.** In a separate, approved code-change task, test Retry-After, X-Ratelimit-Reset, fallback behavior, repeated 429s, bounded retry behavior, recovery, and result counters. Avoid mocking out the behavior the test is intended to verify. Use a fake clock or targeted mocks to make tests deterministic without sending network requests.

**Step 4 — Run the test suite.** Run `python -m pytest tests/ --tb=long -q` after the baseline is tracked and the working tree is understood. Record the exact command, final summary, commit/revision, and any relevant configuration.

**Step 5 — Run live RTH validation.** In one terminal run `python -m data.collector`; in another run `streamlit run app.py`. Observe multiple cycles during regular market hours. Do not run multiple collectors against the same database.

**Step 6 — Validate operational evidence.** Record cycle duration, symbols attempted/succeeded/failed/rate-limited, observed pacing, 429/backoff events, snapshot writes, quote timestamps, stale-symbol eligibility, and dashboard refresh behavior. Redact API keys and other secrets from logs.

**Step 7 — Validate after-hours semantics.** After RTH, confirm provider quote timestamps may remain at 4:00 PM ET while collector/dashboard update timestamps advance. Verify stale data is not treated as fresh merely because a new fetch occurred.

**Step 8 — Freeze a stable baseline.** Only after the Git baseline is reproducible and the RTH checks show no unresolved operational issue, decide whether to create a focused commit using the project's normal review process.

**Step 9 — Resume feature work.** Return to theme rankings and signal UX after data reliability is established. Keep the existing signal hierarchy and avoid composite scoring without evidence.

## 10. RTH validation checklist

Collector runs continuously without overlapping cycles.

The actual loaded universe size and deduplicated symbols match the expected configuration.

Cycle timing and request spacing are plausible under the configured provider rate limit.

429 events, if any, result in bounded and observable backoff rather than rapid retries.

Snapshot data is persisted to SQLite and read by Streamlit without the dashboard running a collector.

Provider `asof` and fetch/dashboard update timestamps remain semantically distinct.

Stale quotes are excluded from eligible calculations according to freshness rules.

`WHAT IS CHANGING?`, rankings, reversals, recovery, Breadth Momentum, and ETF Divergence update as new eligible data arrives.

After-hours provider timestamp freezing is displayed honestly.

Logs contain enough diagnostic information but no API keys or secrets.

## 11. Suggested prompt for the next Claude Code session

SectorRadar — RTH Readiness and Git Baseline

Project: C:\git\ai\Claude\SectorRadar

First perform a READ-ONLY inspection. Do not edit files, stage/commit changes, make network requests, or write to SQLite.

1. Establish the exact Git root and repository boundaries.
2. Explain why tests/test_finnhub_provider.py is not tracked and whether it is ignored.
3. Determine whether the reported 169-test suite is reproducible from tracked files.
4. Inspect existing tests for Retry-After, X-Ratelimit-Reset, fallback backoff, repeated 429s, bounded retries, and recovery. Distinguish real logic coverage from tests that mock the target behavior.
5. Inspect collector logging and identify the exact metrics needed for RTH validation: universe size, requests attempted, success/failure/429 counts, cycle duration, delays, snapshot persistence, and timestamp semantics.
6. Provide a prioritized plan with evidence and file/line references. Do not change any files.

After the read-only report is reviewed and approved, prepare a separate implementation plan. Keep the collector and Streamlit separated; do not add composite scoring or alter signal definitions without evidence.

## 12. Final status

**Confirmed from the supplied report.** The local test command reported 169 passing tests. The fixture setup was corrected to avoid replacing the entire quote dictionary repeatedly. The universe is reported as 230 unique symbols.

**Still to establish.** Tracked, clean-checkout reproducibility; faithful and independent 429 recovery coverage; and actual RTH collector/dashboard behavior.

**Go/no-go.** GO for read-only baseline cleanup and planned RTH observation. HOLD on new signal features until the Git baseline and live data behavior are verified.
