# ROADMAP.md

## V1 — Complete

The following V1 features are implemented and verified:

- Dashboard with 4 panels (TOP UP, TOP DOWN, REVERSALS, RECOVERIES)
- Breadth momentum table (Δ5m/Δ15m)
- ETF / basket divergence (informational only)
- Theme detail page (constituents, charts, ETF comparison, snapshot history)
- Market status badge (OPEN/PREMARKET/CLOSED/WEEKEND/HOLIDAY)
- Auto-refresh at configurable intervals
- Small-sample warning (⚠️ when valid < 5)
- Stale-data notice
- SQLite snapshot persistence
- 39 unit tests passing
- yfinance data pipeline verified
- All unit test suites pass

---

## V1.1 — Possible operational improvements

- Refresh optimization: cache TTL tuning, smarter refresh triggers
- Better data-quality monitoring: alert on sustained stale data
- Performance monitoring: track refresh latency, memory usage
- Logging configuration: structured logs, log rotation

## V2 — Possible analytical improvements

- Richer historical analysis: query SQLite snapshots for multi-session patterns
- Theme rotation: rotate which themes are in the active window
- Correlation: compute pairwise correlations between theme returns
- More sophisticated alerts: volume surge, volatility burst, divergence persistence
- Sentiment integration: combine with news/social sentiment data

## Future

- **Longer-term visions** (not commitments, not scheduled):
  - Real-time data feed integration (dedicated MD feed, not yfinance)
  - Automated pattern detection (e.g., "bullish breadth divergence over 3 sessions")
  - Portfolio integration (link to watchlists, execution systems)
  - Multi-exchange support (NYSE + NASDAQ + International)
  - User accounts / saved watchlists
  - Telegram / Slack / browser notifications for alerts
  - AI-generated thematic summaries (using the structured JSON output from V1)
  - Historical scenario analysis (what-if simulations based on SQLite data)

These future ideas are **not commitments** and are separated from current V1 functionality. They are captured for future consideration.

---

## Current project status

- **Version:** V1 / MVP
- **Status:** Feature complete
- **Tests:** 39 passing
- **Live yfinance pipeline:** verified
- **Dashboard:** verified (all features)
- **SQLite:** verified
- **Alerts:** verified
- **AI JSON export:** verified

The immediate next step after V1 is to decide on V1.1 operational improvements or move to V2 analytical improvements. The codebase is structured so either path can be taken without disrupting the existing V1 functionality.