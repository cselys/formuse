# OPERATIONS.md

## Start

```bash
pip install -r requirements.txt
streamlit run app.py
```

The app will open in your browser at `http://localhost:8599` (or the next available port).

## Tests

```bash
python -m pytest tests/ -q
```

39 tests pass, covering price calculations, breadth classification, reversal/ recovery state, multi-theme orchestration, ranking, composite scores, and snapshot persistence. All tests use synthetic data — no network required.

## Configuration changes

### Editing themes

Edit `config/themes.yaml` — add/remove tickers or ETF mappings. The dashboard auto-detects changes on refresh (no Python restart needed).

### Editing thresholds

Use the sidebar sliders for:
- Up/flat threshold (%)
- Strong move threshold (%)
- Reversal threshold (pp)
- Refresh interval (30s/60s/120s/300s)
- Data interval (5m/1m)
- Panel visibility toggles

All settings are saved to the runtime session and persist within a single Streamlit run.

### Adding a new theme

1. Edit `config/themes.yaml` — add a new top-level key with `tickers` list and optional `etf` list
2. Run `streamlit run app.py` — the new theme appears in all panels immediately
3. No Python code changes required

## Troubleshooting

### yfinance unavailable

- Check internet connectivity
- The app will show a warning and disabled panels if data cannot be fetched
- The "Market Status" will show `HOLIDAY` or `WEEKEND` if no session data available
- Cache is reused for up to 55 seconds (configurable via `cache_ttl_seconds`), so transient failures resolve quickly

### Missing quotes / halted stocks

- Invalid symbols are marked with `issue` in the `StockSnapshot`
- The theme panel shows `⚠️ small` or `✖` for invalid tickers
- Missing symbols do NOT break the calculation — only configured tickers with valid data contribute to percentages

### Stale data

- yfinance data is delayed ~15 minutes (not tick-level real-time)
- The header shows `Data as of HH:MM ET` and a "delayed" notice when the data age exceeds 20 minutes (configurable via `stale_warn_minutes`)
- The app does not pretend real-time data; the timestamp is always shown

### Market closed

- After 16:00 ET, the market status becomes `CLOSED`
- Final session data remains available; no new data is appended
- The app displays `Market closed — showing last session` or `Market closed — no session data` depending on whether prior session data exists

### Streamlit startup problems

- Ensure `streamlit` is installed: `pip install streamlit`
- Ensure `requirements.txt` packages are installed
- The first run may take 30–60 seconds to fetch initial data
- If the app appears blank, check the browser console for JavaScript errors

### API / rate-limit issues

- yfinance batches requests (one download per dataset, not per stock)
- Retry with backoff is implemented (3 attempts, 2s * attempt)
- If you hit rate limits, increase `retry_backoff_seconds` in `config/settings.yaml`

## Market-open verification checklist

### Before open

- [ ] Application starts successfully
- [ ] Market status shows `PRE-MARKET`
- [ ] Timestamp is visible and advances
- [ ] No fake populated market metrics (all values are `—` or `0` until data arrives)
- [ ] Configuration is loaded from `config/themes.yaml` and `config/settings.yaml`

### At/after 9:30 ET

- [ ] Market status becomes `OPEN`
- [ ] Current prices advance bar by bar
- [ ] Theme metrics populate (TOP UP, TOP DOWN panels show themes)
- [ ] Rankings populate (TOP UP, TOP DOWN, REVERSALS, RECOVERIES)
- [ ] Breadth Momentum table shows `Up % Now`, `5m Ago`, `15m Ago`
- [ ] ETF divergence section may show data (or `—` if no ETF mappings)
- [ ] Charts render (return from open, breadth, avg vs median)
- [ ] Alerts section may show initial alerts (breadth breakout/collapse, strong reversal/recovery)
- [ ] `"Data as of"` timestamp advances

### During session

- [ ] Monitor missing/stale data (header notice if age > 20 min)
- [ ] Monitor refresh latency (auto-refresh every N seconds as configured)
- [ ] Monitor errors in the browser console (F12)
- [ ] Confirm SQLite snapshots are being written (check `data/sector_radar.db`)
- [ ] Dashboard remains responsive (no full-page reloads)

### After close

- [ ] Market status becomes `CLOSED`
- [ ] Final session data remains available (no errors)
- [ ] No continuous polling errors after 16:00 ET
- [ ] SQLite snapshots exist for the session date

## History

- **V1 (MVP)**: All features described in this document are implemented and tested.
- **V1.1 (possible)**: Refresh optimization, better data-quality monitoring, additional logging.
- **V2 (possible)**: Richer historical analysis, theme rotation, correlation, more sophisticated alerts.