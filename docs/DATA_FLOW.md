# DATA_FLOW.md

## Complete data path

```text
Market data (yfinance)
    │
    │  fetch_session(symbols, interval, start, end)
    │     │
    │     ├── get_intraday_prices(symbols, interval)     │
    │     │   └─ batched yf.download(start, end, interval, prepost=False) │
    │     │   └─ _split_by_symbol(df) │
    │     │       │ columns: (field, ticker) │
    │     │       └─ sub = df.xs(sym, axis=1, level=1) │
    │     │       └─ keep [open,high,low,close,volume] │
    │     │       └─ sub.columns = lower case │
    │     │       └─ sub = sub.dropna(subset=["close"]) │
    │     │       └─ tz-convert: if tz-aware UTC -> ET; if tz-naive (daily) → stay as-is │
    │     │       └─ out[sym] = sub │
    │     │
    │     └─ get_daily_reference_prices(symbols) │
    │         └─ batched yf.download(symbols, period='15d', interval='1d') │
    │             └─ _split_by_symbol(df) │
    │                 └─ idx = frame.index │
    │                 └─ if idx.tz is None: │
    │                 │   frame.index = pd.to_datetime(idx)  # yfinance daily is already naive │
    │                 └─ else: │
    │                 │   frame.index = pd.to_datetime(idx, utc=True).tz_convert(ET).tz_localize(None) │
    │                 └─ out[sym] = frame.sort_index() │
    │
    └─ MarketData(source, interval, fetched_at UTC, asof, bars, daily, failed)
                │
                │  build_all_stock_metrics(md, settings, now, market_is_open)
                │     │
                │     ├── for each sym in md.bars:
                │     │   ├── daily = md.daily.get(sym)
                │     │   ├── prev_close, today_open = daily_reference(daily, session_date)
                │     │   ├── build_stock_metrics(sym, bars, prev_close, today_open,
                │     │   │       asof=asof, now_ts=now, market_is_open=market_is_open)
                │     │   └─ store in out[sym]
                │     │
                │     └─ for each sym in md.failed:
                │         │   if sym in out and out[sym].is_valid:
                │     │   │       out[sym].issue = out[sym].issue + " + " + md.failed[sym]
                │     │   │   continue
                │         └─ out[sym] = StockSnapshot(..., issue=md.failed[sym], ...)
                │
                └─ returns dict[str, StockSnapshot]

│
│▼ engine: price_engine
│   (pure functions, no I/O)
│   outputs: Dict[str, StockSnapshot]
│   │
│▼ engine: breadth_engine
│   └─ compute_breadth(stocks, settings, total=None)
│        │
│        ├── flat = get_setting(settings, "classification.flat_threshold", 0.10)
│        ├── strong = get_setting(settings, "classification.strong_move_threshold", 1.0)
│        ├── total = len(stocks) if total is None else total
│        ├── valid = [s for s in stocks if s.is_valid and s.change_vs_previous_close is not None]
│        ├── n = len(valid)
│        ├── changes = np.array([s.change_vs_previous_close for s in valid], dtype=float)
│        ├── up = int((changes > flat).sum()) if n else 0
│        ├── down = int((changes < -flat).sum()) if n else 0
│        ├── strong_up = int((changes > strong).sum()) if n else 0
│        ├── strong_down = int((changes < -strong).sum()) if n else 0
│        ├── opens = np.array([s.change_vs_open for s in valid if s.change_vs_open is not None], dtype=float)
│        ├── numeric return: up% = n/valid*100, down%, flat%, avg return, median return,
│        ├── avg_change_from_open, median_change_from_open, total_volume
│        └─ returns Dict
│
│▼ engine: reversal_engine
│   └─ theme_return_series(bars_map, prev_close_map, symbols, flat_threshold)
│        │   │
│        │   ├── rets = {sym: bars["close"]/pc*100 - 100}
│        │   ├── r = pd.DataFrame(rets).sort_index()
│        │   ├── valid_count = r.notna().sum(axis=1)
│        │   ├── out["avg_return"] = r.mean(axis=1)
│        │   ├── out["median_return"] = r.median(axis=1)
│        │   ├── out["up_percent"] = np.where(valid_count>0, (r > flat).sum(axis=1)/valid_count*100, np.nan)
│        │   ├── out["down_percent"] = np.where(valid_count>0, (r < -flat).sum(axis=1)/valid_count*100, np.nan)
│        │   └─ out = out[out["avg_return"].notna()].reset_index()
│        │
│   └─ analyze_history(history, settings)
│        │
│        ├── min_bars = get_setting(settings, "state.min_history_bars", 3)
│        ├── high = history["avg_return"].max(); low = history["avg_return"].min()
│        ├── current = history["avg_return"].iloc[-1]
│        ├── reversal_from_high = current - high
│        ├── recovery_from_low = current - low
│        ├── breadth_now = history["up_percent"].iloc[-1]
│        ├── has_history = len(idx) >= min_bars
│        ├── if has_history:
│        │     ├── b5 = _up_at_offset(history, 5)
│        │     ├── b15 = _up_at_offset(history, 15)
│        │     └─ breadth_5m_ago, breadth_change_5m, breadth_15m_ago, breadth_change_15m
│        └─ returns Dict{intraday_high, intraday_low, reversal_from_high, recovery_from_low,
│                       breadth_now, breadth_5m_ago, breadth_15m_ago, breadth_change_5m, breadth_change_15m, has_history}
│
│▼ engine: sector_engine
│   └─ build_theme_metrics(theme, theme_cfg, stock_metrics, md, settings)
│        │
│        ├── tickers = theme_cfg["tickers"]; etfs = theme_cfg.get("etf", [])
│        ├── stocks = [stock_metrics[t] for t in tickers if t in stock_metrics]
│        ├── unknown = [t for t in tickers if t not in stock_metrics]  // log warning
│        ├── breadth = compute_breadth(stocks, settings, total=len(tickers))
│        ├── valid_syms = [s.symbol for s in stocks if s.is_valid and s.change_vs_previous_close is not None]
│        ├── prev_close_map = {s.symbol: s.previous_close for s in stocks if s.previous_close is not None}
│        ├── flat = get_setting(settings, "classification.flat_threshold", 0.10)
│        ├── history = theme_return_series(md.bars, prev_close_map, valid_syms, flat)
│        ├── hist = analyze_history(history, settings)
│        ├── state = classify_state(
│        │       avg_return=breadth["average_return"],
│        │       avg_change_from_open=breadth["average_change_from_open"],
│        │       up_percent=breadth["up_percent"],
│        │       down_percent=breadth["down_percent"],
│        │       reversal_from_high=hist["reversal_from_high"],
│        │       recovery_from_low=hist["recovery_from_low"],
│        │       settings=settings, has_history=hist["has_history"])
│        ├── etf_rows: for etf in etfs:
│        │   │   sm = stock_metrics.get(etf)
│        │   │   if sm is None or not sm.is_valid or sm.change_vs_previous_close is None:
│        │   │   │   etf_rows.append(ETFComparison(etf=etf, etf_return=None, basket_return=breadth["average_return"], divergence=None))
│        │   │   else:
│        │   │   │   etf_ret = sm.change_vs_previous_close
│        │   │   │   etf_rows.append(ETFComparison(etf=etf, etf_return=etf_ret,
│        │   │   │           basket_return=breadth["average_return"], divergence=etf_ret - breadth["average_return"]))
│        │   │
│        │   └─ returns ThemeMetrics(theme, timestamp, total_stocks, valid_stocks, missing_stocks,
│        │        up/down/flat%, strong up/down%, avg/median return, avg/med change_from_open, total_vol,
│        │        intraday_high/low, reversal_from_high, recovery_from_low, breadth_now/5m/15m, state, small_sample, etf)
│        │
│        └─ returns List[ThemeMetrics]

│
│▼ engine: ranking_engine
│   └─ build_rankings(metrics, settings, min_theme_size, top_n)
│        │   ├── sized = [m for m in metrics if m.valid_stocks >= min_theme_size]
│        │   ├── top_up(sized, top_n)         → avg_return descending
│        │   ├── top_down(sized, top_n)         → avg_return ascending
│        │   ├── broadest_up(sized, top_n)      → up_percent descending
│        │   ├── broadest_down(sized, top_n)      → down_percent descending
│        │   ├── biggest_reversals(sized, top_n, threshold) → reversal_from_high ascending (strict < -threshold)
│        │   ├── biggest_recoveries(sized, top_n, threshold) → recovery_from_low descending (strict > threshold)
│        │   └─ returns dict{"top_up", "top_down", "broadest_up", "broadest_down", "reversals", "recoveries"}
│        │
│   └─ composite_scores(metrics, weights)
│        │   ├── rows = [m for m in metrics if m.valid_stocks > 0]
│        │   ├── def norm(values): arr = np.array(values, float); lo,hi = nanmin/nanmax; return (arr-lo)/(hi-lo)*100 if hi!=lo else 50
│        │   ├── breadth = norm([x.up_percent for x in rows])
│        │   ├── avg = norm([x.average_return for x in rows])
│        │   ├── med = norm([x.median_return for x in rows])
│        │   ├── vol = norm([log10(max(x.total_volume,0)+1) for x in rows])
│        │   ├── w = weights or {breadth:0.40, avg_return:0.30, median_return:0.20, volume:0.10}
│        │   ├── total = w_breadth + w_avg + w_med + w_vol (or 1.0)
│        │   └─ returns {theme: round((w_b*breadth[i] + w_a*avg[i] + w_m*med[i] + w_v*vol[i])/total, 1)}
│        │
│▼ engine: alerts.py
│   └─ detect_alerts(current, previous_top3, settings)
│        │
│        ├── thr5 = get_setting(settings, "alerts.breadth_change_5m", 15.0)
│        ├── thr15 = get_setting(settings, "alerts.breadth_change_15m", 20.0)
│        ├── str_rev = get_setting(settings, "alerts.strong_reversal_pp", 2.0)
│        ├── str_rec = get_setting(settings, "alerts.strong_recovery_pp", 2.0)
│        │
│        ├── for m in current:
│        │   ├── b5, b15 = m.breadth_change_5m, m.breadth_change_15m
│        │   ├── if thr5 and b5 >= thr5: Alert("Breadth Breakout", ...)
│        │   ├── if thr5 and b5 <= -thr5: Alert("Breadth Collapse", ...)
│        │   ├── if thr15 and b15 >= thr15: Alert("Breadth Breakout", ...)
│        │   ├── if thr15 and b15 <= -thr15: Alert("Breadth Collapse", ...)
│        │   ├── if rev_from_high <= -str_rev and up% < 50: Alert("Strong Reversal", ...)
│        │   ├── if rec_from_low >= str_rec: Alert("Strong Recovery", ...)
│        │
│        ├── cur_top3 = top3_by_return(current)
│        ├── if prev_top3:
│        │   ├── for t in cur_top3: if t not in prev_top3: Alert("Top 3 Entry", ...)
│        │   ├── for t in prev_top3: if t not in cur_top3: Alert("Top 3 Exit", ...)
│        └─ returns List[Alert]

│
│▼ SQLite (data/cache.py)
│   └─ SnapshotStore
│      ├── save_snapshots(session_date, theme_metrics, stock_snapshots)
│        │   ├── INSERT OR REPLACE sector_snapshots(16 cols)
│        │   ├── INSERT OR REPLACE stock_snapshots(12 cols)
│        │   └─ indexes on (theme, session_date) and (symbol, session_date)
│        │
│        └─ load_sector_history(theme, session_date) → pd.DataFrame
│            └─ load_stock_history(symbol, session_date) → pd.DataFrame
│            └─ recent_sessions(limit) → List[str]
│
│▼ Streamlit UI (ui/dashboard.py)
│   │
││   └─ render_dashboard(ctx)
│       │
│       ├── _render_header(ctx)                        status badge + last update + data as of
│       │   │   └─ _STATUS_BADGES  (emoji only, no HTML spans)
│       │   └─ _render_alerts(alerts)                 st.warning for each
│       │
│       ├── 4 panels (TOP UP / TOP DOWN / REVERSALS / RECOVERIES)
│       │   │   └─ _panel(rows, spec, empty_note, warn_small)
│       │   │       ├── display_cols + numeric_cols built from ThemeMetrics fields
│       │   │       └─ sty = dfd.style.hide(axis="index")
│       │   │       └─ _color_map(sty, dfd, dfn, col, color_fn) → sty.map(lambda v,i: color_fn(num[i]), subset=[col])
│       │   │
│       ├── breadth momentum table
│       │   │   └─ display = {Theme, Up% Now, 5m Ago, 15m Ago, Δ5m, Δ15m}
│       │   │   └─ numeric = {5m Ago, 15m Ago, Up% Now, Δ5m, Δ15m}
│       │   │   └─ sty = dfd.style → _color_map for plain + signed colors
│       │   │
│       ├── ETF divergence table (if enabled)
│       │   │   └─ display = {Theme, ETF, ETF Return, Basket Return, Divergence}
│       │   │   └─ numeric = {ETF Return, Basket Return, Divergence}
│       │   │   └─ _color_map for all three
│       │   │
│       ├── composite score expander (if enabled)
│       │   │   └─ cdf = pd.DataFrame({Theme, Score{f{0.0f}}} → desc sort
│       │   │
│       ├── all themes expandable table
│       │   │   └─ display + numeric built from ThemeMetrics fields
│       │   │   └─ sty = dfd.style; _color_map for signed cols; _color_map for plain cols;
│       │   │       _color_map for state; _plain_color for Stocks/Up%/Down%/Strong%
│       │   │
│       └─ theme detail page
│           │   │   └─ render_theme_detail(ctx)
│           │       │   └─ key metric cards (6 × st.metric)
│           │       │   ├── constituent table (sortable by return/v/o/dh/volume/state)
│           │       │   ├── 3 Plotly charts: return from open, breadth, avg vs median
│           │       │   ├── ETF comparison table (if m.etf)
│           │       │   └─ session snapshot history from SQLite (store.load_sector_history)
│           │       │
│□ Auto-refresh (st.fragment run_every=Ns)
│   │   └─ when enabled, ctx_and_render() re-fetches data + re-renders
│   │   └─ else: "Refresh now" button
│
## Refresh behavior

- **Market OPEN**: re-download at most every `cache_ttl_seconds` (default 55s)
- **Market CLOSED/HOLIDAY/WEEKEND**: data is final; re-download at most hourly (3600s)
- **PRE-MARKET**: re-download at most every 10 minutes (600s)
- `fetch_session()` respects `expect_intraday=False` when status == PREMARKET, suppressing the "no intraday bars" failure flag
- The `now_et()` timestamp and `md.asof` (max bar time) are stored in `st.session_state["md_cache"]` as `(md, fetched_at_et)`
- Data age is checked: if market is OPEN and `age_min > stale_warn_minutes` (default 20), the header shows a "delayed" notice
- On first load, if no bars exist (pre-market), `asof` is None and the UI displays "no session data yet"