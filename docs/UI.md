# UI.md

## Dashboard layout (spec 18)

The dashboard is the main view the user sees on startup. It is designed to be scannable in under 10 seconds, answering these six questions:

1. Which themes are going up? → **TOP UP** panel
2. Which themes are going down? → **TOP DOWN** panel
3. Are the moves broad or concentrated? → **Avg vs Median** in the full table + Up%/Down% side by side
4. Which themes are reversing? → **REVERSALS** panel
5. Which themes are recovering? → **RECOVERIES** panel
6. What changed in the last 5–15 minutes? → **BREADTH MOMENTUM** table

### Header

- `📡 SECTOR RADAR` (title)
- **Market**: US Equities
- **Data**: yfinance (delayed — not tick data)
- **Last Update**: `HH:MM:SS ET` (wall clock time of the data fetch)
- **Data as of**: `HH:MM:SS ET` (the `md.asof` timestamp)
- **Market Status**: badge (🟢 OPEN / 🟠 PRE-MARKET / ⚪ CLOSED / ⚪ WEEKEND / 🔴 HOLIDAY)
- **Early close**: `⚠️ Early close today (calendar)` if applicable
- **Window note**: `⏱️ First-N-min scanner window: HH:MM–HH:MM ET` or `ℹ️ First-N-min scanner window ended at HH:MM ET — extended-session view (metrics stay live)`
- **Delayed notice** (when market OPEN and data age > 20 min): `ℹ️ yfinance free data is delayed (~15 min) and not tick-by-tick. The 'Data as of' timestamp shows the true data time.`
- **Alerts**: st.warning boxes at the top (breadth breakout/collapse, strong reversal/recovery, Top-3 entry/exit)

### Panels (2×2 grid)

#### TOP UP (col 1, top)

- Sorted by `average_return` descending
- Columns: Theme, Avg %, vs Open, Up %, Strong Up %, Stocks, State
- `Up %` and `Strong Up %` displayed as plain percentages (e.g., `82%`)
- `vs Open` displayed as signed percentage (e.g., `+1.2%`)
- `Stocks` displayed as `"{valid}/{total}"` with `⚠️ small` if `valid < 5` and `show_small_sample_warning=True`
- `State` displayed as colored label (TRENDING_UP → green, etc.)
- Renders via `_panel(rows, spec, empty_note, warn_small)`

#### TOP DOWN (col 2, top)

- Sorted by `average_return` ascending (most negative first)
- Same column format as TOP UP, but `Down %` and `Strong Down %` instead of Up/Strong Up
- Same empty state handling

#### REVERSALS (col 3, bottom left)

- Sorted by `reversal_from_high` ascending (most giveback first)
- Filter: `reversal_from_high < -abs(threshold)` (strict)
- Columns: Theme, Intraday Peak, Current, Giveback, Breadth (up %), State
- `Giveback` displayed as signed pp (e.g., `-2.5 pp`)
- `Intraday Peak` and `Current` as signed percentages

#### RECOVERIES (col 4, bottom right)

- Sorted by `recovery_from_low` descending (largest recovery first)
- Filter: `recovery_from_low > abs(threshold)` (strict)
- Columns: Theme, Intraday Low, Current, Recovery, Breadth (up %), State
- `Recovery` displayed as signed pp (e.g., `+2.5 pp`)
- `Intraday Low` and `Current` as signed percentages

### Breadth Momentum (below the panels)

- Table sorted by `Δ15m` descending (largest expansion first)
- Columns: Theme, Up % Now, 5m Ago, 15m Ago, Δ 5m, Δ 15m (pp)
- `Up % Now`, `5m Ago`, `15m Ago` as plain percentages (e.g., `82%`)
- `Δ 5m`, `Δ 15m` as signed pp (e.g., `+3.2 pp` or `-5.1 pp`)
- `Up % Now` colored: green if > 0.05, red if < -0.05, muted otherwise
- `Δ 5m`, `Δ 15m` colored: green if positive, red if negative, muted otherwise

### ETF / Basket Divergence (sidebar-toggleable)

- Shown when `show["etf"]` is True and `etf_rows` is non-empty
- Table: Theme, ETF, ETF Return, Basket Return, Divergence (pp)
- ETF Return / Basket Return / Divergence as signed percentages (e.g., `+1.8%`, `-0.5 pp`)
- Caption: *"Informational only — NOT a trading recommendation"*

### Composite score expander (if enabled)

- Table: Theme, Score (0–100, integer)
- Sorted by score descending
- Caption: *"Min-max normalized blend of breadth, average and median return and volume. For reference only; the raw panels above are the source of truth."*

### All themes table (expandable)

- Columns: Theme, Stocks, Avg %, Median %, vs Open, Up %, Down %, Strong Up %, Strong Down %, High %, Giveback, Low %, Recovery, Δ5m, Δ15m, State
- `Stocks`: `"{valid}/{total}"` + `⚠️ small` if applicable
- `Avg %`, `Median %`, `vs Open`: signed percentages (`fmt_signed`)
- `Up %`, `Down %`, `Strong Up %`, `Strong Down %`: plain percentages (`fmt_plain`)
- `High %`, `Low %`: signed percentages
- `Giveback`, `Recovery`, `Δ5m`, `Δ15m`: signed pp (`fmt_signed(v, 1, " pp")`)
- `State`: colored label
- Coloring: signed cols → green/red/muted via `_signed_color`; State → colored label; Up/Down/Strong%/Strong%/Stocks → `_plain_color`

### Theme detail page (sidebar selectable)

- **Key metric cards** (6 × `st.metric`):
  - Current Return + delta vs open
  - Median Return
  - Up / Down + up/down counts + delta
  - Strong Up / Strong Down
  - Intraday High + giveback pp delta
  - Intraday Low + recovery pp delta
- **Constituent table**: sortable by Return (vs close), Change from open, Volume, Distance from high
  - Columns: Ticker, Price, vs Close, vs Open, Dist High, Volume, State, Issue
  - Price: `$x,xxx.xx` format
  - vs Close / vs Open: signed percentages
  - Dist High: signed percentage
  - Volume: `x,xxx` format
  - State: colored label (UP → green, DOWN → red, FLAT → muted)
  - Issue: muted text
- **3 Plotly charts**:
  - Return from open (line, HL colleeved, HL at 0)
  - Breadth (up% and down% lines, HL at 50)
  - Average vs median (two lines: avg in green, median in #d97706)
- **ETF comparison table** (if `m.etf` is non-empty):
  - ETF, ETF Return, Basket Return, Divergence (pp)
  - Caption: *"The ETF is a market-capitalization-weighted proxy and is NOT one of the constituents. Divergence = ETF − basket. Informational only."*
- **Session snapshot history** (SQLite expandable):
  - `store.load_sector_history(m.theme, session_date)` → table of recent snapshots
  - Columns: timestamp, up_percent, down_percent, average_return, median_return, average_change_from_open, intraday_high, intraday_low, breadth, state

### State badges (throughout the UI)

- `TRENDING_UP` → 🟢 TRENDING UP (green)
- `TRENDING_DOWN` → 🔴 TRENDING DOWN (red)
- `REVERSING_DOWN` → 🟠 REVERSING DOWN (orange)
- `RECOVERING_UP` → 🔵 RECOVERING UP (blue)
- `MIXED` → ⚪ MIXED (gray)

### Streamlit-specific notes

- `st.dataframe(styler)` with `use_container_width=True` is the standard way to render tables
- `Styler.format()` is **not** applied by Streamlit (raw values shown); pre-format strings are used instead
- `Styler.map(font_color)` IS supported and used for row/column coloring
- `st.set_page_config()` must be the first Streamlit command in the script
- The sidebar persists across auto-refresh ticks via `st.session_state`